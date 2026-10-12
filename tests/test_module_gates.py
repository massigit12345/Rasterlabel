"""Which module needs what: Annotate and Objects an annotation campaign,
Correct and Cutouts only a raster. And which block each one lives in: the
annotation campaign holds Annotate and Objects, CORRECTION holds Correct with
buttons of its own, and Cutouts stands alone.

And every grey button says why in its tooltip, which Qt shows on a disabled
button: with no raster loaded, New of the annotation campaign, New of the
correction, Correct and Cutouts say "Load a raster first:" and where to load
it from; and the tooltips stay true with nothing open, a campaign, a
correction, and both.

All four buttons used to be enabled by one line, `b.setEnabled(open_campaign)`,
and toggle_module refused every one of them with no campaign open. Correct
keeps a campaign of its own now and Cutouts keeps none, so the two of them
must open on an empty panel, and Annotate and Objects must not: they draw
into the campaign's GeoPackage and there is none. And opening or closing a
campaign must not throw away a correction in progress, while Cutouts, which
reads the campaign for its frames and its drawing, is built again.

Needs PyQt5 or PyQt6, and numpy. Not GDAL: see correctkit.py.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correctkit as K                                             # noqa: E402
import numpy as np                                                 # noqa: E402

g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_gates_")
K.HOME[0] = root


def states(panel):
    return [b.isEnabled() for b in panel.modules]


def labels(panel):
    return [b.text() for b in panel.modules]


class Campaign:
    """An annotation campaign, as far as the panel and Cutouts read one."""
    def __init__(self, tiled=False):
        self.folder = os.path.join(root, "campaign")
        os.makedirs(self.folder, exist_ok=True)
        self.saves = 0
        self.data = {"id": "abc123", "name": "aragona_2025", "with_tiles": tiled,
                     "operator": "MG", "classes": [
                         {"code": 1, "name": "crust", "colour": "#b0651f"}],
                     "corrections": [], "cutouts": [],
                     "grid": {"pixel_m": [2.0, 2.0], "crs": "EPSG:32633",
                              "reference_raster": "",
                              "origin": [500000.0, 4100000.0]}}
    def active_classes(self): return self.data["classes"]
    def save(self): self.saves += 1
    @property
    def stem(self): return "aragona_2025"
    @property
    def group_name(self): return "RasterLabel: aragona_2025"
    def layer_name(self, table): return "%s_%s" % (self.stem, table)
    @property
    def package_path(self): return os.path.join(self.folder, "annotation.gpkg")


try:
    print("an empty panel, no raster")
    panel = g["Panel"]()
    check("the four modules are there, in order",
          labels(panel) == ["Annotate", "Correct", "Objects", "Cutouts"],
          labels(panel))
    check("with no raster none of them can open", states(panel) == [False] * 4,
          states(panel))
    LOAD = "Load a raster first: add it to the QGIS project (Layer > Add Layer"
    grey = {"Correct": panel.modules[1], "Cutouts": panel.modules[3],
            "New of ANNOTATION CAMPAIGN": panel.b_new,
            "New of CORRECTION": panel.c_new, "the raster list": panel.rasters}
    for name, w in grey.items():
        check("%s is grey and says to load a raster first" % name,
              not w.isEnabled() and w.toolTip().startswith(LOAD), w.toolTip())
    check("then what it does: the New of the campaign makes a campaign",
          panel.b_new.toolTip().endswith("Create a new annotation campaign."))
    check("and Open, which needs none, is not grey, and says what it opens",
          panel.b_open.isEnabled() and panel.c_open.isEnabled()
          and panel.b_open.toolTip().startswith("Open an annotation campaign"))
    check("New of the campaign says Open needs no raster",
          "Open needs none" in panel.b_new.toolTip())
    check("New of the correction: the raster is the map to correct, and Open "
          "needs none", "the thematic map to correct" in panel.c_new.toolTip()
          and "Open needs none" in panel.c_new.toolTip())
    check("Correct says the same, and what it does",
          "The raster for Correct is the thematic map" in
          panel.modules[1].toolTip() and panel.modules[1].toolTip().endswith(
              "needed."), panel.modules[1].toolTip())
    check("Annotate: a campaign, made on a raster loaded first",
          panel.modules[0].toolTip().startswith(
              "Annotate works inside an annotation campaign, which New makes "
              "on a raster.\n" + LOAD), panel.modules[0].toolTip())
    check("the correction's Close, Classes and Check say none is open, and "
          "that Open needs no map", all(
              b.toolTip().startswith("No correction is open: press Open here")
              for b in (panel.c_close, panel.c_classes, panel.c_check)),
          panel.c_close.toolTip())
    check("the campaign's Close, Classes, Export say none is open", all(
        b.toolTip().startswith("No annotation campaign is open")
        for b in (panel.b_close, panel.b_classes, panel.b_export)))
    check("Check can always be pressed, and says what it does",
          panel.b_check.isEnabled()
          and panel.b_check.toolTip().startswith("Look everything over"))

    # Qt shows a tooltip on a disabled widget: the tooltip event reaches a
    # grey button as it reaches any other, where a click does not.
    class Probe(K.QtWidgets.QPushButton):
        seen = []

        def event(self, e):
            Probe.seen.append(e.type())
            return super().event(e)

    probe = Probe("probe")
    probe.setToolTip("why")
    probe.setEnabled(False)
    K.QtWidgets.QApplication.sendEvent(probe, K.QtGui.QHelpEvent(
        K.QtCore.QEvent.Type.ToolTip, K.QtCore.QPoint(2, 2),
        K.QtCore.QPoint(2, 2)))
    check("Qt hands a tooltip event to a disabled button",
          K.QtCore.QEvent.Type.ToolTip in Probe.seen, Probe.seen)
    check("and shows its tooltip", K.QtWidgets.QToolTip.text() == "why",
          K.QtWidgets.QToolTip.text())
    K.QtWidgets.QToolTip.hideText()

    print()
    print("a raster, still no campaign")
    K.write_map(os.path.join(root, "data", "ortho.tif"),
                np.ones((10, 10), np.uint8))
    K.add_layer(K.Layer(os.path.join(root, "data", "ortho.tif"), "ortho"))
    panel.refresh_rasters()
    check("Correct and Cutouts open with no campaign",
          states(panel) == [False, True, False, True], states(panel))
    check("Annotate says it works inside an annotation campaign",
          panel.modules[0].toolTip() == "Annotate works inside an annotation "
          "campaign: press New or Open in\nANNOTATION CAMPAIGN.\n\n"
          "Draw the class areas on the raster.", panel.modules[0].toolTip())
    check("New of both blocks can be pressed and says what it makes",
          panel.b_new.toolTip() == "Create a new annotation campaign."
          and panel.c_new.toolTip().startswith("Start a new correction"))
    check("Correct and Cutouts no longer say to load a raster",
          not any("Load a raster" in panel.modules[i].toolTip()
                  for i in (1, 3)))
    check("and so does Objects",
          panel.modules[2].toolTip().startswith("Objects works inside an "
                                                "annotation campaign"))
    check("Correct says it needs none",
          "No annotation campaign is\nneeded" in panel.modules[1].toolTip(),
          panel.modules[1].toolTip())
    check("and that leaving it closes the correction",
          "Leaving Correct closes the\ncorrection" in
          panel.modules[1].toolTip())
    check("and that it works on the correction open in CORRECTION",
          "correction open in CORRECTION" in panel.modules[1].toolTip())
    check("CORRECTION: New and Open on, Close, Classes and Check off",
          [b.isEnabled() for b in (panel.c_new, panel.c_open, panel.c_close,
                                   panel.c_classes, panel.c_check)]
          == [True, True, False, False, False])
    check("Cutouts says it needs none and saves none",
          "Needs no campaign and saves none" in panel.modules[3].toolTip())
    check("Classes and Export stay with the campaign",
          not panel.b_classes.isEnabled() and not panel.b_export.isEnabled())
    for index in (0, 2):
        panel.toggle_module(index)
        check("%s does not open with no campaign" % labels(panel)[index],
              panel.section is None and not panel.modules[index].isChecked())

    print()
    print("each block holds its own modules")

    def card_of(widget):
        while widget is not None and widget not in panel.cards:
            widget = widget.parentWidget()
        return widget

    blocks = [card_of(b) for b in panel.modules]
    check("Annotate and Objects are in the annotation campaign's block",
          blocks[0] is blocks[2] and blocks[0] is card_of(panel.b_new))
    check("Correct is in the block of the correction's own buttons",
          blocks[1] is card_of(panel.c_new) and blocks[1] is not blocks[0])
    check("Cutouts stands alone",
          blocks[3] not in (blocks[0], blocks[1]) and blocks[3] is not None)
    check("the blocks are in that order: annotation, correction, cutouts",
          [panel.cards.index(b) for b in (blocks[0], blocks[1], blocks[3])]
          == [1, 2, 3])
    check("each block says what it holds",
          panel.campaign_state.text() == "no annotation campaign open"
          and panel.correction_state.text() == "no correction open")
    words = [w.text() for w in blocks[3].findChildren(K.QtWidgets.QLabel)]
    check("and CUTOUTS says it saves no campaign",
          "saves no campaign" in words, words)

    print()
    print("Cutouts on the empty panel")
    before = K.everything_under(root)
    panel.toggle_module(3)
    cut = panel.section
    check("it opens", type(cut).__name__ == "CutoutsSection",
          type(cut).__name__)
    words = [b.text() for b in cut.findChildren(K.QtWidgets.QPushButton)]
    check("with no All tiles and no Whole, which read a campaign",
          "All tiles" not in words and "Whole" not in words, words)
    check("and Layers, Cut, Undo, Folder", all(w in words for w in (
        "Layers", "Cut", "Undo", "Folder")), words)
    check("the state says no campaign is needed",
          "no campaign needed, none written" in cut.state.text(),
          cut.state.text())
    check("it took the raster on the map", [s["tag"] for s in cut.sources]
          == ["ortho"], cut.sources)
    check("its default folder is beside the project, not a campaign",
          cut.folder == os.path.join(root, "cutouts"), cut.folder)
    check("opening it wrote nothing", K.everything_under(root) == before)
    cut.folder_box.setText(os.path.join(root, "elsewhere"))
    cut.folder_changed()
    check("a folder chosen is remembered by QGIS, under rasterlabel/cutouts",
          g["read_setting"]("rasterlabel/cutouts/folder", "")
          == os.path.join(root, "elsewhere"))
    cut.png.setChecked(False)
    check("and so is a setting", g["read_setting"]("rasterlabel/cutouts/png",
                                                   True, bool) is False)
    cut.png.setChecked(True)

    print()
    print("a campaign is opened while Cutouts is open")
    panel.campaign = Campaign(tiled=True)
    panel.update_enabled()
    panel.campaign_changed()
    check("all four can open", states(panel) == [True] * 4, states(panel))
    check("Annotate has its own tooltip back",
          panel.modules[0].toolTip() == "Draw the class areas on the raster.")
    check("Cutouts was built again, now reading the campaign",
          panel.section is not cut and type(panel.section).__name__
          == "CutoutsSection" and panel.section.campaign is panel.campaign)
    cut = panel.section
    words = [b.text() for b in cut.findChildren(K.QtWidgets.QPushButton)]
    check("with All tiles and Whole now", "All tiles" in words
          and "Whole" in words, words)
    check("its folder is still the one QGIS remembers",
          cut.folder == os.path.join(root, "elsewhere"), cut.folder)
    check("and the campaign was not written", panel.campaign.saves == 0)

    print()
    print("the old folder of a campaign is read once, never written")
    g["write_setting"]("rasterlabel/cutouts/folder", "")
    panel.campaign.data["cutouts_folder"] = os.path.join(root, "kept")
    panel.reopen_module(3)
    check("with nothing remembered, the campaign's old folder is used",
          panel.section.folder == os.path.join(root, "kept"),
          panel.section.folder)
    check("and the campaign is still not written", panel.campaign.saves == 0)

    print()
    print("a correction open beside the campaign")

    class Book:
        folder = os.path.join(root, "fix")
        group_name = "RasterLabel: fix_2025"
        data = {"id": "f1x", "name": "fix_2025", "source": "/maps/lc.tif",
                "operator": "MG", "classes": [
                    {"code": c, "name": "c%d" % c, "colour": "#808080"}
                    for c in (1, 2, 3, 4)]}

    panel.correction = Book()
    panel.update_enabled()
    panel.describe_correction()
    check("CORRECTION names it, with its classes",
          panel.correction_state.text()
          == "correction <b>fix_2025</b> &middot; 4 classes",
          panel.correction_state.text())
    check("its New and Open wait, Close, Classes and Check are on",
          [b.isEnabled() for b in (panel.c_new, panel.c_open, panel.c_close,
                                   panel.c_classes, panel.c_check)]
          == [False, False, True, True, True])
    check("New and Open say one correction at a time",
          all(b.toolTip().startswith("One correction at a time")
              for b in (panel.c_new, panel.c_open)), panel.c_new.toolTip())
    check("and Close, Classes and Check say what they do",
          panel.c_close.toolTip().startswith("Close the correction")
          and panel.c_classes.toolTip().startswith("The value, colour")
          and panel.c_check.toolTip().startswith("Look the correction over"))
    check("Classes no longer promises to open Correct",
          "Opens Correct" not in panel.c_classes.toolTip())
    check("the campaign's own buttons do not follow the correction",
          not panel.b_new.isEnabled() and panel.b_close.isEnabled())
    check("and its New says one campaign at a time",
          panel.b_new.toolTip().startswith("One annotation campaign at a "
                                           "time"), panel.b_new.toolTip())
    check("all four modules can open", states(panel) == [True] * 4,
          states(panel))
    panel.rasters.clear()
    panel.update_enabled()
    check("with no raster left, Correct still opens on the correction",
          panel.modules[1].isEnabled() and not panel.modules[3].isEnabled())
    check("and with both open, the two News say why they are grey",
          panel.b_new.toolTip().startswith("One annotation campaign")
          and panel.c_new.toolTip().startswith("One correction"))
    check("Cutouts says to load a raster first",
          panel.modules[3].toolTip().startswith(LOAD))
    panel.correction = None
    panel.update_enabled()
    panel.describe_correction()
    check("closed, CORRECTION says so and Correct waits for a raster",
          panel.correction_state.text() == "no correction open"
          and not panel.modules[1].isEnabled()
          and panel.modules[1].toolTip().startswith(LOAD))
    check("the correction's New says to load a raster first, Open does not",
          panel.c_new.toolTip().startswith(LOAD) and panel.c_open.isEnabled())
    check("Annotate, with the campaign open, can be pressed with no raster",
          panel.modules[0].isEnabled() and panel.modules[0].toolTip()
          == "Draw the class areas on the raster.")
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
