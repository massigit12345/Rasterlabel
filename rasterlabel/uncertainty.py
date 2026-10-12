"""rasterlabel.uncertainty

Where a model was unsure, and the places to review first.

A model's map often comes with a second number per pixel: the probability
of the class it chose, the entropy of its scores, the margin between the
two best classes, or, for a consensus of readings, how many of them voted
for its class. Correct can take any of these as the map's uncertainty. It
is read once into a file of one byte per pixel beside the working copy,

    <copy>_uncertainty.tif    0..254 = u x 254, 255 = no value

where u is in 0..1 and higher means less sure, whatever the source said:
a probability p becomes 1 - p, a margin m becomes 1 - m, the votes v of n
readings become 1 - v/n. One renderer draws every kind, and the scoring
reads bytes.

The map is cut into fixed square places (blocks of PLACE_SIDE_PX pixels
from the top left corner) and they are ranked by their mean u. Correct
walks them in that order, the most uncertain first, and every
RANDOM_EVERY-th place is drawn instead from a seeded permutation of all of
them: a simple random sample of places without replacement. Only those
carry an inclusion probability. The places chosen by their uncertainty are
purposive and are kept out of every design-based estimate, by name, in
every file.

The report measures the uncertainty against what a person did: the share
of pixels changed per global decile of u and per tenth of the scale, for
the random places (with the standard error of the cluster ratio estimator,
Cochran 1977, places as clusters), for the purposive places (the same
number, labelled a spread and not a standard error) and for the whole map
(a lower bound: nothing says the ground nobody looked at was right); the
AUC of u as a detector of the changed pixels; the ECE when u is 1 - p; and
how much of the change the most uncertain share of the map holds.

No widget here, so the arithmetic is tested without QGIS: GDAL and numpy
for the files, the statistics of stats.py, the folders of reports.py. The
picture of the curve is drawn with Qt, imported when it is drawn.

Nothing here holds a map. The file of u, the record of changes and the net
change are read a strip or a window at a time, from their files, so the
memory a map of hundreds of millions of pixels needs is that of a strip
(STRIP_PX pixels), not of the map. The arrays that come in are anything that
is cut with [rows, columns] slices: a numpy array in a test, a BandPlane of
rasters.py in the program.
"""
import csv
import json
import math
import os
import re

import numpy as np
from osgeo import gdal, osr

from .constants import (BUILD, KIND_WORDS, MAX_PLACES, PLACE_SIDE_PX,
                        PLACE_VALID_SHARE, PLACES_CSV, PLACES_GEOJSON,
                        RANDOM_EVERY, REPORT_SUMMARY, STRIP_PX, STRIP_ROWS,
                        U_LEVELS, U_NODATA, UNCERTAINTY_SUFFIX, VERSION)
from .naming import csv_text, csv_untext_row, long_path
from .errors import log
from .stats import (st_auc_hist, st_bin_of, st_calibration, st_capture,
                    st_decile_cuts, st_ece, st_fixed_bin, st_ratio_se)
from .reports import (report_abandon, report_csv, report_finish,
                      report_folder, report_header, report_headline,
                      report_inputs, report_json, report_utc)
from .rasters import (BandPlane, _drop, _move, _there, has_grid, is_rotated,
                      pixel_grid, temporary_name)
from .geometry import aligned

UNC_KIND = "uncertainty"
UNC_KINDS = ("probability", "entropy", "margin", "uncertainty", "votes")
# The words of the kinds, as the window offers them and the files say them.
UNC_KIND_WORDS = {
    "probability": "probability of the class",
    "entropy": "entropy (0-1)",
    "margin": "margin, p1 - p2",
    "uncertainty": "uncertainty, higher = less sure",
    "votes": "votes of a consensus",
}
UNC_READ_AS = {
    "probability": "read as 1 - p",
    "entropy": "read as it is",
    "margin": "read as 1 - margin",
    "uncertainty": "read as it is",
    "votes": "read as 1 - votes / readings",
}
UNC_SCALES = (1.0, 100.0, 255.0, 10000.0, 65535.0)
UNC_LABELLED_BAND = "readings_labelled"
UNC_VOTES_BAND = "votes"
UNC_CI_Z = 1.96
UNC_CAPTURE_TOPS = (0.01, 0.02, 0.05, 0.10, 0.20, 0.30, 0.50, 1.00)
UNC_QUEUED_SHOWN = 20             # queued places drawn on the map
UNC_ENTROPY_NATS_SHARE = 0.01     # past this share of v > 1, offer ln K

UNC_DESIGN_PURPOSIVE = "exclude: purposive, chosen by uncertainty"
UNC_DESIGN_RANDOM = "include: simple random sample of places"
UNC_DESIGN_REUSED = ("include: simple random sample of places; reviewed "
                     "before it was drawn, not blind")
UNC_DESIGN_NOTE = ("Places ranked by uncertainty are purposive and are "
                   "excluded from design-based estimators. Only the random "
                   "places carry an inclusion probability, m/N, conditional "
                   "on when the review stopped.")
UNC_NOTE_RANDOM = "design-based, SRS of places, fpc"
UNC_NOTE_PURPOSIVE = "between-place spread, not design-based"
UNC_NOTE_WHOLE = "lower bound: unreviewed pixels count as right"
UNC_SINGLE_LEVEL = "u has a single value: no ranking possible"
UNC_RESTARTED = ("The record of which pixels a person changed (%s) is empty, "
                 "but this correction holds %d operations: the record was "
                 "started again after they were made, and a calibration from "
                 "it would count every one of them as right. Nothing was "
                 "written.")

UNC_PLACE_COLUMNS = [
    "place_id", "block_row", "block_col", "col", "row", "width", "height",
    "x_min", "y_min", "x_max", "y_max", "valid_px", "mean_u", "max_u",
    "purposive_rank", "random_order", "selection", "status", "offer_no",
    "offered_at", "done_at", "operator", "overlay_on", "changed_px",
    "design_use", "inclusion_prob"]
UNC_INT_COLUMNS = ("block_row", "block_col", "col", "row", "width", "height",
                   "valid_px", "purposive_rank", "random_order", "offer_no",
                   "overlay_on", "changed_px")
UNC_FLOAT_COLUMNS = ("x_min", "y_min", "x_max", "y_max", "mean_u", "max_u",
                     "inclusion_prob")
UNC_CALIBRATION_COLUMNS = [
    "scope", "binning", "bin", "u_low", "u_high", "n_px", "changed_px",
    "share_changed", "net_changed_px", "share_net", "mean_u",
    "expected_error", "places", "se_share", "ci95_low", "ci95_high", "note"]
UNC_CAPTURE_COLUMNS = ["scope", "top_share", "u_threshold", "share_of_area",
                       "changed_captured", "share_of_changes_captured"]
UNC_PLACES_REPORT_COLUMNS = ["place_id", "selection", "operator", "mean_u",
                             "valid_px", "changed_px", "share_changed",
                             "overlay_on", "inclusion_prob", "design_use"]
UNC_STROKE_COLUMNS = ["n", "when", "operator", "place", "col", "row",
                      "width", "height", "pixels", "u_mean", "u_max"]
UNC_SCOPES = ("random_places", "purposive_places", "whole_map")


class UncRefused(Exception):
    """A report that cannot be made, with the reason in so many words."""


#  The kind and the scale of a band, guessed from its name
# =====================================================================
def unc_guess_kind(desc, siblings=()):
    """What a band's description says it holds: one of UNC_KINDS, or None.

    The description is read lower case and the first word of KIND_WORDS
    that matches wins. "votes" counts only beside a band of the labelled
    readings, as the consensus of the readings job writes them; "classe",
    "validita" or "Band 3" say nothing."""
    text = str(desc or "").lower()
    others = [str(s or "").lower() for s in siblings or ()]
    for kind, pattern in KIND_WORDS:
        if not re.search(pattern, text):
            continue
        if kind == "votes":
            if any(UNC_LABELLED_BAND in s for s in others):
                return "votes"
            continue
        return kind
    return None


def unc_guess_scale(desc, type_name, gdal_scale=None, sample_max=None):
    """What a raw value is divided by to give a number from 0 to 1.

    In this order: "x255" in the name; a GDAL scale other than 1, which
    the read applies, so 1; the type, a byte 255, an unsigned 16 bits
    10000 when what was seen of it stays under 10000 and 65535 otherwise,
    a float 1. None when nothing says, and the window asks."""
    m = re.search(r"(?<![a-z0-9])x\s*(\d+)", str(desc or "").lower())
    if m and int(m.group(1)) > 0:
        return float(m.group(1))
    if gdal_scale not in (None, 0, 1, 1.0):
        return 1.0
    kind = str(type_name or "")
    if kind == "Byte":
        return 255.0
    if kind == "UInt16":
        if sample_max is not None and float(sample_max) <= 10000:
            return 10000.0
        return 65535.0
    if kind.startswith("Float"):
        return 1.0
    return None


def unc_describe(spec):
    """The source and how it is read, as the panel and the card say it:
    'probabilita x255, read as 1 - p'."""
    if not isinstance(spec, dict) or not spec.get("kind"):
        return ""
    name = str(spec.get("band_name") or "").strip()
    if not name:
        name = "band %s" % spec.get("band", "?")
    if spec.get("source") == "file":
        name = "%s of %s" % (name, os.path.basename(
            str(spec.get("path") or "")) or "another raster")
    return "%s, %s" % (name, UNC_READ_AS.get(spec["kind"], ""))


