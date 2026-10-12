"""Enough of QGIS, Qt, numpy and GDAL for the package to be imported.

Taken from harness2.py, which builds the same fakes to exec the single file.
This one stops before reading any source: it exists so that
`import rasterlabel.panel` can be tried on a machine with no QGIS on it, which
is what a continuous integration run is.
"""
import os
import sys

ROOT = os.environ.get("RL_ROOT")
if ROOT and ROOT not in sys.path:
    sys.path.insert(0, ROOT)

"""Render the two new modules offscreen. QGIS and GDAL are stubbed with just
enough behaviour to build the panels and exercise the arithmetic."""
import os, sys, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from qtbinding import PyQt, QtCore, QtGui, QtWidgets

qgis = types.ModuleType("qgis"); qgis.PyQt = PyQt
sys.modules["qgis"] = qgis
sys.modules["qgis.PyQt"] = PyQt
utils = types.ModuleType("qgis.utils")
utils.iface = None          # the harness replaces it below
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
    def isValid(self): return True
    def isGeographic(self): return False
    def createFromWkt(self, w): return True
    def __eq__(self, o): return True
    def __ne__(self, o): return False


class Project:
    _one = None
    layersAdded = Sig(); layersRemoved = Sig()
    @classmethod
    def instance(cls):
        if cls._one is None: cls._one = cls()
        return cls._one
    def mapLayers(self): return {}
    def mapLayer(self, i): return None
    def layerTreeRoot(self): return None
    def transformContext(self): return None
    def ellipsoid(self): return "WGS84"
    def setAvoidIntersectionsLayers(self, x): pass
    def setTopologicalEditing(self, x): pass
    def addMapLayer(self, *a, **k): pass
    def removeMapLayers(self, *a): pass


class Dummy:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return lambda *a, **k: None


class MapTool(QtCore.QObject):
    def __init__(self, *a, **k): super().__init__()
    def __getattr__(self, n): return lambda *a, **k: None


class Measure:
    def __init__(self, *a, **k): pass
    def setSourceCrs(self, *a): pass
    def setEllipsoid(self, *a): pass
    def measureLine(self, a, b): return 1.0
    def measureArea(self, g): return 12.5


class App:
    @staticmethod
    def getThemeIcon(name): return QtGui.QIcon()


core = types.ModuleType("qgis.core")
for n in ("QgsRasterLayer", "QgsVectorLayer", "QgsPointXY", "QgsRectangle",
          "QgsFillSymbol", "QgsMarkerSymbol", "QgsLineSymbol", "QgsCategorizedSymbolRenderer",
          "QgsMessageLog", "Qgis",
          "QgsRendererCategory", "QgsSingleSymbolRenderer", "QgsGeometry",
          "QgsFeature", "QgsWkbTypes", "QgsFeatureRequest",
          "QgsPalettedRasterRenderer", "QgsMultiBandColorRenderer",
          "QgsCoordinateTransform",
          # the five that version 3.15 used without ever importing them
          "QgsPalLayerSettings", "QgsTextFormat", "QgsTextBufferSettings",
          "QgsVectorLayerSimpleLabeling", "QgsRuleBasedRenderer",
          "QgsUnitTypes", "QgsProperty", "QgsSymbolLayer"):
    setattr(core, n, Dummy)
core.QgsDistanceArea = Measure
core.QgsCoordinateReferenceSystem = Crs
core.QgsProject = Project
core.QgsApplication = App
sys.modules["qgis.core"] = core

gui = types.ModuleType("qgis.gui")
gui.QgsMapTool = MapTool; gui.QgsRubberBand = Dummy; gui.QgsVertexMarker = Dummy
gui.QgsMapCanvas = Dummy
gui.QgsMapCanvas = Dummy
sys.modules["qgis.gui"] = gui

# ---------------------------------------------------------------- fake gdal
NX, NY = 400, 300
CLASS_ARRAY = np.zeros((NY, NX), np.uint8)
CLASS_ARRAY[:150] = 1
CLASS_ARRAY[150:] = 3


class Band:
    def __init__(self, array, description=""):
        self.array = array
        self._d = description
    def ReadAsArray(self, *a): return self.array
    def WriteArray(self, a, x=0, y=0): pass
    def GetDescription(self): return self._d
    def SetDescription(self, d): self._d = d
    def GetNoDataValue(self): return 0
    def SetNoDataValue(self, v): pass
    def SetColorInterpretation(self, v): pass
    def Fill(self, v): pass
    def GetHistogram(self, lo, hi, n, approx=1, force=0):
        counts = [0] * n
        for v in (1, 3):
            counts[v] = 100
        return counts
    DataType = 1


class DataSet:
    RasterXSize, RasterYSize, RasterCount = NX, NY, 2
    def GetGeoTransform(self): return (400000.0, 0.05, 0.0, 4100000.0, 0.0, -0.05)
    def SetGeoTransform(self, g): pass
    def GetProjection(self): return ""
    def SetProjection(self, w): pass
    def GetRasterBand(self, b):
        # A thematic map of two bands, the classes and how sure the model
        # was, as the maps Correct is given are: the working copy is the
        # map itself, and the record of changed pixels is a file beside it.
        return Band(CLASS_ARRAY, "classes" if b == 1 else "probability")
    def FlushCache(self): pass


gdal = types.ModuleType("gdal")
gdal.GDT_Byte = 1
gdal.GCI_Undefined = 0
gdal.GA_Update = 1
gdal.Open = lambda *a, **k: DataSet()
gdal.Warp = lambda *a, **k: DataSet()
gdal.RasterizeLayer = lambda *a, **k: None
gdal.GetDataTypeSize = lambda t: 8
gdal.GetDataTypeName = lambda t: "Byte"
gdal.GetDriverByName = lambda n: Dummy()
ogr = types.ModuleType("ogr")
for n in ("wkbPolygon", "wkbMultiPolygon", "wkbPoint", "wkbLineString", "wkbMultiLineString", "wkbUnknown",
          "OFTString", "OFTReal", "OFTInteger"):
    setattr(ogr, n, 0)
ogr.GetDriverByName = lambda n: Dummy()
ogr.Feature = Dummy
ogr.FieldDefn = Dummy
ogr.CreateGeometryFromWkb = lambda b: None
osgeo = types.ModuleType("osgeo")
osgeo.gdal = gdal; osgeo.ogr = ogr; osgeo.osr = types.ModuleType("osr")
osgeo.osr.SpatialReference = Dummy
sys.modules["osgeo"] = osgeo
sys.modules["osgeo.gdal"] = gdal
sys.modules["osgeo.ogr"] = ogr
sys.modules["osgeo.osr"] = osgeo.osr

app = QtWidgets.QApplication(sys.argv)
if "dark" in sys.argv:
    QPalette, _QC = QtGui.QPalette, QtGui.QColor
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, _QC(60, 62, 65))
    pal.setColor(QPalette.ColorRole.WindowText, _QC(228, 228, 228))
    pal.setColor(QPalette.ColorRole.Base, _QC(42, 44, 46))
    pal.setColor(QPalette.ColorRole.Text, _QC(228, 228, 228))
    pal.setColor(QPalette.ColorRole.Button, _QC(72, 74, 78))
    pal.setColor(QPalette.ColorRole.ButtonText, _QC(228, 228, 228))
    pal.setColor(QPalette.ColorRole.Highlight, _QC(58, 123, 213))
    pal.setColor(QPalette.ColorRole.HighlightedText, _QC(255, 255, 255))
    app.setPalette(pal)
DARK = True

