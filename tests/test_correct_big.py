"""A big map is corrected in the memory a small one is.

Correct used to read the class band, and the record of changes beside it,
whole into memory when a correction opened, and to count the codes of the
band by turning all of it into 64 bit integers: a map of 400 million pixels
asked for about 17 times its own size, 6.8 GB for a map of 20000 x 20000
bytes, and QGIS on a laptop closed. The class inventory of a new correction
and Check read the band whole as well.

So a real map of 6000 x 6000 pixels, tiled and compressed as a classifier
writes them, is walked through a new correction (the classes read and shown,
the copy made), Correct opened on it, a stroke, an Undo, Check, the
correction opened again from the list, and in all of it:

  no read of the band asks for more than a strip of it (the largest read,
  in pixels, is a small share of the band);
  what Python holds at the most, besides the band's own file, is less than
  the band itself (it was about nine times the band, with no map larger
  than this one);
  the class band and the record of changes are the files, and a pixel, a
  window and the codes of the band are what numpy says of the same band.

Needs the GDAL Python bindings. QGIS is faked, see correctkit.py. The map of
20000 x 20000 that was measured before and after is in the notes of the
change, not here: it takes a minute.
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
root = tempfile.mkdtemp(prefix="rl_correct_big_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
source = os.path.join(root, "data", "classes.tif")
os.makedirs(os.path.dirname(source))

# five classes in blocks, written strip by strip: the test does not hold the
# band either
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)
ds = gdal.GetDriverByName("GTiff").Create(
    source, N, N, 1, gdal.GDT_Byte,
    ["COMPRESS=DEFLATE", "TILED=YES", "BLOCKXSIZE=256", "BLOCKYSIZE=256"])
ds.SetGeoTransform((500000.0, 0.1, 0.0, 4100000.0, 0.0, -0.1))
ds.SetProjection(srs.ExportToWkt())
band = ds.GetRasterBand(1)
cols = (np.arange(N) // 900).astype(np.int64)
for row in range(0, N, 500):
    rows = (np.arange(row, row + 500) // 900).astype(np.int64)
    band.WriteArray((1 + (cols[None, :] + rows[:, None]) % 5)
                    .astype(np.uint8), 0, row)
band = ds = None


def classes_in(a):
    return sorted(set(np.unique(a).tolist()))


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


layer = K.add_layer(K.Layer(source, "big"))
folder = os.path.join(root, "fixes", "big_fix")
manifest = os.path.join(folder, "correction.json")


def new_campaign(d):
    d.existing.setCurrentIndex(d.existing.findData("new:"))
    d.name.setText("big fix")
    d.raster.setCurrentIndex(d.raster.findData(layer.id()))
    d.fill_bands()
    d.folder.setText(folder)
    d.operator.setText("ann")
    return 1


def open_again(d):
    d.existing.setCurrentIndex(d.existing.findData("open:" + manifest))
    return 1


panel = g["Panel"]()
K.ANSWERS["OpenCorrection"] = new_campaign
seen = {}


def confirm(d):
    seen["rows"] = [(r["value"].value(), r["pixels"].text()) for r in d.rows]
    return 1


K.ANSWERS["ConfirmClasses"] = confirm
print("a new correction on a map of %d x %d" % (N, N))
READS[:] = []
tracemalloc.start()
tracemalloc.reset_peak()
mark = tracemalloc.get_traced_memory()[0]
panel.toggle_module(1)
peak_new = tracemalloc.get_traced_memory()[1] - mark
reads_new = biggest()
section = panel.section
check("Correct opens", type(section).__name__ == "CorrectionSection",
      (type(section).__name__, K.UNEXPECTED, K.BOXES[-3:]))
check("the classes window shows the five classes and what each holds",
      [v for v, _ in seen.get("rows", [])] == [1, 2, 3, 4, 5], seen)
check("Python held %.0f MB at the most, for a band of %.0f MB"
      % (peak_new / 2 ** 20, BAND_BYTES / 2 ** 20),
      peak_new < BAND_BYTES, peak_new)
check("and no read of it asked for more than %.1f%% of the band (%.1f M "
      "pixels)" % (100.0 * reads_new / BAND_BYTES, reads_new / 1e6),
      reads_new <= 0.15 * BAND_BYTES, reads_new)

print()
print("the band and the record are the files")
check("both are read from their files",
      type(section.values).__name__ == "BandPlane"
      and type(section.marks).__name__ == "BandPlane")
whole = gdal.Open(source).ReadAsArray()
check("the same pixels as the map has", np.array_equal(
    section.values[1000:1100, 2000:2100], whole[1000:1100, 2000:2100])
    and section.values[5999, 5999] == whole[5999, 5999])
READS[:] = []
tracemalloc.reset_peak()
mark = tracemalloc.get_traced_memory()[0]
codes = g["codes_present"](section.values, None)
counts = g["class_counts"](section.values, None)
peak = tracemalloc.get_traced_memory()[1] - mark
found, n = np.unique(whole, return_counts=True)
check("its codes and their counts are what numpy says",
      codes == found.tolist()
      and counts == {int(a): int(b) for a, b in zip(found, n)}, counts)
check("counted in %.0f MB, in strips of at most %.1f M pixels"
      % (peak / 2 ** 20, biggest() / 1e6),
      peak < BAND_BYTES and biggest() <= 0.15 * BAND_BYTES,
      (peak, biggest()))
del whole

print()
print("a stroke, Undo, Check")
READS[:] = []
tracemalloc.reset_peak()
mark = tracemalloc.get_traced_memory()[0]
inside = np.ones((300, 400), bool)
section.mask_of = lambda geom: (1000, 1000, inside)
before = section.values[1000:1300, 1000:1400]
section.choose_from(None)
section.choose_class(5)
section.paint(K.Stroke())
after = section.values[1000:1300, 1000:1400]
check("the stroke is in the file",
      (after == 5).all() and not np.array_equal(before, after))
check("and counted, 120000 pixels of 0.01 m2 at most",
      section.operations == 1 and 0 < section.changed_m2 <= 1300,
      (section.operations, section.changed_m2))
section.undo()
check("Undo puts the window back", np.array_equal(
    section.values[1000:1300, 1000:1400], before))
text, bad, notes = g["report"](None, panel.correction, campaign_too=False)
peak = tracemalloc.get_traced_memory()[1] - mark
check("Check finds nothing wrong, and says the copy has a class for every "
      "code in it", not bad and "every code in the copy has a class" in text,
      bad)
check("none of it read more than a strip of the band, or held %.0f MB"
      % (peak / 2 ** 20),
      biggest() <= 0.15 * BAND_BYTES and peak < BAND_BYTES,
      (biggest(), peak))

print()
print("opened again")
panel.close_correction()
K.ANSWERS["OpenCorrection"] = open_again
READS[:] = []
tracemalloc.reset_peak()
mark = tracemalloc.get_traced_memory()[0]
panel.open_correction_campaign()
peak = tracemalloc.get_traced_memory()[1] - mark
check("it opens", panel.section is not None
      and type(panel.section).__name__ == "CorrectionSection")
check("in %.0f MB, reading at most %.1f M pixels at once"
      % (peak / 2 ** 20, biggest() / 1e6),
      peak < BAND_BYTES and biggest() <= 0.15 * BAND_BYTES,
      (peak, biggest()))
tracemalloc.stop()
panel.close_correction()

gdal.Band.ReadAsArray = real_read
shutil.rmtree(root, ignore_errors=True)
sys.exit(K.finish())
