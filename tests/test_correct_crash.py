"""A stroke of Correct is on disk, whole, the moment it is made: for QGIS
reading the map while Correct is open, and after a QGIS that died.

Correct used to hold the corrected map and the record of changes beside it
open for writing for the whole correction, and only flushed them after each
stroke. Through the libtiff of Debian and Ubuntu a compressed block flushed
that way cannot be read by another handle until the writer closes: QGIS drew
the map blank after the first stroke, no other program could read it, and a
QGIS killed in the middle of a correction left the blocks of the last stroke
unreadable. On Windows it all worked, which is how it got this far.

Now each stroke opens the files, writes its window and closes them
(write_window). This suite writes strokes the way Correct does, with the
program's own functions, into a copy and a record made by the program's own
build_copy and build_changes, on the two layouts a copy has: the strips of
the map it was copied from, and tiles. Then:

- a second handle, opened after the stroke as QGIS's layer is when it is
  told to reload, reads every pixel, with GDAL errors raised;
- a process that wrote a stroke and still holds the map open is killed, the
  way a crashed QGIS goes, and the files are read back from nothing: every
  block readable, the stroke in them, every other pixel as it was;
- the map is opened for writing again after the kill, without anybody
  having closed it, an Undo is written, and it reads back as it arrived.

Needs the GDAL Python bindings. tests/run.py finds the interpreter that has
them.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import os as _os

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os
import shutil
import subprocess
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


# The program's own functions, run as written.
FLAG_BAND_NAME = "corrected"
space = {"gdal": gdal, "np": np, "os": os, "FLAG_BAND_NAME": FLAG_BAND_NAME,
         "STRIP_ROWS": 64, "log": print}
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
write_window = space["write_window"]

print("Correct writes every stroke through a handle it closes")
cs = take("CorrectionSection")
ws = take("write_stroke", "CorrectionSection")
check("paint and Undo write through write_stroke",
      "self.write_stroke(" in take("paint", "CorrectionSection")
      and "self.write_stroke(" in take("undo", "CorrectionSection"))
check("which writes the copy and the record with write_window",
      "write_window(self.path" in ws and "write_window(self.changes_path" in ws)
check("and no handle for writing is kept on the section",
      "self.ds =" not in cs and "self.changes =" not in cs
      and "self.flag =" not in cs and "FlushCache" not in cs)
wr = take("write_window")
check("write_window closes what it opened before it returns",
      "GA_Update" in wr and "close()" in wr and "ds = None" in wr)

# The child: a Correct that wrote a stroke and is then killed. It reads the
# program's write_window out of the same file, writes the stroke, keeps the
# map open for reading the way QGIS keeps its layer, says so, and waits to be
# killed.
CHILD = r'''
import ast, os, sys, time
import numpy as np
from osgeo import gdal
gdal.UseExceptions()
src, copy, changes, col, row, path_after = sys.argv[1:7]
col, row = int(col), int(row)
text = open(src, encoding="utf-8").read()
tree = ast.parse(text)
lines = text.splitlines(True)
space = {"gdal": gdal, "np": np, "os": os}
for node in tree.body:
    if getattr(node, "name", None) in ("write_window", "_quiet_gdal",
                                       "_loud_gdal"):
        exec(compile("".join(lines[node.lineno - 1:node.end_lineno]),
                     "<child>", "exec"), space)
values = np.load(os.path.join(path_after, "values.npy"))
marks = np.load(os.path.join(path_after, "marks.npy"))
space["write_window"](copy, 1, values, col, row)
space["write_window"](changes, 1, marks, col, row)
layer = gdal.Open(copy)                 # what QGIS holds while you paint
layer.GetRasterBand(1).ReadAsArray(col, row, 1, 1)
print("STROKE WRITTEN", flush=True)
time.sleep(120)
'''

H, W = 520, 600
CROP, MUD, WATER, ROCK, INTO, NODATA = 1, 2, 3, 4, 7, 255
yy, xx = np.mgrid[0:H, 0:W]
GROUND = np.where(xx < 200, CROP, np.where(yy < 260, MUD,
                  np.where(xx < 420, WATER, ROCK))).astype(np.uint8)
GROUND[(xx - 500) ** 2 + (yy - 80) ** 2 < 900] = NODATA

# A stroke across the boundaries of strips and of 256-pixel tiles: the blocks
# it touches are partly rewritten, which is where a half-written block shows.
COL, ROW, SW, SH = 180, 190, 300, 150
wy, wx = np.mgrid[0:SH, 0:SW]
INSIDE = ((wx - SW / 2) / (SW / 2)) ** 2 + ((wy - SH / 2) / (SH / 2)) ** 2 < 1


def make_map(path, options):
    ds = gdal.GetDriverByName("GTiff").Create(path, W, H, 1, gdal.GDT_Byte,
                                              options)
    ds.SetGeoTransform((500000.0, 0.5, 0.0, 4100000.0, 0.0, -0.5))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32633)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.WriteArray(GROUND)
    band.SetNoDataValue(NODATA)
    band = None
    ds = None


def read_whole(path):
    """Every pixel, through a handle of its own, with GDAL errors raised and
    any error GDAL only notes counted as well."""
    gdal.ErrorReset()
    ds = gdal.Open(path)
    try:
        got = ds.GetRasterBand(1).ReadAsArray()
        cs_ = ds.GetRasterBand(1).Checksum()
    finally:
        ds = None
    return got, cs_, gdal.GetLastErrorType()


folder = tempfile.mkdtemp(prefix="rl_correct_crash_")
try:
    for layout, options in (
            ("strips, DEFLATE", ["COMPRESS=DEFLATE"]),
            ("tiles, DEFLATE, predictor",
             ["COMPRESS=DEFLATE", "PREDICTOR=2", "TILED=YES"])):
        print()
        print("a map in %s" % layout)
        here = os.path.join(folder, layout.split(",")[0])
        os.makedirs(here)
        original = os.path.join(here, "map.tif")
        make_map(original, options)
        copy = os.path.join(here, "map_corrected.tif")
        changes = os.path.join(here, "map_corrected_changes.tif")
        notes = []
        build_copy(original, copy, notes, band_no=1)
        build_changes(copy, changes)
        ims = gdal.Open(copy).GetMetadata("IMAGE_STRUCTURE")
        check("the copy is compressed as the map is",
              ims.get("COMPRESSION") == "DEFLATE", ims)

        window = GROUND[ROW:ROW + SH, COL:COL + SW].copy()
        change = INSIDE & (window != NODATA) & (window != INTO)
        after = window.copy()
        after[change] = INTO
        marks = change.astype(np.uint8)
        expected = GROUND.copy()
        expected[ROW:ROW + SH, COL:COL + SW] = after
        expected_marks = np.zeros((H, W), np.uint8)
        expected_marks[ROW:ROW + SH, COL:COL + SW] = marks

        # QGIS's layer is open on the copy while the stroke is written.
        layer = gdal.Open(copy)
        layer.GetRasterBand(1).ReadAsArray(0, 0, 8, 8)
        write_window(copy, 1, after, COL, ROW)
        write_window(changes, 1, marks, COL, ROW)
        got, _, err = read_whole(copy)
        check("a reader opened after the stroke reads the copy whole, "
              "while QGIS still has it open", err == 0, err)
        check("and finds the stroke in it, and nothing else changed",
              (got == expected).all(), int((got != expected).sum()))
        got, _, err = read_whole(changes)
        check("the record of changes reads whole too, and holds the stroke",
              err == 0 and (got == expected_marks).all(),
              (err, int((got != expected_marks).sum())))
        layer = None

        # Back to the map as it arrived, for the process that is killed.
        write_window(copy, 1, window, COL, ROW)
        write_window(changes, 1, np.zeros_like(marks), COL, ROW)
        check("the stroke is undone the same way",
              (read_whole(copy)[0] == GROUND).all()
              and not read_whole(changes)[0].any())

        print("  a Correct that wrote a stroke is killed, as a QGIS that dies")
        np.save(os.path.join(here, "values.npy"), after)
        np.save(os.path.join(here, "marks.npy"), marks)
        child = os.path.join(folder, "child.py")
        with open(child, "w", encoding="utf-8") as f:
            f.write(CHILD)
        proc = subprocess.Popen(
            [sys.executable, child, SRC, copy, changes, str(COL), str(ROW),
             here], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, encoding="utf-8", errors="replace")
        said = proc.stdout.readline()
        proc.kill()
        out, err_text = proc.communicate(timeout=60)
        check("the child wrote its stroke and was killed with the map open",
              said.strip() == "STROKE WRITTEN" and proc.returncode != 0,
              (said, proc.returncode, err_text[-500:]))
        got, checksum, err = read_whole(copy)
        check("after the kill every block of the copy reads, with no error",
              err == 0, err)
        check("and it holds the stroke, every other pixel as it was",
              (got == expected).all(), int((got != expected).sum()))
        flagged, _, err = read_whole(changes)
        check("the record of changes reads whole after the kill as well",
              err == 0 and (flagged == expected_marks).all(),
              (err, int((flagged != expected_marks).sum())))
        info = gdal.Info(copy, format="json", computeChecksum=True)
        check("and gdal.Info reads it to the same checksum",
              info["bands"][0].get("checksum") == checksum, info.get("bands"))

        print("  opened again with nobody having closed it, and undone")
        write_window(copy, 1, window, COL, ROW)
        write_window(changes, 1, np.zeros_like(marks), COL, ROW)
        got, _, err = read_whole(copy)
        check("the Undo is written into the copy the dead process left",
              err == 0 and (got == GROUND).all(),
              (err, int((got != GROUND).sum())))
        got, _, err = read_whole(changes)
        check("and the record says nobody changed anything",
              err == 0 and not got.any(), (err, int(got.sum())))
        check("the original map was never touched",
              (read_whole(original)[0] == GROUND).all())

    print()
    print("a file that cannot be opened for writing is said, not ignored")
    try:
        write_window(os.path.join(folder, "not_there.tif"), 1,
                     np.zeros((2, 2), np.uint8), 0, 0)
        raised = ""
    except IOError as err:
        raised = str(err)
    check("write_window raises, naming the file",
          "not_there.tif" in raised, raised)
finally:
    shutil.rmtree(folder, ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
