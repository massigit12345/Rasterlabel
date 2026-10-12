"""Render the two new modules offscreen. QGIS and GDAL are stubbed with just
enough behaviour to build the panels and exercise the arithmetic.

    harness2.py WIDTH [annotation|objects|correction|cutouts|none] [free]
                [bare] [corrected] [thirty] [dark|night] [fresh]
                [style=NAME] ...

"free" renders with no annotation campaign open: the state the panel is in
when Correct and Cutouts are used on their own. Correct then runs on a
correction campaign of its own, in a temporary folder. "none" opens no
module at all, and "corrected" opens a correction in CORRECTION. A correction
is open only while Correct is, so "corrected" belongs with "correction"; with
another module it draws a state the panel itself never reaches.

"thirty" gives the campaign thirty classes with long names. "dark" is a dark
Fusion palette; "night" is QGIS's Night Mapping as it really is: a palette
that leaves Button light grey and a Window it does not paint with, and an
application stylesheet that paints the docks, the labels and the buttons
itself. The rules below are the ones of its style.qss that reach the panel.

"fresh" leaves the panel as it is built, before any campaign was described
in it, and "style=NAME" draws it under that Qt style, where Qt has it."""
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os, sys, tempfile, types
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
for _arg in sys.argv:
    # "style=windows11": the panel under that Qt style, where Qt has it
    if _arg.startswith("style=") and _arg[6:] in QtWidgets.QStyleFactory.keys():
        app.setStyle(_arg[6:])
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
NIGHT_QSS = """
QWidget { background: transparent; }
QWidget[autoFillBackground=true] { background-color: #323232; }
QLabel, QCheckBox, QRadioButton { color: #aaa; }
QMainWindow, QDialog, QAbstractScrollArea, QDockWidget, QGroupBox {
    color: #aaa; background-color: #323232; }
QWidget:disabled { color: #535353; background-color: #323232; }
QPushButton { padding: 0.315em; border-width: 1px; border-color: #202020;
    border-style: solid; border-radius: 0px;
    background-color: QLinearGradient(x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 #565656, stop: 0.5 #4e4e4e, stop: 1 #464646);
    color: #aaa; }
QToolButton { padding: 0.18em; border: 1px solid #202020;
    background-color: #535353; color: #aaa; }
QToolButton[autoRaise=true] { border: 1px solid rgba(0,0,0,0);
    background-color: transparent; }
QLineEdit { padding: 0.18em; border: 1px solid #535353;
    background-color: #202020; }
QGroupBox { padding-top: 1.575em; border: 1px solid rgba(0,0,0,0); }
"""
if "night" in sys.argv:
    QPalette, _QC = QtGui.QPalette, QtGui.QColor
    app.setStyle("Fusion")
    pal = QPalette()
    for role, colour in (("Window", "#535353"), ("WindowText", "#aaaaaa"),
                         ("Base", "#202020"), ("Text", "#dddddd"),
                         ("Button", "#efefef"), ("ButtonText", "#000000"),
                         ("Highlight", "#d7801a"),
                         ("HighlightedText", "#323232")):
        pal.setColor(getattr(QPalette.ColorRole, role), _QC(colour))
    app.setPalette(pal)
    app.setStyleSheet(NIGHT_QSS)
DARK = True

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
# need_crs is a keyword the program passes; a stub that refuses it
# turns a change in the program into a failure in the harness.
g["project_rasters"] = lambda need_crs=True: []
g["BrushTool"] = MapTool
g["TileTool"] = MapTool
g["CutoutTool"] = MapTool
g["BoxTool"] = MapTool


class Geom:
    pixel_m = (0.05, 0.05)
    crs = Crs(); metric = Crs()
    def __init__(self, *a, **k): pass
    def area(self, g): return 12.5


g["Geometry"] = Geom

CLASSES = [{"name": "crust", "code": 1, "colour": "#b0651f"},
           {"name": "wet mud", "code": 2, "colour": "#7c5b3f"},
           {"name": "water", "code": 3, "colour": "#2f6f9f"},
           {"name": "vegetation", "code": 4, "colour": "#4a7f3a"},
           {"name": "bare rock", "code": 5, "colour": "#8a8a8a"}]
if "thirty" in sys.argv:
    # a legend as long as a land cover map's, with the names it really has
    NAMES = ["Mediterranean maquis shrubland", "permanent grassland",
             "olive grove", "greenhouse plastic", "bare soil",
             "gypsum outcrop", "shadow", "road", "buildings", "vineyard",
             "almond orchard", "citrus orchard", "reed bed", "salt crust",
             "wet mud", "open water", "badlands", "landslide scar", "quarry",
             "stubble field", "ploughed field", "garrigue",
             "pine plantation", "riparian woodland", "dry stream bed",
             "solar farm", "greenhouse glass", "efflorescence", "cliff",
             "debris"]
    CLASSES = [{"name": n, "code": i + 1,
                "colour": ["#2e8b57", "#f2f2f2", "#202020", "#8a8a8a",
                           "#b0651f", "#2f6f9f"][i % 6]}
               for i, n in enumerate(NAMES)]


