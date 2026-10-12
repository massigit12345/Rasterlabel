"""rasterlabel.model_vs_corrected

The map a model made against the map a person corrected in Correct: how far
the model was from the corrected map, class by class. The corrected map is
the reference, so the model's numbers are its producer's and user's
accuracy, its IoU and F1, the quantity and the allocation disagreement of
Pontius and Millones (2011), and the net ground of every FROM -> TO
transition, read from the pixel values. Kappa is never reported for the
model (Pontius and Millones 2011; Foody 2020); only between people.

On which ground:

- whole: every pixel both maps hold. Ground nobody looked at counts as
  right, so it is an upper bound;
- swept: the pixels a stroke of Correct went over, from the reviewed
  record beside the copy (<map>_corrected_reviewed.tif), and the pixels
  marked as changed, which also covers the strokes made before that record
  existed. The strokes go where the model was wrong, so it is a lower bound;
- polygons: inside the polygons of a layer, one matrix per polygon as well,
  so that with five or more polygons a bootstrap over polygons gives an
  interval. As good as the way the polygons were chosen.

Beside it, if asked, the same numbers for two people: another person's
correction of the same map, on the same pixels (with kappa, as an agreement
statistic), or the agreement report of an annotation campaign, which is on
other pixels and is matched class by class by name.

The reviewed record is kept by ReviewedHook, one of the hooks of Correct
(measure.CORRECT_HOOKS): each stroke written ORs its footprint into the
record, through a handle opened for that stroke alone (the way Correct
writes the copy), and an undo puts the window back. A correction made
before the record existed gets one at its first stroke, and the manifest
says from which stroke on it is complete ("reviewed_since"); opening such a
correction changes nothing.

GDAL, OGR and numpy only, no widget and no QGIS layer:

    mvc_compare(recipe, progress)     the strips, the matrices, the map
    mvc_write(result, folder, ...)    the tables and summary.json
    mvc_report(recipe, ...)           the two in a report folder of its own
    mvc_read_people(path)             an agreement report, read back
    mvc_counts(...)                   the numbers the setup window shows
"""
import math
import os

from datetime import datetime

import numpy as np
from osgeo import gdal, ogr, osr

from .constants import (BOOTSTRAP_LEVEL, BOOTSTRAP_MIN_FRAMES, BOOTSTRAP_N,
                        BOOTSTRAP_SEED, BUILD, CORRECTION_MANIFEST,
                        REPORT_SUMMARY, REVIEWED_BAND_NAME,
                        REVIEWED_MEANING, STRIP_ROWS, VERSION)
from .naming import csv_untext_row, long_path
from .errors import log
from .agreement import (cm_bootstrap, cm_from_pairs, cm_accumulate,
                        cm_metrics, cm_name, cm_pair_dtype, cm_pair_values,
                        cm_stat_values, cm_wide_rows)
from .reports import (report_abandon, report_artifact_name, report_csv,
                      report_finish, report_folder, report_folder_guess,
                      report_header, report_headline, report_inputs,
                      report_json, report_open_problem, report_read,
                      report_utc)
from .rasters import build_changes, open_raster, write_window
from .report_rasters import rr_finish, rr_open, rr_pair_entries
from .correction import REVIEWED_COLOUR, reviewed_path_of, undone_of
from .compare import cmp_burn, cmp_target

MVC_KIND = "model_vs_corrected"
MVC_SCOPES = ("whole", "swept", "polygons")
MVC_SCOPE_WORDS = {"whole": "whole map", "swept": "ground swept",
                   "polygons": "inside the polygons"}
MVC_NOTES = {
    "whole": "whole map: ground nobody looked at counts as right, so the "
             "model's accuracy here is an upper bound",
    "swept": "ground the strokes swept: strokes go where the model was "
             "wrong, so this is a purposive sample and the model's accuracy "
             "here is a lower bound",
    "polygons": "inside the polygons: as good as the way the polygons were "
                "chosen; only polygons drawn by a probability design and "
                "swept whole support an estimate for the map",
}
MVC_REFERENCE_NOTE = "reference = the corrected map (rows: model, columns: " \
                     "corrected, as in Olofsson et al. 2014)"
MVC_KAPPA_NOTE = ("no kappa for the model: it is no measure of a map's "
                  "accuracy (Pontius and Millones 2011; Foody 2020); kappa "
                  "is given only between people, as an agreement statistic")
MVC_CLASS_NOTE = ("per class, quantity_dis and allocation_dis are the class's "
                  "share of the overall quantity and allocation "
                  "disagreement (half the by-category value of Pontius "
                  "2019), so they add up to the overall values")
MVC_GROSS_NOTE = ("the logged figures (operations, m2 changed and swept) "
                  "are gross, counted as each stroke was made, undone "
                  "strokes included; the net figures are read from the "
                  "pixels, and the two are never mixed")


MVC_GROUND_NOTE = ("every area in m2 (the scope, the classes, the net change, "
                   "each transition and each polygon) is the ground its "
                   "pixels cover, row by row, and not the pixel at the "
                   "middle of the map times their number")


class MvcCancelled(Exception):
    """Raised inside a run when its progress says stop."""


#  Reading the maps
# =====================================================================
def _mvc_open(path, band_no, what):
    """(dataset, band) of a raster to read, or an IOError in words."""
    try:
        ds = gdal.Open(long_path(str(path).split("|")[0]))
    except Exception as err:
        raise IOError("cannot read %s, %s: %s"
                      % (what, os.path.basename(str(path)), err))
    if ds is None:
        raise IOError("cannot read %s, %s"
                      % (what, os.path.basename(str(path))))
    if int(band_no) < 1 or int(band_no) > ds.RasterCount:
        raise IOError("%s, %s, has no band %d"
                      % (what, os.path.basename(str(path)), int(band_no)))
    return ds, ds.GetRasterBand(int(band_no))


def mvc_grid_of(path):
    """(width, height, geotransform, projection) of a raster, or None."""
    try:
        ds = gdal.Open(long_path(str(path).split("|")[0]))
    except Exception:
        ds = None
    if ds is None:
        return None
    try:
        return (ds.RasterXSize, ds.RasterYSize, tuple(ds.GetGeoTransform()),
                ds.GetProjection() or "")
    finally:
        ds = None


def mvc_same_system(a, b, empty_ok=False):
    """True when two WKTs name one system. With empty_ok, a raster whose file
    names none is on the system of the other: the map a correction started
    from may have had its system set in QGIS, which the copy then carries in
    its file and the original never had."""
    if a == b or (empty_ok and (not a or not b)):
        return True
    if not a or not b:
        return False
    try:
        sa = osr.SpatialReference()
        sa.ImportFromWkt(a)
        sb = osr.SpatialReference()
        sb.ImportFromWkt(b)
        return bool(sa.IsSame(sb))
    except Exception:
        return False


def mvc_grid_refusal(path, reference, what, empty_ok=False):
    """Why a raster is not on the grid of the working copy, in words, or
    None when it is: the same size, the same grid and the same system, the
    checks of rasters.differences without the pixels. empty_ok is for the map
    the correction started from, whose system may have been set in QGIS."""
    a = mvc_grid_of(path)
    b = mvc_grid_of(reference)
    if a is None:
        return "%s cannot be read: %s" % (what, path)
    if b is None:
        return "the working copy cannot be read: %s" % reference
    if (a[0], a[1]) != (b[0], b[1]):
        return ("%s is %d x %d pixels and this correction's copy %d x %d: "
                "they are not the same map, and cannot be compared pixel by "
                "pixel" % (what, a[0], a[1], b[0], b[1]))
    if any(abs(x - y) > 1e-9 * max(1.0, abs(x), abs(y))
           for x, y in zip(a[2], b[2])):
        return ("%s is not on the grid of this correction's copy (the grid "
                "moved), so its pixels are not the same ground" % what)
    if not mvc_same_system(a[3], b[3], empty_ok):
        return ("%s is in another coordinate system than this correction's "
                "copy, so its pixels are not the same ground" % what)
    return None


def mvc_valid(values, nodata):
    """(valid, not_a_code) of one strip: valid is every pixel that holds a
    class code; not_a_code the pixels of a float band that hold a number
    but not a whole one (counted and left out, the rule of codes_present)."""
    v = np.asarray(values)
    valid = np.ones(v.shape, dtype=bool)
    odd = np.zeros(v.shape, dtype=bool)
    if v.dtype.kind == "f":
        valid &= np.isfinite(v)
        if nodata is not None and nodata == nodata:
            valid &= v != nodata
        with np.errstate(invalid="ignore"):
            odd = valid & (v != np.floor(np.where(valid, v, 0)))
        valid &= ~odd
    elif nodata is not None and nodata == nodata:
        try:
            valid &= v != nodata
        except (TypeError, OverflowError):
            pass
    return valid, odd


