"""Cutouts of a map of classes that has a nodata, and of a project that holds a
raster no file stands behind. Real files out, read back.

Each of these stopped or spoiled a cutout:

  a map of classes stored as Int16 or Float32 with a nodata of -9999 aborted
  every cutout whose window held a nodata pixel or ran past the edge of the
  map, with "list index out of range", because the coloured picture asked for
  the colour of class -9999;
  a Float32 map of classes 1 and 2 with the nodata -3.4e38 that Raster
  Calculator and SAGA write came out as Int32, with the smallest 32 bit number
  where the nodata was, and no nodata declared;
  a web basemap in the project (a valid layer, no file) stopped Cutouts, and
  Whole raster, with a RuntimeError out of gdal.Open: QGIS switches GDAL
  exceptions on, and the code expected a None.

Needs the GDAL Python bindings: the rasters and the PNGs are real. QGIS is
faked, see correctkit.py. GDAL exceptions are on, as they are in QGIS.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                                 # noqa: E402
from osgeo import gdal, osr                                        # noqa: E402
import correctkit as K                                             # noqa: E402

gdal.UseExceptions()
g, check = K.g, K.check

root = tempfile.mkdtemp(prefix="rl_cutouts_nodata_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
data = os.path.join(root, "data")
os.makedirs(data)
X0, Y0 = 500000.0, 4100000.0
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)
UTM = srs.ExportToWkt()
WEB = ("type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png"
       "&zmax=19&zmin=0")


def write(name, array, gt, gtype, nodata=None):
    path = os.path.join(data, name)
    h, w = array.shape
    ds = gdal.GetDriverByName("GTiff").Create(path, w, h, 1, gtype)
    ds.SetGeoTransform(gt)
    ds.SetProjection(UTM)
    if nodata is not None:
        ds.GetRasterBand(1).SetNoDataValue(nodata)
    ds.GetRasterBand(1).WriteArray(array)
    ds = None
    return path


class Layer(K.Layer):
    def crs(self): return K.Crs()


class WebLayer(K.Layer):
    """What QGIS holds for an OpenStreetMap tile layer: valid, from the wms
    provider, and a source that is no path."""
    def __init__(self, name):
        super().__init__(WEB, name)
    def dataProvider(self):
        provider = K.Provider(self)
        provider.name = lambda: "wms"
        provider.bandCount = lambda: 3
        provider.sourceHasNoDataValue = lambda b: False
        return provider
    def _gt(self): return (X0 - 1000.0, 1.0, 0, Y0 + 1000.0, 0, -1.0)
    def width(self): return 4000
    def height(self): return 4000
    def crs(self): return K.Crs()


class Canvas(object):
    def extent(self): return K.Dummy()
    def mapSettings(self):
        m = K.Dummy()
        m.destinationCrs = lambda: K.Crs()
        return m
    def __getattr__(self, n): return lambda *a, **k: None


g["canvas"] = lambda: Canvas()


def paletted(codes):
    colours = ["#e6194b", "#3cb44b", "#0082c8", "#ffe119", "#911eb4"]
    return K.Paletted(None, 1, [K.Paletted.Class(c, colours[i % 5], "c%d" % c)
                                for i, c in enumerate(codes)])


def open_cutouts(folder, layers, png=True):
    K.LOADED.clear()
    K.TREE.clear()
    for layer in layers:
        K.add_layer(layer)
    panel = g["Panel"]()
    panel.toggle_module(3)
    cut = panel.section
    if cut is None:
        print("Cutouts did not open:", K.BOXES[-3:], K.SAID[-3:])
    cut.folder_box.setText(folder)
    cut.folder_changed()
    for box in (cut.common, cut.same_size, cut.stac):
        box.setChecked(True)
    cut.png.setChecked(png)
    want = [layer.id() for layer in layers]
    cut.sources.sort(key=lambda s: want.index(s["id"]))
    return panel, cut


def cut_at(cut, rect):
    try:
        return cut.export(rect, nominal=None)
    except Exception as err:
        print("      [the cutout raised %s: %s]" % (type(err).__name__, err))
        return False


def read(path):
    ds = gdal.Open(path)
    band = ds.GetRasterBand(1)
    out = (ds.ReadAsArray(), gdal.GetDataTypeName(band.DataType),
           band.GetNoDataValue())
    ds = None
    return out


# A window inside the map that holds a hole of nodata, and one that runs past
# the edge of the map into a larger layer beside it: both are nodata.
INSIDE = K.Rect(X0, Y0 - 25.0, X0 + 25.0, Y0)
PAST = K.Rect(X0 + 60.0, Y0 - 120.0, X0 + 120.0, Y0 - 60.0)
big = write("big.tif", np.full((200, 200), 1, np.uint8),
            (X0, 1.0, 0, Y0, 0, -1.0), gdal.GDT_Byte)


def expected(values, hole, nodata):
    """The cutout of INSIDE: class 1 with the hole, rows and columns 5 to 14."""
    want = np.full((25, 25), 1)
    want[5:15, 5:15] = nodata
    return np.array_equal(values, want)


def expected_past(values, nodata):
    """The cutout of PAST: columns 60 to 99 of the map are class 2, and
    rows 0 to 79; what lies beyond is nodata."""
    want = np.full((60, 60), nodata)
    want[:20, :40] = 2
    return np.array_equal(values, want)


try:
    print("a map of classes with a nodata of -9999")
    codes = np.full((80, 100), 1, np.int16)
    codes[:, 50:] = 2
    codes[5:15, 5:15] = -9999
    path = write("nodata_i16.tif", codes, (X0, 1.0, 0, Y0, 0, -1.0),
                 gdal.GDT_Int16, -9999)
    for png in (True, False):
        out = os.path.join(root, "i16_png" if png else "i16")
        panel, cut = open_cutouts(out, [Layer(path, "map", paletted([1, 2]))],
                                  png)
        K.BOXES[:] = []
        done = cut_at(cut, INSIDE)
        check("is cut%s" % (", with its coloured picture" if png else ""),
              done, K.BOXES[-2:])
        tif = os.path.join(out, "cut_0001_map_classes.tif")
        check("the file is there", os.path.exists(tif))
        if os.path.exists(tif):
            got, kind, nodata = read(tif)
            check("in the type the map holds", kind == "Int16", kind)
            check("its nodata is declared, the map's own", nodata == -9999,
                  nodata)
            check("the classes are the map's, the hole is -9999",
                  expected(got, None, -9999), got[::3, ::3])
        if png:
            picture = os.path.join(out, "cut_0001_map_classes.png")
            check("and the picture is there", os.path.exists(picture))
            if os.path.exists(picture):
                pic = gdal.Open(picture)
                alpha = pic.GetRasterBand(pic.RasterCount).ReadAsArray()
                pic = None
                check("with the hole see-through, the classes opaque",
                      (alpha[5:15, 5:15] == 0).all()
                      and alpha[:5].all() and alpha[15:].all(), alpha.shape)
        panel.close_module()
    out = os.path.join(root, "i16_edge")
    # a file of its own: a folder is remembered by the layers it was cut from
    again = write("nodata_i16_edge.tif", codes, (X0, 1.0, 0, Y0, 0, -1.0),
                  gdal.GDT_Int16, -9999)
    panel, cut = open_cutouts(out, [Layer(big, "big", paletted([1])),
                                    Layer(again, "map", paletted([1, 2]))])
    K.BOXES[:] = []
    done = cut_at(cut, PAST)
    check("a window past the edge of the map is cut", done, K.BOXES[-2:])
    tif = os.path.join(out, "cut_0001_map_classes.tif")
    if os.path.exists(tif):
        got, kind, nodata = read(tif)
        check("with -9999 where the map ends", expected_past(got, -9999),
              got[::6, ::6])
    else:
        check("the file is there", False)
    panel.close_module()

    print()
    print("a Float32 map of classes with the nodata -3.4e38")
    FLT_NODATA = -3.4028234663852886e+38
    floats = np.full((80, 100), 1, np.float32)
    floats[:, 50:] = 2
    floats[5:15, 5:15] = FLT_NODATA
    path = write("nodata_f32.tif", floats, (X0, 1.0, 0, Y0, 0, -1.0),
                 gdal.GDT_Float32, FLT_NODATA)
    for png in (False, True):
        out = os.path.join(root, "f32_png" if png else "f32")
        panel, cut = open_cutouts(out, [Layer(path, "map", paletted([1, 2]))],
                                  png)
        K.BOXES[:] = []
        done = cut_at(cut, INSIDE)
        check("is cut%s" % (", with its coloured picture" if png else ""),
              done, K.BOXES[-2:])
        tif = os.path.join(out, "cut_0001_map_classes.tif")
        if os.path.exists(tif):
            got, kind, nodata = read(tif)
            check("in a byte: every value it holds fits in one", kind == "Byte",
                  kind)
            check("with a nodata declared, not a class", nodata == 255,
                  nodata)
            check("the hole is the nodata, the classes the map's",
                  nodata is not None and expected(got, None, nodata),
                  got[::3, ::3])
        else:
            check("the file is there", False)
        panel.close_module()
    out = os.path.join(root, "f32_edge")
    again = write("nodata_f32_edge.tif", floats, (X0, 1.0, 0, Y0, 0, -1.0),
                  gdal.GDT_Float32, FLT_NODATA)
    panel, cut = open_cutouts(out, [Layer(big, "big", paletted([1])),
                                    Layer(again, "map", paletted([1, 2]))])
    K.BOXES[:] = []
    done = cut_at(cut, PAST)
    check("a window past the edge of the map is cut", done, K.BOXES[-2:])
    tif = os.path.join(out, "cut_0001_map_classes.tif")
    if os.path.exists(tif):
        got, kind, nodata = read(tif)
        check("as a byte with the nodata where the map ends",
              kind == "Byte" and nodata == 255 and expected_past(got, 255),
              (kind, nodata, np.unique(got)))
    else:
        check("the file is there", False)
    panel.close_module()

    print()
    print("a web basemap in the project, with GDAL exceptions on")
    ground = np.full((80, 100), 1, np.uint8)
    ground[:, 50:] = 2
    path = write("plain.tif", ground, (X0, 1.0, 0, Y0, 0, -1.0), gdal.GDT_Byte)
    out = os.path.join(root, "web")
    panel, cut = open_cutouts(out, [Layer(path, "map", paletted([1, 2])),
                                    WebLayer("OpenStreetMap")])
    check("the basemap is a source like any visible layer",
          [s["tag"] for s in cut.sources].count("OpenStreetMap") == 1,
          [s["tag"] for s in cut.sources])
    K.BOXES[:] = []
    done = cut_at(cut, K.Rect(X0 + 10.0, Y0 - 30.0, X0 + 30.0, Y0 - 10.0))
    check("the cutout is made all the same", done, K.BOXES[-2:])
    check("the map is cut", os.path.exists(
        os.path.join(out, "cut_0001_map_classes.tif")))
    check("and the basemap is said to be left out, as what it is",
          "web or database" in cut.skipped.get("OpenStreetMap", ""),
          cut.skipped)
    check("no file of it is written", not [f for f in os.listdir(out)
                                           if "OpenStreetMap" in f],
          os.listdir(out))
    panel.close_module()

    print()
    print("opening a layer that is no file, in every place that does")
    check("open_raster answers None for it, where gdal.Open raises",
          g["open_raster"](WEB) is None)
    check("and for a path that is not there", g["open_raster"](
        os.path.join(data, "nowhere.tif")) is None)
    check("and opens a raster that is", g["open_raster"](path) is not None)
finally:
    shutil.rmtree(g.get("long_path", str)(root), ignore_errors=True)

sys.exit(K.finish())
