"""A real QGIS with the program's own panel in it, and no window.

What the suites that drive the panel in a real QGIS share: the application,
started headless with a profile of its own; a stand-in for the QGIS window
around the panel (map canvas, message bar, layer tree), which is the one part
of QGIS a suite cannot have without a screen; the built single file, run into
a namespace of its own; the windows that ask, answered from here; and the
rasters, campaigns and corrections the suites start from.

Every question the program asks through run_dialog is answered by name from
ANSWERS, and a QMessageBox put up that way (the recovery question) is answered
by clicking the button named next in CLICK, or by closing it when there is
none. QMessageBox.warning, critical, information and question are recorded
in BOXES and answered with the harmless button.

Imported only under a Python that has QGIS: the suites that use it are named
in NEEDS_QGIS in tests/run.py.
"""
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The settings the panel writes (recent corrections, the operator, the
# autosave) go to a profile of this run, never to the one of whoever runs it.
PROFILE = tempfile.mkdtemp(prefix="rl_qgiskit_profile_")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = PROFILE
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
SRC = os.environ.get("RL_SRC") or os.path.join(ROOT, "dist", "rasterlabel.py")

from qgis.core import (Qgis, QgsApplication, QgsGeometry,  # noqa: E402
                       QgsPointXY, QgsProject, QgsRasterLayer, QgsRectangle)
from qgis.PyQt import QtWidgets  # noqa: E402
from qgis.PyQt.QtCore import QSettings  # noqa: E402
from qgis.gui import QgsMapCanvas  # noqa: E402
import qgis.utils  # noqa: E402
import numpy as np  # noqa: E402
from osgeo import gdal, osr  # noqa: E402

gdal.UseExceptions()
# Before the application: QgsSettings of a standalone QGIS go to the registry
# of the machine otherwise.
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                  PROFILE)
app = QgsApplication([], False)
app.initQgis()
QGIS_VERSION = Qgis.QGIS_VERSION

SAID = []           # what reached the message bar
BOXES = []          # (kind, text) of every QMessageBox.warning and the like
ASKED = []          # the text of every QMessageBox asked through run_dialog
CLICK = []          # the button to click on the next one of those
ANSWERS = {}        # dialog class name -> function(dialog) -> result
UNEXPECTED = []     # dialogs nobody answered


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
        self.bar = Bar()

    def mapCanvas(self): return self.canvas
    def messageBar(self): return self.bar
    def layerTreeView(self): return Tree()
    def mainWindow(self): return self.main
    def addDockWidget(self, *a): pass
    def removeDockWidget(self, *a): pass
    def setActiveLayer(self, *a): pass
    def activeLayer(self): return None


iface = Iface()
qgis.utils.iface = iface
with io.open(SRC, encoding="utf-8") as _fh:
    _code = _fh.read().replace("\nstart()\n", "\n")
g = {"__name__": "rasterlabel", "__file__": SRC}
exec(compile(_code, SRC, "exec"), g)


def run_dialog(d):
    if isinstance(d, QtWidgets.QMessageBox):
        ASKED.append("%s | %s" % (d.text(), d.informativeText()))
        want = CLICK.pop(0) if CLICK else None
        for b in d.buttons():
            if want and b.text().replace("&", "") == want:
                b.click()
                return 0
        return 0            # closed without an answer
    name = type(d).__name__
    f = ANSWERS.pop(name, None)
    if f is None:
        UNEXPECTED.append(name)
        return 0
    return f(d)


g["run_dialog"] = run_dialog


def _box(kind, answer):
    def f(*a, **k):
        BOXES.append((kind, str(a[2] if len(a) > 2 else "")))
        return answer
    return staticmethod(f)


# A folder written is shown in the file manager of the desktop: not from here.
OPENED = []
from qgis.PyQt.QtGui import QDesktopServices  # noqa: E402
QDesktopServices.openUrl = staticmethod(
    lambda url, *a, **k: OPENED.append(url.toString()) or True)

QMB = QtWidgets.QMessageBox
QMB.warning = _box("warning", QMB.StandardButton.Cancel)
QMB.critical = _box("critical", QMB.StandardButton.Ok)
QMB.information = _box("information", QMB.StandardButton.Ok)
QMB.question = _box("question", QMB.StandardButton.Yes)


# ------------------------------------------------------------------ checks
fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)[:600]) if not cond and detail != "" else ""),
          flush=True)
    if not cond:
        fails.append(name)
    return bool(cond)


def finish():
    print()
    print("FAILED: %d" % len(fails) if fails else "all pass", flush=True)
    for f in fails:
        print("   " + f)
    sys.stdout.flush()
    os._exit(1 if fails else 0)


# ----------------------------------------------------------------- rasters
UTM = osr.SpatialReference()
UTM.ImportFromEPSG(32633)
X0, Y0 = 500000.0, 4100000.0