def unc_rule(spec, gain=1.0, offset=0.0):
    """The formula, as one sentence written into the file it made."""
    kind = spec.get("kind")
    if kind == "votes":
        return ("u = 1 - votes / readings_labelled where readings_labelled "
                ">= 1; %d = no value" % U_NODATA)
    raw = "raw"
    if gain not in (None, 1, 1.0) or offset not in (None, 0, 0.0):
        raw = "(raw * %.12g + %.12g)" % (gain or 1.0, offset or 0.0)
    v = "clip(%s / %.12g, 0, 1)" % (raw, float(spec.get("scale") or 1.0))
    if kind in ("probability", "margin"):
        v = "1 - " + v
    return "u = %s; %d = no value" % (v, U_NODATA)


def unc_signature(spec):
    """What the file made from a spec depends on, as text: a file whose
    signature is another one was made from another spec."""
    keys = ("source", "path", "band", "labelled_band", "kind", "scale")
    return json.dumps({k: (spec or {}).get(k) for k in keys}, sort_keys=True)


#  From raw values to u
# =====================================================================
def unc_to_u8(raw, labelled, spec, class_valid, band_nodata=None, gain=1.0,
              offset=0.0):
    """The raw values of a strip as bytes of u, and what was met.

    raw is the band read; labelled the band of labelled readings (votes
    only, None otherwise); class_valid where the class band holds a class.
    The value v = (raw * gain + offset) / scale, gain and offset being the
    band's own GDAL scale and offset, then:

      probability   u = 1 - clip(v, 0, 1); a nodata or a 0 under a class
                    has no value, since the probability of the class a
                    model chose is never 0
      entropy       u = clip(v, 0, 1)
      margin        u = 1 - clip(v, 0, 1)
      uncertainty   u = clip(v, 0, 1)
      votes         u = 1 - votes / labelled, no value where labelled is 0

    For entropy, margin and uncertainty a nodata of 0 under a class is read
    as the value 0 and counted (zero_read_as_value): a map whose entropy
    band says 0 for nodata would otherwise lose its most certain pixels.
    Stored as floor(u * 254 + 0.5); 255 where there is no value.

    Returns (u8, {valid_px, no_value, zero_read_as_value, clipped_px})."""
    valid = np.asarray(class_valid, dtype=bool)
    kind = (spec or {}).get("kind")
    out = np.full(valid.shape, U_NODATA, dtype=np.uint8)
    said = {"valid_px": 0, "no_value": 0, "zero_read_as_value": 0,
            "clipped_px": 0}
    r = np.asarray(raw, dtype=np.float64)
    finite = np.isfinite(r)
    if kind == "votes":
        lab = np.asarray(labelled, dtype=np.float64)
        ok = valid & finite & np.isfinite(lab) & (lab >= 1)
        v = np.zeros(r.shape)
        np.divide(r, lab, out=v, where=ok)
        clipped = ok & ((v < 0) | (v > 1))
        u = 1.0 - np.clip(v, 0.0, 1.0)
    else:
        scale = float((spec or {}).get("scale") or 1.0)
        if band_nodata is not None and np.isfinite(band_nodata):
            is_nd = finite & (r == float(band_nodata))
        else:
            is_nd = np.zeros(r.shape, dtype=bool)
        if kind == "probability":
            ok = valid & finite & ~is_nd & (r != 0)
        else:
            zero_nd = is_nd & (float(band_nodata or 0) == 0.0)
            ok = valid & finite & (~is_nd | zero_nd)
            said["zero_read_as_value"] = int((ok & zero_nd).sum())
        v = (r * float(gain if gain is not None else 1.0)
             + float(offset or 0.0)) / scale
        v = np.where(ok, v, 0.0)
        clipped = ok & ((v < 0) | (v > 1))
        v = np.clip(v, 0.0, 1.0)
        u = 1.0 - v if kind in ("probability", "margin") else v
    out[ok] = np.floor(u[ok] * U_LEVELS + 0.5).astype(np.uint8)
    said["valid_px"] = int(ok.sum())
    said["no_value"] = int((valid & ~ok).sum())
    said["clipped_px"] = int(clipped.sum())
    return out, said


def unc_preview(u8, class_valid, raw_v=None, kind=None):
    """The one line the window and Use it show of a reading: the range of
    u, its median and the share of the classes that has a value.
    {text, nats}: nats is True when an entropy is mostly above 1, as one
    in nats would be."""
    have = u8[u8 < U_NODATA].astype(np.float64) / U_LEVELS
    classes = int(np.asarray(class_valid, dtype=bool).sum())
    if have.size == 0:
        text = "no value anywhere: nothing would be read"
    else:
        text = ("reads as uncertainty %.2f-%.2f · median %.2f · %.1f%% of "
                "the map has a value" % (have.min(), have.max(),
                                         float(np.median(have)),
                                         100.0 * have.size / max(1, classes)))
    nats = False
    if kind == "entropy" and raw_v is not None:
        v = np.asarray(raw_v, dtype=np.float64)
        v = v[np.isfinite(v)]
        nats = bool(v.size) and float((v > 1).mean()) > UNC_ENTROPY_NATS_SHARE
    return {"text": text, "nats": nats}


#  The bands of a raster, and the file of u
# =====================================================================
def unc_bands(path):
    """[{band, description, type, nodata, scale, offset}] of a raster, or
    [] when it cannot be read."""
    out = []
    try:
        ds = gdal.Open(long_path(path))
    except Exception:
        ds = None
    if ds is None:
        return out
    try:
        for b in range(1, ds.RasterCount + 1):
            band = ds.GetRasterBand(b)
            try:
                kind = gdal.GetDataTypeName(band.DataType)
            except Exception:
                kind = ""
            scale = getattr(band, "GetScale", lambda: None)()
            offset = getattr(band, "GetOffset", lambda: None)()
            out.append({"band": b, "description": band.GetDescription() or "",
                        "type": kind, "nodata": band.GetNoDataValue(),
                        "scale": scale, "offset": offset})
            band = None
    finally:
        ds = None
    return out


def unc_sample(path, band_nos, sample=512):
    """The bands read small, as values_in reads one: a decimated look at
    the whole of each, the same size for all. {band: array}."""
    out = {}
    ds = gdal.Open(long_path(path))
    if ds is None:
        raise IOError("cannot read %s" % os.path.basename(path))
    try:
        wide = min(sample, ds.RasterXSize)
        tall = min(sample, ds.RasterYSize)
        for b in band_nos:
            if not b:
                continue
            out[b] = ds.GetRasterBand(int(b)).ReadAsArray(
                0, 0, ds.RasterXSize, ds.RasterYSize, buf_xsize=wide,
                buf_ysize=tall)
    finally:
        ds = None
    return out


def unc_class_valid(values, nodata):
    """Where a class band holds a class: finite, and not its nodata."""
    a = np.asarray(values)
    ok = np.ones(a.shape, dtype=bool)
    if a.dtype.kind == "f":
        ok &= np.isfinite(a)
    if nodata is not None:
        try:
            if np.isfinite(nodata):
                ok &= a != nodata
        except TypeError:
            pass
    return ok


def unc_path_of(copy, record=None):
    """<copy stem>_uncertainty.tif beside the copy, or the name the
    manifest gives it."""
    spec = (record or {}).get("uncertainty") if isinstance(record, dict) \
        else None
    name = str((spec or {}).get("derived") or "").strip() \
        if isinstance(spec, dict) else ""
    folder = os.path.dirname(str(copy).split("|")[0])
    if name:
        return os.path.join(folder, os.path.basename(name))
    stem = os.path.splitext(os.path.basename(str(copy).split("|")[0]))[0]
    return os.path.join(folder, stem + UNCERTAINTY_SUFFIX + ".tif")


def unc_source_path(spec, folder):
    """The raster a spec reads, absolute: "" for a band of the copy."""
    if not isinstance(spec, dict) or spec.get("source") != "file":
        return ""
    path = str(spec.get("path") or "")
    if path and not os.path.isabs(path):
        path = os.path.join(folder, path)
    return path


def unc_stamp(path):
    """size:mtime of a file, or "" when it is not there."""
    try:
        st = os.stat(long_path(path))
    except OSError:
        return ""
    return "%d:%d" % (st.st_size, int(st.st_mtime))


def unc_same_crs(a, b):
    """True when two WKTs name one system, or when either is empty (a
    picture with no system is on the grid it is given)."""
    if not a or not b:
        return True
    try:
        sa = osr.SpatialReference()
        sa.ImportFromWkt(a)
        sb = osr.SpatialReference()
        sb.ImportFromWkt(b)
        return bool(sa.IsSame(sb))
    except Exception:
        return a == b


def unc_grid_relation(copy_path, other_path):
    """How another raster sits on the copy's grid: "same", "aligned",
    "resampled", or ("refused", why)."""
    a = gdal.Open(long_path(copy_path))
    b = gdal.Open(long_path(other_path))
    if a is None or b is None:
        return "refused", "cannot be read"
    try:
        ga, gb = pixel_grid(a), pixel_grid(b)
        if is_rotated(gb):
            return "refused", "its grid is rotated"
        if not unc_same_crs(a.GetProjection(), b.GetProjection()):
            return "refused", ("it is in another coordinate system than the "
                               "map")
        if tuple(ga) == tuple(gb) and (a.RasterXSize, a.RasterYSize) == \
                (b.RasterXSize, b.RasterYSize):
            return "same"
        if aligned(ga, gb):
            return "aligned"
        return "resampled"
    finally:
        a = b = None


UNC_TILE_ROWS = 256               # the tile height of the files GDAL writes
UNC_BUILD_SHARE = 4               # a strip of the build is this part of STRIP_PX


