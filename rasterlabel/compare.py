"""rasterlabel.compare

Two readings of the same frames compared: how far they agree, and where.

A reading is one operator in one pass (campaign.operator_word and
pass_number, nothing normalised again here). Two of them, A and B, are
compared on the frames both of them annotated, and under the default rule
only on the frames both of them closed: the area rule of every other place
in the program, campaign.reading_shares above CLOSED_SHARE. Each frame is
burned on the campaign's own grid with the same Stencil Whole raster burns
its "one reading" masks with, points laid over the areas only when asked,
so the two arrays compared are, pixel for pixel, the masks Whole raster
writes for each reading.

What comes out goes in a report folder of its own,
reports/agreement/<tagA>_vs_<tagB>_<stamp>/, written under .tmp and renamed
when it is whole (reports.py): the confusion matrix with "unlabelled" as a
row and a column of its own, per class IoU, F1 (Dice) and the agreement
seen from A and from B, Cohen's kappa as an agreement statistic, quantity
and allocation disagreement (with exchange and shift), each pooled, as the
median and quartiles over frames, and with a frame bootstrap interval; the
disagreement map (agree, disagree, only A, only B, neither), the map of
pairs (1 + i*K + j) and a GeoPackage of the disagreement polygons and the
frames with their numbers.

GDAL, OGR and numpy only, no widget and no QGIS layer: the panel and the
Processing algorithm run the same functions, the second one off the main
thread. Nothing here writes the manifest or the package; the panel records
the report in the manifest itself, through Campaign.save().

    cmp_marks(package)                 what each reading drew, attributes only
    cmp_plan(data, package, A, B, ...) which frames, and why the others not
    cmp_run(plan, ..., folder)         the burn, the maps and the matrices
    cmp_write(result, folder)          the tables and summary.json
    cmp_compare(recipe, ...)           the three in a report folder of its own
"""
import math
import os

from datetime import datetime

import numpy as np
from osgeo import gdal, ogr, osr

from .constants import (BOOTSTRAP_LEVEL, BOOTSTRAP_MIN_FRAMES, BUILD,
                        CLOSED_SHARE, DISAGREEMENT_CLASSES,
                        MAX_POLYGONS_PER_FRAME, OPERATOR_BLANK,
                        VERSION)
from .naming import long_path, tidy
from .errors import log
from .agreement import (cm_codes, cm_confusion, cm_disagreement_values,
                        cm_long_rows, cm_name, cm_pair_dtype, cm_pair_of,
                        cm_pair_values, cm_summarize, cm_wide_rows)
from .reports import (report_abandon, report_artifact_name, report_csv,
                      report_finish, report_folder, report_folder_guess,
                      report_header, report_headline, report_inputs,
                      report_json, report_open_problem, report_utc)
from .campaign import (comparison_kind, frame_design, operator_word,
                       pair_tag, pass_number, reading_label, reading_shares,
                       reading_tag)
from .geometry import on_edge
from .rasters import Stencil
from .report_rasters import rr_finish, rr_open, rr_pair_entries

CMP_KIND = "agreement"
CMP_RULES = ("closed", "touched")
CMP_KIND_WORDS = {
    "inter": "Two operators, one pass (inter-observer)",
    "intra": "One operator, two passes (intra-observer)",
    "other": "Any two readings",
}
CMP_WHOLE = "(whole)"
CMP_KAPPA_NOTE = ("kappa is an agreement statistic between two readings, not "
                  "a measure of accuracy (Pontius and Millones 2011; Foody "
                  "2020)")
CMP_SAME_READING = "A and B are the same reading: there is nothing to compare."
CMP_TABLES = ("polygons", "points")


class CmpCancelled(Exception):
    """The comparison was stopped from its progress window."""


#  What each reading drew
# =====================================================================
def _cmp_field(defn, name):
    for i in range(defn.GetFieldCount()):
        if defn.GetFieldDefn(i).GetName().lower() == name:
            return defn.GetFieldDefn(i).GetName()
    return None


def cmp_marks(package, tables=CMP_TABLES):
    """{reading: {table: {"n", "codes", "frames": {tile: (n, first, last)},
    "no_frame", "first", "last", "size_px"}}} of the package, read with SQL
    over the attributes only, from a package opened read only.

    first and last are the earliest and the latest "created" of the marks;
    a mark with an empty tile_id is counted under no_frame."""
    out = {}
    try:
        ds = ogr.Open(long_path(package), 0) if isinstance(package, str) \
            else package
    except Exception as err:
        log("cannot read the marks of %s: %s" % (package, err))
        return out
    if ds is None:
        return out
    for table in tables:
        lyr = ds.GetLayerByName(table)
        if lyr is None:
            continue
        defn = lyr.GetLayerDefn()
        col = {k: _cmp_field(defn, k) for k in ("operator", "pass_no",
                                                "tile_id", "class_code",
                                                "created", "size_px")}
        lyr = None

        def sql(k):
            return '"%s"' % col[k] if col[k] else "NULL"
        query = ('SELECT %s, %s, %s, %s, COUNT(*), MIN(%s), MAX(%s), MAX(%s) '
                 'FROM "%s" GROUP BY 1, 2, 3, 4'
                 % (sql("operator"), sql("pass_no"), sql("tile_id"),
                    sql("class_code"), sql("created"), sql("created"),
                    sql("size_px"), table))
        try:
            rows = ds.ExecuteSQL(query)
        except Exception as err:
            log("cannot count the marks of %s: %s" % (table, err))
            rows = None
        if rows is None:
            continue
        try:
            for f in rows:
                r = (operator_word(f.GetField(0)), pass_number(f.GetField(1)))
                held = out.setdefault(r, {}).setdefault(table, {
                    "n": 0, "codes": set(), "frames": {}, "no_frame": 0,
                    "first": None, "last": None, "size_px": 1})
                n = int(f.GetField(4) or 0)
                tid = f.GetField(2)
                tid = None if tid is None or str(tid) == "" else str(tid)
                try:
                    code = int(f.GetField(3) or 0)
                except (TypeError, ValueError):
                    code = 0
                first, last = f.GetField(5), f.GetField(6)
                held["n"] += n
                held["codes"].add(code)
                try:
                    held["size_px"] = max(held["size_px"],
                                          int(f.GetField(7) or 1))
                except (TypeError, ValueError):
                    pass
                if tid is None:
                    held["no_frame"] += n
                else:
                    was = held["frames"].get(tid, (0, None, None))
                    held["frames"][tid] = (was[0] + n, _cmp_min(was[1], first),
                                           _cmp_max(was[2], last))
                held["first"] = _cmp_min(held["first"], first)
                held["last"] = _cmp_max(held["last"], last)
        finally:
            ds.ReleaseResultSet(rows)
    ds = None
    return out