class Campaign:
    # Only shown in the panel, never opened, so any folder will do, and
    # this one exists on every machine.
    folder = os.path.join(tempfile.gettempdir(), "aragona_2025")
    data = {"id": "abc123", "name": "aragona_2025", "with_tiles": True,
            "operator": "MG", "classes": CLASSES, "corrections": [], "cutouts": [],
            "grid": {"pixel_m": [0.05, 0.05], "crs": "EPSG:32633",
                     "reference_raster": "", "origin": [400000.0, 4100000.0]}}
    def active_classes(self): return CLASSES
    def save(self): pass
    @property
    def stem(self): return "aragona_2025"
    def layer_name(self, table): return "%s_%s" % (self.stem, table)


panel = g["Panel"]()
if "night" in sys.argv:
    # what the dock and its scroll area paint under the panel in QGIS
    panel.setAutoFillBackground(True)
FREE = "free" in sys.argv
panel.campaign = None if FREE else Campaign()
if FREE and "bare" not in sys.argv:
    # a raster in the selector, as there is when Correct or Cutouts is used;
    # "bare" leaves it empty, as the panel is before any raster is loaded
    panel.rasters.addItem("ortho_2025", "ortho_2025")
if "fresh" not in sys.argv:
    # "fresh" leaves the panel as it is built, before anything was opened
    panel.describe_campaign()
panel.update_enabled()

which = sys.argv[2] if len(sys.argv) > 2 else "correction"


def correction_book():
    book = g["CorrectionCampaign"](tempfile.mkdtemp(prefix="rl_harness2_"))
    book.data = {"program": "RasterLabel", "kind": "correction", "format": 1,
                 "id": "c0ffee", "name": "landcover_fix", "operator": "ANN",
                 "source": "/data/mask_2025.tif", "band": 1,
                 "working_copy": "mask_2025_corrected.tif",
                 "grid": {"pixel_m": [0.05, 0.05], "crs": "EPSG:32633",
                          "origin": [400000.0, 4100000.0]},
                 "classes": [dict(c) for c in CLASSES[:3]],
                 "operations": 7, "changed_m2": 41.25}
    return book


if "corrected" in sys.argv or (which == "correction" and FREE):
    panel.correction = correction_book()
    panel.describe_correction()
    panel.update_enabled()
if which == "none":
    section = None
elif which == "annotation":
    section = g["AnnotationSection"](panel)
elif which == "objects":
    section = g["ObjectsSection"](panel)
elif which == "correction" and (FREE or panel.correction is not None):
    book = panel.correction
    section = g["CorrectionSection"](panel, book.data, book=book)
elif which == "correction":
    record = {"name": "correction 1", "source": "/data/mask_2025.tif",
              "band": 1, "files": [os.path.join(Campaign.folder, "corrections", "c1",
                                     "m_corrected.tif")],
              "operations": 7, "changed_m2": 41.25}
    section = g["CorrectionSection"](panel, record)
else:
    section = g["CutoutsSection"](panel)

if section is not None:
    panel.section = section
    panel.open_index = {"annotation": 0, "correction": 1,
                        "objects": 2}.get(which, 3)
    panel.modules[panel.open_index].setChecked(True)
    panel.annotation_slot.addWidget(section)
    if "settings" in sys.argv:
        section.fold.setChecked(True)
    for word, attr in (("line", "b_line"), ("round", "round_brush"),
                       ("points", "b_points"), ("tiles", "b_tiles")):
        if word in sys.argv and hasattr(section, attr):
            getattr(section, attr).setChecked(True)
            if hasattr(section, "tool_settings"):
                section.tool_settings()
    panel.redeal()

w = int(sys.argv[1]) if len(sys.argv) > 1 else 286
panel.setFixedWidth(w)
panel.show()
app.processEvents()
# what the scroll area in the dock does: give it the width, then ask how tall
# it has to be at that width
for _ in range(3):
    panel.resize(w, max(panel.heightForWidth(w), panel.sizeHint().height()))
    app.processEvents()
out = (os.environ.get("OUT")
       or os.path.join(tempfile.gettempdir(), "panel2.png"))
panel.grab().save(out)
print("rendered %d x %d -> %s" % (panel.width(), panel.height(), out))
