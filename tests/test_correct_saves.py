"""What Correct writes reaches the disk, and the original does not move.

The sister suite, test_correct_pixels, asks which pixels the brush decides to
change. This one asks the question after that, and it is the one that matters
when somebody has spent an afternoon correcting a map: does the file on disk
actually hold the change, and is the map the algorithm produced still exactly
what it was.

So nothing here is mocked. A real class raster is written with gdal, the
program's own build_copy() makes the working copy from it and build_changes()
the record of changed pixels beside it, pixels are written through the copy's
band and the record's the way paint() writes them, the handles are dropped,
and then the files are opened again from scratch and read. Reopening is the
whole point: a value that is only in memory looks identical to a value that
was saved, right up until the moment QGIS closes.

Needs the GDAL Python bindings. tests/run.py finds the interpreter that has them.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import os as _os

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os
import shutil
import sys
import tempfile

import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()

SRC = os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def take(name, inside=None):
    for node in tree.body:
        if inside is None and getattr(node, "name", None) == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if inside is None and isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == name for t in node.targets):
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if getattr(sub, "name", None) == name:
                    text = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in text.splitlines())
    raise AssertionError("%s not found" % name)


# The program's own copier and its helpers, run as written. A copy of them in
# this file would pass forever while the program drifted away from them. Two
# rows at a time, so the six rows of this map go through every strip loop.
FLAG_BAND_NAME = "corrected"
space = {"gdal": gdal, "np": np, "os": os, "FLAG_BAND_NAME": FLAG_BAND_NAME,
         "STRIP_ROWS": 2, "log": print}
for name in ("LOSSLESS", "long_path", "_there", "_move", "_drop",
             "_quiet_gdal", "_loud_gdal", "temporary_name", "is_bigtiff",
             "creation_options_like", "_translate", "_forget_statistics",
             "build_copy", "build_changes", "flag_band_of", "_same_value",
             "differences", "type_for_all", "held_aux_of", "settle_held_aux",
             "strip_flag_band", "PICTURE_GRID", "pixel_grid", "has_grid", "open_raster",
             "write_window"):
    exec(compile(take(name), "<%s>" % name, "exec"), space)
build_copy = space["build_copy"]
build_changes = space["build_changes"]
strip_flag_band = space["strip_flag_band"]
write_window = space["write_window"]

CROP, MUD, WATER, ROCK, NODATA = 1, 2, 3, 4, 255
GROUND = np.array([
    [CROP,  CROP,  MUD,   MUD,   WATER, WATER],
    [CROP,  MUD,   MUD,   MUD,   WATER, WATER],
    [ROCK,  MUD,   MUD,   NODATA, WATER, 0],
    [ROCK,  ROCK,  MUD,   NODATA, 0,    0],
    [ROCK,  ROCK,  WATER, WATER, 0,    0],
    [ROCK,  ROCK,  ROCK,  WATER, WATER, 0],
], dtype=np.uint8)

folder = tempfile.mkdtemp(prefix="rl_correct_")
try:
    original = os.path.join(folder, "mask_from_the_model.tif")
    ds = gdal.GetDriverByName("GTiff").Create(original, 6, 6, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((500000.0, 0.05, 0.0, 4100000.0, 0.0, -0.05))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32633)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.WriteArray(GROUND)
    band.SetNoDataValue(NODATA)
    band.SetDescription("classes")
    ds.FlushCache()
    ds = None
    before = open(original, "rb").read()

    print("the working copy is made from the map the model produced")
    copy = os.path.join(folder, "mask_corrected.tif")
    changes = os.path.join(folder, "mask_corrected_changes.tif")
    notes = []
    total = build_copy(original, copy, notes, band_no=1)
    check("it exists", os.path.exists(copy))
    check("with the bands of the original and not one more", total == 1, total)
    check("and nothing to complain about", not notes, notes)
    check("and nothing half written left beside it",
          sorted(os.listdir(folder)) == ["mask_corrected.tif",
                                         "mask_from_the_model.tif"],
          os.listdir(folder))
    marked = build_changes(copy, changes)
    check("the record of changed pixels is made beside it, empty",
          os.path.exists(changes) and marked == 0, marked)

    out = gdal.Open(copy)
    check("same size", (out.RasterXSize, out.RasterYSize) == (6, 6),
          (out.RasterXSize, out.RasterYSize))
    check("same grid, to the last decimal",
          out.GetGeoTransform() == (500000.0, 0.05, 0.0, 4100000.0, 0.0, -0.05),
          out.GetGeoTransform())
    check("same projection", "32633" in out.GetProjection(),
          out.GetProjection()[:60])
    copied = out.GetRasterBand(1).ReadAsArray()
    check("and the very same pixels", (copied == GROUND).all())
    check("the nodata value came across",
          out.GetRasterBand(1).GetNoDataValue() == NODATA,
          out.GetRasterBand(1).GetNoDataValue())
    check("and the name of the band", out.GetRasterBand(1).GetDescription()
          == "classes", out.GetRasterBand(1).GetDescription())
    check("one band, as the original: no flag band inside it",
          out.RasterCount == 1, out.RasterCount)
    out = None
    rec = gdal.Open(changes)
    check("the record is one byte band on the same grid, named",
          rec.RasterCount == 1 and (rec.RasterXSize, rec.RasterYSize) == (6, 6)
          and rec.GetGeoTransform() == (500000.0, 0.05, 0.0, 4100000.0, 0.0,
                                        -0.05)
          and rec.GetRasterBand(1).DataType == gdal.GDT_Byte
          and rec.GetRasterBand(1).GetDescription() == FLAG_BAND_NAME)
    check("and it starts empty: nobody has moved anything yet",
          not rec.GetRasterBand(1).ReadAsArray().any())
    rec = None

    print()
    print("a correction is written through the copy, the way paint writes it")
    # Exactly what paint() does once it has decided: write the window back into
    # the class band and mark the record beside it, through the program's own
    # write_window, which opens each file for the stroke alone and closes it.
    # Only mud becomes water.
    work = gdal.Open(copy)
    record = gdal.Open(changes)
    values = work.GetRasterBand(1).ReadAsArray()
    marks = record.GetRasterBand(1).ReadAsArray()
    work = record = None
    change = values == MUD
    moved = int(change.sum())
    values[change] = WATER
    marks[change] = 1
    write_window(copy, 1, values, 0, 0)
    write_window(changes, 1, marks, 0, 0)

    print()
    print("and now the files are opened again from nothing, which is the test")
    again = gdal.Open(copy)
    saved = again.GetRasterBand(1).ReadAsArray()
    seen = gdal.Open(changes)
    flagged = seen.GetRasterBand(1).ReadAsArray()
    check("there is no mud left in the file", not (saved == MUD).any())
    check("exactly the pixels that were mud are now water",
          (saved[change] == WATER).all() and int((saved == WATER).sum())
          == int((GROUND == WATER).sum()) + moved,
          (int((saved == WATER).sum()), int((GROUND == WATER).sum()) + moved))
    check("every other pixel is untouched, value for value",
          (saved[~change] == GROUND[~change]).all())
    check("the nodata hole survived", (saved == NODATA).sum()
          == (GROUND == NODATA).sum())
    check("the record beside it says exactly what a person moved",
          (flagged.astype(bool) == change).all())
    check("and nothing else", int(flagged.sum()) == moved,
          (int(flagged.sum()), moved))
    again = seen = None

    print()
    print("the map the model produced is byte for byte what it was")
    check("not one byte of the original has changed",
          open(original, "rb").read() == before)
    back = gdal.Open(original)
    check("and reading it back gives the pixels it started with",
          (back.GetRasterBand(1).ReadAsArray() == GROUND).all())
    check("it still has one band, with nothing added to it",
          back.RasterCount == 1, back.RasterCount)
    back = None

    print()
    print("a second correction on top of the first adds to the record")
    work = gdal.Open(copy, gdal.GA_Update)
    record = gdal.Open(changes, gdal.GA_Update)
    values = work.GetRasterBand(1).ReadAsArray()
    marks = record.GetRasterBand(1).ReadAsArray()
    second = values == ROCK
    values[second] = CROP
    marks[second] = 1
    work.GetRasterBand(1).WriteArray(values)
    record.GetRasterBand(1).WriteArray(marks)
    work.FlushCache()
    record.FlushCache()
    work = record = None
    again = gdal.Open(changes)
    flagged = again.GetRasterBand(1).ReadAsArray()
    check("both corrections are remembered",
          int(flagged.sum()) == moved + int(second.sum()),
          (int(flagged.sum()), moved + int(second.sum())))
    again = None
    again = gdal.Open(copy)
    check("and the first one is still in the pixels",
          not (again.GetRasterBand(1).ReadAsArray() == MUD).any())
    again = None

    print()
    print("opening the same source twice does not disturb the first copy")
    second_copy = os.path.join(folder, "mask_corrected_2.tif")
    build_copy(original, second_copy, [])
    # The dataset has to be held while its band is read: a chained
    # gdal.Open(...).GetRasterBand(1).ReadAsArray() frees the dataset between
    # the two calls and the band it left behind points at nothing.
    first_ds = gdal.Open(copy)
    one = first_ds.GetRasterBand(1).ReadAsArray()
    second_ds = gdal.Open(second_copy)
    two = second_ds.GetRasterBand(1).ReadAsArray()
    check("the new copy is the original again, not the corrected one",
          (two == GROUND).all())
    check("and the corrected one is still corrected",
          not (one == MUD).any())
    first_ds = second_ds = None

    print()
    print("a copy of an earlier build, with its flag band, loses only the band")
    old = os.path.join(folder, "old_corrected.tif")
    ds = gdal.GetDriverByName("GTiff").Create(old, 6, 6, 2, gdal.GDT_Byte)
    ds.SetGeoTransform((500000.0, 0.05, 0.0, 4100000.0, 0.0, -0.05))
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(saved)
    ds.GetRasterBand(1).SetNoDataValue(NODATA)
    ds.GetRasterBand(1).SetDescription("classes")
    ds.GetRasterBand(2).WriteArray(flagged)
    ds.GetRasterBand(2).SetDescription(FLAG_BAND_NAME)
    ds = None
    old_changes = os.path.join(folder, "old_corrected_changes.tif")
    done = strip_flag_band(old, old_changes, 1)
    check("it says what it did", done == {"pixels": int(flagged.sum()),
                                          "band": 1, "dropped": 2, "bands": 1},
          done)
    kept = gdal.Open(old)
    check("the copy keeps its classes, and only them",
          kept.RasterCount == 1
          and (kept.GetRasterBand(1).ReadAsArray() == saved).all()
          and kept.GetRasterBand(1).GetDescription() == "classes"
          and kept.GetRasterBand(1).GetNoDataValue() == NODATA)
    kept = None
    moved_out = gdal.Open(old_changes)
    check("and the band is beside it, pixel for pixel",
          (moved_out.GetRasterBand(1).ReadAsArray() == flagged).all())
    moved_out = None
    check("a copy already in shape is left alone",
          strip_flag_band(old, old_changes, 1) is None)

    print()
    print("what the module writes beside the copy")
    wl = take("write_log", "CorrectionSection")
    check("every operation is written to a csv as it happens",
          "csv.writer(f)" in wl and 'open(self.log_path, "a"' in wl)
    check("with a header the first time", "if fresh:" in wl)
    check("and the file is named, not nameless",
          "LOG_COLUMNS" in source)
    sv = take("save", "CorrectionSection")
    check("Save has nothing to flush: no handle is held between strokes",
          "FlushCache" not in sv
          and "GA_Update" not in take("paint", "CorrectionSection")
          and "self.ds =" not in take("CorrectionSection")
          and "self.changes =" not in take("CorrectionSection"))
    check("and writes the correction into the manifest",
          "self.remember()" in sv)
    cd = take("close_dataset", "CorrectionSection")
    check("and closing dresses the copy once, through no held handle",
          "if not self.closed:" in cd and "self.dress()" in cd)
finally:
    shutil.rmtree(folder, ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
