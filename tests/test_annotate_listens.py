"""Annotate listens to the tables it has now, and gives the map back.

The same three things test_annotate_safety_qgis.py runs in a real QGIS, here
on the kit that needs none, so that a machine without QGIS runs them too:

  reread    a table read again is another object with the same id. The check
            that a table was being listened to compared the ids, so the new
            one was taken for the old and nobody listened to it: a vertex
            dragged was no longer settled;
  table     the table of the polygons taken out of the project: the next
            stroke loads it again and says so, instead of going nowhere;
  tool      closing a module hands the canvas the tool it had before, Pan when
            there was none, and leaves alone a tool the person picked since.
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

from rasterlabel import tools as T

SA = K.SA
fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def two_polygons(layer):
    """a on the left, b on the right, one frame between them."""
    a = K.put(layer, box(0, 0, 10, 20), class_name="a", class_code=1,
              tile_id="t001", pass_no=1, operator="OP1")
    b = K.put(layer, box(10, 0, 20, 20), class_name="b", class_code=2,
              tile_id="t001", pass_no=1, operator="OP1")
    return a, b


def frame():
    tiles = K.Layer("tiles")
    K.put(tiles, box(0, 0, 20, 20), tile_id="t001")
    return tiles


# ---------------------------------------------------------------- reread
print("a table read again is listened to again")
old = K.Layer("polygons")
tiles = frame()
a, b = two_polygons(old)
host = K.Host(old, tiles)
host.geometry.origin = (0.0, 20.0)
old.startEditing()
host.remember_shapes()

# the project is read again: the same table, as a new object with the same id
new = K.Layer("polygons")
new._id = old._id
two_polygons(new)
host.layers["polygons"] = new
before = host.watched_tables()
host.layers_came()
K.Loop.run()
check("the new table is the one listened to now",
      host._watching is new, host._watching)
check("and what is listened to has changed",
      host.watched_tables() != before)
new.startEditing()
host.remember_shapes()
new.drag(a, box(0, 0, 14, 20))
K.Loop.run()
left = K.shape_of(new, b)
check("a vertex dragged into the neighbour is settled: b is trimmed",
      left is not None and abs(left.area - 120.0) < 1e-6,
      None if left is None else left.area)
check("no ground is claimed twice", K.overlap_area(new) < 1e-6,
      K.overlap_area(new))

# and nothing is hooked twice when nothing changed
count = len(host.__dict__.get("_hooks", []))
host.layers_came()
K.Loop.run()
check("nothing is hooked again when the tables are the same",
      len(host.__dict__.get("_hooks", [])) == count)

# ----------------------------------------------------------------- table
print()
print("the table of the polygons taken out of the project")
polys = K.Layer("polygons")
host = K.Host(polys, frame())
loaded = []


def load_layers():
    loaded.append(1)
    back = K.Layer("polygons")
    host.layers["polygons"] = back


host.panel.load_layers = load_layers
host.layers["polygons"] = None
K.Bar.said[:] = []
got = host.table_back("polygons")
check("the table is loaded again", got is not None and loaded == [1],
      (got, loaded))
check("and it is said", any("taken out of the project" in m
                            for m in K.Bar.said), K.Bar.said)
loaded[:] = []
again = host.table_back("polygons")
check("a table that is there is left alone", again is got and not loaded,
      loaded)

host.layers["polygons"] = None
host.panel.load_layers = lambda: None
K.Bar.said[:] = []
check("when it cannot be loaded there is no table",
      host.table_back("polygons") is None)
check("and it is said that nothing was drawn",
      any("nothing was drawn" in m for m in K.Bar.said), K.Bar.said)

# ------------------------------------------------------------------ tool
print()
print("closing a module gives the map back")


class Mine(T.BrushTool):
    def __init__(self): pass


class Pen(object):
    """A tool of QGIS's, or of somebody else's."""


class Canvas(object):
    def __init__(self, tool=None):
        self.tool = tool
        self.set = []

    def mapTool(self): return self.tool

    def setMapTool(self, tool):
        self.tool = tool
        self.set.append(tool)

    def unsetMapTool(self, tool):
        if self.tool is tool:
            self.tool = None


class Face(object):
    def __init__(self, canvas, pan=True):
        self.canvas, self.pan = canvas, pan
        self.panned = 0

    def actionPan(self):
        if not self.pan:
            raise AttributeError("no pan action")
        face = self

        class Action(object):
            def trigger(self):
                face.panned += 1
                face.canvas.tool = Pen()
        return Action()


def hand(before, current, pan=True):
    cv = Canvas(current)
    face = Face(cv, pan)
    T.canvas = lambda: cv
    T.iface = face
    mine = Mine()
    if current == "mine":
        cv.tool = mine
    gave = T.hand_back_tool(before, (mine, None))
    return gave, cv, face


pen = Pen()
gave, cv, face = hand(pen, "mine")
check("the tool the person had comes back", gave and cv.tool is pen
      and not face.panned, (cv.tool, face.panned))
gave, cv, face = hand(None, "mine")
check("with none before, Pan", gave and face.panned == 1, face.panned)
gave, cv, face = hand(Mine(), "mine")
check("a tool of ours before is not given back, Pan is",
      gave and face.panned == 1 and not isinstance(cv.tool, Mine))
other = Pen()
cv = Canvas(other)
T.canvas = lambda: cv
T.iface = Face(cv)
gave = T.hand_back_tool(pen, (Mine(),))
check("a tool the person picked since is left alone",
      not gave and cv.tool is other and not cv.set)

# ------------------------------------------------------------------- keys
print()
print("a key the tool took is not QGIS's too")
from qtbinding.QtGui import QKeyEvent
from qtbinding.QtCore import QEvent, Qt


def key(code):
    ev = QKeyEvent(QEvent.Type.KeyPress, code, Qt.KeyboardModifier.NoModifier)
    ev.accept()                     # what QgsMapCanvas does before the tool
    return ev


class Redrawn(object):
    def _redraw(self, *a): pass


class Pencil(Redrawn, T.LineTool):
    def __init__(self):
        self.points, self.last_point = [1, 2], None


class Pen2(Redrawn, T.BrushTool):
    def __init__(self):
        self.points = [1, 2]


for name, tool in (("Line", Pencil()), ("Brush", Pen2())):
    ev = key(Qt.Key.Key_Backspace)
    tool.keyPressEvent(ev)
    check("%s: Backspace takes a vertex back and is left ignored" % name,
          tool.points == [1] and not ev.isAccepted(), tool.points)
    tool.points = []
    ev = key(Qt.Key.Key_Backspace)
    tool.keyPressEvent(ev)
    check("%s: with none left it is still ignored, so that a held key "
          "deletes nothing" % name, not ev.isAccepted())
    ev = key(Qt.Key.Key_Delete)
    tool.keyPressEvent(ev)
    check("%s: Delete is none of its business" % name, ev.isAccepted())


class Deleted(object):
    timing = None
    gone = 0

    def delete_selected(self):
        self.gone += 1


class Boxer(T.BoxTool):
    def __init__(self):
        self.section = Deleted()

    def show_selection(self): pass


boxer = Boxer()
for code in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
    ev = key(code)
    boxer.keyPressEvent(ev)
check("Box: Delete and Backspace delete the box and are left ignored",
      boxer.section.gone == 2 and not ev.isAccepted(), boxer.section.gone)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
