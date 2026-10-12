"""Correct on the ground it is measured on, in a real QGIS.

Five things that only a real QGIS can show, because they are the project, the
canvas and the ellipsoid:

  the area of a stroke on a map in degrees or in Web Mercator is the ground
  its pixels cover, row by row, not the pixel at the middle of the map times
  their number (1.6 times too much at 55 to 60 north on a map of 0 to 60,
  0.87 times at the equator); on a map in UTM it is still the one pixel;

  an Undo is visible: operations.csv is the log of what was written and keeps
  the row (fourteen columns, as ever), the manifest says how much of it was
  undone, and the panel counts net of it and says how much ground a person
  changed once each, where strokes painted over the same pixels;

  the operator picked in the panel in this session is the one the strokes
  are filed under, the operator typed in the box of Correct too, and the
  creator when nobody said; the correction's list of operators grows; the
  name typed in the window that made the correction stays the operator while
  the session's reading is the one it was, and gives way to one picked since;

  saving the project while Correct is open does not save the map it started
  from unticked, and the screen keeps it unticked;

  the view of the original beside the copy follows the main view into
  another coordinate system;

  a copy that cannot be written refuses the stroke: nothing is counted and
  nothing is logged.

Needs QGIS itself (tests/run.py, NEEDS_QGIS).
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import json
import math
import os
import shutil
import stat
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qgiskit as K  # noqa: E402
import numpy as np  # noqa: E402
from osgeo import gdal, osr  # noqa: E402
from qgis.core import (QgsCoordinateReferenceSystem, QgsGeometry,  # noqa: E402
                       QgsProject, QgsRasterLayer, QgsRectangle)

g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_ground_qgis_")
print("QGIS %s" % K.QGIS_VERSION)

# the WGS 84 ellipsoid, for an area that does not come from the program
A_AXIS = 6378137.0
FLAT = 1 / 298.257223563
B_AXIS = A_AXIS * (1 - FLAT)
E2 = FLAT * (2 - FLAT)
E1 = math.sqrt(E2)


def _band(phi):
    s = math.sin(phi)
    return B_AXIS * B_AXIS * (s / (2 * (1 - E2 * s * s))
                              + math.log((1 + E1 * s) / (1 - E1 * s))
                              / (4 * E1))


def cell_m2(lon0, lon1, lat0, lat1):
    """The area of a cell of longitude and latitude on the ellipsoid."""
    return abs(math.radians(lon1 - lon0)
               * (_band(math.radians(lat1)) - _band(math.radians(lat0))))


def write_map(path, nx, ny, gt, epsg, classes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, gdal.GDT_Byte)
    ds.SetGeoTransform(list(gt))
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(classes)
    ds = None
    return path


def correct(source, name, operator="ann"):
    """A new correction on the map, the way the panel makes one, and the
    section Correct opens on it."""
    layer = QgsRasterLayer(source, name)
    QgsProject.instance().addMapLayer(layer)
    panel = K.new_panel()
    folder = os.path.join(root, name + "_fix")

    def opened(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText(name)
        d.raster.setCurrentIndex(d.raster.findData(layer.id()))
        d.fill_bands()
        d.folder.setText(folder)
        d.operator.setText(operator)
        return 1

    K.ANSWERS["OpenCorrection"] = opened
    K.ANSWERS["ConfirmClasses"] = lambda d: (d.accept(), 1)[1]
    panel.new_correction_campaign()
    K.app.processEvents()
    return panel, panel.section, layer, folder


def reopen(panel, folder):
    """Open correction.json again, as the list of recent corrections does."""
    def again(d):
        d.existing.setCurrentIndex(d.existing.findData(
            "open:" + os.path.join(folder, "correction.json")))
        return 1
    K.ANSWERS["OpenCorrection"] = again
    panel.open_correction_campaign()
    K.app.processEvents()
    return panel.section


def stroke(section, c0, r0, c1, r1, into, only=None):
    """A rectangle of pixels, c0 r0 to c1 r1, painted into a class."""
    gt = section.gt
    x0, x1 = gt[0] + c0 * gt[1], gt[0] + c1 * gt[1]
    y0, y1 = gt[3] + r1 * gt[5], gt[3] + r0 * gt[5]
    inset = abs(gt[1]) * 0.01
    geom = QgsGeometry.fromRect(QgsRectangle(
        min(x0, x1) + inset, min(y0, y1) + abs(gt[5]) * 0.01,
        max(x0, x1) - inset, max(y0, y1) - abs(gt[5]) * 0.01))
    section.choose_from(only)
    section.choose_class(into)
    section.paint(geom)


def array_of(path):
    return K.array_of(path)


def another_copy(path, name):
    """The same map under another name: a map that already has a correction
    is asked about before it gets a second one."""
    out = os.path.join(os.path.dirname(path), name + ".tif")
    shutil.copyfile(path, out)
    return out


def rows_of(folder):
    if not os.path.exists(os.path.join(folder, "operations.csv")):
        return []
    with open(os.path.join(folder, "operations.csv"), newline="",
              encoding="utf-8") as fh:
        return list(csv.reader(fh))


def manifest_of(folder):
    with open(os.path.join(folder, "correction.json"),
              encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------
print("the ground a stroke changed, on a map in degrees")
NX, NY = 100, 600
classes = np.ones((NY, NX), np.uint8)
classes[:, 50:] = 2
geo = write_map(os.path.join(root, "data", "geo.tif"), NX, NY,
                (10.0, 0.1, 0.0, 60.0, 0.0, -0.1), 4326, classes)
panel, section, layer, folder = correct(geo, "geo")
check("Correct opens on the map in degrees",
      type(section).__name__ == "CorrectionSection", (K.BOXES[-3:],
                                                      K.UNEXPECTED))
check("and finds that a pixel is not the same ground all down it",
      section.row_m2 is not None)
for label, (c0, r0, c1, r1) in (("55 to 60 north", (10, 0, 40, 50)),
                                ("0 to 5 north", (10, 550, 40, 600)),
                                ("28 to 32 north", (10, 280, 40, 320))):
    before = section.changed_m2
    now_ = array_of(section.path)[r0:r1, c0:c1].copy()
    stroke(section, c0, r0, c1, r1, 2, only=None)
    after = array_of(section.path)[r0:r1, c0:c1]
    moved = now_ != after
    want = sum(cell_m2(10.0 + c * 0.1, 10.0 + (c + 1) * 0.1,
                       60.0 - (r + 1) * 0.1, 60.0 - r * 0.1)
               for r in range(r0, r1) for c in range(c0, c1)
               if moved[r - r0, c - c0])
    got = section.changed_m2 - before
    check("%s: %.0f m2 changed, the ellipsoid says %.0f" % (label, got, want),
          want > 0 and abs(got / want - 1) < 0.005, (got, want, got / want))

print()
print("the Dataset card and Model vs corrected measure it the same way")
section.save()
record = manifest_of(folder)
done = array_of(section.path)
differs = done != classes
want_all = sum(cell_m2(10.0 + c * 0.1, 10.0 + (c + 1) * 0.1,
                       60.0 - (r + 1) * 0.1, 60.0 - r * 0.1)
               for r, c in zip(*np.nonzero(differs)))
card = g["card_gather_correction"](record, folder)
ops = card["operations"]
check("the card measures the changed ground row by row: %.0f m2, the "
      "ellipsoid says %.0f" % (ops["changed_m2_measured"], want_all),
      abs(ops["changed_m2_measured"] / want_all - 1) < 0.005,
      (ops["changed_m2_measured"], want_all))
check("it agrees with the log, with nothing undone",
      abs(ops["changed_m2_logged"] / ops["changed_m2_measured"] - 1) < 1e-6,
      (ops["changed_m2_logged"], ops["changed_m2_measured"]))
check("so it does not blame undone strokes that were never made",
      not any("undone strokes" in n for n in card["limits"]), card["limits"])
by_pair = {(p["from"], p["to"]): p["m2"]
           for p in card["pixels"]["changed_pairs_px"]}
check("and the m2 of each transition is the ground too",
      abs(sum(by_pair.values()) / want_all - 1) < 0.005, by_pair)
recipe = {"model": {"path": geo, "band": 1},
          "corrected": {"path": section.path, "band": 1},
          "scope": "whole", "changes": section.changes_path,
          "codes": [1, 2], "names": {1: "one", 2: "two"},
          "pixel_m2": section.pixel_area_m2, "row_m2": section.row_m2,
          "write_map": False}
result = g["mvc_compare"](recipe)
summed = g["mvc_summarize"](result, record)
check("Model vs corrected: the net change is the ground, %.0f m2 for %.0f"
      % (summed["changed_m2"], want_all),
      abs(summed["changed_m2"] / want_all - 1) < 0.005,
      (summed["changed_m2"], want_all))
want_map = NX * sum(cell_m2(10.0, 10.1, 60.0 - (r + 1) * 0.1,
                            60.0 - r * 0.1) for r in range(NY))
check("the scope is the ground of the whole map",
      abs(summed["scope_m2"] / want_map - 1) < 0.005,
      (summed["scope_m2"], want_map))
check("and so are the transitions",
      abs(sum(t["area_m2"] for t in summed["transitions"]) / want_all - 1)
      < 0.005, [t["area_m2"] for t in summed["transitions"]])
flat = g["mvc_compare"](dict(recipe, row_m2=None))
flat = g["mvc_summarize"](flat, record)
check("without the rows it is the pixel at the middle of the map times their "
      "number, as it was",
      abs(flat["changed_m2"] - result["counts"]["changed_px"]
          * section.pixel_area_m2) < 1e-6 and not flat["ground_by_row"],
      flat["changed_m2"])
panel.close_correction()
K.app.processEvents()
QgsProject.instance().removeMapLayer(layer.id())

print()
print("and on a map in Web Mercator")
ytop = A_AXIS * math.log(math.tan(math.pi / 4 + math.radians(60.0) / 2))
step = ytop / NY
gt_merc = (1113194.9, step, 0.0, ytop, 0.0, -step)
merc = write_map(os.path.join(root, "data", "merc.tif"), NX, NY, gt_merc,
                 3857, classes)
panel, section, layer, folder = correct(merc, "merc")
to_geo = None
try:
    from qgis.core import QgsCoordinateTransform, QgsPointXY
    to_geo = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:3857"),
        QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
except Exception as err:        # a QGIS without them is not this suite's
    print("no transform:", err)


def merc_cell(c, r):
    p0 = to_geo.transform(QgsPointXY(gt_merc[0] + c * step,
                                     gt_merc[3] - r * step))
    p1 = to_geo.transform(QgsPointXY(gt_merc[0] + (c + 1) * step,
                                     gt_merc[3] - (r + 1) * step))
    return cell_m2(p0.x(), p1.x(), p1.y(), p0.y())


for label, (c0, r0, c1, r1) in (("the top of the map", (10, 0, 40, 50)),
                                ("the bottom", (10, 550, 40, 600))):
    before = section.changed_m2
    now_ = array_of(section.path)[r0:r1, c0:c1].copy()
    stroke(section, c0, r0, c1, r1, 2)
    moved = now_ != array_of(section.path)[r0:r1, c0:c1]
    want = sum(merc_cell(c, r) for r in range(r0, r1) for c in range(c0, c1)
               if moved[r - r0, c - c0])
    got = section.changed_m2 - before
    check("%s: %.0f m2, the ellipsoid says %.0f" % (label, got, want),
          want > 0 and abs(got / want - 1) < 0.005, (got, want, got / want))
panel.close_correction()
K.app.processEvents()
QgsProject.instance().removeMapLayer(layer.id())

print()
print("on a map in UTM the pixel is the one pixel, as it was")
utm_classes = np.ones((80, 100), np.uint8)
utm_classes[:, 50:] = 2
utm_classes[60:, :] = 3
utm = write_map(os.path.join(root, "data", "utm.tif"), 100, 80,
                (500000.0, 2.0, 0.0, 4100000.0, 0.0, -2.0), 32633,
                utm_classes)
panel, section, layer, folder = correct(utm, "utm")
check("no row-by-row area is kept", section.row_m2 is None)
stroke(section, 0, 0, 10, 10, 2, only=1)
check("100 pixels are 100 times the pixel of the manifest",
      abs(section.changed_m2 - 100 * section.pixel_area_m2) < 1e-6,
      (section.changed_m2, section.pixel_area_m2))

# ---------------------------------------------------------------------
print()
print("Undo leaves a trace, and the count is net")
stroke(section, 0, 0, 10, 10, 2, only=1)            # 100 pixels, 1 to 2
section.undo()                                       # the first, taken back
check("Undo took the first stroke back",
      (array_of(section.path)[0:10, 0:10] == 1).all())
stroke(section, 0, 0, 10, 10, 2, only=1)            # 100 px again
stroke(section, 0, 0, 10, 10, 3, only=2)            # the same 100 px, 2 to 3
stroke(section, 50, 0, 60, 10, 1)                    # 100 px of 2 into 1
pixel = section.pixel_area_m2
rows = rows_of(folder)
check("operations.csv has its fourteen columns, and a row per stroke "
      "written, the undone one included",
      len(rows[0]) == 14 and len(rows) == 5 and
      all(len(r) == 14 for r in rows), [len(r) for r in rows])
check("the manifest counts what was written, as the log does",
      manifest_of(folder)["operations"] == 4
      and abs(manifest_of(folder)["changed_m2"] - 400 * pixel) < 0.01,
      manifest_of(folder))
check("and says how much of it was undone",
      manifest_of(folder).get("undone", {}).get("operations") == 1
      and abs(manifest_of(folder)["undone"]["changed_m2"] - 100 * pixel)
      < 0.01, manifest_of(folder).get("undone"))
check("the panel counts net of the undone stroke",
      section.net_operations == 3 and abs(section.net_m2 - 300 * pixel) < 1e-6,
      (section.net_operations, section.net_m2))
text = section.tally.text()
check("and says so", "3</b> operations (1 undone)" in text, text)
check("a pixel painted over twice is counted once on the ground: 200 pixels "
      "differ from the map",
      section.on_ground_px == 200
      and abs(section.on_ground_m2 - 200 * pixel) < 1e-6
      and "on the ground, once each" in text,
      (section.on_ground_px, text))
names = {c: section.class_of(c)["name"] for c in (1, 2, 3)}
net = section.net_pairs()
check("the pairs are net too: the undone 1 to 2 is counted once, not twice",
      net.get("%s -> %s" % (names[1], names[2]), [0])[0] == 1
      and sum(n for n, _ in net.values()) == 3, net)
differ = int((array_of(section.path) != utm_classes).sum())
check("200 pixels really differ from the map", differ == 200, differ)
section.save()
panel.close_correction()
K.app.processEvents()
section = reopen(panel, folder)
check("opened again, the correction still counts net",
      section is not None and section.net_operations == 3
      and "3</b> operations (1 undone)" in section.tally.text(),
      section.tally.text() if section is not None else K.UNEXPECTED)
check("and the pixels once each, read from the record",
      section.on_ground_px == 200, section.on_ground_px)
logged = g["mvc_logged"](manifest_of(folder))
check("Model vs corrected reads the log as gross and says what was undone",
      logged["operations"] == 4 and logged["operations_undone"] == 1
      and abs(logged["changed_m2_undone"] - 100 * pixel) < 0.01, logged)

# ---------------------------------------------------------------------
print()
print("who struck")
check("opened again, the creator is the operator when nobody said otherwise",
      section.operator_name() == "ANN", section.operator_name())
stroke(section, 0, 70, 10, 80, 1, only=3)
check("so the last row is the creator's",
      rows_of(folder)[-1][2] == "ANN", rows_of(folder)[-1])
g["SESSION"]["operator"] = "BRUNO"
stroke(section, 10, 70, 20, 80, 1, only=3)
check("the operator picked in the panel files the next stroke",
      rows_of(folder)[-1][2] == "BRUNO", rows_of(folder)[-1])
check("and is one of the operators of the correction",
      manifest_of(folder)["operators"] == ["ANN", "BRUNO"],
      manifest_of(folder)["operators"])
section.who.setText("carla")
section.operator_edited()
stroke(section, 20, 70, 30, 80, 1, only=3)
check("an operator typed in the box wins over the panel's",
      rows_of(folder)[-1][2] == "CARLA", rows_of(folder)[-1])
check("in capitals, and listed", section.who.text() == "CARLA"
      and manifest_of(folder)["operators"] == ["ANN", "BRUNO", "CARLA"],
      manifest_of(folder)["operators"])
panel.close_correction()
K.app.processEvents()
g["SESSION"]["operator"] = None
section = reopen(panel, folder)
check("and is remembered for this correction on this machine",
      section.who.text() == "CARLA" and section.operator_name() == "CARLA",
      (section.who.text(), section.operator_name()))
section.who.setText("")
section.operator_edited()
check("emptied, it is the creator again",
      section.operator_name() == "ANN", section.operator_name())
panel.close_correction()
K.app.processEvents()

print()
print("the name typed in the window that made it is not lost on reopening")
g["SESSION"]["operator"] = "BOB"          # a reading somebody else picked
panel, section, layer_w, folder_w = correct(another_copy(utm, "utm_said"),
                                            "said", operator="alice")
check("the correction is made by the name typed in the window",
      section.operator_name() == "ALICE", section.operator_name())
panel.close_correction()
K.app.processEvents()
section = reopen(panel, folder_w)
check("opened again in the same session, the strokes still go to the one "
      "who made it, not to the reading picked since",
      section.operator_name() == "ALICE", section.operator_name())
stroke(section, 0, 0, 10, 10, 2, only=1)
check("so the row of the log says so, and the list of operators is not "
      "grown by a name nobody typed here",
      rows_of(folder_w)[-1][2] == "ALICE"
      and manifest_of(folder_w)["operators"] == ["ALICE"],
      (rows_of(folder_w)[-1], manifest_of(folder_w)["operators"]))
panel.close_correction()
K.app.processEvents()
g["SESSION"]["operator"] = "CARL"         # somebody picks a reading on purpose
section = reopen(panel, folder_w)
check("a reading picked since, on purpose, takes over",
      section.operator_name() == "CARL", section.operator_name())
panel.close_correction()
K.app.processEvents()
# a session of its own: the memory of what was typed goes with it
g["SESSION"]["operator"] = "BOB"
g["SESSION"].get("said", {}).clear()
section = reopen(panel, folder_w)
with open(os.path.join(folder_w, g["LOG_NAME"]), encoding="utf-8",
          errors="replace") as fh:
    said = fh.read()
check("a later session is the reading's to say, and the log says who it "
      "files the strokes under when that is not the one who made it",
      section.operator_name() == "BOB"
      and "was made by ALICE, and its strokes are filed under BOB" in said,
      (section.operator_name(), said[-500:]))
panel.close_correction()
K.app.processEvents()
g["SESSION"]["operator"] = None
QgsProject.instance().removeMapLayer(layer_w.id())

# --------------------------------------------------------------- L13, L4
print()
print("the project saved while Correct is open")
QgsProject.instance().removeMapLayer(layer.id())
panel, section, layer, folder = correct(another_copy(utm, "utm_saved"),
                                        "saved")
node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
check("the map the correction started from is unticked on the screen",
      node is not None and not node.isVisible())
project = os.path.join(root, "project.qgs")
check("the project is written", QgsProject.instance().write(project))


def ticked_in(path, layer_id):
    for el in ET.parse(path).getroot().iter("layer-tree-layer"):
        if el.get("id") == layer_id:
            return el.get("checked")
    return None


check("and the file has it ticked, so it comes back as it was",
      ticked_in(project, layer.id()) == "Qt::Checked",
      ticked_in(project, layer.id()))
check("the screen still has it unticked, for the correction goes on",
      not QgsProject.instance().layerTreeRoot().findLayer(
          layer.id()).isVisible())
panel.close_correction()
K.app.processEvents()
check("closing the correction ticks it, as it always did",
      QgsProject.instance().layerTreeRoot().findLayer(
          layer.id()).isVisible())
os.remove(project)
check("closed, saving writes the tree as it is: nothing is listened to",
      QgsProject.instance().write(project)
      and ticked_in(project, layer.id()) == "Qt::Checked")

print()
print("the view of the original follows the main view into another system")
canvas = K.iface.mapCanvas()
panel, section, layer2, folder = correct(another_copy(utm, "utm_mirror"),
                                         "mirror")
canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:32633"))
section.compare.setChecked(True)
K.app.processEvents()
check("the view of the original is opened", section.mirror is not None)
check("in the system of the main view",
      section.mirror.mapSettings().destinationCrs().authid() == "EPSG:32633",
      section.mirror.mapSettings().destinationCrs().authid())
canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
K.app.processEvents()
check("a change of system of the main view is a change of the other",
      section.mirror.mapSettings().destinationCrs().authid() == "EPSG:3857",
      section.mirror.mapSettings().destinationCrs().authid())
section.compare.setChecked(False)
K.app.processEvents()
check("unticked, it listens no more",
      section.mirror is None and not section.following_crs)
canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:32633"))
panel.close_correction()
K.app.processEvents()

# ------------------------------------------------------------------ L22
print()
print("a copy that cannot be written refuses the stroke")
panel, section, layer3, folder = correct(another_copy(utm, "utm_ro"),
                                         "readonly")
before_rows = len(rows_of(folder))
os.chmod(section.path, stat.S_IREAD)
try:
    try:
        gdal.UseExceptions()
        probe = gdal.Open(section.path, gdal.GA_Update)
    except Exception:
        probe = None
    honoured = probe is None
    probe = None
    if honoured:
        stroke(section, 0, 0, 10, 10, 2, only=1)
        check("nothing was counted", section.operations == 0
              and section.history == [], (section.operations,
                                          section.history))
        check("nothing was logged", len(rows_of(folder)) == before_rows)
        check("and the map is as it was",
              (array_of(section.path) == utm_classes).all())
        with open(os.path.join(folder, g["LOG_NAME"]), encoding="utf-8",
                  errors="replace") as fh:
            said = fh.read()
        check("the refusal is said", "nothing was changed: cannot open"
              in said, said[-400:])
        check("and, as nothing was written, it does not say that the copy "
              "may hold part of the stroke",
              "part of that stroke" not in said, said[-400:])
    else:
        print("  (this system lets a read only file be written: skipped)")
finally:
    os.chmod(section.path, stat.S_IWRITE | stat.S_IREAD)
stroke(section, 0, 0, 10, 10, 2, only=1)
check("writable again, the same stroke is made",
      section.operations == 1 and len(rows_of(folder)) == before_rows + 2,
      (section.operations, len(rows_of(folder)), before_rows))
panel.close_correction()
K.app.processEvents()

shutil.rmtree(root, ignore_errors=True)
K.finish()
