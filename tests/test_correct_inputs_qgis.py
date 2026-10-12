"""Maps that are not what a correction needs, chosen in a real QGIS.

A correction takes its classes from the codes of one band and finds the
pixels under a stroke on a north-up grid. Three kinds of map break one of
the two, and a new correction went ahead on each of them without a word:

  a class map saved with a compression that does not keep values exactly, a
  JPEG above all: the compression leaves values that are no class along the
  edges of the classes, and the classes window offered them as classes;
  a class map exported as a picture in colour: its classes are colours across
  red, green and blue, and the correction made classes of the shades of the
  red band, with no question at all when the picture had few colours;
  a map on a rotated grid: every stroke changed other pixels than the ones
  painted over, and operations.csv wrote it down as done.

Here each is chosen as the map of a new correction, in a real QGIS, with the
panel the program's own:

  rasters.lossy_codec names JPEG, WebP and JPEG 2000 when they lose values,
  and nothing when they do not: a lossless WebP or JPEG 2000 is as exact as
  a GeoTIFF;
  a lossy class map asks first, Cancel the default: Cancel makes nothing,
  Yes goes on to the classes window; a lossless one is not asked about;
  a picture in colour asks its own question, before the one about too many
  values and instead of it, and says to convert it to a map of codes;
  a map on a rotated grid is refused before anything is asked or written,
  and a correction whose working copy is on a rotated grid is not opened;
  the window that chooses the map says each of these as soon as it is
  picked.

Needs QGIS itself, and GDAL, which comes with it. tests/run.py skips it where
QGIS is missing and, with RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The recent corrections are a QGIS setting: kept in a profile of this run's
# own, not in the profile of whoever runs it.
_PROFILE = tempfile.mkdtemp(prefix="rl_inputs_profile_")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = _PROFILE
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.environ.get("RL_ROOT") or os.path.dirname(_HERE)
SRC = os.environ.get("RL_SRC", os.path.join(_ROOT, "dist", "rasterlabel.py"))

from qgis.core import Qgis, QgsApplication, QgsProject, QgsRasterLayer
from qgis.PyQt import QtWidgets
from qgis.gui import QgsMapCanvas
import qgis.utils
import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()
app = QgsApplication([], False)
app.initQgis()
print("QGIS %s, GDAL %s" % (Qgis.QGIS_VERSION, gdal.__version__))


class Bar:
    def pushMessage(self, *a, **k):
        pass


class Tree:
    def refreshLayerSymbology(self, *a):
        pass


class Iface:
    def __init__(self):
        self.canvas = QgsMapCanvas()
        self.main = QtWidgets.QMainWindow()

    def mapCanvas(self): return self.canvas
    def messageBar(self): return Bar()
    def layerTreeView(self): return Tree()
    def mainWindow(self): return self.main
    def addDockWidget(self, *a): pass
    def removeDockWidget(self, *a): pass
    def setActiveLayer(self, *a): pass


qgis.utils.iface = Iface()
with open(SRC, encoding="utf-8") as _f:
    code = _f.read().replace("\nstart()\n", "\n")
g = {"__name__": "rasterlabel", "__file__": SRC}
exec(compile(code, SRC, "exec"), g)

ANSWERS = {}
ASKED = []


def run_dialog(d):
    name = type(d).__name__
    ASKED.append(name)
    f = ANSWERS.pop(name, None)
    if f is None:
        return 0
    return f(d)


g["run_dialog"] = run_dialog

QMB = QtWidgets.QMessageBox
BOXES = []              # (text, buttons, default button)
REPLY = [QMB.StandardButton.Cancel]


def _warning(*a, **k):
    BOXES.append((str(a[2] if len(a) > 2 else ""),
                  a[3] if len(a) > 3 else None, a[4] if len(a) > 4 else None))
    return REPLY[0]


QMB.warning = staticmethod(_warning)
QMB.critical = staticmethod(lambda *a, **k: BOXES.append(
    ("critical: " + str(a[2] if len(a) > 2 else ""), None, None))
    or QMB.StandardButton.Ok)
QMB.information = staticmethod(lambda *a, **k: QMB.StandardButton.Ok)

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)[:700]) if not cond and detail != "" else ""))
    if not cond:
        fails.append(name)


# ----------------------------------------------------------------- the maps
NX, NY = 96, 72
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)
WKT = srs.ExportToWkt()
GT = (500000.0, 2.0, 0.0, 4100000.0, 0.0, -2.0)
# twenty degrees, the way a world file from the Georeferencer turns a grid
ANGLE = np.radians(20.0)
ROTATED = (500000.0, 2.0 * np.cos(ANGLE), 2.0 * np.sin(ANGLE),
           4100000.0, 2.0 * np.sin(ANGLE), -2.0 * np.cos(ANGLE))
CODES = (1, 2, 3, 4)
COLOURS = {1: (31, 120, 180), 2: (230, 194, 41), 3: (68, 68, 68),
           4: (27, 127, 42)}

classes = np.empty((NY, NX), np.uint8)
for i, c in enumerate(CODES):
    classes[:, i * NX // 4:(i + 1) * NX // 4] = c
classes[NY // 3:NY // 2, NX // 5:NX // 2] = 3


def mem(arrays, gt=GT):
    ds = gdal.GetDriverByName("MEM").Create("", NX, NY, len(arrays),
                                            gdal.GDT_Byte)
    ds.SetGeoTransform(gt)
    ds.SetProjection(WKT)
    for b, a in enumerate(arrays, start=1):
        ds.GetRasterBand(b).WriteArray(a)
    if len(arrays) == 3:
        for b, ci in enumerate((gdal.GCI_RedBand, gdal.GCI_GreenBand,
                                gdal.GCI_BlueBand), start=1):
            ds.GetRasterBand(b).SetColorInterpretation(ci)
    return ds


def save(path, driver, arrays, options=(), gt=GT):
    out = gdal.GetDriverByName(driver).CreateCopy(path, mem(arrays, gt), 0,
                                                  list(options))
    out = None
    return path


def colour_bands():
    rgb = [np.zeros((NY, NX), np.uint8) for _ in range(3)]
    for c, col in COLOURS.items():
        for k in range(3):
            rgb[k][classes == c] = col[k]
    return rgb


def photo_bands():
    y, x = np.mgrid[0:NY, 0:NX]
    return [((x * 3 + y) % 256).astype(np.uint8),
            ((x + y * 3) % 256).astype(np.uint8),
            ((x * 2 + y * 2) % 256).astype(np.uint8)]


root = tempfile.mkdtemp(prefix="rl_inputs_")
data = os.path.join(root, "data")
os.makedirs(data)
K = {}
K["tif"] = save(os.path.join(data, "landcover.tif"), "GTiff", [classes],
                ["COMPRESS=LZW"])
K["jpg"] = save(os.path.join(data, "landcover.jpg"), "JPEG", [classes],
                ["QUALITY=75"])
K["tif_jpeg"] = save(os.path.join(data, "landcover_jpeg.tif"), "GTiff",
                     [classes], ["COMPRESS=JPEG"])
K["jp2_lossy"] = save(os.path.join(data, "landcover_lossy.jp2"),
                      "JP2OpenJPEG", [classes], ["QUALITY=20"])
K["jp2_lossless"] = save(os.path.join(data, "landcover_lossless.jp2"),
                         "JP2OpenJPEG", [classes],
                         ["REVERSIBLE=YES", "QUALITY=100"])
K["webp_lossy"] = save(os.path.join(data, "colours_lossy.webp"), "WEBP",
                       colour_bands(), ["QUALITY=60"])
K["webp_lossless"] = save(os.path.join(data, "colours_lossless.webp"),
                          "WEBP", colour_bands(), ["LOSSLESS=YES"])
K["tif_webp"] = save(os.path.join(data, "colours_webp.tif"), "GTiff",
                     colour_bands(), ["COMPRESS=WEBP"])
K["tif_webp_lossless"] = save(os.path.join(data, "colours_webp_ll.tif"),
                              "GTiff", colour_bands(),
                              ["COMPRESS=WEBP", "WEBP_LOSSLESS=YES"])
# LERC is exact unless an error is allowed: Cutouts and Correct ask the same
# function, rasters.lossy_codec
K["tif_lerc"] = save(os.path.join(data, "landcover_lerc.tif"), "GTiff",
                     [classes], ["COMPRESS=LERC", "MAX_Z_ERROR=0.6"])
K["tif_lerc_exact"] = save(os.path.join(data, "landcover_lerc0.tif"),
                           "GTiff", [classes], ["COMPRESS=LERC"])
K["tif2"] = save(os.path.join(data, "landcover_two.tif"), "GTiff", [classes],
                 ["COMPRESS=LZW"])
K["png"] = save(os.path.join(data, "landcover.png"), "PNG", [classes])
K["colour_png"] = save(os.path.join(data, "map_picture.png"), "PNG",
                       colour_bands())
K["colour_jpg"] = save(os.path.join(data, "map_picture.jpg"), "JPEG",
                       colour_bands())
K["photo"] = save(os.path.join(data, "photo.tif"), "GTiff", photo_bands())
K["rotated"] = save(os.path.join(data, "landcover_rotated.tif"), "GTiff",
                    [classes], ["COMPRESS=LZW"], gt=ROTATED)


def stack(name, how):
    """Three bands of bytes, the classes second, as a classifier writes
    them: GDAL calls three bands of bytes in a GeoTIFF red, green and blue."""
    path = save(os.path.join(data, name), "GTiff",
                [photo_bands()[0], classes, photo_bands()[2]],
                ["COMPRESS=LZW"])
    ds = gdal.Open(path, gdal.GA_Update)
    band = ds.GetRasterBand(2)
    if how == "names":
        for b, words in enumerate(("probability", "class", "entropy"), 1):
            ds.GetRasterBand(b).SetDescription(words)
    elif how == "categories":
        band.SetRasterCategoryNames(["none", "water", "crops", "forest",
                                     "urban"])
    else:
        rat = gdal.RasterAttributeTable()
        rat.CreateColumn("Value", gdal.GFT_Integer, gdal.GFU_MinMax)
        rat.CreateColumn("Class_Name", gdal.GFT_String, gdal.GFU_Name)
        rat.SetRowCount(4)
        for i, words in enumerate(("water", "crops", "forest", "urban")):
            rat.SetValueAsInt(i, 0, i + 1)
            rat.SetValueAsString(i, 1, words)
        band.SetDefaultRAT(rat)
    ds = None
    return path


K["stack_names"] = stack("stack_names.tif", "names")
K["stack_categories"] = stack("stack_categories.tif", "categories")
K["stack_rat"] = stack("stack_rat.tif", "rat")


def loaded(path):
    QgsProject.instance().removeAllMapLayers()
    layer = QgsRasterLayer(path, os.path.splitext(os.path.basename(path))[0])
    QgsProject.instance().addMapLayer(layer)
    return layer


def new_correction(key, reply, tag):
    """A new correction on the map K[key], every question answered with
    reply. What was asked, and whether the correction was made."""
    layer = loaded(K[key])
    folder = os.path.join(root, "fix_" + tag)
    panel = g["Panel"]()
    seen = {}

    def choose(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText("fix " + tag)
        d.raster.setCurrentIndex(d.raster.findData(layer.id()))
        d.fill_bands()
        d.band.setCurrentIndex(d.band.findData(1))
        d.folder.setText(folder)
        d.operator.setText("ann")
        d.refresh()
        seen["note"] = d.note.text()
        return 1

    def confirm(d):
        seen["codes"] = [r["value"].value() for r in d.rows]
        d.accept()
        return 1

    ANSWERS.clear()
    ANSWERS["OpenCorrection"] = choose
    ANSWERS["ConfirmClasses"] = confirm
    del BOXES[:]
    del ASKED[:]
    REPLY[0] = reply
    try:
        panel.new_correction_campaign()
    except Exception:
        traceback.print_exc()
        seen["raised"] = True
    seen["boxes"] = list(BOXES)
    seen["asked"] = list(ASKED)
    seen["made"] = panel.correction is not None
    seen["folder"] = os.path.exists(folder)
    seen["panel"] = panel
    seen["layer"] = layer
    return seen


def done(seen):
    panel = seen["panel"]
    try:
        panel.close_correction()
    except Exception:
        traceback.print_exc()
    panel.close()
    panel.deleteLater()
    QgsProject.instance().removeAllMapLayers()
    app.processEvents()


YES = QMB.StandardButton.Yes
CANCEL = QMB.StandardButton.Cancel


def asks_to_go_on(box):
    """Yes and Cancel, Cancel the default."""
    buttons, default = box[1], box[2]
    try:
        both = bool(buttons & YES) and bool(buttons & CANCEL)
    except TypeError:
        both = False
    return both and default == CANCEL


try:
    print()
    print("the compressions that lose values, and those that do not")
    lossy_codec = g.get("lossy_codec")
    check("rasters.lossy_codec exists", lossy_codec is not None)
    if lossy_codec is not None:
        want = {"tif": None, "png": None, "jpg": "JPEG", "tif_jpeg": "JPEG",
                "jp2_lossy": "JPEG 2000", "jp2_lossless": None,
                "webp_lossy": "WebP", "webp_lossless": None,
                "tif_webp": "WebP", "tif_webp_lossless": None,
                "colour_jpg": "JPEG", "colour_png": None, "rotated": None,
                "tif_lerc": "LERC", "tif_lerc_exact": None}
        for key, expected in want.items():
            got = lossy_codec(K[key])
            check("%s: %s" % (os.path.basename(K[key]),
                              expected or "nothing is lost"),
                  got == expected, got)
        check("a file that is not there names nothing",
              lossy_codec(os.path.join(data, "nothing.tif")) is None)

    print()
    print("a class map as a GeoTIFF: nothing to ask")
    s = new_correction("tif", CANCEL, "tif")
    check("no question", s["boxes"] == [], s["boxes"])
    check("the classes window, and the correction made",
          "ConfirmClasses" in s["asked"] and s["made"], s["asked"])
    check("the window says nothing about the map",
          "rotated" not in s["note"] and "stored as" not in s["note"]
          and "picture in colour" not in s["note"], s["note"])
    done(s)

    print()
    print("a class map saved as a JPEG")
    s = new_correction("jpg", CANCEL, "jpg_cancel")
    check("one question, that it is stored as JPEG",
          len(s["boxes"]) == 1 and "stored as JPEG" in s["boxes"][0][0],
          s["boxes"])
    check("it says the codes along the edges are no class",
          s["boxes"] and "no class" in s["boxes"][0][0], s["boxes"])
    check("Yes and Cancel, Cancel the default",
          s["boxes"] and asks_to_go_on(s["boxes"][0]), s["boxes"])
    check("Cancel makes nothing: no classes window, no folder",
          "ConfirmClasses" not in s["asked"] and not s["made"]
          and not s["folder"], (s["asked"], s["made"], s["folder"]))
    check("the window said it as soon as the map was picked",
          "stored as JPEG" in s["note"], s["note"])
    done(s)
    s = new_correction("jpg", YES, "jpg_yes")
    check("Yes goes on to the classes window, and the correction is made",
          "ConfirmClasses" in s["asked"] and s["made"],
          (s["asked"], s["boxes"]))
    done(s)

    for key, codec in (("tif_jpeg", "JPEG"), ("jp2_lossy", "JPEG 2000")):
        s = new_correction(key, CANCEL, key)
        check("%s asks first, as %s" % (os.path.basename(K[key]), codec),
              len(s["boxes"]) == 1 and ("stored as %s" % codec)
              in s["boxes"][0][0] and not s["made"], s["boxes"])
        done(s)
    s = new_correction("jp2_lossless", CANCEL, "jp2_lossless")
    check("a JPEG 2000 without loss is not asked about",
          s["boxes"] == [] and s["made"], s["boxes"])
    done(s)

    print()
    print("a class map exported as a picture in colour")
    s = new_correction("colour_png", CANCEL, "colour_png")
    check("a picture of four colours is asked about",
          len(s["boxes"]) == 1 and "picture in colour" in s["boxes"][0][0],
          s["boxes"])
    check("it says to convert it to a map of codes in one band",
          s["boxes"] and "map of one band with one code per class"
          in s["boxes"][0][0], s["boxes"])
    check("Yes and Cancel, Cancel the default",
          s["boxes"] and asks_to_go_on(s["boxes"][0]), s["boxes"])
    check("Cancel makes nothing", not s["made"] and not s["folder"]
          and "ConfirmClasses" not in s["asked"])
    check("the window said it as soon as the map was picked",
          "picture in colour" in s["note"], s["note"])
    done(s)

    s = new_correction("colour_jpg", CANCEL, "colour_jpg")
    check("a picture in colour saved as JPEG: one question, that says both",
          len(s["boxes"]) == 1 and "picture in colour" in s["boxes"][0][0]
          and "also stored as JPEG" in s["boxes"][0][0], s["boxes"])
    done(s)

    s = new_correction("photo", CANCEL, "photo")
    check("a photograph gets the question about colour, not the one about "
          "too many values", len(s["boxes"]) == 1
          and "picture in colour" in s["boxes"][0][0]
          and "different values and its style" not in s["boxes"][0][0],
          s["boxes"])
    done(s)
    s = new_correction("photo", YES, "photo_yes")
    check("Yes to it is not asked again about its values",
          len(s["boxes"]) == 1 and "ConfirmClasses" in s["asked"],
          (s["boxes"], s["asked"]))
    done(s)

    print()
    print("a stack of three bands of bytes is not a picture in colour")
    # GDAL reads them as red, green and blue, and the stacks of
    # test_correct_typical were asked about as pictures until a band that
    # says what it holds was taken to mean a stack
    colour_picture = g["colour_picture"]
    for key in ("stack_names", "stack_categories", "stack_rat"):
        check("%s is not taken for a picture" % os.path.basename(K[key]),
              not colour_picture(K[key]))
    check("a photograph still is", colour_picture(K["photo"]))
    check("and a class map exported as a picture still is",
          colour_picture(K["colour_png"]))

    print()
    print("a map on a rotated grid")
    s = new_correction("rotated", YES, "rotated")
    check("refused, with one message that says why",
          len(s["boxes"]) == 1 and "rotated pixel grid" in s["boxes"][0][0],
          s["boxes"])
    check("it says to warp it north-up with nearest neighbour",
          s["boxes"] and "north-up" in s["boxes"][0][0]
          and "nearest neighbour" in s["boxes"][0][0], s["boxes"])
    check("nothing is asked, nothing is made, no folder is written",
          "ConfirmClasses" not in s["asked"] and not s["made"]
          and not s["folder"], (s["asked"], s["made"], s["folder"]))
    check("the window said it as soon as the map was picked",
          "rotated pixel grid" in s["note"], s["note"])
    done(s)

    print()
    print("a correction whose working copy is on a rotated grid")
    s = new_correction("tif2", CANCEL, "to_rotate")
    made = s["made"]
    book = s["panel"].correction
    manifest = book.manifest_path if book is not None else None
    copy = book.working_path if book is not None else None
    done(s)
    check("a correction made on the north-up map", made and manifest)
    if made and manifest:
        ds = gdal.Open(copy, gdal.GA_Update)
        ds.SetGeoTransform(ROTATED)
        ds = None
        panel = g["Panel"]()
        del BOXES[:]
        reread = panel.read_correction(manifest)
        opened = panel.start_correction(reread) if reread else None
        check("it is not opened", opened is None
              and panel.correction is None, BOXES)
        check("and the message says why",
              any("rotated pixel grid" in b[0] and "not opened" in b[0]
                  for b in BOXES), BOXES)
        panel.close()
        panel.deleteLater()
        app.processEvents()
finally:
    QgsProject.instance().removeAllMapLayers()
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(_PROFILE, ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.stdout.flush()
os._exit(1 if fails else 0)
