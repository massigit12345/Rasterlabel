"""Annotate and Objects, in a real QGIS: what they leave behind, what they lose,
what they stop listening to.

Each case is a thing a person does in an ordinary session, and what it cost
before:

  closed      an "over" stroke leaves a sliver of the polygon under it, and the
              sliver was thrown away: a frame marked closed had pixels of no
              class, and Fill Gap answered "no holes";
  net         stretching, reclassing, deleting or undoing a box was never
              written into the recovery file, which only knew the box when it
              was drawn and when it was saved;
  table       the table of the polygons taken out of the layer tree, and every
              stroke after it vanished without a word;
  close       Close campaign took the whole group out of the project, the
              layers of the person put in it too;
  reread      the project read again with Annotate open: the new tables were
              taken for the old ones, vertex settling and the lock on the marks
              listened to nobody;
  settings    topological editing was turned off for good, and avoiding
              intersections, whose mode was never set, was not really off;
  tool        closing Annotate or Objects left the map with no tool;
  points      opening a campaign put the point size back to one pixel, so a
              second session of 9 x 9 points began by mixing two footprints;
  strip       the amber strip of a blind pass said "Passes 1 to 1".

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
from qgis.core import (QgsGeometry, QgsPointXY, QgsProject,  # noqa: E402
                       QgsRectangle, QgsVectorLayer)
from qgis.gui import QgsMapToolPan  # noqa: E402

print("QGIS %s" % K.QGIS_VERSION)
root = tempfile.mkdtemp(prefix="rl_safety_")
IMAGE = K.write_image(os.path.join(root, "data", "image.tif"))
PX = 0.1


def settle():
    """The event loop, a few turns: the timers of the section run in it."""
    for _ in range(5):
        K.app.processEvents()


def start(name, tiled=False):
    """A campaign in a project of its own, Annotate not yet open."""
    QgsProject.instance().clear()
    settle()
    image = K.layer_of(IMAGE)
    panel = K.new_panel()
    folder = K.fresh(os.path.join(root, name))
    campaign = K.new_campaign(panel, folder, image, tiled=tiled, name=name)
    return panel, campaign


def finish(panel):
    K.close_panel(panel)
    QgsProject.instance().clear()
    settle()


def modes():
    p = QgsProject.instance()
    return p.topologicalEditing(), p.avoidIntersectionsMode(), \
        list(p.avoidIntersectionsLayers())


def mode_named(word):
    """An avoid intersections mode by name, under whichever name this QGIS
    keeps the enumeration."""
    for home in (K.Qgis, QgsProject):
        kinds = getattr(home, "AvoidIntersectionsMode", None)
        if kinds is not None and hasattr(kinds, word):
            return getattr(kinds, word)
    return None


def allow_mode():
    return mode_named("AllowIntersections")


# ===================================================================== closed
print()
print("closed: an over stroke that leaves a sliver, in a frame")
panel, campaign = start("closed", tiled=True)
section = K.annotate(panel)
section.autosave.setValue(0)
section.create_tile(QgsPointXY(K.X0 + 10, K.Y0 - 10))
tid = section.current_tile_id()
K.check("a frame is placed", bool(tid), K.SAID[-3:])
frame = section.tile_geometry()
bb = frame.boundingBox()
section.choose_class("water")
section.paint(QgsGeometry(frame))
polys = K.find_mine(campaign.data["id"], "polygons")
K.check("the frame is water", polys.featureCount() == 1, polys.featureCount())


def holes_in(layer, frame):
    """Pixel centres of the frame that no polygon holds, as the mask burned
    from the table would have them at 0."""
    shapes = [f.geometry() for f in layer.getFeatures()]
    zero = 0
    x0, y0 = bb.xMinimum(), bb.yMinimum()
    cols = int(round(bb.width() / PX))
    rows = int(round(bb.height() / PX))
    for r in range(rows):
        for c in range(cols):
            centre = QgsGeometry.fromPointXY(
                QgsPointXY(x0 + (c + 0.5) * PX, y0 + (r + 0.5) * PX))
            if not frame.intersects(centre):
                continue
            if not any(g.intersects(centre) for g in shapes):
                zero += 1
    return zero


# a ring of mud with an island of water two pixels big left inside it: the
# island is what the stroke leaves of the water, apart from the rest
cx, cy = bb.center().x(), bb.center().y()
ox, oy = round((cx - bb.xMinimum()) / PX) * PX + bb.xMinimum(), \
    round((cy - bb.yMinimum()) / PX) * PX + bb.yMinimum()
outer = QgsGeometry.fromRect(QgsRectangle(ox - 0.5, oy - 0.5, ox + 0.5, oy + 0.5))
island = QgsGeometry.fromRect(QgsRectangle(ox, oy, ox + 2 * PX, oy + PX))
ring = outer.difference(island)
section.choose_class("mud")
section.paint(ring, under=False)           # over: the default is to paint under
K.check("the island is two pixels, under the four a stroke needs",
        abs(island.area() - 2 * PX * PX) < 1e-6)
K.check("no pixel of the frame is left of no class",
        holes_in(polys, frame) == 0, holes_in(polys, frame))
water = [f for f in polys.getFeatures() if f["class_name"] == "water"]
K.check("the island is still water, as a polygon of its own",
        any(abs(f.geometry().area() - island.area()) < 1e-6 for f in water),
        [round(f.geometry().area(), 6) for f in water])
del K.SAID[:]
section.close_holes()
K.check("Fill Gap finds nothing to fill, because nothing was lost",
        any("no holes" in s for s in K.SAID), K.SAID)
# and a hole that really is there is found, however small
lone = [f for f in polys.getFeatures()
        if abs(f.geometry().area() - island.area()) < 1e-6]
if lone:
    polys.startEditing()
    polys.deleteFeature(lone[0].id())
    del K.SAID[:]
    del K.BOXES[:]
    section.close_holes()
    K.check("a hole of two pixels is found by Fill Gap, which asks about it",
            not any("no holes" in s for s in K.SAID)
            and any("unpainted area" in text for _, text in K.BOXES),
            (K.SAID, K.BOXES))
    K.check("and filled", holes_in(polys, frame) == 0, holes_in(polys, frame))
finish(panel)

# ======================================================================== net
print()
print("net: boxes stretched, reclassed, deleted and undone reach the recovery file")
panel, campaign = start("net")
panel.toggle_module(2)
objects = panel.section
K.check("Objects opens", type(objects).__name__ == "ObjectsSection",
        type(objects).__name__)
objects.choose_class("mud")
objects.create_box(QgsRectangle(K.X0 + 3, K.Y0 - 15, K.X0 + 8, K.Y0 - 10))
objects.save()
K.check("the box is saved, and the net has nothing to hold",
        not os.path.exists(panel.recovery.path), panel.recovery.path)
box = next(iter(K.find_mine(campaign.data["id"], "boxes").getFeatures()))


def net_rows():
    from_file = K.g["read_snapshot"]
    if not os.path.exists(panel.recovery.path):
        return []
    return [r for r in from_file(panel.recovery.path)[1]
            if r["role"] == "boxes"]


objects.select_box(box.id())
objects.reshape_box(QgsRectangle(K.X0 + 3, K.Y0 - 15, K.X0 + 9, K.Y0 - 10))
rows = net_rows()
K.check("a stretched box is in the net, as it is now",
        any(r["what"] == "moved" and "9" in r["wkt"] for r in rows), rows)
objects.choose_class("water")
objects.assign_class_at(QgsPointXY(K.X0 + 5, K.Y0 - 12))
rows = net_rows()
K.check("a reclassed box is in the net",
        any(r["what"] == "attrs" and "water" in str(r["fields"])
            for r in rows), rows)
objects.select_box(box.id())
objects.delete_selected()
rows = net_rows()
K.check("a deleted box is in the net",
        any(r["what"] == "deleted" and r["fid"] == box.id() for r in rows),
        rows)
objects.undo()
rows = net_rows()
K.check("and after undoing the deletion it is not",
        not any(r["what"] == "deleted" for r in rows), rows)
objects.undo()
objects.undo()
K.check("and after undoing the rest the net holds nothing of the boxes",
        not net_rows(), net_rows())
objects.create_box(QgsRectangle(K.X0 + 10, K.Y0 - 15, K.X0 + 15, K.Y0 - 10))
K.check("a box drawn is in the net",
        any(r["what"] == "added" for r in net_rows()), net_rows())
objects.undo()
K.check("and drawn and undone it is not: the net is not left with a box that "
        "is gone", not net_rows(), net_rows())
finish(panel)

# ===================================================================== table
print()
print("table: the table of the polygons taken out of the project")
panel, campaign = start("table")
section = K.annotate(panel)
section.autosave.setValue(0)
section.choose_class("mud")
section.paint(K.square(K.X0 + 2, K.Y0 - 18, 1.0))
section.save()
cid = campaign.data["id"]
gone = K.find_mine(cid, "polygons")
QgsProject.instance().removeMapLayer(gone.id())
settle()
K.check("the table is out of the project", K.find_mine(cid, "polygons") is None)
del K.SAID[:]
section.paint(K.square(K.X0 + 5, K.Y0 - 18, 1.0))
back = K.find_mine(cid, "polygons")
K.check("the next stroke puts the table back", back is not None)
K.check("and says so", any("taken out of the project" in s for s in K.SAID),
        K.SAID)
K.check("the stroke is drawn in it", back is not None
        and back.featureCount() == 2, back and back.featureCount())
section.save()
K.check("and saved with the rest", K.counts(campaign.package_path)["polygons"] == 2,
        K.counts(campaign.package_path))
finish(panel)

# ====================================================================== close
print()
print("close: Close campaign takes out the program's layers and nothing else")
panel, campaign = start("close")
cid = campaign.data["id"]
notes = QgsVectorLayer("Point?crs=EPSG:32633&field=note:string", "my notes",
                       "memory")
notes_id = notes.id()
QgsProject.instance().addMapLayer(notes, False)
group = K.g["group_node"](campaign.group_name)
group.addLayer(notes)
K.check("a layer of the person is in the campaign's group",
        group.findLayer(notes_id) is not None)
panel.close_campaign()
settle()
root_node = QgsProject.instance().layerTreeRoot()
K.check("the campaign's layers are gone", not K.g["my_layers"](cid))
K.check("the person's layer is still in the project",
        QgsProject.instance().mapLayer(notes_id) is not None)
left = root_node.findGroup(campaign.group_name)
K.check("and still in its group", left is not None
        and left.findLayer(notes_id) is not None)
finish(panel)

panel, campaign = start("close2")
cid = campaign.data["id"]
name = campaign.group_name
panel.close_campaign()
settle()
K.check("with nothing else in it, the group goes too",
        QgsProject.instance().layerTreeRoot().findGroup(name) is None)
finish(panel)

# ====================================================================== reread
print()
print("reread: the project read again with Annotate open")
panel, campaign = start("reread")
cid = campaign.data["id"]
# a project saved with topological editing on, before Annotate is open
project = os.path.join(root, "reread.qgz")
QgsProject.instance().setTopologicalEditing(True)
QgsProject.instance().write(project)
QgsProject.instance().setTopologicalEditing(False)
section = K.annotate(panel)
section.autosave.setValue(0)
section.choose_class("mud")
section.paint(K.square(K.X0 + 2, K.Y0 - 10, 4.0), under=False)
section.choose_class("water")
section.paint(K.square(K.X0 + 6, K.Y0 - 10, 4.0), under=False)
section.save()
before = K.find_mine(cid, "polygons")
old_id = before.id()
K.check("the project is read again",
        QgsProject.instance().read(project))
settle()
after = K.find_mine(cid, "polygons")
K.check("the tables are new objects with the old ids",
        after is not None and after is not before
        and after.id() == old_id)
K.check("the project's topological editing was put down again",
        not QgsProject.instance().topologicalEditing())


def rows_by_class(layer):
    return {f["class_name"]: f for f in layer.getFeatures()}


def drag_into_neighbour(layer):
    """What the vertex tool does: mud stretched across the border into the
    water, in one edit command."""
    by = rows_by_class(layer)
    mud = by["mud"].geometry()
    layer.startEditing()
    layer.beginEditCommand("Moved vertex")
    layer.changeGeometry(by["mud"].id(), mud.combine(K.square(
        K.X0 + 5.5, K.Y0 - 10, 2.0)))
    layer.endEditCommand()
    settle()


drag_into_neighbour(after)
by = rows_by_class(after)
shared = by["mud"].geometry().intersection(by["water"].geometry())
K.check("a vertex dragged into the neighbour is settled: the water is trimmed",
        shared.isEmpty() or shared.area() < 1e-6,
        None if shared.isEmpty() else shared.area())
after.rollBack()
settle()
section.lock_marks.setChecked(True)
settle()
by = rows_by_class(after)
area = by["mud"].geometry().area()
after.startEditing()
after.beginEditCommand("Moved vertex")
after.changeGeometry(by["mud"].id(), by["mud"].geometry().combine(
    K.square(K.X0 + 1, K.Y0 - 10, 1.0)))
after.endEditCommand()
settle()
K.check("and the lock on the marks holds the new table still",
        abs(rows_by_class(after)["mud"].geometry().area() - area) < 1e-6,
        (area, rows_by_class(after)["mud"].geometry().area()))
section.lock_marks.setChecked(False)
finish(panel)

# =================================================================== settings
print()
print("settings: topological editing and avoid intersections, as they were")
panel, campaign = start("settings")
proj = QgsProject.instance()
proj.setTopologicalEditing(True)
current = mode_named("AvoidIntersectionsCurrentLayer")
K.check("this QGIS has the mode that avoids the layer being edited",
        current is not None)
if current is not None:
    proj.setAvoidIntersectionsMode(current)
before = modes()
section = K.annotate(panel)
topo, mode, layers = modes()
K.check("with Annotate open topological editing is off", not topo, topo)
K.check("and avoiding intersections is really off, the mode and all",
        mode == allow_mode(), (mode, allow_mode()))
panel.close_module()
settle()
K.check("closing Annotate gives topological editing back",
        modes()[0] == before[0] and before[0], modes())
K.check("and the mode that avoids the layer being edited",
        modes()[1] == before[1], modes())
panel.close_module()
K.check("closing it again changes nothing", modes() == before, modes())

# a project that is read while Annotate is open brings its own settings
proj.setTopologicalEditing(True)
project = os.path.join(root, "settings.qgz")
proj.write(project)
proj.setTopologicalEditing(False)
section = K.annotate(panel)
K.check("Annotate reopened: off", not proj.topologicalEditing())
proj.read(project)
settle()
K.check("a project read with it on has it put down again",
        not QgsProject.instance().topologicalEditing())
panel.close_module()
settle()
K.check("and closing Annotate gives the project's own value back",
        QgsProject.instance().topologicalEditing())
QgsProject.instance().setTopologicalEditing(False)
finish(panel)

# ======================================================================= tool
print()
print("tool: the map goes back to the tool the person had")
panel, campaign = start("tool")
canvas = K.iface.mapCanvas()
mine = QgsMapToolPan(canvas)
canvas.setMapTool(mine)
section = K.annotate(panel)
K.check("Annotate takes the map", canvas.mapTool() is not mine
        and canvas.mapTool() is not None)
panel.close_module()
K.check("closing Annotate gives it back", canvas.mapTool() is mine,
        canvas.mapTool())

panel.toggle_module(2)
K.check("Objects takes the map", canvas.mapTool() is not mine
        and canvas.mapTool() is not None)
panel.close_module()
K.check("closing Objects gives it back", canvas.mapTool() is mine,
        canvas.mapTool())

canvas.unsetMapTool(mine)
K.check("with no tool in hand", canvas.mapTool() is None)
section = K.annotate(panel)
panel.close_module()
K.check("closing Annotate leaves Pan, not nothing",
        isinstance(canvas.mapTool(), QgsMapToolPan), canvas.mapTool())

other = QgsMapToolPan(canvas)
canvas.setMapTool(mine)
section = K.annotate(panel)
canvas.setMapTool(other)
panel.close_module()
K.check("a tool the person picked meanwhile is left alone",
        canvas.mapTool() is other, canvas.mapTool())
finish(panel)

# ===================================================================== points
print()
print("points: a campaign goes on with the footprint most of its points have")
panel, campaign = start("points")
section = K.annotate(panel)
section.autosave.setValue(0)
K.check("a campaign with no point starts at one pixel",
        section.point_px.currentData() == 1, section.point_px.currentData())
section.choose_class("mud")


def size_to(section, n):
    section.point_px.setCurrentIndex(section.point_px.findData(n))
    return section.point_px.currentData()


def drop(section, n, count, x):
    size_to(section, n)
    for i in range(count):
        section.drop_point(K.point(K.X0 + x + i, K.Y0 - 5))


drop(section, 9, 3, 2)
drop(section, 3, 1, 10)
K.check("three points of 9 x 9 and one of 3 x 3 are there",
        section.sizes_in_use() == {9: 3, 3: 1}, section.sizes_in_use())
section.save()
panel.close_module()
section = K.annotate(panel)
K.check("Annotate opened again goes on with the 9 x 9 most of them have, "
        "not with one pixel", section.point_px.currentData() == 9,
        section.point_px.currentData())
section.choose_class("water")
drop(section, 3, 2, 14)
K.check("a size most of the points have changes with the points",
        section.sizes_in_use() == {9: 3, 3: 3}, section.sizes_in_use())
section.save()
panel.close_module()
section = K.annotate(panel)
K.check("and when two sizes are as many it is the smaller",
        section.point_px.currentData() == 3, section.point_px.currentData())
folder = campaign.folder
finish(panel)

panel = K.new_panel()
K.open_campaign(panel, folder)
section = K.annotate(panel)
K.check("the campaign opened in another session does the same",
        section.point_px.currentData() == 3, section.point_px.currentData())
finish(panel)

# ===================================================================== strip
print()
print("strip: what the amber strip of a blind pass says")
panel, campaign = start("strip")
section = K.annotate(panel)
section.pass_no.setValue(2)
section.blind.setChecked(True)
section.show_blind()
words = section.blind_note.text()
K.check("a second pass hides one pass, and says Pass 1",
        "Pass 1 is hidden and stays untouched" in words
        and "Passes 1 to 1" not in words, words)
section.pass_no.setValue(3)
section.show_blind()
words = section.blind_note.text()
K.check("a third hides the other two, and says Passes 1 and 2",
        "Passes 1 and 2 are hidden and stay untouched" in words
        and "see them" in words, words)
section.pass_no.setValue(1)
section.show_blind()
words = section.blind_note.text()
K.check("back in pass 1 the others are hidden too: Passes 2 and 3",
        "Passes 2 and 3 are hidden and stay untouched" in words, words)
finish(panel)

shutil.rmtree(root, ignore_errors=True)
K.finish()
