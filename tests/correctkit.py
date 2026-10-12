"""The panel with no campaign open, Correct and Cutouts in it, and QGIS faked.

The suites of Correct before this one all began with an annotation campaign
already on the panel, because Correct could not be opened without one. That
is exactly what changed, so these begin from an empty panel and go through the
doors a user goes through: the Correct button, the window that asks which
correction, the window that shows the classes, the brush, Close, and the
Correct button again.

What is real: the whole program, read from the built single file, its
manifests and its folders on disk, operations.csv, the log, the dialogs as
widgets. What is faked: QGIS, and the raster files. A raster here is a numpy
array kept in DISK under its path, with an empty file of the same name on disk
so that os.path.exists() answers as it would. The program's build_copy() is
replaced by one that copies the bands, build_changes() by one that puts the
record of changed pixels beside the copy, and strip_flag_band() by one that
moves the "corrected" band of a copy of an earlier build out to that record;
test_correct_saves and test_correct_thematic run the real ones against real
GDAL.

With RL_KIT_REAL_GDAL set in the environment before it is imported, the
rasters are real files read and written by the GDAL bindings instead, and
build_copy() is the program's own: test_cutouts_free cuts real GeoTIFFs.

A dialog is answered by whatever the suite put in ANSWERS under its class
name: a function given the dialog, returning what exec() would. A dialog with
no answer waiting is a failure, recorded in UNEXPECTED, and is cancelled.
"""
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os, sys, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from qtbinding import PyQt, QtCore, QtGui, QtWidgets

qgis = types.ModuleType("qgis"); qgis.PyQt = PyQt
sys.modules["qgis"] = qgis
sys.modules["qgis.PyQt"] = PyQt
utils = types.ModuleType("qgis.utils")
utils.iface = None
qgis.utils = utils
sys.modules["qgis.utils"] = utils
sys.modules["qgis.PyQt.QtCore"] = QtCore
sys.modules["qgis.PyQt.QtGui"] = QtGui
sys.modules["qgis.PyQt.QtWidgets"] = QtWidgets


class Sig:
    def connect(self, *a, **k): pass
    def disconnect(self, *a, **k): pass


class Crs:
    def __init__(self, a="EPSG:32633"): self._a = a
    def authid(self): return self._a
    def isValid(self): return bool(self._a)
    def isGeographic(self): return False
    def createFromWkt(self, w):
        self._a = "EPSG:32633" if w else ""
        return bool(w)
    def toWkt(self, *a): return "PROJCS[\"fake\"]" if self._a else ""
    def mapUnits(self): return None
    def description(self): return self._a
    def __eq__(self, o): return getattr(o, "_a", None) == self._a
    def __ne__(self, o): return not self.__eq__(o)


LOADED = {}
TREE = {}            # layer id -> ticked in the Layers panel


class Node:
    def __init__(self, lid): self.lid = lid
    def isVisible(self): return TREE.get(self.lid, True)
    def setItemVisibilityChecked(self, on): TREE[self.lid] = bool(on)


class Root:
    def findLayer(self, lid): return Node(lid) if lid in LOADED else None
    def findGroup(self, name): return None
    def insertGroup(self, i, name): return Group()
    def removeChildNode(self, n): pass


class Group:
    def addLayer(self, l): pass
    def findLayer(self, i): return None


class Project:
    _one = None
    layersAdded = Sig(); layersRemoved = Sig()
    @classmethod
    def instance(cls):
        if cls._one is None: cls._one = cls()
        return cls._one
    def mapLayers(self): return dict(LOADED)
    def mapLayer(self, i): return LOADED.get(i)
    def layerTreeRoot(self): return Root()
    def transformContext(self): return None
    def ellipsoid(self): return "WGS84"
    def homePath(self): return HOME[0]
    def setAvoidIntersectionsLayers(self, x): pass
    def setTopologicalEditing(self, x): pass
    def addMapLayer(self, l, *a, **k): LOADED[l.id()] = l
    def removeMapLayers(self, ids):
        for i in ids:
            LOADED.pop(i, None)


HOME = [""]


class Dummy:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return lambda *a, **k: None


class MapTool(QtCore.QObject):
    def __init__(self, *a, **k): super().__init__()
    def __getattr__(self, n): return lambda *a, **k: None


