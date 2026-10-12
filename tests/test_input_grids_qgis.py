"""Rasters that are not a north-up GeoTIFF in metres, in a real QGIS.

The program grew up on orthophotos: a GeoTIFF, a coordinate system in
metres, a grid that runs north-up, square pixels of a few centimetres. Here
is what else people load, each with what went wrong on it:

  a picture with no georeference, a PNG or a JPEG: QGIS draws it at y 0 to
  minus the number of rows, and GDAL answers a grid with y going up. Every
  stroke of Correct fell "outside the map", the pixel under the cursor was
  never found, the record of changes was drawn beside the map;
  a map written north-down, pixel height positive: every stroke of Correct
  fell "outside the map", and a click just off the map read its edge;
  a map on a rotated grid: Correct changed pixels beside the stroke and
  logged it as right. It is refused now, new or already made, and New
  campaign says what a rotated grid does to frames;
  no coordinate system at all: every area and length NaN, boxes never too
  small, Cutouts' ruler NaN;
  a .prj beside a picture with a world file, which GDAL does not read for
  those formats, and a system set on the layer in QGIS by hand: the campaign
  and the corrected copy did not carry them;
  250 m, 30 m and 2 mm pixels: the radius and frame side boxes were made for
  5 cm, and locked, clamped or jumped a hundred pixels a click;
  pixels that are not square on the ground, and a photo stored turned by
  its EXIF orientation: nothing said so.

Every raster is made here. The panel is the program's own, on a real map
canvas, with real QgsRasterLayers in a real project; only the QGIS window
around them is faked, and the windows that ask are answered here. Needs QGIS
itself; tests/run.py skips it where QGIS is missing and, with
RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import math
import os
import shutil
import struct
import sys
import tempfile
import traceback
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# the settings this writes (recent corrections, the operator) go to a
# profile of its own, never to the one of whoever runs it
_PROFILE = tempfile.mkdtemp(prefix="rl_grids_profile_")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = _PROFILE
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.environ.get("RL_ROOT") or os.path.dirname(_HERE)
SRC = os.environ.get("RL_SRC", os.path.join(_ROOT, "dist", "rasterlabel.py"))

from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem,
                       QgsGeometry, QgsPointXY, QgsProject, QgsRasterLayer,
                       QgsRectangle)
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QSettings
from qgis.gui import QgsMapCanvas
import qgis.utils
import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()
# Before the application: QgsSettings of a standalone QGIS go to the
# registry of the machine otherwise.
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                  _PROFILE)
app = QgsApplication([], False)
app.initQgis()
print("QGIS %s, GDAL %s" % (Qgis.QGIS_VERSION, gdal.__version__))

SAID = []


class Bar:
    def pushMessage(self, *a, **k):
        SAID.append(" ".join(str(x) for x in a))

    def pushWidget(self, *a, **k):
        pass

    def popWidget(self, *a, **k):
        pass

    def clearWidgets(self, *a, **k):
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
    def activeLayer(self): return None


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


# ----------------------------------------------------------------- rasters
UTM = osr.SpatialReference()
UTM.ImportFromEPSG(32633)
WKT = UTM.ExportToWkt()
NX, NY = 200, 160


def classes_array(nx=NX, ny=NY):
    """Four classes in vertical bands, 1 to 4."""
    a = np.empty((ny, nx), np.uint8)
    for i in range(4):
        a[:, i * nx // 4:(i + 1) * nx // 4] = i + 1
    return a


def write(path, arrays, gt=None, wkt=None, driver="GTiff", dtype=gdal.GDT_Byte,
          table=False):
    """A raster made in memory and copied out, so PNG and JPEG are made the
    way their drivers allow. gt None: no georeference at all."""
    ny, nx = arrays[0].shape
    mem = gdal.GetDriverByName("MEM").Create("", nx, ny, len(arrays), dtype)
    if gt is not None:
        mem.SetGeoTransform(gt)
    if wkt:
        mem.SetProjection(wkt)
    for b, a in enumerate(arrays, start=1):
        mem.GetRasterBand(b).WriteArray(a)
    if table:
        ct = gdal.ColorTable()
        for c, rgb in enumerate([(0, 0, 0), (31, 120, 180), (230, 194, 41),
                                 (68, 68, 68), (27, 127, 42)]):
            ct.SetColorEntry(c, rgb + (255,))
        mem.GetRasterBand(1).SetColorTable(ct)
    out = gdal.GetDriverByName(driver).CreateCopy(path, mem, 0)
    out = None
    mem = None
    # a georeference GDAL keeps beside a PNG is not what this is about
    for leftover in (path + ".aux.xml",):
        if gt is None and os.path.exists(leftover):
            os.remove(leftover)
    return path


def world_file(path, ext, gt):
    with open(os.path.splitext(path)[0] + ext, "w") as f:
        f.write("%.10f\n%.10f\n%.10f\n%.10f\n%.10f\n%.10f\n"
                % (gt[1], gt[4], gt[2], gt[5], gt[0] + gt[1] / 2.0,
                   gt[3] + gt[5] / 2.0))


def exif_turned(path, orientation=6):
    """The JPEG at path, with an EXIF block saying it is stored turned: the
    one tag a camera writes when it is held upright, put in by hand so it
    does not depend on the GDAL of the day being able to write EXIF."""
    with open(path, "rb") as f:
        data = f.read()
    assert data[:2] == b"\xff\xd8"
    ifd = struct.pack("<H", 1) + struct.pack("<HHIHH", 0x0112, 3, 1,
                                             orientation, 0) \
        + struct.pack("<I", 0)
    tiff = b"II*\x00" + struct.pack("<I", 8) + ifd
    body = b"Exif\x00\x00" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body
    with open(path, "wb") as f:
        f.write(data[:2] + app1 + data[2:])


def layer_of(path, name=None):
    layer = QgsRasterLayer(path, name or os.path.basename(path))
    QgsProject.instance().addMapLayer(layer)
    return layer


def drop_layers():
    QgsProject.instance().removeAllMapLayers()
    app.processEvents()


def gt_of(path):
    ds = gdal.Open(path)
    gt = ds.GetGeoTransform(can_return_null=True)
    ds = None
    return gt


def extent_of(path):
    layer = QgsRasterLayer(path, "probe")
    e = layer.extent()
    out = (round(e.xMinimum(), 6), round(e.yMinimum(), 6),
           round(e.xMaximum(), 6), round(e.yMaximum(), 6))
    del layer
    return out


def array_of(path, band=1):
    ds = gdal.Open(path)
    a = ds.GetRasterBand(band).ReadAsArray()
    ds = None
    return a


def rect_over(gt, col0, row0, col1, row1):
    """The polygon over pixels [col0, col1) x [row0, row1) of a north-up or
    north-down grid, shrunk a little so it takes exactly them."""
    xs = [gt[0] + col0 * gt[1], gt[0] + col1 * gt[1]]
    ys = [gt[3] + row0 * gt[5], gt[3] + row1 * gt[5]]
    sx, sy = 0.01 * abs(gt[1]), 0.01 * abs(gt[5])
    return QgsGeometry.fromRect(QgsRectangle(min(xs) + sx, min(ys) + sy,
                                             max(xs) - sx, max(ys) - sy))


# ------------------------------------------------------------ the walks
def new_panel():
    panel = g["Panel"]()
    return panel


def close_panel(panel):
    try:
        if panel.correction is not None:
            panel.close_correction()
        elif panel.section is not None:
            panel.close_module()
    except Exception:
        traceback.print_exc()
    panel.close()
    panel.deleteLater()
    drop_layers()


def new_correction(panel, layer, folder, seen):
    def opened(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText("fix " + layer.name())
        d.raster.setCurrentIndex(d.raster.findData(layer.id()))
        d.fill_bands()
        d.band.setCurrentIndex(d.band.findData(1))
        d.folder.setText(folder)
        d.operator.setText("ann")
        return 1

    def confirm(d):
        d.add_blank()
        d.rows[-1]["name"].setText("burnt area")
        seen["added"] = d.rows[-1]["value"].value()
        d.accept()
        return 1

    ANSWERS["OpenCorrection"] = opened
    ANSWERS["ConfirmClasses"] = confirm
    del BOXES[:]
    panel.new_correction_campaign()
    ANSWERS.pop("OpenCorrection", None)
    ANSWERS.pop("ConfirmClasses", None)
    section = panel.section
    if type(section).__name__ != "CorrectionSection":
        return None
    return section


def new_campaign(panel, layer, folder, seen, tiled=None):
    def answer(d):
        d.raster.setCurrentIndex(d.raster.findData(layer.id()))
        d.show_grid()
        d.name.setText("grid " + layer.name())
        d.folder.setText(folder)
        d.folder_by_hand = True
        if tiled is not None:
            d.tiled.setChecked(tiled)
            d.free.setChecked(not tiled)
        seen["info"] = d.info.text()
        d.check()
        return 1 if d.result() == QtWidgets.QDialog.DialogCode.Accepted else 0

    ANSWERS["NewCampaign"] = answer
    del BOXES[:]
    panel.new_campaign()
    ANSWERS.pop("NewCampaign", None)
    return panel.campaign


def info_of(layer):
    """What New campaign says about a raster, without making a campaign."""
    d = g["NewCampaign"](None, [layer])
    d.raster.setCurrentIndex(d.raster.findData(layer.id()))
    d.show_grid()
    text = d.info.text()
    d.deleteLater()
    return text


# 1 ------------------------------------------------- no georeference
def picture_in_correct(root):
    case = "picture"
    print("\na class map saved as a PNG with no georeference, in Correct")
    path = write(os.path.join(root, "data", "pal_nogeo.png"),
                 [classes_array()], driver="PNG", table=True)
    check(case, "the PNG has no georeference", gt_of(path) is None,
          gt_of(path))
    layer = layer_of(path)
    check(case, "QGIS draws it at y 0 to minus its rows",
          extent_of(path) == (0.0, -NY, NX, 0.0), extent_of(path))
    panel = new_panel()
    seen = {}
    try:
        section = new_correction(panel, layer,
                                 os.path.join(root, "fix_picture"), seen)
        check(case, "Correct opened on it", section is not None,
              (BOXES[-2:], UNEXPECTED))
        if section is None:
            return
        before = section.values.copy()
        target = seen["added"]
        section.choose_from(None)
        section.choose_class(target)
        del SAID[:]
        # columns 25 to 40, rows 55 to 70, in the coordinates QGIS gives
        # the picture: y is minus the row
        section.paint(QgsGeometry.fromRect(QgsRectangle(25.01, -69.99,
                                                        39.99, -55.01)))
        changed = before != section.values
        want = np.zeros_like(changed)
        want[55:70, 25:40] = True
        check(case, "a stroke changes the pixels under it, 225 of them",
              np.array_equal(changed, want),
              (int(changed.sum()), SAID[-2:]))
        check(case, "and is not said to fall outside the map",
              not any("outside the map" in s for s in SAID), SAID[-3:])
        code = section.code_at(QgsPointXY(5.5, -5.5), "nothing")
        check(case, "the class under the cursor is found",
              code == int(before[5, 5]), code)
        section.save()
        copy = section.path
        record = section.changes_path
        book = panel.correction
        panel.close_correction()
        app.processEvents()
        check(case, "the record of changes is drawn where the copy is",
              extent_of(record) == extent_of(copy),
              (extent_of(record), extent_of(copy)))
        marks = array_of(record).astype(bool)
        check(case, "and marks the pixels the stroke changed",
              np.array_equal(marks, want), int(marks.sum()))

        # A record an earlier build wrote on GDAL's default grid
        print("  the record of an earlier build, on GDAL's default grid")
        ds = gdal.Open(record, gdal.GA_Update)
        ds.SetGeoTransform((0.0, 1.0, 0.0, 0.0, 0.0, 1.0))
        ds = None
        check(case, "(set up: QGIS draws that record beside the copy)",
              extent_of(record) != extent_of(copy), extent_of(record))
        found = [str(f) for f in g["about_the_correction"](book)]
        check(case, "Check says the record is not where the copy is",
              any("not drawn where the copy is" in f for f in found),
              [f for f in found if "changes" in f])
        again = panel.read_correction(book.manifest_path)
        panel.start_correction(again)
        panel.show_correction()
        check(case, "Correct opens it again",
              type(panel.section).__name__ == "CorrectionSection",
              BOXES[-2:])
        panel.close_correction()
        app.processEvents()
        check(case, "and puts the record back on the copy",
              extent_of(record) == extent_of(copy),
              (extent_of(record), extent_of(copy)))
    finally:
        close_panel(panel)


# 2 ----------------------------------------------------------- north-down
def north_down_in_correct(root):
    case = "north-down"
    print("\na class map written north-down, in Correct")
    gt = (500000.0, 0.25, 0.0, 4100000.0, 0.0, 0.25)
    path = write(os.path.join(root, "data", "map_northdown.tif"),
                 [classes_array(96, 72)], gt=gt, wkt=WKT)
    layer = layer_of(path)
    panel = new_panel()
    seen = {}
    try:
        section = new_correction(panel, layer,
                                 os.path.join(root, "fix_northdown"), seen)
        check(case, "Correct opened on it", section is not None,
              (BOXES[-2:], UNEXPECTED))
        if section is None:
            return
        before = section.values.copy()
        section.choose_from(None)
        section.choose_class(seen["added"])
        del SAID[:]
        section.paint(rect_over(gt, 20, 10, 32, 22))
        changed = before != section.values
        want = np.zeros_like(changed)
        want[10:22, 20:32] = True
        check(case, "a stroke changes the 144 pixels under it",
              np.array_equal(changed, want),
              (int(changed.sum()), SAID[-2:]))
        # a point a little before the first row, which on this map is the
        # bottom one: off the map
        outside = section.code_at(QgsPointXY(gt[0] + 5.5 * gt[1],
                                             gt[3] - 0.3 * gt[5]), "nothing")
        check(case, "a click just off the map finds no class",
              outside is None, outside)
        inside = section.code_at(QgsPointXY(gt[0] + 5.5 * gt[1],
                                            gt[3] + 0.5 * gt[5]), "nothing")
        check(case, "a click on the first row finds its class",
              inside == int(before[0, 5]), inside)
    finally:
        close_panel(panel)


# 3 ---------------------------------------------------------------- rotated
def rotated_in_correct(root):
    case = "rotated"
    print("\na class map on a rotated grid, in Correct")
    c, s = math.cos(math.radians(20)), math.sin(math.radians(20))
    gt = (500000.0, 0.25 * c, 0.25 * s, 4100000.0, 0.25 * s, -0.25 * c)
    path = write(os.path.join(root, "data", "map_rotated.tif"),
                 [classes_array(96, 72)], gt=gt, wkt=WKT)
    layer = layer_of(path)
    panel = new_panel()
    seen = {}
    folder = os.path.join(root, "fix_rotated")
    try:
        section = new_correction(panel, layer, folder, seen)
        check(case, "a new correction is refused", section is None,
              type(section).__name__)
        check(case, "saying the grid is rotated and what to do",
              any("rotated" in t and "north-up" in t for _, t in BOXES),
              BOXES[-2:])
        check(case, "and nothing is written",
              not os.path.exists(os.path.join(folder, "correction.json")))
        # one made before Correct refused them
        book = g["CorrectionCampaign"].create(
            os.path.join(root, "fix_rotated_old"), "old", layer, 1,
            [dict(code=k, name="class %d" % k, colour="#336699")
             for k in (1, 2, 3, 4)], "ann")
        raised = None
        try:
            made = g["CorrectionSection"](panel, book.data, book=book)
            made.deleteLater()
        except Exception as err:
            raised = str(err)
        check(case, "one made before does not open either",
              raised is not None and "rotated" in raised, raised)
    finally:
        close_panel(panel)
    info = info_of(layer_of(path))
    check(case, "New campaign says a rotated grid is not its pixels",
          "rotated" in info, info)
    drop_layers()


# 4 ---------------------------------------------- the system set in QGIS
def system_set_in_qgis(root):
    case = "layer system"
    print("\na map whose system is set on the layer in QGIS, in Correct")
    gt = (500000.0, 0.5, 0.0, 4100000.0, 0.0, -0.5)
    path = write(os.path.join(root, "data", "wf_map.png"),
                 [classes_array(96, 72)], driver="PNG", table=True)
    world_file(path, ".pgw", gt)
    layer = layer_of(path)
    layer.setCrs(QgsCoordinateReferenceSystem("EPSG:32633"))
    panel = new_panel()
    seen = {}
    try:
        section = new_correction(panel, layer,
                                 os.path.join(root, "fix_layer_crs"), seen)
        check(case, "Correct opened on it", section is not None,
              (BOXES[-2:], UNEXPECTED))
        if section is None:
            return
        copy = section.path
        panel.close_correction()
        ds = gdal.Open(copy)
        srs = ds.GetSpatialRef()
        ds = None
        code_ = None
        if srs is not None:
            srs.AutoIdentifyEPSG()
            code_ = srs.GetAuthorityCode(None)
        check(case, "the corrected copy carries the system of the layer",
              code_ == "32633", code_)
    finally:
        close_panel(panel)


# 5 ---------------------------------------------- a .prj beside a picture
def prj_beside_picture(root):
    case = ".prj"
    print("\na PNG with a world file and a .prj, in New campaign")
    gt = (500000.0, 0.1, 0.0, 4100000.0, 0.0, -0.1)
    path = write(os.path.join(root, "data", "wf_png.png"),
                 [classes_array(), classes_array(), classes_array()],
                 driver="PNG")
    world_file(path, ".pgw", gt)
    esri = UTM.Clone()
    esri.MorphToESRI()
    with open(os.path.splitext(path)[0] + ".prj", "w") as f:
        f.write(esri.ExportToWkt())
    layer = layer_of(path)
    check(case, "(QGIS does not apply it by itself)",
          not layer.crs().isValid(), layer.crs().authid())
    panel = new_panel()
    seen = {}
    try:
        campaign = new_campaign(panel, layer,
                                os.path.join(root, "camp_prj"), seen)
        check(case, "New campaign says a .prj names a system",
              ".prj" in seen.get("info", "") and "32633" in seen["info"],
              seen.get("info"))
        check(case, "and Ok asks to write it beside the file",
              any(k == "question" and ".prj" in t for k, t in BOXES),
              BOXES[-2:])
        check(case, "the campaign is made", campaign is not None, BOXES[-2:])
        if campaign is None:
            return
        check(case, "in the system the .prj names",
              campaign.data["grid"]["crs"] == "EPSG:32633",
              campaign.data["grid"]["crs"])
        # alone in the project, the picture takes the project with it, so
        # it stays where it was drawn instead of jumping into degrees
        check(case, "and the project is in it too",
              QgsProject.instance().crs().authid() == "EPSG:32633",
              QgsProject.instance().crs().authid())
    finally:
        close_panel(panel)
    app.processEvents()
    ds = gdal.Open(path)
    proj = ds.GetProjection()
    ds = None
    check(case, "GDAL reads the system from beside the file, after QGIS let "
          "go of it", bool(proj), proj[:60])
    check(case, "the picture itself is untouched",
          np.array_equal(array_of(path), classes_array()))

    # a .prj beside a picture nothing places: applied, it would put the
    # pixels at 0, 0 of that system
    stray = write(os.path.join(root, "data", "stray.png"),
                  [classes_array()] * 3, driver="PNG")
    with open(os.path.splitext(stray)[0] + ".prj", "w") as f:
        f.write(esri.ExportToWkt())
    layer = layer_of(stray)
    info = info_of(layer)
    check(case, "a .prj beside a picture with no world file is said",
          ".prj" in info and "no world file" in info, info)
    panel = new_panel()
    try:
        campaign = new_campaign(panel, layer, os.path.join(root, "camp_stray"),
                                {})
        check(case, "and not offered", not any(k == "question" and ".prj" in t
                                               for k, t in BOXES), BOXES[-2:])
        check(case, "so the campaign has no system",
              campaign is not None and campaign.data["grid"]["crs"] == "",
              campaign and campaign.data["grid"]["crs"])
    finally:
        close_panel(panel)


# 6 ----------------------------------------- no system: measures, boxes
def no_system_measures(root):
    case = "no system"
    print("\na picture with no system, in Annotate and Objects")
    path = write(os.path.join(root, "data", "photo.png"),
                 [classes_array(), classes_array(), classes_array()],
                 driver="PNG")
    layer = layer_of(path)
    info = info_of(layer)
    check(case, "New campaign says sizes are in pixels, and not that the "
          "pixel is in metres", "pixels, not metres" in info
          and "1.000 x 1.000 m" not in info, info)
    panel = new_panel()
    seen = {}
    try:
        campaign = new_campaign(panel, layer, os.path.join(root, "camp_photo"),
                                seen, tiled=True)
        check(case, "the campaign is made", campaign is not None, BOXES[-2:])
        if campaign is None:
            return
        panel.toggle_module(0)
        section = panel.section
        check(case, "Annotate opened", section is not None, BOXES[-2:])
        if section is None:
            return
        square = QgsGeometry.fromRect(QgsRectangle(10, -110, 20, -100))
        area = section.geometry.area(square)
        length = section.geometry.length(
            QgsGeometry.fromPolylineXY([QgsPointXY(10, -300),
                                        QgsPointXY(20, -300)]))
        check(case, "a 10 x 10 pixel square measures 100", abs(area - 100) <
              1e-6, area)
        check(case, "a 10 pixel line measures 10", abs(length - 10) < 1e-6,
              length)
        check(case, "the radius is counted in pixels",
              section.radius.suffix().strip() == "px",
              section.radius.suffix())
    finally:
        close_panel(panel)
    ruler = g["ground_measure"](QgsCoordinateReferenceSystem())
    side = ruler.measureLine(QgsPointXY(0, -300), QgsPointXY(10, -300))
    check(case, "Cutouts' ruler measures a picture on the plane",
          abs(side - 10) < 1e-6, side)

    class NaNRuler:
        def measureLine(self, *a):
            return float("nan")

    me = types.SimpleNamespace(
        smallest=types.SimpleNamespace(value=lambda: 2.0),
        geometry=types.SimpleNamespace(measure=NaNRuler(), pixel_crs=(1, 1),
                                       pixel_m=(1.0, 1.0)))
    small, wide, tall = g["ObjectsSection"].too_small(
        me, QgsRectangle(0, -10, 1, -9))
    check(case, "a box measured NaN is measured from its pixels instead",
          wide == wide and abs(wide - 1.0) < 1e-9, (wide, tall))
    check(case, "and a one pixel box is too small for a two pixel minimum",
          small, small)


# 7 ---------------------------------------------------- odd resolutions
def resolutions(root):
    case = "resolution"
    print("\nnumber boxes on 250 m, 30 m and 2 mm rasters")
    for name, px, tiled in (("modis250", 250.0, True), ("micro2mm", 0.002,
                                                        True)):
        gt = (500000.0, px, 0.0, 4100000.0, 0.0, -px)
        path = write(os.path.join(root, "data", name + ".tif"),
                     [classes_array(400, 400)], gt=gt, wkt=WKT)
        layer = layer_of(path)
        panel = new_panel()
        seen = {}
        try:
            campaign = new_campaign(panel, layer,
                                    os.path.join(root, "camp_" + name), seen,
                                    tiled=tiled)
            if campaign is None:
                check(case, name + ": the campaign is made", False, BOXES[-2:])
                continue
            panel.toggle_module(0)
            section = panel.section
            if section is None:
                check(case, name + ": Annotate opened", False, BOXES[-2:])
                continue
            pm = section.geometry.pixel_m[0]
            r = section.radius
            check(case, "%s: the brush starts at 10 pixels" % name,
                  abs(r.value() / pm - 10) < 0.2, r.value() / pm)
            check(case, "%s: and reaches 500 pixels" % name,
                  r.maximum() / pm >= 499, r.maximum() / pm)
            check(case, "%s: one click of an arrow is one pixel" % name,
                  abs(r.singleStep() / pm - 1) < 0.02, r.singleStep() / pm)
            check(case, "%s: its smallest radius does not read 0" % name,
                  r.minimum() > 0 and r.textFromValue(r.minimum())
                  .strip("0.,") != "", r.textFromValue(r.minimum()))
            t = section.tile_side
            check(case, "%s: a frame starts at 200 pixels" % name,
                  abs(t.value() / pm - 200) < 1, t.value() / pm)
            check(case, "%s: and may be as small as 8 pixels" % name,
                  t.minimum() / pm <= 8.5, t.minimum() / pm)
        finally:
            close_panel(panel)
    gt = (500000.0, 30.0, 0.0, 4100000.0, 0.0, -30.0)
    path = write(os.path.join(root, "data", "classes30.tif"),
                 [classes_array(96, 72)], gt=gt, wkt=WKT)
    layer = layer_of(path)
    panel = new_panel()
    try:
        section = new_correction(panel, layer, os.path.join(root, "fix_30"),
                                 {})
        check(case, "Correct opened on a 30 m map", section is not None,
              BOXES[-2:])
        if section is not None:
            pm = section.geometry.pixel_m[0]
            check(case, "30 m: Correct's brush reaches 500 pixels",
                  section.radius.maximum() / pm >= 499,
                  section.radius.maximum() / pm)
    finally:
        close_panel(panel)


# 8 ------------------------------------------ non-square pixels, EXIF
def said_in_new_campaign(root):
    case = "said"
    print("\nwhat New campaign says about pixels and photos")
    gt = (500000.0, 0.04, 0.0, 4100000.0, 0.0, -0.06)
    path = write(os.path.join(root, "data", "nsq.tif"),
                 [classes_array(400, 400)], gt=gt, wkt=WKT)
    layer = layer_of(path)
    info = info_of(layer)
    check(case, "pixels that are not square on the ground are said",
          "not square" in info, info)
    panel = new_panel()
    try:
        campaign = new_campaign(panel, layer, os.path.join(root, "camp_nsq"),
                                {}, tiled=True)
        if campaign is not None:
            panel.toggle_module(0)
            section = panel.section
            if section is not None:
                section.show_side_in_pixels()
                text = section.side_px.text()
                check(case, "the frame side says its two lengths",
                      " x " in text and "px" in text, text)
    finally:
        close_panel(panel)

    path = write(os.path.join(root, "data", "turned.jpg"),
                 [classes_array() * 50] * 3, driver="JPEG")
    exif_turned(path, 6)
    ds = gdal.Open(path)
    check(case, "(GDAL reads the orientation)",
          ds.GetMetadataItem("EXIF_Orientation") == "6",
          ds.GetMetadataItem("EXIF_Orientation"))
    ds = None
    info = info_of(layer_of(path))
    check(case, "a photo stored turned is said", "EXIF orientation 6" in info,
          info)

    gt = (500000.0, 0.1, 0.0, 4100000.0, 0.0, -0.1)
    path = write(os.path.join(root, "data", "world_only.png"),
                 [classes_array()] * 3, driver="PNG")
    world_file(path, ".pgw", gt)
    info = info_of(layer_of(path))
    check(case, "a world file with no system is said, in its own units",
          "world file" in info and "0.100 x 0.100 m" not in info, info)
    drop_layers()


root = tempfile.mkdtemp(prefix="rl_grids_")
os.makedirs(os.path.join(root, "data"))
try:
    for walk in (picture_in_correct, north_down_in_correct, rotated_in_correct,
                 system_set_in_qgis, prj_beside_picture, no_system_measures,
                 resolutions, said_in_new_campaign):
        try:
            walk(root)
        except Exception:
            traceback.print_exc()
            fails.append("%s: raised" % walk.__name__)
            drop_layers()
finally:
    drop_layers()
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(_PROFILE, ignore_errors=True)

print()
if UNEXPECTED:
    print("unexpected dialogs: %s" % UNEXPECTED)
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.stdout.flush()
os._exit(1 if fails else 0)