def _cmp_min(a, b):
    a, b = (a or None), (b or None)
    return b if a is None else a if b is None else min(str(a), str(b))


def _cmp_max(a, b):
    a, b = (a or None), (b or None)
    return b if a is None else a if b is None else max(str(a), str(b))


def cmp_readings(marks, points_in=False):
    """The readings that can be compared, in the order the windows list
    them: by pass, then by operator. A reading with only lines or boxes is
    not one: they are not in the mask."""
    found = [r for r, t in marks.items()
             if t.get("polygons", {}).get("n")
             or (points_in and t.get("points", {}).get("n"))]
    return sorted(found, key=lambda r: (r[1], r[0]))


def _cmp_touched(marks, reading, points_in):
    held = marks.get(reading) or {}
    frames = {}
    for table in ("polygons",) + (("points",) if points_in else ()):
        for tid, info in (held.get(table) or {}).get("frames", {}).items():
            was = frames.get(tid, (0, None, None))
            frames[tid] = (was[0] + info[0], _cmp_min(was[1], info[1]),
                           _cmp_max(was[2], info[2]))
    return frames


def cmp_frames(package):
    """[(tile_id, OGR geometry)] of the tiles table, first of each tile_id,
    read only; frames with no tile_id or no area are left out."""
    out = []
    try:
        ds = ogr.Open(long_path(package), 0)
    except Exception:
        ds = None
    if ds is None:
        return out
    lyr = ds.GetLayerByName("tiles")
    if lyr is not None:
        name = _cmp_field(lyr.GetLayerDefn(), "tile_id")
        seen = set()
        if name:
            for f in lyr:
                tid = f.GetField(name)
                g = f.GetGeometryRef()
                if tid is None or str(tid) == "" or str(tid) in seen \
                        or g is None or g.IsEmpty() or not g.GetArea() > 0:
                    continue
                seen.add(str(tid))
                out.append((str(tid), g.Clone()))
    lyr = None
    ds = None
    return out


def cmp_wkt(package):
    """The system of the campaign's tables as WKT, "" for a campaign on a
    picture (or the GeoPackage's stand-in for no system)."""
    try:
        ds = ogr.Open(long_path(package), 0)
    except Exception:
        return ""
    if ds is None:
        return ""
    wkt = ""
    for table in ("polygons", "tiles", "points"):
        lyr = ds.GetLayerByName(table)
        srs = lyr.GetSpatialRef() if lyr is not None else None
        if srs is not None and "Undefined" not in (srs.GetName() or ""):
            wkt = srs.ExportToWkt()
            break
    lyr = srs = None
    ds = None
    return wkt


def cmp_grid(data):
    """The campaign's grid as a geotransform, north up: (ox, px, 0, oy, 0,
    -py), from the manifest's origin and pixel_crs."""
    grid = data.get("grid") or {}
    ox, oy = [float(v) for v in grid.get("origin") or (0.0, 0.0)]
    px, py = [abs(float(v)) for v in grid.get("pixel_crs")
              or grid.get("pixel_m") or (1.0, 1.0)]
    return (ox, px, 0.0, oy, 0.0, -py)


def cmp_pixel_m2(data):
    """The ground of one pixel in m², or None when the campaign has no
    system (a picture: its pixels are not metres of anything)."""
    grid = data.get("grid") or {}
    if not grid.get("crs"):
        return None
    try:
        px, py = [abs(float(v)) for v in grid.get("pixel_m")]
    except (TypeError, ValueError):
        return None
    return px * py if px > 0 and py > 0 else None


def cmp_window(gt, bbox):
    """(c0, r0, w, h) of a box on the grid, snapped outwards with the
    floor and ceil and the edge tolerance of geometry.snap; not clipped,
    since the campaign's grid has no edge."""
    xmin, ymin, xmax, ymax = bbox
    c0 = int(math.floor(on_edge((xmin - gt[0]) / gt[1])))
    c1 = int(math.ceil(on_edge((xmax - gt[0]) / gt[1])))
    r0 = int(math.floor(on_edge((gt[3] - ymax) / -gt[5])))
    r1 = int(math.ceil(on_edge((gt[3] - ymin) / -gt[5])))
    return c0, r0, max(1, c1 - c0), max(1, r1 - r0)


def cmp_window_gt(gt, c0, r0):
    return (gt[0] + c0 * gt[1], gt[1], 0.0, gt[3] + r0 * gt[5], 0.0, gt[5])


def _cmp_bbox(geom):
    xmin, xmax, ymin, ymax = geom.GetEnvelope()
    return (xmin, ymin, xmax, ymax)


def _cmp_box_geom(bbox):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in ((bbox[0], bbox[1]), (bbox[2], bbox[1]), (bbox[2], bbox[3]),
                 (bbox[0], bbox[3]), (bbox[0], bbox[1])):
        ring.AddPoint_2D(x, y)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly


def _cmp_extent(package, readings, points_in, pixel=1.0):
    """The box around every mark of these readings, for a campaign with no
    frames, grown by the largest point footprint."""
    box = None
    try:
        ds = ogr.Open(long_path(package), 0)
    except Exception:
        ds = None
    if ds is None:
        return None
    for table in ("polygons",) + (("points",) if points_in else ()):
        lyr = ds.GetLayerByName(table)
        if lyr is None:
            continue
        defn = lyr.GetLayerDefn()
        who = defn.GetFieldIndex("operator")
        when = defn.GetFieldIndex("pass_no")
        size = defn.GetFieldIndex("size_px")
        for f in lyr:
            r = (operator_word(f.GetField(who) if who >= 0 else None),
                 pass_number(f.GetField(when) if when >= 0 else None))
            g = f.GetGeometryRef()
            if r not in readings or g is None or g.IsEmpty():
                continue
            xmin, xmax, ymin, ymax = g.GetEnvelope()
            if table == "points":
                pad = pixel * (max(1, int(f.GetField(size) or 1))
                               if size >= 0 else 1)
                xmin, ymin, xmax, ymax = xmin - pad, ymin - pad, \
                    xmax + pad, ymax + pad
            box = (xmin, ymin, xmax, ymax) if box is None else (
                min(box[0], xmin), min(box[1], ymin), max(box[2], xmax),
                max(box[3], ymax))
        lyr = None
    ds = None
    return box


