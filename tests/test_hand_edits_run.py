"""The hand edits, run: settle_edits, give_back, save and move_tile themselves.

Not a model of the rule and not a reading of the source. editkit borrows the
methods of AnnotationSection unchanged, puts them on a layer that edits the way
QGIS's does, and lets GEOS do the arithmetic. Every case below is something
that went wrong under Massi's hand or was found reading the code, and each was
seen failing here before it was fixed.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import sys

if not os.environ.get("RL_ROOT"):
    print("set RL_ROOT to the repository root")
    sys.exit(2)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import editkit as K
except ImportError as err:
    print("cannot build the kit: %s (pip install shapely)" % err)
    sys.exit(2)
from shapely.geometry import box

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


print("the stand-in message bar takes a level as PyQt6 does")
# It took anything, and pushWidget(bar, 0), which PyQt6 refuses, passed every
# suite and stopped Whole on QGIS 4 before it wrote a single file.
from rasterlabel import constants as _C                           # noqa: E402


def _refused(call):
    try:
        call()
        return False
    except TypeError:
        return True


check("LEVEL_INFO is the enum here too, not a bare number",
      type(_C.LEVEL_INFO) is not int, type(_C.LEVEL_INFO).__name__)
check("pushWidget refuses a bare number",
      _refused(lambda: K.Bar().pushWidget(None, 0)))
check("and takes LEVEL_INFO",
      not _refused(lambda: K.Bar().pushWidget(None, _C.LEVEL_INFO)))
check("pushMessage refuses a bare number too",
      _refused(lambda: K.Bar().pushMessage("RasterLabel", "x", level=1)))
print()

T1 = box(0, 0, 10, 10)
T2 = box(20, 0, 30, 10)


def campaign(with_t2=False):
    polys = K.Layer("polygons")
    tiles = K.Layer("tiles")
    K.put(tiles, T1, tile_id="t001")
    K.put(tiles, T2, tile_id="t002")
    a = K.put(polys, box(0, 0, 5, 10), class_name="a", class_code=1,
              tile_id="t001", pass_no=1, operator="OP1")
    b = K.put(polys, box(5, 0, 10, 10), class_name="b", class_code=2,
              tile_id="t001", pass_no=1, operator="OP1")
    ids = {"a": a, "b": b}
    if with_t2:
        ids["a2"] = K.put(polys, box(20, 0, 25, 10), class_name="a",
                          class_code=1, tile_id="t002", pass_no=1,
                          operator="OP1")
        ids["b2"] = K.put(polys, box(25, 0, 30, 10), class_name="b",
                          class_code=2, tile_id="t002", pass_no=1,
                          operator="OP1")
    host = K.Host(polys, tiles)
    polys.startEditing()
    host.remember_shapes()
    return host, polys, tiles, ids


# ---------------------------------------------------------------- baseline
print("the kit runs the real code: a border dragged both ways")
host, polys, tiles, ids = campaign()
polys.drag(ids["a"], box(0, 0, 4, 10))          # pulled back
K.Loop.run()
check("pulled back: the neighbour takes the strip",
      abs(K.shape_of(polys, ids["b"]).area - 60) < 1e-9,
      K.shape_of(polys, ids["b"]).area)
polys.drag(ids["a"], box(0, 0, 7, 10))          # pushed in
K.Loop.run()
check("pushed in: the neighbour is trimmed",
      abs(K.shape_of(polys, ids["b"]).area - 30) < 1e-9,
      K.shape_of(polys, ids["b"]).area)
check("and nothing overlaps", K.overlap_area(polys) < 1e-9,
      K.overlap_area(polys))
check("the frame stays covered", abs(K.covered(polys, T1) - 100) < 1e-9)

# ---------------------------------------------------------------------
print()
print("after Save, a vertex pulled back still gives its ground away")
# Save commits, and a commit gives every polygon drawn since the last one a
# new id. The shapes remembered before the save were filed under the old ones,
# so the first pull after a Save found no "before" and left a hole.
polys = K.Layer("polygons")
tiles = K.Layer("tiles")
K.put(tiles, T1, tile_id="t001")
host = K.Host(polys, tiles)
polys.startEditing()
host.class_name = "a"
for shape, name in ((box(0, 0, 5, 10), "a"), (box(5, 0, 10, 10), "b")):
    polys.addFeature(host.new_feature(K.G(shape), name))
host.remember_shapes()                       # what ticked() does after a stroke
host.save(quiet=True)
polys.startEditing()                         # save() reopens it: it may be open already
new_a = [f.id() for f in polys.getFeatures() if f["class_name"] == "a"][0]
new_b = [f.id() for f in polys.getFeatures() if f["class_name"] == "b"][0]
check("the commit renumbered them", new_a > 0 and new_b > 0, (new_a, new_b))
polys.drag(new_a, box(0, 0, 4, 10))
K.Loop.run()
check("the neighbour takes the strip, as before the save",
      abs(K.shape_of(polys, new_b).area - 60) < 1e-9,
      K.shape_of(polys, new_b).area)
check("no hole is left", abs(K.covered(polys, T1) - 100) < 1e-9,
      K.covered(polys, T1))

# ---------------------------------------------------------------------
print()
print("a vertex dragged in another frame is settled in that frame")
# Every frame is on screen unless 'show the current tile only' is ticked, and
# it is not by default. A vertex dragged in t002 while t001 was the frame in the
# list was skipped as "outside the current pass" and the overlap stayed.
host, polys, tiles, ids = campaign(with_t2=True)
polys.drag(ids["a2"], box(20, 0, 27, 10))       # pushed into b2, in t002
K.Loop.run()
check("the neighbour in t002 is trimmed",
      abs(K.shape_of(polys, ids["b2"]).area - 30) < 1e-9,
      K.shape_of(polys, ids["b2"]).area)
check("and the two no longer share ground",
      K.overlap_area(polys, scope=lambda f: f["tile_id"] == "t002") < 1e-9)
polys.drag(ids["a2"], box(20, 0, 23, 10))       # and pulled back past where it was
K.Loop.run()
check("pulled back in t002, b2 takes the ground",
      abs(K.shape_of(polys, ids["b2"]).area - 70) < 1e-9,
      K.shape_of(polys, ids["b2"]).area)
check("t002 stays covered",
      abs(K.covered(polys, T2, lambda f: f["tile_id"] == "t002") - 100) < 1e-9)
check("t001 was not touched",
      abs(K.shape_of(polys, ids["a"]).area - 50) < 1e-9
      and abs(K.shape_of(polys, ids["b"]).area - 50) < 1e-9)

print()
print("but another reading is still never settled against this one")
host, polys, tiles, ids = campaign()
other = K.put(polys, box(2, 2, 8, 8), class_name="c", class_code=3,
              tile_id="t001", pass_no=1, operator="OP2")
polys.startEditing()
polys.buffer[other] = polys.saved[other].copy()
host.remember_shapes()
polys.drag(other, box(1, 1, 9, 9))
K.Loop.run()
check("OP1's polygons are as they were",
      abs(K.shape_of(polys, ids["a"]).area - 50) < 1e-9
      and abs(K.shape_of(polys, ids["b"]).area - 50) < 1e-9)

# ------------------------------------------------------------------ undo
print()
print("Ctrl+Z takes a drag back, and the tidying does not come back by itself")
# Undo replays the drag backwards and fires geometryChanged like any edit. It
# used to be taken for a new hand drag and settled again, pushing a fresh
# command: Ctrl+Z went back and forth between two states for ever and the
# drag could never be undone.
for where in ("t001", "t002"):
    host, polys, tiles, ids = campaign(with_t2=True)
    a, b = (ids["a"], ids["b"]) if where == "t001" else (ids["a2"], ids["b2"])
    polys.drag(a, box(*((0, 0, 7, 10) if where == "t001" else (20, 0, 27, 10))))
    K.Loop.run()
    stack = polys.undoStack()
    check("%s: the drag is settled (b trimmed to 30)" % where,
          abs(K.shape_of(polys, b).area - 30) < 1e-9, K.shape_of(polys, b).area)
    states = []
    for _ in range(4):
        stack.undo()
        K.Loop.run()
        states.append((round(K.shape_of(polys, a).area),
                       round(K.shape_of(polys, b).area), stack.index()))
    check("%s: undoing walks back to where it started and stays there" % where,
          states[-1][:2] == (50, 50) and states[-1][2] == 0, states)
    check("%s: no command was added by the undos" % where,
          stack.count() <= 2, stack.count())
    while stack.canRedo():
        stack.redo()
        K.Loop.run()
    check("%s: and redo brings the settled drag back" % where,
          abs(K.shape_of(polys, b).area - 30) < 1e-9
          and abs(K.shape_of(polys, a).area - 70) < 1e-9,
          (K.shape_of(polys, a).area, K.shape_of(polys, b).area))

# ------------------------------------------------------------ marks lock
print()
print("with the marks locked, nothing moves: not a drag, not a redo, not an undo")
host, polys, tiles, ids = campaign()
stack = polys.undoStack()
polys.drag(ids["a"], box(0, 0, 7, 10))          # an ordinary drag, settled
K.Loop.run()
host.lock_marks.setChecked(True)
host.locks_changed()
locked_at = (K.shape_of(polys, ids["a"]).area, K.shape_of(polys, ids["b"]).area)
polys.drag(ids["a"], box(0, 0, 9, 10))          # a drag while locked
K.Loop.run()
now_ = (K.shape_of(polys, ids["a"]).area, K.shape_of(polys, ids["b"]).area)
check("a drag while locked is put back", now_ == locked_at, (now_, locked_at))
stack.redo()                                    # Ctrl+Shift+Z
K.Loop.run()
now_ = (K.shape_of(polys, ids["a"]).area, K.shape_of(polys, ids["b"]).area)
check("and redo cannot bring it back", now_ == locked_at, (now_, locked_at))
stack.undo()                                    # QGIS's own Ctrl+Z
K.Loop.run()
now_ = (K.shape_of(polys, ids["a"]).area, K.shape_of(polys, ids["b"]).area)
check("and QGIS's undo does not rub out what was drawn before the lock",
      now_ == locked_at, (now_, locked_at))
host.lock_marks.setChecked(False)
host.locks_changed()
stack.undo()
K.Loop.run()
check("unlocked, undo works again",
      K.shape_of(polys, ids["b"]).area != locked_at[1],
      K.shape_of(polys, ids["b"]).area)

print()
print("the lock also holds against an undo that moves no geometry")
host, polys, tiles, ids = campaign()
stack = polys.undoStack()
polys.beginEditCommand("stroke a")                  # a stroke on empty ground:
polys.addFeature(K.Feature(polys.fields(), None, box(0, 0, 1, 1),   # an add only
                           class_name="a", class_code=1, tile_id="t001",
                           pass_no=1, operator="OP1"))
polys.endEditCommand()
polys.beginEditCommand("reclassify")                # and a class swap: attributes
polys.changeAttributeValue(ids["b"], polys.fields().indexOf("class_name"), "c")
polys.endEditCommand()
K.Loop.run()
host.lock_marks.setChecked(True)
host.locks_changed()
n_before = polys.featureCount()
stack.undo()
K.Loop.run()
check("undoing a class swap is put back",
      polys.getFeature(ids["b"])["class_name"] == "c",
      polys.getFeature(ids["b"])["class_name"])
stack.undo()
stack.undo()
K.Loop.run()
check("undoing an added polygon is put back",
      polys.featureCount() == n_before, (polys.featureCount(), n_before))

print()
print("the lock survives a commit that does not go through Save")
host, polys, tiles, ids = campaign()
polys.drag(ids["a"], box(0, 0, 7, 10))
K.Loop.run()
host.lock_marks.setChecked(True)
host.locks_changed()
polys.commitChanges()                 # QGIS's own Save Layer Edits, a rename...
polys.startEditing()
held = K.shape_of(polys, ids["a"]).area
polys.drag(ids["a"], box(0, 0, 9, 10))
K.Loop.run()
check("a drag after that commit is still put back",
      K.shape_of(polys, ids["a"]).area == held,
      (K.shape_of(polys, ids["a"]).area, held))

print()
print("the lock holds the lines and the points too")
host, polys, tiles, ids = campaign()
lines = K.Layer("lines")
host.layers["lines"] = lines
host.watch_geometry_edits()
lines.startEditing()
lines.beginEditCommand("line")
lines.addFeature(K.Feature(lines.fields(), None, box(0, 0, 1, 1),
                           class_name="a", class_code=1, tile_id="t001",
                           pass_no=1, operator="OP1"))
lines.endEditCommand()
host.lock_marks.setChecked(True)
host.locks_changed()
lines.undoStack().undo()              # QGIS's Ctrl+Z with the lines active
K.Loop.run()
check("the trace of a line cannot be undone under the lock",
      lines.featureCount() == 1, lines.featureCount())

print()
print("Delete tile does not delete marks while they are locked")
host, polys, tiles, ids = campaign()
host.lock_marks.setChecked(True)
host.locks_changed()


class Yes(object):
    Yes, Cancel = 1, 2
    @staticmethod
    def question(*a, **k): return 1


# The program asks for QMessageBox.StandardButton.Yes, QMessageBox.Icon.Warning
# and the like, the spelling Qt 5 and Qt 6 share: the stand-in answers to
# those through itself.
Yes.Icon = Yes.StandardButton = Yes.ButtonRole = Yes


real_box = K.SA.QMessageBox
K.SA.QMessageBox = Yes
host.refresh_tiles = lambda: None
try:
    host.delete_tile()
finally:
    K.SA.QMessageBox = real_box
check("the polygons of the frame are still there",
      K.shape_of(polys, ids["a"]) is not None
      and K.shape_of(polys, ids["b"]) is not None)
check("and so is the frame", tiles.featureCount() == 2, tiles.featureCount())

print()
print("a class renamed under the lock keeps its new name on the features")
# Renaming writes the new name into every feature, as one command on each
# table. If the commit after it failed, the lock took that command for an edit
# and walked it back: the manifest said "c", the features said "b", and the
# map, which paints by name, stopped drawing them.
host, polys, tiles, ids = campaign()
host.lock_marks.setChecked(True)
host.locks_changed()
for name in ("class_by_code", "cancel_rename", "finish_rename"):
    setattr(K.Host, name, K.SA.AnnotationSection.__dict__[name])
host.campaign.save = lambda: None
host.rebuild_class_buttons = lambda: None
host.panel.describe_campaign = lambda: None
K.SA.restyle = lambda campaign: None


def rename_features():
    """What the panel does, with a commit that fails."""
    polys.beginEditCommand("rename classes")
    for f in polys.getFeatures():
        if f["class_name"] == "b":
            polys.changeAttributeValue(f.id(),
                                       polys.fields().indexOf("class_name"),
                                       "renamed")
    polys.endEditCommand()
    return 1


host.panel.rename_features = rename_features
said = []
real_log = K.SA.log
K.SA.log = lambda msg, loud=False: said.append(str(msg))
try:
    host.finish_rename(2, "renamed")
    K.Loop.run()
finally:
    K.SA.log = real_log
check("the log names the old name and the new one",
      any("renamed from 'b' to 'renamed'" in m for m in said),
      [m for m in said if "renamed from" in m])
polys.drag(ids["a"], box(0, 0, 9, 10))          # and anything later under lock
K.Loop.run()
check("the features keep the new name",
      polys.getFeature(ids["b"])["class_name"] == "renamed",
      polys.getFeature(ids["b"])["class_name"])
check("and the drag is still put back",
      abs(K.shape_of(polys, ids["a"]).area - 50) < 1e-9,
      K.shape_of(polys, ids["a"]).area)

print()
print("a settling that fails is taken back and not announced")
host, polys, tiles, ids = campaign()
K.Bar.said[:] = []
real_give = K.Host.give_back


def broken_give(self, *a):
    raise RuntimeError("GEOS said no")


K.Host.give_back = broken_give
try:
    polys.drag(ids["a"], box(0, 0, 7, 10))
    K.Loop.run()
finally:
    K.Host.give_back = real_give
check("the neighbour is as it was before the tidying",
      abs(K.shape_of(polys, ids["b"]).area - 50) < 1e-9,
      K.shape_of(polys, ids["b"]).area)
check("and no 'vertex moved: 1 neighbour trimmed' is said",
      not any("vertex moved" in m for m in K.Bar.said), K.Bar.said)

print()
print("an undo of many changes looks at the layer once, not once per change")
host, polys, tiles, ids = campaign()
polys.drag(ids["a"], box(0, 0, 7, 10))
K.Loop.run()
calls = []
real_remember = K.Host.remember_shapes
K.Host.remember_shapes = lambda self: (calls.append(1), real_remember(self))
try:
    host._settling = True               # a command of ours, not a drag
    polys.beginEditCommand("many")
    for k, fid in enumerate((ids["a"], ids["b"])):
        polys.changeGeometry(fid, K.G(box(0, 0, 1 + k, 1)))
    polys.endEditCommand()
    host._settling = False
    K.Loop.run()
    calls[:] = []
    polys.undoStack().undo()            # two geometry changes replayed
    K.Loop.run()
finally:
    K.Host.remember_shapes = real_remember
check("one scan", len(calls) <= 1, len(calls))

# ------------------------------------------------------- readings apart
print()
print("with 'one operator at a time' off, a drag still settles only its reading")
# Off, every operator is on screen and in scope_polygons(). The settling used
# the same scope, so dragging OP1's border cut OP2's polygons and OP2's ground
# blocked the gift back to OP1: two readings that exist to be compared, each
# rewritten by the other.
host, polys, tiles, ids = campaign()
host.by_operator.setChecked(False)
o2a = K.put(polys, box(0, 0, 6, 10), class_name="b", class_code=2,
            tile_id="t001", pass_no=1, operator="OP2")
o2b = K.put(polys, box(6, 0, 10, 10), class_name="a", class_code=1,
            tile_id="t001", pass_no=1, operator="OP2")
for f in (o2a, o2b):
    polys.buffer[f] = polys.saved[f].copy()
host.remember_shapes()
polys.drag(ids["a"], box(0, 0, 4, 10))          # OP1 pulls a border back
K.Loop.run()
check("OP1's neighbour takes the strip, OP2 or not",
      abs(K.shape_of(polys, ids["b"]).area - 60) < 1e-9,
      K.shape_of(polys, ids["b"]).area)
check("OP2's polygons are exactly as they were",
      abs(K.shape_of(polys, o2a).area - 60) < 1e-9
      and abs(K.shape_of(polys, o2b).area - 40) < 1e-9,
      (K.shape_of(polys, o2a).area, K.shape_of(polys, o2b).area))

print()
print("a stroke next to another operator's polygon does not take it over")
# add_merging merges a new stroke with the touching polygons of its class, and
# with the operators shown together it merged OP2's polygon into OP1's stroke:
# OP2's polygon was deleted and the union written under OP1.
polys = K.Layer("polygons")
tiles = K.Layer("tiles")
K.put(tiles, T1, tile_id="t001")
theirs = K.put(polys, box(0, 0, 5, 10), class_name="a", class_code=1,
               tile_id="t001", pass_no=1, operator="OP2")
host = K.Host(polys, tiles)
host.by_operator.setChecked(False)
polys.startEditing()
host.remember_shapes()
host.class_name = "a"
host.paint(K.G(box(5, 0, 8, 10)))
K.Loop.run()
op2_now = [f for f in polys.getFeatures() if f["operator"] == "OP2"]
check("OP2's polygon is still OP2's",
      len(op2_now) == 1 and abs(op2_now[0]._g.s.area - 50) < 1e-9,
      [(f["operator"], f._g.s.area) for f in polys.getFeatures()])
mine = [f for f in polys.getFeatures() if f["operator"] == "OP1"]
check("and the stroke is OP1's, on its own",
      len(mine) == 1 and abs(mine[0]._g.s.area - 30) < 1e-9,
      [(f["operator"], f._g.s.area) for f in polys.getFeatures()])

print()
print("a polygon whose frame is gone gives nothing away, whatever frame is selected")
results = []
for selected in ("t001", "t002"):
    polys = K.Layer("polygons")
    tiles = K.Layer("tiles")
    K.put(tiles, T1, tile_id="t001")
    K.put(tiles, T2, tile_id="t002")
    oa = K.put(polys, box(0, 0, 5, 10), class_name="a", class_code=1,
               tile_id="gone", pass_no=1, operator="OP1")
    ob = K.put(polys, box(5, 0, 10, 10), class_name="b", class_code=2,
               tile_id="gone", pass_no=1, operator="OP1")
    host = K.Host(polys, tiles, tile_id=selected)
    polys.startEditing()
    host.remember_shapes()
    polys.drag(oa, box(0, 0, 4, 10))
    K.Loop.run()
    results.append(K.shape_of(polys, ob).area)
check("the result does not depend on the list", results[0] == results[1],
      results)

# ------------------------------------------------------------------ A1b
print()
print("a piece split off another reading keeps that reading")
# The lobes of an untangled bow tie, the leftover of a trim, the ground a
# neighbour takes: all of them used to be written with the frame, pass and
# operator in hand. Dragged in t002 by OP2, with OP1 and t001 in the panel,
# the second lobe came out as OP1's work in t001.
from shapely.geometry import Polygon
host, polys, tiles, ids = campaign(with_t2=True)
host.by_operator.setChecked(False)
op2 = K.put(polys, box(21, 1, 27, 7), class_name="c", class_code=3,
            tile_id="t002", pass_no=2, operator="OP2")
polys.buffer[op2] = polys.saved[op2].copy()
host.remember_shapes()
bow = Polygon([(21, 1), (27, 7), (27, 1), (21, 7)])    # crosses itself
polys.drag(op2, bow)
K.Loop.run()
lobes = [f for f in polys.getFeatures() if f["class_name"] == "c"]
check("the bow tie became two lobes", len(lobes) == 2, len(lobes))
check("both are still OP2's",
      all(f["operator"] == "OP2" for f in lobes),
      [f["operator"] for f in lobes])
check("in t002, pass 2",
      all(f["tile_id"] == "t002" and f["pass_no"] == 2 for f in lobes),
      [(f["tile_id"], f["pass_no"]) for f in lobes])

# ------------------------------------------------------------------ DO5
print()
print("what Check calls an overlap, Repair resolves")
# Check counts as overlap anything above a hundredth of a pixel. Repair used
# to act only above four pixels, the sliver threshold, so an overlap of two
# pixels was a PROBLEM in one window and "0 overlaps resolved" in the other.
host, polys, tiles, ids = campaign()
polys.buffer[ids["b"]].setGeometry(K.G(box(4.8, 0, 10, 10)))   # 2 px shared
before = K.overlap_area(polys)
host.repair()
check("there was an overlap of two pixels", abs(before - 2.0) < 1e-9, before)
check("Repair takes it away", K.overlap_area(polys) < 1e-9,
      K.overlap_area(polys))
check("and the frame is still covered", abs(K.covered(polys, T1) - 100) < 1e-9,
      K.covered(polys, T1))

# ------------------------------------------------------------------ R1
print()
print("a frame moved with its contents carries them, and paints nothing new")


class Ask(object):
    """QMessageBox, answering the first button it was given."""
    Warning = Cancel = AcceptRole = DestructiveRole = 0

    def __init__(self, *a): self.buttons = []
    def setIcon(self, *a): pass
    def setWindowTitle(self, *a): pass
    def setText(self, *a): pass
    def setInformativeText(self, *a): pass
    def setDefaultButton(self, *a): pass
    def button(self, *a): return None

    def addButton(self, *a):
        b = object()
        self.buttons.append(b)
        return b

    def clickedButton(self): return self.buttons[0]


# The program asks for QMessageBox.StandardButton.Yes, QMessageBox.Icon.Warning
# and the like, the spelling Qt 5 and Qt 6 share: the stand-in answers to
# those through itself.
Ask.Icon = Ask.StandardButton = Ask.ButtonRole = Ask


K.SA.QMessageBox = Ask
K.SA.run_dialog = lambda d: None


def move(host, polys, tiles, ids):
    frame = [f for f in tiles.getFeatures() if f["tile_id"] == "t001"][0]
    host.move_tile(frame, 3.0, 0.0)
    K.Loop.run()
    return {k: K.shape_of(polys, v) for k, v in ids.items()}


def gapped():
    """A frame read only in part: a gap of two units between a and b."""
    host, polys, tiles, ids = campaign()
    polys.buffer[ids["a"]].setGeometry(K.G(box(0, 0, 4, 10)))
    polys.buffer[ids["b"]].setGeometry(K.G(box(6, 0, 10, 10)))
    polys.commitChanges()
    polys.startEditing()
    host.remember_shapes()
    return host, polys, tiles, ids


host, polys, tiles, ids = gapped()
after = move(host, polys, tiles, ids)
check("both polygons moved by 3", after["a"].bounds == (3, 0, 7, 10)
      and after["b"].bounds == (9, 0, 13, 10), (after["a"].bounds,
                                                 after["b"].bounds))
check("with their areas unchanged", abs(after["a"].area - 40) < 1e-9
      and abs(after["b"].area - 40) < 1e-9,
      (after["a"].area, after["b"].area))

# and the same move with the fix taken away, to show the test can see it
host, polys, tiles, ids = gapped()
real = K.Host._carry_or_drop


def unguarded(self, *a):
    # every guard off: the flag, the shapes remembered after the carry, and
    # the open-command test that also tells a carry from a hand drag
    self._settling = False
    self._command_open = None
    self.remember_shapes = lambda: None
    return real(self, *a)


K.Host._carry_or_drop = unguarded
try:
    broken = move(host, polys, tiles, ids)
finally:
    K.Host._carry_or_drop = real
    host.__dict__.pop("remember_shapes", None)
check("(without the flag the move does fabricate ground: the test can tell)",
      abs(broken["a"].area - 40) > 1e-6 or abs(broken["b"].area - 40) > 1e-6,
      (broken["a"].area, broken["b"].area))

# ------------------------------------------------------------------ R2
print()
print("the + of the Objects legend adds a class without falling over")
# add_class is lent to Objects, which has no view filter. Unguarded, it raised
# AttributeError after the class had been saved and the rename box never came.


class ObjectsLike(object):
    add_class = K.SA.AnnotationSection.__dict__["add_class"]

    def __init__(self):
        self.campaign = type("C", (), {})()
        self.campaign.data = {"classes": [{"name": "a", "code": 1,
                                           "colour": "#000000"}]}
        self.campaign.next_code = lambda: 2
        self.campaign.save = lambda: None
        self.panel = type("P", (), {"describe_campaign": lambda s: None})()
        self.renamed = []

    def rebuild_class_buttons(self): pass
    def start_rename(self, code): self.renamed.append(code)


K.SA.restyle = lambda campaign: None
o = ObjectsLike()
try:
    o.add_class()
    K.Loop.run()
    done = True
except AttributeError as err:
    done = False
    print("     ", err)
check("no AttributeError", done)
check("the class is in the legend", len(o.campaign.data["classes"]) == 2)
check("and the rename box is opened on it", o.renamed == [2], o.renamed)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