def _mvc_side(path, band_no, w, h, what):
    """A record beside the copy, read a strip at a time: None when it is not
    there or not on the copy's size (said by the caller)."""
    if not path or not os.path.exists(long_path(path)):
        return None
    try:
        ds, band = _mvc_open(path, band_no, what)
    except IOError:
        return None
    if (ds.RasterXSize, ds.RasterYSize) != (w, h):
        return None
    return ds, band


def _mvc_pixel_window(gt, w, h, geom):
    """The window (c0, r0, c1, r1) of the pixels whose centres can fall in
    a polygon, cut to the raster; None when it misses it."""
    x0, x1, y0, y1 = geom.GetEnvelope()
    ca = (x0 - gt[0]) / gt[1]
    cb = (x1 - gt[0]) / gt[1]
    ra = (y0 - gt[3]) / gt[5]
    rb = (y1 - gt[3]) / gt[5]
    c0 = max(0, int(math.floor(min(ca, cb))))
    c1 = min(w, int(math.ceil(max(ca, cb))))
    r0 = max(0, int(math.floor(min(ra, rb))))
    r1 = min(h, int(math.ceil(max(ra, rb))))
    if c1 <= c0 or r1 <= r0:
        return None
    return c0, r0, c1, r1


def mvc_polygons(polygons, gt, w, h):
    """The polygons of the recipe, read: [{fid, geom, window}] with a
    polygon that misses the map kept with window None, so it is listed
    with 0 pixels rather than quietly lost."""
    out = []
    for i, p in enumerate(polygons or []):
        fid = p.get("fid", i + 1) if isinstance(p, dict) else i + 1
        wkb = p.get("wkb") if isinstance(p, dict) else p
        try:
            geom = ogr.CreateGeometryFromWkb(bytes(wkb))
        except Exception:
            geom = None
        if geom is None or geom.IsEmpty():
            out.append({"fid": fid, "geom": None, "window": None})
            continue
        out.append({"fid": fid, "geom": geom,
                    "window": _mvc_pixel_window(gt, w, h, geom)})
    return out


# Pixels counted at a time: the int64 keys of a strip of a wide map would
# otherwise be held all at once, several times over.
MVC_CHUNK = 1 << 21


def _mvc_ground(picked, row, row_m2):
    """The ground, in m2, of the pixels picked in a strip whose first row is
    row of the map, row by row (the strip's own rows of row_m2)."""
    per_row = picked.sum(axis=1)
    return float(np.dot(per_row, row_m2[row:row + len(per_row)]))


def _mvc_add_ground(ground, a, b, rows, row_m2):
    """The ground of every (a, b) pair of the pixels picked, added into the
    dict ground, a chunk at a time like _mvc_add. rows is the row of the map
    of each pixel, in the order a and b hold them."""
    for k in range(0, a.size, MVC_CHUNK):
        both = np.stack([a[k:k + MVC_CHUNK].astype(np.int64),
                         b[k:k + MVC_CHUNK].astype(np.int64)], axis=1)
        found, inverse = np.unique(both, axis=0, return_inverse=True)
        sums = np.bincount(np.asarray(inverse).reshape(-1),
                           weights=row_m2[rows[k:k + MVC_CHUNK]],
                           minlength=len(found))
        for (f, t), m2 in zip(found.tolist(), sums.tolist()):
            ground[(f, t)] = ground.get((f, t), 0.0) + m2
    return ground


def _mvc_add(pairs, a, b):
    """cm_accumulate a chunk at a time, so the memory a strip costs stays a
    few strips of bytes whatever the width of the map."""
    for k in range(0, a.size, MVC_CHUNK):
        cm_accumulate(pairs, a[k:k + MVC_CHUNK], b[k:k + MVC_CHUNK])
    return pairs


def _mvc_tick(progress, cancelled, done, total):
    if progress is not None:
        if progress(done, total) is False:
            raise MvcCancelled()
    if cancelled is not None and cancelled():
        raise MvcCancelled()