#  Which frames
# =====================================================================
def cmp_names(data):
    """{code: name} of the campaign's classes, retired ones included and
    said so, so a retired code still has its name."""
    out = {}
    for c in data.get("classes") or []:
        try:
            code = int(c.get("code"))
        except (TypeError, ValueError):
            continue
        name = str(c.get("name") or "class %d" % code)
        out[code] = name + (" (retired)" if c.get("retired") else "")
    return out


def cmp_colours(data):
    out = {}
    for c in data.get("classes") or []:
        try:
            out[int(c.get("code"))] = str(c.get("colour") or "")
        except (TypeError, ValueError):
            continue
    return out


def cmp_share_words(side, share):
    return "%s %.1f %%" % (side, 100.0 * float(share or 0.0))


def cmp_plan(data, package, a, b, frame_rule="closed", points_in=False,
             marks=None, shares=None, frames=None):
    """Which frames A and B are compared on, and why each other one is not.
    Reads attributes, the frames and the areas of the polygons; burns
    nothing, writes nothing.

    marks, shares and frames are what cmp_marks, campaign.reading_shares and
    cmp_frames answer, passed in by a window that asks again at every change
    and read here when left out."""
    a = (operator_word(a[0]), pass_number(a[1]))
    b = (operator_word(b[0]), pass_number(b[1]))
    rule = frame_rule if frame_rule in CMP_RULES else "closed"
    untiled = not bool(data.get("with_tiles", True))
    if untiled:
        rule = "touched"
    plan = {"A": a, "B": b, "kind": comparison_kind(a, b),
            "frame_rule": rule, "asked_rule": frame_rule,
            "points_in": bool(points_in), "untiled": untiled,
            "frames": [], "used": [], "left_out": [], "notes": [],
            "counts": {"closed": 0, "touched": 0},
            "unfinished": {"A": [], "B": []}, "codes": [0],
            "refusal": None, "delay": {}}
    if a == b:
        plan["refusal"] = CMP_SAME_READING
        return plan
    if marks is None:
        marks = cmp_marks(package)
    touched = {"A": _cmp_touched(marks, a, points_in),
               "B": _cmp_touched(marks, b, points_in)}
    codes = set(cmp_names(data)) | {0}
    for side, r in (("A", a), ("B", b)):
        for table in ("polygons",) + (("points",) if points_in else ()):
            held = (marks.get(r) or {}).get(table) or {}
            codes |= set(held.get("codes") or ())
            if held.get("no_frame") and not untiled:
                plan["notes"].append(
                    "%d %s of %s %s no frame (tile_id empty) and %s not "
                    "compared" % (held["no_frame"], table, reading_label(r),
                                  "has" if held["no_frame"] == 1 else "have",
                                  "is" if held["no_frame"] == 1 else "are"))
    plan["codes"] = cm_codes(codes)
    if OPERATOR_BLANK in (a[0], b[0]):
        plan["notes"].append("the marks of %s carry no operator's name and "
                             "may be the work of several people"
                             % OPERATOR_BLANK)
    if untiled:
        box = _cmp_extent(package, {a, b}, points_in,
                          max(cmp_grid(data)[1], -cmp_grid(data)[5]))
        if box is None:
            plan["refusal"] = ("Neither reading has an area to compare.")
            return plan
        plan["frames"].append({"tile_id": CMP_WHOLE, "bbox": box,
                               "geometry": None, "share_A": None,
                               "share_B": None, "closed_A": None,
                               "closed_B": None, "used": True,
                               "reason": ""})
        plan["used"].append(CMP_WHOLE)
        plan["counts"] = {"closed": 0, "touched": 1}
        plan["notes"].append("a campaign with no frames is compared as one "
                             "region: one region is not a sample of frames, "
                             "so there is no spread over frames and no "
                             "interval")
        plan["delay"][CMP_WHOLE] = _cmp_delay(
            ((marks.get(b) or {}).get("polygons") or {}).get("first"),
            ((marks.get(a) or {}).get("polygons") or {}).get("last"))
        return plan
    if frames is None:
        frames = cmp_frames(package)
    geoms = dict(frames)
    both = sorted(set(touched["A"]) & set(touched["B"]))
    if shares is None:
        shares = reading_shares(package, sorted(set(touched["A"])
                                                | set(touched["B"])))
    for side, r in (("A", a), ("B", b)):
        for tid in sorted(touched[side]):
            s = (shares.get(tid) or {}).get(r, 0.0)
            if tid in geoms and not s > CLOSED_SHARE:
                plan["unfinished"][side].append((tid, s))
    for tid in both:
        sa = (shares.get(tid) or {}).get(a, 0.0)
        sb = (shares.get(tid) or {}).get(b, 0.0)
        entry = {"tile_id": tid, "geometry": geoms.get(tid),
                 "bbox": _cmp_bbox(geoms[tid]) if tid in geoms else None,
                 "share_A": sa, "share_B": sb, "closed_A": sa > CLOSED_SHARE,
                 "closed_B": sb > CLOSED_SHARE, "used": False, "reason": ""}
        if tid not in geoms:
            entry["reason"] = "no frame %s in the tiles" % tid
        else:
            plan["counts"]["touched"] += 1
            if entry["closed_A"] and entry["closed_B"]:
                plan["counts"]["closed"] += 1
            if rule == "closed" and not (entry["closed_A"]
                                         and entry["closed_B"]):
                entry["reason"] = ", ".join(
                    cmp_share_words(side, s) for side, s, c in
                    (("A", sa, entry["closed_A"]),
                     ("B", sb, entry["closed_B"])) if not c)
            else:
                entry["used"] = True
        plan["frames"].append(entry)
        plan["delay"][tid] = _cmp_delay(touched["B"][tid][1],
                                        touched["A"][tid][2])
    for side, other in (("A", "B"), ("B", "A")):
        for tid in sorted(set(touched[side]) - set(touched[other])):
            plan["frames"].append({"tile_id": tid, "geometry": geoms.get(tid),
                                   "bbox": None, "share_A": None,
                                   "share_B": None, "closed_A": None,
                                   "closed_B": None, "used": False,
                                   "reason": "only %s" % side})
    plan["frames"].sort(key=lambda f: f["tile_id"])
    plan["used"] = [f["tile_id"] for f in plan["frames"] if f["used"]]
    plan["left_out"] = [{"tile_id": f["tile_id"], "reason": f["reason"]}
                        for f in plan["frames"] if not f["used"]]
    return plan


