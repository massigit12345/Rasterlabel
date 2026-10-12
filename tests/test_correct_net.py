"""Correct counts net, files its strokes under who struck, refuses a write that
failed, and holds a band by its file instead of in memory.

QGIS and the rasters are faked (correctkit.py), so this runs anywhere; the
same things on real files and a real QGIS are test_correct_big and
test_correct_ground_qgis.

  Undo:        operations.csv is the log of what was written and keeps the row
               of a stroke that was undone, in its fourteen columns; the
               manifest says how much of it was undone, and only once
               something was; the panel counts net of it, says how much ground
               a person changed once each, and the list of corrections says
               the net count; Model vs corrected reads the log as gross and
               says what was undone;
  operator:    the creator, unless the operator picked in the panel in this
               session, unless one is typed in the box of Correct; every row
               and the list of operators of the manifest say who struck; a
               correction made and corrected by one person keeps its manifest;
  write:       a copy that cannot be written (the write answers with an error,
               or the close does) refuses the stroke and the Undo: nothing is
               counted, logged or kept in the history, and the record of
               changes given up on its own leaves the strokes working;
  memory:      the class band and the record of changes are the files, read a
               window or a strip at a time (BandPlane); the codes of a large
               band are counted without turning all of it into 64 bit
               integers, and the answer is the one np.unique gives.

Needs PyQt5 or PyQt6, and numpy. Not GDAL.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import json
import os
import sys
import tempfile
import tracemalloc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correctkit as K                                             # noqa: E402
import numpy as np                                                 # noqa: E402

g, check = K.g, K.check

WATER, CROPS, ROADS, FOREST, NODATA = 0, 3, 7, 12, 255
MAP = np.array([
    [WATER, WATER, CROPS, CROPS, CROPS, ROADS, FOREST, FOREST],
    [WATER, WATER, CROPS, CROPS, CROPS, ROADS, FOREST, FOREST],
    [WATER, CROPS, CROPS, NODATA, NODATA, ROADS, FOREST, FOREST],
    [CROPS, CROPS, CROPS, NODATA, NODATA, ROADS, ROADS, FOREST],
    [CROPS, CROPS, ROADS, ROADS, ROADS, ROADS, FOREST, FOREST],
    [CROPS, CROPS, ROADS, FOREST, FOREST, FOREST, FOREST, FOREST],
], dtype=np.uint8)

root = tempfile.mkdtemp(prefix="rl_correct_net_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
source = os.path.join(root, "data", "landcover_model.tif")
K.write_map(source, MAP, NODATA)               # a pixel of 2 m: 4 m2
styled = K.Paletted(None, 1, [
    K.Paletted.Class(WATER, "#1f78b4", "water"),
    K.Paletted.Class(CROPS, "#e6c229", "crops"),
    K.Paletted.Class(ROADS, "#444444", "roads"),
    K.Paletted.Class(FOREST, "#1b7f2a", "forest")])
thematic = K.add_layer(K.Layer(source, "landcover", styled))
folder = os.path.join(root, "fixes", "landcover_fix")
manifest = os.path.join(folder, "correction.json")
copy = os.path.join(folder, "landcover_model_corrected.tif")
changes = os.path.join(folder, "landcover_model_corrected_changes.tif")
ops_csv = os.path.join(folder, "operations.csv")

# every read of a band the fake disk is asked for, as (w, h), None for whole
READS = []
real_read = K.Band.ReadAsArray


def spy(self, x=0, y=0, w=None, h=None, *a, **k):
    READS.append((w, h))
    return real_read(self, x, y, w, h, *a, **k)


K.Band.ReadAsArray = spy


def new_campaign(d):
    d.existing.setCurrentIndex(d.existing.findData("new:"))
    d.name.setText("landcover fix")
    d.raster.setCurrentIndex(d.raster.findData(thematic.id()))
    d.fill_bands()
    d.folder.setText(folder)
    d.operator.setText("ann")
    return 1


SEEN = {}


def open_again(d):
    SEEN["items"] = [d.existing.itemText(i) for i in range(d.existing.count())]
    d.existing.setCurrentIndex(d.existing.findData("open:" + manifest))
    return 1


def stroke(section, rows, cols, from_code, into):
    """A rectangle of pixels, rows and cols as (first, past the last)."""
    inside = np.ones((rows[1] - rows[0], cols[1] - cols[0]), bool)
    section.mask_of = lambda geom: (cols[0], rows[0], inside)
    section.choose_from(from_code)
    section.choose_class(into)
    section.paint(K.Stroke())


def rows_of():
    with open(ops_csv, newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


def book():
    with open(manifest, encoding="utf-8") as fh:
        return json.load(fh)


panel = g["Panel"]()
# a reading somebody else picked in this session for another campaign
g["SESSION"]["operator"] = "ZOE"
K.ANSWERS["OpenCorrection"] = new_campaign
K.ANSWERS["ConfirmClasses"] = lambda d: 1
READS[:] = []
panel.toggle_module(1)
section = panel.section
check("Correct opens", type(section).__name__ == "CorrectionSection",
      type(section).__name__)

# ------------------------------------------------------------ the memory
print("the class band and the record of changes are the files")
Plane = g["BandPlane"]
check("the class band is read from its file, not held",
      isinstance(section.values, Plane) and section.values.shape == (6, 8)
      and section.values.dtype == np.uint8 and section.values.nodata == NODATA,
      type(section.values))
check("and so is the record of changes",
      isinstance(section.marks, Plane) and section.marks.shape == (6, 8))
check("no read of a whole band was asked for in making the correction, "
      "counting its classes, and opening it",
      all(w is not None for w, _ in READS), READS)
READS[:] = []
check("a pixel", section.values[2, 3] == NODATA and section.values[-1, -1]
      == FOREST)
check("a window", np.array_equal(section.values[1:4, 2:7], MAP[1:4, 2:7]))
check("some rows", np.array_equal(section.values[4:], MAP[4:]))
check("a column", np.array_equal(section.values[:, 1], MAP[:, 1]))
check("a step", np.array_equal(section.values[::2, ::3], MAP[::2, ::3]))
check("nothing, as numpy has it",
      section.values[3:3, 0:4].shape == MAP[3:3, 0:4].shape
      and section.values[2:4, 5:5].shape == MAP[2:4, 5:5].shape)
check("the whole band when it is asked for as an array",
      np.array_equal(np.asarray(section.values), MAP)
      and np.array_equal(section.values.copy(), MAP))
check("a comparison of the band is an array, as for one in memory",
      np.array_equal(section.values == CROPS, MAP == CROPS)
      and np.array_equal(section.values != CROPS, MAP != CROPS))
try:
    section.values[6, 0]
    check("a pixel off the band is an error", False)
except IndexError:
    check("a pixel off the band is an error", True)

print()
print("counting the codes a strip at a time gives numpy's answer")
rng = np.random.default_rng(3)
cases = [
    ("bytes", rng.integers(0, 6, (3000, 1500)).astype(np.uint8), 0),
    ("shorts, some below zero", rng.integers(-40, 900, (2500, 1800))
     .astype(np.int16), -40),
    ("sixteen bits unsigned", rng.integers(0, 60000, (2200, 2200))
     .astype(np.uint16), None),
    ("32 bit integers", rng.integers(0, 70000, (2200, 2200))
     .astype(np.int32), 5),
    ("floats with holes", np.where(rng.random((2300, 2000)) < 0.1, np.nan,
                                   rng.integers(0, 9, (2300, 2000)))
     .astype(np.float32), None),
]
for word, a, nodata in cases:
    # a band wider than the room of a strip: more than one strip
    codes = g["codes_present"](a, nodata)
    counts = g["class_counts"](a, nodata)
    flat = a[np.isfinite(a)] if a.dtype.kind == "f" else a.ravel()
    found, n = np.unique(flat, return_counts=True)
    want = {int(v): int(c) for v, c in zip(found.tolist(), n.tolist())
            if float(v) == int(v) and (nodata is None or v != nodata)}
    check("%s: the codes" % word, codes == sorted(want), (codes[:5],
                                                           sorted(want)[:5]))
    check("%s: and how many pixels hold each" % word, counts == want)
fake_whole = np.zeros((10, 10), np.uint8)
check("nothing, and nothing but nodata",
      g["codes_present"](np.zeros(0, np.uint8)) == []
      and g["class_counts"](fake_whole + 255, 255) == {}
      and g["codes_present"](None) == [] and g["class_counts"](None) == {})
check("a code that is not whole is not a code",
      g["codes_present"](np.array([1.0, 2.5, 3.0, np.inf])) == [1, 3])

print()
print("and without holding eight times the band to do it")
band = np.random.default_rng(5).integers(0, 9, (4000, 4000)).astype(np.uint8)
tracemalloc.start()
tracemalloc.reset_peak()
base = tracemalloc.get_traced_memory()[0]
g["codes_present"](band, 255)
g["class_counts"](band, 255)
peak = tracemalloc.get_traced_memory()[1] - base
tracemalloc.stop()
check("16 million pixels are counted in less than twice their own size "
      "(%.0f MB for a band of %.0f MB)" % (peak / 2 ** 20, band.nbytes / 2 ** 20),
      peak < 2 * band.nbytes, peak)
del band

# ----------------------------------------------------------------- Undo
print()
print("Undo leaves a trace, and the count is net")
check("a correction nobody has undone anything in has no 'undone' in its "
      "manifest", "undone" not in book() and book()["operators"] == ["ANN"],
      sorted(book()))
stroke(section, (0, 2), (2, 5), CROPS, FOREST)          # 6 pixels, 24 m2
section.undo()
stroke(section, (0, 2), (2, 5), CROPS, FOREST)          # the same, again
stroke(section, (0, 2), (2, 5), FOREST, ROADS)          # and over them again
rows = rows_of()
check("a correction just made by ANN, with another reading in the panel, "
      "is ANN's: the name typed in the window that made it",
      rows[1][2] == "ANN" and rows[3][2] == "ANN", rows)
check("operations.csv keeps a row for each stroke written, the undone one "
      "included, in fourteen columns",
      len(rows) == 4 and all(len(r) == 14 for r in rows)
      and rows[0][:3] == ["n", "when", "operator"], rows)
b = book()
check("the manifest counts what was written, as the log does",
      b["operations"] == 3 and abs(b["changed_m2"] - 72.0) < 1e-9
      and sum(n for n, _ in b["pairs"].values()) == 3, b["pairs"])
check("and says how much of it was undone",
      b["undone"]["operations"] == 1
      and abs(b["undone"]["changed_m2"] - 24.0) < 1e-9
      and list(b["undone"]["pairs"].values()) == [[1, 24.0]], b.get("undone"))
check("the panel counts net: two operations, 48 m2",
      section.net_operations == 2 and abs(section.net_m2 - 48.0) < 1e-9
      and "<b>2</b> operations (1 undone)" in section.tally.text()
      and "48.00 m2" in section.tally.text(), section.tally.text())
check("and, the strokes having gone over the same six pixels, says so: "
      "24 m2 once each",
      section.on_ground_px == 6 and abs(section.on_ground_m2 - 24.0) < 1e-9
      and "on the ground, once each" in section.tally.text()
      and "24.00 m2" in section.tally.text(), section.tally.text())
check("the pairs of the panel are net: the first stroke is counted once",
      sorted(n for n, _ in section.net_pairs().values()) == [1, 1],
      section.net_pairs())
import re as _re                                                   # noqa: E402
rows = section.tally.text()
check("a row says its strokes in words: the count cannot be read as a "
      "thousands separator before the area",
      "m2 in 1 stroke<" in rows and not _re.search(r"\d, \d+\.\d\d m2", rows),
      rows)
logged = g["mvc_logged"](b)
check("Model vs corrected reads the log as gross, and says what was undone",
      logged["operations"] == 3 and abs(logged["changed_m2_gross"] - 72) < 1e-9
      and logged["operations_undone"] == 1
      and abs(logged["changed_m2_undone"] - 24.0) < 1e-9, logged)
check("a manifest that never had an Undo has no such words in it",
      "operations_undone" not in g["mvc_logged"](
          {"operations": 2, "changed_m2": 8.0, "pairs": {}}))
section.save()
panel.close_correction()
g["SESSION"]["operator"] = None
K.ANSWERS["OpenCorrection"] = open_again
panel.open_correction_campaign()
section = panel.section
check("the list of corrections says the net count",
      any("landcover_fix" in t and "2 operations" in t
          for t in SEEN.get("items", [])), SEEN.get("items"))
check("opened again, it counts net, and the ground once each is read back "
      "from the record",
      section is not None and section.net_operations == 2
      and "<b>2</b> operations (1 undone)" in section.tally.text()
      and section.on_ground_px == 6, section.tally.text())
check("Undo has nothing to take back in a session that has made no stroke",
      not section.history)
stroke(section, (0, 2), (2, 5), ROADS, FOREST)
section.undo()
check("an Undo in a later session is counted with the earlier ones",
      section.net_operations == 2 and book()["undone"]["operations"] == 2
      and abs(book()["undone"]["changed_m2"] - 48.0) < 1e-9
      and len(rows_of()) == 5, book().get("undone"))
check("and the pixels go back to what the stroke before it left",
      (K.read_map(copy)[0:2, 2:5] == ROADS).all(), K.read_map(copy)[0:2])

# --------------------------------------------------------------- operator
print()
print("who struck")
check("the creator, when nobody said otherwise",
      section.operator_name() == "ANN" and rows_of()[-1][2] == "ANN",
      rows_of()[-1])
g["SESSION"]["operator"] = "bruno".upper()
stroke(section, (2, 4), (0, 3), CROPS, ROADS)
check("the operator picked in the panel in this session files the stroke",
      rows_of()[-1][2] == "BRUNO", rows_of()[-1])
check("and joins the operators of the correction, after the creator",
      book()["operators"] == ["ANN", "BRUNO"], book()["operators"])
section.who.setText("carla")
section.operator_edited()
stroke(section, (4, 6), (0, 2), CROPS, ROADS)
check("one typed in the box of Correct comes first, in capitals",
      rows_of()[-1][2] == "CARLA" and section.who.text() == "CARLA"
      and book()["operators"] == ["ANN", "BRUNO", "CARLA"], rows_of()[-1])
check("the journal and the tooltip say the same",
      "CARLA" in section.describe(), section.describe())
panel.close_correction()
g["SESSION"]["operator"] = None
K.ANSWERS["OpenCorrection"] = open_again
panel.open_correction_campaign()
section = panel.section
check("opened again, the box has what was typed, remembered on this machine",
      section.who.text() == "CARLA" and section.operator_name() == "CARLA")
section.who.setText("")
section.operator_edited()
check("emptied, it is the creator again", section.operator_name() == "ANN")

# ------------------------------------------------------------ a failed write
print()
print("a copy that cannot be written refuses the stroke")
copy_band = K.DISK[K.key(copy)]["bands"][0]
changes_band = K.DISK[K.key(changes)]["bands"][0]
operations = section.operations
shown = section.tally.text()
pixels_before = K.read_map(copy)
depth = len(section.history)
n_rows = len(rows_of())
saved_book = book()

copy_band.WriteArray = lambda a, x=0, y=0: 1           # CE_Failure
stroke(section, (4, 6), (4, 8), ROADS, WATER)
check("the write answered with an error: nothing is counted",
      section.operations == operations and len(section.history) == depth
      and section.tally.text() == shown, (section.operations, operations))
check("nothing is logged", len(rows_of()) == n_rows)
check("the manifest is as it was", book() == saved_book)
check("and the map is as it was", np.array_equal(K.read_map(copy),
                                                pixels_before))
del copy_band.WriteArray

closes = []


def refuse_once(self):
    closes.append(1)                    # the flush failed, once
    return 1 if len(closes) == 1 else 0


K.DataSet.Close = refuse_once
stroke(section, (4, 6), (4, 8), ROADS, WATER)
del K.DataSet.Close
check("the close answered with an error: the same, and the blocks that "
      "reached the disk are put back",
      section.operations == operations and len(rows_of()) == n_rows
      and len(section.history) == depth
      and np.array_equal(K.read_map(copy), pixels_before),
      K.read_map(copy)[4:6])

stroke(section, (4, 6), (4, 8), ROADS, WATER)
check("writable again, the same stroke is made and counted",
      section.operations == operations + 1 and len(rows_of()) == n_rows + 1
      and (K.read_map(copy)[4:6, 4:8] != pixels_before[4:6, 4:8]).any())

done_ops, done_undone = section.operations, section.undone["operations"]
copy_band.WriteArray = lambda a, x=0, y=0: 1
section.undo()
check("an Undo that cannot be written is not made: the stroke is kept to be "
      "undone, and not counted as undone",
      len(section.history) == depth + 1
      and section.undone["operations"] == done_undone
      and section.operations == done_ops, (len(section.history), depth))
del copy_band.WriteArray
section.undo()
check("and is made once the copy can be written",
      len(section.history) == depth
      and section.undone["operations"] == done_undone + 1)

changes_band.WriteArray = lambda a, x=0, y=0: 1
stroke(section, (4, 6), (4, 8), ROADS, WATER)
check("a record of changes that cannot be written is given up, said, and "
      "the strokes still work",
      section.marks is None and section.on_ground_px is None
      and section.operations == done_ops + 1
      and (K.read_map(copy)[4:6, 4:8] != pixels_before[4:6, 4:8]).any(),
      section.marks)
del changes_band.WriteArray
section.undo()
check("and the Undo works without it",
      section.undone["operations"] == done_undone + 2
      and np.array_equal(K.read_map(copy), pixels_before))

# a map that is not a class band of bytes: the codes of 16 bits come through
print()
print("a window of any type")
wide = os.path.join(root, "data", "wide.tif")
K.write_map(wide, (MAP.astype(np.uint16) * 300), None)
plane = Plane(wide, 1)
check("sixteen bits", plane.dtype == np.uint16
      and plane[0, 6] == FOREST * 300 and plane.nodata is None)
check("and its codes", g["codes_present"](plane, None)
      == sorted(set((MAP.astype(np.uint16) * 300).ravel().tolist())))

sys.exit(K.finish())
