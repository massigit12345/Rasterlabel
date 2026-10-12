"""Time, in a real QGIS: the journal written while drawing, and the report.

What is checked, with the panel driven the way a person drives it:

- an old campaign opens as it was: opening it, opening Annotate and closing
  both writes no journal.csv and changes not a byte of its manifest;
- a new campaign has no "journal" block in its manifest, and gets none from
  opening Annotate, choosing a class or moving around; the first frame
  placed begins the journal, and only then is the block written, with the
  moment of its first row;
- the round brush, driven by presses, moves and releases as the canvas
  sends them, two strokes, one thrown away with Esc, a point and its undo:
  the journal's marks are, in order, two strokes, the discard, the point
  and the undo, each with its frame, its class, the operator and the pass,
  and the strokes with the time the stopwatch measured;
- the line under the coverage says the day's active time; unticking "keep a
  journal of working time" stops the rows and says "on": false in the
  manifest, and ticking it again starts them;
- Correct on the same grid: two strokes. operations.csv keeps exactly its
  14 columns and has 2 rows, tally_operations reads them as before, and
  journal.csv beside it has the two "correct" rows with ref 1 and 2;
  correction.json gets its block at the first stroke, not at the opening;
- TimeSetup written without a window: the five files, their headers,
  time_frames.gpkg with both frames, the thresholds 30, 60 and 120 in
  the summary, the pairing of the frame that was drawn and corrected, the
  report in the campaign's list and its map in QGIS;
- Time is grey in the Measure menu until the journal has begun.

Needs QGIS; tests/run.py skips it where QGIS is missing and, with
RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qgiskit as K  # noqa: E402
from qgis.core import QgsPointXY, QgsProject  # noqa: E402
from qgis.PyQt.QtCore import QPoint, Qt  # noqa: E402
from osgeo import ogr  # noqa: E402

g, check = K.g, K.check
MARKS = set(g["MARK_ACTIONS"])


class Ev(object):
    """A mouse event as the canvas hands it to a map tool, at a point of
    the map (the tools below read positions as map coordinates)."""

    def __init__(self, x, y, button=Qt.MouseButton.LeftButton,
                 mods=Qt.KeyboardModifier.NoModifier):
        self._pos = QPoint(int(x), int(y))
        self._button = button
        self._mods = mods

    def button(self):
        return self._button

    def buttons(self):
        return self._button

    def pos(self):
        return self._pos

    def modifiers(self):
        return self._mods


class Key(object):
    def __init__(self, key):
        self._key = key

    def key(self):
        return self._key


def on_map(tool):
    """Positions read as map coordinates, one pixel a metre: what the tool
    does with them is the same, and no window is needed to place them."""
    tool.toMapCoordinates = lambda p: QgsPointXY(p.x(), p.y())
    return tool


def manifest(folder, name="campaign.json"):
    with io.open(os.path.join(folder, name), encoding="utf-8") as fh:
        return json.load(fh)


def raw(path):
    with open(path, "rb") as fh:
        return fh.read()


def journal(folder):
    return g["journal_read"](os.path.join(folder, "journal.csv"))


def classes_rect(col0, row0, col1, row1):
    from qgis.core import QgsGeometry, QgsRectangle
    return QgsGeometry.fromRect(QgsRectangle(
        K.X0 + col0 + 0.01, K.Y0 - row1 + 0.01,
        K.X0 + col1 - 0.01, K.Y0 - row0 - 0.01))


root = tempfile.mkdtemp(prefix="rl_time_")
try:
    # one band of classes, 80 x 60 m in 1 m pixels: campaign and correction
    # on the same grid
    classes = K.layer_of(K.write_classes(os.path.join(root, "data",
                                                      "model.tif")))
    panel = K.new_panel()

    print("an old campaign opens as it was")
    old = os.path.join(root, "old")
    K.new_campaign(panel, old, classes, tiled=True, name="old campaign")
    panel.close_campaign()
    before = raw(os.path.join(old, "campaign.json"))
    K.open_campaign(panel, old)
    section = K.annotate(panel)
    section.choose_class("water")
    panel.close_module()
    panel.close_campaign()
    check("no journal.csv after opening, Annotate and closing",
          not os.path.exists(os.path.join(old, "journal.csv")))
    check("and the manifest is the same, byte for byte",
          raw(os.path.join(old, "campaign.json")) == before)

    print()
    print("a new campaign: no journal until there is something in it")
    camp = os.path.join(root, "camp")
    K.new_campaign(panel, camp, classes, tiled=True, name="time campaign")
    check("created with no journal block", "journal" not in manifest(camp))
    on, why = g["time_enabled"](panel)
    check("Time is grey, and says the journal has not begun",
          not on and "No journal yet" in why, why)
    section = K.annotate(panel)
    section.tile_side.setValue(10.0)
    section.radius.setValue(1.5)
    section.choose_class("mud")
    check("opening Annotate and choosing a class write nothing",
          "journal" not in manifest(camp)
          and not os.path.exists(os.path.join(camp, "journal.csv")))
    started = time.time()
    section.use_tile_tool()
    tiles = on_map(section.tile_tool)
    tiles.canvasPressEvent(Ev(K.X0 + 5, K.Y0 - 5))
    block = manifest(camp).get("journal")
    check("the first frame placed begins it: the block is written",
          isinstance(block, dict) and block.get("on") is True
          and block.get("file") == "journal.csv", block)
    since = g["effort_parse_utc"](block.get("since")) if block else None
    check("since the moment of its first row",
          since is not None and abs(since - started) < 120,
          (block, started))
    section.use_tile_tool()
    on_map(section.tile_tool).canvasPressEvent(Ev(K.X0 + 15, K.Y0 - 5))
    ids = sorted(f["tile_id"] for f in section.all_tiles())
    check("two frames", ids == ["t001", "t002"], ids)
    section.select_tile("t001")
    on, why = g["time_enabled"](panel)
    check("Time can now be chosen", on, why)

    print()
    print("the brush, as the canvas drives it")
    section.use_brush(round_=True)
    brush = on_map(section.brush)
    section.choose_class("mud")
    brush.canvasPressEvent(Ev(K.X0 + 2, K.Y0 - 3))
    time.sleep(0.05)
    brush.canvasMoveEvent(Ev(K.X0 + 7, K.Y0 - 3))
    time.sleep(0.05)
    brush.canvasReleaseEvent(Ev(K.X0 + 7, K.Y0 - 3))
    section.choose_class("water")
    brush.canvasPressEvent(Ev(K.X0 + 2, K.Y0 - 7))
    brush.canvasMoveEvent(Ev(K.X0 + 7, K.Y0 - 7))
    brush.canvasReleaseEvent(Ev(K.X0 + 7, K.Y0 - 7))
    brush.canvasPressEvent(Ev(K.X0 + 4, K.Y0 - 5))
    brush.keyPressEvent(Key(Qt.Key.Key_Escape))
    section.use_point_tool()
    on_map(section.point_tool).canvasPressEvent(Ev(K.X0 + 5, K.Y0 - 5))
    section.undo_stroke()
    rows = journal(camp)
    actions = [r["action"] for r in rows]
    check("the journal opens with the module", actions[:1] == ["open"],
          actions)
    check("the two frames placed are in it before the first stroke",
          actions.count("frame_new") == 2
          and actions.index("frame_new") < actions.index("under"), actions)
    marks = [r for r in rows if r["action"] in MARKS]
    check("the marks, in order: two strokes, the discard, the point, the "
          "undo", [r["action"] for r in marks]
          == ["under", "under", "discard", "point", "undo"],
          [r["action"] for r in marks])
    s1, s2 = marks[0], marks[1]
    check("each stroke with its frame, class, operator and pass",
          (s1["tile_id"], s1["class_code"], s1["operator"], s1["pass_no"])
          == ("t001", "1", "ANNA", "1")
          and (s2["tile_id"], s2["class_code"]) == ("t001", "2"),
          (s1, s2))
    check("and the time the stopwatch measured, from press to release",
          s1["dur_ms"] >= 90 and s1["tool"] == "round", s1)
    check("the stroke's ground and middle",
          float(s1["area_m2"] or 0) > 1 and s1["x"] and s1["y"], s1)
    check("the point is of its class, on its frame",
          (marks[3]["class_code"], marks[3]["tile_id"]) == ("2", "t001"),
          marks[3])
    check("one session, counted from 1",
          len({r["session"] for r in rows}) == 1
          and [r["seq"] for r in rows] == list(range(1, len(rows) + 1)))
    check("the quiet line says the day",
          section.time_line.text().startswith("active ")
          and "this frame" in section.time_line.text(),
          section.time_line.text())

    print()
    print("the switch in Annotate's settings")
    n = len(journal(camp))
    section.keep_journal.setChecked(False)
    check("unticked, the manifest says so",
          manifest(camp)["journal"]["on"] is False)
    section.use_brush(round_=True)
    section.paint(K.square(K.X0 + 1, K.Y0 - 9.5, 1.0), "mud")
    check("and nothing more is written but the close of the journal",
          [r["action"] for r in journal(camp)[n:]] == ["close"],
          [r["action"] for r in journal(camp)[n:]])
    check("the quiet line is gone", not section.time_line.isVisible()
          or not section.time_line.text())
    section.keep_journal.setChecked(True)
    check("ticked again, on again", manifest(camp)["journal"]["on"] is True)
    section.save()

    print()
    print("Correct on the same grid")

    def opened(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText("time fix")
        d.raster.setCurrentIndex(d.raster.findData(classes.id()))
        d.fill_bands()
        d.band.setCurrentIndex(d.band.findData(1))
        d.folder.setText(os.path.join(root, "corr"))
        d.operator.setText("bruno")
        return 1

    def confirm(d):
        d.accept()
        return 1
    K.ANSWERS["OpenCorrection"] = opened
    K.ANSWERS["ConfirmClasses"] = confirm
    panel.new_correction_campaign()
    fix = panel.section
    corr = os.path.join(root, "corr")
    if check("Correct opens", type(fix).__name__ == "CorrectionSection",
             (type(fix).__name__, K.BOXES[-3:], K.UNEXPECTED)):
        check("its manifest says nothing of a journal before a stroke",
              "journal" not in manifest(corr, "correction.json"))
        fix.choose_from(None)
        fix.choose_class(2)
        fix.paint(classes_rect(2, 2, 5, 5))
        check("the first stroke begins it",
              manifest(corr, "correction.json").get("journal", {})
              .get("on") is True)
        fix.paint(classes_rect(12, 2, 15, 5))
        fix.save()
        ops = os.path.join(corr, "operations.csv")
        with io.open(ops, encoding="utf-8", newline="") as fh:
            table = list(csv.reader(fh))
        check("operations.csv keeps its 14 columns",
              table[0] == fix.LOG_COLUMNS and len(table[0]) == 14, table[0])
        check("and has the two strokes", len(table) == 3, len(table))
        tally = g["tally_operations"](ops)
        check("tally_operations reads them as before",
              tally["operations"] == 2 and tally["operations"]
              == fix.operations
              and abs(tally["changed_m2"] - round(fix.changed_m2, 3)) < 1e-6,
              tally)
        crow = [r for r in journal(corr) if r["action"] == "correct"]
        check("journal.csv beside it: two correct rows, ref 1 and 2",
              [r["ref"] for r in crow] == ["1", "2"], crow)
        check("with the class written, FROM any and the operator",
              all(r["class_code"] == "2" and r["from_code"] == "0"
                  and r["operator"] == "BRUNO" and r["pass_no"] == ""
                  for r in crow), crow)
        check("journal.csv is the correction's own file",
              os.path.join(corr, "journal.csv") in fix.own_files()
              or "journal.csv" in fix.own_files(), fix.own_files())
        on, why = g["time_enabled_correction"](panel)
        check("Time in the correction's menu can be chosen", on, why)

    print()
    print("the report, written without a window")
    d = g["TimeSetup"](panel, panel.campaign,
                       correction=os.path.join(corr, "correction.json"),
                       owner="campaign", reading=panel.reading())
    d.live = panel.campaign
    chosen = [key for b, key in d.readings if b.isChecked()]
    check("the reading in hand is chosen", chosen == [("ANNA", 1)], chosen)
    check("the correction is on the same grid",
          "same grid" in d.grid_note.text(), d.grid_note.text())
    result = d.write()
    out = result["folder"]
    check("written under reports/time/", os.path.dirname(out)
          == os.path.join(camp, "reports", "time"), out)
    for name in ("time_per_frame.csv", "time_per_class.csv",
                 "time_paired.csv", "time_frames.gpkg", "time_summary.json",
                 "time_frames.qml"):
        check("%s is there" % name, os.path.isfile(os.path.join(out, name)))

    def header(name):
        with io.open(os.path.join(out, name), encoding="utf-8",
                     newline="") as fh:
            return next(csv.reader(fh))
    check("time_per_frame.csv has the columns the README names",
          header("time_per_frame.csv") == list(g["EFFORT_FRAME_COLUMNS"]),
          header("time_per_frame.csv"))
    check("time_per_class.csv too",
          header("time_per_class.csv") == list(g["EFFORT_CLASS_COLUMNS"]))
    check("and time_paired.csv",
          header("time_paired.csv") == list(g["EFFORT_PAIRED_COLUMNS"]))
    ds = ogr.Open(os.path.join(out, "time_frames.gpkg"))
    lyr = ds.GetLayerByName("time_frames") if ds is not None else None
    check("time_frames.gpkg holds both frames",
          lyr is not None and lyr.GetFeatureCount() == 2,
          lyr.GetFeatureCount() if lyr is not None else None)
    lyr = None
    ds = None
    with io.open(os.path.join(out, "time_summary.json"),
                 encoding="utf-8") as fh:
        summary = json.load(fh)
    check("the summary says the thresholds 30, 60 and 120",
          summary["parameters"]["thresholds"] == [30, 60, 120]
          and summary["parameters"]["idle_s"] == 60, summary["parameters"])
    check("and the rule, the version and the kind",
          "longer than 60 s" in summary["parameters"]["rule"]
          and summary["version"] == "1.1"
          and summary["rasterlabel:report"] == "time")
    check("the inputs with their sha256",
          all(i.get("sha256") for i in summary["inputs"])
          and any(i["path"].endswith("journal.csv")
                  for i in summary["inputs"]), summary["inputs"])
    paired = [r for r in result["paired"] if r["tile_id"] != "*"]
    check("the frame drawn and corrected is paired",
          [r["tile_id"] for r in paired] == ["t001"]
          and paired[0]["ratio_T"] > 0, result["paired"])
    by = {(r["source"], r["tile_id"]): r for r in result["frames"]}
    check("t001 drawn from scratch, with its time and closed or not",
          by[("scratch", "t001")]["active_s_T"] is not None
          and by[("scratch", "t001")]["journal"] == 1, by.get(
              ("scratch", "t001")))
    check("t002 corrected, with the ground it changed",
          by[("correct", "t002")]["changed_m2"] > 0
          and by[("correct", "t002")]["operator"] == "BRUNO",
          by.get(("correct", "t002")))
    check("the headline has the keys of the card",
          sorted(result["headline"]) == sorted(
              g["REPORT_HEADLINES"]["time"]), result["headline"])
    listed = [e for e in manifest(camp).get("reports", [])
              if e.get("kind") == "time"]
    check("the campaign's manifest lists the report",
          len(listed) == 1 and listed[0]["folder"].startswith("reports/time/"),
          listed)
    loaded = [l for l in QgsProject.instance().mapLayers().values()
              if l.customProperty("rasterlabel/report") == "time"]
    check("and its map is in QGIS", len(loaded) == 1, loaded)
    if loaded:
        check("styled in graduated colours from its .qml",
              loaded[0].renderer().type() == "graduatedSymbol",
              loaded[0].renderer().type())
    window = g["time_report_window"](panel, result)
    check("the report window says the frames and the time",
          "frames" in window.scope and "active" in window.scope,
          window.scope)
    window.deleteLater()

    print()
    print("a folder QGIS could not open the map in")
    # as Windows answers it, wherever this runs: a GeoPackage on 260
    # characters or more is not one SQLite opens
    real_problem = g["report_open_problem"]
    g["report_open_problem"] = lambda folder, names, windows=None:         real_problem(folder, names, True)
    try:
        deep = os.path.join(root, "t" * 120, "u" * 120)
        d = g["TimeSetup"](panel, panel.campaign,
                           correction=os.path.join(corr, "correction.json"),
                           owner="campaign", reading=panel.reading())
        d.live = panel.campaign
        check("Write can be pressed where the report fits",
              d.b_write.isEnabled() and not d.path_note.isVisibleTo(d),
              d.path_note.text())
        d.folder.setText(deep)
        check("a folder too deep greys Write, and the note says why",
              not d.b_write.isEnabled() and d.path_note.isVisibleTo(d)
              and "shorter folder" in d.path_note.text(),
              d.path_note.text())
        try:
            d.write()
            said = None
        except ValueError as err:
            said = str(err)
        check("and writing anyway is refused, in the same words",
              said == d.path_note.text(), said)
        check("before a folder is made",
              not os.path.exists(deep) and not os.path.exists(deep + ".tmp"))
        d.folder.setText("")
        check("an empty folder, the campaign's own place, is let be",
              d.b_write.isEnabled())
        d.deleteLater()
    finally:
        g["report_open_problem"] = real_problem
    check("no window was left unanswered", not K.UNEXPECTED, K.UNEXPECTED)
finally:
    try:
        K.close_panel(panel)
    except Exception:
        pass
    shutil.rmtree(root, ignore_errors=True)

K.finish()