def _cmp_when(text):
    try:
        when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when.replace(tzinfo=None) if when.tzinfo is None else \
        when.astimezone().replace(tzinfo=None)


def _cmp_delay(first_b, last_a):
    """Hours from A's last mark in a frame to B's first one there."""
    fb, la = _cmp_when(first_b), _cmp_when(last_a)
    if fb is None or la is None:
        return None
    return (fb - la).total_seconds() / 3600.0


def cmp_left_out_words(plan, most=3):
    """"t007 (B 81.0 %), t012 (only A), +3 more": the frames left out."""
    gone = plan.get("left_out") or []
    words = ["%s (%s)" % (g["tile_id"], g["reason"]) for g in gone[:most]]
    if len(gone) > most:
        words.append("+%d more" % (len(gone) - most))
    return ", ".join(words)


def cmp_label(a, b):
    return pair_tag(a, b)


#  The burn
# =====================================================================
def cmp_burn(geom, gt, w, h, wkt=""):
    """1 where the centre of a pixel of the window is inside geom: the
    centre rule of the whole program (GDAL with ALL_TOUCHED off). The
    window and the frame in the one system, so nothing is transformed."""
    target = gdal.GetDriverByName("MEM").Create("", int(w), int(h), 1,
                                                gdal.GDT_Byte)
    target.SetGeoTransform(gt)
    srs = _cmp_srs(wkt)
    if srs is not None:
        target.SetProjection(wkt)
    target.GetRasterBand(1).Fill(0)
    source = Stencil.in_memory("frame")
    layer = source.CreateLayer("f", srs, ogr.wkbUnknown)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(geom)
    layer.CreateFeature(feature)
    feature = None
    gdal.RasterizeLayer(target, [1], layer, burn_values=[1],
                        options=["ALL_TOUCHED=FALSE"])
    out = target.GetRasterBand(1).ReadAsArray()
    layer = None
    source = None
    target = None
    return out


def _cmp_srs(wkt):
    if not wkt:
        return None
    srs = osr.SpatialReference()
    try:
        srs.ImportFromWkt(wkt)
    except Exception:
        return None
    try:
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    except Exception:
        pass
    return srs


def _cmp_kind_of(ca, cb):
    if ca and cb:
        return "disagree"
    return "only_A" if ca else "only_B"


