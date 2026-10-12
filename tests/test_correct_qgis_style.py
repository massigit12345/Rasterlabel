"""The corrected map opens in a real QGIS the way the original does.

The working copy of a correction used to open in QGIS as a picture: one band
more than the map, no style, and QGIS put the class on red, the probability
on green and the entropy on blue. The fakes the other suites use take any
style and say yes, so only QGIS itself can tell whether the .qml written
beside the copy is one it reads, and reads on its own, as the default style
of the file, the moment the file is opened as a layer.

So this suite builds a thematic map of five bands with a .qml of its own, as
a model leaves one, makes its working copy with the program's own functions,
and opens it with QgsRasterLayer, as Add Raster Layer does:

  the original opens paletted, from its .qml, which is the bar to clear;
  the copy opens paletted on its class band, with the classes of the
  correction, code, colour and name, at the opacity of the original's .qml;
  a copy whose map brought no .qml opens paletted too, solid;
  the classes changed, the copy opens with the new ones;
  an opacity the user set on the copy and saved with Save as Default stays
  when the classes change again, which only the real QGIS can write;
  a copy of the earlier build, six bands with "corrected" last, opens as a
  picture, multiband colour; brought up to date, it opens paletted;
  a class band that is not the first is styled on that band;
  a map of one band keeps its colour table inside the file, and opens
  paletted even without its .qml.

Needs QGIS itself, its Python and its classes, and GDAL, which comes with
it. tests/run.py skips it where QGIS is missing and, with RL_REQUIRE_QGIS=1,
fails it instead.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.environ.get("RL_ROOT") or os.path.dirname(_HERE)
SRC = os.environ.get("RL_SRC", os.path.join(_ROOT, "dist", "rasterlabel.py"))

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail != "" and not cond else ""))
    if not cond:
        fails.append(name)


def finish():
    print()
    print("FAILED: %d" % len(fails) if fails else "all pass")
    for f in fails:
        print("   " + f)
    sys.stdout.flush()
    # os._exit: the QGIS application object is not torn down, and a teardown
    # that crashes would turn a passing run into a failed one.
    os._exit(1 if fails else 0)


try:
    from qgis.core import Qgis, QgsApplication, QgsMapLayer, QgsRasterLayer
    import numpy as np
    from osgeo import gdal, osr
except ImportError as e:
    print("QGIS is not importable here: %s" % e)
    sys.exit(1)

gdal.UseExceptions()
app = QgsApplication([], False)
app.initQgis()
print("QGIS %s, GDAL %s" % (Qgis.QGIS_VERSION, gdal.__version__))

# The shipped file, run as it is shipped, minus the line that puts the panel
# up: its functions are the ones under test.
code = open(SRC, encoding="utf-8").read().replace("\nstart()\n", "\n")
g = {"__name__": "rasterlabel", "__file__": SRC}
exec(compile(code, SRC, "exec"), g)

NX, NY = 120, 90
GT = (13.597, 5.6448e-07, 0.0, 37.377, 0.0, -4.50488e-07)
srs = osr.SpatialReference()
srs.ImportFromEPSG(4326)
CLASSES = [{"code": 1, "name": "fango fresco", "colour": "#2b3a4a"},
           {"code": 2, "name": "fango secco", "colour": "#e8e2d5"},
           {"code": 3, "name": "suolo", "colour": "#d9a441"},
           {"code": 4, "name": "vegetazione", "colour": "#2f7b5f"}]
rng = np.random.default_rng(5)


def write(path, n=5, class_band=1, flag=False):
    ds = gdal.GetDriverByName("GTiff").Create(
        path, NX, NY, n + (1 if flag else 0), gdal.GDT_Byte,
        ["COMPRESS=LZW", "TILED=YES"])
    ds.SetGeoTransform(GT)
    ds.SetProjection(srs.ExportToWkt())
    for b in range(1, n + 1):
        a = (rng.integers(1, 5, (NY, NX)) if b == class_band
             else rng.integers(1, 256, (NY, NX))).astype(np.uint8)
        ds.GetRasterBand(b).WriteArray(a)
        ds.GetRasterBand(b).SetNoDataValue(0)
        ds.GetRasterBand(b).SetDescription(
            "classe" if b == class_band else "band %d" % b)
    if flag:
        ds.GetRasterBand(n + 1).WriteArray(
            (rng.random((NY, NX)) < 0.1).astype(np.uint8))
        ds.GetRasterBand(n + 1).SetDescription("corrected")
    ds = None


def source_qml(path, opacity):
    with open(os.path.splitext(path)[0] + ".qml", "w", encoding="utf-8") as f:
        f.write('<qgis><pipe><rasterrenderer type="paletted" band="1" '
                'opacity="%s">\n<colorPalette>\n' % opacity
                + "".join('<paletteEntry value="%d" color="%s" label="%s"/>\n'
                          % (c["code"], c["colour"].upper(), c["name"])
                          for c in CLASSES)
                + "</colorPalette>\n</rasterrenderer></pipe></qgis>")


def opened(path):
    """(renderer type, band, [(code, colour, name)], opacity) of the layer
    QGIS makes of this file, its default style and all."""
    layer = QgsRasterLayer(path, "probe")
    if not layer.isValid():
        return ("invalid", None, None, None)
    r = layer.renderer()
    kind = r.type()
    band = None
    classes = None
    if kind == "paletted":
        band = (r.inputBand() if hasattr(r, "inputBand") else r.band())
        classes = [(int(c.value), c.color.name(), c.label) for c in r.classes()]
    out = (kind, band, classes, round(r.opacity(), 3))
    del layer
    return out


def want(classes):
    return [(c["code"], c["colour"].lower(), c["name"]) for c in classes]


root = tempfile.mkdtemp(prefix="rl_qgis_style_")
try:
    print()
    print("the original, with its own .qml")
    original = os.path.join(root, "output", "72_mappa_fold.tif")
    os.makedirs(os.path.dirname(original))
    write(original)
    source_qml(original, "0.7")
    kind, band, classes, opacity = opened(original)
    check("opens paletted on band 1, from its .qml",
          (kind, band) == ("paletted", 1), (kind, band))

    print()
    print("its working copy, made by the program")
    folder = os.path.join(root, "correction_1")
    os.makedirs(folder)
    copy = os.path.join(folder, "72_mappa_fold_corrected.tif")
    g["build_copy"](original, copy, [], band_no=1)
    g["build_changes"](copy, g["changes_of"](copy))
    kind, band, classes, opacity = opened(copy)
    check("with no style yet, QGIS shows it as the picture it is not",
          kind == "multibandcolor", kind)
    g["dress_copy"](copy, 1, CLASSES, original)
    kind, band, classes, opacity = opened(copy)
    check("with its .qml it opens paletted, on band 1",
          (kind, band) == ("paletted", 1), (kind, band))
    check("with the classes of the correction: code, colour and name",
          classes == want(CLASSES), classes)
    check("at the opacity of the original's .qml", opacity == 0.7, opacity)
    ds = gdal.Open(copy)
    check("five bands, as the original", ds.RasterCount == 5, ds.RasterCount)
    ct = ds.GetRasterBand(1).GetColorTable()
    check("and a colour table GDAL reads back",
          ct is not None and ct.GetColorEntry(3)[:3] == (217, 164, 65),
          ct and ct.GetColorEntry(3))
    ds = None

    print()
    print("the classes change, and the copy opens with the new ones")
    changed = [dict(c) for c in CLASSES] + [
        {"code": 5, "name": "class 5", "colour": "#008300"}]
    changed[3]["colour"] = "#10067b"
    g["dress_copy"](copy, 1, changed, original)
    kind, band, classes, opacity = opened(copy)
    check("the added class and the new colour", classes == want(changed),
          classes)

    print()
    print("a style the user saves as default in QGIS stays")
    # Layer Properties, opacity 42 %, Style > Save as Default: QGIS writes
    # the copy's own .qml. It used to be rewritten from the original's .qml
    # at the next open, save, close or class change, back to 70 %.
    layer = QgsRasterLayer(copy, "mine")
    layer.renderer().setOpacity(0.42)
    try:
        saved = layer.saveDefaultStyle(
            QgsMapLayer.StyleCategory.AllStyleCategories)
    except TypeError:
        saved = layer.saveDefaultStyle()
    del layer
    kind, band, classes, opacity = opened(copy)
    check("QGIS saved it as the default style of the copy",
          opacity == 0.42, (saved, opacity))
    again = [dict(c) for c in changed] + [
        {"code": 6, "name": "class 6", "colour": "#aa00aa"}]
    g["dress_copy"](copy, 1, again, original)
    kind, band, classes, opacity = opened(copy)
    check("the classes change and QGIS opens it at the user's opacity",
          (kind, band, opacity) == ("paletted", 1, 0.42), (kind, opacity))
    check("with the new classes", classes == want(again), classes)

    print()
    print("a map that brought no .qml")
    bare = os.path.join(root, "bare", "bare.tif")
    os.makedirs(os.path.dirname(bare))
    write(bare)
    bare_copy = os.path.join(root, "bare", "c", "bare_corrected.tif")
    os.makedirs(os.path.dirname(bare_copy))
    g["build_copy"](bare, bare_copy, [], band_no=1)
    g["dress_copy"](bare_copy, 1, CLASSES, bare)
    kind, band, classes, opacity = opened(bare_copy)
    check("its copy opens paletted all the same, solid",
          (kind, band, classes, opacity) == ("paletted", 1, want(CLASSES), 1.0),
          (kind, band, classes, opacity))

    print()
    print("a copy of the earlier build, six bands")
    old = os.path.join(root, "old", "72_mappa_fold_corrected.tif")
    os.makedirs(os.path.dirname(old))
    write(old, flag=True)
    kind, band, classes, opacity = opened(old)
    check("opens as a picture of class, probability and entropy",
          kind == "multibandcolor", kind)
    done = g["bring_up_to_date"](old, 1, {"band": 1})
    check("brought up to date, its band moves out",
          done and done["bands"] == 5 and os.path.exists(g["changes_of"](old)),
          done)
    g["dress_copy"](old, 1, CLASSES, original)
    kind, band, classes, opacity = opened(old)
    check("and it opens paletted, with its classes",
          (kind, band, classes) == ("paletted", 1, want(CLASSES)),
          (kind, band, classes))

    print()
    print("a class band that is not the first")
    second = os.path.join(root, "second", "second.tif")
    os.makedirs(os.path.dirname(second))
    write(second, n=3, class_band=2)
    second_copy = os.path.join(root, "second", "c", "second_corrected.tif")
    os.makedirs(os.path.dirname(second_copy))
    g["build_copy"](second, second_copy, [], band_no=2)
    g["dress_copy"](second_copy, 2, CLASSES, second)
    kind, band, classes, opacity = opened(second_copy)
    check("is styled on its own band",
          (kind, band, classes) == ("paletted", 2, want(CLASSES)),
          (kind, band, classes))

    print()
    print("a map of one band")
    single = os.path.join(root, "single", "single.tif")
    os.makedirs(os.path.dirname(single))
    write(single, n=1)
    single_copy = os.path.join(root, "single", "c", "single_corrected.tif")
    os.makedirs(os.path.dirname(single_copy))
    g["build_copy"](single, single_copy, [], band_no=1)
    g["dress_copy"](single_copy, 1, CLASSES, single)
    aux = single_copy + ".aux.xml"
    if os.path.exists(aux):
        with open(aux, encoding="utf-8") as f:
            aux = f.read()
    else:
        aux = ""
    check("keeps its colour table inside the file, not in an .aux.xml",
          "<ColorTable>" not in aux, aux)
    os.remove(g["style_of"](single_copy))
    kind, band, classes, opacity = opened(single_copy)
    check("and opens paletted from it even without the .qml",
          kind == "paletted" and band == 1
          and [c for c in classes if c[0] in (1, 2, 3, 4)]
          == [(c[0], c[1], c[2]) for c in want(CLASSES)],
          (kind, band, classes))
finally:
    shutil.rmtree(root, ignore_errors=True)

finish()
