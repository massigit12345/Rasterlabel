"""Render the RasterLabel panel offscreen, with every QGIS call stubbed out.
Only the layout is real: widgets, margins, spacings, sizes."""
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os, sys, tempfile, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtbinding import PyQt, QtCore, QtGui, QtWidgets

# ---------------------------------------------------------------- fake qgis
qgis = types.ModuleType("qgis")
qgis.PyQt = PyQt
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
    def __eq__(self, o): return True


class Project:
    _one = None
    layersAdded = Sig()
    layersRemoved = Sig()
    @classmethod
    def instance(cls):
        if cls._one is None:
            cls._one = cls()
        return cls._one
    def mapLayers(self): return {}
    def mapLayer(self, i): return None
    def layerTreeRoot(self): return None
    def setAvoidIntersectionsLayers(self, x): pass
    def setTopologicalEditing(self, x): pass


class Dummy:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return lambda *a, **k: None


class MapTool(QtCore.QObject):
    def __init__(self, *a, **k): super().__init__()
    def __getattr__(self, n): return lambda *a, **k: None


class App:
    @staticmethod
    def getThemeIcon(name):
        return QtGui.QIcon()


core = types.ModuleType("qgis.core")
for n in ("QgsRasterLayer", "QgsVectorLayer", "QgsPointXY", "QgsRectangle",
          "QgsDistanceArea", "QgsFillSymbol", "QgsMarkerSymbol",
          "QgsCategorizedSymbolRenderer", "QgsRendererCategory",
          "QgsSingleSymbolRenderer", "QgsGeometry", "QgsFeature",
          "QgsWkbTypes", "QgsCoordinateTransform", "QgsFeatureRequest",
          "QgsPalettedRasterRenderer", "QgsMultiBandColorRenderer"):
    setattr(core, n, Dummy)
core.QgsCoordinateReferenceSystem = Crs
core.QgsProject = Project
core.QgsApplication = App
sys.modules["qgis.core"] = core

gui = types.ModuleType("qgis.gui")
gui.QgsMapTool = MapTool
gui.QgsRubberBand = Dummy
gui.QgsVertexMarker = Dummy
gui.QgsMapCanvas = Dummy
sys.modules["qgis.gui"] = gui

gdal = types.ModuleType("gdal")
gdal.GDT_Byte = 1
gdal.GCI_Undefined = 0
gdal.GA_Update = 1
for _n in ("Open", "Warp", "RasterizeLayer", "GetDriverByName"):
    setattr(gdal, _n, lambda *a, **k: None)
gdal.GetDataTypeSize = lambda t: 8
gdal.GetDataTypeName = lambda t: "Byte"
ogr = types.ModuleType("ogr")
for n in ("wkbPolygon", "wkbMultiPolygon", "wkbPoint", "OFTString", "OFTReal",
          "OFTInteger"):
    setattr(ogr, n, 0)
osgeo = types.ModuleType("osgeo")
osgeo.gdal = gdal
osgeo.ogr = ogr
osgeo.osr = types.ModuleType("osr")
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

# ---------------------------------------------------------------- the file
SRC = os.environ.get("RL_SRC", _BUILT)
code = open(SRC, encoding="utf-8").read().replace("\nmain()\n", "\n").replace("\nstart()\n", "\n")
utils.iface = Dummy()        # what the package will import by name
g = {"__name__": "rasterlabel", "__file__": SRC, "iface": utils.iface}
exec(compile(code, SRC, "exec"), g)


class Canvas:
    def extent(self): return Dummy()
    def mapSettings(self):
        m = Dummy(); m.destinationCrs = lambda: Crs(); return m
    def __getattr__(self, n): return lambda *a, **k: None


g["canvas"] = lambda: Canvas()
g["find_mine"] = lambda *a, **k: None
g["BrushTool"] = MapTool
g["TileTool"] = MapTool
g["PointTool"] = MapTool


class Geom:
    pixel_m = (0.05, 0.05)
    crs = Crs()
    metric = Crs()
    def __init__(self, *a, **k): pass


g["Geometry"] = Geom

CLASSES = [{"name": "crust", "code": 1, "colour": "#b0651f"},
           {"name": "wet mud", "code": 2, "colour": "#7c5b3f"},
           {"name": "water", "code": 3, "colour": "#2f6f9f"},
           {"name": "vegetation", "code": 4, "colour": "#4a7f3a"},
           {"name": "bare rock", "code": 5, "colour": "#8a8a8a"}]


class Campaign:
    # Only shown in the panel, never opened, so any folder will do, and
    # this one exists on every machine.
    folder = os.path.join(tempfile.gettempdir(), "aragona_2025")
    data = {"id": "abc123", "name": "aragona_2025",
            "with_tiles": "free" not in sys.argv,
            "operator": "MG", "classes": CLASSES,
            "grid": {"pixel_m": [0.05, 0.05], "crs": "EPSG:32633"}}
    def active_classes(self): return CLASSES


panel = g["Panel"]()
panel.campaign = Campaign()
panel.describe_campaign()
panel.update_enabled()
panel.toggle_module(0)
if "settings" in sys.argv:
    panel.annotation.fold.setChecked(True)

w = int(sys.argv[1]) if len(sys.argv) > 1 else 286
panel.setFixedWidth(w)
panel.show()
app.processEvents()
# what the scroll area in the dock does: give it the width, then ask how tall
# it has to be at that width
for _ in range(3):
    panel.resize(w, max(panel.heightForWidth(w), panel.sizeHint().height()))
    app.processEvents()
out = os.environ.get("OUT") or os.path.join(tempfile.gettempdir(), "panel.png")
panel.grab().save(out)
print("rendered %d x %d -> %s" % (panel.width(), panel.height(), out))
