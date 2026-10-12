"""Walk through docs/tutorial.md without a window.

    python tools/tutorial_walk.py                   # numbers only
    python tools/tutorial_walk.py --figures docs/img  # and the pictures
    python tools/tutorial_walk.py --keep some/folder  # and keep what it wrote

Run it with the Python of a QGIS (the suites' own way: python-qgis.bat on
Windows, the QGIS Python elsewhere), QT_QPA_PLATFORM=offscreen. It copies the
example of examples/rasterlabel_example/ into a scratch folder and does what
the tutorial tells a person to do, through the panel of the built file
(dist/rasterlabel.py), with the windows that ask answered from here: New
campaign with its four classes, Import frames from the sample design, two
readings of two frames, Check, Measure (Compare two readings, Time, the
dataset card), Export, Whole raster with the ignore value, Cutouts, the
Processing algorithm, Correct on the model's map, Model vs corrected,
Uncertainty, and the card of the correction. It prints the numbers each
measure gives and, with --figures, renders the pictures of the tutorial.

Everything is made up and written in the scratch folder, and a home of its
own is set before anything else (tests/scratch_home.py), so nothing of the
machine it runs on is read or written. The strokes are scripted, not
drawn, so the working times are those of a script: what matters of them is
that the report is written, not the number.

tests/test_tutorial_walk.py runs it as a suite (NEEDS_QGIS), so a button
that is renamed or a window that changes its way breaks the suite and not,
silently, the tutorial.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (os.path.join(ROOT, "tests"), HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import scratch_home  # noqa: E402  a home of its own, before anything else
import csv  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import tempfile  # noqa: E402

import qgiskit as K  # noqa: E402
import make_example as ME  # noqa: E402
import numpy as np  # noqa: E402
from osgeo import gdal  # noqa: E402
from qgis.core import (QgsGeometry, QgsMapRendererSequentialJob,  # noqa: E402
                       QgsMapSettings, QgsPointXY, QgsProject,
                       QgsRectangle)
from qgis.PyQt.QtCore import QSize  # noqa: E402

scratch_home                     # it only has to be imported, and be seen
from qgis.PyQt.QtGui import QColor, QImage, QPainter  # noqa: E402

g, check = K.g, K.check
EXAMPLE = os.path.join(ROOT, "examples", "rasterlabel_example")


# ----------------------------------------------------------------- helpers
def said(*parts):
    print(*parts, flush=True)


def px_polygon(points, dx=0.0, dy=0.0):
    """A polygon given in pixels of the scene, in the ground of the scene."""
    ring = [QgsPointXY(ME.ORIGIN[0] + (c + dx) * ME.PIXEL,
                       ME.ORIGIN[1] - (r + dy) * ME.PIXEL)
            for c, r in points]
    return QgsGeometry.fromPolygonXY([ring])


def px_rect(c0, r0, c1, r1):
    return px_polygon([(c0, r0), (c1, r0), (c1, r1), (c0, r1)])


def object_index(cls, near):
    """The index in ME.outlines() of the object of this class around a pixel."""
    probe = px_polygon([near, (near[0] + 0.1, near[1]),
                        (near[0] + 0.1, near[1] + 0.1)])
    for k, (c, pts) in enumerate(ME.outlines()):
        if c == cls and px_polygon(pts).intersects(probe):
            return k
    return None


def read_csv(path):
    with io.open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def classes_from_csv(path):
    return [{"code": int(r["code"]), "name": r["name"], "colour": r["colour"]}
            for r in read_csv(path)]


def shot(widget, path, width=None):
    """The widget as a picture, at a width if one is asked."""
    widget.show()
    K.app.processEvents()
    if width:
        widget.setFixedWidth(width)
        for _ in range(3):
            widget.resize(width, max(widget.heightForWidth(width),
                                     widget.sizeHint().height()))
            K.app.processEvents()
    image = widget.grab()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.save(path)
    return image.width(), image.height()


def render(layers, extents, path, size=(330, 330), gap=8):
    """Maps of these layers, one over each extent, side by side in one
    picture, drawn the way QGIS draws them."""
    images = []
    for extent in extents:
        s = QgsMapSettings()
        s.setLayers(layers)
        s.setDestinationCrs(layers[0].crs())
        s.setExtent(extent)
        s.setOutputSize(QSize(*size))
        s.setBackgroundColor(QColor(244, 244, 240))
        job = QgsMapRendererSequentialJob(s)
        job.start()
        job.waitForFinished()
        images.append(job.renderedImage())
    width = sum(i.width() for i in images) + gap * (len(images) - 1)
    sheet = QImage(width, size[1], QImage.Format.Format_RGB32)
    sheet.fill(QColor(255, 255, 255))
    painter = QPainter(sheet)
    x = 0
    for image in images:
        painter.drawImage(x, 0, image)
        x += image.width() + gap
    painter.end()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sheet.save(path)
    return path


def layer_of_report(kind, part):
    for layer in QgsProject.instance().mapLayers().values():
        if layer.customProperty("rasterlabel/report") == kind \
                and part in layer.source().lower():
            return layer
    return None


def frame_extents(section, tiles, margin=2.0):
    """The extent of each frame, grown by a margin of metres."""
    out = []
    for t in tiles:
        for f in section.all_tiles():
            if f["tile_id"] == t:
                box = QgsRectangle(f.geometry().boundingBox())
                box.grow(margin)
                out.append(box)
    return out


# --------------------------------------------------------------- the drawing
def draw_frame(section, tile, names, background, jitter=(0.0, 0.0),
               skip=()):
    """What a person does in one frame: the small sharp things first, each
    in its class, then Fill Gap with the background."""
    section.select_tile(tile)
    section.use_brush(False)
    frame = [f for f in section.all_tiles()
             if f["tile_id"] == tile][0].geometry()
    objects = ME.outlines()
    for k in range(len(objects) - 1, -1, -1):     # the truth paints later
        if k in skip:                              # objects over earlier ones
            continue
        cls, pts = objects[k]
        dx = jitter[0] * (((k * 7) % 5) - 2) / 2.0
        dy = jitter[1] * (((k * 3) % 5) - 2) / 2.0
        geom = px_polygon(pts, dx, dy)
        if not geom.intersects(frame):
            continue
        section.choose_class(names[cls])
        section.paint(geom, names[cls])
    section.choose_class(background)
    section.close_holes()


def set_reading(section, who, pass_no):
    section.operator.setCurrentText(who)
    section.operator_changed()
    section.pass_no.setValue(pass_no)


# ---------------------------------------------------------------- the steps
def walk(work, figures=None, say=said):
    """Do the tutorial in work (a scratch folder). Returns what was measured:
    {"numbers": {...}, "files": {...}}; the checks go to K.check."""
    out = {"numbers": {}, "files": {}, "figures": []}
    nums = out["numbers"]
    fig = (lambda name: os.path.join(figures, name)) if figures else \
        (lambda name: os.path.join(work, "figures", name))
    example = os.path.join(work, "rasterlabel_example")
    shutil.copytree(EXAMPLE, example)
    camp = os.path.join(work, "campaign")
    corr = os.path.join(work, "correction")
    classes = classes_from_csv(os.path.join(example, "classes.csv"))
    names = {c["code"]: c["name"] for c in classes}
    ANNA, BRUNO = "ANNA", "BRUNO"

    scene = K.layer_of(os.path.join(example, "scene_rgb.tif"), "scene_rgb")
    panel = K.new_panel()
    windows = []

    def keep_window(w):
        windows.append(w)
        return 1

    def expect_window():
        """The next report window is kept, to be read and photographed."""
        del windows[:]
        K.ANSWERS["ReportWindow"] = keep_window

    if not hasattr(K.Bar, "createMessage"):     # the kit's bar is a stub
        K.Bar.createMessage = lambda self, *a, **k: None

    # ------------------------------------------------ 2. New campaign
    say("== New campaign on scene_rgb.tif, with the four classes")
    seen = {}

    def classes_window(d):
        # one row to begin with, then Add class three times
        first = d.rows[0]
        first[1].setText(classes[0]["name"])
        first[2].setProperty("colour", classes[0]["colour"])
        for c in classes[1:]:
            d.add_blank()
            row = d.rows[-1]
            row[1].setText(c["name"])
            row[2].setProperty("colour", c["colour"])
        seen["wrong"] = d.complaints()
        return 1

    def new_window(d):
        d.name.setText("example")
        d.operator.setText(ANNA)
        d.raster.setCurrentIndex(d.raster.findData(scene.id()))
        d.show_grid()
        d.folder.setText(camp)       # typed by hand, as the tutorial says
        d.folder_touched(camp)
        seen["grid_note"] = d.info.text()
        seen["mode_proposed"] = "In tiles" if d.tiled.isChecked() else "Free"
        d.tiled.setChecked(True)
        K.ANSWERS["ClassEditor"] = classes_window
        d.edit_classes()
        seen["summary"] = d.summary.text()
        return 1

    K.ANSWERS["NewCampaign"] = new_window
    panel.new_campaign()
    campaign = panel.campaign
    check("New campaign made the campaign", campaign is not None,
          (K.BOXES[-3:], K.UNEXPECTED))
    check("the window proposed free drawing for a scene this small",
          seen.get("mode_proposed") == "Free", seen.get("mode_proposed"))
    check("the grid line says the pixel and the system",
          "pixel 0.500 x 0.500 m, system EPSG:32633" in seen["grid_note"],
          seen["grid_note"])
    check("the four classes were typed in with no complaint",
          not seen.get("wrong") and len(campaign.data["classes"]) == 4,
          seen.get("wrong"))
    check("with the codes of the map: 1 to 4",
          [c["code"] for c in campaign.data["classes"]] == [1, 2, 3, 4])
    check("campaign.json and annotation.gpkg are written",
          os.path.isfile(os.path.join(camp, "campaign.json"))
          and os.path.isfile(os.path.join(camp, "annotation.gpkg")))
    check("the campaign is tiled, in the scene's system",
          campaign.data["with_tiles"] is True
          and "32633" in str(campaign.data["grid"].get("crs")),
          campaign.data.get("grid"))

    # -------------------------------------------- 3. Import frames
    say("== Import frames from sample_design.gpkg, keeping the design")
    section = K.annotate(panel)
    # As the tutorial says: the row "tile side" is not there until the Tiles
    # tool is in hand, and taking it opens Settings by itself.
    check("tile side is hidden until the Tiles tool is taken",
          section.row_tile.isHidden() and not section.fold.isChecked())
    section.b_tiles.click()
    K.app.processEvents()
    check("Tiles shows tile side and opens Settings",
          not section.row_tile.isHidden() and section.fold.isChecked())
    check("it starts at 200 pixels, 100 m on this scene",
          section.side_px.text().strip().startswith("200"),
          section.side_px.text())
    section.tile_side.setValue(30.0)
    check("a frame side of 30 m is 60 pixels",
          section.side_px.text().strip().startswith("60"),
          section.side_px.text())
    seen = {}

    def import_window(d):
        seen["what"] = d.source_what.text()
        seen["mapping"] = {f: b.currentText() for f, b in d.combos.items()}
        seen["side"] = d.settings_side.text()
        seen["preview"] = d.preview.text()
        seen["go"] = d.go.text()
        return 1

    K.ANSWERS["ImportFrames"] = import_window
    dialog = g["QFileDialog"]
    dialog.getOpenFileName = staticmethod(lambda *a, **k: (
        os.path.join(example, "sample_design.gpkg"), ""))
    del K.BOXES[:]
    section.import_tiles()
    nums["import_preview"] = seen.get("preview")
    nums["import_message"] = [t for k, t in K.BOXES if k == "information"][-1:]
    tiles = [(f["tile_id"], f["sample_id"], f["stratum"], f["incl_prob"],
              f["weight"]) for f in section.all_tiles()]
    check("twelve frames, t001 to t012", [t[0] for t in tiles] ==
          ["t%03d" % k for k in range(1, 13)], tiles)
    check("the window guessed the five columns of the design",
          seen["mapping"] == {"sample_id": "sample_id", "stratum": "stratum",
                              "incl_prob": "incl_prob", "weight": "weight",
                              "design": "design"}, seen.get("mapping"))
    check("and the frame side is the one of Settings",
          seen["side"].startswith("Settings: 30.00 m (60 px)"), seen["side"])
    check("the preview adds twelve frames, from points",
          seen["preview"].startswith("12 added") and
          "12 from points" in seen["preview"], seen["preview"])
    check("each frame carries sample, stratum, probability and weight",
          all(t[1] and t[2] and t[3] and t[4] for t in tiles), tiles[:2])
    check("no two frames overlap", K.overlapping_pairs(section.tile_layer) == 0)
    check("design_log.csv has twelve rows, all added",
          [r["outcome"] for r in read_csv(os.path.join(
              camp, "design_log.csv"))] == ["added"] * 12)
    nums["frames"] = len(tiles)
    nums["sample_ids"] = [t[1] for t in tiles]
    section.select_tile("t001")
    check("under the list, the design of the frame in hand",
          section.design_line.text().startswith("sample 1 · stratum 2"),
          section.design_line.text())

    # -------------------------------- 4. Two readings of two frames
    say("== ANNA, pass 1, frames t001 and t002")
    roof = object_index(4, (170, 344))
    set_reading(section, ANNA, 1)
    for t in ("t001", "t002"):
        draw_frame(section, t, names, names[1])
    section.save()
    say("== BRUNO, pass 1, the same frames, not seeing ANNA's")
    set_reading(section, BRUNO, 1)
    check("with 'one operator at a time' on, BRUNO sees none of ANNA's work",
          section.by_operator.isChecked() and not [
              f for f in section.scope_polygons()],
          [f["class_name"] for f in section.scope_polygons()][:3])
    draw_frame(section, "t001", names, names[1], jitter=(0.8, 0.8),
               skip=(roof,))
    draw_frame(section, "t002", names, names[1], jitter=(1.5, 1.5))
    section.save()
    package = os.path.join(camp, "annotation.gpkg")
    con = sqlite3.connect(package)
    try:
        by_reading = [tuple(r) for r in con.execute(
            "select upper(operator), pass_no, count(*) from polygons "
            "group by 1, 2 order by 1, 2")]
    finally:
        con.close()
    check("two readings in the package, ANNA and BRUNO, pass 1",
          [r[:2] for r in by_reading] == [(ANNA, 1), (BRUNO, 1)],
          by_reading)
    nums["polygons_by_reading"] = {"%s_p%d" % r[:2]: r[2] for r in by_reading}
    if True:
        panel.setMinimumWidth(0)
        panel.setMaximumWidth(16777215)
        out["figures"].append(fig("panel_campaign.png"))
        shot(panel, fig("panel_campaign.png"), 320)
        panel.setMinimumWidth(0)
        panel.setMaximumWidth(16777215)
        set_reading(section, ANNA, 1)
        section.apply_filter()
        K.app.processEvents()
        polygons = K.find_mine(campaign.data["id"], "polygons")
        frames_layer = K.find_mine(campaign.data["id"], "tiles")
        if polygons is not None and frames_layer is not None:
            boxes = frame_extents(section, ("t001", "t002"), 3.0)
            out["figures"].append(fig("annotated_frames.png"))
            render([frames_layer, polygons, scene], boxes,
                   fig("annotated_frames.png"))
    set_reading(section, BRUNO, 1)

    # --------------------------------------------------- 5. Check
    say("== Check")
    seen = {}

    def check_window(d):
        seen["title"] = d.windowTitle()
        seen["text"] = d.text
        seen["keys"] = sorted(b.text().replace("&", "")
                              for b in d.findChildren(g["QPushButton"]))
        return 1

    K.ANSWERS["Report"] = check_window
    panel.check_everything()
    text = seen.get("text", "")
    first = text.splitlines()[0] if text else ""
    check("the Check key opens a window of its own",
          seen.get("title") == "RasterLabel: Check", seen.get("title"))
    check("Check finds the campaign sound: Everything checks out, or "
          "Nothing is broken", first == "Everything checks out."
          or first.startswith("Nothing is broken"), first)
    check("with a key to Copy report", "Copy report" in seen.get("keys", []),
          seen.get("keys"))
    nums["check"] = first
    out["check_text"] = text

    # ------------------------------------------ 6. Measure > Compare
    say("== Measure > Compare two readings")
    menu = panel.b_measure.menu()
    labels = [a.text() for a in menu.actions() if a.text()]
    check("the Measure menu of a campaign",
          labels == ["Compare two readings…", "Time…", "Dataset card…"],
          labels)
    nums["menu_campaign"] = labels
    # BRUNO is drawing with 'one operator at a time' on: the gate refuses
    refused = panel.blind_gate([(ANNA, 1), (BRUNO, 1)])
    check("with 'one operator at a time' on, Compare is refused, and says "
          "how to go on", refused and "one operator at a time" in refused,
          refused)
    nums["compare_refusal"] = refused
    section.by_operator.setChecked(False)
    section.operator_changed()
    check("unticked, the gate lets both readings through",
          panel.blind_gate([(ANNA, 1), (BRUNO, 1)]) is None)
    seen = {}

    def compare_window_setup(d):
        seen["kind"] = d.kind.currentText()
        seen["a"], seen["b"] = d.a.currentText(), d.b.currentText()
        seen["closed"] = d.closed.text()
        seen["touched"] = d.touched.text()
        seen["folder"] = d.where.text()
        return 1

    K.ANSWERS["CompareSetup"] = compare_window_setup
    expect_window()
    result = g["compare_start"](panel)
    check("Compare ran", result is not None, (K.BOXES[-3:], K.UNEXPECTED))
    if result is not None:
        head = result["summary_json"]["headline"]
        nums["compare"] = {k: head.get(k) for k in (
            "A", "B", "kind", "frames_used", "overall", "kappa", "quantity",
            "allocation", "mean_iou")}
        nums["compare"]["per_class_iou"] = head.get("per_class_iou")
        nums["compare_files"] = sorted(os.listdir(result["folder"]))
        check("two readings of one pass, two frames closed by both",
              head["frames_used"] == 2 and head["kind"] == "inter", head)
        check("an overall agreement between 0.9 and 1, not perfect",
              0.9 < head["overall"] < 1.0, head["overall"])
        check("the report is under reports/agreement/ of the campaign",
              os.path.dirname(result["folder"]) == os.path.join(
                  camp, "reports", "agreement"), result["folder"])
        check("a window was shown, with the headline numbers",
              windows and windows[-1].windowTitle() ==
              "RasterLabel: ANNA, pass 1 vs BRUNO, pass 1",
              [w.windowTitle() for w in windows])
        check("the folder offered, the readings and the rule",
              seen["a"].startswith(ANNA) and seen["b"].startswith(BRUNO)
              and seen["closed"].startswith("closed by both readings (2)"),
              seen)
        if windows:
            out["figures"].append(fig("compare_report.png"))
            shot(windows[-1], fig("compare_report.png"))
        disagreement = layer_of_report("agreement", "disagreement")
        check("the disagreement map is in QGIS", disagreement is not None)
        if disagreement is not None:
            boxes = frame_extents(section, ("t001", "t002"), 3.0)
            out["figures"].append(fig("disagreement_map.png"))
            was = disagreement.opacity()
            disagreement.setOpacity(0.75)
            render([disagreement, scene], boxes, fig("disagreement_map.png"))
            disagreement.setOpacity(was)
        out["files"]["compare"] = result["folder"]
    with io.open(os.path.join(camp, "campaign.json"),
                 encoding="utf-8") as fh:
        mf = json.load(fh)
    check("the campaign's manifest lists the report",
          any(r.get("kind") == "agreement" for r in mf.get("reports", [])))

    # ----------------------------------------------- 7. Measure > Time
    say("== Measure > Time")
    on, why = g["time_enabled"](panel)
    check("Time can be chosen: the journal has begun", on, why)
    seen = {}

    def time_setup(d):
        for box, key in d.readings:
            box.setChecked(True)
        seen["readings"] = [k for b, k in d.readings if b.isChecked()]
        return 1

    K.ANSWERS["TimeSetup"] = time_setup
    expect_window()
    result = g["time_start"](panel)
    check("Time ran", result is not None, (K.BOXES[-3:], K.UNEXPECTED))
    if result is not None:
        nums["time"] = result["headline"]
        nums["time_files"] = sorted(os.listdir(result["folder"]))
        check("both readings are measured", len(seen["readings"]) == 2,
              seen)
        check("under reports/time/ of the campaign",
              os.path.dirname(result["folder"]) == os.path.join(
                  camp, "reports", "time"))
        check("with its window", windows and windows[-1].windowTitle()
              .endswith("Time"), [w.windowTitle() for w in windows])
        out["files"]["time"] = result["folder"]

    say("== Measure > Dataset card (of the campaign)")
    del K.BOXES[:]
    result = g["card_start_campaign"](panel)
    check("the card of the campaign is written", result is not None,
          K.BOXES[-2:])
    if result is not None:
        nums["campaign_card_files"] = sorted(os.path.basename(f)
                                             for f in result["files"])
        check("under reports/card/ of the campaign",
              os.path.dirname(result["folder"]) == os.path.join(
                  camp, "reports", "card"), result["folder"])
        out["files"]["campaign_card"] = result["folder"]
        nums["campaign_card_message"] = [t for k, t in K.BOXES
                                         if k == "information"][-1:]

    # ----------------------------- 8. Export, with the dataset card
    say("== Export, with the dataset card")
    exp = os.path.join(work, "export")
    seen = {}

    def export_window(d):
        seen["tables"] = [(n, b.text()) for n, b in d.tables]
        seen["readings"] = [c["label"] for c in d.choices]
        seen["chosen"] = d.reading.currentText()
        seen["card_default"] = d.card.isChecked()
        d.card.setChecked(True)
        d.where.setText(exp)
        seen["note"] = d.note.text()
        return 1

    K.ANSWERS["ExportVectors"] = export_window
    del K.BOXES[:]
    panel.export_vectors()
    files = sorted(os.listdir(exp)) if os.path.isdir(exp) else []
    nums["export_files"] = files
    check("Export wrote the GeoPackage and the card, in Markdown and JSON",
          "example.gpkg" in files and "example_card.md" in files
          and "example_card.json" in files, (files, K.BOXES[-2:]))
    check("the card is ticked to begin with, and the reading is "
          "'all readings together'", seen["card_default"]
          and seen["chosen"] == "all readings together", seen)
    check("the Export window offers the readings, with 'all readings "
          "together' first", seen["readings"][0] == "all readings together"
          and "ANNA, pass 1" in seen["readings"], seen["readings"])
    if "example_card.json" in files:
        with io.open(os.path.join(exp, "example_card.json"),
                     encoding="utf-8") as fh:
            card = json.load(fh)
        nums["export_card_keys"] = sorted(card)[:12]
    out["files"]["export"] = exp

    # the same Export with one reading chosen, as the tutorial says: the
    # tables are named after it and the card keeps the campaign's name
    exp_one = os.path.join(work, "export_anna")

    def export_one_window(d):
        d.reading.setCurrentIndex(d.reading.findText("ANNA, pass 1"))
        d.card.setChecked(True)
        d.where.setText(exp_one)
        return 1

    K.ANSWERS["ExportVectors"] = export_one_window
    panel.export_vectors()
    one = sorted(os.listdir(exp_one)) if os.path.isdir(exp_one) else []
    nums["export_one_files"] = one
    check("with ANNA, pass 1 chosen the tables are example_ANNA_p1.gpkg and "
          "the card is still example_card", "example_ANNA_p1.gpkg" in one
          and "example_card.md" in one and "example_card.json" in one, one)

    # ----------------- 9. Whole raster, with the ignore value; the mask
    say("== Whole raster with the ignore value")
    panel.toggle_module(3)
    cut = panel.section
    check("Cutouts opens", type(cut).__name__ == "CutoutsSection",
          type(cut).__name__)
    whole = os.path.join(work, "whole")
    seen = {}

    def whole_window(d):
        seen["readings"] = [c["label"] for c in d.choices]
        seen["modes"] = [d.unlabelled.itemText(i)
                         for i in range(d.unlabelled.count())]
        d.raster.setCurrentIndex(d.raster.findData(scene.id()))
        # what the window offers to begin with, then what the tutorial says:
        # untick the painted image, leave the mask, tick the card
        seen["defaults"] = {k: b.isChecked() for k, b in d.want.items()}
        d.want["painted"].setChecked(False)
        d.want["card"].setChecked(True)
        seen["ticked"] = sorted(k for k, b in d.want.items() if b.isChecked())
        d.reading.setCurrentIndex(d.reading.findText("ANNA, pass 1"))
        d.unlabelled.setCurrentIndex(d.unlabelled.findData("ignore"))
        d.ignore_value.setValue(255)
        d.describe()
        seen["note"] = d.unlabelled_note.text()
        d.folder.setText(whole)
        return 1

    K.ANSWERS["WholeRaster"] = whole_window
    del K.BOXES[:]
    cut.export_whole()
    wfiles = sorted(os.listdir(whole)) if os.path.isdir(whole) else []
    nums["whole_files"] = wfiles
    mask_path = next((os.path.join(whole, f) for f in wfiles
                      if f.endswith("_mask.tif")), None)
    check("the window starts with the painted image and the mask ticked, "
          "and the card not", seen["defaults"] == {
              "painted": True, "mask": True, "plain": False, "figure": False,
              "card": False}, seen["defaults"])
    check("the tutorial's choice leaves the mask and the card",
          seen["ticked"] == ["card", "mask"], seen["ticked"])
    stem = "example_scene_rgb_ANNA_p1_ign255"
    check("and writes the files the tutorial lists, no more",
          wfiles == sorted([stem + "_card.json", stem + "_card.md",
                            stem + "_mask.qml", stem + "_mask.stac.json",
                            stem + "_mask.tif", stem + "_mask.tif.aux.xml"]),
          wfiles)
    check("Whole raster wrote the mask of ANNA, pass 1", mask_path is not None
          and "ANNA_p1" in mask_path, (wfiles, K.BOXES[-2:]))
    check("and the card beside it", any(f.endswith("_card.md")
                                        for f in wfiles), wfiles)
    check("the window offered the three ways of the ignore value",
          seen["modes"] == ["0, as before", "the ignore value everywhere",
                            "0 in the frames, the ignore value outside"],
          seen["modes"])
    if mask_path:
        ds = gdal.Open(mask_path)
        band = ds.GetRasterBand(1)
        mask = band.ReadAsArray()
        nums["mask"] = {
            "size": [ds.RasterXSize, ds.RasterYSize],
            "nodata": band.GetNoDataValue(),
            "values": {int(v): int(n) for v, n in zip(
                *np.unique(mask, return_counts=True))}}
        band = None
        ds = None
        check("the mask declares 255 as nodata", nums["mask"]["nodata"] == 255,
              nums["mask"]["nodata"])
        painted = int((mask != 255).sum())
        check("only the two frames are labelled: 2 x 60 x 60 pixels",
              painted == 2 * 60 * 60, painted)
        check("every pixel of them has a class, and none is 0",
              not (mask == 0).any(), nums["mask"]["values"])
        check("everything else, ten frames and the ground between, is 255",
              int((mask == 255).sum()) == mask.size - painted)
    out["files"]["whole"] = whole

    # -------------------------------------------------- 10. Cutouts
    say("== Cutouts, on the scene and the mask")
    cuts = os.path.join(work, "cutouts")
    mask_layer = K.layer_of(mask_path, "ANNA_p1_mask", show=False)

    def layers_window(d):
        for layer, role, band, rgb, tag, _, shape in d.rows:
            if layer.id() == scene.id():
                role.setCurrentText("image")
            elif layer.id() == mask_layer.id():
                role.setCurrentText("classes")
            else:
                role.setCurrentText("ignore")
        d.grid_from.setCurrentIndex(d.grid_from.findData(scene.id()))
        return 1

    K.ANSWERS["CutoutSetup"] = layers_window
    cut.pick_layers()
    cut.folder_box.setText(cuts)
    cut.folder_changed()
    cut.side.setValue(30.0)
    cut.ignore_on.setChecked(True)
    cut.ignore_value.setValue(255)
    check("the layers are chosen: the scene as image, the mask as classes",
          [(s["tag"], s["role"]) for s in cut.sources] ==
          [("scene_rgb", "image"), ("ANNA_p1_mask", "classes")],
          [(s["tag"], s["role"]) for s in cut.sources])
    for t in ("t001", "t002"):
        f = [f for f in section.all_tiles() if f["tile_id"] == t][0]
        centre = f.geometry().boundingBox().center()
        ok = cut.export(cut.square_at(QgsPointXY(centre.x(), centre.y())),
                        quiet=False, tile_id=t,
                        nominal=float(f["side_m"]))
        check("a cutout of %s" % t, ok)
    cfiles = sorted(os.listdir(cuts)) if os.path.isdir(cuts) else []
    nums["cutout_files"] = cfiles
    rows = read_csv(os.path.join(cuts, "cutouts.csv")) \
        if "cutouts.csv" in cfiles else []
    nums["cutouts"] = len(rows)
    check("two cutouts of two layers in cutouts.csv",
          len(rows) == 4 and {r["tile_id"] for r in rows} == {"t001", "t002"},
          rows[:1])
    check("the mask layer is written with an ignore_index of 255",
          [r["ignore_index"] for r in rows if r["role"] == "classes"]
          == ["255", "255"], [(r["role"], r["ignore_index"]) for r in rows])
    check("and a STAC catalogue", "stac" in cfiles, cfiles)
    out["files"]["cutouts"] = cuts
    panel.toggle_module(3)

    # ------------------------------------- 11. The Processing route
    say("== Processing: rasterlabel:agreement")
    result = processing_agreement(camp, work)
    if result is not None:
        nums["processing"] = result
        check("the same agreement as the panel's, the same seed",
              nums.get("compare") and abs(
                  result["OVERALL"] - nums["compare"]["overall"]) < 1e-9,
              (result.get("OVERALL"), nums.get("compare")))

    if panel.section is not None:
        panel.close_module()
    panel.close_campaign()
    app_events()

    # ---------------------------------------------- 12. Correct
    say("== Correct on model_map.tif, classes from the map")
    model_layer = K.layer_of(os.path.join(example, "model_map.tif"),
                             "model_map")
    seen = {}

    def correction_window(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText("example correction")
        d.raster.setCurrentIndex(d.raster.findData(model_layer.id()))
        d.fill_bands()
        seen["bands"] = [d.band.itemText(i) for i in range(d.band.count())]
        d.band.setCurrentIndex(d.band.findData(1))
        d.folder.setText(corr)
        d.operator.setText(ANNA)
        return 1

    def confirm_window(d):
        seen["classes"] = [(c["code"], c["name"], c["colour"])
                           for c in d.reading]
        seen["nodata"] = d.nodata
        d.accept()
        return 1

    untouched = digests(example)
    K.ANSWERS["OpenCorrection"] = correction_window
    K.ANSWERS["ConfirmClasses"] = confirm_window
    panel.new_correction_campaign()
    fix = panel.section
    check("Correct opens", type(fix).__name__ == "CorrectionSection",
          (K.BOXES[-3:], K.UNEXPECTED))
    check("Correct is open already after New, and its button is pressed",
          panel.open_index == 1 and panel.modules[1].isChecked()
          and panel.correction is not None)
    check("the class band offered is band 1, 'class'",
          seen["bands"][0].startswith("band 1") and "class" in seen["bands"][0]
          and "probability" in seen["bands"][1], seen.get("bands"))
    check("the classes were read from the map: the names of its category "
          "table", [(c[0], c[1]) for c in seen["classes"]] ==
          [(c["code"], c["name"]) for c in classes], seen["classes"])
    check("and its colours", [c[2].lower() for c in seen["classes"]] ==
          [c["colour"].lower() for c in classes], seen["classes"])
    nums["correction_classes"] = seen["classes"]
    copy = fix.path
    check("the working copy is <map>_corrected.tif in the folder chosen",
          os.path.basename(copy) == "model_map_corrected.tif"
          and os.path.dirname(copy) == corr, copy)
    check("the map it started from is untouched, and so are the files "
          "beside it", digests(example) == untouched, "changed")

    # the uncertainty card: band 2
    hook = g["unc_hook_of"](fix)
    card = hook.card
    check("the UNCERTAINTY card suggests band 2",
          card.line.text().startswith('band 2 "probability x255"'),
          card.line.text())
    card.use_it()
    K.app.processEvents()
    nums["uncertainty_line"] = card.line.text()
    nums["places"] = hook.places.N
    check("Use it: the uncertainty is read once beside the copy",
          os.path.isfile(os.path.join(corr,
                                      "model_map_corrected_uncertainty.tif")))

    say("== a few strokes, place by place")
    steps = [
        # the west half of the big pond: the model said vegetation
        (2, 3, px_polygon([(420, 84), (448, 84), (448, 140), (420, 140)])),
        # a stretch of the channel the model missed
        (1, 3, channel_gap(110, 185)),
        (1, 3, channel_gap(385, 440)),
        # the oblong pond the model took for ground
        (1, 3, px_polygon(ME.outlines()[object_index(3, (338, 316))][1])),
        # a roof it missed
        (1, 4, px_rect(404, 288, 438, 312)),
    ]
    card.next()                                    # Start
    K.app.processEvents()
    changed = []
    for k, (from_code, into, geom) in enumerate(steps):
        fix.choose_from(from_code)
        fix.choose_class(into)
        before = fix.operations
        fix.paint(geom)
        changed.append(fix.operations - before)
        if k in (1, 3):
            card.next()                            # Done, next
            K.app.processEvents()
    fix.choose_from(None)
    check("every stroke changed pixels", all(n == 1 for n in changed),
          changed)
    fix.save()
    check("Save wrote correction.json, the changes and operations.csv",
          all(os.path.isfile(os.path.join(corr, f)) for f in (
              "correction.json", "model_map_corrected.tif",
              "model_map_corrected_changes.tif", "operations.csv")),
          sorted(os.listdir(corr)))
    with io.open(os.path.join(corr, "operations.csv"), encoding="utf-8",
                 newline="") as fh:
        ops = list(csv.reader(fh))
    nums["operations"] = len(ops) - 1
    check("operations.csv: one row a stroke", len(ops) - 1 == len(steps),
          len(ops))
    nums["correction_files"] = sorted(os.listdir(corr))
    after = band_of(copy)
    truth = ME.scene_truth()
    wrong_before = band_of(os.path.join(example, "model_map.tif")) != truth
    nums["wrong_px_before"] = int(wrong_before.sum())
    nums["wrong_px_after"] = int((after != truth).sum())
    check("the strokes took pixels off the map's errors",
          nums["wrong_px_after"] < nums["wrong_px_before"], nums)

    # -------------------- 13. Measure > Model vs corrected, Uncertainty
    say("== Measure > Model vs corrected")
    menu = panel.c_measure.menu()
    labels = [a.text() for a in menu.actions() if a.text()]
    check("the Measure menu of a correction", labels == [
        "Model vs corrected…", "Uncertainty report…", "Time…",
        "Dataset card…"], labels)
    nums["menu_correction"] = labels
    seen = {}
    scope = {"which": "whole"}

    def mvc_setup(d):
        getattr(d, scope["which"]).setChecked(True)
        d.refresh()
        seen[scope["which"]] = {"whole": d.whole_note.text(),
                                "swept": d.swept_note.text()}[scope["which"]]
        seen["go"] = d.go.text()
        return 1

    for which in ("whole", "swept"):
        scope["which"] = which
        K.ANSWERS["ModelVsCorrectedSetup"] = mvc_setup
        expect_window()
        result = g["mvc_start"](panel)
        check("Model vs corrected ran on %s" % which, result is not None,
              (K.BOXES[-3:], K.UNEXPECTED))
        if result is None:
            continue
        o = result["summarized"]["metrics"]["overall"]
        nums["model_vs_corrected_" + which] = {
            "scope": result["scope"], "pixels": result["summarized"]["n"],
            "agree": o["po"], "quantity": o["quantity"],
            "allocation": o["allocation"], "mean_iou": o["mean_iou"]}
        nums["mvc_files"] = sorted(os.listdir(result["folder"]))
        check("under reports/model_vs_corrected/ of the correction",
              os.path.dirname(result["folder"]) == os.path.join(
                  corr, "reports", "model_vs_corrected"), result["folder"])
        check("the model agrees with the corrected map on less than 100 %",
              0.0 < o["po"] < 1.0, o)
        out["files"]["mvc_" + which] = result["folder"]
    nums["mvc_notes"] = {k: v for k, v in seen.items() if k != "go"}
    check("the key of the window is Compare", seen.get("go") == "Compare",
          seen.get("go"))

    say("== Uncertainty")
    card.next()
    K.app.processEvents()
    expect_window()
    result = g["unc_report_start"](panel)
    check("the Uncertainty report ran", result is not None,
          (K.BOXES[-3:], K.UNEXPECTED))
    if result is not None:
        s = result["summary"]
        nums["uncertainty"] = s.get("headline")
        nums["uncertainty_files"] = sorted(os.listdir(result["folder"]))
        check("under reports/uncertainty/ of the correction",
              os.path.dirname(result["folder"]) == os.path.join(
                  corr, "reports", "uncertainty"), result["folder"])
        out["files"]["uncertainty"] = result["folder"]
    out["figures"].append(fig("correct_uncertainty.png"))
    panel.setMinimumWidth(0)
    panel.setMaximumWidth(16777215)
    shot(panel, fig("correct_uncertainty.png"), 340)
    panel.setMinimumWidth(0)
    panel.setMaximumWidth(16777215)

    say("== Measure > Dataset card (of the correction)")
    del K.BOXES[:]
    result = g["card_start_correction"](panel)
    check("the card of the correction is written", result is not None,
          K.BOXES[-2:])
    if result is not None:
        nums["card_files"] = sorted(os.path.basename(f)
                                    for f in result["files"])
        check("under reports/card/ of the correction",
              os.path.dirname(result["folder"]) == os.path.join(
                  corr, "reports", "card"), result["folder"])
        out["files"]["card"] = result["folder"]

    check("no window was left unanswered", not K.UNEXPECTED, K.UNEXPECTED)
    K.close_panel(panel)
    return out


def band_of(path, number=1):
    """One band of a raster as an array (the dataset is kept until read)."""
    ds = gdal.Open(path)
    try:
        return ds.GetRasterBand(number).ReadAsArray()
    finally:
        ds = None


def digests(folder):
    """{name: sha256} of the files of a folder, to see that nothing moved."""
    out = {}
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                out[name] = hashlib.sha256(fh.read()).hexdigest()
    return out


def app_events():
    K.app.processEvents()


def channel_gap(lo, hi):
    """The channel between two columns, as a polygon of pixels."""
    xs = np.linspace(lo, hi, 40)
    row, half = ME.channel_centre(xs)
    top = [(float(x), float(r - h - 1.0)) for x, r, h in zip(xs, row, half)]
    low = [(float(x), float(r + h + 1.0)) for x, r, h in zip(xs, row, half)]
    return px_polygon(top + low[::-1])


def processing_agreement(camp, work):
    """processing.run("rasterlabel:agreement", {...}) on the campaign."""
    import qgis
    from qgis.core import QgsApplication
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(qgis.__file__))), "plugins"))
    import processing
    from processing.core.Processing import Processing
    Processing.initialize()
    import rasterlabel
    plugin = rasterlabel.classFactory(None)
    plugin.initProcessing()
    try:
        out = processing.run("rasterlabel:agreement", {
            "CAMPAIGN": os.path.join(camp, "campaign.json"),
            "READING_A": "ANNA,1", "READING_B": "BRUNO,1",
            "FRAMES": 0, "POINTS_IN": False, "RESAMPLES": 2000, "SEED": 1,
            "ALLOW_UNFINISHED": False,
            "OUTPUT_FOLDER": os.path.join(work, "processing_agreement")})
    finally:
        plugin.unload()
        check("the provider is taken away again",
              QgsApplication.processingRegistry().providerById(
                  "rasterlabel") is None)
    return {k: out[k] for k in ("OVERALL", "KAPPA", "QUANTITY",
                                "ALLOCATION", "MEAN_IOU", "FRAMES_USED")}


def main(argv):
    figures = None
    if "--figures" in argv:
        figures = os.path.abspath(argv[argv.index("--figures") + 1])
    keep = os.path.abspath(argv[argv.index("--keep") + 1])         if "--keep" in argv else None
    work = keep or tempfile.mkdtemp(prefix="rl_tutorial_walk_")
    if keep:
        os.makedirs(keep, exist_ok=True)
    try:
        out = walk(work, figures)
        said()
        said("numbers")
        for key, value in out["numbers"].items():
            said("  %-22s %s" % (key, json.dumps(value, default=str)))
        for path in out["figures"]:
            if os.path.isfile(path):
                said("  figure %s, %d bytes" % (os.path.relpath(path, ROOT)
                                                if figures else
                                                os.path.basename(path),
                                                os.path.getsize(path)))
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    K.finish()


if __name__ == "__main__":
    main(sys.argv)
