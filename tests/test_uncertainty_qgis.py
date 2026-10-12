"""The layers of uncertainty-guided correction, in a real QGIS.

The fakes of the other suites take any renderer and any blend mode, and
the pseudocolour shader and the blend modes are exactly what moved between
QGIS 3 and QGIS 4. So a map of three bands, the class, "probabilita x255"
and "entropia x255", is corrected here in a real QGIS, through the panel:

  Use it puts the uncertainty on the map in the correction's group, right
  above the copy: a pseudocolour of band 1, interpolated from white to dark
  red, multiplied into the classes at 60 %, its 255 clear; hidden while the
  walk is blind, shown when the card's tick is;
  the places are a layer of their own above it, read from
  uncertainty_places.geojson in the copy's system, drawn by status, with no
  word of u in it while the walk is blind;
  Close takes the copy, the uncertainty and the places out of the project
  and touches no file; opened again, the place in hand is the one it was,
  and the two layers come back above the copy.

With RL_SHOTS set to a folder, the Source window, Correct with the card at
260 and 340 pixels and the report window are saved there as pictures.

Needs QGIS itself (tests/run.py, NEEDS_QGIS).
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qgiskit as K  # noqa: E402
import numpy as np  # noqa: E402
from osgeo import gdal  # noqa: E402
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer  # noqa: E402
from qgis.PyQt import QtWidgets  # noqa: E402
from qgis.PyQt.QtGui import QPainter  # noqa: E402

g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_unc_qgis_")
SHOTS = os.environ.get("RL_SHOTS")
print("QGIS %s" % K.QGIS_VERSION)

NX, NY = 96, 64
rng = np.random.default_rng(5)
CLASS = np.empty((NY, NX), np.uint8)
for i in range(4):
    CLASS[:, i * NX // 4:(i + 1) * NX // 4] = i + 1
PROB = rng.integers(70, 256, (NY, NX)).astype(np.uint8)
ENT = rng.integers(1, 255, (NY, NX)).astype(np.uint8)


def write_map(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ds = gdal.GetDriverByName("GTiff").Create(path, NX, NY, 3, gdal.GDT_Byte)
    ds.SetGeoTransform([K.X0, 0.5, 0, K.Y0, 0, -0.5])
    ds.SetProjection(K.UTM.ExportToWkt())
    for b, (a, name) in enumerate(((CLASS, "classe"),
                                   (PROB, "probabilita x255"),
                                   (ENT, "entropia x255"))):
        band = ds.GetRasterBand(b + 1)
        band.WriteArray(a)
        band.SetNoDataValue(0)
        band.SetDescription(name)
    ds = None
    return path


def mine(book_id, role):
    return g["find_mine"](book_id, role)


def order_in(group_name):
    group = QgsProject.instance().layerTreeRoot().findGroup(group_name)
    if group is None:
        return []
    return [k.layerId() for k in group.children() if hasattr(k, "layerId")]


def ticked(layer):
    node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
    return node is not None and node.isVisible()


def text_width(fm, words):
    try:
        return fm.horizontalAdvance(words)
    except AttributeError:
        return fm.width(words)


def fits(panel, card, width):
    """The card at this width: nothing of it past the panel's edge, no key
    or tick box cutting its words, and the three keys of the walk on one
    row from 280 pixels on."""
    panel.setFixedWidth(width)
    panel.show()
    for _ in range(3):
        panel.resize(width, max(panel.heightForWidth(width),
                                panel.sizeHint().height()))
        K.app.processEvents()
    bad = []
    kinds = (QtWidgets.QPushButton, QtWidgets.QLabel, QtWidgets.QCheckBox)
    for w in card.findChildren(kinds):
        if not w.isVisible():
            continue
        p = w.mapTo(panel, w.rect().topLeft())
        if p.x() < 0 or p.x() + w.width() > panel.width() + 1:
            bad.append("past the edge: %s" % w.text()[:20])
        if isinstance(w, QtWidgets.QPushButton) and w.text():
            if text_width(w.fontMetrics(), w.text()) + 4 > w.width():
                bad.append("cut: %s" % w.text())
        if isinstance(w, QtWidgets.QCheckBox) and \
                w.sizeHint().width() > w.width() + 1:
            bad.append("cut: %s" % w.text())
    ys = set(b.mapTo(panel, b.rect().topLeft()).y()
             for b in (card.b_back, card.b_next, card.b_skip))
    if width >= 280 and len(ys) != 1:
        bad.append("the walk is on %d rows" % len(ys))
    spark = card.spark.mapTo(panel, card.spark.rect().topRight()).x()
    if spark > card.mapTo(panel, card.rect().topRight()).x() + 1:
        bad.append("the sparkline is wider than the card")
    return bad


def shot(widget, name, width=None):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    if width:
        widget.setFixedWidth(width)
    widget.show()
    K.app.processEvents()
    for _ in range(3):
        if width:
            widget.resize(width, max(widget.heightForWidth(width),
                                     widget.sizeHint().height()))
        K.app.processEvents()
    widget.grab().save(os.path.join(SHOTS, name))
    print("  shot %s, %d x %d" % (name, widget.width(), widget.height()))


try:
    source = write_map(os.path.join(root, "data", "landcover.tif"))
    layer = K.layer_of(source, "landcover")
    panel = K.new_panel()

    def opened(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText("unc fix")
        d.raster.setCurrentIndex(d.raster.findData(layer.id()))
        d.fill_bands()
        d.band.setCurrentIndex(d.band.findData(1))
        d.folder.setText(os.path.join(root, "corr"))
        d.operator.setText("anna")
        return 1

    def confirm(d):
        d.accept()
        return 1

    K.ANSWERS["OpenCorrection"] = opened
    K.ANSWERS["ConfirmClasses"] = confirm
    panel.new_correction_campaign()
    section = panel.section
    folder = os.path.join(root, "corr")
    print("Correct, and the card's suggestion")
    check("Correct opens", type(section).__name__ == "CorrectionSection",
          (K.BOXES[-3:], K.UNEXPECTED))
    hook = g["unc_hook_of"](section)
    card = hook.card
    book_id = section.book.data["id"]
    name = section.record["name"]
    check("the card suggests band 2", card.line.text().startswith(
        'band 2 "probabilita x255"'), card.line.text())
    check("no layer of the walk yet",
          mine(book_id, "uncertainty:" + name) is None
          and mine(book_id, "places:" + name) is None)
    if SHOTS:
        shot(panel, "correct_card_suggestion_260.png", 260)

    print()
    print("Use it: the uncertainty on the map")
    card.use_it()
    K.app.processEvents()
    # places of 16 px, so the walk has somewhere to go on a small map: the
    # file is made again, and its layer with it
    hook.apply(dict(hook.spec), {"side_px": 16})
    card.refresh()
    K.app.processEvents()
    check("24 places of 16 px", hook.places.N == 24, hook.places.N)
    over = mine(book_id, "uncertainty:" + name)
    copy_layer = mine(book_id, section.layer_role())
    check("a raster layer of <copy>_uncertainty.tif",
          isinstance(over, QgsRasterLayer) and over.isValid()
          and over.source().endswith("landcover_corrected_uncertainty.tif"),
          over and over.source())
    r = over.renderer() if over is not None else None
    check("a pseudocolour of band 1", r is not None
          and r.type() == "singlebandpseudocolor"
          and (r.inputBand() if hasattr(r, "inputBand") else r.band()) == 1,
          r and r.type())
    items = []
    shader = None
    try:
        shader = r.shader().rasterShaderFunction()
        items = [(round(i.value), i.color.name())
                 for i in shader.colorRampItemList()]
    except Exception as err:
        items = [str(err)]
    check("white at 0, orange in the middle, dark red at 254", items ==
          [(0, "#ffffff"), (127, "#f0a040"), (254, "#8b1a1a")], items)
    kind = str(shader.colorRampType()) if shader is not None else ""
    check("interpolated, not in classes", "Interpolated" in kind
          or "Linear" in kind or kind == "0", kind)
    check("multiplied into what is under it",
          over.blendMode() == QPainter.CompositionMode.CompositionMode_Multiply,
          over.blendMode())
    check("at 60 %", abs(over.opacity() - 0.6) < 1e-6, over.opacity())
    check("255 is its nodata, so clear",
          over.dataProvider().sourceNoDataValue(1) == 255)
    ids = order_in(section.book.group_name)
    places_layer = mine(book_id, "places:" + name)
    check("in the correction's group, the places, then the uncertainty "
          "right above the copy", copy_layer is not None
          and places_layer is not None and ids[:3] ==
          [places_layer.id(), over.id(), copy_layer.id()], ids)
    check("hidden while the walk is blind", not ticked(over))
    card.overlay.setChecked(True)
    check("shown when the card's tick is", ticked(over))
    card.overlay.setChecked(False)

    print()
    print("the places")
    check("a vector layer of uncertainty_places.geojson",
          isinstance(places_layer, QgsVectorLayer) and places_layer.isValid()
          and "uncertainty_places.geojson" in places_layer.source())
    check("in the copy's system", places_layer.crs().authid()
          == "EPSG:32633", places_layer.crs().authid())
    cats = []
    try:
        cats = sorted(c.value() for c in
                      places_layer.renderer().categories())
    except Exception as err:
        cats = [str(err)]
    check("drawn by status", cats == ["current", "done", "queued",
                                      "skipped"], cats)
    card.next()
    K.app.processEvents()
    places_layer.dataProvider().reloadData()
    feats = list(places_layer.getFeatures())
    status = [f["status"] for f in feats]
    check("the place in hand, and the next ones queued",
          status.count("current") == 1 and status.count("queued") >= 1,
          status)
    fields = [f.name() for f in places_layer.fields()]
    check("no word of u while blind", "mean_u" not in fields
          and "selection" not in fields, fields)
    current = hook.places.current()["place_id"]
    for width in (260, 300, 520):
        bad = fits(panel, card, width)
        check("the card holds at %d px" % width, not bad, bad)
    panel.setMinimumWidth(0)
    panel.setMaximumWidth(16777215)
    if SHOTS:
        shot(panel, "correct_card_260.png", 260)
        shot(panel, "correct_card_340.png", 340)
        panel.setMinimumWidth(0)
        panel.setMaximumWidth(16777215)
        d = g["UncertaintySource"](section, section, hook)
        d.in_copy.setChecked(True)
        d.select(d.band, 2)
        d.source_changed()
        shot(d, "uncertainty_source.png")
        d.close()

    print()
    print("Close, and open again")
    card.next()
    current = hook.places.current()["place_id"]
    gone = [mine(book_id, role) for role in
            (section.layer_role(), "uncertainty:" + name, "places:" + name)]
    before = sorted(os.listdir(folder))
    panel.close_correction()
    K.app.processEvents()
    check("Close takes the copy, the uncertainty and the places out",
          all(lyr is not None for lyr in gone)
          and all(mine(book_id, role) is None for role in
                  ("uncertainty:" + name, "places:" + name)))
    check("and touches no file", sorted(os.listdir(folder)) == before,
          sorted(set(os.listdir(folder)) ^ set(before)))

    def again(d):
        d.existing.setCurrentIndex(d.existing.findData(
            "open:" + os.path.join(folder, "correction.json")))
        return 1
    K.ANSWERS["OpenCorrection"] = again
    panel.open_correction_campaign()
    K.app.processEvents()
    section = panel.section
    hook = g["unc_hook_of"](section)
    check("opened again", type(section).__name__ == "CorrectionSection")
    check("the place in hand is the one it was",
          hook.places.current() is not None
          and hook.places.current()["place_id"] == current)
    over = mine(book_id, "uncertainty:" + name)
    places_layer = mine(book_id, "places:" + name)
    copy_layer = mine(book_id, section.layer_role())
    ids = order_in(section.book.group_name)
    check("and the two layers are back above the copy",
          over is not None and places_layer is not None
          and copy_layer is not None
          and ids[:3] == [places_layer.id(), over.id(), copy_layer.id()],
          ids)
    spec = json.load(open(os.path.join(folder, "correction.json"),
                          encoding="utf-8"))["uncertainty"]
    check("the manifest kept the spec", spec["kind"] == "probability"
          and spec["band"] == 2)
    if SHOTS:
        section.mask_of = lambda geom: (2, 2, np.ones((10, 10), bool))
        section.choose_from(None)
        section.choose_class(2)
        section.paint(K.square(K.X0 + 1, K.Y0 - 6, 5))
        hook.card.next()
        SEEN = []
        K.ANSWERS["ReportWindow"] = lambda w: SEEN.append(w) or 1
        g["unc_report_start"](panel)
        if SEEN:
            shot(SEEN[0], "uncertainty_report.png")
    panel.close_correction()
except Exception:
    import traceback
    traceback.print_exc()
    check("the suite ran to its end", False)
finally:
    shutil.rmtree(root, ignore_errors=True)

K.finish()