class Measure:
    """Lengths in the units of the system: a metric grid is all these use."""
    def __init__(self, *a, **k): pass
    def setSourceCrs(self, *a): pass
    def setEllipsoid(self, *a): pass
    def measureLine(self, a, b):
        return ((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5
    def measureArea(self, g): return 0.0


class Point:
    def __init__(self, x, y=None):
        if y is None: x, y = x.x(), x.y()
        self._x, self._y = float(x), float(y)
    def x(self): return self._x
    def y(self): return self._y


class Rect:
    def __init__(self, a, b, c, d):
        self.v = [min(a, c), min(b, d), max(a, c), max(b, d)]
    def xMinimum(self): return self.v[0]
    def yMinimum(self): return self.v[1]
    def xMaximum(self): return self.v[2]
    def yMaximum(self): return self.v[3]
    def width(self): return self.v[2] - self.v[0]
    def height(self): return self.v[3] - self.v[1]
    def center(self):
        return Point((self.v[0] + self.v[2]) / 2.0, (self.v[1] + self.v[3]) / 2.0)


class App:
    @staticmethod
    def getThemeIcon(name): return QtGui.QIcon()


class Paletted:
    class Class:
        def __init__(self, value, color, label=""):
            self.value, self.color, self.label = value, QtGui.QColor(color), label
    def __init__(self, provider, band, classes):
        self._band, self._classes = band, list(classes)
    def type(self): return "paletted"
    def band(self): return self._band
    def classes(self): return list(self._classes)


class Gray:
    def type(self): return "singlebandgray"
    def band(self): return 1


core = types.ModuleType("qgis.core")
for n in ("QgsRasterLayer", "QgsVectorLayer", "QgsFillSymbol",
          "QgsMarkerSymbol", "QgsLineSymbol", "QgsCategorizedSymbolRenderer",
          "QgsMessageLog", "Qgis", "QgsRendererCategory",
          "QgsSingleSymbolRenderer", "QgsGeometry", "QgsFeature", "QgsWkbTypes",
          "QgsFeatureRequest", "QgsMultiBandColorRenderer",
          "QgsCoordinateTransform", "QgsPalLayerSettings", "QgsTextFormat",
          "QgsTextBufferSettings", "QgsVectorLayerSimpleLabeling",
          "QgsRuleBasedRenderer", "QgsUnitTypes", "QgsProperty",
          "QgsSymbolLayer"):
    setattr(core, n, Dummy)
core.QgsPalettedRasterRenderer = Paletted
core.QgsDistanceArea = Measure
core.QgsCoordinateReferenceSystem = Crs
core.QgsProject = Project
core.QgsApplication = App
core.QgsPointXY = Point
core.QgsRectangle = Rect
sys.modules["qgis.core"] = core

gui = types.ModuleType("qgis.gui")
gui.QgsMapTool = MapTool; gui.QgsRubberBand = Dummy; gui.QgsVertexMarker = Dummy
gui.QgsMapCanvas = Dummy
sys.modules["qgis.gui"] = gui


# ------------------------------------------------------------ the rasters
class Band:
    """Keeps what is written into it, at the offset it was written at."""
    DataType = 1                        # GDT_Byte
    def __init__(self, array, description, nodata):
        self.array, self._d, self._nodata = array, description, nodata
    def ReadAsArray(self, x=0, y=0, w=None, h=None, *a, **k):
        if w is None or h is None:
            return self.array.copy()
        return self.array[int(y):int(y) + int(h), int(x):int(x) + int(w)].copy()
    def WriteArray(self, a, x=0, y=0):
        h, w = a.shape
        self.array[y:y + h, x:x + w] = a
    def GetDescription(self): return self._d
    def GetNoDataValue(self): return self._nodata
    def GetColorTable(self): return None
    def GetCategoryNames(self): return None
    def FlushCache(self): pass


class DataSet:
    def __init__(self, store):
        self.store = store["bands"]
        self.gt = store["gt"]
        h, w = self.store[0].array.shape
        self.RasterXSize, self.RasterYSize = w, h
        self.RasterCount = len(self.store)
    def GetGeoTransform(self): return self.gt
    def GetProjection(self): return "PROJCS[\"fake\"]"
    def GetRasterBand(self, b): return self.store[b - 1]
    def FlushCache(self): pass


DISK = {}


def key(path):
    return os.path.normcase(os.path.abspath(path))


def write_map(path, array, nodata=None, gt=(500000.0, 2.0, 0.0, 4100000.0,
                                            0.0, -2.0), flagged=False):
    """A raster on the fake disk, and an empty file of its name on the real
    one, so that every os.path.exists in the program answers truly."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bands = [Band(np.array(array).copy(), "classes", nodata)]
    if flagged:
        bands.append(Band(np.zeros(np.shape(array), np.uint8), "corrected", None))
    DISK[key(path)] = {"bands": bands, "gt": gt}
    with open(path, "wb") as f:
        f.write(b"raster " + os.path.basename(path).encode())


def read_map(path, band=1):
    return DISK[key(path)]["bands"][band - 1].array.copy()


def open_map(path, *a, **k):
    store = DISK.get(key(path))
    return None if store is None else DataSet(store)


def fake_build_copy(source, destination, log_lines=None, band_no=None,
                    wkt=None):
    """The map itself, band for band, and nothing added."""
    store = DISK[key(source)]
    write_map(destination, store["bands"][0].array,
              store["bands"][0].GetNoDataValue(), store["gt"])
    DISK[key(destination)]["bands"] = [
        Band(b.array.copy(), b._d, b._nodata) for b in store["bands"]]
    return len(store["bands"])


def write_changes(path, shape, gt, flags=None, name="corrected"):
    """The record of changed pixels on the fake disk: one band, "corrected",
    or another record of pixels on the same grid under its own name."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    marks = (np.zeros(shape, np.uint8) if flags is None
             else (np.asarray(flags) != 0).astype(np.uint8))
    DISK[key(path)] = {"bands": [Band(marks, name, None)], "gt": gt}
    with open(path, "wb") as f:
        f.write(b"changes " + os.path.basename(path).encode())
    return int(marks.sum())


def fake_build_changes(like, destination, flags=None, name="corrected",
                       meaning="", colour=None):
    store = DISK[key(like)]
    return write_changes(destination, store["bands"][0].array.shape,
                         store["gt"],
                         None if flags is None else flags.array, name)


def fake_strip_flag_band(copy, changes, band_no=1, before_swap=None):
    store = DISK[key(copy)]
    flag = [i for i, b in enumerate(store["bands"])
            if (b._d or "").lower() == "corrected"]
    if not flag:
        return None
    i = flag[-1]
    pixels = write_changes(changes, store["bands"][i].array.shape, store["gt"],
                           store["bands"][i].array)
    done = {"pixels": pixels, "band": band_no - (1 if i + 1 < band_no else 0),
            "dropped": i + 1, "bands": len(store["bands"]) - 1}
    if before_swap is not None:
        before_swap(done)
    del store["bands"][i]
    STRIPPED.append(copy)
    return done


STRIPPED = []


REAL = bool(os.environ.get("RL_KIT_REAL_GDAL"))
gdal = types.ModuleType("gdal")
gdal.GDT_Byte = 1
gdal.GCI_Undefined = 0
gdal.GA_Update = 1
gdal.Open = open_map
gdal.Warp = lambda *a, **k: None
gdal.RasterizeLayer = lambda *a, **k: None
gdal.GetDataTypeSize = lambda t: 8
gdal.GetDataTypeName = lambda t: "Byte"
gdal.GetDriverByName = lambda n: Dummy()
ogr = types.ModuleType("ogr")
for n in ("wkbPolygon", "wkbMultiPolygon", "wkbPoint", "wkbLineString",
          "wkbMultiLineString", "wkbUnknown", "wkbLinearRing", "OFTString",
          "OFTReal", "OFTInteger"):
    setattr(ogr, n, 0)
ogr.GetDriverByName = lambda n: Dummy()
ogr.Open = lambda *a, **k: None
ogr.Feature = Dummy
ogr.FieldDefn = Dummy
ogr.CreateGeometryFromWkb = lambda b: None
osgeo = types.ModuleType("osgeo")
osgeo.gdal = gdal; osgeo.ogr = ogr; osgeo.osr = types.ModuleType("osr")
osgeo.osr.SpatialReference = Dummy
if REAL:
    from osgeo import gdal, ogr                                   # noqa: F811
else:
    sys.modules["osgeo"] = osgeo
    sys.modules["osgeo.gdal"] = gdal
    sys.modules["osgeo.ogr"] = ogr
    sys.modules["osgeo.osr"] = osgeo.osr

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

SRC = os.environ.get("RL_SRC", _BUILT)
code = (open(SRC, encoding="utf-8").read()
        .replace("\nmain()\n", "\n").replace("\nstart()\n", "\n"))
SAID = []


class Bar:
    def pushMessage(self, *a, **k): SAID.append(" ".join(str(x) for x in a))


class Iface(Dummy):
    def messageBar(self): return Bar()


utils.iface = Iface()
g = {"__name__": "rasterlabel", "__file__": SRC, "iface": utils.iface}
exec(compile(code, SRC, "exec"), g)


class Canvas:
    def extent(self): return Dummy()
    def mapSettings(self):
        m = Dummy(); m.destinationCrs = lambda: Crs(); return m
    def __getattr__(self, n): return lambda *a, **k: None


g["canvas"] = lambda: Canvas()
g["BrushTool"] = MapTool
g["CutoutTool"] = MapTool
if not REAL:
    g["build_copy"] = fake_build_copy
    g["build_changes"] = fake_build_changes
    g["strip_flag_band"] = fake_strip_flag_band
g["project_rasters"] = lambda need_crs=True: sorted(
    [l for l in LOADED.values() if isinstance(l, Layer)],
    key=lambda l: l.name().lower())


class Geom:
    """Geometry as far as Correct asks of it, read from the book it is given:
    so a test can see which grid the areas are measured on."""
    def __init__(self, book, crs=None):
        self.pixel_m = tuple(book.data["grid"]["pixel_m"])
        self.crs = Crs(); self.metric = Crs()
    def area(self, g): return 0.0


g["Geometry"] = Geom


def info(path):
    """(geotransform, width, height, the nodata of each band) of a raster,
    from the fake disk or, with real GDAL, from the file."""
    if REAL:
        ds = gdal.Open(path)
        out = (ds.GetGeoTransform(), ds.RasterXSize, ds.RasterYSize,
               [ds.GetRasterBand(b).GetNoDataValue()
                for b in range(1, ds.RasterCount + 1)])
        ds = None
        return out
    store = DISK[key(path)]
    h, w = store["bands"][0].array.shape
    return store["gt"], w, h, [b.GetNoDataValue() for b in store["bands"]]


class Provider:
    def __init__(self, layer): self.layer = layer
    def bandCount(self): return len(info(self.layer.path)[3])
    def generateBandName(self, b): return "Band %d" % b
    def sourceHasNoDataValue(self, b):
        return info(self.layer.path)[3][b - 1] is not None
    def sourceNoDataValue(self, b):
        return info(self.layer.path)[3][b - 1]


class Layer:
    """A raster layer in the project: a path on the fake disk, a style."""
    def __init__(self, path, name, renderer=None, lid=None):
        self.path, self._name = path, name
        self._renderer = renderer or Gray()
        self._id = lid or "layer_%s" % name
        self._props = {}
    def id(self): return self._id
    def customProperty(self, k, default=None): return self._props.get(k, default)
    def setCustomProperty(self, k, v): self._props[k] = v
    def name(self): return self._name
    def source(self): return self.path
    def renderer(self): return self._renderer
    def setRenderer(self, r): self._renderer = r
    def dataProvider(self): return Provider(self)
    def triggerRepaint(self): pass
    def isValid(self): return True
    def crs(self): return Crs()
    def _gt(self): return info(self.path)[0]
    def width(self): return info(self.path)[1]
    def height(self): return info(self.path)[2]
    def rasterUnitsPerPixelX(self): return abs(self._gt()[1])
    def rasterUnitsPerPixelY(self): return abs(self._gt()[5])
    def extent(self):
        gt = self._gt()
        return Rect(gt[0], gt[3] + gt[5] * self.height(),
                    gt[0] + gt[1] * self.width(), gt[3])


def add_layer(layer, ticked=True):
    LOADED[layer.id()] = layer
    TREE[layer.id()] = ticked
    return layer


# ------------------------------------------------------------ the dialogs
ANSWERS = {}
ASKED = []
UNEXPECTED = []


def run_dialog(dialog):
    name = type(dialog).__name__
    ASKED.append(name)
    answer = ANSWERS.pop(name, None)
    if answer is None:
        UNEXPECTED.append(name)
        return 0
    return answer(dialog)


g["run_dialog"] = run_dialog

BOXES = []


def _box(kind, answer):
    def f(*a, **k):
        text = a[2] if len(a) > 2 else ""
        BOXES.append((kind, str(text)))
        return answer
    return staticmethod(f)


QtWidgets.QMessageBox.warning = _box("warning", QtWidgets.QMessageBox.StandardButton.Cancel)
QtWidgets.QMessageBox.critical = _box("critical", QtWidgets.QMessageBox.StandardButton.Ok)
QtWidgets.QMessageBox.information = _box("information", QtWidgets.QMessageBox.StandardButton.Ok)
QtWidgets.QMessageBox.question = _box("question", QtWidgets.QMessageBox.StandardButton.Yes)


class P:
    def __init__(self, x, y): self._x, self._y = x, y
    def x(self): return self._x
    def y(self): return self._y
    def asPoint(self): return self


class Stroke:
    def makeValid(self): return self
    def centroid(self): return P(500004.0, 4099996.0)


def everything_under(folder):
    out = []
    for here, dirs, files in os.walk(folder):
        for f in files:
            out.append(os.path.relpath(os.path.join(here, f), folder))
    return sorted(out)


fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail))
           if not cond and not (isinstance(detail, str) and not detail)
           else ""))
    if not cond:
        fails.append(name)


def finish():
    if UNEXPECTED:
        check("no window opened that the suite did not expect", False,
              UNEXPECTED)
    print()
    print("FAILED: %d" % len(fails) if fails else "all pass")
    for f in fails:
        print("   " + f)
    return 1 if fails else 0
