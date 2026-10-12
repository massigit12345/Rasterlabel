"""The uncertainty of Correct on a big map holds a strip of it, not the map.

Correct reads in strips (BandPlane), but the uncertainty beside it kept the
whole file of u in memory, a byte a pixel, the net change from the map the
correction started from as another, and the report took each of them whole:
a map of 20000 x 20000 pixels with a probability band asked for 2.1 GB at
the report and 690 MB just to open (the same map after: 264 MB and 261 MB,
with 191 MB being the program and QGIS's own libraries; the numbers are in
the notes of the change, they take a minute to measure).

So a real map of 6000 x 6000 pixels, tiled and compressed as a classifier
writes them, with a class band and a probability band, is walked through
Correct, and in all of it:

  Use it (the file of u made, the places cut, the sparkline's histograms)
  holds, in Python, a small share of the map and reads no more than a
  strip of it at a time (the strip of this suite is 100 000 pixels, which
  is what makes the share small on a map this size; the one line Use it
  says of a reading is worked out from a 512 x 512 look at the map, some
  13 MB whatever the map, which is why the map here is not smaller);
  the file of u is read from its file, a window at a time (BandPlane),
  and so is the record of changes;
  a stroke, Done, and the report hold a small share of the map too;
  and the report is, to the byte, the one that comes of the same arrays
  held in memory: the calibration, the capture curve, the places and the
  strokes.

Then the pieces, on arrays, with the strip made so small that every one of
them goes through many: the blocks of a map as wide as a place, the
histograms, the counts of changes, the net change cut by windows, the
strokes with a window of the whole map.

Needs the GDAL Python bindings. QGIS is faked, see correctkit.py.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile
import tracemalloc

os.environ["RL_KIT_REAL_GDAL"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                                 # noqa: E402
from osgeo import gdal, osr                                        # noqa: E402
import correctkit as K                                             # noqa: E402

gdal.UseExceptions()
g, check = K.g, K.check

N = 6000
BAND_BYTES = N * N
STRIP = 100000
root = tempfile.mkdtemp(prefix="rl_unc_big_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
source = os.path.join(root, "data", "classes.tif")
os.makedirs(os.path.dirname(source))

srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)
ds = gdal.GetDriverByName("GTiff").Create(
    source, N, N, 2, gdal.GDT_Byte,
    ["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256"])
ds.SetGeoTransform((500000.0, 0.1, 0.0, 4100000.0, 0.0, -0.1))
ds.SetProjection(srs.ExportToWkt())
for b, name in ((1, "classe"), (2, "probabilita x255")):
    ds.GetRasterBand(b).SetNoDataValue(0)
    ds.GetRasterBand(b).SetDescription(name)
rng = np.random.default_rng(5)
cols = np.arange(N)
for row in range(0, N, 500):
    rows = np.arange(row, row + 500)
    cls = (1 + ((cols[None, :] // 900) + (rows[:, None] // 900)) % 5)
    cls = cls.astype(np.uint8)
    if row == 0:
        cls[:50, :] = 0                     # a margin of nodata
    prob = 150 + 90 * np.sin(cols[None, :] / 400.0) * np.cos(rows[:, None]
                                                              / 300.0)
    prob = (prob + rng.integers(-6, 7, (500, N))).clip(1, 255)
    ds.GetRasterBand(1).WriteArray(cls, 0, row)
    ds.GetRasterBand(2).WriteArray(np.where(cls > 0, prob, 0)
                                   .astype(np.uint8), 0, row)
ds = None

# a strip of 100 000 pixels, wherever the program asks how much to hold
REAL_STRIP = g["STRIP_PX"]
g["STRIP_PX"] = STRIP

# every read of a band: the pixels it brings back, None for the whole band
READS = []
real_read = gdal.Band.ReadAsArray


def spy(self, xoff=0, yoff=0, win_xsize=None, win_ysize=None, buf_xsize=None,
        buf_ysize=None, *a, **k):
    w = buf_xsize or win_xsize
    h = buf_ysize or win_ysize
    READS.append(None if w is None or h is None else w * h)
    return real_read(self, xoff, yoff, win_xsize, win_ysize, buf_xsize,
                     buf_ysize, *a, **k)


gdal.Band.ReadAsArray = spy


def biggest():
    return max([BAND_BYTES if r is None else r for r in READS] or [0])


class Held(object):
    """What Python held at the most, in megabytes, while it ran."""

    def __enter__(self):
        READS[:] = []
        tracemalloc.reset_peak()
        self.mark = tracemalloc.get_traced_memory()[0]
        return self

    def __exit__(self, *exc):
        self.peak = tracemalloc.get_traced_memory()[1] - self.mark
        return False

    @property
    def mb(self):
        return self.peak / 2 ** 20


layer = K.add_layer(K.Layer(source, "big"))
folder = os.path.join(root, "fixes", "big_fix")
panel = g["Panel"]()


def new_correction(d):
    d.existing.setCurrentIndex(d.existing.findData("new:"))
    d.name.setText("big fix")
    d.raster.setCurrentIndex(d.raster.findData(layer.id()))
    d.fill_bands()
    d.folder.setText(folder)
    d.operator.setText("ann")
    return 1


K.ANSWERS["OpenCorrection"] = new_correction
K.ANSWERS["ConfirmClasses"] = lambda d: 1
panel.toggle_module(1)
section = panel.section
tracemalloc.start()
try:
    print("Correct opens on a map of %d x %d with a probability band" % (N, N))
    check("Correct opens", type(section).__name__ == "CorrectionSection",
          (type(section).__name__, K.UNEXPECTED, K.BOXES[-3:]))
    hook = g["unc_hook_of"](section)
    card = hook.card

    print()
    print("Use it: the file of u is made, the places cut")
    with Held() as held:
        card.use_it()
    spec = section.record.get("uncertainty") or {}
    check("the probability of the class, band 2, was read",
          (spec.get("kind"), spec.get("band")) == ("probability", 2), spec)
    check("Python held %.1f MB at the most, for a map of %.0f MB"
          % (held.mb, BAND_BYTES / 2 ** 20),
          held.peak < 0.5 * BAND_BYTES, held.peak)
    check("and no read asked for more than %.1f%% of the map (%.2f M "
          "pixels)" % (100.0 * biggest() / BAND_BYTES, biggest() / 1e6),
          biggest() <= 0.15 * BAND_BYTES, biggest())
    check("the file of u is read from its file, so is the record of changes",
          type(hook.u8).__name__ == "BandPlane"
          and (section.marks is None
               or type(section.marks).__name__ == "BandPlane"),
          (type(hook.u8).__name__, type(section.marks).__name__))
    check("it is the size of the map and a byte a pixel",
          hook.u8.shape == (N, N) and hook.u8.dtype == np.uint8)
    derived = hook.derived
    check("the places are cut", hook.places is not None
          and hook.places.N > 100, hook.places and hook.places.N)

    print()
    print("a stroke, Done, and the sparkline's histograms")
    with Held() as held:
        card.next()                                  # Start
        here = hook.places.current()
        h, w = max(1, here["height"] // 2), max(1, here["width"] // 2)
        inside = np.ones((h, w), bool)
        col, row = here["col"] + here["width"] // 4, \
            here["row"] + here["height"] // 4
        section.mask_of = lambda geom: (col, row, inside)
        section.choose_from(None)
        section.choose_class(5 if int(section.values[row, col]) != 5 else 4)
        section.paint(K.Stroke())
        card.next()                                  # Done
    check("held %.1f MB, read at most %.2f M pixels"
          % (held.mb, biggest() / 1e6),
          held.peak < 0.5 * BAND_BYTES and biggest() <= 0.15 * BAND_BYTES,
          (held.peak, biggest()))
    check("the stroke is in the record of changes and the walk counted it",
          int(section.marks[row:row + h, col:col + w].sum()) > 0
          and hook.places.counts()["purposive_done"] == 1,
          hook.places.counts())

    print()
    print("the report")
    K.ANSWERS["ReportWindow"] = lambda d: 1
    with Held() as held:
        result = g["unc_report_start"](panel)
    check("it is written", result is not None
          and os.path.isfile(os.path.join(result["folder"], "summary.json")),
          K.BOXES[-3:])
    check("Python held %.1f MB at the most, for a map of %.0f MB"
          % (held.mb, BAND_BYTES / 2 ** 20),
          held.peak < 0.5 * BAND_BYTES, held.peak)
    check("and no read asked for more than %.1f%% of the map (%.2f M "
          "pixels)" % (100.0 * biggest() / BAND_BYTES, biggest() / 1e6),
          biggest() <= 0.15 * BAND_BYTES, biggest())
    summary = result["summary"]
    check("the record of changes is consistent with the net change",
          summary["changes_record"]["consistent"] is True
          and summary["changes_record"]["net_px"] > 0,
          summary["changes_record"])
finally:
    tracemalloc.stop()
    gdal.Band.ReadAsArray = real_read

print()
print("the same report from the same arrays held whole")
folder_of = {}
values_whole = section.values[0:N, 0:N]
marks_whole = section.marks[0:N, 0:N]
u_ds, before_ds = gdal.Open(derived), gdal.Open(source)
u_whole = u_ds.ReadAsArray()
before_whole = before_ds.GetRasterBand(1).ReadAsArray()
u_ds = before_ds = None
net_whole = (g["unc_class_valid"](values_whole, section.nodata)
             & (before_whole != values_whole)).astype(np.uint8)
paths = {"copy": section.path, "changes": section.changes_path,
         "derived": derived, "places_csv": hook.places_path,
         "operations": section.log_path,
         "journal": os.path.join(os.path.dirname(section.path),
                                 "journal.csv"),
         "source": section.record.get("source")}
owner = {"kind": "correction", "id": "x", "name": "big",
         "folder": os.path.join(root, "again")}
os.makedirs(owner["folder"])
again = g["unc_report"](owner, section.record, hook.spec,
                        {"u8": u_whole, "marks": marks_whole,
                         "net": net_whole}, hook.places, paths,
                        section.record.get("operations", 0), draw=False)
for name in ("calibration.csv", "capture.csv", "places.csv", "strokes.csv"):
    a = open(os.path.join(result["folder"], name), "rb").read()
    b = open(os.path.join(again["folder"], name), "rb").read()
    check("%s is the same, byte for byte (%d bytes)" % (name, len(a)),
          a == b)
check("and so is every number of the summary that is not a time",
      all(summary[k] == again["summary"][k] for k in
          ("auc", "ece_fixed", "changes_record", "strokes", "places",
           "single_level", "operators")), None)

print()
print("the net change, cut by windows, is the net change")
net = g["unc_net"](section.values, section.record.get("source"), 1,
                   section.nodata)
check("it is not an array of the map", net is not None
      and type(net).__name__ == "UncNet" and net.shape == (N, N))
spots = [(slice(0, 7), slice(0, 9)), (slice(40, 400), slice(100, 5999)),
         (slice(N - 3, N + 10), slice(N - 5, N)), (slice(2000, 2000),
                                                   slice(0, 5))]
check("windows, rows, and the empty one are what the whole says",
      all(np.array_equal(net[w], net_whole[w]) for w in spots)
      and np.array_equal(net[300:700], net_whole[300:700]))
try:
    net[::2]
    stepped = False
except IndexError:
    stepped = True
check("a step of 2 is refused", stepped)

# ---------------------------------------------------------------- pieces
print()
print("the pieces, with a strip so small that every one goes through many")
rng = np.random.default_rng(3)
U = rng.integers(0, 256, (300, 777)).astype(np.uint8)
U[:, :40] = 255
MARKS = (rng.random(U.shape) < 0.1).astype(np.uint8)
NET = (rng.random(U.shape) < 0.07).astype(np.uint8)
g["STRIP_PX"] = 10 ** 9
whole_blocks = g["unc_score_blocks"](U, 32)
whole_hist = g["unc_whole_hist"](U, MARKS, NET)
g["STRIP_PX"] = 1500                    # one block, a tile row at the least
cut_blocks = g["unc_score_blocks"](U, 32)
cut_hist = g["unc_whole_hist"](U, MARKS, NET)
g["STRIP_PX"] = STRIP
check("the blocks of a map scored a run of blocks at a time are the same",
      all(np.array_equal(whole_blocks[k], cut_blocks[k]) for k in
          ("bi", "bj", "n_px", "n_valid", "sum", "max", "eligible")))
check("the histograms of a strip at a time are the same",
      all(np.array_equal(a, b) for a, b in zip(whole_hist, cut_hist)))
check("a map nobody changed: the histograms without a record",
      np.array_equal(g["unc_whole_hist"](U, None)[0], whole_hist[0])
      and not g["unc_whole_hist"](U, None)[1].any())
marked, changed, loose = g["unc_count_changes"](MARKS, NET)
check("marked, net, and net but not marked are what numpy counts",
      (marked, changed, loose) == (int(MARKS.sum()), int(NET.sum()),
                                   int(((NET != 0) & (MARKS == 0)).sum())),
      (marked, changed, loose))
check("without a net, the last two are None",
      g["unc_count_changes"](MARKS)[1:] == (None, None))
ops = [{"n": "1", "col": "0", "row": "0", "width": "777", "height": "300",
        "when": "", "operator": "", "pixels": "5"},
       {"n": "2", "col": "100", "row": "50", "width": "20", "height": "9",
        "when": "", "operator": "", "pixels": "5"},
       {"n": "3", "col": "-5", "row": "290", "width": "40", "height": "99",
        "when": "", "operator": "", "pixels": "5"},
       {"n": "4", "col": "5000", "row": "0", "width": "3", "height": "3",
        "when": "", "operator": "", "pixels": "5"}]
g["STRIP_PX"] = 1500
got = g["unc_strokes"](ops, {}, U, MARKS)
g["STRIP_PX"] = STRIP
want = []
for op in ops:
    c, r, w_, h_ = (int(op[k]) for k in ("col", "row", "width", "height"))
    win = (slice(max(0, r), min(300, r + h_)), slice(max(0, c), min(777,
                                                                      c + w_)))
    u = U[win]
    pick = (u < 255) & (MARKS[win] != 0)
    vals = u[pick].astype(np.float64) / 254
    want.append((float(vals.mean()) if vals.size else None,
                 float(vals.max()) if vals.size else None))
check("the u of a stroke as large as the map, a small one, one past the "
      "edge and one off the map",
      all((a["u_mean"] is None) == (b[0] is None)
          and (a["u_mean"] is None or (abs(a["u_mean"] - b[0]) < 1e-12
                                       and abs(a["u_max"] - b[1]) < 1e-12))
          for a, b in zip(got, want)), (got, want))
g["STRIP_PX"] = REAL_STRIP
check("the rows of a strip are whole tile rows, 256 at the least",
      all(g["unc_rows_for"](nx) % 256 == 0 and g["unc_rows_for"](nx) >= 256
          for nx in (1, 100, 5000, 20000, 400000)))
check("and about STRIP_PX pixels, never more than STRIP_ROWS of them",
      g["unc_rows_for"](100) == 512 and g["unc_rows_for"](2000) == 512
      and g["unc_rows_for"](20000) == 256)
g["STRIP_PX"] = STRIP

gdal.Band.ReadAsArray = real_read
shutil.rmtree(root, ignore_errors=True)
sys.exit(K.finish())