def unc_rows_for(nx):
    """How many rows to read at once from a file of u or of changes nx
    pixels wide: whole rows of tiles, because a strip that cuts a tile makes
    GDAL decode it twice, as many as hold STRIP_PX pixels, one row of tiles
    at the least and STRIP_ROWS rows at the most."""
    tiles = max(1, STRIP_PX // (max(1, int(nx)) * UNC_TILE_ROWS))
    return min(tiles, max(1, STRIP_ROWS // UNC_TILE_ROWS)) * UNC_TILE_ROWS


def _unc_index_map(t0, tstep, n, s0, sstep, ns):
    """For each of n target pixels along one axis, the source pixel whose
    area holds its centre, or -1 off the source."""
    centre = t0 + (np.arange(n) + 0.5) * tstep
    idx = np.floor((centre - s0) / sstep).astype(np.int64)
    idx[(idx < 0) | (idx >= ns)] = -1
    return idx


def _unc_read_mapped(band, cols, rows):
    """A band read at the given source columns and rows (-1 off it, NaN
    there): nearest neighbour onto another grid, an exact read on one
    shifted by whole pixels."""
    out = np.full((rows.size, cols.size), np.nan)
    rr = rows[rows >= 0]
    cc = cols[cols >= 0]
    if rr.size == 0 or cc.size == 0:
        return out
    r0, r1 = int(rr.min()), int(rr.max()) + 1
    c0, c1 = int(cc.min()), int(cc.max()) + 1
    block = band.ReadAsArray(c0, r0, c1 - c0, r1 - r0).astype(np.float64)
    nd = band.GetNoDataValue()
    if nd is not None and np.isfinite(nd):
        # the band's own nodata is told apart later; keep it as it is
        pass
    sub = block[np.clip(rows - r0, 0, r1 - r0 - 1)][:,
                                                     np.clip(cols - c0, 0,
                                                             c1 - c0 - 1)]
    keep = (rows >= 0)[:, None] & (cols >= 0)[None, :]
    out[keep] = sub[keep]
    return out


def unc_build(copy_path, class_band, class_nodata, spec, out_path,
              progress=None):
    """<copy>_uncertainty.tif made from a spec, a strip at a time.

    The source is a band of the copy, or a band of another raster on the
    same ground: on the copy's grid it is read exactly, shifted by whole
    pixels it is read from the window that covers it, on another grid it
    is read nearest neighbour (the spec must say "resampled" was agreed
    to). Another coordinate system is refused. Written under a temporary
    name and moved into place once it reads back whole, as the record of
    changes is. progress(done, total) may return False to stop.

    Returns {valid_px, no_value, zero_read_as_value, clipped_px, map_px,
    grid, gain, offset, stamp}."""
    copy = gdal.Open(long_path(copy_path))
    if copy is None:
        raise IOError("cannot read the working copy %s"
                      % os.path.basename(copy_path))
    other = None
    tmp = temporary_name(out_path)
    ds = None
    try:
        w, h = copy.RasterXSize, copy.RasterYSize
        gt = pixel_grid(copy)
        wkt = copy.GetProjection()
        src_path = unc_source_path(spec, os.path.dirname(copy_path))
        if spec.get("source") == "file":
            relation = unc_grid_relation(copy_path, src_path)
            if isinstance(relation, tuple):
                raise IOError("%s cannot be used: %s"
                              % (os.path.basename(src_path), relation[1]))
            if relation == "resampled" and not spec.get("resample_ok", True):
                raise IOError("%s is not on the grid of the map"
                              % os.path.basename(src_path))
            other = gdal.Open(long_path(src_path))
            src = other
            grid = relation
        else:
            src = copy
            grid = "same"
        band_no = int(spec.get("band") or 0)
        if not 1 <= band_no <= src.RasterCount:
            raise IOError("the raster has no band %s" % band_no)
        if spec.get("source") != "file" and band_no == int(class_band):
            raise IOError("the class band cannot be its own uncertainty")
        raw_band = src.GetRasterBand(band_no)
        lab_band = None
        if spec.get("kind") == "votes":
            lab_no = int(spec.get("labelled_band") or 0)
            if not 1 <= lab_no <= src.RasterCount:
                raise IOError("the votes have no band of labelled readings")
            lab_band = src.GetRasterBand(lab_no)
        gain = getattr(raw_band, "GetScale", lambda: None)()
        offset = getattr(raw_band, "GetOffset", lambda: None)()
        gain = 1.0 if gain in (None, 0) else float(gain)
        offset = 0.0 if offset is None else float(offset)
        nodata = raw_band.GetNoDataValue()
        cls = copy.GetRasterBand(int(class_band))
        cols = rows_of = None
        if grid in ("aligned", "resampled"):
            sg = pixel_grid(src)
            cols = _unc_index_map(gt[0], gt[1], w, sg[0], sg[1],
                                  src.RasterXSize)
            rows_of = _unc_index_map(gt[3], gt[5], h, sg[3], sg[5],
                                     src.RasterYSize)
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(long_path(tmp), w, h, 1, gdal.GDT_Byte,
                        ["COMPRESS=DEFLATE", "TILED=YES",
                         "BIGTIFF=IF_SAFER"])
        if ds is None:
            raise IOError("cannot create %s. The disk may be full or the "
                          "folder read only." % os.path.basename(out_path))
        if has_grid(copy):
            ds.SetGeoTransform(gt)
        if wkt:
            ds.SetProjection(wkt)
        out = ds.GetRasterBand(1)
        out.SetDescription("uncertainty")
        out.SetNoDataValue(U_NODATA)
        said = {"valid_px": 0, "no_value": 0, "zero_read_as_value": 0,
                "clipped_px": 0, "map_px": 0}
        # One handle is held all through, so a strip need not line up with
        # the tiles. It is smaller than the strips that are only read: the
        # arithmetic of unc_to_u8 holds about ten arrays of it, as floats.
        strip = max(1, min(STRIP_ROWS, STRIP_PX // UNC_BUILD_SHARE
                           // max(1, w)))
        for row in range(0, h, strip):
            take = min(strip, h - row)
            values = cls.ReadAsArray(0, row, w, take)
            valid = unc_class_valid(values, class_nodata)
            if cols is None:
                raw = raw_band.ReadAsArray(0, row, w, take)
                lab = lab_band.ReadAsArray(0, row, w, take) \
                    if lab_band is not None else None
            else:
                rr = rows_of[row:row + take]
                raw = _unc_read_mapped(raw_band, cols, rr)
                lab = _unc_read_mapped(lab_band, cols, rr) \
                    if lab_band is not None else None
            u8, part = unc_to_u8(raw, lab, spec, valid, nodata, gain, offset)
            for k in ("valid_px", "no_value", "zero_read_as_value",
                      "clipped_px"):
                said[k] += part[k]
            said["map_px"] += int(valid.sum())
            out.WriteArray(u8, 0, row)
            if progress is not None and progress(row + take, h) is False:
                raise UncRefused("Stopped. Nothing was written.")
        meta = {"RASTERLABEL_VERSION": VERSION, "RASTERLABEL_BUILD": BUILD,
                "RASTERLABEL_UNCERTAINTY_KIND": str(spec.get("kind")),
                "RASTERLABEL_UNCERTAINTY_SCALE": "%.12g"
                % float(spec.get("scale") or 1.0),
                "RASTERLABEL_UNCERTAINTY_OFFSET": "%.12g" % offset,
                "RASTERLABEL_UNCERTAINTY_SOURCE": unc_source_words(spec),
                "RASTERLABEL_UNCERTAINTY_GRID": grid,
                "RASTERLABEL_UNCERTAINTY_RULE": unc_rule(spec, gain, offset),
                "RASTERLABEL_UNCERTAINTY_SPEC": unc_signature(spec),
                "RASTERLABEL_UNCERTAINTY_STAMP": unc_stamp(src_path)
                if src_path else ""}
        ds.SetMetadata(meta)
        out = None
        ds.FlushCache()
        ds = None
        back = gdal.Open(long_path(tmp))
        if back is None or (back.RasterXSize, back.RasterYSize) != (w, h):
            raise IOError("%s does not read back" % os.path.basename(tmp))
        back = None
        _move(tmp, out_path)
    except BaseException:
        ds = None
        try:
            if _there(tmp):
                _drop(tmp)
        except OSError:
            pass
        raise
    finally:
        copy = other = None
    said.update({"grid": grid, "gain": gain, "offset": offset,
                 "stamp": unc_stamp(src_path) if src_path else ""})
    return said


def unc_source_words(spec):
    """Where the values came from, as the file's metadata says it:
    'copy band 2 probabilita x255' or 'path|band'."""
    if spec.get("source") == "file":
        return "%s|%s" % (spec.get("path") or "", spec.get("band"))
    return ("copy band %s %s" % (spec.get("band"), spec.get("band_name")
                                 or "")).strip()


def unc_file_state(path, spec, folder):
    """("ok"|"missing"|"stale"|"other", why) of the file of u against the
    spec the manifest holds: missing when it is not there, other when it
    was made from another spec, stale when its source changed since."""
    if not _there(path):
        return "missing", "not there"
    try:
        ds = gdal.Open(long_path(path))
        meta = ds.GetMetadata() if ds is not None else None
        ds = None
    except Exception:
        meta = None
    if meta is None:
        return "missing", "cannot be read"
    if meta.get("RASTERLABEL_UNCERTAINTY_SPEC") != unc_signature(spec):
        return "other", "made from another source or reading"
    src = unc_source_path(spec, folder)
    if src and _there(src) and \
            meta.get("RASTERLABEL_UNCERTAINTY_STAMP", "") != unc_stamp(src):
        return "stale", "its source changed since it was made"
    return "ok", ""


def unc_plane(path, nx, ny):
    """The file of u as a band read a window at a time, or None when it is
    not the size of the copy. Correct and the report use this: the file is
    the truth and a map of hundreds of millions of pixels is never held
    whole."""
    try:
        plane = BandPlane(long_path(path), 1)
    except (IOError, RuntimeError):
        return None
    if (plane.nx, plane.ny) != (nx, ny):
        return None
    return plane


def unc_read_u8(path, nx, ny):
    """The whole file of u, one byte a pixel, or None when it is not the
    size of the copy. For a map small enough to hold; unc_plane is the one
    that does not hold it."""
    ds = gdal.Open(long_path(path))
    if ds is None:
        return None
    try:
        if (ds.RasterXSize, ds.RasterYSize) != (nx, ny):
            return None
        return np.asarray(ds.GetRasterBand(1).ReadAsArray(), dtype=np.uint8)
    finally:
        ds = None


#  Places
# =====================================================================
def unc_side_for(nx, ny, side=PLACE_SIDE_PX, most=MAX_PLACES):
    """The side of a place, raised from the one asked until the map holds
    no more than most of them."""
    s = max(1, int(side))
    while int(math.ceil(nx / float(s))) * int(math.ceil(ny / float(s))) \
            > most:
        s += max(1, s // 8)
    return s


def unc_score_blocks(u8, side, valid_share=PLACE_VALID_SHARE):
    """Every block of side x side pixels from the top left corner, scored.

    {bi, bj, n_px, n_valid, sum, max, eligible}, arrays in row-major
    order of the blocks; the last row and column of blocks are cut to the
    map. A block is eligible when at least valid_share of its pixels have
    a value. One pass over u8, a row of blocks at a time and, on a map
    wide enough that a row of blocks is more than a strip, a run of blocks
    of it at a time."""
    ny, nx = u8.shape
    s = int(side)
    nby, nbx = int(math.ceil(ny / float(s))), int(math.ceil(nx / float(s)))
    out = {k: [] for k in ("bi", "bj", "n_px", "n_valid", "sum", "max")}
    widths = np.minimum(s, nx - np.arange(nbx) * s)
    per = max(1, STRIP_PX // (s * s))
    for i in range(nby):
        top, bottom = i * s, min((i + 1) * s, ny)
        h = bottom - top
        for first in range(0, nbx, per):
            last = min(nbx, first + per)
            left, right = first * s, min(nx, last * s)
            pad = np.full((h, (last - first) * s), U_NODATA, dtype=np.uint8)
            pad[:, :right - left] = u8[top:bottom, left:right]
            cube = pad.reshape(h, last - first, s)
            valid = cube < U_NODATA
            vals = np.where(valid, cube, 0).astype(np.int64)
            out["bi"].append(np.full(last - first, i))
            out["bj"].append(np.arange(first, last))
            out["n_px"].append(widths[first:last] * h)
            out["n_valid"].append(valid.sum(axis=(0, 2)))
            out["sum"].append(vals.sum(axis=(0, 2)))
            out["max"].append(vals.max(axis=(0, 2)))
    blocks = {k: np.concatenate(v).astype(np.int64) if v else
              np.zeros(0, np.int64) for k, v in out.items()}
    blocks["eligible"] = blocks["n_valid"] >= valid_share * blocks["n_px"]
    blocks["eligible"] &= blocks["n_valid"] > 0
    blocks["side"] = s
    return blocks


def unc_rank(blocks):
    """The eligible blocks, as indices into blocks, ranked: highest mean u
    first, then highest max, then by row and column."""
    idx = np.nonzero(blocks["eligible"])[0]
    if idx.size == 0:
        return idx
    mean = blocks["sum"][idx] / np.maximum(1, blocks["n_valid"][idx])
    order = np.lexsort((blocks["bj"][idx], blocks["bi"][idx],
                        -blocks["max"][idx], -mean))
    return idx[order]


def _unc_num(value, kind=float):
    if value is None or value == "":
        return None
    try:
        return kind(float(value)) if kind is int else kind(value)
    except (TypeError, ValueError):
        return None


class Places(object):
    """The places of one correction, their order and what was done in each.

    Kept in uncertainty_places.csv beside the copy, one row per eligible
    place, written whole at every change (a .tmp, then os.replace). The
    queue is not stored: it is worked out from the rows, so the file read
    back gives the same next place.

    - Every place has a purposive_rank (by mean u) and a random_order (its
      position in numpy.random.default_rng(seed).permutation(N), over the
      places in row-major order).
    - The k-th place offered (k from 1) is a random draw when random_every
      divides k: the next of the permutation. A place the permutation draws
      that was already offered as purposive joins the random sample as it
      is, without a visit, and the next draw is taken in the same press:
      membership is decided by the permutation alone, so the random places
      are always its first m entries, a simple random sample without
      replacement. Otherwise the next place by rank that was not offered.
      A draw that is due once the permutation has run out gives way to the
      next place by rank; once every place was offered the walk ends, and
      no draw is made only to join a place already seen.
    - Done and Skip close the current place. Skip is nonresponse: a skipped
      place counts in no curve.
    """

    def __init__(self, path, side=PLACE_SIDE_PX, seed=0,
                 random_every=RANDOM_EVERY, blind=True):
        self.path = path
        self.side = int(side)
        self.seed = int(seed)
        self.random_every = max(0, int(random_every))
        self.blind = bool(blind)
        self.rows = []
        self._index()

    # ---------------------------------------------------------- building
    @classmethod
    def from_blocks(cls, path, blocks, gt, nx, ny, seed,
                    random_every=RANDOM_EVERY, blind=True):
        places = cls(path, blocks["side"], seed, random_every, blind)
        s = blocks["side"]
        eligible = np.nonzero(blocks["eligible"])[0]
        ranked = unc_rank(blocks)
        rank = {int(b): k + 1 for k, b in enumerate(ranked)}
        perm = np.random.default_rng(int(seed)).permutation(eligible.size)
        order = {}
        for t, k in enumerate(perm):
            order[int(eligible[int(k)])] = t + 1
        rows = []
        for b in eligible:
            b = int(b)
            i, j = int(blocks["bi"][b]), int(blocks["bj"][b])
            col, row = j * s, i * s
            w, h = min(s, nx - col), min(s, ny - row)
            xs = (gt[0] + col * gt[1], gt[0] + (col + w) * gt[1])
            ys = (gt[3] + row * gt[5], gt[3] + (row + h) * gt[5])
            n_valid = int(blocks["n_valid"][b])
            rows.append({
                "place_id": "b%d_%d" % (i, j), "block_row": i,
                "block_col": j, "col": col, "row": row, "width": w,
                "height": h, "x_min": min(xs), "y_min": min(ys),
                "x_max": max(xs), "y_max": max(ys), "valid_px": n_valid,
                "mean_u": blocks["sum"][b] / float(U_LEVELS * n_valid),
                "max_u": blocks["max"][b] / float(U_LEVELS),
                "purposive_rank": rank[b], "random_order": order[b],
                "selection": "", "status": "", "offer_no": None,
                "offered_at": "", "done_at": "", "operator": "",
                "overlay_on": None, "changed_px": None, "design_use": "",
                "inclusion_prob": None})
        places.rows = rows
        places._index()
        return places

    def rescore(self, blocks):
        """New values of u for the same places: mean, max and rank follow,
        while which places there are, their random order and what was done
        in them stay. The design does not change when the reading does."""
        index = {(int(blocks["bi"][b]), int(blocks["bj"][b])): b
                 for b in range(blocks["bi"].size)}
        for r in self.rows:
            b = index.get((r["block_row"], r["block_col"]))
            if b is None:
                continue
            n = int(blocks["n_valid"][b])
            r["valid_px"] = n
            r["mean_u"] = blocks["sum"][b] / float(U_LEVELS * max(1, n))
            r["max_u"] = blocks["max"][b] / float(U_LEVELS)
        ranked = sorted(self.rows, key=lambda r: (-r["mean_u"], -r["max_u"],
                                                  r["block_row"],
                                                  r["block_col"]))
        for k, r in enumerate(ranked):
            r["purposive_rank"] = k + 1
        self._index()

    def _index(self):
        self.by_id = {r["place_id"]: r for r in self.rows}
        self._by_rank = sorted(self.rows, key=lambda r: r["purposive_rank"]
                               or 0)
        self._by_draw = sorted(self.rows, key=lambda r: r["random_order"]
                               or 0)

    @property
    def N(self):
        return len(self.rows)

    # ---------------------------------------------------------- the file
    def load(self):
        """The rows of the file, with its settings read from it when it has
        them. Raises IOError when it cannot be read."""
        try:
            with open(long_path(self.path), newline="",
                      encoding="utf-8") as fh:
                got = list(csv.DictReader(fh))
        except (OSError, csv.Error) as err:
            raise IOError("cannot read %s: %s"
                          % (os.path.basename(self.path), err))
        rows = []
        for raw in got:
            raw = csv_untext_row(raw)       # the quote _unc_cell put on a text
            r = {}
            for k in UNC_PLACE_COLUMNS:
                v = raw.get(k, "")
                if k in UNC_INT_COLUMNS:
                    r[k] = _unc_num(v, int)
                elif k in UNC_FLOAT_COLUMNS:
                    r[k] = _unc_num(v, float)
                else:
                    r[k] = v or ""
            if r["place_id"]:
                rows.append(r)
        self.rows = rows
        # the side, from where the places start: a place cut by the edge of
        # the map, or a map smaller than one place, says nothing of it
        sides = set(r["col"] // r["block_col"] for r in rows
                    if r["block_col"] and r["col"] is not None) | \
            set(r["row"] // r["block_row"] for r in rows
                if r["block_row"] and r["row"] is not None)
        if sides:
            self.side = max(sides)
        self._index()
        return self

    def save(self):
        tmp = self.path + ".tmp"
        with open(long_path(tmp), "w", newline="", encoding="utf-8") as fh:
            out = csv.writer(fh, lineterminator="\n")
            out.writerow(UNC_PLACE_COLUMNS)
            for r in self.rows:
                out.writerow([_unc_cell(k, r.get(k))
                              for k in UNC_PLACE_COLUMNS])
        os.replace(long_path(tmp), long_path(self.path))
        return self.path

    # ---------------------------------------------------------- the queue
    def current(self):
        for r in self.rows:
            if r["status"] == "current":
                return r
        return None

    def offered(self):
        return sorted((r for r in self.rows if r["offer_no"]),
                      key=lambda r: r["offer_no"])

    @staticmethod
    def _sel(row, sel):
        return sel.get(row["place_id"], row["selection"])

    def _step(self, sel, k, draws, cursor):
        """One offer decided, rows untouched: (row, joined, k, draws,
        cursor), sel holding the selections given so far."""
        joined = []
        while True:
            while cursor < len(self._by_rank) and \
                    self._sel(self._by_rank[cursor], sel):
                cursor += 1
            purposive = self._by_rank[cursor] \
                if cursor < len(self._by_rank) else None
            if purposive is None:
                # every place was offered: nothing is left to visit, and
                # no draw is made only to join a place already seen
                return None, joined, k, draws, cursor
            drawn = self._by_draw[draws] if draws < len(self._by_draw) \
                else None
            due = self.random_every > 0 and \
                (k + 1) % self.random_every == 0
            if drawn is not None and due:
                draws += 1
                if self._sel(drawn, sel):
                    sel[drawn["place_id"]] = "random"
                    joined.append(drawn)
                    continue
                sel[drawn["place_id"]] = "random"
                return drawn, joined, k + 1, draws, cursor
            sel[purposive["place_id"]] = "purposive"
            return purposive, joined, k + 1, draws, cursor + 1

    def _state(self):
        k = sum(1 for r in self.rows if r["selection"])
        draws = sum(1 for r in self.rows if r["selection"] == "random")
        return k, draws, 0

    def next(self, when=None):
        """The current place, or the next one offered and made current;
        None when every place was seen."""
        here = self.current()
        if here is not None:
            return here
        k, draws, cursor = self._state()
        sel = {}
        row, joined, _, _, _ = self._step(sel, k, draws, cursor)
        for r in joined:
            r["selection"] = "random"
            r["design_use"] = UNC_DESIGN_REUSED
        if row is None:
            return None
        row["selection"] = sel[row["place_id"]]
        row["status"] = "current"
        row["offer_no"] = max([r["offer_no"] or 0 for r in self.rows]
                              or [0]) + 1
        row["offered_at"] = when or report_utc()
        row["design_use"] = UNC_DESIGN_RANDOM \
            if row["selection"] == "random" else UNC_DESIGN_PURPOSIVE
        return row

    def upcoming(self, n=UNC_QUEUED_SHOWN):
        """The next n places the walk would offer after the current one,
        rows untouched."""
        k, draws, cursor = self._state()
        sel = {}
        out = []
        while len(out) < n:
            row, _, k, draws, cursor = self._step(sel, k, draws, cursor)
            if row is None:
                break
            out.append(row)
        return out

    def done(self, operator="", when=None, overlay_on=False, changed_px=0):
        row = self.current()
        if row is None:
            return None
        row["status"] = "done"
        row["done_at"] = when or report_utc()
        row["operator"] = operator or ""
        row["overlay_on"] = 1 if overlay_on else 0
        row["changed_px"] = int(changed_px or 0)
        return row

    def skip(self, when=None, overlay_on=False):
        row = self.current()
        if row is None:
            return None
        row["status"] = "skipped"
        row["done_at"] = when or report_utc()
        row["overlay_on"] = 1 if overlay_on else 0
        return row

    def back(self, row):
        """The place offered before this one, or None: ◀ only moves the
        view, it marks nothing."""
        seen = self.offered()
        if row is None:
            return seen[-1] if seen else None
        before = [r for r in seen if r["offer_no"] < (row["offer_no"] or 0)]
        return before[-1] if before else None

    def remaining(self):
        """True while a place is current or still to be offered."""
        if self.current() is not None:
            return True
        k, draws, cursor = self._state()
        row = self._step({}, k, draws, cursor)[0]
        return row is not None

    # ---------------------------------------------------------- the counts
    def counts(self):
        rnd = [r for r in self.rows if r["selection"] == "random"]
        out = {"eligible_N": self.N,
               "offered": sum(1 for r in self.rows if r["offer_no"]),
               "done": sum(1 for r in self.rows if r["status"] == "done"),
               "skipped": sum(1 for r in self.rows
                              if r["status"] == "skipped"),
               "purposive_done": sum(1 for r in self.rows
                                     if r["selection"] == "purposive"
                                     and r["status"] == "done"),
               "random_done": sum(1 for r in rnd if r["status"] == "done"),
               "random_skipped": sum(1 for r in rnd
                                     if r["status"] == "skipped"),
               "random_drawn_m": sum(1 for r in rnd if r["status"]
                                     in ("done", "skipped", "current")),
               "random_reused": sum(1 for r in rnd
                                    if r["design_use"] == UNC_DESIGN_REUSED),
               "overlay_seen_random": sum(1 for r in rnd
                                          if r["status"] == "done"
                                          and r["overlay_on"])}
        return out

    def inclusion(self):
        """m/N, the inclusion probability of every random place, or None."""
        c = self.counts()
        if not self.N or not c["random_drawn_m"]:
            return None
        return c["random_drawn_m"] / float(self.N)

    def fill_inclusion(self):
        pi = self.inclusion()
        for r in self.rows:
            r["inclusion_prob"] = pi if r["selection"] == "random" and \
                r["status"] in ("done", "skipped", "current") else None
        return pi

    # ---------------------------------------------------------- the map
    def geojson(self, path, wkt="", reveal=False):
        """The offered places and the next UNC_QUEUED_SHOWN, for the layer
        of the walk and for any other program. While places remain in blind
        mode, nothing in it says how uncertain a place is or why it was
        chosen; the report writes it whole (reveal)."""
        hide = self.blind and not reveal
        feats = []
        shown = list(self.offered())
        queued = [] if not self.remaining() else \
            [r for r in self.upcoming() if not r["offer_no"]]
        for r in shown + queued:
            props = {"place_id": r["place_id"],
                     "status": r["status"] if r["offer_no"] else "queued",
                     "random_order": r["random_order"],
                     "inclusion_prob": r["inclusion_prob"]}
            if not hide:
                props.update({"selection": r["selection"],
                              "design_use": r["design_use"],
                              "purposive_rank": r["purposive_rank"],
                              "mean_u": round(float(r["mean_u"] or 0.0), 6)})
            ring = [[r["x_min"], r["y_min"]], [r["x_max"], r["y_min"]],
                    [r["x_max"], r["y_max"]], [r["x_min"], r["y_max"]],
                    [r["x_min"], r["y_min"]]]
            feats.append({"type": "Feature", "properties": props,
                          "geometry": {"type": "Polygon",
                                       "coordinates": [ring]}})
        doc = {"type": "FeatureCollection", "name": "uncertainty_places",
               "features": feats}
        epsg = unc_epsg(wkt)
        if epsg:
            doc["crs"] = {"type": "name", "properties": {
                "name": "urn:ogc:def:crs:EPSG::%s" % epsg}}
        text = json.dumps(doc, indent=0, allow_nan=False)
        tmp = path + ".tmp"
        with open(long_path(tmp), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        try:
            os.replace(long_path(tmp), long_path(path))
        except OSError:
            # Windows refuses to replace a file a layer holds open, as the
            # places layer holds this one; it can still be written over
            with open(long_path(path), "w", encoding="utf-8",
                      newline="\n") as fh:
                fh.write(text)
            try:
                os.remove(long_path(tmp))
            except OSError:
                pass
        return path


def _unc_cell(key, value):
    if value is None:
        return ""
    if key in ("mean_u", "max_u"):
        return "%.6f" % float(value)
    if isinstance(value, float):
        return "%.12g" % value
    return csv_text(str(value))


def unc_epsg(wkt):
    """The EPSG code of a WKT, or None."""
    if not wkt:
        return None
    try:
        srs = osr.SpatialReference()
        srs.ImportFromWkt(wkt)
        try:
            srs.AutoIdentifyEPSG()
        except Exception:
            pass
        code = srs.GetAuthorityCode(None)
        return int(code) if code else None
    except Exception:
        return None


def unc_default_seed(owner_id, name=""):
    """The design seed of a correction: its id, a hexadecimal number, modulo
    2**31; a sum of its name when the id is not one."""
    try:
        return int(str(owner_id), 16) % 2 ** 31
    except (TypeError, ValueError):
        return sum(ord(c) * (k + 1) for k, c in
                   enumerate(str(owner_id or name))) % 2 ** 31


#  Histograms and the calibration
# =====================================================================
def unc_hist(u8, flags=None):
    """(H_all, H_flag) over the 255 levels of u: how many pixels have each
    level, and how many of them are flagged (changed). 255 is left out.
    Counted STRIP_PX pixels at a time: bincount turns the bytes it is given
    into 64 bit integers, eight times the strip."""
    v = np.asarray(u8).ravel()
    f = np.asarray(flags).ravel() if flags is not None else None
    h_all = np.zeros(U_NODATA, np.int64)
    h_flag = np.zeros(U_NODATA, np.int64)
    for first in range(0, v.size, STRIP_PX):
        part = v[first:first + STRIP_PX]
        ok = part < U_NODATA
        h_all += np.bincount(part[ok], minlength=U_NODATA)[:U_NODATA]
        if f is not None:
            hit = f[first:first + STRIP_PX][ok] != 0
            h_flag += np.bincount(part[ok][hit],
                                  minlength=U_NODATA)[:U_NODATA]
    return h_all, h_flag


def unc_whole_hist(u8, marks, net=None, progress=None):
    """The histograms of the whole map, a strip at a time: (all, changed,
    net). marks may be None, a map nobody changed."""
    h_all = np.zeros(U_NODATA, np.int64)
    h_chg = np.zeros(U_NODATA, np.int64)
    h_net = np.zeros(U_NODATA, np.int64)
    ny, nx = u8.shape
    take = unc_rows_for(nx)
    for row in range(0, ny, take):
        part = u8[row:row + take]
        a, c = unc_hist(part, marks[row:row + take]
                        if marks is not None else None)
        h_all += a
        h_chg += c
        if net is not None:
            h_net += unc_hist(part, net[row:row + take])[1]
        if progress is not None and progress(row + part.shape[0],
                                             ny) is False:
            raise UncRefused("Stopped. Nothing was written.")
    return h_all, h_chg, h_net


def unc_place_hists(u8, marks, net, rows):
    """For each place, the histograms of its window: three arrays of shape
    (places, 255)."""
    n = len(rows)
    p_all = np.zeros((n, U_NODATA), np.int64)
    p_chg = np.zeros((n, U_NODATA), np.int64)
    p_net = np.zeros((n, U_NODATA), np.int64)
    for k, r in enumerate(rows):
        win = (slice(r["row"], r["row"] + r["height"]),
               slice(r["col"], r["col"] + r["width"]))
        p_all[k], p_chg[k] = unc_hist(u8[win], marks[win])
        if net is not None:
            p_net[k] = unc_hist(u8[win], net[win])[1]
    return p_all, p_chg, p_net


def unc_bins(binning, cuts):
    levels = np.arange(U_NODATA)
    if binning == "fixed":
        return st_fixed_bin(levels, U_LEVELS)
    return st_bin_of(levels, cuts)


def unc_scope_rows(scope, h_all, h_chg, h_net, cuts, kind, p_all=None,
                   p_chg=None, big_n=None, net_known=True):
    """The calibration rows of one scope, both binnings."""
    rows = []
    for binning in ("decile", "fixed"):
        bins = unc_bins(binning, cuts)
        base = st_calibration(h_all, h_chg, binning, U_LEVELS,
                              cuts=cuts if binning == "decile" else None)
        for b in base:
            inside = bins == b["bin"]
            n = b["n"]
            net_n = int(h_net[inside].sum()) if net_known else None
            row = {"scope": scope, "binning": binning, "bin": b["bin"],
                   "u_low": b["u_low"], "u_high": b["u_high"], "n_px": n,
                   "changed_px": b["changed"], "share_changed": b["share"],
                   "net_changed_px": net_n,
                   "share_net": (net_n / float(n)) if net_known and n
                   else None,
                   "mean_u": b["mean_u"],
                   "expected_error": b["mean_u"] if kind == "probability"
                   else None, "places": None, "se_share": None,
                   "ci95_low": None, "ci95_high": None,
                   "note": UNC_NOTE_WHOLE}
            if p_all is not None:
                x = p_all[:, inside].sum(axis=1)
                y = p_chg[:, inside].sum(axis=1)
                row["places"] = int((x > 0).sum())
                got = st_ratio_se(y, x, big_n if scope == "random_places"
                                  else None)
                se = got["se"]
                if se == se:
                    row["se_share"] = se
                    row["ci95_low"] = max(0.0, b["share"] - UNC_CI_Z * se)
                    row["ci95_high"] = min(1.0, b["share"] + UNC_CI_Z * se)
                row["note"] = UNC_NOTE_RANDOM if scope == "random_places" \
                    else UNC_NOTE_PURPOSIVE
            rows.append(row)
    return rows


def unc_calibrate(u8, marks, net, places, kind, progress=None):
    """Everything the report says, from the arrays in memory.

    u8, the file of u; marks, the record of changed pixels (1 = a person
    changed it); net, where the copy differs from the map it started from,
    or None when that map is gone; places, the Places of the walk (or
    None). Returns {cuts, rows, auc, ece, capture, single_level, hists,
    place_rows, place_hists}."""
    h_all, h_chg, h_net = unc_whole_hist(u8, marks, net, progress)
    cuts = st_decile_cuts(h_all)
    done = [r for r in (places.rows if places is not None else [])
            if r["status"] == "done"]
    p_all, p_chg, p_net = unc_place_hists(u8, marks, net, done)
    net_known = net is not None
    scopes = {}
    rows = []
    big_n = places.N if places is not None else None
    for scope in UNC_SCOPES:
        if scope == "whole_map":
            a, c, nn = h_all, h_chg, h_net
            pa = pc = None
        else:
            want = "random" if scope == "random_places" else "purposive"
            pick = np.array([r["selection"] == want for r in done],
                            dtype=bool)
            if not pick.any():
                scopes[scope] = None
                continue
            pa, pc = p_all[pick], p_chg[pick]
            a, c, nn = pa.sum(axis=0), pc.sum(axis=0), p_net[pick].sum(axis=0)
        scopes[scope] = (a, c, nn)
        rows.extend(unc_scope_rows(scope, a, c, nn, cuts, kind, pa, pc,
                                   big_n, net_known))
    auc = {}
    ece = {}
    capture = []
    for scope in UNC_SCOPES:
        got = scopes.get(scope)
        if got is None:
            auc[scope] = None
            ece[scope] = None
            continue
        a, c, _ = got
        auc[scope] = st_auc_hist(c, a - c)
        if kind == "probability":
            fixed = [r for r in rows if r["scope"] == scope
                     and r["binning"] == "fixed"]
            ece[scope] = st_ece([r["n_px"] for r in fixed],
                                [r["share_changed"] for r in fixed],
                                [r["mean_u"] for r in fixed])
        else:
            ece[scope] = None
        if scope in ("whole_map", "random_places"):
            for r in st_capture(a, c, UNC_CAPTURE_TOPS, U_LEVELS):
                capture.append(dict(r, scope=scope))
    return {"cuts": cuts, "rows": rows, "auc": auc, "ece": ece,
            "capture": capture,
            "single_level": int((h_all > 0).sum()) <= 1,
            "hists": (h_all, h_chg, h_net), "place_rows": done,
            "place_hists": (p_all, p_chg, p_net)}


class UncNet(object):
    """Where the copy's classes differ from the map it started from, 1 for
    a pixel that does and has a class, worked out a window at a time from
    the two maps. An array of the whole map would be a byte a pixel on top
    of the file of u and the record of changes."""
    ndim = 2
    dtype = np.dtype(np.uint8)

    def __init__(self, values, before, nodata):
        self.values = values
        self.before = before
        self.nodata = nodata

    @property
    def shape(self):
        return (self.values.shape[0], self.values.shape[1])

    def __getitem__(self, key):
        """net[a:b] some rows, net[a:b, c:d] a window: slices that go
        forwards, as the strips and the places of the report ask."""
        if not isinstance(key, tuple):
            key = (key,)
        ny, nx = self.shape
        rows = key[0] if key else slice(None)
        cols = key[1] if len(key) > 1 else slice(None)
        if not isinstance(rows, slice) or not isinstance(cols, slice):
            raise IndexError("the net change is cut by slices")
        r0, r1, rs = rows.indices(ny)
        c0, c1, cs = cols.indices(nx)
        if rs != 1 or cs != 1:
            raise IndexError("the net change is cut by slices of step 1")
        if r1 <= r0 or c1 <= c0:
            return np.zeros((max(0, r1 - r0), max(0, c1 - c0)), np.uint8)
        now_ = np.asarray(self.values[r0:r1, c0:c1])
        was = self.before.window(c0, r0, c1 - c0, r1 - r0)
        valid = unc_class_valid(now_, self.nodata)
        return (valid & (was != now_)).astype(np.uint8)


def unc_net(values, source_path, band_no, nodata):
    """Where the copy's classes differ from the map it started from, read
    a window at a time (UncNet); None when that map cannot be read or is
    not the size of the copy."""
    try:
        before = BandPlane(long_path(str(source_path).split("|")[0]),
                           int(band_no))
        if (before.nx, before.ny) != values.shape[::-1]:
            return None
        before.window(0, 0, 1, 1)
        return UncNet(values, before, nodata)
    except Exception as err:
        log("the map the correction started from cannot be read for the net "
            "change: %s" % err)
        return None


def unc_count_changes(marks, net=None):
    """(marked, net changed, net changed and not marked), counted a strip at
    a time; the last two are None without a net."""
    ny, nx = marks.shape
    take = unc_rows_for(nx)
    marked = changed = loose = 0
    for row in range(0, ny, take):
        m = np.asarray(marks[row:row + take]) != 0
        marked += int(np.count_nonzero(m))
        if net is not None:
            n = np.asarray(net[row:row + take]) != 0
            changed += int(np.count_nonzero(n))
            loose += int(np.count_nonzero(n & ~m))
    if net is None:
        return marked, None, None
    return marked, changed, loose


#  The strokes, again, from operations.csv and the journal
# =====================================================================
def unc_read_operations(path):
    """The rows of operations.csv, as dicts; [] when there is none."""
    try:
        with open(long_path(path), newline="", encoding="utf-8") as fh:
            return [csv_untext_row(r) for r in csv.DictReader(fh)]
    except (OSError, csv.Error):
        return []


def unc_journal_places(path):
    """{stroke number: place id} from the "correct" rows of journal.csv,
    where the walk wrote the place that was current at each stroke."""
    out = {}
    try:
        with open(long_path(path), newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("action") == "correct" and r.get("place"):
                    out[str(r.get("ref") or "")] = r["place"]
    except (OSError, csv.Error):
        pass
    return out


def unc_strokes(operations, places_of, u8, marks):
    """One row per stroke of operations.csv, with u over the pixels of its
    window that are marked as changed now: operations.csv keeps its 14
    columns, and what u was where a stroke changed something is worked out
    here, from the stroke's window over the file of u. A window is read a
    strip of rows at a time: a stroke can be as large as the map."""
    out = []
    ny, nx = u8.shape
    for op in operations:
        try:
            col, row = int(op.get("col")), int(op.get("row"))
            w, h = int(op.get("width")), int(op.get("height"))
        except (TypeError, ValueError):
            continue
        top, bottom = max(0, row), min(ny, row + h)
        left, right = max(0, col), min(nx, col + w)
        take = unc_rows_for(max(1, right - left))
        count = total = peak = 0
        for first in range(top, bottom, take):
            last = min(bottom, first + take)
            u = np.asarray(u8[first:last, left:right])
            pick = (u < U_NODATA) & (np.asarray(
                marks[first:last, left:right]) != 0)
            vals = u[pick]
            if vals.size:
                count += int(vals.size)
                total += int(vals.sum(dtype=np.int64))
                peak = max(peak, int(vals.max()))
        out.append({"n": op.get("n"), "when": op.get("when"),
                    "operator": op.get("operator"),
                    "place": places_of.get(str(op.get("n") or ""), ""),
                    "col": col, "row": row, "width": w, "height": h,
                    "pixels": op.get("pixels"),
                    "u_mean": total / float(count) / U_LEVELS if count
                    else None,
                    "u_max": peak / float(U_LEVELS) if count else None})
    return out


#  The report
# =====================================================================
def unc_check_record(marks, operations, changes_name):
    """The refusal of a report whose record of changes cannot be trusted,
    or None."""
    if marks is None:
        return ("There is no record of which pixels a person changed (%s), "
                "so nothing can be said of where they changed it. Nothing "
                "was written." % changes_name)
    if int(operations or 0) > 0 and not unc_count_changes(marks)[0]:
        return UNC_RESTARTED % (changes_name, int(operations))
    return None


def unc_report(owner, record, spec, arrays, places, paths, operations=0,
               target=None, progress=None, draw=True):
    """The uncertainty report, in a folder of its own under reports/.

    owner is {kind, id, name, folder}; record the correction's manifest;
    spec its "uncertainty"; arrays {u8, marks, net}; places the walk (or
    None); paths {copy, changes, derived, places_csv, operations,
    journal, source}; operations the number of strokes the manifest
    counts. The record of changes is checked first, and a report that
    could not be trusted is refused before anything is written (UncRefused).
    Returns {folder, files, summary, calibration, places}."""
    u8, marks, net = arrays.get("u8"), arrays.get("marks"), arrays.get("net")
    why = unc_check_record(marks, operations,
                           os.path.basename(paths.get("changes") or ""))
    if why:
        raise UncRefused(why)
    if u8 is None:
        raise UncRefused("The uncertainty is not chosen: choose it in "
                         "Correct first (UNCERTAINTY, Source…).")
    kind = spec.get("kind")
    if places is not None:
        places.fill_inclusion()
    cal = unc_calibrate(u8, marks, net, places, kind, progress)
    strokes = unc_strokes(unc_read_operations(paths.get("operations") or ""),
                          unc_journal_places(paths.get("journal") or ""),
                          u8, marks)
    marked, net_px, loose = unc_count_changes(marks, net)
    counts = places.counts() if places is not None else {}
    notes = [UNC_DESIGN_NOTE,
             "The whole map is a lower bound of the error: the pixels nobody "
             "reviewed count as right.",
             "Inside a done place every pixel is taken as reviewed. Changed "
             "is not the same as wrong: a pixel changed and changed back "
             "stays marked; share_net counts only the pixels whose class "
             "differs from the map the correction started from."]
    if cal["single_level"]:
        notes.append(UNC_SINGLE_LEVEL + ".")
    if net is None:
        notes.append("The map the correction started from cannot be read: "
                     "the net change is not given.")
    elif loose:
        notes.append("%d pixels differ from the map the correction started "
                     "from without being marked as changed: the record of "
                     "changes is incomplete there." % loose)
    if counts.get("overlay_seen_random"):
        notes.append("%d random places were reviewed with the uncertainty "
                     "shown on the map: not blind." % counts[
                         "overlay_seen_random"])
    if counts.get("random_reused"):
        notes.append("%d random places had been reviewed before they were "
                     "drawn, as purposive places: they keep their membership "
                     "of the sample but were not reviewed blind."
                     % counts["random_reused"])
    if counts.get("random_done", 0) < 2:
        notes.append("Fewer than two random places are done: no standard "
                     "error yet.")
    for r in cal["rows"]:
        if r["scope"] == "random_places" and r["se_share"] is not None:
            r["note"] = UNC_NOTE_RANDOM
    pi = places.inclusion() if places is not None else None
    if pi is not None:
        notes.append("The inclusion probability of a random place is m/N = "
                     "%d/%d = %.6g, conditional on when the review stopped: "
                     "the size of the sample was not fixed in advance."
                     % (counts["random_drawn_m"], places.N, pi))
    rnd_auc = cal["auc"].get("random_places")
    headline = {"kind": kind, "auc_random": rnd_auc,
                "auc_whole": cal["auc"].get("whole_map"),
                "ece_random": cal["ece"].get("random_places"),
                "random_done": counts.get("random_done", 0),
                "purposive_done": counts.get("purposive_done", 0)}
    operators = sorted(set(r["operator"] for r in cal["place_rows"]
                           if r.get("operator")))
    side_m = None
    try:
        pixel = (record.get("grid") or {}).get("pixel_m") or []
        side_m = float(pixel[0]) * (places.side if places else 0) \
            if pixel else None
    except (TypeError, ValueError, AttributeError):
        side_m = None
    tmp = final = None
    files = ["calibration.csv", "capture.csv", "places.csv", "strokes.csv",
             REPORT_SUMMARY]
    try:
        if target:
            tmp = target + ".tmp"
            os.makedirs(long_path(tmp))
            final = target
        else:
            tmp, final = report_folder(owner["folder"], UNC_KIND)
        report_csv(os.path.join(tmp, "calibration.csv"),
                   UNC_CALIBRATION_COLUMNS,
                   [[r[k] for k in UNC_CALIBRATION_COLUMNS]
                    for r in cal["rows"]])
        report_csv(os.path.join(tmp, "capture.csv"), UNC_CAPTURE_COLUMNS,
                   [[r[k] for k in UNC_CAPTURE_COLUMNS]
                    for r in cal["capture"]])
        p_all, p_chg, _ = cal["place_hists"]
        prow = []
        for k, r in enumerate(cal["place_rows"]):
            n = int(p_all[k].sum())
            c = int(p_chg[k].sum())
            prow.append([r["place_id"], r["selection"], r["operator"],
                         r["mean_u"], n, c, c / float(n) if n else None,
                         r["overlay_on"], r["inclusion_prob"],
                         r["design_use"]])
        report_csv(os.path.join(tmp, "places.csv"),
                   UNC_PLACES_REPORT_COLUMNS, prow)
        report_csv(os.path.join(tmp, "strokes.csv"), UNC_STROKE_COLUMNS,
                   [[s[k] for k in UNC_STROKE_COLUMNS] for s in strokes])
        summary = report_header(UNC_KIND, owner)
        summary.update({
            "inputs": report_inputs([p for p in (
                paths.get("copy"), paths.get("changes"),
                paths.get("derived"), paths.get("places_csv"),
                paths.get("operations")) if p], owner["folder"]),
            "parameters": {"levels": U_LEVELS, "binning": ["decile",
                                                           "fixed"],
                           "decile_cuts": cal["cuts"],
                           "se": "cluster ratio estimator, places as "
                                 "clusters (Cochran 1977)",
                           "ci": "share ± %.2f SE" % UNC_CI_Z,
                           "capture_tops": list(UNC_CAPTURE_TOPS)},
            "headline": report_headline(UNC_KIND, headline),
            "correction": {"name": record.get("name"),
                           "id": record.get("id"),
                           "source": record.get("source"),
                           "band": record.get("band"),
                           "working_copy": os.path.basename(
                               paths.get("copy") or ""),
                           "changes": os.path.basename(
                               paths.get("changes") or "")},
            "uncertainty": {k: spec.get(k) for k in (
                "kind", "scale", "offset", "source", "path", "band",
                "band_name", "grid", "valid_px", "zero_read_as_value",
                "clipped_px")},
            "places": {"side_px": places.side if places else None,
                       "side_m": side_m,
                       "eligible_N": places.N if places else 0,
                       "random_every": places.random_every if places
                       else None,
                       "seed": places.seed if places else None,
                       "blind": places.blind if places else None,
                       "purposive_done": counts.get("purposive_done", 0),
                       "random_drawn_m": counts.get("random_drawn_m", 0),
                       "random_done": counts.get("random_done", 0),
                       "random_skipped": counts.get("random_skipped", 0),
                       "random_reused": counts.get("random_reused", 0),
                       "overlay_seen_random":
                           counts.get("overlay_seen_random", 0),
                       "inclusion_prob": pi},
            "auc": cal["auc"], "ece_fixed": cal["ece"]
            if kind == "probability" else None,
            "single_level": cal["single_level"],
            "changes_record": {"marked_px": marked, "net_px": net_px,
                               "net_not_marked_px": loose,
                               "consistent": None if net is None
                               else not loose},
            "operators": operators,
            "strokes": len(strokes),
            "design_note": UNC_DESIGN_NOTE,
            "notes": notes,
            "files": files + (["calibration.png"] if draw else [])})
        if draw:
            try:
                unc_draw_png(cal, summary, os.path.join(tmp,
                                                        "calibration.png"))
            except Exception as err:
                summary["files"].remove("calibration.png")
                summary["notes"].append("The picture of the curve could not "
                                        "be drawn: %s" % err)
        report_json(os.path.join(tmp, REPORT_SUMMARY), summary)
        final = report_finish(tmp, final)
    except BaseException:
        if tmp:
            report_abandon(tmp)
        raise
    return {"folder": final, "files": summary["files"], "summary": summary,
            "calibration": cal, "strokes": strokes}


def unc_draw_png(cal, summary, path, size=(1200, 800)):
    """The curve as a picture, drawn with Qt (no plotting library): mean u
    per decile across, the share changed up; the random places filled with
    their 95 % bars, the purposive places hollow, the whole map a dashed
    grey line, the diagonal when u is 1 - p, and AUC and ECE in the
    legend."""
    from qgis.PyQt.QtCore import QPointF, QRectF, Qt
    from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter, QPen
    w, h = size
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left, top, right, bottom = 110, 70, w - 300, h - 100
        f = QFont()
        f.setPixelSize(20)
        p.setFont(f)

        def at(x, y):
            return QPointF(left + x * (right - left),
                           bottom - y * (bottom - top))

        axis = QPen(QColor("#333333"))
        axis.setWidth(2)
        p.setPen(axis)
        p.drawLine(at(0, 0), at(1, 0))
        p.drawLine(at(0, 0), at(0, 1))
        grid = QPen(QColor("#dddddd"))
        for k in range(0, 11, 2):
            t = k / 10.0
            p.setPen(grid)
            p.drawLine(at(t, 0), at(t, 1))
            p.drawLine(at(0, t), at(1, t))
            p.setPen(axis)
            p.drawText(QRectF(at(t, 0).x() - 30, bottom + 8, 60, 28),
                       int(Qt.AlignmentFlag.AlignCenter), "%.1f" % t)
            p.drawText(QRectF(left - 70, at(0, t).y() - 14, 60, 28),
                       int(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter), "%.1f" % t)
        p.drawText(QRectF(left, bottom + 40, right - left, 30),
                   int(Qt.AlignmentFlag.AlignCenter),
                   "mean uncertainty u per decile")
        p.save()
        p.translate(30, (top + bottom) / 2.0)
        p.rotate(-90)
        p.drawText(QRectF(-200, -15, 400, 30),
                   int(Qt.AlignmentFlag.AlignCenter),
                   "share of pixels a person changed")
        p.restore()
        kind = (summary.get("uncertainty") or {}).get("kind")
        if kind == "probability":
            diag = QPen(QColor("#888888"))
            diag.setStyle(Qt.PenStyle.DotLine)
            p.setPen(diag)
            p.drawLine(at(0, 0), at(1, 1))
        rows = [r for r in cal["rows"] if r["binning"] == "decile"]

        def line(scope, colour, dashed):
            pts = [at(r["mean_u"], r["share_changed"]) for r in rows
                   if r["scope"] == scope and r["mean_u"] == r["mean_u"]]
            if len(pts) < 2:
                return
            pen = QPen(QColor(colour))
            pen.setWidth(2)
            if dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)

        line("whole_map", "#9a9a9a", True)
        blue = QColor("#2a78d6")
        for r in rows:
            if r["scope"] != "random_places":
                continue
            c = at(r["mean_u"], r["share_changed"])
            if r["se_share"] is not None:
                pen = QPen(blue)
                pen.setWidth(2)
                p.setPen(pen)
                p.drawLine(at(r["mean_u"], r["ci95_low"]),
                           at(r["mean_u"], r["ci95_high"]))
            p.setPen(QPen(blue))
            p.setBrush(blue)
            p.drawEllipse(c, 7, 7)
        orange = QColor("#d65f00")
        for r in rows:
            if r["scope"] != "purposive_places":
                continue
            pen = QPen(orange)
            pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(at(r["mean_u"], r["share_changed"]), 7, 7)
        p.setPen(axis)
        auc = summary.get("auc") or {}
        ece = summary.get("ece_fixed") or {}

        def num(v):
            return "—" if v is None or v != v else "%.3f" % v

        legend = ["● random places (95% CI)",
                  "○ purposive places",
                  "- - whole map (lower bound)",
                  "", "AUC random %s" % num(auc.get("random_places")),
                  "AUC purposive %s" % num(auc.get("purposive_places")),
                  "AUC whole map %s" % num(auc.get("whole_map"))]
        if kind == "probability":
            legend += ["ECE random %s" % num(ece.get("random_places")),
                       "ECE whole map %s" % num(ece.get("whole_map")),
                       "··· y = x"]
        for k, text in enumerate(legend):
            p.drawText(QRectF(right + 30, top + k * 30, 260, 28),
                       int(Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter), text)
        f.setPixelSize(24)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(left, 15, right - left, 40),
                   int(Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter),
                   "Uncertainty against the corrections of a person")
    finally:
        p.end()
    if not img.save(long_path(path), "PNG"):
        raise IOError("cannot write %s" % os.path.basename(path))
    return path


#  What Check and the panel say of it
# =====================================================================
def unc_finding(level, what, detail=""):
    """A line of Check, made by Check's own Finding (doctor comes after this
    module, so it is looked up when a line is made)."""
    import importlib
    package = globals().get("__package__") or ""
    if package:
        doctor = importlib.import_module(".doctor", package)
        return doctor.Finding(level, what, detail)
    return globals()["Finding"](level, what, detail)


def unc_findings(owner):
    """Check, on the uncertainty of a correction. Nothing is repaired."""
    data = getattr(owner, "data", None) or {}
    spec = data.get("uncertainty")
    if not isinstance(spec, dict) or not spec.get("kind"):
        return []
    copy = getattr(owner, "working_path", "") or ""
    if not copy:
        return []
    folder = os.path.dirname(copy)
    derived = unc_path_of(copy, data)
    src = unc_source_path(spec, folder)
    source_there = _there(src) if src else _there(copy)
    out = []
    if not _there(derived):
        if not source_there:
            return [unc_finding(
                "problem", "the uncertainty named in the manifest is not "
                "there", "%s and %s are both missing: the walk and the report "
                "are off until it is chosen again in Correct (UNCERTAINTY, "
                "Source…)" % (os.path.basename(src or copy),
                              os.path.basename(derived)))]
        out.append(unc_finding("note", "%s is not beside the working copy"
                               % os.path.basename(derived),
                               "it is made again when Correct opens"))
    else:
        state, why = unc_file_state(derived, spec, folder)
        if state in ("stale", "other"):
            out.append(unc_finding("note", "%s is out of date: %s"
                                   % (os.path.basename(derived), why),
                                   "it is made again when Correct opens"))
        if not source_there:
            out.append(unc_finding(
                "note", "the raster the uncertainty was read from is not "
                "where it was", "%s: the file made from it is used as it is"
                % (src or copy)))
        share = ""
        if spec.get("map_px"):
            share = ", a value on %.1f%% of the classes" % (
                100.0 * float(spec.get("valid_px") or 0) /
                float(spec["map_px"]))
        out.append(unc_finding("ok", "uncertainty: %s%s"
                               % (unc_describe(spec), share)))
    side = (data.get("places") or {}).get("side_px")
    pfile = os.path.join(folder, PLACES_CSV)
    if side and _there(pfile):
        try:
            places = Places(pfile).load()
        except IOError:
            places = None
        if places is not None and places.rows and places.side != int(side):
            out.append(unc_finding(
                "note", "%s has places of %d px, the manifest says %d"
                % (PLACES_CSV, places.side, int(side))))
        if places is not None:
            seen = places.counts().get("overlay_seen_random", 0)
            if seen:
                out.append(unc_finding(
                    "note", "%d random place%s reviewed with the uncertainty "
                    "on the map" % (seen, "" if seen == 1 else "s"),
                    "not blind: the report says so"))
    return out


def unc_tooltip_line(book):
    """The line the tooltip of the correction's line in the panel adds:
    'uncertainty: probabilita x255, read as 1 - p', or nothing."""
    spec = (getattr(book, "data", None) or {}).get("uncertainty")
    words = unc_describe(spec)
    return "uncertainty: %s" % words if words else ""


def unc_files(copy):
    """The names of the files the walk keeps beside the copy."""
    path = unc_path_of(copy)
    folder = os.path.dirname(path)
    return [path, path + ".aux.xml",
            os.path.join(folder, PLACES_CSV),
            os.path.join(folder, PLACES_CSV + ".tmp"),
            os.path.join(folder, PLACES_GEOJSON),
            os.path.join(folder, PLACES_GEOJSON + ".tmp")]
