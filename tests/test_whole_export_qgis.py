"""The whole raster comes out the way QGIS shows it, and Export on a campaign
with no coordinate system, both against the real QGIS classes.

The Whole export used to rebuild its pictures from the raw bands with a
stretch of its own: an RGB image came out in other colours than the screen
(QGIS draws eight bit RGB as it is, and the stored limits were applied all
the same), a paletted map came out as its indices stretched to grey, sixteen
bits with another stretch, the brightness, contrast and saturation of the
layer were not there, and what was transparent on the screen came out
opaque. Only QGIS itself can say what the screen shows, so each raster here
is drawn by a real map render, as the canvas draws it, and the export is
compared with that, pixel for pixel:

  RGB of eight bits, a paletted map, a grey map of sixteen bits, a picture
  with no georeferencing at all;
  the same RGB with brightness, contrast and saturation set on the layer;
  an RGBA image: its pictures get an alpha band, the alpha of the screen,
  and an area painted over the transparent part is the class colour at the
  opacity of the paint; as a JPEG, which holds no alpha, the transparent
  part is white.

And the Export window, on a campaign whose manifest names no system: the
"in longitude and latitude" box is off and greyed, KML cannot be chosen,
and what goes out asks for no reprojection.

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
    from qgis.core import (Qgis, QgsApplication, QgsMapRendererSequentialJob,
                           QgsMapSettings, QgsRasterLayer)
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor, QImage
    from qgis.PyQt.QtWidgets import QDialogButtonBox
    import numpy as np
    from osgeo import gdal, ogr, osr
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
g["STRIP_ROWS"] = 32        # small strips, so the loop runs over several

W, H = 90, 70
PX = 0.5
OX, OY = 500000.0, 4100000.0
CLASS = (235, 104, 52)
tmp = tempfile.mkdtemp(prefix="rl_whole_qgis_")
utm = osr.SpatialReference()
utm.ImportFromEPSG(32633)


def raster(name, bands, kind=gdal.GDT_Byte, table=None, alpha=False,
           georeferenced=True):
    """A GeoTIFF, or a PNG with nothing but its pixels, of these bands."""
    path = os.path.join(tmp, name)
    if georeferenced:
        options = ["PHOTOMETRIC=RGB", "ALPHA=YES"] if alpha else []
        ds = gdal.GetDriverByName("GTiff").Create(path, W, H, len(bands),
                                                  kind, options)
        ds.SetGeoTransform((OX, PX, 0.0, OY, 0.0, -PX))
        ds.SetProjection(utm.ExportToWkt())
    else:
        ds = gdal.GetDriverByName("MEM").Create("", W, H, len(bands), kind)
    if table is not None:
        # before the pixels: a GeoTIFF takes no colour table once written to
        ct = gdal.ColorTable()
        for value, rgba in table.items():
            ct.SetColorEntry(value, rgba)
        ds.GetRasterBand(1).SetRasterColorTable(ct)
        ds.GetRasterBand(1).SetRasterColorInterpretation(gdal.GCI_PaletteIndex)
    for i, b in enumerate(bands):
        ds.GetRasterBand(i + 1).WriteArray(b)
    if not georeferenced:
        gdal.GetDriverByName("PNG").CreateCopy(path, ds)
    ds = None
    return path


def package(name, georeferenced=True):
    """A campaign's GeoPackage holding one class 2 square, 20 by 20 pixels,
    whose top left corner is the pixel at row 10, column 10."""
    path = os.path.join(tmp, name)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    layer = ds.CreateLayer("polygons", utm if georeferenced else None,
                           ogr.wkbMultiPolygon, ["GEOMETRY_NAME=geom"])
    layer.CreateField(ogr.FieldDefn("class_code", ogr.OFTInteger))
    ox, oy, px = (OX, OY, PX) if georeferenced else (0.0, 0.0, 1.0)
    x0, y0, x1, y1 = ox + 10 * px, oy - 10 * px, ox + 30 * px, oy - 30 * px
    f = ogr.Feature(layer.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt(
        "MULTIPOLYGON(((%r %r,%r %r,%r %r,%r %r,%r %r)))"
        % (x0, y0, x1, y0, x1, y1, x0, y1, x0, y0)))
    f.SetField("class_code", 2)
    layer.CreateFeature(f)
    f = layer = ds = None
    return path


def screen(layer):
    """The layer as the canvas draws it, pixel for pixel, on nothing: four
    planes, red, green, blue and alpha, not premultiplied."""
    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setDestinationCrs(layer.crs())
    settings.setExtent(layer.extent())
    settings.setOutputSize(QSize(layer.width(), layer.height()))
    settings.setBackgroundColor(QColor(0, 0, 0, 0))
    settings.setOutputImageFormat(QImage.Format.Format_ARGB32)
    job = QgsMapRendererSequentialJob(settings)
    job.start()
    job.waitForFinished()
    image = job.renderedImage().convertToFormat(QImage.Format.Format_RGBA8888)
    bits = image.constBits()
    bits.setsize(image.bytesPerLine() * image.height())
    data = np.frombuffer(bits, np.uint8).reshape(image.height(),
                                                 image.bytesPerLine())
    data = data[:, :image.width() * 4].reshape(image.height(),
                                               image.width(), 4)
    return np.ascontiguousarray(data.transpose(2, 0, 1)).astype(int)


def export(layer, gpkg, kinds, driver="GTiff", extension=".tif",
           classes=None):
    """paint_whole, handed what the Whole button hands it, layer and all."""
    ds = gdal.Open(layer.source())
    bands = g["renderer_bands"](layer)
    limits = g["display_limits"](layer, bands) or [(0.0, 255.0)] * 3
    folder = os.path.join(tmp, "out_%s_%s" % (layer.name(), driver))
    os.makedirs(folder, exist_ok=True)
    outputs = [(k, os.path.join(folder, k + extension),
                "GTiff" if k == "mask" else driver) for k in kinds]
    recipe = {"ds": ds, "layer": layer, "scale": 1, "rgb": bands,
              "limits": limits, "alpha": 45, "colours": {2: CLASS},
              "outputs": outputs, "package": gpkg,
              "want_lines": False, "want_points": False, "want_boxes": False,
              "points_in_mask": False, "dot_px": 1}
    if classes is not None:
        recipe["classes"] = classes
    g["paint_whole"](recipe)
    ds = None
    out = {}
    for k, path, _ in outputs:
        f = gdal.Open(path)
        out[k] = f.ReadAsArray().astype(int)
        f = None
    return out


def same(written, shown, opaque):
    """How far the three bands written are from the screen where it is
    opaque, as (pixels that differ, largest difference)."""
    d = np.abs(written[:3] - shown[:3]).max(axis=0)[opaque]
    return int((d > 0).sum()), int(d.max()) if d.size else 0


rng = np.random.default_rng(3)
rgb = [rng.integers(30, 221, (H, W)).astype(np.uint8) for _ in range(3)]
square = np.zeros((H, W), bool)
square[10:30, 10:30] = True
gpkg = package("annotation.gpkg")

# ---------------------------------------------------------------- the colours
cases = [
    ("rgb", raster("rgb.tif", rgb), "eight bit RGB"),
    ("palette", raster("palette.tif",
                       [np.repeat(np.arange(W)[None] % 3, H, 0)
                        .astype(np.uint8)],
                       table={0: (230, 230, 40, 255), 1: (30, 200, 30, 255),
                              2: (200, 30, 30, 255)}), "a paletted map"),
    ("grey16", raster("grey16.tif",
                      [rng.integers(1000, 4000, (H, W)).astype(np.uint16)],
                      kind=gdal.GDT_UInt16), "a grey map of sixteen bits"),
]
for name, path, words in cases:
    print()
    print(words)
    lyr = QgsRasterLayer(path, name)
    check("QGIS opens it", lyr.isValid())
    shown = screen(lyr)
    out = export(lyr, gpkg, ["plain", "painted", "mask"])
    n, worst = same(out["plain"], shown, shown[3] == 255)
    check("the plain image is the screen, pixel for pixel", n == 0,
          "%d pixels differ, by up to %d" % (n, worst))
    check("with three bands, nothing being transparent",
          out["plain"].shape[0] == 3, out["plain"].shape)
    outside = ~square
    n, worst = same(out["painted"][:, outside].reshape(3, 1, -1),
                    shown[:, outside].reshape(4, 1, -1),
                    np.ones((1, int(outside.sum())), bool))
    check("so is the painted one, away from the paint", n == 0,
          "%d pixels differ, by up to %d" % (n, worst))
    check("and the mask holds the square",
          int((out["mask"] == 2).sum()) == 400
          and bool((out["mask"][square] == 2).all()),
          int((out["mask"] == 2).sum()))

print()
print("a picture with no georeferencing at all")
bare = raster("bare.png", rgb, georeferenced=False)
lyr = QgsRasterLayer(bare, "bare")
check("QGIS opens it", lyr.isValid())
shown = screen(lyr)
out = export(lyr, package("bare.gpkg", georeferenced=False),
             ["plain", "mask"])
n, worst = same(out["plain"], shown, shown[3] == 255)
check("the plain image is the screen, pixel for pixel", n == 0,
      "%d pixels differ, by up to %d" % (n, worst))
check("and the mask holds the square drawn on it",
      bool((out["mask"][square] == 2).all())
      and int((out["mask"] == 2).sum()) == 400,
      int((out["mask"] == 2).sum()))

print()
print("brightness, contrast and saturation set on the layer")
lyr = QgsRasterLayer(cases[0][1], "tuned")
lyr.brightnessFilter().setBrightness(40)
lyr.brightnessFilter().setContrast(25)
lyr.hueSaturationFilter().setSaturation(-60)
shown = screen(lyr)
plain_rgb = screen(QgsRasterLayer(cases[0][1], "untuned"))
check("they do change what the screen shows",
      bool(np.abs(shown[:3] - plain_rgb[:3]).max() > 20))
out = export(lyr, gpkg, ["plain"])
n, worst = same(out["plain"], shown, shown[3] == 255)
check("the plain image has them, as the screen does", n == 0,
      "%d pixels differ, by up to %d" % (n, worst))

print()
print("an image with an alpha band")
cut = np.full((H, W), 255, np.uint8)
cut[:, :25] = 0                       # transparent down the left
cut[:, 25:40] = 128                   # and half so beside it
see = raster("rgba.tif", rgb + [cut], alpha=True)
lyr = QgsRasterLayer(see, "rgba")
shown = screen(lyr)
out = export(lyr, gpkg, ["plain", "painted"])
check("the plain image gets an alpha band", out["plain"].shape[0] == 4,
      out["plain"].shape)
if out["plain"].shape[0] == 4:
    gap = np.abs(out["plain"][3] - shown[3])
    check("and it is the alpha of the screen", int(gap.max()) <= 1,
          int(gap.max()))
n, worst = same(out["plain"], shown, shown[3] == 255)
check("where the screen is opaque the colours are its own", n == 0,
      "%d pixels differ, by up to %d" % (n, worst))
half = shown[3] == 128
n, worst = same(out["plain"], shown, half)
check("and where it is half transparent nearly so", worst <= 2,
      "%d pixels differ, by up to %d" % (n, worst))
if out["painted"].shape[0] == 4:
    on_nothing = square & (cut == 0)
    paint = out["painted"][:, on_nothing]
    check("the paint over the transparent part is the class colour",
          bool((np.abs(paint[:3].T - np.array(CLASS)) <= 1).all()),
          paint[:3, :3].T.tolist())
    check("at the opacity of the paint", bool((np.abs(paint[3] - 115) <= 1).all()),
          sorted(set(paint[3].tolist())))
    check("and the transparent part away from it stays transparent",
          bool((out["painted"][3][(cut == 0) & ~square] == 0).all()))
else:
    check("the painted image gets an alpha band too", False,
          out["painted"].shape)
out = export(lyr, gpkg, ["plain"], driver="JPEG", extension=".jpg")
clear = (cut == 0)
clear[:, 22:] = False                 # off the edge, where JPEG blurs
check("a JPEG, which holds no alpha, has white where the screen has nothing",
      out["plain"].shape[0] == 3
      and float(out["plain"][:, clear].mean()) > 245,
      float(out["plain"][:, clear].mean()))

# ---------------------------------------------------------- the legend
print()
print("the mask opens in its classes")
LEGEND = [{"code": 2, "name": "crust", "colour": "#eb6834"},
          {"code": 3, "name": "water", "colour": "#2f6f9f"}]
lyr = QgsRasterLayer(cases[0][1], "legend")
bare_out = export(lyr, gpkg, ["mask"])
bare_mask = bare_out["mask"]
out = export(lyr, gpkg, ["mask"], classes=LEGEND)
mask_path = os.path.join(tmp, "out_legend_GTiff", "mask.tif")
check("the codes are the same with and without the legend",
      np.array_equal(out["mask"], bare_mask))
shown = QgsRasterLayer(mask_path, "mask")
check("QGIS opens the mask", shown.isValid())
check("as a paletted map, not as grey", shown.renderer().type() == "paletted",
      shown.renderer().type())
named = g["style_classes"](shown, 1) or []
check("with the name and colour of each class, which is what Cutouts, "
      "its sampler note and its STAC items list",
      [(c["code"], c["name"], c["colour"]) for c in named]
      == [(2, "crust", "#eb6834"), (3, "water", "#2f6f9f")], named)
# without the .qml, the colour table and the names inside and beside the
# file are what a program other than this one has
os.remove(os.path.splitext(mask_path)[0] + ".qml")
alone = QgsRasterLayer(mask_path, "mask alone")
check("with the .qml gone it still opens paletted, from the colour table",
      alone.renderer().type() == "paletted", alone.renderer().type())
alone_named = {c["code"]: c for c in g["style_classes"](alone, 1) or []}
check("in the colours of the classes", alone_named.get(2, {}).get(
    "colour") == "#eb6834" and alone_named.get(3, {}).get(
        "colour") == "#2f6f9f", alone_named)
check("and with their names", alone_named.get(2, {}).get(
    "name") == "crust" and alone_named.get(3, {}).get(
        "name") == "water", alone_named)
shown = alone = lyr = None
app.processEvents()

# ---------------------------------------------------- Export, with no system
print()
print("Export on a campaign with no coordinate system")


class Campaign(object):
    def __init__(self, crs):
        self.folder = os.path.join(tmp, "campaign")
        self.package_path = package("export_%s.gpkg" % (crs or "none"),
                                    georeferenced=bool(crs))
        self.stem = "camp"
        self.data = {"grid": {"crs": crs}, "classes": []}


def window(crs):
    w = g["ExportVectors"](None, Campaign(crs))
    ok = w.findChild(QDialogButtonBox).button(
        QDialogButtonBox.StandardButton.Ok)
    return w, ok


def pick(w, driver):
    for i, row in enumerate(g["FORMATS"]):
        if row[1] == driver:
            w.shape.setCurrentIndex(i)
            return


w, ok = window("")
pick(w, "GeoJSON")
check("the degrees box is off", not w.degrees.isChecked())
check("and cannot be ticked", not w.degrees.isEnabled())
check("GeoJSON can still be written", ok.isEnabled())
r = w.result()
check("and asks for no reprojection", r["crs"] is None, r["crs"])
check("saying there is no system", r.get("system") is False, r.get("system"))
check("the window says the coordinates are not degrees",
      "not in longitude and latitude" in w.note.text(), w.note.text())
pick(w, "KML")
check("KML cannot be written", not ok.isEnabled())
check("and the window says why", "KML" in w.note.text()
      and "coordinate system" in w.note.text(), w.note.text())
pick(w, "ESRI Shapefile")
w.degrees.setChecked(True)
check("a shapefile asks for no reprojection either",
      w.result()["crs"] is None, w.result()["crs"])
w.deleteLater()

w, ok = window("EPSG:32633")
pick(w, "KML")
check("with a system KML can be written", ok.isEnabled())
check("in degrees", w.result()["crs"] == "EPSG:4326", w.result()["crs"])
check("and the degrees box says so", w.degrees.isChecked())
w.deleteLater()

# the layers hold their files open, and Windows keeps an open file
lyr = w = ok = None
app.processEvents()
shutil.rmtree(tmp, ignore_errors=True)
finish()
