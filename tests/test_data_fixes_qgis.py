"""Work that is still pending, and a project written while a module is open,
in a real QGIS.

What was wrong, each case:

  whole      Whole, reached from Cutouts, never asked the tables whether they
             still held work: a package that refused the save when Annotate
             was closed left polygons in a buffer, and the mask and the card
             were made from the file without them, with no word. The other
             export doors ask (panel.pending_layers); Whole does now, writes
             what it can, and asks "Export anyway?" about the rest;
  objects    the Save button of Objects said nothing, on success or on
             failure, and a failed commit went to the log alone; there was no
             autosave either, so boxes could sit in a buffer all afternoon.
             It says what Annotate says, and writes every so many changes;
  project    a project saved while Annotate was open was written with
             topological editing and avoid intersections off, the plugin's
             settings and not the user's, and they stayed off for good. The
             project is written with the user's own and Annotate goes on
             with its own after;
  undo       Undo stops at the last save, by hand or by itself, and the
             Settings tooltip and the message say so.

Needs QGIS; tests/run.py skips it where QGIS is missing and, with
RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgiskit as K  # noqa: E402
from qgis.core import (QgsPointXY, QgsProject, QgsRectangle,  # noqa: E402
                       QgsVectorLayer)
from qgis.PyQt.QtWidgets import QMessageBox  # noqa: E402

print("QGIS %s" % K.QGIS_VERSION)
root = tempfile.mkdtemp(prefix="rl_datafix_")
IMAGE = K.write_image(os.path.join(root, "data", "image.tif"))
refusing = []


def settle():
    for _ in range(5):
        K.app.processEvents()


def start(name):
    QgsProject.instance().clear()
    settle()
    image = K.layer_of(IMAGE)
    panel = K.new_panel()
    campaign = K.new_campaign(panel, K.fresh(os.path.join(root, name)), image,
                              name=name)
    return panel, campaign


def finish(panel):
    K.close_panel(panel)
    QgsProject.instance().clear()
    settle()


def lock(layer):
    """The package refuses every commit of this table from here on, as one on
    a read-only share or held by a sync client does. The layer is told to
    answer a commit with a failure, which is all the program sees of it."""
    layer.commitChanges = lambda: False
    layer.commitErrors = lambda: ["database is locked"]
    refusing.append(layer)


def unlock(layer):
    for name in ("commitChanges", "commitErrors"):
        try:
            delattr(layer, name)
        except AttributeError:
            pass
    if layer in refusing:
        refusing.remove(layer)


def box(o, i):
    o.create_box(QgsRectangle(K.X0 + 1 + 3 * i, K.Y0 - 6, K.X0 + 3 + 3 * i,
                              K.Y0 - 4))


try:
    # =================================================================== whole
    print()
    print("whole: work still pending when Whole is pressed in Cutouts")
    panel, campaign = start("whole")
    package = campaign.package_path
    cid = campaign.data["id"]
    polygons = K.find_mine(cid, "polygons")
    section = K.annotate(panel)
    section.autosave.setValue(0)
    section.choose_class("mud")
    for i in range(3):
        section.paint(K.square(K.X0 + 1 + 3 * i, K.Y0 - 10, 2.0))
    section.save()
    lock(polygons)
    section.paint(K.square(K.X0 + 1, K.Y0 - 14, 2.0))
    panel.toggle_module(3)
    settle()
    cutouts = panel.section
    K.check("Cutouts is open, and the fourth polygon is still pending",
            type(cutouts).__name__ == "CutoutsSection"
            and [r for r, _ in panel.pending_layers()] == ["polygons"],
            (type(cutouts).__name__, panel.pending_layers()))
    reached = []

    def window(dialog):
        reached.append(1)
        return 0                    # closed: nothing is written
    original = QMessageBox.__dict__["warning"]
    K.ANSWERS["WholeRaster"] = window
    del K.BOXES[:]
    cutouts.export_whole()
    asked = [t for k, t in K.BOXES if k == "warning"]
    K.check("Whole asks before writing: the work did not go",
            len(asked) == 1 and "Not everything could be saved" in asked[0]
            and "polygons" in asked[0], K.BOXES)
    K.check("and, the answer being Cancel, the window of Whole never opens",
            not reached, reached)
    QMessageBox.warning = staticmethod(
        lambda *a, **k: (K.BOXES.append(("warning", str(a[2]))),
                         QMessageBox.StandardButton.Yes)[1])
    K.ANSWERS["WholeRaster"] = window
    del K.BOXES[:]
    cutouts.export_whole()
    K.check("answered Export anyway, it goes on to the window", reached,
            K.BOXES)
    QMessageBox.warning = original
    unlock(polygons)
    K.check("the package lets the work through now", not panel.flush_layers(),
            panel.pending_layers())
    del K.BOXES[:]
    reached[:] = []
    K.ANSWERS["WholeRaster"] = window
    cutouts.export_whole()
    K.check("with nothing pending there is nothing to ask",
            not [t for k, t in K.BOXES if k == "warning"] and reached,
            (K.BOXES, reached))
    finish(panel)

    # ================================================================ objects
    print()
    print("objects: Save says how it went, and the boxes are saved by themselves")
    panel, campaign = start("objects")
    package = campaign.package_path
    panel.toggle_module(2)
    o = panel.section
    boxes = o.boxes
    o.choose_class("mud")
    box(o, 0)
    del K.SAID[:]
    o.save()
    K.check("a Save that works says so, as Annotate does",
            any("saved, 1 layer written" in s for s in K.SAID), K.SAID)
    K.check("and the box is on disk", K.counts(package)["boxes"] == 1,
            K.counts(package))
    lock(boxes)
    box(o, 1)
    del K.SAID[:]
    o.save()
    K.check("a Save the package refuses says so, with the reason",
            any("not everything could be saved" in s and "boxes" in s
                for s in K.SAID), K.SAID)
    K.check("and the box is still pending, not lost",
            o.unsaved() and K.counts(package)["boxes"] == 1,
            (o.unsaved(), K.counts(package)))
    unlock(boxes)
    del K.SAID[:]
    o.save()
    K.check("pressed again once the package lets it, it goes",
            K.counts(package)["boxes"] == 2
            and any("saved, 1 layer written" in s for s in K.SAID),
            (K.counts(package), K.SAID))
    K.check("Objects has the autosave setting, with Annotate's default",
            o.autosave.value() == K.g["AUTOSAVE"] == 20, o.autosave.value())
    o.autosave.setValue(2)
    box(o, 2)
    K.check("one change under the number: not written yet",
            K.counts(package)["boxes"] == 2, K.counts(package))
    del K.SAID[:]
    box(o, 3)
    K.check("the second one writes both, by itself",
            K.counts(package)["boxes"] == 4, K.counts(package))
    K.check("quietly: no message in the bar for an automatic save",
            not any("saved," in s for s in K.SAID), K.SAID)
    o.autosave.setValue(0)
    box(o, 4)
    box(o, 5)
    box(o, 6)
    K.check("at zero it is off", K.counts(package)["boxes"] == 4,
            K.counts(package))
    lock(boxes)
    o.autosave.setValue(1)
    del K.SAID[:]
    box(o, 7)
    K.check("an automatic save that is refused is said, not silent",
            any("not everything could be saved" in s for s in K.SAID), K.SAID)
    unlock(boxes)
    finish(panel)

    # ===================================================== the box selected
    print()
    print("objects: a save in the middle of an edit keeps the box picked up")
    panel, campaign = start("picked")
    panel.toggle_module(2)
    o = panel.section
    o.choose_class("mud")
    o.autosave.setValue(3)
    box(o, 0)
    box(o, 1)
    point = QgsPointXY(K.X0 + 2, K.Y0 - 5)
    o.select_box(o.box_at(point).id())
    o.choose_class("water")
    o.assign_class_at(point)        # the third change: the autosave
    K.check("the autosave wrote the boxes",
            K.counts(campaign.package_path)["boxes"] == 2,
            K.counts(campaign.package_path))
    K.check("the box that was picked up still is",
            o.selected is not None and o.selected >= 0
            and o.selected_rect() is not None
            and o.boxes.selectedFeatureIds() == [o.selected],
            (o.selected, o.boxes.selectedFeatureIds()))
    K.check("and it is the one that was picked up",
            o.boxes.getFeature(o.selected)["class_name"] == "water",
            o.boxes.getFeature(o.selected)["class_name"])
    o.delete_selected()
    K.check("so Delete removes it",
            o.boxes.featureCount() == 1, o.boxes.featureCount())
    finish(panel)

    # ============================================ QGIS's own Save Layer Edits
    print()
    print("recovery: the table committed by QGIS itself")
    panel, campaign = start("qgis_save")
    section = K.annotate(panel)
    section.autosave.setValue(0)
    section.choose_class("mud")
    section.paint(K.square(K.X0 + 1, K.Y0 - 10, 2.0))
    polygons = section.layer("polygons")

    def net_rows():
        if not os.path.exists(panel.recovery.path):
            return []
        return K.g["read_snapshot"](panel.recovery.path)[1]

    K.check("a stroke waiting: the net lists it",
            [r["role"] for r in net_rows()] == ["polygons"], net_rows())
    K.check("QGIS's Save Layer Edits works", polygons.commitChanges(False))
    K.check("and the net no longer lists a stroke that is in the package",
            not net_rows(), net_rows())
    finish(panel)

    # ================================================================ project
    print()
    print("project: written while Annotate is open")
    panel, campaign = start("project")
    project = QgsProject.instance()
    allow = K.g["AnnotationSection"].allow_intersections()
    current = None
    for home in (K.Qgis, QgsProject):
        kinds = getattr(home, "AvoidIntersectionsMode", None)
        if kinds is not None and hasattr(kinds, "AvoidIntersectionsLayers"):
            current = kinds.AvoidIntersectionsLayers
            break
    # the user's own: avoid intersections with one layer of theirs
    mine = QgsVectorLayer("Polygon?crs=EPSG:32633", "my polygons", "memory")
    project.addMapLayer(mine)
    project.setTopologicalEditing(True)
    project.setAvoidIntersectionsMode(current)
    project.setAvoidIntersectionsLayers([mine])
    section = K.annotate(panel)
    K.check("Annotate turns both off while it is open",
            project.topologicalEditing() is False
            and project.avoidIntersectionsMode() == allow,
            (project.topologicalEditing(), project.avoidIntersectionsMode()))
    path = os.path.join(root, "mine.qgz")
    project.setDirty(False)
    K.check("the project is written", project.write(path))
    settle()
    K.check("while it is open, Annotate goes on with its own settings",
            project.topologicalEditing() is False
            and project.avoidIntersectionsMode() == allow,
            (project.topologicalEditing(), project.avoidIntersectionsMode()))
    K.check("and the write did not leave the project marked as changed",
            not project.isDirty())
    fresh = QgsProject()
    fresh.read(path)
    K.check("the file holds the user's own topological editing",
            fresh.topologicalEditing() is True, fresh.topologicalEditing())
    K.check("and the user's own way of avoiding intersections",
            fresh.avoidIntersectionsMode() == current,
            fresh.avoidIntersectionsMode())
    K.check("and the layers they chose to avoid",
            [l.name() for l in fresh.avoidIntersectionsLayers()]
            == ["my polygons"], fresh.avoidIntersectionsLayers())
    project.write(path)
    settle()
    again = QgsProject()
    again.read(path)
    K.check("a second write is the same",
            again.topologicalEditing() is True, again.topologicalEditing())
    panel.close_module()
    settle()
    K.check("and closing Annotate gives them back as before",
            project.topologicalEditing() is True
            and project.avoidIntersectionsMode() == current
            and [l.name() for l in project.avoidIntersectionsLayers()]
            == ["my polygons"],
            (project.topologicalEditing(), project.avoidIntersectionsMode()))
    finish(panel)

    # =================================================================== undo
    print()
    print("undo: the limit is said")
    panel, campaign = start("undo")
    section = K.annotate(panel)
    tip = section.autosave.toolTip()
    K.check("the autosave tooltip says Undo cannot take back what was "
            "written", "Undo" in tip and "written" in tip, tip)
    section.autosave.setValue(1)
    section.choose_class("mud")
    section.paint(K.square(K.X0 + 2, K.Y0 - 10, 2.0))
    del K.SAID[:]
    section.undo_stroke()
    K.check("an Undo after a save says it stops at the last save",
            any("nothing left to undo" in s and "last save" in s
                for s in K.SAID), K.SAID)
    finish(panel)
finally:
    for layer in list(refusing):
        unlock(layer)
    shutil.rmtree(root, ignore_errors=True)

K.finish()
