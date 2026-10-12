"""Correct paints with the classes of the map it corrects, not with the legend.

The legend of a campaign is what people draw with in Annotate and Objects. The
map Correct mends came out of a model, numbered the model's way: a land cover
map with water at 0, crops at 3, roads at 7 and forest at 12 has nothing to do
with a legend of "crust" at 1 and "mud" at 2. Correct used to offer the legend
as its chips, so the brush wrote 1 and 2 into a map that had never held either,
Ctrl and click on a forest pixel said "the legend does not name it", and the
copy was painted in the legend's colours, which named nothing on it.

So this suite builds that map, with nodata at 255 and a legend of two other
codes, opens the real CorrectionSection on it with QGIS faked, and asks:

  the chips are the map's codes, {0, 3, 7, 12}, nodata not among them;
  with a paletted style on the layer they carry its names and colours, and
  without one they are "class 7" in distinct colours;
  a stroke writes the thematic code in hand into the pixels;
  Ctrl and click picks the code under the cursor, and a code nobody listed
  is given a class instead of being refused;
  the classes are kept in the record, and reopening shows the same ones even
  when the style has changed since;
  a record made by an earlier build, with no classes, gets them on opening;
  the Classes of the campaign do not reach the correction, and Annotate still
  shows the legend.

And that the panel says what changes into what: FROM chips are any class and
the classes, TO chips are the classes and "+", the banner reads "FROM crops,
TO forest" (or says there is nothing to change when the two are the same), a
stroke from crops to forest changes only crops and one from any class changes
everything but nodata, Ctrl+click on the map sets FROM and Shift+click sets TO
through the brush itself, and Shift in Annotate still starts a stroke.

Needs PyQt5 or PyQt6, and numpy. Not GDAL: the raster is a fake that keeps what is
written into it, which is what is under test here.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os, shutil, sys, tempfile, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from qtbinding import PyQt, QtCore, QtGui, QtWidgets

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail != "" and not cond else ""))
    if not cond:
        fails.append(name)


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
    def isValid(self): return True
    def isGeographic(self): return False
    def createFromWkt(self, w): return True
    def __eq__(self, o): return True
    def __ne__(self, o): return False


LOADED = {}


class Project:
    _one = None
    layersAdded = Sig(); layersRemoved = Sig()
    @classmethod
    def instance(cls):
        if cls._one is None: cls._one = cls()
        return cls._one
    def mapLayers(self): return dict(LOADED)
    def mapLayer(self, i): return LOADED.get(i)
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


class Paletted:
    """QgsPalettedRasterRenderer, as far as a style is read and set."""
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


class StyledLayer:
    """A raster layer in the project, with the style a person gave it."""
    def __init__(self, path, renderer):
        self.path, self._renderer = path, renderer
    def id(self): return "thematic_layer"
    def name(self): return "landcover"
    def source(self): return self.path
    def renderer(self): return self._renderer
    def setRenderer(self, r): self._renderer = r
    def dataProvider(self): return None
    def triggerRepaint(self): pass


core = types.ModuleType("qgis.core")
for n in ("QgsRasterLayer", "QgsVectorLayer", "QgsPointXY", "QgsRectangle",
          "QgsFillSymbol", "QgsMarkerSymbol", "QgsLineSymbol",
          "QgsCategorizedSymbolRenderer", "QgsMessageLog", "Qgis",
          "QgsRendererCategory", "QgsSingleSymbolRenderer", "QgsGeometry",
          "QgsFeature", "QgsWkbTypes", "QgsFeatureRequest",
          "QgsMultiBandColorRenderer", "QgsCoordinateTransform",
          "QgsPalLayerSettings", "QgsTextFormat", "QgsTextBufferSettings",
          "QgsVectorLayerSimpleLabeling", "QgsRuleBasedRenderer",
          "QgsUnitTypes", "QgsProperty", "QgsSymbolLayer"):
    setattr(core, n, Dummy)
core.QgsPalettedRasterRenderer = Paletted
core.QgsDistanceArea = Measure
core.QgsCoordinateReferenceSystem = Crs
core.QgsProject = Project
core.QgsApplication = App
sys.modules["qgis.core"] = core

gui = types.ModuleType("qgis.gui")
gui.QgsMapTool = MapTool; gui.QgsRubberBand = Dummy; gui.QgsVertexMarker = Dummy
gui.QgsMapCanvas = Dummy
sys.modules["qgis.gui"] = gui

# ------------------------------------------------- the map a model produced
#
#   water 0, crops 3, roads 7, forest 12, and a hole of nodata at 255
#
WATER, CROPS, ROADS, FOREST, NODATA = 0, 3, 7, 12, 255
NX, NY = 8, 6
THEMATIC = np.array([
    [WATER, WATER, CROPS, CROPS, CROPS, ROADS,  FOREST, FOREST],
    [WATER, WATER, CROPS, CROPS, CROPS, ROADS,  FOREST, FOREST],
    [WATER, CROPS, CROPS, NODATA, NODATA, ROADS, FOREST, FOREST],
    [CROPS, CROPS, CROPS, NODATA, NODATA, ROADS, ROADS,  FOREST],
    [CROPS, CROPS, ROADS, ROADS, ROADS,  ROADS, FOREST, FOREST],
    [CROPS, CROPS, ROADS, FOREST, FOREST, FOREST, FOREST, FOREST],
], dtype=np.uint8)
GT = (500000.0, 1.0, 0.0, 4100000.0, 0.0, -1.0)


class Band:
    """Keeps what is written into it, at the offset it was written at."""
    def __init__(self, array, description, nodata):
        self.array, self._d, self._nodata = array, description, nodata
    def ReadAsArray(self, x=0, y=0, w=None, h=None, *a, **k):
        if w is None or h is None:
            return self.array.copy()
        return self.array[y:y + h, x:x + w].copy()
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
        self.store = store
        self.RasterXSize, self.RasterYSize, self.RasterCount = NX, NY, 2
    def GetGeoTransform(self): return GT
    def GetProjection(self): return ""
    def GetRasterBand(self, b):
        return self.store[b - 1]
    def FlushCache(self): pass


DISK = {}


def write_map(path):
    DISK[os.path.normcase(os.path.abspath(path))] = [
        Band(THEMATIC.copy(), "classes", NODATA),
        Band(np.zeros((NY, NX), np.uint8), "probability", None)]


def open_map(path, *a, **k):
    store = DISK.get(os.path.normcase(os.path.abspath(path)))
    return None if store is None else DataSet(store)


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
          "wkbMultiLineString", "wkbUnknown", "OFTString", "OFTReal",
          "OFTInteger"):
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

SRC = os.environ.get("RL_SRC", _BUILT)
code = (open(SRC, encoding="utf-8").read()
        .replace("\nmain()\n", "\n").replace("\nstart()\n", "\n"))
said = []


class Bar:
    def pushMessage(self, *a, **k): said.append(" ".join(str(x) for x in a))


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
g["find_mine"] = lambda *a, **k: None
g["drop_stale"] = lambda *a, **k: 0       # nor a stale one to drop
g["project_rasters"] = lambda need_crs=True: []
REAL_BRUSH = g["BrushTool"]     # the real one, for the press of Ctrl and Shift
g["BrushTool"] = MapTool
g["TileTool"] = MapTool
g["CutoutTool"] = MapTool
g["BoxTool"] = MapTool
logged = []
_log = g["log"]


def log(text, *a, **k):
    logged.append(str(text))
    try:
        _log(text, *a, **k)
    except Exception:
        pass


g["log"] = log


class Geom:
    pixel_m = (1.0, 1.0)
    crs = Crs(); metric = Crs()
    def __init__(self, *a, **k): pass
    def area(self, g): return 4.0


g["Geometry"] = Geom

LEGEND = [{"name": "crust", "code": 1, "colour": "#b0651f"},
          {"name": "wet mud", "code": 2, "colour": "#7c5b3f"}]
folder = tempfile.mkdtemp(prefix="rl_correct_classes_")


class Campaign:
    def __init__(self):
        self.folder = folder
        self.saves = 0
        self.data = {"id": "abc123", "name": "aragona_2025", "with_tiles": True,
                     "operator": "MG", "classes": [dict(c) for c in LEGEND],
                     "corrections": [], "cutouts": [],
                     "grid": {"pixel_m": [1.0, 1.0], "crs": "EPSG:32633",
                              "reference_raster": "",
                              "origin": [500000.0, 4100000.0]}}
    def active_classes(self):
        return [c for c in self.data["classes"] if not c.get("retired")]
    def next_code(self):
        return max([c["code"] for c in self.data["classes"]] or [0]) + 1
    def save(self): self.saves += 1
    @property
    def stem(self): return "aragona_2025"
    def layer_name(self, table): return "%s_%s" % (self.stem, table)
    @property
    def package_path(self): return os.path.join(folder, "campaign.gpkg")


panel = g["Panel"]()
panel.campaign = Campaign()


class P:
    def __init__(self, x, y): self._x, self._y = x, y
    def x(self): return self._x
    def y(self): return self._y
    def asPoint(self): return self


class Stroke:
    def makeValid(self): return self
    def centroid(self): return P(GT[0] + 4, GT[3] - 3)


def centre(col, row):
    return P(GT[0] + (col + 0.5) * GT[1], GT[3] + (row + 0.5) * GT[5])


def open_correction(record, layer=None):
    """The section as the panel makes it. The build before this change took
    no layer: it is opened without one there, so this suite says what that
    build does instead of stopping at its signature."""
    try:
        return g["CorrectionSection"](panel, record, layer=layer)
    except TypeError:
        return g["CorrectionSection"](panel, record)


def chips(section):
    return [b.text() for b in section._buttons if b.text() != "+"]


def from_chips(section):
    return [b.text() for b in section._from_buttons]


def codes_of(section):
    """The codes FROM offers, any class left out."""
    return [c["code"] for c in section.from_choices() if c["code"] is not None]


def banner(section):
    """The two halves of the banner as plain words, and the arrow."""
    def words(label):
        doc = QtGui.QTextDocument()
        doc.setHtml(label.text())
        return " ".join(doc.toPlainText().split())
    return (words(section.from_pill), section.arrow.text(),
            words(section.into_pill))


def new_record(name):
    source = os.path.join(folder, "%s_model.tif" % name)
    copy = os.path.join(folder, "corrections", name, "%s_corrected.tif" % name)
    os.makedirs(os.path.dirname(copy), exist_ok=True)
    write_map(source)
    write_map(copy)
    record = {"name": name, "source": source, "band": 1, "files": [copy],
              "operations": 0, "changed_m2": 0.0}
    panel.campaign.data["corrections"].append(record)
    return record


try:
    # ------------------------------------------------------------ no style
    print("a map with no style that names classes: the values are the classes")
    record = new_record("plain")
    gray = StyledLayer(record["source"], Gray())
    section = open_correction(record, gray)
    got = sorted(codes_of(section))
    check("FROM offers exactly the codes of the map, {0, 3, 7, 12}",
          got == [0, 3, 7, 12], got)
    check("one chip per code, and the legend's codes nowhere among them",
          len(chips(section)) == 4 and "crust" not in chips(section)
          and "wet mud" not in chips(section), chips(section))
    check("named after their code",
          chips(section) == ["class 0", "class 3", "class 7", "class 12"],
          chips(section))
    colours = [c["colour"] for c in record.get("classes", [])]
    check("in four different colours", len(set(colours)) == 4, colours)
    check("and nodata is not a class",
          NODATA not in [c["code"] for c in record.get("classes", [])])
    check("zero is a class, because it is not the nodata value",
          0 in [c["code"] for c in record.get("classes", [])])
    check("the class in hand is one of the map's", section.current_code()
          in (0, 3, 7, 12), section.current_code())

    print()
    print("a stroke writes the thematic code in hand")
    work = DISK[os.path.normcase(os.path.abspath(record["files"][0]))][0]
    section.choose_class(FOREST)
    check("forest is in hand", section.current_code() == FOREST
          and section.class_name == "class 12",
          (section.current_code(), section.class_name))
    check("and the banner says so",
          banner(section)[2] == "TO class 12", banner(section))
    section.choose_from(CROPS)
    inside = np.zeros((2, 3), bool)
    inside[:, :] = True
    section.mask_of = lambda geom: (2, 0, inside)       # rows 0-1, cols 2-4
    section.paint(Stroke())
    window = work.array[0:2, 2:5]
    check("the crops under the stroke became 12 in the band on disk",
          (window == FOREST).all(), window.tolist())
    check("and in the values the section holds",
          (section.values[0:2, 2:5] == FOREST).all())
    check("nothing became 1 or 2, the legend's codes",
          not np.isin(work.array, [1, 2]).any())
    check("the rest of the map is as the model made it",
          (work.array[2:] == THEMATIC[2:]).all())
    check("the tally names the pair by the map's own names",
          "class 3 -> class 12" in section.pairs, list(section.pairs))

    print()
    print("every class: the brush is a boundary, zero included, nodata spared")
    section.choose_from(None)
    section.choose_class(ROADS)
    box = np.zeros((3, 4), bool)
    box[:, :] = True
    section.mask_of = lambda geom: (0, 1, box)          # rows 1-3, cols 0-3
    section.paint(Stroke())
    check("water at zero under the stroke became roads",
          work.array[1, 0] == ROADS and work.array[2, 0] == ROADS,
          work.array[1:4, 0:4].tolist())
    check("and the nodata hole inside the stroke is left alone",
          work.array[2, 3] == NODATA and work.array[3, 3] == NODATA,
          work.array[1:4, 0:4].tolist())

    print()
    print("Ctrl and click picks the code under the cursor")
    said[:] = []
    section.reclassify_at(centre(7, 5))
    check("forest under the cursor: the brush now looks for 12",
          section.from_code == FOREST, section.from_code)
    section.reclassify_at(centre(3, 2))
    check("nodata under the cursor changes nothing",
          section.from_code == FOREST, section.from_code)
    work.array[5, 0] = 42          # a code that came from outside the program
    section.reclassify_at(centre(0, 5))
    check("a code nobody listed is given a class instead of a refusal",
          section.from_code == 42 and 42 in codes_of(section),
          (section.from_code, codes_of(section)))
    check("and the log says it", any("42" in line and "class" in line
                                     for line in logged), logged[-3:])

    # ------------------------------------------------------------ FROM, TO
    print()
    print("the panel says what changes into what: FROM chips, TO chips, banner")
    record = new_record("fromto")
    ft = open_correction(record, StyledLayer(record["source"], Paletted(None, 1, [
        Paletted.Class(WATER, "#1f78b4", "water"),
        Paletted.Class(CROPS, "#e6c229", "crops"),
        Paletted.Class(ROADS, "#444444", "roads"),
        Paletted.Class(FOREST, "#1b7f2a", "forest")])))
    check("FROM offers any class, then every class of the map",
          from_chips(ft) == ["any class", "water", "crops", "roads", "forest"],
          from_chips(ft))
    check("TO offers every class of the map, then +",
          [b.text() for b in ft._buttons]
          == ["water", "crops", "roads", "forest", "+"],
          [b.text() for b in ft._buttons])
    check("+ is not among the FROM chips: a class the map lacks has no pixels",
          "+" not in from_chips(ft))
    check("a new correction starts from any class",
          ft.from_code is None and ft._from_buttons[0].isChecked())
    ft.choose_class(FOREST)
    check("banner, any: 'FROM any class -> TO forest'",
          banner(ft) == ("FROM any class", "➜", "TO forest"), banner(ft))
    check("and no note about nothing to change", ft.same_note.isHidden())
    ft.choose_from(CROPS)
    check("banner, one class: 'FROM crops -> TO forest'",
          banner(ft) == ("FROM crops", "➜", "TO forest"), banner(ft))
    chosen = [b.text() for b in ft._from_buttons if b.isChecked()]
    check("the FROM chip of crops is the one checked", chosen == ["crops"],
          chosen)
    check("FROM chips are outlined, TO chips filled: the two rows differ",
          "palette(base)" in ft._from_buttons[1].styleSheet()
          and "palette(base)" not in ft._buttons[0].styleSheet(),
          (ft._from_buttons[1].styleSheet(), ft._buttons[0].styleSheet()))
    chip = ft._from_buttons[ft._from_buttons.index(
        [b for b in ft._from_buttons if b.isChecked()][0])]
    check("the FROM chip chosen is not filled: neutral, the class colour as "
          "its edge, outlined thick and bold, with a tick",
          "background-color:palette(base)" in chip.styleSheet()
          and "border-left:7px solid #e6c229" in chip.styleSheet()
          and "border:3px solid palette(text)" in chip.styleSheet()
          and "font-weight:bold" in chip.styleSheet()
          and chip.property("ticked") and not chip.icon().isNull(),
          chip.styleSheet())
    # a class added during the session is a chip like the others, a yellow
    # one included
    ft.classes().append({"code": 9, "name": "test", "colour": "#ffff00"})
    ft.rebuild_class_buttons()
    ft.choose_from(9)
    added = [b for b in ft._from_buttons if b.property("full_name") == "test"]
    others = [b for b in ft._from_buttons if b.property("full_name") in
              ("water", "roads")]
    check("an added class: its FROM chip, chosen, is neutral with its edge",
          added and added[0].isChecked()
          and "background-color:palette(base)" in added[0].styleSheet()
          and "border-left:7px solid #ffff00" in added[0].styleSheet(),
          added and added[0].styleSheet())
    check("and not chosen it is as the others are",
          all("border-left:6px solid" in b.styleSheet()
              and "background-color:palette(base)" in b.styleSheet()
              for b in others))
    ft.choose_from(None)
    anyc = ft._from_buttons[0]
    check("any class keeps its own look, chosen: dark grey, no tick",
          "background-color:#5a5a5a" in anyc.styleSheet()
          and not anyc.property("ticked"), anyc.styleSheet())
    ft.classes().pop()
    ft.rebuild_class_buttons()
    ft.choose_from(FOREST)
    check("banner, the same class on both sides says there is nothing to do",
          banner(ft)[1] == "=" and not ft.same_note.isHidden()
          and "nothing to change" in ft.same_note.text(),
          (banner(ft), ft.same_note.text()))

    # Past eight classes the chips stay in two columns over a wide range of
    # widths, so they are not built again when the panel is narrowed. Their
    # names were cut once, for the width they were born at, and then ran off
    # both ends of the chip.
    # Twelve classes and more take their columns from the room, four at
    # most, and 520 and 440 pixels both hold four: the narrowing keeps the
    # columns whatever the font, and only the names have to be cut again.
    narrowed = new_record("narrowed")
    long_names = ["permanently irrigated arable land under olive groves %d" % i
                  for i in range(10)]
    nw = open_correction(narrowed, StyledLayer(narrowed["source"], Paletted(None, 1, [
        Paletted.Class(i + 20, "#1f78b4", nm)
        for i, nm in enumerate(long_names)])))
    nw.chip_room = lambda: 520
    nw.rebuild_class_buttons()
    wide = list(nw._columns)
    nw.chip_room = lambda: 440
    nw.reflow()
    metrics = g["bold_metrics"](nw)
    cells = [(440 - 5 * (c - 1)) // c for c in nw._columns]
    too_long = [b.text() for buttons, cell in ((nw._from_buttons, cells[0]),
                                               (nw._buttons, cells[1]))
                for b in buttons
                if g["text_width"](metrics, b.text()) > cell - 12]
    check("narrowed with the same columns, every chip's name is cut to fit",
          wide == list(nw._columns) and not too_long
          and any(b.text().endswith("…") for b in nw._buttons),
          (wide, nw._columns, too_long))
    check("and the chip still knows the whole name",
          nw._buttons[0].property("full_name") == long_names[0])

    work = DISK[os.path.normcase(os.path.abspath(record["files"][0]))][0]
    every = np.ones((NY, NX), bool)
    ft.mask_of = lambda geom: (0, 0, every)             # the whole map
    said[:] = []
    ft.paint(Stroke())
    check("and a stroke refuses, the map unchanged",
          (work.array == THEMATIC).all() and any("same class" in s for s in said),
          said)

    print()
    print("FROM crops, TO forest: only crops change")
    ft.choose_from(CROPS)
    ft.paint(Stroke())
    expect = THEMATIC.copy()
    expect[THEMATIC == CROPS] = FOREST
    check("every crops pixel is forest, every other pixel as it was",
          (work.array == expect).all(), work.array.tolist())
    check("the tally keeps the pair as it always wrote it",
          "crops -> forest" in ft.pairs, list(ft.pairs))

    print()
    print("FROM any class, TO roads: everything but nodata")
    ft.choose_from(None)
    ft.choose_class(ROADS)
    ft.paint(Stroke())
    expect = np.where(THEMATIC == NODATA, NODATA, ROADS)
    check("every pixel is roads, the nodata hole kept",
          (work.array == expect).all(), work.array.tolist())
    check("the pair is still written 'every class', as older records have it",
          "every class -> roads" in ft.pairs, list(ft.pairs))
    check("and the tally shows it as any class",
          "any class ➜ roads" in ft.tally.text(), ft.tally.text())

    print()
    print("Ctrl+click sets FROM, Shift+click sets TO, through the brush itself")
    # The brush is built without its canvas: only the press is under test.
    Brush = REAL_BRUSH

    class Geometry:
        @staticmethod
        def fromPointXY(p): return p

    kept_geometry = g["QgsGeometry"]
    g["QgsGeometry"] = Geometry

    class Press:
        def __init__(self, mods): self._m = mods
        def button(self): return QtCore.Qt.MouseButton.LeftButton
        def modifiers(self): return self._m
        def pos(self): return QtCore.QPoint(5, 5)

    def brush_for(section, where):
        tool = Brush.__new__(Brush)
        tool.section, tool.points, tool.skipped = section, [], False
        tool.pressed = tool.dragged = False
        tool._map = lambda ev: where
        tool._to_layer = lambda geom: geom
        tool._redraw_round = lambda: None
        return tool

    record2 = new_record("clicks")
    ck = open_correction(record2, StyledLayer(record2["source"], Gray()))
    ck.choose_from(None)
    ck.choose_class(WATER)
    tool = brush_for(ck, centre(7, 5))                  # forest
    tool.canvasPressEvent(Press(QtCore.Qt.KeyboardModifier.ControlModifier))
    check("Ctrl+click on forest: FROM is forest, TO untouched",
          ck.from_code == FOREST and ck.current_code() == WATER,
          (ck.from_code, ck.current_code()))
    check("and the click did not start an outline", tool.skipped
          and not tool.pressed)
    tool = brush_for(ck, centre(2, 0))                  # crops
    tool.canvasPressEvent(Press(QtCore.Qt.KeyboardModifier.ShiftModifier))
    check("Shift+click on crops: TO is crops, FROM untouched",
          ck.current_code() == CROPS and ck.from_code == FOREST,
          (ck.from_code, ck.current_code()))
    check("and the click did not start an outline", tool.skipped
          and not tool.pressed)
    check("the banner follows the clicks",
          banner(ck) == ("FROM class 12", "➜", "TO class 3"), banner(ck))
    said[:] = []
    tool = brush_for(ck, centre(3, 2))                  # nodata
    tool.canvasPressEvent(Press(QtCore.Qt.KeyboardModifier.ShiftModifier))
    check("Shift+click on nodata keeps TO and says why",
          ck.current_code() == CROPS and any("nodata" in s for s in said), said)

    print()
    print("Annotate's Shift is untouched: the press still starts a stroke")
    annotate = g["AnnotationSection"](panel)
    check("Annotate has no Shift pick for the brush to call",
          not hasattr(annotate, "pick_into_at"))
    tool = brush_for(annotate, centre(1, 1))
    tool.canvasPressEvent(Press(QtCore.Qt.KeyboardModifier.ShiftModifier))
    check("Shift+press in Annotate begins an outline as before",
          tool.pressed and not tool.skipped, (tool.pressed, tool.skipped))
    g["QgsGeometry"] = kept_geometry

    # ---------------------------------------------------------- with a style
    print()
    print("a map with a paletted style: its names and colours are the chips")
    record = new_record("styled")
    style = Paletted(None, 1, [
        Paletted.Class(WATER, "#1f78b4", "water"),
        Paletted.Class(CROPS, "#e6c229", "crops"),
        Paletted.Class(ROADS, "#444444", "roads"),
        Paletted.Class(FOREST, "#1b7f2a", "forest"),
        Paletted.Class(NODATA, "#000000", "no data")])
    layer = StyledLayer(record["source"], style)
    saves = panel.campaign.saves
    section = open_correction(record, layer)
    check("the chips are the style's labels, in its order",
          chips(section) == ["water", "crops", "roads", "forest"],
          chips(section))
    by_code = {c["code"]: c for c in record.get("classes", [])}
    check("with the style's colours",
          [by_code.get(k, {}).get("colour") for k in (0, 3, 7, 12)]
          == ["#1f78b4", "#e6c229", "#444444", "#1b7f2a"],
          [by_code.get(k, {}).get("colour") for k in (0, 3, 7, 12)])
    check("the nodata entry of the style is not a class", NODATA not in by_code)
    check("and the classes were written into the manifest",
          panel.campaign.saves > saves, (saves, panel.campaign.saves))

    print()
    print("the copy is painted in the map's own colours")
    target = StyledLayer(record["files"][0], Gray())
    section.style(target)
    painted = target.renderer()
    entries = {c.value: (c.color.name(), c.label)
               for c in getattr(painted, "classes", lambda: [])()}
    check("one entry per class of the map",
          sorted(entries) == [0, 3, 7, 12], sorted(entries))
    check("forest is drawn in the forest green of the style",
          entries.get(12) == ("#1b7f2a", "forest"), entries.get(12))
    check("and no entry for the legend's codes", 1 not in entries
          and 2 not in entries)

    print()
    print("reopening keeps the classes, even when the style has changed")
    layer.setRenderer(Paletted(None, 1, [Paletted.Class(WATER, "#ff0000",
                                                        "lake")]))
    LOADED[layer.id()] = layer
    again = open_correction(record)
    check("the same chips as when it was made",
          chips(again) == ["water", "crops", "roads", "forest"], chips(again))
    check("and the same colours",
          [c["colour"] for c in again.record.get("classes", [])]
          == ["#1f78b4", "#e6c229", "#444444", "#1b7f2a"],
          [c["colour"] for c in again.record.get("classes", [])])
    LOADED.clear()

    print()
    print("a correction made by an earlier build has no classes of its own")
    record = new_record("older")
    record.pop("classes", None)
    LOADED[layer.id()] = StyledLayer(record["source"], style)
    saves = panel.campaign.saves
    old = open_correction(record)
    check("they are read from the map, through its style in the project",
          chips(old) == ["water", "crops", "roads", "forest"], chips(old))
    check("and written into its record, once",
          len(record.get("classes", [])) == 4
          and panel.campaign.saves == saves + 1,
          (len(record.get("classes", [])), panel.campaign.saves - saves))
    LOADED.clear()

    print()
    print("the style QGIS gives a colour table lists 256 entries, not classes")
    # A byte band with a colour table opens in QGIS with a Paletted style of
    # one entry per entry of the table, labelled with its own number. Taken
    # whole, it gave 255 chips, most of them black, for a map of four codes.
    record = new_record("table")
    table = [Paletted.Class(v, "#000000", str(v)) for v in range(256)]
    table[CROPS] = Paletted.Class(CROPS, "#e6c229", "crops")
    table[40] = Paletted.Class(40, "#33cccc", "salt flat")
    tabled = open_correction(record, StyledLayer(record["source"],
                                                 Paletted(None, 1, table)))
    got = [c["code"] for c in record.get("classes", [])]
    check("only the codes the map holds, and the one a person named",
          got == [0, 3, 7, 12, 40], got)
    # The number alone is the label QGIS gives every entry of a colour
    # table, not a name: those classes are named as a bare value is.
    check("with the names the style gives them, and none for an entry "
          "labelled with its own number",
          chips(tabled) == ["class 0", "crops", "class 7", "class 12",
                            "salt flat"], chips(tabled))

    print()
    print("a float map whose nodata is NaN: 'every class' spares the holes")
    record = new_record("floats")
    holes = THEMATIC.astype(np.float32)
    holes[THEMATIC == NODATA] = np.nan
    for path in (record["source"], record["files"][0]):
        DISK[os.path.normcase(os.path.abspath(path))][0] = Band(
            holes.copy(), "classes", float("nan"))
    floats = open_correction(record, StyledLayer(record["source"], Gray()))
    check("NaN is not a class",
          [c["code"] for c in record.get("classes", [])] == [0, 3, 7, 12],
          record.get("classes"))
    floats.choose_from(None)
    floats.choose_class(ROADS)
    box = np.ones((3, 4), bool)
    floats.mask_of = lambda geom: (0, 1, box)           # rows 1-3, cols 0-3
    floats.paint(Stroke())
    work = DISK[os.path.normcase(os.path.abspath(record["files"][0]))][0]
    check("the NaN pixels under the stroke are still NaN",
          bool(np.isnan(work.array[2:4, 3]).all()), work.array[1:4, 0:4].tolist())
    check("and the rest of the stroke became roads",
          work.array[1, 0] == ROADS and work.array[3, 0] == ROADS,
          work.array[1:4, 0:4].tolist())
    said[:] = []
    floats.reclassify_at(centre(3, 2))
    check("Ctrl and click on NaN says it is nodata",
          any("nodata" in s for s in said), said)

    print()
    print("+ adds a class the map does not hold yet, by its code")
    answers = {"int": (20, True), "text": ("salt marsh", True)}

    class Ask:
        @staticmethod
        def getInt(*a, **k): return answers["int"]
        @staticmethod
        def getText(*a, **k): return answers["text"]

    g["QInputDialog"] = Ask
    g["QMessageBox"].warning = staticmethod(lambda *a, **k: said.append(a[2]))
    plus = [b for b in again._buttons if b.text() == "+"]
    check("there is a + chip", len(plus) == 1)
    if plus and hasattr(again, "add_class"):
        plus[0].click()
        check("class 20 is in the record, named as typed",
              any(c["code"] == 20 and c["name"] == "salt marsh"
                  for c in again.record["classes"]), again.record["classes"])
        check("it is in hand", again.current_code() == 20, again.current_code())
        check("and the legend did not gain it",
              20 not in [c["code"] for c in panel.campaign.data["classes"]])
        answers["int"] = (NODATA, True)
        n = len(again.record["classes"])
        plus = [b for b in again._buttons if b.text() == "+"]
        plus[0].click()
        check("the nodata value is refused as a class",
              len(again.record["classes"]) == n and not again.class_of(NODATA))

    print()
    print("the Classes of the campaign do not reach a correction")
    before = [dict(c) for c in again.record.get("classes", [])]
    panel.campaign.data["classes"].append({"name": "salt", "code": 3,
                                           "colour": "#ffffff"})
    again.rebuild_class_buttons()
    check("a legend class with the same code changes nothing here",
          again.record.get("classes", []) == before and "salt" not in chips(again),
          chips(again))
    panel.campaign.data["classes"] = [dict(c) for c in LEGEND]

    print()
    print("Annotate still shows the legend")
    annotation = g["AnnotationSection"](panel)
    names = [b.text() for b in annotation._buttons if b.text() != "+"]
    check("its chips are the legend, {1, 2}", names == ["crust", "wet mud"],
          names)
    check("and it holds a legend code",
          annotation.current_code() in (1, 2), annotation.current_code())
finally:
    shutil.rmtree(folder, ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