#  The run
# =====================================================================
def mvc_compare(recipe, progress=None, cancelled=None):
    """Read the two maps a strip at a time and count, on the ground asked
    for, the pixels of every (model, corrected) pair, and of every
    (other, corrected) pair when another correction is given.

    recipe: model {path, band}, corrected {path, band}, scope (whole, swept
    or polygons), changes and reviewed (the records beside the copy, either
    may be missing), polygons [{fid, wkb}] in the copy's system, other
    {path, band} or None, strata {path, band, edges} or None, map (the path
    of the map of pairs to write, or None), codes (the classes' codes),
    names {code: name}, colours {code: colour}, metadata (for the map),
    strip_rows. progress(done, total) is told after each strip and stops
    the run when it answers False, as cancelled() does when it answers
    True: MvcCancelled is raised, and whatever was being written is left
    for the caller to throw away."""
    scope = recipe.get("scope") or "whole"
    if scope not in MVC_SCOPES:
        raise ValueError("%r is not a scope: %s" % (scope,
                                                   ", ".join(MVC_SCOPES)))
    rows_at = int(recipe.get("strip_rows") or STRIP_ROWS)
    model, corrected = recipe["model"], recipe["corrected"]
    # the map the model made is the map the correction started from, whose
    # system may have been set in QGIS and so be in the copy and not in it
    refusal = mvc_grid_refusal(model["path"], corrected["path"],
                               "the map the model made", empty_ok=True)
    if refusal:
        raise IOError(refusal)
    mds, mband = _mvc_open(model["path"], model.get("band", 1),
                           "the map the model made")
    cds, cband = _mvc_open(corrected["path"], corrected.get("band", 1),
                           "the corrected map")
    w, h = cds.RasterXSize, cds.RasterYSize
    if (mds.RasterXSize, mds.RasterYSize) != (w, h):
        raise IOError("the map the model made is not the size of the "
                      "corrected map")
    gt = tuple(cds.GetGeoTransform())
    wkt = cds.GetProjection() or ""
    m_nodata = model.get("nodata", mband.GetNoDataValue()) \
        if "nodata" in model else mband.GetNoDataValue()
    c_nodata = corrected.get("nodata", cband.GetNoDataValue()) \
        if "nodata" in corrected else cband.GetNoDataValue()
    notes = []
    # The ground of a pixel in every row, when the caller measured it (the
    # pixel is not the same ground all down a map in degrees or in Web
    # Mercator); the engine itself reads no coordinate system.
    row_m2 = recipe.get("row_m2")
    if row_m2 is not None:
        row_m2 = np.asarray(row_m2, dtype=np.float64)
        if row_m2.shape != (h,) or not np.isfinite(row_m2).all():
            row_m2 = None
    changes = _mvc_side(recipe.get("changes"), 1, w, h,
                        "the record of changed pixels")
    reviewed = _mvc_side(recipe.get("reviewed"), 1, w, h,
                         "the record of the ground swept")
    if recipe.get("changes") and changes is None:
        notes.append("the record of changed pixels, %s, is not there or not "
                     "on the copy's grid: no pixel counts as marked"
                     % os.path.basename(str(recipe.get("changes"))))
    if scope == "swept" and reviewed is None:
        notes.append("the ground swept is not recorded for this correction: "
                     "the swept ground is the changed pixels alone")
    other = None
    o_nodata = None
    if recipe.get("other"):
        why = mvc_grid_refusal(recipe["other"]["path"], corrected["path"],
                               "the other correction")
        if why:
            raise IOError(why)
        other = _mvc_open(recipe["other"]["path"],
                          recipe["other"].get("band", 1),
                          "the other correction")
        o_nodata = other[1].GetNoDataValue()
    strata = None
    if recipe.get("strata"):
        s = recipe["strata"]
        why = mvc_grid_refusal(s["path"], corrected["path"], "the strata")
        if why:
            raise IOError(why)
        strata = (_mvc_open(s["path"], s.get("band", 1), "the strata"),
                  [float(e) for e in s.get("edges") or []])
    polys = mvc_polygons(recipe.get("polygons"), gt, w, h) \
        if scope == "polygons" else []
    for p in polys:
        p.update({"pixels": 0, "swept": 0, "changed": 0, "pairs": {},
                  "m2": 0.0 if row_m2 is not None else None})

    codes_hint = sorted({int(c) for c in recipe.get("codes") or []})
    writer = None
    map_path = recipe.get("map")
    if map_path:
        writer = {"path": map_path, "codes": codes_hint, "ds": None,
                  "ok": bool(codes_hint), "present": {}}

    pairs, other_pairs = {}, {}
    pairs_m2 = {} if row_m2 is not None else None
    counts = {"map_px": 0, "scope_px": 0, "nodata_mismatch": 0,
              "not_a_code": 0, "marked_but_unchanged": 0, "swept_px": 0,
              "reviewed_px": 0, "changes_px": 0, "changed_px": 0,
              "changed_m2": 0.0 if row_m2 is not None else None,
              "scope_m2": 0.0 if row_m2 is not None else None,
              "other_px": 0, "other_nodata_mismatch": 0, "width": w,
              "height": h}
    per_stratum = {}
    total = h

    def strip(row, take):
        a = mband.ReadAsArray(0, row, w, take)
        b = cband.ReadAsArray(0, row, w, take)
        va, oa = mvc_valid(a, m_nodata)
        vb, ob = mvc_valid(b, c_nodata)
        both = va & vb
        chg = changes[1].ReadAsArray(0, row, w, take).astype(bool) \
            if changes is not None else np.zeros(a.shape, dtype=bool)
        rev = reviewed[1].ReadAsArray(0, row, w, take).astype(bool) \
            if reviewed is not None else np.zeros(a.shape, dtype=bool)
        return a, b, va, vb, oa, ob, both, chg, rev

    def scope_of(both, chg, rev, row, take, polygon_work=None):
        if scope == "whole":
            return both.copy()
        if scope == "swept":
            return both & (rev | chg)
        inside = np.zeros(both.shape, dtype=bool)
        for p in polys:
            win = p["window"]
            if win is None:
                continue
            c0, r0, c1, r1 = win
            lo, hi = max(r0, row), min(r1, row + take)
            if hi <= lo:
                continue
            burned = cmp_burn(p["geom"], (gt[0] + c0 * gt[1], gt[1], 0.0,
                                          gt[3] + lo * gt[5], 0.0, gt[5]),
                              c1 - c0, hi - lo, wkt).astype(bool)
            inside[lo - row:hi - row, c0:c1] |= burned
            if polygon_work is not None:
                polygon_work(p, burned, lo - row, hi - row, c0, c1)
        return inside & both

    try:
        for row in range(0, h, rows_at):
            take = min(rows_at, h - row)
            a, b, va, vb, oa, ob, both, chg, rev = strip(row, take)
            counts["map_px"] += int(both.sum())
            counts["nodata_mismatch"] += int((va ^ vb).sum())
            counts["not_a_code"] += int((oa | ob).sum())

            def polygon_work(p, burned, s0, s1, c0, c1):
                sub = both[s0:s1, c0:c1] & burned
                if not sub.any():
                    return
                sa = a[s0:s1, c0:c1][sub]
                sb = b[s0:s1, c0:c1][sub]
                p["pixels"] += int(sub.sum())
                if row_m2 is not None:
                    p["m2"] += _mvc_ground(sub, row + s0, row_m2)
                p["swept"] += int((sub & (rev[s0:s1, c0:c1]
                                          | chg[s0:s1, c0:c1])).sum())
                p["changed"] += int((sa != sb).sum())
                _mvc_add(p["pairs"], sa, sb)

            inside = scope_of(both, chg, rev, row, take, polygon_work)
            counts["scope_px"] += int(inside.sum())
            swept = both & (rev | chg)
            counts["swept_px"] += int((inside & swept).sum())
            counts["reviewed_px"] += int((both & rev).sum())
            counts["changes_px"] += int((both & chg).sum())
            if inside.any():
                sa, sb = a[inside], b[inside]
                _mvc_add(pairs, sa, sb)
                counts["changed_px"] += int((sa != sb).sum())
                if row_m2 is not None:
                    counts["scope_m2"] += _mvc_ground(inside, row, row_m2)
                    moved = inside.copy()
                    moved[inside] = sa != sb
                    counts["changed_m2"] += _mvc_ground(moved, row, row_m2)
                    _mvc_add_ground(pairs_m2, sa, sb,
                                    row + np.nonzero(inside)[0], row_m2)
                counts["marked_but_unchanged"] += int(
                    (chg[inside] & (sa == sb)).sum())
            if other is not None:
                o = other[1].ReadAsArray(0, row, w, take)
                vo, oo = mvc_valid(o, o_nodata)
                counts["other_nodata_mismatch"] += int((inside & ~vo).sum())
                both_o = inside & vo
                counts["other_px"] += int(both_o.sum())
                if both_o.any():
                    _mvc_add(other_pairs, o[both_o], b[both_o])
            if strata is not None and inside.any():
                level = strata[0][1].ReadAsArray(0, row, w, take)[inside]
                where = np.digitize(level.astype(np.float64), strata[1])
                sa, sb = a[inside], b[inside]
                for k in np.unique(where).tolist():
                    sel = where == k
                    got = per_stratum.setdefault(int(k), [0, 0])
                    got[0] += int(sel.sum())
                    got[1] += int((sa[sel] != sb[sel]).sum())
            if writer is not None and writer["ok"]:
                _mvc_write_strip(writer, a, b, inside, row, gt, w, h, wkt)
            _mvc_tick(progress, cancelled, row + take, total)
        codes = sorted(set(codes_hint) | {int(c) for k in pairs for c in k}
                       | {int(c) for k in other_pairs for c in k})
        if writer is not None and writer["codes"] != codes:
            # A code the classes do not hold: the map is written again with
            # every code in its list, so each pair keeps one value.
            _mvc_close_map(writer, drop=True)
            writer.update({"codes": codes, "ok": True, "present": {}})
            for row in range(0, h, rows_at):
                take = min(rows_at, h - row)
                a, b, va, vb, oa, ob, both, chg, rev = strip(row, take)
                inside = scope_of(both, chg, rev, row, take)
                _mvc_write_strip(writer, a, b, inside, row, gt, w, h, wkt)
                _mvc_tick(progress, cancelled, row + take, total)
        map_info = None
        if writer is not None:
            map_info = _mvc_finish_map(writer, recipe, gt, w, h, wkt)
    except BaseException:
        if writer is not None:
            _mvc_close_map(writer, drop=False)
        raise
    finally:
        mband = cband = None
        mds = cds = None
        changes = reviewed = other = None
        if strata is not None:
            strata = None
    grid_area = abs(gt[1] * gt[5])
    return {"recipe": recipe, "scope": scope, "pairs": pairs,
            "pairs_m2": pairs_m2, "other_pairs": other_pairs,
            "counts": counts, "codes": codes,
            "polygons": [{k: v for k, v in p.items() if k != "geom"}
                         for p in polys],
            "per_stratum": per_stratum, "map": map_info, "notes": notes,
            "grid": {"gt": list(gt), "wkt": wkt, "size": [w, h],
                     "pixel_area": grid_area},
            "nodata": {"model": m_nodata, "corrected": c_nodata,
                       "other": o_nodata}}