def write_image(path, n=200, px=0.1):
    """Three bands of bytes, n x n pixels of px metres, in UTM 33N."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ds = gdal.GetDriverByName("GTiff").Create(path, n, n, 3, gdal.GDT_Byte)
    ds.SetGeoTransform([X0, px, 0, Y0, 0, -px])
    ds.SetProjection(UTM.ExportToWkt())
    yy, xx = np.mgrid[0:n, 0:n]
    for b in range(3):
        ds.GetRasterBand(b + 1).WriteArray(
            ((xx + yy * (b + 1)) % 256).astype("uint8"))
    ds = None
    return path


def write_classes(path, nx=80, ny=60, px=1.0):
    """One band of classes 1 to 4 in vertical stripes, in UTM 33N."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    a = np.empty((ny, nx), np.uint8)
    for i in range(4):
        a[:, i * nx // 4:(i + 1) * nx // 4] = i + 1
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, gdal.GDT_Byte)
    ds.SetGeoTransform([X0, px, 0, Y0, 0, -px])
    ds.SetProjection(UTM.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(a)
    ds = None
    return path


def array_of(path, band=1):
    ds = gdal.Open(path)
    a = ds.GetRasterBand(band).ReadAsArray()
    ds = None
    return a


def layer_of(path, name=None, show=True):
    layer = QgsRasterLayer(path, name or os.path.basename(path))
    QgsProject.instance().addMapLayer(layer)
    if show:
        canvas = iface.mapCanvas()
        canvas.setDestinationCrs(layer.crs())
        canvas.setExtent(layer.extent())
        canvas.refresh()
    app.processEvents()
    return layer


def square(x, y, side):
    return QgsGeometry.fromRect(QgsRectangle(x, y, x + side, y + side))


def point(x, y):
    return QgsPointXY(x, y)


# ------------------------------------------------------- campaigns, panel
CLASSES = [{"code": 1, "name": "mud", "colour": "#aa5500"},
           {"code": 2, "name": "water", "colour": "#0055ff"}]


def new_panel():
    return g["Panel"]()


def new_campaign(panel, folder, raster, tiled=False, name="kit campaign",
                 operator="ANNA"):
    """What New campaign does once its window is answered."""
    panel.campaign = g["Campaign"].create(folder, name, tiled, raster,
                                          [dict(c) for c in CLASSES],
                                          operator)
    panel.open_the_net()
    panel.load_layers()
    panel.describe_campaign()
    panel.update_enabled()
    return panel.campaign


def open_campaign(panel, folder):
    """Open campaign, with its file chooser answered with this folder."""
    dialog = g["QFileDialog"]
    real = dialog.getOpenFileName
    dialog.getOpenFileName = staticmethod(
        lambda *a, **k: (os.path.join(folder, "campaign.json"), ""))
    try:
        panel.open_campaign()
    finally:
        dialog.getOpenFileName = real
    return panel.campaign


def annotate(panel):
    """Annotate, open."""
    if panel.open_index != 0:
        panel.toggle_module(0)
    return panel.section


def find_mine(owner_id, role):
    return g["find_mine"](owner_id, role)


def counts(package):
    """Rows per table, read straight from the file."""
    con = sqlite3.connect(package)
    out = {}
    try:
        for t in ("polygons", "lines", "points", "boxes", "tiles"):
            try:
                out[t] = con.execute('select count(*) from "%s"' % t
                                     ).fetchone()[0]
            except sqlite3.Error as err:
                out[t] = str(err)
    finally:
        con.close()
    return out


def readings(package):
    """[operator, pass] of the polygons, each once, sorted."""
    con = sqlite3.connect(package)
    try:
        return [list(r) for r in con.execute(
            "select distinct upper(operator), pass_no from polygons "
            "order by 1, 2")]
    finally:
        con.close()


def overlapping_pairs(layer):
    fs = list(layer.getFeatures())
    bad = 0
    for i in range(len(fs)):
        for j in range(i + 1, len(fs)):
            inter = fs[i].geometry().intersection(fs[j].geometry())
            if inter is not None and not inter.isEmpty() and inter.area() > 1e-6:
                bad += 1
    return bad


def file_key(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def same_file(a, b):
    return file_key(a) == file_key(b)


def reads(layer, path):
    return layer is not None and layer.isValid() and same_file(
        layer.source().split("|")[0], path)


def check_report(campaign, correction=None):
    """Check, as the button runs it: (text, problems, notes)."""
    return g["report"](campaign, correction)


def close_panel(panel):
    try:
        if panel.correction is not None:
            panel.close_correction()
        if panel.section is not None:
            panel.close_module()
        if panel.campaign is not None:
            panel.close_campaign()
    except Exception:
        traceback.print_exc()
    panel.close()
    panel.deleteLater()
    app.processEvents()


def hard_kill(code=9):
    """What a crash, or End task, does: no clean up of any kind, no DLL told
    the process is going, nothing flushed that was not already flushed."""
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        k.TerminateProcess(k.GetCurrentProcess(), code)
    os._exit(code)


def emit(tag, value):
    """One line a parent process reads back."""
    print("@@%s %s" % (tag, json.dumps(value)), flush=True)


def read_emitted(text):
    out = {}
    for line in (text or "").splitlines():
        if line.startswith("@@"):
            tag, _, rest = line[2:].partition(" ")
            try:
                out[tag] = json.loads(rest)
            except ValueError:
                out[tag] = rest
    return out


def fresh(path):
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)
    return path
