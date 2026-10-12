"""The thematic maps people really load, corrected in a real QGIS.

test_correct_typical walks the same maps through Correct with QGIS faked,
and the fakes give a layer whatever style the suite hands them. Here QGIS
gives it, as it does when the map is dragged into it: grey for a band with
nothing else, paletted from a colour table, from a .qml, from an attribute
table or a .tif.vat.dbf, pseudocolor from a .qml. The panel is the
program's own, on a real map canvas, with a real QgsRasterLayer of the map
in a real project; only the QGIS window around them is faked, and the
windows that ask are answered here.

For each map: a new correction, the classes window, three strokes drawn as
polygons on the map, one of them undone, Save, the classes window again
with a class renamed, Close, opened again, Close. Then:

  the classes window offered the class band, every code of the map and no
  nodata, with the names and colours QGIS shows the map in;
  the corrected map has the structure of the map, band for band, and a
  BigTIFF stays one;
  every pixel nobody painted is byte for byte the map's, and the record
  beside it marks exactly the pixels that changed;
  QGIS opens the corrected map paletted on the class band, with the classes
  of the correction, and a map of one band does so even without its .qml,
  from the file itself: the colour table, the category names and the
  attribute table follow the classes, the counts of the attribute table and
  the .tif.vat.dbf are those of the corrected map;
  the map and the files beside it are as they were, but for the .aux.xml of
  statistics QGIS itself leaves beside a map it showed in grey.

The cases can be narrowed by name on the command line. Needs QGIS itself,
its Python and its classes, and GDAL, which comes with it. tests/run.py
skips it where QGIS is missing and, with RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import struct
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.environ.get("RL_ROOT") or os.path.dirname(_HERE)
SRC = os.environ.get("RL_SRC", os.path.join(_ROOT, "dist", "rasterlabel.py"))
ONLY = sys.argv[1:]

from qgis.core import (Qgis, QgsApplication, QgsGeometry, QgsProject,
                       QgsRasterLayer, QgsRectangle)
from qgis.PyQt import QtWidgets
from qgis.gui import QgsMapCanvas
import qgis.utils
import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
app = QgsApplication([], False)
app.initQgis()
print("QGIS %s, GDAL %s" % (Qgis.QGIS_VERSION, gdal.__version__))

SAID = []


class Bar:
    def pushMessage(self, *a, **k):
        SAID.append(" ".join(str(x) for x in a))


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


iface = Iface()
qgis.utils.iface = iface
code = open(SRC, encoding="utf-8").read().replace("\nstart()\n", "\n")
g = {"__name__": "rasterlabel", "__file__": SRC}
exec(compile(code, SRC, "exec"), g)

ANSWERS = {}
UNEXPECTED = []


def run_dialog(d):
    name = type(d).__name__
    f = ANSWERS.pop(name, None)
    if f is None:
        UNEXPECTED.append(name)
        return 0
    return f(d)


g["run_dialog"] = run_dialog
BOXES = []


def _box(kind, answer):
    def f(*a, **k):
        BOXES.append((kind, str(a[2] if len(a) > 2 else "")))
        return answer
    return staticmethod(f)


QMB = QtWidgets.QMessageBox
QMB.warning = _box("warning", QMB.StandardButton.Cancel)
QMB.critical = _box("critical", QMB.StandardButton.Ok)
QMB.information = _box("information", QMB.StandardButton.Ok)
QMB.question = _box("question", QMB.StandardButton.Yes)

fails = []


def check(case, name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)[:600]) if not cond and detail != "" else ""))
    if not cond:
        fails.append("%s: %s" % (case, name))


# ----------------------------------------------------------------- the maps
NX, NY = 96, 72
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)
WKT = srs.ExportToWkt()
GT = (500000.0, 2.0, 0.0, 4100000.0, 0.0, -2.0)
rng = np.random.default_rng(7)


def class_array(codes, nodata=None, dtype=np.uint8):
    a = np.empty((NY, NX), dtype)
    # blocks of classes, so a stroke finds them where it expects
    for i, c in enumerate(codes):
        a[:, i * NX // len(codes):(i + 1) * NX // len(codes)] = c
    noise = rng.random((NY, NX)) < 0.15
    a[noise] = np.array(codes, dtype)[rng.integers(0, len(codes), noise.sum())]
    if nodata is not None:
        a[NY - 8:, NX - 10:] = nodata
    return a


def make(path, arrays, dtype=gdal.GDT_Byte, nodata=None, options=(),
         descriptions=None, driver="GTiff"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = len(arrays)
    if driver == "COG":
        mem = gdal.GetDriverByName("MEM").Create("", NX, NY, n, dtype)
        target = mem
    else:
        target = gdal.GetDriverByName("GTiff").Create(
            path, NX, NY, n, dtype, list(options))
    target.SetGeoTransform(GT)
    target.SetProjection(WKT)
    for b, a in enumerate(arrays, start=1):
        band = target.GetRasterBand(b)
        band.WriteArray(a)
        nd = nodata[b - 1] if isinstance(nodata, (list, tuple)) else nodata
        if nd is not None:
            band.SetNoDataValue(nd)
        if descriptions:
            band.SetDescription(descriptions[b - 1])
    if driver == "COG":
        out = gdal.GetDriverByName("COG").CreateCopy(path, mem, 0,
                                                     list(options))
        if out is None:
            raise IOError("GDAL could not write the COG %s" % path)
        out = None
        mem = None
    target = None


def qml(path, body):
    with open(os.path.splitext(path)[0] + ".qml", "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
                "<qgis version=\"3.36.0\" styleCategories=\"AllStyleCategories\">"
                "<pipe>%s</pipe><blendMode>0</blendMode></qgis>\n" % body)


def paletted_qml(path, band, classes, opacity="1"):
    qml(path, '<rasterrenderer type="paletted" band="%d" opacity="%s" '
              'alphaBand="-1" nodataColor=""><rasterTransparency/>'
              '<colorPalette>%s</colorPalette></rasterrenderer>'
        % (band, opacity, "".join(
            '<paletteEntry value="%d" color="%s" alpha="255" label="%s"/>'
            % (c, col, name) for c, col, name in classes)))


def pseudo_qml(path, band, classes, ramp_type):
    lo = min(c for c, _, _ in classes)
    hi = max(c for c, _, _ in classes)
    qml(path, '<rasterrenderer type="singlebandpseudocolor" band="%d" '
              'opacity="1" alphaBand="-1" classificationMin="%d" '
              'classificationMax="%d" nodataColor=""><rasterTransparency/>'
              '<rastershader><colorrampshader colorRampType="%s" '
              'classificationMode="1" clip="0" minimumValue="%d" '
              'maximumValue="%d">%s</colorrampshader></rastershader>'
              '</rasterrenderer>'
        % (band, lo, hi, ramp_type, lo, hi, "".join(
            '<item value="%d" color="%s" alpha="255" label="%s"/>'
            % (c, col, name) for c, col, name in classes)))


NAMED = [(1, "#1f78b4", "water"), (2, "#e6c229", "crops"),
         (3, "#444444", "roads"), (4, "#1b7f2a", "forest")]


def colour_table(entries):
    ct = gdal.ColorTable()
    for c, col, _ in entries:
        col = col.lstrip("#")
        ct.SetColorEntry(c, (int(col[0:2], 16), int(col[2:4], 16),
                             int(col[4:6], 16), 255))
    return ct


def add_rat(path, entries, band_no=1, with_colour=True, counts=None):
    ds = gdal.Open(path, gdal.GA_Update)
    rat = gdal.RasterAttributeTable()
    rat.CreateColumn("Value", gdal.GFT_Integer, gdal.GFU_MinMax)
    rat.CreateColumn("Count", gdal.GFT_Integer, gdal.GFU_PixelCount)
    rat.CreateColumn("Class_Name", gdal.GFT_String, gdal.GFU_Name)
    if with_colour:
        rat.CreateColumn("Red", gdal.GFT_Integer, gdal.GFU_Red)
        rat.CreateColumn("Green", gdal.GFT_Integer, gdal.GFU_Green)
        rat.CreateColumn("Blue", gdal.GFT_Integer, gdal.GFU_Blue)
    rat.SetRowCount(len(entries))
    for i, (c, col, name) in enumerate(entries):
        rat.SetValueAsInt(i, 0, c)
        rat.SetValueAsInt(i, 1, int((counts or {}).get(c, 0)))
        rat.SetValueAsString(i, 2, name)
        if with_colour:
            col = col.lstrip("#")
            rat.SetValueAsInt(i, 3, int(col[0:2], 16))
            rat.SetValueAsInt(i, 4, int(col[2:4], 16))
            rat.SetValueAsInt(i, 5, int(col[4:6], 16))
    try:
        rat.SetTableType(gdal.GRTT_THEMATIC)
    except Exception:
        pass
    ds.GetRasterBand(band_no).SetDefaultRAT(rat)
    ds = None


def add_vat(path, entries, counts):
    """An ArcGIS value attribute table, <map>.tif.vat.dbf."""
    drv = ogr.GetDriverByName("ESRI Shapefile")
    dbf = path + ".vat.dbf"
    ds = drv.CreateDataSource(dbf)
    lyr = ds.CreateLayer(os.path.basename(path) + ".vat", None, ogr.wkbNone)
    for name, kind in (("Value", ogr.OFTInteger), ("Count", ogr.OFTInteger),
                       ("ClassName", ogr.OFTString), ("Red", ogr.OFTInteger),
                       ("Green", ogr.OFTInteger), ("Blue", ogr.OFTInteger)):
        lyr.CreateField(ogr.FieldDefn(name, kind))
    for c, col, name in entries:
        f = ogr.Feature(lyr.GetLayerDefn())
        col = col.lstrip("#")
        f.SetField("Value", c)
        f.SetField("Count", int(counts.get(c, 0)))
        f.SetField("ClassName", name)
        f.SetField("Red", int(col[0:2], 16))
        f.SetField("Green", int(col[2:4], 16))
        f.SetField("Blue", int(col[4:6], 16))
        lyr.CreateFeature(f)
    ds = None
    return os.path.exists(dbf)


def counts_of(a, nodata=None):
    v, n = np.unique(a, return_counts=True)
    return {int(x): int(k) for x, k in zip(v, n) if x != nodata}


def build_cases(root):
    cases = []

    def case(name, **kw):
        if ONLY and not any(o in name for o in ONLY):
            return None
        path = os.path.join(root, name, "data", name + ".tif")
        kw.setdefault("band", 1)
        kw.setdefault("names", {})
        cases.append(dict(name=name, path=path, **kw))
        return path

    # (1) the plain output of a classifier, written with GDAL or rasterio
    p = case("c1_byte_plain", codes=[1, 2, 3, 4, 5])
    if p:
        make(p, [class_array([1, 2, 3, 4, 5])])
    p = case("c1_byte_plain_zero", codes=[0, 1, 2, 3])
    if p:
        make(p, [class_array([0, 1, 2, 3])], options=["COMPRESS=LZW"])

    # (2) a colour table inside, no .qml; and one with category names too
    p = case("c2_byte_ct", codes=[1, 2, 3, 4],
             colours={c: col for c, col, _ in NAMED},
             names={c: "class %d" % c for c in (1, 2, 3, 4)})
    if p:
        make(p, [class_array([1, 2, 3, 4])])
        ds = gdal.Open(p, gdal.GA_Update)
        ds.GetRasterBand(1).SetColorTable(colour_table(NAMED))
        ds = None
    p = case("c2_byte_ct_names", codes=[1, 2, 3, 4],
             colours={c: col for c, col, _ in NAMED},
             names={c: n for c, _, n in NAMED})
    if p:
        make(p, [class_array([1, 2, 3, 4])], nodata=0)
        ds = gdal.Open(p, gdal.GA_Update)
        ds.GetRasterBand(1).SetColorTable(colour_table(NAMED))
        ds.GetRasterBand(1).SetRasterCategoryNames(
            ["nodata", "water", "crops", "roads", "forest"])
        ds = None

    # (3) a .qml beside it: paletted, and pseudocolor exact and discrete
    p = case("c3_qml_paletted", codes=[1, 2, 3, 4],
             names={c: n for c, _, n in NAMED},
             colours={c: col for c, col, _ in NAMED})
    if p:
        make(p, [class_array([1, 2, 3, 4])], nodata=255)
        paletted_qml(p, 1, NAMED, "0.8")
    for kind in ("EXACT", "DISCRETE"):
        p = case("c3_qml_pseudo_%s" % kind.lower(), codes=[1, 2, 3, 4],
                 names={c: n for c, _, n in NAMED},
                 colours={c: col for c, col, _ in NAMED})
        if p:
            make(p, [class_array([1, 2, 3, 4])], nodata=255)
            pseudo_qml(p, 1, NAMED, kind)

    # (4) sixteen bits, high codes, three nodata values
    for nd in (0, 255, 65535):
        p = case("c4_uint16_nd%d" % nd, codes=[100, 2000, 65000],
                 nodata=nd)
        if p:
            make(p, [class_array([100, 2000, 65000], nd, np.uint16)],
                 dtype=gdal.GDT_UInt16, nodata=nd, options=["COMPRESS=DEFLATE",
                                                            "TILED=YES"])

    # (5) several bands, the class band not the first
    p = case("c5_multiband_byte", codes=[1, 2, 3, 4], band=3)
    if p:
        make(p, [rng.integers(0, 101, (NY, NX)).astype(np.uint8),
                 rng.integers(0, 256, (NY, NX)).astype(np.uint8),
                 class_array([1, 2, 3, 4], 0)], nodata=0,
             options=["COMPRESS=LZW", "INTERLEAVE=BAND"],
             descriptions=["probability", "entropy", "class"])
    p = case("c5_multiband_float", codes=[1, 2, 3], band=2)
    if p:
        make(p, [rng.random((NY, NX)).astype(np.float32),
                 class_array([1, 2, 3], -9999, np.float32),
                 rng.random((NY, NX)).astype(np.float32)],
             dtype=gdal.GDT_Float32, nodata=-9999,
             options=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES"],
             descriptions=["probability", "classification", "entropy"])
    p = case("c5_multiband_unnamed", codes=[1, 2, 3, 4], band=2)
    if p:
        make(p, [rng.integers(0, 101, (NY, NX)).astype(np.uint8),
                 class_array([1, 2, 3, 4]),
                 rng.integers(0, 256, (NY, NX)).astype(np.uint8)],
             options=["COMPRESS=LZW", "INTERLEAVE=PIXEL"])
        paletted_qml(p, 2, NAMED)
    # the probability drawn in a stretch: that style names no classes, and
    # the band named "class" is still the one offered
    p = case("c5_multiband_stretch_on_1", codes=[1, 2, 3, 4], band=2)
    if p:
        make(p, [rng.integers(0, 101, (NY, NX)).astype(np.uint8),
                 class_array([1, 2, 3, 4]),
                 rng.integers(0, 256, (NY, NX)).astype(np.uint8)],
             options=["COMPRESS=LZW"],
             descriptions=["probability", "class", "entropy"])
        pseudo_qml(p, 1, [(0, "#440154", "0"), (100, "#fde725", "100")],
                   "INTERPOLATED")

    p = case("c5_multiband_rat", codes=[1, 2, 3, 4], band=2, nodata=0,
             names={c: n for c, _, n in NAMED},
             colours={c: col for c, col, _ in NAMED})
    if p:
        a = class_array([1, 2, 3, 4], 0)
        make(p, [rng.integers(1, 101, (NY, NX)).astype(np.uint8), a,
                 rng.integers(1, 256, (NY, NX)).astype(np.uint8)], nodata=0,
             options=["COMPRESS=LZW"])
        add_rat(p, NAMED, band_no=2, counts=counts_of(a, 0))

    # (6) a raster attribute table with the class names, and an ArcGIS
    # .vat.dbf
    p = case("c6_rat", codes=[1, 2, 3, 4], names={c: n for c, _, n in NAMED},
             colours={c: col for c, col, _ in NAMED})
    if p:
        a = class_array([1, 2, 3, 4])
        make(p, [a], nodata=0)
        add_rat(p, NAMED, counts=counts_of(a, 0))
    p = case("c6_rat_nocolour", codes=[1, 2, 3, 4], rat_no_colour=True,
             names={c: n for c, _, n in NAMED})
    if p:
        a = class_array([1, 2, 3, 4])
        make(p, [a], nodata=0, options=["COMPRESS=LZW"])
        add_rat(p, NAMED, with_colour=False, counts=counts_of(a, 0))
    p = case("c6_vat_dbf", codes=[1, 2, 3, 4], names={c: n for c, _, n in NAMED},
             colours={c: col for c, col, _ in NAMED})
    if p:
        a = class_array([1, 2, 3, 4])
        make(p, [a], nodata=0)
        add_vat(p, NAMED, counts_of(a, 0))
    p = case("c6_rat_uint16", codes=[100, 2000, 65000], nodata=65535,
             names={100: "water", 2000: "crops", 65000: "forest"})
    if p:
        a = class_array([100, 2000, 65000], 65535, np.uint16)
        make(p, [a], dtype=gdal.GDT_UInt16, nodata=65535)
        add_rat(p, [(100, "#1f78b4", "water"), (2000, "#e6c229", "crops"),
                    (65000, "#1b7f2a", "forest")], counts=counts_of(a, 65535))

    # (7) BigTIFF, compressed and tiled; striped and uncompressed
    for comp in ("LZW", "DEFLATE"):
        p = case("c7_bigtiff_%s" % comp.lower(), codes=[1, 2, 3, 4])
        if p:
            make(p, [class_array([1, 2, 3, 4])], nodata=255,
                 options=["COMPRESS=%s" % comp, "TILED=YES", "BLOCKXSIZE=32",
                          "BLOCKYSIZE=32", "BIGTIFF=YES"])
    p = case("c7_striped_raw", codes=[1, 2, 3, 4])
    if p:
        make(p, [class_array([1, 2, 3, 4])], options=["BLOCKYSIZE=8"])

    # (8) a cloud optimised GeoTIFF
    p = case("c8_cog", codes=[1, 2, 3, 4], cog=True)
    if p:
        make(p, [class_array([1, 2, 3, 4], 0)], nodata=0, driver="COG",
             options=["COMPRESS=DEFLATE", "BLOCKSIZE=32", "OVERVIEWS=AUTO",
                      "OVERVIEW_RESAMPLING=MODE"])
    return cases


# ------------------------------------------------------------- inspection
def structure(path):
    ds = gdal.Open(path)
    out = {"size": (ds.RasterXSize, ds.RasterYSize), "count": ds.RasterCount,
           "gt": ds.GetGeoTransform(), "srs": ds.GetProjection(),
           "ims": {k: v for k, v in (ds.GetMetadata("IMAGE_STRUCTURE") or {})
                   .items() if k in ("COMPRESSION", "INTERLEAVE", "PREDICTOR")},
           "bands": []}
    for b in range(1, ds.RasterCount + 1):
        band = ds.GetRasterBand(b)
        out["bands"].append({"type": gdal.GetDataTypeName(band.DataType),
                             "nodata": band.GetNoDataValue(),
                             "desc": band.GetDescription(),
                             "block": tuple(band.GetBlockSize()),
                             "overviews": band.GetOverviewCount()})
    ds = None
    with open(path, "rb") as f:
        head = f.read(4)
    out["bigtiff"] = struct.unpack("<H", head[2:4])[0] == 43 \
        if head[:2] == b"II" else struct.unpack(">H", head[2:4])[0] == 43
    return out


def arrays(path):
    ds = gdal.Open(path)
    out = [ds.GetRasterBand(b).ReadAsArray() for b in range(1, ds.RasterCount + 1)]
    ds = None
    return out


def opened(path):
    layer = QgsRasterLayer(path, "probe")
    if not layer.isValid():
        return ("invalid", None, None)
    r = layer.renderer()
    kind = r.type()
    band = classes = None
    if kind == "paletted":
        band = r.inputBand() if hasattr(r, "inputBand") else r.band()
        classes = [(int(c.value), c.color.name(), c.label) for c in r.classes()]
    del layer
    return (kind, band, classes)


def files_of(folder):
    out = {}
    for here, _, names in os.walk(folder):
        for n in names:
            p = os.path.join(here, n)
            with open(p, "rb") as f:
                out[os.path.relpath(p, folder)] = f.read()
    return out


# -------------------------------------------------------------- the walk
def pixel_rect(col0, row0, col1, row1):
    """The rectangle covering pixels [col0, col1) x [row0, row1), shrunk a
    little so it takes exactly them."""
    x0 = GT[0] + col0 * GT[1] + 0.01
    x1 = GT[0] + col1 * GT[1] - 0.01
    y0 = GT[3] + row0 * GT[5] - 0.01
    y1 = GT[3] + row1 * GT[5] + 0.01
    return QgsGeometry.fromRect(QgsRectangle(x0, y1, x1, y0))


def walk(c, root):
    name = c["name"]
    print()
    print(name)
    src = c["path"]
    folder = os.path.join(root, name, "correction")
    # QGIS leaves an .aux.xml of statistics beside a map it showed in grey
    # or in colour, when the layer goes: opened and closed once first, so
    # what it writes is in the picture before Correct comes near the map.
    probe = QgsRasterLayer(src, "first look")
    QgsProject.instance().addMapLayer(probe)
    QgsProject.instance().removeAllMapLayers()
    app.processEvents()
    data_before = files_of(os.path.dirname(src))
    src_struct = structure(src)
    src_arrays = arrays(src)
    band_no = c["band"]
    QgsProject.instance().removeAllMapLayers()
    layer = QgsRasterLayer(src, name)
    check(name, "the source loads in QGIS", layer.isValid())
    src_kind = layer.renderer().type()
    print("  source opens as %s" % src_kind)
    QgsProject.instance().addMapLayer(layer)
    panel = g["Panel"]()
    seen = {}

    def new_campaign(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText("fix " + name)
        d.raster.setCurrentIndex(d.raster.findData(layer.id()))
        d.fill_bands()
        seen["default_band"] = d.band.currentData()
        d.band.setCurrentIndex(d.band.findData(band_no))
        d.folder.setText(folder)
        d.operator.setText("ann")
        return 1

    def confirm(d):
        seen["rows"] = [(r["value"].value(), r["swatch"].property("colour"),
                         r["name"].text(), r["origin"].text()) for r in d.rows]
        d.add_blank()
        d.rows[-1]["name"].setText("burnt area")
        seen["added"] = d.rows[-1]["value"].value()
        seen["complaints"] = d.complaints()
        d.accept()
        return 1 if not seen["complaints"] else 0

    ANSWERS["OpenCorrection"] = new_campaign
    ANSWERS["ConfirmClasses"] = confirm
    panel.new_correction_campaign()
    section = panel.section
    check(name, "Correct opened on the new correction",
          type(section).__name__ == "CorrectionSection",
          (type(section).__name__, BOXES[-3:], UNEXPECTED, SAID[-3:]))
    if type(section).__name__ != "CorrectionSection":
        return
    check(name, "the window offered the class band",
          seen["default_band"] == band_no, (seen["default_band"], band_no))
    rows = seen["rows"]
    print("  classes window: %s" % rows)
    codes = [r[0] for r in rows]
    check(name, "the classes window lists every code of the map",
          set(c["codes"]) <= set(codes) and not seen["complaints"],
          (codes, seen["complaints"]))
    for code_, want in c["names"].items():
        got = [r[2] for r in rows if r[0] == code_]
        check(name, "class %d is named %r in the window" % (code_, want),
              got == [want], got)
    for code_, want in c.get("colours", {}).items():
        got = [r[1] for r in rows if r[0] == code_]
        check(name, "class %d is coloured %s in the window" % (code_, want),
              got == [want.lower()], got)
    nodata = c.get("nodata")
    if nodata is not None:
        check(name, "nodata is not a class", nodata not in codes, codes)

    copy = section.path
    book = panel.correction
    manifest = book.manifest_path
    added = seen["added"]
    cl = c["codes"]
    # stroke 1: any class into the added one; undone
    w = NX // len(cl)
    section.choose_from(None)
    section.choose_class(added)
    section.paint(pixel_rect(2, 2, 12, 12))
    after_first = section.values.copy()
    section.undo()
    # stroke 2: from the second class into the first, over its column
    section.choose_from(cl[1])
    section.choose_class(cl[0])
    section.paint(pixel_rect(w, 10, 2 * w, 30))
    # stroke 3: any class into the added class, kept
    section.choose_from(None)
    section.choose_class(added)
    section.paint(pixel_rect(4, 40, 20, 50))
    section.save()
    check(name, "three strokes counted, one undone",
          section.operations == 3, section.operations)
    check(name, "the first stroke did change something",
          not np.array_equal(after_first, src_arrays[band_no - 1]))
    # the classes window again: rename the first class
    def again(d):
        for r in d.rows:
            if r["value"].value() == cl[0]:
                r["name"].setText("renamed %d" % cl[0])
        d.accept()
        return 1
    ANSWERS["ConfirmClasses"] = again
    panel.correction_classes()
    panel.close_correction()
    check(name, "closed: no correction open", panel.correction is None)
    check(name, "the copy is no longer in the project",
          not any(os.path.normcase(l.source().split("|")[0])
                  == os.path.normcase(copy)
                  for l in QgsProject.instance().mapLayers().values()))

    # reopen
    book = panel.read_correction(manifest)
    check(name, "it reads again", book is not None, BOXES[-3:])
    panel.start_correction(book)
    panel.show_correction()
    section = panel.section
    check(name, "and Correct opens on it again",
          type(section).__name__ == "CorrectionSection")
    if type(section).__name__ == "CorrectionSection":
        check(name, "with its classes as confirmed",
              [(x["code"], x["name"]) for x in section.classes()]
              == [(x["code"], x["name"]) for x in book.data["classes"]])
    panel.close_correction()
    panel.close()
    panel.deleteLater()
    QgsProject.instance().removeAllMapLayers()
    app.processEvents()

    classes = book.data["classes"]
    print("  manifest classes: %s" % [(x["code"], x["name"]) for x in classes])
    check(name, "the renamed class is in the manifest",
          any(x["code"] == cl[0] and x["name"] == "renamed %d" % cl[0]
              for x in classes))

    # ------------------------------------------------ the files after
    after = structure(copy)
    for k in ("size", "count", "gt", "srs", "ims", "bigtiff"):
        check(name, "the copy has the %s of the source" % k,
              after[k] == src_struct[k], (src_struct[k], after[k]))
    for b, (x, y) in enumerate(zip(src_struct["bands"], after["bands"]),
                               start=1):
        for k in ("type", "nodata", "desc", "block"):
            same = (x[k] == y[k]) or (k == "nodata" and x[k] != x[k]
                                      and y[k] != y[k])
            check(name, "band %d keeps its %s" % (b, k), same, (x[k], y[k]))
        if x["overviews"] != y["overviews"]:
            print("  note: band %d had %d overviews, the copy %d"
                  % (b, x["overviews"], y["overviews"]))
    now_arrays = arrays(copy)
    for b in range(len(src_arrays)):
        if b + 1 == band_no:
            continue
        check(name, "band %d is byte for byte the source's" % (b + 1),
              now_arrays[b].tobytes() == src_arrays[b].tobytes())
    changes = os.path.join(os.path.dirname(copy),
                           book.data.get("changes") or "")
    check(name, "the sidecar is named in the manifest and is there",
          os.path.exists(changes), changes)
    marks = arrays(changes)[0].astype(bool)
    cls_before = src_arrays[band_no - 1]
    cls_after = now_arrays[band_no - 1]
    diff = cls_before != cls_after
    if cls_before.dtype.kind == "f":
        diff &= ~(np.isnan(cls_before) & np.isnan(cls_after))
    check(name, "untouched pixels of the class band are the source's",
          cls_after[~marks].tobytes() == cls_before[~marks].tobytes())
    check(name, "the sidecar marks exactly the changed pixels",
          np.array_equal(marks, diff), (int(marks.sum()), int(diff.sum())))
    check(name, "the undone stroke left nothing",
          not marks[2:12, 2:12].any() or (marks[2:12, 2:12] & ~diff[2:12, 2:12]).sum() == 0)
    check(name, "the kept strokes wrote their classes",
          set(np.unique(cls_after[marks]).astype(int).tolist())
          <= {cl[0], added}, np.unique(cls_after[marks]))
    if nodata is not None:
        check(name, "nodata pixels untouched",
              ((cls_before == nodata) == (cls_after == nodata)).all())
    kind, band, pal = opened(copy)
    want = [(x["code"], x["colour"].lower(), x["name"]) for x in classes]
    check(name, "QGIS opens the corrected map paletted on the class band",
          (kind, band) == ("paletted", band_no), (kind, band))
    check(name, "with the classes of the correction", pal == want, (pal, want))
    data_after = files_of(os.path.dirname(src))
    # QGIS itself leaves the statistics it computed for a grey style in an
    # .aux.xml when the layer goes: that one is not the program's doing.
    for k in list(data_after):
        if k not in data_before and k.endswith(".aux.xml") and all(
                l.strip().startswith(("<PAM", "</PAM", "<Metadata",
                                      "</Metadata", '<MDI key="STATISTICS_'))
                or not l.strip()
                for l in data_after[k].decode("utf-8", "replace").splitlines()):
            del data_after[k]
    check(name, "the source folder is byte for byte as it was",
          data_after == data_before,
          sorted(set(data_after) ^ set(data_before))
          or [k for k in data_after if data_after[k] != data_before.get(k)])
    # without its .qml
    style = os.path.splitext(copy)[0] + ".qml"
    if os.path.exists(style):
        os.replace(style, style + ".off")
        kind2, band2, pal2 = opened(copy)
        os.replace(style + ".off", style)
        ok_names = None
        if pal2:
            ok_names = [p for p in pal2 if p[0] in [x["code"] for x in classes]]
        print("  without its .qml QGIS opens it as %s on band %s, %s"
              % (kind2, band2, (ok_names or [])[:6]))
        # A band wider than a byte is given no colour table it did not come
        # with: without its .qml it opens in grey, as the map itself does.
        if src_struct["count"] == 1 and (src_kind == "paletted" or
                                         src_struct["bands"][0]["type"]
                                         == "Byte"):
            check(name, "without its .qml it still opens in the classes of "
                  "the correction, from the file itself",
                  kind2 == "paletted" and (
                      ok_names == want if not c.get("rat_no_colour") else
                      [(x[0], x[2]) for x in ok_names or []]
                      == [(x[0], x[2]) for x in want]), (kind2, ok_names))
    ds = gdal.Open(copy)
    ds.GetGeoTransform()            # the .aux.xml is read from here on
    names = list(ds.GetRasterBand(band_no).GetCategoryNames() or [])
    ds = None
    check(name, "the category names of the class band are the correction's",
          all(len(names) > x["code"] and names[x["code"]] == x["name"]
              for x in classes), names[:8])
    # the attribute tables
    real = {x["code"]: x for x in classes}
    counts_now = counts_of(cls_after, nodata)
    src_rat = g["attribute_table"](src, band_no)
    if src_rat is not None:
        cp = g["attribute_table"](copy, band_no)
        got = g["classes_of_table"](cp) if cp else {}
        check(name, "the copy has an attribute table, as its source",
              cp is not None)
        check(name, "whose names are the correction's",
              {k: v["name"] for k, v in got.items() if k in real}
              == {k: v["name"] for k, v in real.items()},
              (got, real))
        roles = g["table_roles"](cp) if cp else {}
        if cp and roles.get("count") is not None:
            have = {}
            for row in cp["rows"]:
                have[int(row[roles["value"]])] = int(row[roles["count"]])
            check(name, "and whose counts are the corrected map's",
                  all(have.get(k, 0) == n for k, n in counts_now.items()),
                  (have, counts_now))
        if cp and roles.get("red") is not None and not roles.get("by_name"):
            check(name, "and whose colours are the correction's",
                  {k: v["colour"] for k, v in got.items() if k in real}
                  == {k: v["colour"].lower() for k, v in real.items()},
                  got)
    if os.path.exists(src + ".vat.dbf"):
        vt = g["table_of_vat"](copy)
        check(name, "the copy has its own .vat.dbf", vt is not None)
        if vt:
            got = g["classes_of_table"](vt)
            check(name, "with the correction's names and colours",
                  {k: (v["name"], v["colour"]) for k, v in got.items()}
                  == {k: (v["name"], v["colour"].lower())
                      for k, v in real.items()}, (got, real))
            roles = g["table_roles"](vt)
            have = {int(r[roles["value"]]): int(r[roles["count"]])
                    for r in vt["rows"]}
            check(name, "and the corrected map's counts",
                  all(have.get(k, 0) == n for k, n in counts_now.items()),
                  (have, counts_now))
    print("  files: %s" % sorted(os.listdir(os.path.dirname(copy))))


root = tempfile.mkdtemp(prefix="rl_e2e_")
try:
    for c in build_cases(root):
        try:
            walk(c, root)
        except Exception:
            traceback.print_exc()
            fails.append("%s: raised" % c["name"])
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
if UNEXPECTED:
    print("unexpected dialogs: %s" % UNEXPECTED)
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.stdout.flush()
os._exit(1 if fails else 0)
