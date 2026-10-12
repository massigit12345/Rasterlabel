"""The vertex tool, once put down, leaves no green X behind: run, not read.

QGIS's vertex tool keeps a cache of every table it has hovered over, and the
cache stays connected to the table's geometryChanged after the tool is put
down. Each geometry changed afterwards is checked by a tool nobody is holding,
and every fault the check finds, two edges of an outline crossing, is pinned
to the map as a green X that only putting the same tool down again deletes. A
frame moved with its contents changes every polygon in it, so after one Move
the map was dotted with green X marks over polygons that had moved, and
nothing in the panel could clear them.

The cure is in Panel.vertex_tool_put_down: when the canvas takes the vertex
tool away, every campaign table says its data changed, which is the signal on
which the tool drops its cache of a table and lets go of it. load_layers does
the same for the tables a campaign adopts from the project, which the tool may
still follow from before the plugin was upgraded or reloaded.

What is real here: move_tile and _carry_or_drop of AnnotationSection, run
through editkit, and vertex_tool_put_down of Panel, borrowed unchanged. What is
a model: the vertex tool, written to behave as qgsvertextool.cpp does in QGIS
3.36 where it matters (it connects to a table when it first reads a geometry
of it, validates on geometryChanged, deletes its marks when put down, and
disconnects on dataChanged). The case "without the cure" runs the same model
with the cure left out, and must show the marks, or the model proves nothing.
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
from shapely.geometry import Polygon, box                         # noqa: E402

from rasterlabel import panel as P                                # noqa: E402
from rasterlabel import project as T                                # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def attempt(name, fn):
    try:
        return fn()
    except Exception as err:
        import traceback
        traceback.print_exc()
        check(name + " (it ran)", False, "%s: %s" % (type(err).__name__, err))
        return None


class Meta(object):
    def __init__(self, name): self.name = name
    def className(self): return self.name


class MapTool(object):
    """A map tool as Python sees it: a base class, and Qt's name for it."""
    def __init__(self, name): self._meta = Meta(name)
    def metaObject(self): return self._meta


class VertexTool(MapTool):
    """What QgsVertexTool does with a table, and no more."""

    def __init__(self):
        super().__init__("QgsVertexTool")
        self.cached = {}            # layer id -> (layer, slots)
        self.marks = []             # (layer id, fid): one green X each

    def hover(self, lyr):
        """cachedGeometry: the first read of a table connects to it."""
        if lyr.id() in self.cached:
            return

        def changed(fid, geom, lyr=lyr):
            self.marks = [m for m in self.marks if m != (lyr.id(), fid)]
            shape = geom.s if hasattr(geom, "s") else None
            if shape is not None and not shape.is_valid:
                self.marks.append((lyr.id(), fid))

        def forget(lyr=lyr):
            lyr.geometryChanged.disconnect(changed)
            lyr.dataChanged.disconnect(forget)
            self.cached.pop(lyr.id(), None)

        lyr.geometryChanged.connect(changed)
        lyr.dataChanged.connect(forget)
        self.cached[lyr.id()] = (lyr, changed)

    def put_down(self):
        """deactivate(): the marks go, the cache and its signals stay."""
        self.marks = []


class Ask(object):
    """QMessageBox, answering its first button: move with the contents."""
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


T1 = box(0, 0, 10, 10)
# A bow tie: a ring whose edges cross, the fault the vertex tool marks.
BOW = Polygon([(1, 1), (4, 4), (4, 1), (1, 4), (1, 1)])
SQUARE = box(5, 5, 8, 8)


def campaign():
    polys = K.Layer("polygons")
    tiles = K.Layer("tiles")
    K.put(tiles, T1, tile_id="t001")
    K.put(tiles, box(30, 0, 40, 10), tile_id="t002")
    K.put(polys, BOW, tile_id="t001", class_name="a", class_code=1,
          operator="OP1", pass_no=1)
    K.put(polys, SQUARE, tile_id="t001", class_name="b", class_code=2,
          operator="OP1", pass_no=1)
    host = K.Host(polys, tiles)
    polys.startEditing()
    tiles.startEditing()
    return host


class Shell(object):
    """The panel, as far as vertex_tool_put_down reads it."""
    def __init__(self, host):
        self.campaign = host.campaign
        self.host = host

    def vertex_tool_let_go(self):
        return P.Panel.vertex_tool_let_go(self)


def move(host):
    real = (K.SA.QMessageBox, K.SA.run_dialog)
    K.SA.QMessageBox, K.SA.run_dialog = Ask, (lambda d: None)
    try:
        frame = [f for f in host.tile_layer.getFeatures()
                 if f["tile_id"] == "t001"][0]
        host.move_tile(frame, 12.0, 0.0)
        K.Loop.run()
    finally:
        K.SA.QMessageBox, K.SA.run_dialog = real