def _mvc_write_strip(writer, a, b, inside, row, gt, w, h, wkt):
    """One strip of the map of pairs, or the map given up on (ok False)
    when the strip holds a code its list does not: it is then written
    again once every code is known."""
    codes = writer["codes"]
    if inside.any():
        seen = set(np.unique(a[inside]).tolist()) | \
            set(np.unique(b[inside]).tolist())
        if not seen <= set(codes):
            writer["ok"] = False
            return
    if writer["ds"] is None:
        writer["ds"] = rr_open(writer["path"], gt, w, h, wkt,
                               cm_pair_dtype(len(codes)), nodata=0,
                               band_name="pairs")
    band = writer["ds"].GetRasterBand(1)
    # a few rows at a time, for the same reason as _mvc_add
    step = max(1, MVC_CHUNK // max(1, a.shape[1]))
    for r0 in range(0, a.shape[0], step):
        sl = slice(r0, r0 + step)
        values = cm_pair_values(a[sl], b[sl], codes, inside[sl])
        band.WriteArray(values, 0, row + r0)
        found, n = np.unique(values[values > 0], return_counts=True)
        for v, k in zip(found.tolist(), n.tolist()):
            got = writer["present"]
            got[int(v)] = got.get(int(v), 0) + int(k)
    band = None


def _mvc_close_map(writer, drop):
    ds = writer.get("ds")
    writer["ds"] = None
    if ds is not None:
        try:
            ds.FlushCache()
        except Exception:
            pass
        ds = None
    if drop and writer.get("path") and os.path.exists(long_path(
            writer["path"])):
        try:
            gdal.GetDriverByName("GTiff").Delete(long_path(writer["path"]))
        except Exception:
            try:
                os.remove(long_path(writer["path"]))
            except OSError:
                pass


def _mvc_finish_map(writer, recipe, gt, w, h, wkt):
    """The map closed and dressed: colours and names inside when it is a
    Byte, a .qml beside it always, and the metadata of the comparison."""
    codes = writer["codes"]
    if writer["ds"] is None:
        # nothing in scope at all: an empty map, so the file is still there
        writer["ds"] = rr_open(writer["path"], gt, w, h, wkt,
                               cm_pair_dtype(max(1, len(codes))), nodata=0,
                               band_name="pairs")
    names = dict(recipe.get("names") or {})
    colours = dict(recipe.get("colours") or {})
    entries = rr_pair_entries(codes, {c: cm_name(c, names, None)
                                      for c in codes},
                              colours, writer["present"].keys())
    ds = writer["ds"]
    writer["ds"] = None
    qml = rr_finish(ds, writer["path"], entries, recipe.get("metadata"))
    return {"path": writer["path"], "qml": qml, "codes": codes,
            "present": dict(writer["present"]),
            "dtype": cm_pair_dtype(len(codes))}


#  The numbers
# =====================================================================
def _mvc_num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def mvc_metrics(pairs, codes, pixel_m2, kappa=False):
    """cm_metrics of a dict of pairs over these codes (no unlabelled code:
    every code of a thematic map is a class)."""
    m, cs = cm_from_pairs(pairs, codes)
    return m, cs, cm_metrics(m, cs, None, kappa, pixel_m2)


def mvc_people_from_report(people, model_rows, names):
    """The rows of an agreement report matched to the classes of the
    correction: by name (case and spaces aside) first, then by code. The
    classes nobody matched are listed apart."""
    by_name = {}
    for code, name in names.items():
        by_name.setdefault(str(name).strip().casefold(), code)
    matched, unmatched = {}, []
    codes = {int(r["code"]) for r in model_rows}
    for r in people.get("per_class") or []:
        key = str(r.get("name") or "").strip().casefold()
        code = by_name.get(key)
        if code is None:
            try:
                c = int(r.get("code"))
            except (TypeError, ValueError):
                c = None
            code = c if c in codes else None
        if code is None or code in matched:
            unmatched.append(str(r.get("name") or r.get("code")))
            continue
        matched[code] = r
    return matched, unmatched


def mvc_side_by_side(model_per_class, people_rows, names):
    """Per class: the model's IoU and F1 against the corrected map beside
    two people's on the same classes. excess_error is (1 - model IoU) -
    (1 - people IoU): above 0, the model's error is beyond what two people
    disagree on. With an interval for the people, a class is flagged only
    when the model's IoU is below its low end."""
    out = []
    for c in model_per_class:
        p = people_rows.get(c["code"])
        if p is None:
            continue
        m_iou, p_iou = _mvc_num(c["iou"]), _mvc_num(p.get("iou"))
        lo, hi = _mvc_num(p.get("iou_lo")), _mvc_num(p.get("iou_hi"))
        excess = (p_iou - m_iou) if m_iou is not None and p_iou is not None \
            else None
        if lo is not None and m_iou is not None:
            beyond = m_iou < lo
        else:
            beyond = excess is not None and excess > 1e-12
        out.append({"code": c["code"], "class": cm_name(c["code"], names,
                                                        None),
                    "model_iou": m_iou, "people_iou": p_iou,
                    "model_f1": _mvc_num(c["f1"]),
                    "people_f1": _mvc_num(p.get("f1")),
                    "excess_error": excess, "people_iou_lo": lo,
                    "people_iou_hi": hi, "beyond_people": bool(beyond)})
    return out


def mvc_read_people(path):
    """An agreement report of an annotation campaign, read back: its
    summary.json (or the folder that holds it) and its per_class.csv.
    {kind, path, readings, overall {oa, kappa, quantity, allocation},
    per_class [{code, name, iou, f1, iou_lo, iou_hi}]}; IOError in words
    when it is no agreement report."""
    import csv
    import io
    where = str(path or "")
    if os.path.isdir(long_path(where)):
        where = os.path.join(where, REPORT_SUMMARY)
    summary = report_read(where)
    if not isinstance(summary, dict) or \
            summary.get("rasterlabel:report") != "agreement":
        raise IOError("%s is not the summary.json of an agreement report "
                      "(Measure, Compare two readings)" % where)
    folder = os.path.dirname(where)
    rows = []
    table = os.path.join(folder, "per_class.csv")
    try:
        with io.open(long_path(table), encoding="utf-8", newline="") as fh:
            for r in map(csv_untext_row, csv.DictReader(fh)):
                rows.append({"code": r.get("code"), "name": r.get("name"),
                             "iou": _mvc_num(r.get("iou")),
                             "f1": _mvc_num(r.get("f1")),
                             "iou_lo": _mvc_num(r.get("iou_ci_low")),
                             "iou_hi": _mvc_num(r.get("iou_ci_high"))})
    except OSError as err:
        raise IOError("the agreement report has no per_class.csv beside "
                      "its summary.json: %s" % err)
    pooled = summary.get("pooled") or {}
    axes = summary.get("axes") or {}
    return {"kind": "agreement_report", "path": where,
            "readings": [axes.get("A"), axes.get("B")],
            "overall": {"oa": _mvc_num(pooled.get("overall")),
                        "kappa": _mvc_num(pooled.get("kappa")),
                        "quantity": _mvc_num(pooled.get("quantity")),
                        "allocation": _mvc_num(pooled.get("allocation"))},
            "per_class": rows}


def mvc_logged(record):
    """What the manifest logged as each stroke was made, gross. The part of
    it that was undone is given beside it, when there was any, so that the
    net of the log can be read off without the two being mixed."""
    ops = int(record.get("operations", 0) or 0)
    changed = float(record.get("changed_m2", 0.0) or 0.0)
    swept = float(record.get("swept_m2", 0.0) or 0.0)
    pairs = record.get("pairs") or {}
    any_class = {k: v for k, v in pairs.items()
                 if str(k).startswith("every class -> ")}
    out = {"operations": ops, "changed_m2_gross": changed,
           "swept_m2": swept,
           "swept_over_changed": swept / changed if changed > 0 else None,
           "pairs": dict(pairs), "logged_any_class": any_class}
    gone = undone_of(record)
    if gone["operations"]:
        out["operations_undone"] = gone["operations"]
        out["changed_m2_undone"] = gone["changed_m2"]
    return out


def mvc_source_changed(record, source):
    """True when the map the model made was changed after the copy was
    made (its time on disk later than the manifest's "created"); None when
    it cannot be told."""
    try:
        made = datetime.fromisoformat(str(record.get("created") or ""))
        then = datetime.fromtimestamp(os.path.getmtime(long_path(
            str(source).split("|")[0])))
    except (ValueError, OSError, TypeError):
        return None
    if made.tzinfo is not None:
        made = made.astimezone().replace(tzinfo=None)
    return then > made


#  The tables
# =====================================================================
MVC_PER_CLASS = ["code", "name", "colour", "model_px", "corrected_px",
                 "agree_px", "model_m2", "corrected_m2", "net_change_m2",
                 "producers_accuracy", "users_accuracy", "omission",
                 "commission", "iou", "f1", "quantity_dis", "allocation_dis"]
MVC_CI = ["iou_ci_low", "iou_ci_high", "f1_ci_low", "f1_ci_high"]
MVC_PEOPLE = ["people_iou", "people_f1", "people_source", "excess_error"]
MVC_PAIRS = ["value", "a_code", "a_name", "b_code", "b_name", "changed",
             "pixels", "area_m2", "share_of_scope", "share_of_a",
             "logged_strokes", "logged_m2"]
MVC_SIDE = ["code", "class", "model_iou", "people_iou", "model_f1",
            "people_f1", "excess_error", "people_iou_lo", "people_iou_hi",
            "beyond_people"]
MVC_POLYGONS = ["fid", "pixels", "area_m2", "swept_share", "changed_px",
                "oa"]
MVC_STRATA = ["stratum", "low", "high", "pixels", "changed_share",
              "changed_px"]


def _mvc_less(a, b):
    return None if a is None else 1.0 - a


def mvc_files(stem, scope):
    """The name of the map of a report, <copy stem>_mvc_<scope>_pairs.tif:
    it says what it is once copied out of the folder."""
    return {"pairs": report_artifact_name(stem, MVC_KIND, scope, "pairs",
                                          ".tif")}


def mvc_metadata(record, scope, reference="corrected map"):
    """The tags of the map of pairs, in the manner of cmp_metadata."""
    return {"RASTERLABEL_VERSION": VERSION, "RASTERLABEL_BUILD": BUILD,
            "RASTERLABEL_REPORT": MVC_KIND,
            "RASTERLABEL_OWNER_ID": record.get("id", ""),
            "RASTERLABEL_COMPARISON": MVC_KIND,
            "RASTERLABEL_SCOPE": scope,
            "RASTERLABEL_REFERENCE": reference,
            "RASTERLABEL_PAIR_ENCODING": "1 + i*K + j over the codes, i the "
                                         "model's, j the corrected map's; 0 "
                                         "outside"}


def mvc_summarize(result, record, people=None):
    """Everything the tables and the window show, from one run: the
    model's metrics, the people's, the pairs, the polygons."""
    recipe = result["recipe"]
    codes = result["codes"]
    names = {int(k): v for k, v in (recipe.get("names") or {}).items()}
    pixel_m2 = float(recipe.get("pixel_m2") or result["grid"]["pixel_area"])
    m, cs, metrics = mvc_metrics(result["pairs"], codes, pixel_m2)
    n = int(m.sum())
    # the counts of a run, when the result came from one: the ground of the
    # scope and of the changed pixels row by row, where it was measured
    counts = result.get("counts") or {}
    ground = result.get("pairs_m2")
    changed_px = counts.get("changed_px")
    if changed_px is None:
        changed_px = int(n - np.trace(m))
    # The ground of every pair, the classes and the whole: row by row where it
    # was measured, else the pixels times the pixel, which is what a map in a
    # metric system of its own always gave.
    if ground is not None:
        m2 = np.array([[ground.get((a, b), 0.0) for b in cs] for a in cs],
                      dtype=np.float64).reshape((len(cs), len(cs)))
        by_row = [float(v) for v in m2.sum(axis=1)]
        by_col = [float(v) for v in m2.sum(axis=0)]
        total_m2 = float(m2.sum())
        net = [c - r for r, c in zip(by_row, by_col)]
    else:
        m2 = m * pixel_m2
        by_row = [float(m[i].sum()) * pixel_m2 for i in range(len(cs))]
        by_col = [float(v) * pixel_m2 for v in m.sum(axis=0)]
        total_m2 = float(m.sum()) * pixel_m2
        net = [(int(m[:, i].sum()) - int(m[i].sum())) * pixel_m2
               for i in range(len(cs))]
    out = {"codes": cs, "names": names, "pixel_m2": pixel_m2, "matrix": m,
           "matrix_m2": m2, "model_m2": dict(zip(cs, by_row)),
           "corrected_m2": dict(zip(cs, by_col)),
           "net_change_m2": dict(zip(cs, net)), "total_m2": total_m2,
           "metrics": metrics, "n": n,
           "scope_m2": counts["scope_m2"] if counts.get("scope_m2")
           is not None else n * pixel_m2,
           "changed_m2": counts["changed_m2"] if counts.get("changed_m2")
           is not None else changed_px * pixel_m2,
           "ground_by_row": ground is not None}
    # the pairs, net, from the pixels
    k = len(cs)
    row_sums = m.sum(axis=1)
    logged = mvc_logged(record)
    rows = []
    for i, a in enumerate(cs):
        for j, b in enumerate(cs):
            px = int(m[i, j])
            if not px:
                continue
            a_name, b_name = cm_name(a, names, None), cm_name(b, names, None)
            got = logged["pairs"].get("%s -> %s" % (a_name, b_name)) \
                if i != j else None
            rows.append({"value": 1 + i * k + j, "a": a, "a_name": a_name,
                         "b": b, "b_name": b_name, "changed": i != j,
                         "pixels": px,
                         "area_m2": ground.get((a, b), 0.0)
                         if ground is not None else px * pixel_m2,
                         "share_of_scope": px / float(n) if n else None,
                         "share_of_a": px / float(row_sums[i])
                         if row_sums[i] else None,
                         "logged_strokes": got[0] if got else None,
                         "logged_m2": got[1] if got else None})
    out["pairs"] = rows
    out["transitions"] = sorted([r for r in rows if r["changed"]],
                                key=lambda r: (-r["pixels"], r["value"]))
    out["logged"] = logged
    # polygons: one matrix each, and an interval over them
    polys = result.get("polygons") or []
    if polys:
        ms = [cm_from_pairs(p["pairs"], cs)[0] for p in polys]
        stack = np.array(ms, dtype=np.int64).reshape((len(ms), k, k))
        boot = cm_bootstrap(stack, lambda one: cm_stat_values(
            cm_metrics(one, cs, None, False)), BOOTSTRAP_N, BOOTSTRAP_SEED,
            BOOTSTRAP_MIN_FRAMES, BOOTSTRAP_LEVEL)
        boot["reason"] = boot.get("reason", "").replace("frames",
                                                        "polygons")
        boot["method"] = "percentile; polygons resampled with replacement"
        out["bootstrap"] = boot
        out["polygon_rows"] = []
        for p, one in zip(polys, ms):
            total = int(one.sum())
            out["polygon_rows"].append({
                "fid": p["fid"], "pixels": p["pixels"],
                "area_m2": p["m2"] if p.get("m2") is not None
                else p["pixels"] * pixel_m2,
                "swept_share": p["swept"] / float(p["pixels"])
                if p["pixels"] else None,
                "changed_px": p["changed"],
                "oa": float(np.trace(one)) / total if total else None})
    else:
        out["bootstrap"] = None
        out["polygon_rows"] = []
    # people against people
    out["people"] = None
    if people is not None and people.get("kind") == "correction":
        pm, pcs, pmet = mvc_metrics(result["other_pairs"], cs, pixel_m2,
                                    kappa=True)
        rows_p = {c["code"]: {"code": c["code"], "iou": c["iou"],
                              "f1": c["f1"]} for c in pmet["per_class"]}
        out["people"] = dict(people, metrics=pmet, matrix=pm,
                             matched=rows_p, unmatched=[],
                             overall={"oa": pmet["overall"]["po"],
                                      "kappa": pmet["overall"].get("kappa"),
                                      "pe": pmet["overall"]["pe"],
                                      "quantity": pmet["overall"]["quantity"],
                                      "allocation":
                                          pmet["overall"]["allocation"],
                                      "pixels": pmet["overall"]["n"]})
    elif people is not None and people.get("kind") == "agreement_report":
        matched, unmatched = mvc_people_from_report(
            people, metrics["per_class"], names)
        out["people"] = dict(people, matched=matched, unmatched=unmatched)
    if out["people"] is not None:
        out["side_by_side"] = mvc_side_by_side(
            metrics["per_class"], out["people"]["matched"], names)
    else:
        out["side_by_side"] = []
    return out


def mvc_people_word(people):
    if not people:
        return ""
    if people.get("kind") == "correction":
        return "%s's correction %s" % (people.get("operator") or "?",
                                       people.get("name") or "")
    readings = [r for r in people.get("readings") or [] if r]
    return "agreement report %s" % " vs ".join(readings)


def mvc_write(result, folder, record, owner_folder, people=None):
    """The tables and summary.json of a run, into folder. Returns the
    summary (with "files", every file of the report relative to it)."""
    s = mvc_summarize(result, record, people)
    recipe = result["recipe"]
    cs, names = s["codes"], s["names"]
    colours = {int(k): v for k, v in (recipe.get("colours") or {}).items()}
    m = s["matrix"]
    files = ["summary.json", "confusion.csv", "per_class.csv", "pairs.csv"]
    # confusion.csv: pixels with the totals, then the same in m2
    wide = cm_wide_rows(m, cs, names, None, corner="model \\ corrected")
    head = wide[0] + ["total"]
    rows = [r + [int(m[i].sum())] for i, r in enumerate(wide[1:])]
    rows.append(["total"] + [int(v) for v in m.sum(axis=0)] + [int(m.sum())])
    rows.append([])
    m2 = s["matrix_m2"]
    rows.append(["model \\ corrected (m2)"] + head[1:])
    for i, r in enumerate(wide[1:]):
        rows.append([r[0]] + [float(v) for v in m2[i]]
                    + [s["model_m2"][cs[i]]])
    rows.append(["total"] + [s["corrected_m2"][c] for c in cs]
                + [s["total_m2"]])
    report_csv(os.path.join(folder, "confusion.csv"), head, rows)
    # per_class.csv
    boot = s["bootstrap"]
    ci = (boot or {}).get("ci") or {}
    people_rows = {r["code"]: r for r in s["side_by_side"]}
    header = list(MVC_PER_CLASS) + (MVC_CI if ci else []) \
        + (MVC_PEOPLE if s["people"] else [])
    rows = []
    for c in s["metrics"]["per_class"]:
        code = c["code"]
        row = [code, cm_name(code, names, None), colours.get(code, ""),
               c["n_A"], c["n_B"], c["n_same"], s["model_m2"][code],
               s["corrected_m2"][code], s["net_change_m2"][code],
               c["rate_B"], c["rate_A"], _mvc_less(_mvc_num(c["rate_B"]), 0),
               _mvc_less(_mvc_num(c["rate_A"]), 0), c["iou"], c["f1"],
               c["q"] / 2.0, c["a"] / 2.0]
        if ci:
            row += (ci.get("iou:%d" % code) or [None, None])[:2] \
                + (ci.get("f1:%d" % code) or [None, None])[:2]
        if s["people"]:
            p = people_rows.get(code)
            row += [p["people_iou"] if p else None,
                    p["people_f1"] if p else None,
                    mvc_people_word(s["people"]) if p else None,
                    p["excess_error"] if p else None]
        rows.append(row)
    report_csv(os.path.join(folder, "per_class.csv"), header, rows)
    report_csv(os.path.join(folder, "pairs.csv"), MVC_PAIRS,
               [[r["value"], r["a"], r["a_name"], r["b"], r["b_name"],
                 r["changed"], r["pixels"], r["area_m2"], r["share_of_scope"],
                 r["share_of_a"], r["logged_strokes"], r["logged_m2"]]
                for r in s["pairs"]])
    if s["people"]:
        files.append("side_by_side.csv")
        report_csv(os.path.join(folder, "side_by_side.csv"), MVC_SIDE,
                   [[r[k] for k in MVC_SIDE] for r in s["side_by_side"]])
    if result["scope"] == "polygons":
        files.append("polygons.csv")
        report_csv(os.path.join(folder, "polygons.csv"), MVC_POLYGONS,
                   [[r[k] for k in MVC_POLYGONS] for r in s["polygon_rows"]])
    if recipe.get("strata"):
        files.append("per_stratum.csv")
        edges = [float(e) for e in recipe["strata"].get("edges") or []]
        rows = []
        for k_, (px, chg) in sorted(result["per_stratum"].items()):
            low = edges[k_ - 1] if 0 < k_ <= len(edges) else None
            high = edges[k_] if k_ < len(edges) else None
            rows.append([k_, low, high, px, chg / float(px) if px else None,
                         chg])
        report_csv(os.path.join(folder, "per_stratum.csv"), MVC_STRATA, rows)
    if result.get("map"):
        name = os.path.basename(result["map"]["path"])
        files += [name, os.path.basename(result["map"]["qml"])]
    summary = mvc_summary(result, s, record, owner_folder, files)
    report_json(os.path.join(folder, "summary.json"), summary)
    summary["files"] = sorted(files)
    result["summarized"] = s
    result["summary_json"] = summary
    return summary


def mvc_summary(result, s, record, owner_folder, files):
    """summary.json: the report header, what it was made from, the headline,
    then the numbers and the sentences that qualify them."""
    recipe = result["recipe"]
    counts = result["counts"]
    o = s["metrics"]["overall"]
    cs, names = s["codes"], s["names"]
    w, h = result["grid"]["size"]
    owner = {"kind": "correction", "id": record.get("id", ""),
             "name": record.get("name", ""), "folder": owner_folder}
    summary = report_header(MVC_KIND, owner)
    inputs = [recipe["model"]["path"], recipe["corrected"]["path"]]
    for key in ("changes", "reviewed"):
        if recipe.get(key) and os.path.exists(long_path(recipe[key])):
            inputs.append(recipe[key])
    manifest = os.path.join(owner_folder, CORRECTION_MANIFEST)
    if os.path.exists(long_path(manifest)):
        inputs.append(manifest)
    if recipe.get("other"):
        inputs.append(recipe["other"]["path"])
    people = s["people"]
    per_iou = {cm_name(c["code"], names, None): c["iou"]
               for c in s["metrics"]["per_class"] if c["n_A"] or c["n_B"]}
    headline = report_headline(MVC_KIND, {
        "scope": result["scope"], "pixels": s["n"], "oa": o["po"],
        "quantity": o["quantity"], "allocation": o["allocation"],
        "per_class_iou": per_iou,
        "people_oa": (people or {}).get("overall", {}).get("oa")
        if people else None,
        "people_kappa": (people or {}).get("overall", {}).get("kappa")
        if people else None})
    since = record.get("reviewed_since")
    reviewed_there = bool(recipe.get("reviewed")) and os.path.exists(
        long_path(recipe["reviewed"]))
    notes = [MVC_REFERENCE_NOTE, MVC_KAPPA_NOTE, MVC_NOTES[result["scope"]],
             MVC_CLASS_NOTE, MVC_GROSS_NOTE]
    notes += result.get("notes") or []
    if s["ground_by_row"]:
        notes.append(MVC_GROUND_NOTE)
    if not reviewed_there:
        notes.append("the ground the strokes swept was not recorded for this "
                     "correction: only the pixels they changed are known")
    elif since:
        notes.append("the first %d stroke%s left no footprint (made before "
                     "the ground swept was recorded): only the pixels %s "
                     "changed count as swept" % (since, "" if since == 1
                                                 else "s",
                                                 "it" if since == 1
                                                 else "they"))
    if people and people.get("kind") == "agreement_report":
        notes.append("the people's numbers come from an annotation "
                     "campaign: other pixels, classes matched by name, so "
                     "they are side by side, not a paired comparison")
    if result["scope"] == "polygons":
        boot = s["bootstrap"] or {}
        if boot.get("reason"):
            notes.append("interval over polygons: %s" % boot["reason"])
        notes.append("a pixel under two polygons counts once in the pooled "
                     "numbers and once in each polygon's own")
    logged = s["logged"]
    gross = {"operations": logged["operations"],
             "changed_m2_gross": logged["changed_m2_gross"],
             "swept_m2": logged["swept_m2"],
             "swept_over_changed": logged["swept_over_changed"],
             "logged_any_class": logged["logged_any_class"]}
    if since:
        gross["strokes_without_footprint"] = since
    if logged.get("operations_undone"):
        gross["operations_undone"] = logged["operations_undone"]
        gross["changed_m2_undone"] = logged["changed_m2_undone"]
        notes.append("%d of the %d logged strokes (%.2f m2 of the %.2f m2 "
                     "logged) were undone, as the manifest records; the "
                     "net figures are read from the pixels"
                     % (logged["operations_undone"], logged["operations"],
                        logged["changed_m2_undone"],
                        logged["changed_m2_gross"]))
    scope = {"kind": result["scope"], "pixels": s["n"],
             "area_m2": s["scope_m2"],
             "share_of_map": s["n"] / float(counts["map_px"])
             if counts["map_px"] else None,
             "swept_share": counts["swept_px"] / float(counts["scope_px"])
             if counts["scope_px"] else None,
             "layer": recipe.get("layer"),
             "selected_only": recipe.get("selected_only"),
             "polygons": len(result.get("polygons") or [])}
    body = {
        "inputs": report_inputs(inputs, owner_folder),
        "parameters": {"scope": result["scope"],
                       "layer": recipe.get("layer"),
                       "selected_only": recipe.get("selected_only"),
                       "people": mvc_people_word(people) or None,
                       "resamples": BOOTSTRAP_N if s["bootstrap"] else None,
                       "seed": BOOTSTRAP_SEED if s["bootstrap"] else None},
        "headline": headline,
        "axes": {"A": "model", "B": "corrected"},
        "correction": {"id": record.get("id", ""),
                       "name": record.get("name", ""),
                       "folder": owner_folder,
                       "operators": record.get("operators")
                       or [record.get("operator")]},
        "model": {"path": recipe["model"]["path"],
                  "band": recipe["model"].get("band", 1),
                  "source_changed_after_copy":
                      recipe.get("source_changed_after_copy")},
        "corrected": {"path": recipe["corrected"]["path"],
                      "band": recipe["corrected"].get("band", 1)},
        "changes": recipe.get("changes"),
        "reviewed": {"path": recipe.get("reviewed") if reviewed_there
                     else None,
                     "reviewed_since": since if reviewed_there else None,
                     "recorded": reviewed_there},
        "grid": {"crs": (record.get("grid") or {}).get("crs"),
                 "pixel_m": (record.get("grid") or {}).get("pixel_m"),
                 "size": [w, h], "geotransform": result["grid"]["gt"]},
        "nodata": result["nodata"],
        "scope": scope,
        "codes": cs,
        "names": {str(c): cm_name(c, names, None) for c in cs},
        "overall": {"oa": o["po"], "quantity": o["quantity"],
                    "allocation": o["allocation"],
                    "disagreement": o["disagreement"],
                    "mean_iou": o["mean_iou"],
                    "changed_px_net": counts["changed_px"],
                    "changed_m2_net": s["changed_m2"],
                    "marked_but_unchanged": counts["marked_but_unchanged"],
                    "nodata_mismatch": counts["nodata_mismatch"],
                    "not_a_code": counts["not_a_code"]},
        "per_class": {str(c["code"]): {
            "name": cm_name(c["code"], names, None),
            "model_px": c["n_A"], "corrected_px": c["n_B"],
            "agree_px": c["n_same"], "producers_accuracy": c["rate_B"],
            "users_accuracy": c["rate_A"], "iou": c["iou"], "f1": c["f1"],
            "quantity_dis": c["q"] / 2.0, "allocation_dis": c["a"] / 2.0}
            for c in s["metrics"]["per_class"]},
        "transitions": [{"from": r["a_name"], "to": r["b_name"],
                         "from_code": r["a"], "to_code": r["b"],
                         "pixels": r["pixels"], "area_m2": r["area_m2"]}
                        for r in s["transitions"]],
        "logged": gross,
        "notes": notes,
        "files": sorted(files)}
    if s["bootstrap"] is not None:
        b = s["bootstrap"]
        body["bootstrap"] = {k: b.get(k) for k in (
            "resamples", "seed", "level", "method", "min_frames", "frames",
            "ci", "n_valid", "reason")}
    if people:
        p = {"kind": people.get("kind"), "path": people.get("path"),
             "unmatched": people.get("unmatched") or []}
        if people.get("kind") == "correction":
            p.update({"operator": people.get("operator"),
                      "name": people.get("name"),
                      "overall": people.get("overall"),
                      "other_nodata_mismatch":
                          counts.get("other_nodata_mismatch")})
        else:
            p.update({"readings": people.get("readings"),
                      "overall": people.get("overall")})
        body["people"] = p
        body["side_by_side"] = s["side_by_side"]
    if result.get("map"):
        body["maps"] = {"pairs": os.path.basename(result["map"]["path"]),
                        "pair_encoding": "1 + i*K + j over codes, i the "
                                         "model's index, j the corrected "
                                         "map's; 0 outside the scope or "
                                         "nodata",
                        "type": result["map"]["dtype"]}
    summary.update(body)
    return summary


#  One report, start to end
# =====================================================================
def mvc_report(recipe, record, owner_folder, people=None, target=None,
               progress=None, cancelled=None):
    """A whole report: the folder, the run, the tables, the rename.

    record is the correction's manifest (read, never written here),
    owner_folder its folder; target a report folder the user named, or None
    for reports/model_vs_corrected/<scope>_<stamp>/. On any failure, a
    cancel included, the .tmp folder goes and nothing else is touched.
    Returns the result, with "folder" the finished report."""
    scope = recipe.get("scope") or "whole"
    if recipe.get("write_map", True):
        # before a folder is made: the map must be one QGIS can open where
        # it is going (a GeoTIFF is, on any path GDAL can write; the check
        # is the same for every report that loads a file)
        stem = os.path.splitext(os.path.basename(
            recipe["corrected"]["path"]))[0]
        problem = report_open_problem(
            report_folder_guess(owner_folder, MVC_KIND, scope, target),
            [mvc_files(stem, scope)["pairs"]])
        if problem:
            raise ValueError(problem)
    if target:
        tmp, final = cmp_target(target)
    else:
        tmp, final = report_folder(owner_folder, MVC_KIND, scope)
    try:
        if recipe.get("write_map", True):
            stem = os.path.splitext(os.path.basename(
                recipe["corrected"]["path"]))[0]
            recipe = dict(recipe, map=os.path.join(
                tmp, mvc_files(stem, scope)["pairs"]),
                metadata=mvc_metadata(record, scope))
        else:
            recipe = dict(recipe, map=None)
        result = mvc_compare(recipe, progress, cancelled)
        if result["counts"]["scope_px"] == 0:
            raise ValueError("there is no pixel to compare on the %s"
                             % MVC_SCOPE_WORDS[scope])
        mvc_write(result, tmp, record, owner_folder, people)
        result["folder"] = report_finish(tmp, final)
        if result.get("map"):
            result["map"]["path"] = os.path.join(
                result["folder"], os.path.basename(result["map"]["path"]))
    except BaseException:
        report_abandon(tmp)
        raise
    result["created_utc"] = (result.get("summary_json") or {}).get(
        "created_utc") or report_utc()
    o = result["summarized"]["metrics"]["overall"]
    log("model vs corrected, %s: the model agrees on %s of %d px, in %s"
        % (MVC_SCOPE_WORDS[scope], mvc_percent(o["po"]),
           result["summarized"]["n"], result["folder"]))
    return result


def mvc_percent(v, digits=1):
    f = _mvc_num(v)
    return "—" if f is None else "%.*f %%" % (digits, 100.0 * f)


#  What the setup window shows before a run
# =====================================================================
def mvc_counts(copy, band_no, changes=None, reviewed=None, polygons=None,
               strip_rows=None):
    """The pixels of the corrected map, of the ground swept (reviewed or
    changed) and, with polygons [{fid, wkb}], inside them and swept inside
    them: {map_px, swept_px, reviewed_px, changes_px, poly_px,
    poly_swept_px}. Read a strip at a time, nothing written."""
    rows_at = int(strip_rows or STRIP_ROWS)
    ds, band = _mvc_open(copy, band_no, "the corrected map")
    w, h = ds.RasterXSize, ds.RasterYSize
    gt = tuple(ds.GetGeoTransform())
    wkt = ds.GetProjection() or ""
    nodata = band.GetNoDataValue()
    chg = _mvc_side(changes, 1, w, h, "the record of changed pixels")
    rev = _mvc_side(reviewed, 1, w, h, "the record of the ground swept")
    polys = mvc_polygons(polygons, gt, w, h) if polygons is not None else []
    out = {"map_px": 0, "swept_px": 0, "reviewed_px": 0, "changes_px": 0,
           "poly_px": 0, "poly_swept_px": 0, "width": w, "height": h,
           "reviewed": rev is not None}
    try:
        for row in range(0, h, rows_at):
            take = min(rows_at, h - row)
            valid, _ = mvc_valid(band.ReadAsArray(0, row, w, take), nodata)
            c = chg[1].ReadAsArray(0, row, w, take).astype(bool) \
                if chg is not None else np.zeros(valid.shape, dtype=bool)
            r = rev[1].ReadAsArray(0, row, w, take).astype(bool) \
                if rev is not None else np.zeros(valid.shape, dtype=bool)
            out["map_px"] += int(valid.sum())
            out["swept_px"] += int((valid & (c | r)).sum())
            out["reviewed_px"] += int((valid & r).sum())
            out["changes_px"] += int((valid & c).sum())
            if polys:
                inside = np.zeros(valid.shape, dtype=bool)
                for p in polys:
                    if p["window"] is None:
                        continue
                    c0, r0, c1, r1 = p["window"]
                    lo, hi = max(r0, row), min(r1, row + take)
                    if hi <= lo:
                        continue
                    inside[lo - row:hi - row, c0:c1] |= cmp_burn(
                        p["geom"], (gt[0] + c0 * gt[1], gt[1], 0.0,
                                    gt[3] + lo * gt[5], 0.0, gt[5]),
                        c1 - c0, hi - lo, wkt).astype(bool)
                inside &= valid
                out["poly_px"] += int(inside.sum())
                out["poly_swept_px"] += int((inside & (c | r)).sum())
    finally:
        band = None
        ds = None
        chg = rev = None
    return out


#  The record of the ground swept, kept stroke by stroke
# =====================================================================
def mvc_read_window(path, col, row, w, h):
    """A window of band 1 of a record, through a handle of its own."""
    ds = open_raster(long_path(path))
    if ds is None:
        raise IOError("cannot read %s" % os.path.basename(path))
    try:
        got = ds.GetRasterBand(1).ReadAsArray(int(col), int(row), int(w),
                                              int(h))
    finally:
        ds = None
    if got is None:
        raise IOError("cannot read %s" % os.path.basename(path))
    return np.asarray(got)


class ReviewedHook(object):
    """Which pixels a stroke of Correct went over, beside the copy.

    The stroke's whole footprint ("inside"), not only the pixels it
    changed: a stroke over ground the model had right says the ground was
    looked at, and that is what the swept scope of Model vs corrected needs.
    Only strokes that are written are told (a stroke refused, or one with
    nothing to change, is not), so the record holds what the person applied.

    Each stroke reads its window of the record, ORs the footprint in and
    writes the window back, through a handle opened for that alone, as
    Correct writes the copy: the file on disk is whole between any two
    strokes, whatever happens to QGIS. What the window held is kept for the
    undo, which writes it back.

    A correction made by an earlier build has no record. Nothing is made
    when it opens; at its first stroke the record is started, empty, and
    the manifest says from which stroke on it is complete: "reviewed_since"
    is the number of strokes made before it, whose footprints are not
    known."""

    def __init__(self, section):
        self.section = section
        record = getattr(section, "record", None) or {}
        copy = getattr(section, "path", "") or ""
        self.path = reviewed_path_of(record, copy) if copy else ""
        self.broken = not bool(self.path)
        self.checked = False

    # ------------------------------------------------------------ the file
    def _own(self, section):
        try:
            return bool(section.own_book())
        except Exception:
            return False

    def _tell_manifest(self, section, since):
        """The record named in the correction's own manifest. A correction
        still kept inside an annotation campaign has none of its own, and
        nothing is written into the campaign's for it."""
        if not self._own(section):
            return
        record = section.record
        changed = False
        name = os.path.basename(self.path)
        if record.get("reviewed") != name:
            record["reviewed"] = name
            changed = True
        if "reviewed_since" not in record or since is not None:
            record["reviewed_since"] = int(since or 0)
            changed = True
        if changed:
            try:
                section.book.save()
            except Exception as err:
                log("cannot update the manifest: %s" % err)

    def ready(self, section, n):
        """The record there and on the copy's size, started when it is not.
        n is the number of the stroke being recorded."""
        if self.broken:
            return False
        name = os.path.basename(self.path)
        if not os.path.exists(long_path(self.path)):
            try:
                build_changes(section.path, self.path,
                              name=REVIEWED_BAND_NAME,
                              meaning=REVIEWED_MEANING,
                              colour=REVIEWED_COLOUR)
            except Exception as err:
                self.broken = True
                log("cannot start %s: %s. The strokes still work; which "
                    "ground they swept is not remembered." % (name, err),
                    loud=True)
                return False
            before = max(0, int(n) - 1)
            if before:
                log("the ground the strokes sweep is recorded from now on, "
                    "in %s: the %d stroke%s made before left no footprint, "
                    "and only the pixels %s changed are known"
                    % (name, before, "" if before == 1 else "s",
                       "it" if before == 1 else "they"), loud=True)
            else:
                log("the ground the strokes sweep is recorded in %s" % name)
            self._tell_manifest(section, before)
            self.checked = True
            return True
        if not self.checked:
            try:
                ds = gdal.Open(long_path(self.path))
                size = (ds.RasterXSize, ds.RasterYSize) if ds is not None \
                    else None
                ds = None
            except Exception:
                size = None
            if size != (section.nx, section.ny):
                self.broken = True
                log("%s is not the record of this copy (%s pixels against "
                    "%d x %d): it is left as it is and not used. The strokes "
                    "still work." % (name, "%d x %d" % size if size
                                     else "unreadable", section.nx,
                                     section.ny), loud=True)
                return False
            self.checked = True
            if section.record.get("reviewed") != name:
                self._tell_manifest(section, section.record.get(
                    "reviewed_since", max(0, int(n) - 1)))
        return True

    # ----------------------------------------------------------- the hooks
    def stroke(self, section, ctx):
        if not self.ready(section, ctx.get("n") or 1):
            return None
        col, row = int(ctx["col"]), int(ctx["row"])
        inside = np.asarray(ctx["inside"], dtype=bool)
        h, w = inside.shape
        try:
            old = mvc_read_window(self.path, col, row, w, h)
            new = (old.astype(bool) | inside).astype(np.uint8)
            if np.array_equal(new, old):
                return {"col": col, "row": row, "old": None}
            write_window(self.path, 1, new, col, row)
        except Exception as err:
            self.broken = True
            log("%s. The strokes still work; which ground they sweep from "
                "now on is not remembered." % err, loud=True)
            return None
        return {"col": col, "row": row, "old": old}

    def undo(self, section, state):
        if not state or state.get("old") is None or self.broken:
            return
        try:
            write_window(self.path, 1, state["old"], state["col"],
                         state["row"])
        except Exception as err:
            log("the undo is made, but %s still counts its ground as swept: "
                "%s" % (os.path.basename(self.path), err), loud=True)

    def files(self, section):
        if not self.path:
            return []
        return [self.path, self.path + ".aux.xml"]

    def tally_lines(self, section):
        line = mvc_tally_line(getattr(section, "record", None) or {})
        return [line] if line else []


def mvc_tally_line(record):
    """The quiet line under the tally of Correct: the newest Model vs
    corrected report of this correction, from its manifest."""
    found = [e for e in record.get("reports") or []
             if e.get("kind") == MVC_KIND]
    if not found:
        return ""
    head = found[-1].get("headline") or {}
    scope = MVC_SCOPE_WORDS.get(head.get("scope"), head.get("scope") or "")
    pixels = head.get("pixels")
    return ("last measured, %s: the model agrees on %s of %s px"
            % (scope, mvc_percent(head.get("oa")),
               "{:,}".format(int(pixels)).replace(",", " ")
               if isinstance(pixels, (int, float)) else "?"))


#  What Check says of it
# =====================================================================
def mvc_finding(level, what, detail=""):
    """A line of Check, made by Check's own Finding (doctor comes after this
    module, so it is looked up when a line is made)."""
    import importlib
    package = globals().get("__package__") or ""
    if package:
        doctor = importlib.import_module(".doctor", package)
        return doctor.Finding(level, what, detail)
    return globals()["Finding"](level, what, detail)


def reviewed_findings(owner):
    """Check, on the record of the ground swept beside the copy."""
    data = getattr(owner, "data", None) or {}
    copy = getattr(owner, "working_path", "") or ""
    if not copy or not os.path.exists(long_path(copy)):
        return []
    path = reviewed_path_of(data, copy)
    name = os.path.basename(path)
    there = os.path.exists(long_path(path))
    since = data.get("reviewed_since")
    if not there:
        if data.get("reviewed"):
            return [mvc_finding(
                "note", "%s is not beside the working copy" % name,
                "which ground the strokes swept is not known: a new, empty "
                "record starts at the next stroke, and Model vs corrected "
                "counts the changed pixels alone as swept until then")]
        return [mvc_finding(
            "ok", "the ground the strokes sweep is recorded from the next "
            "stroke on", "this correction was made before it was recorded"
            if int(data.get("operations", 0) or 0) else "")]
    try:
        ds = gdal.Open(long_path(path))
        size = (ds.RasterXSize, ds.RasterYSize) if ds is not None else None
        same = mvc_grid_of(copy)
        swept = 0
        if ds is not None and same is not None and size == same[:2]:
            band = ds.GetRasterBand(1)
            for row in range(0, size[1], STRIP_ROWS):
                take = min(STRIP_ROWS, size[1] - row)
                swept += int((band.ReadAsArray(0, row, size[0], take) != 0)
                             .sum())
            band = None
        ds = None
    except Exception:
        size, same, swept = None, None, 0
    if size is None or same is None or size != same[:2]:
        return [mvc_finding(
            "note", "%s is not on the grid of the working copy" % name,
            "it is not used: the strokes leave no footprint in it")]
    words = "%s: %d px swept by the strokes" % (name, swept)
    if since:
        words += ", from stroke %d on" % (int(since) + 1)
    return [mvc_finding("ok", words)]
