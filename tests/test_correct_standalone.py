"""Correct from an empty panel: no annotation campaign, a correction of its own.

Correct used to be a part of the annotation campaign. Its button stayed grey
until a campaign was open, its record was a line of campaign.json, and its
copy went into a folder of the campaign's. A thematic map made by another
program could not be corrected without first making a campaign of hand
drawing nobody wanted. And the classes it read from the map were used
without being shown: a wrong reading was found out as wrong chips, after the
copy existed.

So this suite starts from a panel with a raster and nothing else, presses
Correct, and walks the whole way:

  the window asks for a new correction campaign, a thematic map and a folder;
  the classes are read and SHOWN, value, colour and name, and the window
  refuses a repeated name, a value the map holds left without a class, and
  the nodata value; the user's edits are what the correction uses;
  cancelling there writes nothing at all;
  the copy is made in the chosen folder with correction.json beside it, and
  no campaign.json is written anywhere;
  a stroke changes the copy, never the map, and its area is measured on the
  map's own pixel, not a campaign's;
  operations.csv and the log are beside the manifest, the operator on every
  row;
  going to another module closes the correction, as Close does: its layer
  leaves the project and nothing holds the working copy any more;
  closing takes the layer out and lets go of the log; opening it again from
  the list of recent corrections shows the same classes and the same count;
  the Classes button opens the same window with the values the copy holds
  locked;
  a folder that already holds a correction and a map that is already a
  working copy are refused before anything is written;
  Set aside moves the folder and forgets it.

Needs PyQt5 or PyQt6, and numpy. Not GDAL: see correctkit.py.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correctkit as K                                             # noqa: E402
import numpy as np                                                 # noqa: E402

g, check = K.g, K.check

WATER, CROPS, ROADS, FOREST, NODATA = 0, 3, 7, 12, 255
MAP = np.array([
    [WATER, WATER, CROPS, CROPS, CROPS, ROADS, FOREST, FOREST],
    [WATER, WATER, CROPS, CROPS, CROPS, ROADS, FOREST, FOREST],
    [WATER, CROPS, CROPS, NODATA, NODATA, ROADS, FOREST, FOREST],
    [CROPS, CROPS, CROPS, NODATA, NODATA, ROADS, ROADS, FOREST],
    [CROPS, CROPS, ROADS, ROADS, ROADS, ROADS, FOREST, FOREST],
    [CROPS, CROPS, ROADS, FOREST, FOREST, FOREST, FOREST, FOREST],
], dtype=np.uint8)

root = tempfile.mkdtemp(prefix="rl_correct_free_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
data = os.path.join(root, "data")
source = os.path.join(data, "landcover_model.tif")
K.write_map(source, MAP, NODATA)          # a pixel of 2 m, on a UTM grid
styled = K.Paletted(None, 1, [
    K.Paletted.Class(WATER, "#1f78b4", "water"),
    K.Paletted.Class(CROPS, "#e6c229", "crops"),
    K.Paletted.Class(ROADS, "#444444", "roads"),
    K.Paletted.Class(FOREST, "#1b7f2a", "forest")])
thematic = K.add_layer(K.Layer(source, "landcover", styled))
folder = os.path.join(root, "my corrections", "landcover_fix")
before_source = K.read_map(source)

panel = g["Panel"]()
check("the panel opens with no campaign", panel.campaign is None)
check("and says so under ANNOTATION CAMPAIGN",
      panel.campaign_state.text() == "no annotation campaign open",
      panel.campaign_state.text())
check("CORRECTION says no correction is open",
      panel.correction_state.text() == "no correction open",
      panel.correction_state.text())
check("its New can be pressed, and Close, Classes and Check cannot",
      panel.c_new.isEnabled() and panel.c_open.isEnabled()
      and not panel.c_close.isEnabled() and not panel.c_classes.isEnabled()
      and not panel.c_check.isEnabled())
check("Correct is enabled with no campaign open", panel.modules[1].isEnabled())

# ------------------------------------------------------- the classes window
SEEN = {}


def new_campaign(d):
    """The first window: a new correction campaign on the landcover map."""
    SEEN["choices"] = [d.existing.itemText(i) for i in range(d.existing.count())]
    SEEN["intro"] = " ".join(w.text() for w in d.findChildren(K.QtWidgets.QLabel))
    d.existing.setCurrentIndex(d.existing.findData("new:"))
    d.name.setText("landcover fix")
    d.raster.setCurrentIndex(d.raster.findData(thematic.id()))
    d.fill_bands()
    d.folder.setText(folder)
    d.operator.setText("ann")
    SEEN["enabled"] = d.name.isEnabled() and d.folder.isEnabled()
    return 1


def rows_of(d):
    return [(r["value"].value(), r["swatch"].property("colour"),
             r["name"].text(), r["pixels"].text(), r["origin"].text())
            for r in d.rows]


def confirm_with_edits(d):
    """The second window: look, try three wrong things, then fix two."""
    SEEN["read"] = rows_of(d)
    SEEN["title"] = d.windowTitle()
    SEEN["words"] = " ".join(w.text() for w in d.findChildren(K.QtWidgets.QLabel))
    by_value = {r["value"].value(): r for r in d.rows}
    # a repeated name
    by_value[ROADS]["name"].setText("crops")
    SEEN["twice"] = d.complaints()
    by_value[ROADS]["name"].setText("roads")
    # a value the map holds, left with no row: renumber forest to 13
    by_value[FOREST]["value"].setValue(13)
    SEEN["missing"] = d.complaints()
    SEEN["moved_count"] = by_value[FOREST]["pixels"].text()
    # the nodata value as a class
    by_value[FOREST]["value"].setValue(NODATA)
    SEEN["nodata"] = d.complaints()
    by_value[FOREST]["value"].setValue(FOREST)
    # what the user really changes: a name and a colour
    by_value[CROPS]["name"].setText("wheat")
    by_value[FOREST]["swatch"].setProperty("colour", "#ff00ff")
    # and a class the map does not hold yet
    d.add_blank()
    d.rows[-1]["name"].setText("burnt")
    SEEN["added"] = rows_of(d)[-1]
    SEEN["clean"] = d.complaints()
    return 1


try:
    print("cancelling the classes window writes nothing")
    K.ANSWERS["OpenCorrection"] = new_campaign
    K.ANSWERS["ConfirmClasses"] = lambda d: 0
    panel.toggle_module(1)
    check("no module is open", panel.section is None and panel.correction is None)
    check("and the folder was not even made", not os.path.exists(folder))
    check("the map was only read", np.array_equal(K.read_map(source),
                                                 before_source))

    print()
    print("a new correction campaign, from an empty panel")
    K.ANSWERS["OpenCorrection"] = new_campaign
    K.ANSWERS["ConfirmClasses"] = confirm_with_edits
    panel.toggle_module(1)
    section = panel.section
    check("Correct opened", type(section).__name__ == "CorrectionSection",
          type(section).__name__)
    check("the first window offered a new correction campaign",
          any("new correction campaign" in c for c in SEEN["choices"]),
          SEEN["choices"])
    check("and said it needs no annotation campaign",
          "It needs no annotation campaign" in SEEN["intro"])
    check("its fields could be filled", SEEN["enabled"])

    print()
    print("the classes were shown before anything was made")
    check("in a window called Classes of the map",
          SEEN["title"] == "RasterLabel: Classes of the map", SEEN["title"])
    check("one row per class of the style, with its value, colour and name",
          [(v, c, n) for v, c, n, _, _ in SEEN["read"]] ==
          [(WATER, "#1f78b4", "water"), (CROPS, "#e6c229", "crops"),
           (ROADS, "#444444", "roads"), (FOREST, "#1b7f2a", "forest")],
          SEEN["read"])
    check("each says where it came from", all(o == "style" for *_, o in SEEN["read"]))
    check("and how many pixels it holds",
          SEEN["read"][1][3].startswith("%d " % int((MAP == CROPS).sum())),
          SEEN["read"][1])
    check("nodata is not a row", NODATA not in [r[0] for r in SEEN["read"]])
    check("the window says the legend is not used, and that no pixel is "
          "recoded", "The campaign legend is not used" in SEEN["words"]
          and "no pixel is recoded" in SEEN["words"])
    check("a repeated name is refused",
          any("'crops' is used twice" in c for c in SEEN["twice"]),
          SEEN["twice"])
    check("a value the map holds left without a row is refused",
          any("value 12 is in the map and has no class" in c
              for c in SEEN["missing"]), SEEN["missing"])
    check("and a renumbered row says it holds nothing in the map",
          SEEN["moved_count"] == "not in the map", SEEN["moved_count"])
    check("the nodata value as a class is refused, with the old words",
          any("255 is the nodata value of this map" in c for c in SEEN["nodata"]),
          SEEN["nodata"])
    check("Add class gives the next free value",
          SEEN["added"][0] == FOREST + 1 and SEEN["added"][4] == "added",
          SEEN["added"])
    check("with the edits made the window has nothing to say", not SEEN["clean"],
          SEEN["clean"])

    print()
    print("the correction campaign on disk")
    manifest = os.path.join(folder, "correction.json")
    check("correction.json is in the folder that was chosen",
          os.path.exists(manifest), K.everything_under(root))
    book = json.load(open(manifest, encoding="utf-8"))
    check("it says what it is", book.get("kind") == "correction"
          and book.get("program") == "RasterLabel" and book.get("format") == 1)
    check("the working copy is named relative to the folder",
          book.get("working_copy") == "landcover_model_corrected.tif"
          and os.path.exists(os.path.join(folder, book["working_copy"])),
          book.get("working_copy"))
    check("the classes are the confirmed ones, edits and all",
          [(c["code"], c["name"], c["colour"]) for c in book["classes"]] ==
          [(WATER, "water", "#1f78b4"), (CROPS, "wheat", "#e6c229"),
           (ROADS, "roads", "#444444"), (FOREST, "forest", "#ff00ff"),
           (FOREST + 1, "burnt", book["classes"][-1]["colour"])],
          book["classes"])
    check("and when they were confirmed", bool(book.get("classes_confirmed")))
    check("the grid is the map's own: a pixel of 2 m",
          book["grid"]["pixel_m"] == [2.0, 2.0]
          and book["grid"]["origin"] == [500000.0, 4100000.0]
          and book["grid"]["size"] == [8, 6], book["grid"])
    check("the operator, in capitals", book.get("operator") == "ANN")
    check("the chips are the confirmed classes",
          [b.text() for b in section._buttons if b.text() != "+"] ==
          ["water", "wheat", "roads", "forest", "burnt"],
          [b.text() for b in section._buttons])
    check("no campaign.json was written anywhere",
          not [f for f in K.everything_under(root) if "campaign.json" in f],
          K.everything_under(root))
    check("the panel still has no annotation campaign", panel.campaign is None)
    check("the head of the module says correction campaign",
          "correction campaign" in section.head.text(), section.head.text())
    check("and its tooltip says where", folder in section.head.toolTip())

    print()
    print("a stroke, on the copy")
    copy = os.path.join(folder, "landcover_model_corrected.tif")
    inside = np.zeros((2, 3), bool)
    inside[:, :] = True
    section.mask_of = lambda geom: (2, 0, inside)       # rows 0-1, cols 2-4
    section.choose_from(CROPS)
    section.choose_class(FOREST)
    section.paint(K.Stroke())
    after = K.read_map(copy)
    check("the crops under the stroke became forest",
          (after[0:2, 2:5] == FOREST).all(), after[0:2])
    check("nothing else changed",
          int((after != MAP).sum()) == 6, int((after != MAP).sum()))
    check("the map it started from is untouched",
          np.array_equal(K.read_map(source), before_source))
    check("the copy is the map, band for band: nothing added to it",
          len(K.DISK[K.key(copy)]["bands"]) == len(K.DISK[K.key(source)]["bands"]))
    changes = os.path.join(folder, "landcover_model_corrected_changes.tif")
    flag = K.read_map(changes)
    check("the file beside it remembers the six pixels, and only them",
          int(flag.sum()) == 6 and (flag[0:2, 2:5] == 1).all(), flag)
    check("the manifest names that file",
          json.load(open(manifest, encoding="utf-8")).get("changes")
          == "landcover_model_corrected_changes.tif")
    style = os.path.join(folder, "landcover_model_corrected.qml")
    text = open(style, encoding="utf-8").read() if os.path.exists(style) else ""
    check("the .qml QGIS opens the corrected map with is beside it, paletted "
          "on the class band with the confirmed classes",
          'type="paletted"' in text and 'band="1"' in text
          and 'value="13"' in text and 'label="burnt"' in text
          and 'value="3" color="#e6c229" alpha="255" label="wheat"' in text,
          text)
    book = json.load(open(manifest, encoding="utf-8"))
    check("the manifest counts one operation", book["operations"] == 1)
    check("and 24 m2: six pixels of 2 m by 2 m, the map's own pixel",
          abs(book["changed_m2"] - 24.0) < 1e-9, book["changed_m2"])
    ops = os.path.join(folder, "operations.csv")
    rows = open(ops, encoding="utf-8").read().splitlines()
    check("operations.csv is beside the manifest, one row and a header",
          len(rows) == 2, rows)
    check("the row carries the operator and the classes",
          ",ANN,forest,wheat," in rows[1], rows[1])
    log_file = os.path.join(folder, "rasterlabel.log")
    check("the log is written beside the correction",
          os.path.exists(log_file) and g["_LOG"]["path"] == log_file,
          g["_LOG"]["path"])

    print()
    print("CORRECTION says which correction is open")
    check("its name and its classes",
          "landcover_fix" in panel.correction_state.text()
          and "5 classes" in panel.correction_state.text(),
          panel.correction_state.text())
    check("New and Open wait, Close, Classes and Check can be pressed",
          not panel.c_new.isEnabled() and not panel.c_open.isEnabled()
          and panel.c_close.isEnabled() and panel.c_classes.isEnabled()
          and panel.c_check.isEnabled())
    check("Classes is no longer a button of the module",
          "Classes" not in [b.text() for b in section.findChildren(
              K.QtWidgets.QPushButton)])

    print()
    print("going to another module closes the correction")
    # It used to stay open behind the other module, its layer in the
    # project and the working copy held by it, which on Windows cannot then
    # be moved or renamed. The author's rule: the correction lives as long
    # as Correct does, exactly as if Close had been pressed.
    book_id = panel.correction.data["id"]
    dropped = []
    take_out = g["drop_layers"]
    g["drop_layers"] = lambda cid, group: dropped.append(cid) or take_out(
        cid, group)
    panel.toggle_module(3)
    check("Cutouts opens and the correction is closed",
          type(panel.section).__name__ == "CutoutsSection"
          and panel.correction is None)
    check("its layer left the project", dropped == [book_id], dropped)
    check("CORRECTION says no correction is open",
          panel.correction_state.text() == "no correction open")
    check("New and Open can be pressed again, Close, Classes and Check not",
          panel.c_new.isEnabled() and panel.c_open.isEnabled()
          and not panel.c_close.isEnabled() and not panel.c_classes.isEnabled()
          and not panel.c_check.isEnabled())
    check("and the grey ones say why",
          all(b.toolTip().startswith("No correction is open: press New or "
                                     "Open here, or Correct.")
              for b in (panel.c_close, panel.c_classes, panel.c_check)),
          panel.c_classes.toolTip())
    check("Classes with nothing open opens nothing",
          panel.correction_classes() is None and panel.section is not None
          and type(panel.section).__name__ == "CutoutsSection")
    check("the log left the correction's folder",
          g["_LOG"]["path"] != log_file, g["_LOG"]["path"])
    moved = copy + ".moved"
    os.rename(copy, moved)
    os.rename(moved, copy)
    check("and nothing holds the working copy: it can be renamed",
          os.path.exists(copy))
    check("the files stay", os.path.exists(manifest) and os.path.exists(copy))

    print()
    print("opening again, and Close")
    panel.close_module()
    check("the log lets go: no campaign and no correction is open",
          g["_LOG"]["path"] is None, g["_LOG"]["path"])

    def reopen(d):
        SEEN["start"] = (d.windowTitle(), d.existing.currentIndex())
        SEEN["again"] = [(d.existing.itemText(i), d.existing.itemData(i))
                         for i in range(d.existing.count())]
        d.existing.setCurrentIndex(0)
        SEEN["fields_off"] = not d.name.isEnabled() and not d.folder.isEnabled()
        return 1

    K.ANSWERS["OpenCorrection"] = reopen
    K.ASKED.clear()
    panel.open_correction_campaign()
    section = panel.section
    check("Open in CORRECTION opens the window on the recent ones",
          SEEN["start"] == ("RasterLabel: Open a correction", 0), SEEN["start"])
    check("Open in CORRECTION opens it in Correct",
          type(section).__name__ == "CorrectionSection"
          and panel.open_index == 1)
    check("it is first in the list of recent corrections",
          SEEN["again"][0][1] == "open:" + manifest
          and SEEN["again"][0][0].startswith("landcover_fix"), SEEN["again"])
    check("and the fields of a new one are off for it", SEEN["fields_off"])
    check("it opens with no classes window: they were confirmed already",
          "ConfirmClasses" not in K.ASKED[-1:], K.ASKED)
    check("the same classes", [c["name"] for c in section.classes()] ==
          ["water", "wheat", "roads", "forest", "burnt"])
    check("the same count", section.operations == 1)
    check("and the stroke is still in the copy",
          (K.read_map(copy)[0:2, 2:5] == FOREST).all())
    del dropped[:]
    panel.close_correction()
    check("Close in CORRECTION closes the module and the correction",
          panel.section is None and panel.correction is None
          and dropped == [book_id], dropped)
    check("and CORRECTION says so",
          panel.correction_state.text() == "no correction open")
    K.ASKED.clear()
    K.ANSWERS["OpenCorrection"] = reopen
    panel.toggle_module(1)
    check("Correct with nothing open asks which correction, and opens it",
          K.ASKED[:1] == ["OpenCorrection"] and type(panel.section).__name__
          == "CorrectionSection" and panel.correction is not None, K.ASKED)
    section = panel.section

    print()
    print("the Classes button: the same window, the copy's values locked")

    def reconfirm(d):
        SEEN["locked"] = {r["value"].value(): r["value"].isEnabled()
                          for r in d.rows}
        for r in d.rows:
            if r["value"].value() == ROADS:
                r["name"].setText("tracks")
        return 1

    K.ANSWERS["ConfirmClasses"] = reconfirm
    panel.correction_classes()
    check("Classes in CORRECTION opens the window on the correction open",
          type(panel.section).__name__ == "CorrectionSection"
          and "locked" in SEEN)
    section = panel.section
    check("every value the copy holds is locked",
          all(not SEEN["locked"][v] for v in (WATER, CROPS, ROADS, FOREST)),
          SEEN["locked"])
    check("the class it does not hold can still be renumbered",
          SEEN["locked"][FOREST + 1], SEEN["locked"])
    book = json.load(open(manifest, encoding="utf-8"))
    check("the new name is in the manifest",
          [c["name"] for c in book["classes"]][2] == "tracks", book["classes"])
    check("and on the chip", "tracks" in [b.text() for b in section._buttons])

    print()
    print("refused before anything is written")
    panel.close_correction()
    listing = K.everything_under(root)

    def same_folder(d):
        SEEN["start"] = (d.windowTitle(), d.existing.currentData())
        new_campaign(d)
        return 1

    K.ANSWERS["OpenCorrection"] = same_folder
    K.BOXES.clear()
    panel.new_correction_campaign()
    check("New in CORRECTION opens the window on a new correction",
          SEEN["start"] == ("RasterLabel: New correction", "new:"), SEEN["start"])
    check("a folder that already holds a correction is refused",
          panel.section is None and any(
              "already holds the correction 'landcover_fix'" in t
              for _, t in K.BOXES), K.BOXES)
    check("and nothing was written", K.everything_under(root) == listing)

    copy_layer = K.add_layer(K.Layer(copy, "the copy"))

    def on_the_copy(d):
        new_campaign(d)
        d.raster.setCurrentIndex(d.raster.findData(copy_layer.id()))
        d.folder.setText(os.path.join(root, "second"))
        return 1

    asked = []

    def cancel(d):
        asked.append(d.text())
        return 0

    K.ANSWERS["OpenCorrection"] = on_the_copy
    K.ANSWERS["QMessageBox"] = cancel
    panel.toggle_module(1)
    check("a map that is already a working copy is refused",
          panel.section is None and any(
              "already the working copy of a correction" in t
              for t in asked), asked)
    check("and its folder was not made",
          not os.path.exists(os.path.join(root, "second")))
    K.LOADED.pop(copy_layer.id())

    print()
    print("Set aside moves the folder and forgets it")
    K.ANSWERS["OpenCorrection"] = reopen
    panel.toggle_module(1)
    section = panel.section
    section.delete()
    moved = [f for f in os.listdir(os.path.dirname(folder))
             if f.startswith("landcover_fix.removed-")]
    check("the folder is renamed, not erased", len(moved) == 1
          and os.path.exists(os.path.join(os.path.dirname(folder), moved[0],
                                          "correction.json")), moved)
    check("the module is closed, and the correction with it",
          panel.section is None and panel.correction is None)
    check("and CORRECTION says no correction is open",
          panel.correction_state.text() == "no correction open")
    # The log was written inside the folder that moved. Left pointing there,
    # the next line looked for a folder that was gone and the log gave up
    # with a warning in the QGIS log.
    check("the log no longer points into the folder that moved",
          g["_LOG"]["path"] is None and not g["_LOG"]["complained"],
          dict(g["_LOG"]))
    check("and nothing recreated the old folder", not os.path.exists(folder))
    check("and the correction is no longer offered",
          manifest not in g["recent_corrections"]())
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