def put_down(shell, new, old):
    real = P.find_mine
    P.find_mine = lambda cid, role: shell.host.layers.get(role)
    try:
        return P.Panel.vertex_tool_put_down(shell, new, old)
    finally:
        P.find_mine = real


def without_cure():
    host = campaign()
    tool = VertexTool()
    tool.hover(host.polygons)
    tool.put_down()             # Move pressed: the frame tool takes the map
    move(host)
    check("the model shows the bug: without the cure a moved frame leaves a "
          "green X", len(tool.marks) == 1, tool.marks)


def with_cure():
    host = campaign()
    shell = Shell(host)
    tool = VertexTool()
    tool.hover(host.polygons)
    tool.put_down()
    told = put_down(shell, MapTool("TileTool"), tool)
    check("putting the vertex tool down tells the campaign tables",
          told == 2, told)
    check("and the vertex tool lets go of them", not tool.cached,
          list(tool.cached))
    move(host)
    check("a frame moved with its contents leaves no green X",
          tool.marks == [], tool.marks)
    moved = sorted(round(f.geometry().s.bounds[0], 6)
                   for f in host.polygons.getFeatures())
    check("and its polygons did move with it", moved == [13.0, 17.0], moved)
    # Back in hand, the tool works as before: a fault it finds while held is
    # shown, which is what a person dragging a vertex is meant to see.
    tool.hover(host.polygons)
    fid = [f.id() for f in host.polygons.getFeatures()][0]
    host.polygons.changeGeometry(fid, K.G(BOW))
    check("with the tool held again its marks are shown",
          len(tool.marks) == 1, tool.marks)


def leaves_alone():
    host = campaign()
    shell = Shell(host)
    seen = []
    host.polygons.dataChanged.connect(lambda: seen.append(1))
    tool = VertexTool()
    put_down(shell, MapTool("TileTool"), MapTool("BrushTool"))
    check("a change between the program's own tools tells nobody", not seen)
    put_down(shell, tool, MapTool("BrushTool"))
    check("taking the vertex tool up tells nobody", not seen)
    put_down(shell, tool, tool)
    check("nor does setting it again over itself", not seen)
    put_down(shell, None, None)
    check("nor a canvas with no tool before", not seen)
    shell.campaign = None
    check("and with no campaign open there is nothing to tell",
          put_down(shell, MapTool("TileTool"), tool) == 0)


def let_go(shell):
    real = P.find_mine
    P.find_mine = lambda cid, role: shell.host.layers.get(role)
    try:
        return P.Panel.vertex_tool_let_go(shell)
    finally:
        P.find_mine = real


def adopted():
    """The plugin upgraded without closing QGIS: the vertex tool was put down
    under the old plugin, which had no hook, and still follows the tables the
    reopened campaign adopts from the project. load_layers lets go of them."""
    host = campaign()
    shell = Shell(host)
    tool = VertexTool()
    tool.hover(host.polygons)
    tool.put_down()             # under the old plugin: nobody told the tables
    told = let_go(shell)
    check("a campaign loading its tables tells them all", told == 2, told)
    check("and the vertex tool from before lets go of them", not tool.cached,
          list(tool.cached))
    move(host)
    check("so the first frame moved leaves no green X", tool.marks == [],
          tool.marks)
    shell.campaign = None
    check("with no campaign open there is nothing to tell",
          let_go(shell) == 0)


def recognised():
    check("QGIS's vertex tool is recognised by its Qt name",
          T.is_vertex_tool(VertexTool()))
    check("the program's own tools are not",
          not T.is_vertex_tool(MapTool("TileTool")))
    check("nor is no tool", not T.is_vertex_tool(None))
    check("nor something that is not a Qt object",
          not T.is_vertex_tool(object()))


def wired():
    src = open(os.path.join(os.environ["RL_ROOT"], "rasterlabel", "panel.py"),
               encoding="utf-8").read()
    init = src[src.index("    def __init__"):src.index("    def _card")]
    check("the panel follows every change of map tool",
          "canvas().mapToolSet" in init and "vertex_tool_put_down" in init)
    load = src[src.index("    def load_layers"):src.index("    def edit_classes")]
    check("loading the tables lets go of the vertex tool, unless it is in hand",
          "vertex_tool_let_go()" in load
          and "is_vertex_tool(canvas().mapTool())" in load)


print("without the cure, in the model of the vertex tool")
attempt("without", without_cure)
print()
print("with it")
attempt("with", with_cure)
attempt("leaves alone", leaves_alone)
attempt("adopted", adopted)
attempt("recognised", recognised)
attempt("wired", wired)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