def _cmp_polygons(values, wgt, srs, codes, names, tid, pixel_area, pixel_m2):
    """The 4-connected regions of one pair of classes where A and B differ,
    in one frame, as rows for the "disagreement" layer; None when there are
    more than MAX_POLYGONS_PER_FRAME of them."""
    h, w = values.shape
    mem = gdal.GetDriverByName("MEM").Create("", w, h, 1, gdal.GDT_Int32)
    mem.SetGeoTransform(wgt)
    band = mem.GetRasterBand(1)
    band.WriteArray(values.astype(np.int32))
    mask = gdal.GetDriverByName("MEM").Create("", w, h, 1, gdal.GDT_Byte)
    mask.SetGeoTransform(wgt)
    mask.GetRasterBand(1).WriteArray((values > 0).astype(np.uint8))
    source = Stencil.in_memory("p")
    layer = source.CreateLayer("p", srs, ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(band, mask.GetRasterBand(1), layer, 0, [])
    if layer.GetFeatureCount() > MAX_POLYGONS_PER_FRAME:
        layer = source = mem = mask = band = None
        return None
    rows = []
    for f in layer:
        pair = cm_pair_of(f.GetField(0), codes)
        if pair is None:
            continue
        ca, cb = pair
        g = f.GetGeometryRef()
        pixels = int(round(g.GetArea() / pixel_area)) if pixel_area else 0
        rows.append({"tile_id": tid, "kind": _cmp_kind_of(ca, cb),
                     "code_A": ca, "name_A": cm_name(ca, names),
                     "code_B": cb, "name_B": cm_name(cb, names),
                     "pixels": pixels,
                     "area_m2": pixels * pixel_m2 if pixel_m2 else None,
                     "wkb": ogr.ForceToMultiPolygon(g.Clone()).ExportToWkb()})
    layer = source = mem = mask = band = None
    return rows


CMP_DIS_FIELDS = [("tile_id", "s"), ("kind", "s"), ("code_A", "i"),
                  ("name_A", "s"), ("code_B", "i"), ("name_B", "s"),
                  ("pixels", "i"), ("area_m2", "r")]
CMP_FRAME_FIELDS = [("tile_id", "s"), ("used", "i"), ("reason", "s"),
                    ("share_A", "r"), ("share_B", "r"), ("coverage_A", "r"),
                    ("coverage_B", "r"), ("pixels", "i"), ("both", "i"),
                    ("only_A", "i"), ("only_B", "i"), ("neither", "i"),
                    ("overall", "r"), ("kappa", "r"), ("quantity", "r"),
                    ("allocation", "r"), ("mean_iou", "r"), ("delay_h", "r")]


def _cmp_layer(ds, name, srs, kind, fields):
    lyr = ds.CreateLayer(name, srs, kind, ["GEOMETRY_NAME=geom"])
    types = {"s": ogr.OFTString, "i": ogr.OFTInteger, "r": ogr.OFTReal}
    for fname, t in fields:
        lyr.CreateField(ogr.FieldDefn(fname, types[t]))
    return lyr


def _cmp_put(lyr, row, fields, wkb):
    f = ogr.Feature(lyr.GetLayerDefn())
    for fname, t in fields:
        v = row.get(fname)
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            continue
        f.SetField(fname, int(v) if t == "i" else float(v) if t == "r"
                   else str(v))
    if wkb is not None:
        f.SetGeometry(ogr.CreateGeometryFromWkb(wkb))
    lyr.CreateFeature(f)
    f = None


def _cmp_window_into(ds, block, inside, x, y):
    """block written into the map at (x, y), inside the frame only: a frame
    beside another, or over it, leaves the other's pixels as they were."""
    band = ds.GetRasterBand(1)
    h, w = block.shape
    old = band.ReadAsArray(x, y, w, h)
    old[inside] = block[inside]
    band.WriteArray(old, x, y)
    band = None


def cmp_files(stem, label):
    """The names of the maps of a report: they say what they are once
    copied out of the folder, <stem>_agreement_<label>_<part>, made by
    report_artifact_name, which never cuts a name short: cut at 48
    letters, the disagreement map and the map of pairs of two long readings
    would come out under one name."""
    return {"disagreement": report_artifact_name(
                stem, CMP_KIND, label, "disagreement", ".tif"),
            "pairs": report_artifact_name(stem, CMP_KIND, label, "pairs",
                                          ".tif"),
            "vectors": report_artifact_name(stem, CMP_KIND, label, "",
                                            ".gpkg")}


def cmp_path_problem(data, owner_folder, a, b, target=None, windows=None):
    """"" if QGIS will be able to open the GeoPackage of the report of A and
    B, or why not, before anything is written: on Windows a path of 260
    characters or more is not one SQLite opens (see report_open_problem). The
    report goes where the person named, or in the campaign's reports
    folder."""
    label = cmp_label(a, b)
    stem = tidy(data.get("name") or "campaign", "campaign")
    folder = report_folder_guess(owner_folder, CMP_KIND, label, target)
    return report_open_problem(folder, [cmp_files(stem, label)["vectors"]],
                               windows)


def cmp_metadata(plan, data, extra):
    out = {"RASTERLABEL_VERSION": VERSION, "RASTERLABEL_BUILD": BUILD,
           "RASTERLABEL_REPORT": CMP_KIND,
           "RASTERLABEL_OWNER_ID": data.get("id", ""),
           "RASTERLABEL_AGREEMENT_A": reading_label(plan["A"]),
           "RASTERLABEL_AGREEMENT_B": reading_label(plan["B"]),
           "RASTERLABEL_AGREEMENT_KIND": plan["kind"],
           "RASTERLABEL_FRAMES_RULE": plan["frame_rule"],
           "RASTERLABEL_CLOSED_SHARE": "%g" % CLOSED_SHARE,
           "RASTERLABEL_POINTS_IN": "1" if plan["points_in"] else "0"}
    out.update(extra)
    return out


def cmp_run(plan, data, package, folder, stem, n_boot=2000, seed=1,
            progress=None, cancelled=None):
    """Burn the used frames of a plan, write the two maps and the
    GeoPackage into folder, and gather the matrices; returns the result
    that cmp_write turns into tables.

    progress(done, total) is told after each frame; cancelled() is asked
    after each frame, and True stops the run with CmpCancelled. The files
    are left where they are for the caller to take away."""
    gt = cmp_grid(data)
    wkt = cmp_wkt(package)
    srs = _cmp_srs(wkt)
    names = cmp_names(data)
    pixel_m2 = cmp_pixel_m2(data)
    pixel_area = abs(gt[1] * gt[5])
    codes = list(plan["codes"])
    label = cmp_label(plan["A"], plan["B"])
    files = cmp_files(stem, label)
    paths = {k: os.path.join(folder, v) for k, v in files.items()}
    used = [f for f in plan["frames"] if f["used"]]
    if not used:
        raise ValueError("no frame qualifies: nothing to compare")
    windows = {}
    for f in used:
        windows[f["tile_id"]] = cmp_window(gt, f["bbox"])
    c0 = min(w[0] for w in windows.values())
    r0 = min(w[1] for w in windows.values())
    c1 = max(w[0] + w[2] for w in windows.values())
    r1 = max(w[1] + w[3] for w in windows.values())
    out_gt = cmp_window_gt(gt, c0, r0)
    width, height = c1 - c0, r1 - r0
    pair_type = cm_pair_dtype(len(codes))
    a, b = plan["A"], plan["B"]
    keep_points = plan["points_in"]
    stencils = {"A": Stencil(package, "polygons", "class_code", wkt,
                             keep={a}),
                "B": Stencil(package, "polygons", "class_code", wkt,
                             keep={b})}
    if keep_points:
        for side, r in (("A", a), ("B", b)):
            stencils["dots_" + side] = Stencil(
                package, "points", "class_code", wkt, size_field="size_px",
                grid=gt, fallback=1, keep={r})
    dis_ds = rr_open(paths["disagreement"], out_gt, width, height, wkt,
                     "uint8", 0, "disagreement")
    pair_ds = rr_open(paths["pairs"], out_gt, width, height, wkt, pair_type,
                      0, "pair 1+i*K+j")
    vec = ogr.GetDriverByName("GPKG").CreateDataSource(
        long_path(paths["vectors"]))
    if vec is None:
        raise IOError("cannot write %s" % files["vectors"])
    dis_layer = _cmp_layer(vec, "disagreement", srs, ogr.wkbMultiPolygon,
                           CMP_DIS_FIELDS)
    frame_layer = _cmp_layer(vec, "frames", srs, ogr.wkbPolygon,
                             CMP_FRAME_FIELDS)
    matrices, ids, frames_out, notes = [], [], {}, list(plan["notes"])
    present_dis, present_pairs = set(), {}
    try:
        vec.StartTransaction()
        for i, f in enumerate(used):
            tid = f["tile_id"]
            fc, fr, w, h = windows[tid]
            wgt = cmp_window_gt(gt, fc, fr)
            if f.get("geometry") is not None:
                inside = cmp_burn(f["geometry"], wgt, w, h, wkt) > 0
            else:
                inside = np.ones((h, w), dtype=bool)
            arrays = {}
            # from the shapes in the pixels of the whole grid, as Whole and
            # the card burn, so that a pixel whose centre lies on a polygon
            # edge is the same pixel in all three
            at = {"whole": tuple(gt), "col": fc, "row": fr}
            for side in ("A", "B"):
                v = stencils[side].burn_into(wgt, w, h, wkt, **at)
                if keep_points:
                    d = stencils["dots_" + side].burn_into(wgt, w, h, wkt,
                                                           **at)
                    v = np.where(d > 0, d, v)
                v = np.asarray(v).astype(np.int64)
                v[~inside] = 0
                arrays[side] = v
            va, vb = arrays["A"], arrays["B"]
            n_in = int(inside.sum())
            m = cm_confusion(va[inside], vb[inside], codes)
            dis = cm_disagreement_values(va, vb, inside)
            pairs = cm_pair_values(va, vb, codes, inside)
            x, y = fc - c0, fr - r0
            _cmp_window_into(dis_ds, dis, inside, x, y)
            _cmp_window_into(pair_ds, pairs, inside, x, y)
            present_dis |= {int(v) for v in np.unique(dis[inside])}
            for value, n in zip(*np.unique(pairs[inside],
                                           return_counts=True)):
                present_pairs[int(value)] = present_pairs.get(int(value), 0) \
                    + int(n)
            differ = np.isin(dis, (2, 3, 4)) & inside
            rows = _cmp_polygons(np.where(differ, pairs, 0).astype(np.int64),
                                 wgt, srs, codes, names, tid, pixel_area,
                                 pixel_m2) if differ.any() else []
            if rows is None:
                notes.append("%s: more than %d separate places of "
                             "disagreement (salt and pepper), so it has no "
                             "polygons; the maps hold it"
                             % (tid, MAX_POLYGONS_PER_FRAME))
                rows = []
            for row in rows:
                _cmp_put(dis_layer, row, CMP_DIS_FIELDS, row["wkb"])
            matrices.append(m)
            ids.append(tid)
            frames_out[tid] = {
                "pixels": n_in,
                "coverage_A": float((va[inside] > 0).sum()) / n_in
                if n_in else float("nan"),
                "coverage_B": float((vb[inside] > 0).sum()) / n_in
                if n_in else float("nan"),
                "window": (fc, fr, w, h)}
            if progress is not None:
                progress(i + 1, len(used))
            if cancelled is not None and cancelled():
                raise CmpCancelled("cancelled after %d of %d frames"
                                   % (i + 1, len(used)))
        n_boot_run = 0 if plan["untiled"] else int(n_boot or 0)
        summary = cm_summarize(np.array(matrices, dtype=np.int64), ids,
                               codes, n_boot_run, seed, unlabelled=0,
                               kappa=True, min_frames=BOOTSTRAP_MIN_FRAMES,
                               pixel_m2=pixel_m2, level=BOOTSTRAP_LEVEL)
        by_id = {e["id"]: e["metrics"] for e in summary["frames"]}
        for f in plan["frames"]:
            tid = f["tile_id"]
            if f.get("geometry") is None and tid != CMP_WHOLE:
                continue
            m = by_id.get(tid)
            row = {"tile_id": tid, "used": 1 if f["used"] else 0,
                   "reason": f["reason"], "share_A": f["share_A"],
                   "share_B": f["share_B"],
                   "delay_h": plan["delay"].get(tid)}
            if m is not None:
                o, cn = m["overall"], m["counts"]
                row.update(frames_out[tid])
                row.update({"both": cn["both"], "only_A": cn["only_A"],
                            "only_B": cn["only_B"], "neither": cn["neither"],
                            "overall": o["po"], "kappa": o.get("kappa"),
                            "quantity": o["quantity"],
                            "allocation": o["allocation"],
                            "mean_iou": o["mean_iou"]})
            geom = f.get("geometry")
            if geom is None and tid == CMP_WHOLE:
                geom = _cmp_box_geom(f["bbox"])
            wkb = ogr.ForceToPolygon(geom.Clone()).ExportToWkb() \
                if geom is not None else None
            _cmp_put(frame_layer, row, CMP_FRAME_FIELDS, wkb)
        vec.CommitTransaction()
    except BaseException:
        # every handle let go before the caller takes the folder away:
        # Windows removes no file that is still open
        dis_ds = pair_ds = None
        raise
    finally:
        dis_layer = frame_layer = None
        vec = None
        for st in stencils.values():
            st.close()
    meta_dis = cmp_metadata(plan, data, {
        "RASTERLABEL_CODES": "0 outside;1 agree;2 disagree;3 only A;"
                             "4 only B;5 neither"})
    entries = [dict(c, present=c["code"] in present_dis)
               for c in DISAGREEMENT_CLASSES]
    rr_finish(dis_ds, paths["disagreement"], entries, meta_dis)
    dis_ds = None
    colours = cmp_colours(data)
    pair_names = {c: cm_name(c, names) for c in codes}
    pair_entries = rr_pair_entries(codes, pair_names, colours,
                                   present=set(present_pairs) - {0})
    meta_pairs = cmp_metadata(plan, data, {
        "RASTERLABEL_CODES": "value = 1 + i*K + j, i the index of A's code "
                             "and j of B's in %s; 0 outside"
                             % ",".join(str(c) for c in codes)})
    rr_finish(pair_ds, paths["pairs"], pair_entries, meta_pairs)
    pair_ds = None
    if plan["untiled"]:
        summary["spread"] = {}
    return {"plan": plan, "summary": summary, "codes": codes,
            "names": names, "colours": colours, "pixel_m2": pixel_m2,
            "grid": gt, "wkt": wkt, "frames": frames_out,
            "matrices": matrices, "ids": ids, "notes": notes,
            "files": files, "pairs_present": present_pairs,
            "pair_entries": pair_entries, "label": label,
            "extent": (out_gt, width, height)}


#  The tables
# =====================================================================
def _cmp_ci(boot, name):
    ci = (boot or {}).get("ci") or {}
    got = ci.get(name)
    return (got[0], got[1]) if got else (None, None)


def cmp_headline(result):
    s = result["summary"]
    o = s["pooled"]["overall"]
    boot = s["bootstrap"]
    names = result["names"]
    per_class = {}
    for c in s["pooled"]["per_class"]:
        if not (c["n_A"] or c["n_B"]):
            continue
        lo, hi = _cmp_ci(boot, "iou:%d" % c["code"])
        per_class[cm_name(c["code"], names)] = [c["iou"], lo, hi]
    plan = result["plan"]
    return report_headline(CMP_KIND, {
        "A": reading_label(plan["A"]), "B": reading_label(plan["B"]),
        "kind": plan["kind"], "frames_used": len(result["ids"]),
        "overall": o["po"], "overall_ci": list(_cmp_ci(boot, "po"))
        if boot.get("ci") else None,
        "kappa": o.get("kappa"), "kappa_ci": list(_cmp_ci(boot, "kappa"))
        if boot.get("ci") else None,
        "quantity": o["quantity"], "allocation": o["allocation"],
        "mean_iou": o["mean_iou"], "per_class_iou": per_class})


def cmp_per_class_rows(result):
    s = result["summary"]
    boot, spread = s["bootstrap"], s.get("spread") or {}
    names, colours = result["names"], result["colours"]
    frames_with = {}
    for e in s["frames"]:
        for c in e["metrics"]["per_class"]:
            if c["n_A"] or c["n_B"]:
                frames_with[c["code"]] = frames_with.get(c["code"], 0) + 1
    rows = []
    for c in s["pooled"]["per_class"]:
        code = c["code"]
        iou_lo, iou_hi = _cmp_ci(boot, "iou:%d" % code)
        f1_lo, f1_hi = _cmp_ci(boot, "f1:%d" % code)
        sp = spread.get("iou:%d" % code) or {}
        rows.append([code, cm_name(code, names), colours.get(code, ""),
                     c["n_A"], c["n_B"], c["n_same"], c["iou"], iou_lo,
                     iou_hi, sp.get("median"), sp.get("q1"), sp.get("q3"),
                     frames_with.get(code, 0), c["f1"], f1_lo, f1_hi,
                     c["rate_A"], c["rate_B"], c["q"], c["a"], c["e"],
                     c["s"]])
    return rows


CMP_PER_CLASS = ["code", "name", "colour", "pixels_A", "pixels_B",
                 "pixels_same", "iou", "iou_ci_low", "iou_ci_high",
                 "iou_median_frames", "iou_q1", "iou_q3", "frames_with_class",
                 "f1", "f1_ci_low", "f1_ci_high", "agree_from_A",
                 "agree_from_B", "quantity", "allocation", "exchange",
                 "shift"]
CMP_PER_FRAME = ["tile_id", "used", "reason", "pixels_in_frame", "share_A",
                 "share_B", "coverage_A", "coverage_B", "closed_A",
                 "closed_B", "both", "only_A", "only_B", "neither", "overall",
                 "kappa", "quantity", "allocation", "exchange", "shift",
                 "mean_iou", "delay_h"]
CMP_DESIGN = ["sample_id", "stratum", "incl_prob", "weight"]


def cmp_per_frame_rows(result, design=None):
    s = result["summary"]
    plan = result["plan"]
    by_id = {e["id"]: e["metrics"] for e in s["frames"]}
    rows = []
    for f in plan["frames"]:
        tid = f["tile_id"]
        m = by_id.get(tid)
        px = result["frames"].get(tid) or {}
        row = [tid, 1 if f["used"] else 0, f["reason"], px.get("pixels"),
               f["share_A"], f["share_B"], px.get("coverage_A"),
               px.get("coverage_B"), f["closed_A"], f["closed_B"]]
        if m is not None:
            o, cn = m["overall"], m["counts"]
            row += [cn["both"], cn["only_A"], cn["only_B"], cn["neither"],
                    o["po"], o.get("kappa"), o["quantity"], o["allocation"],
                    o["exchange"], o["shift"], o["mean_iou"]]
        else:
            row += [None] * 11
        row.append(plan["delay"].get(tid) if f["used"] else None)
        if design is not None:
            d = design.get(tid) or {}
            row += [d.get(k) for k in CMP_DESIGN]
        rows.append(row)
    return rows


def cmp_write(result, folder, data, package, owner_folder):
    """The tables and summary.json of a run, into folder. Returns the
    names of every file of the report, relative to it."""
    s = result["summary"]
    plan = result["plan"]
    codes, names = result["codes"], result["names"]
    pixel_m2 = result["pixel_m2"]
    total = np.sum(np.array(result["matrices"], dtype=np.int64), axis=0)
    # confusion.csv: pixels, then the same in m²
    wide = cm_wide_rows(total, codes, names, 0)
    rows = [r for r in wide[1:]]
    if pixel_m2:
        rows.append([])
        rows.append(["A \\ B (m²)"] + wide[0][1:])
        for r in wide[1:]:
            rows.append([r[0]] + [v * pixel_m2 for v in r[1:]])
    report_csv(os.path.join(folder, "confusion.csv"), wide[0], rows)
    long_rows = []
    for tid, m in zip(result["ids"], result["matrices"]):
        long_rows += cm_long_rows(m, codes, names, tid, 0, pixel_m2)
    long_rows += cm_long_rows(total, codes, names, "ALL", 0, pixel_m2)
    report_csv(os.path.join(folder, "confusion_by_frame.csv"),
               ["tile_id", "code_A", "name_A", "code_B", "name_B", "pixels",
                "area_m2"], long_rows)
    report_csv(os.path.join(folder, "per_class.csv"), CMP_PER_CLASS,
               cmp_per_class_rows(result))
    design = frame_design(package) if not plan["untiled"] else {}
    report_csv(os.path.join(folder, "per_frame.csv"),
               CMP_PER_FRAME + (CMP_DESIGN if design else []),
               cmp_per_frame_rows(result, design if design else None))
    pair_rows = []
    for e in result["pair_entries"]:
        n = result["pairs_present"].get(e["code"], 0)
        if not n:
            continue
        pair_rows.append([e["code"], e["a"], cm_name(e["a"], names), e["b"],
                          cm_name(e["b"], names), n,
                          n * pixel_m2 if pixel_m2 else None])
    report_csv(os.path.join(folder, "pairs.csv"),
               ["value", "a_code", "a_name", "b_code", "b_name", "pixels",
                "area_m2"], pair_rows)
    vec = result["files"]["vectors"]
    stem = os.path.splitext(vec)[0]
    files = sorted(["confusion.csv", "confusion_by_frame.csv",
                    "per_class.csv", "per_frame.csv", "pairs.csv",
                    "summary.json", result["files"]["disagreement"],
                    os.path.splitext(result["files"]["disagreement"])[0]
                    + ".qml", result["files"]["pairs"],
                    os.path.splitext(result["files"]["pairs"])[0] + ".qml",
                    vec, stem + "_polygons.qml", stem + "_frames.qml"])
    pooled = s["pooled"]
    o = pooled["overall"]
    marks = cmp_marks(package)
    readings = {}
    for side in ("A", "B"):
        r = plan[side]
        held = (marks.get(r) or {}).get("polygons") or {}
        readings[side] = {"operator": r[0], "pass": r[1],
                          "label": reading_label(r), "tag": reading_tag(r),
                          "first_created": held.get("first"),
                          "last_created": held.get("last")}
    delays = [plan["delay"].get(t) for t in result["ids"]]
    delays = [d for d in delays if d is not None]
    notes = list(result["notes"]) + [
        CMP_KAPPA_NOTE,
        "boxes (Objects) and line traces are not compared, as they are not "
        "in the mask; a line's band is in the polygons and is",
        "pooled values weigh every pixel equally; the median and quartiles "
        "over frames weigh every frame equally",
        "rates, IoU, F1 and kappa are taken over the pixels both readings "
        "painted; the pixels only one painted, and those neither painted, "
        "are counted apart (with_unlabelled counts unlabelled as a class)",
        "per class, quantity, allocation, exchange and shift are the "
        "by-category components of Pontius (2019): each pixel of difference "
        "concerns two classes, so they add up to twice the overall values",
        "frames are seldom a random sample: the interval describes how much "
        "the result varies across these frames, not over a population",
        "a frame is closed when one reading covers more than %g %% of its "
        "area (the area rule of Annotate and Check); coverage_A and "
        "coverage_B are the share of its pixels, which can differ by a "
        "sliver" % (CLOSED_SHARE * 100)]
    if plan["kind"] == "intra":
        notes.append("one operator, two passes: only meaningful if the later "
                     "pass read the ground again from scratch, with blind on")
    boot = s["bootstrap"]
    if boot.get("reason"):
        notes.append("bootstrap: %s" % boot["reason"])
    grid = data.get("grid") or {}
    owner = {"kind": "campaign", "id": data.get("id", ""),
             "name": data.get("name", ""), "folder": owner_folder}
    summary = report_header(CMP_KIND, owner)
    summary.update({
        "inputs": report_inputs([os.path.join(owner_folder, "campaign.json"),
                                 package], owner_folder),
        "parameters": {"frame_rule": plan["frame_rule"],
                       "frame_rule_asked": plan["asked_rule"],
                       "points_in": plan["points_in"],
                       "closed_share": CLOSED_SHARE,
                       "resamples": boot.get("resamples"),
                       "seed": boot.get("seed"), "level": boot.get("level")},
        "headline": cmp_headline(result),
        "campaign": {"name": data.get("name", ""), "id": data.get("id", ""),
                     "folder": owner_folder},
        "axes": {"A": reading_label(plan["A"]), "B": reading_label(plan["B"])},
        "readings": readings, "kind": plan["kind"],
        "frame_rule": plan["frame_rule"], "closed_share": CLOSED_SHARE,
        "points_in": plan["points_in"],
        "grid": {"crs": grid.get("crs"), "origin": grid.get("origin"),
                 "pixel_crs": grid.get("pixel_crs"),
                 "pixel_m": grid.get("pixel_m")},
        "codes": codes,
        "names": {str(c): cm_name(c, names) for c in codes},
        "frames": {"used": list(result["ids"]),
                   "left_out": list(plan["left_out"])},
        "counts": pooled["counts"],
        "pooled": {"overall": o["po"], "expected": o["pe"],
                   "kappa": o.get("kappa"), "quantity": o["quantity"],
                   "allocation": o["allocation"], "exchange": o["exchange"],
                   "shift": o["shift"], "mean_iou": o["mean_iou"],
                   "per_class": {str(c["code"]): {
                       "name": cm_name(c["code"], names),
                       "pixels_A": c["n_A"], "pixels_B": c["n_B"],
                       "pixels_same": c["n_same"], "iou": c["iou"],
                       "f1": c["f1"], "agree_from_A": c["rate_A"],
                       "agree_from_B": c["rate_B"], "quantity": c["q"],
                       "allocation": c["a"], "exchange": c["e"],
                       "shift": c["s"]} for c in pooled["per_class"]}},
        "with_unlabelled": s.get("with_unlabelled"),
        "spread": s.get("spread") or {},
        "bootstrap": {"resamples": boot.get("resamples"),
                      "seed": boot.get("seed"), "level": boot.get("level"),
                      "method": boot.get("method"),
                      "min_frames": boot.get("min_frames"),
                      "frames": boot.get("frames"), "ci": boot.get("ci"),
                      "n_valid": boot.get("n_valid"),
                      "reason": boot.get("reason")},
        "delay_h": {"median": float(np.median(delays)) if delays else None,
                    "min": min(delays) if delays else None,
                    "max": max(delays) if delays else None,
                    "n": len(delays)},
        "maps": {"disagreement": result["files"]["disagreement"],
                 "pairs": result["files"]["pairs"],
                 "vectors": vec,
                 "disagreement_codes": {str(c["code"]): c["name"]
                                        for c in DISAGREEMENT_CLASSES},
                 "pair_encoding": "1 + i*K + j over codes, 0 outside"},
        "notes": notes,
        "files": files})
    report_json(os.path.join(folder, "summary.json"), summary)
    result["summary_json"] = summary
    return files


#  One report, start to end
# =====================================================================
def cmp_target(final):
    """(tmp, final) for a report folder the user named: the first free one
    of final, final-2... with nothing ending in .tmp under it either."""
    for n in range(1, 1000):
        name = final if n == 1 else "%s-%d" % (final, n)
        tmp = name + ".tmp"
        if os.path.exists(long_path(name)) or os.path.exists(long_path(tmp)):
            continue
        try:
            os.makedirs(long_path(tmp))
        except FileExistsError:
            continue
        return tmp, name
    raise OSError("no free name for a report at %s" % final)


def cmp_compare(recipe, progress=None, cancelled=None):
    """A whole report: the folder, the run, the tables, the rename.

    recipe: data (the manifest), folder (the campaign's), package (its
    GeoPackage), plan (cmp_plan), n_boot, seed, and target, the report
    folder to make, or None for reports/agreement/<label>_<stamp>. On any
    failure, a cancel included, the .tmp folder goes and nothing else is
    touched. Returns the result, with "folder" the finished report."""
    data, plan = recipe["data"], recipe["plan"]
    label = cmp_label(plan["A"], plan["B"])
    # before a folder is made: the GeoPackage must be one QGIS can open
    problem = cmp_path_problem(data, recipe["folder"], plan["A"], plan["B"],
                               recipe.get("target"))
    if problem:
        raise ValueError(problem)
    if recipe.get("target"):
        tmp, final = cmp_target(recipe["target"])
    else:
        tmp, final = report_folder(recipe["folder"], CMP_KIND, label)
    stem = tidy(data.get("name") or "campaign", "campaign")
    try:
        result = cmp_run(plan, data, recipe["package"], tmp, stem,
                         recipe.get("n_boot", 2000), recipe.get("seed", 1),
                         progress, cancelled)
        result["written"] = cmp_write(result, tmp, data, recipe["package"],
                                      recipe["folder"])
        result["folder"] = report_finish(tmp, final)
    except BaseException:
        report_abandon(tmp)
        raise
    result["created_utc"] = (result.get("summary_json") or {}).get(
        "created_utc") or report_utc()
    log("agreement %s vs %s: %d frame%s, overall %s, in %s"
        % (reading_label(plan["A"]), reading_label(plan["B"]),
           len(result["ids"]), "" if len(result["ids"]) == 1 else "s",
           _cmp_num(result["summary"]["pooled"]["overall"]["po"]),
           result["folder"]))
    return result


def _cmp_num(v, digits=3):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return "%.*f" % (digits, f) if math.isfinite(f) else "—"
