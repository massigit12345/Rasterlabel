"""Frames do not overlap, and a frame is moved or deleted only by whose work it
holds: run, not read.

Two rules, each case run through the methods of AnnotationSection themselves
(editkit borrows them unchanged and lets GEOS do the arithmetic):

  overlap   a frame dragged onto another one is refused before anything is
            asked or written, whoever made the other frame; frames that only
            touch, edge to edge, are fine; the outline checked is the one put
            back on the grid, not the one the mouse let go of; a new frame
            placed half over an existing one is refused the same way
  owner     a frame can be moved or deleted only when everything it holds, in
            every table and every pass, is the current operator's work in the
            current pass; otherwise the refusal says whose work it is, by name
            and pass, and in a blind pass only that it is another reading; an
            empty frame moves and goes freely; a frame that passes the rule
            still offers "Move with its contents" and "Move and delete them"
  the tool  the frame tool does not pick up a frame it may not move, and its
            band turns red while it lies over another frame
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
from shapely.geometry import Point, box                            # noqa: E402

from rasterlabel import tools as T                                  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def attempt(name, fn):
    """Run one case; an error is a failure of that case, not of the suite."""
    try:
        return fn()
    except Exception as err:
        import traceback
        traceback.print_exc()
        check(name + " (it ran)", False, "%s: %s" % (type(err).__name__, err))
        return None


# --------------------------------------------------------------- the dialogs
class Ask(object):
    """QMessageBox for the move question: counts how often it was built and
    answers the button it is told to."""
    Warning = Cancel = AcceptRole = DestructiveRole = 0
    built = 0
    answer = 0                         # 0: with the contents, 1: delete them

    def __init__(self, *a):
        Ask.built += 1
        self.buttons = []
        self.text = ""

    def setIcon(self, *a): pass
    def setWindowTitle(self, *a): pass
    def setText(self, t): self.text = t
    def setInformativeText(self, *a): pass
    def setDefaultButton(self, *a): pass
    def button(self, *a): return None

    def addButton(self, *a):
        b = object()
        self.buttons.append((a[0] if a else None, b))
        return b

    def clickedButton(self): return self.buttons[Ask.answer][1]

    # the delete question
    Yes = 1
    asked = 0

    @staticmethod
    def question(*a, **k):
        Ask.asked += 1
        return Ask.Yes


# The program asks for QMessageBox.StandardButton.Yes, QMessageBox.Icon.Warning
# and the like, the spelling Qt 5 and Qt 6 share: the stand-in answers to
# those through itself.
Ask.Icon = Ask.StandardButton = Ask.ButtonRole = Ask


K.SA.QMessageBox = Ask
K.SA.run_dialog = lambda d: None

T1 = box(0, 0, 10, 10)
T2 = box(20, 0, 30, 10)


def campaign(operator="OP1", pass_no=1, blind=False):
    tables = {role: K.Layer(role)
              for role in ("polygons", "lines", "points", "boxes")}
    tiles = K.Layer("tiles")
    K.put(tiles, T1, tile_id="t001")
    K.put(tiles, T2, tile_id="t002")
    host = K.Host(tables["polygons"], tiles, operator=operator,
                  pass_no=pass_no)
    host.layers.update(tables)
    host.blind.setChecked(blind)
    host.refresh_tiles = lambda: None
    return host, tables, tiles


def frame(tiles, tid):
    return [f for f in tiles.getFeatures() if f["tile_id"] == tid][0]


def where(tiles, tid):
    return frame(tiles, tid).geometry().s.bounds


def mine(host, tables, role="polygons", shape=None, **values):
    values.setdefault("operator", "OP1")
    values.setdefault("pass_no", 1)
    values.setdefault("tile_id", "t001")
    values.setdefault("class_name", "a")
    values.setdefault("class_code", 1)
    return K.put(tables[role], shape if shape is not None
                 else box(1, 1, 4, 4), **values)


def move(host, tiles, tid, dx, dy=0.0):
    Ask.built = 0
    before = len(K.Bar.said)
    for lyr in list(host.layers.values()):
        if lyr is not None:
            lyr.startEditing()
    host.move_tile(frame(tiles, tid), dx, dy)
    K.Loop.run()
    return K.Bar.said[before:]


def delete(host, tid):
    """Delete asks in a box of its own, with a button named Delete tile:
    Ask counts it, and presses that button, the first one added."""
    Ask.built = 0
    answer, Ask.answer = Ask.answer, 0
    before = len(K.Bar.said)
    host._tile = tid
    try:
        host.delete_tile()
    finally:
        Ask.answer = answer
    Ask.asked = Ask.built
    return K.Bar.said[before:]


# ------------------------------------------------------------------ overlap
print("1. a frame is not moved onto another one")


def onto():
    host, tables, tiles = campaign()
    fid = mine(host, tables)
    said = move(host, tiles, "t001", 15.0)          # 15..25 over 20..30
    check("a drag that lands over t002 leaves t001 where it was",
          where(tiles, "t001") == (0, 0, 10, 10), where(tiles, "t001"))
    check("and t002 too", where(tiles, "t002") == (20, 0, 30, 10))
    check("nothing is asked first", Ask.built == 0, Ask.built)
    check("the contents are untouched",
          K.shape_of(tables["polygons"], fid).bounds == (1, 1, 4, 4))
    check("the refusal names the frame it would overlap",
          any("not moved" in s and "overlap t002" in s for s in said), said)


attempt("onto", onto)


def onto_empty():
    host, tables, tiles = campaign()
    said = move(host, tiles, "t001", 12.0)
    check("an empty frame is not dropped over another either",
          where(tiles, "t001") == (0, 0, 10, 10), where(tiles, "t001"))
    check("and it is said", any("overlap t002" in s for s in said), said)


attempt("onto_empty", onto_empty)


def onto_others_frame():
    # A frame holds no operator of its own; the one it would land on holds
    # another operator's work. It is still ground read by somebody.
    host, tables, tiles = campaign()
    K.put(tables["polygons"], box(21, 1, 24, 4), tile_id="t002",
          operator="OP2", pass_no=1, class_name="a", class_code=1)
    said = move(host, tiles, "t001", 14.0)
    check("over a frame holding another operator's work: refused as well",
          where(tiles, "t001") == (0, 0, 10, 10), said)


attempt("onto_others_frame", onto_others_frame)


def touching():
    host, tables, tiles = campaign()
    fid = mine(host, tables)
    said = move(host, tiles, "t001", 10.0)          # 10..20 touches 20..30
    check("a frame dropped edge to edge with another is moved",
          where(tiles, "t001") == (10, 0, 20, 10), (where(tiles, "t001"), said))
    check("after the usual question", Ask.built == 1, Ask.built)
    check("with its contents", K.shape_of(tables["polygons"], fid).bounds
          == (11, 1, 14, 4))


attempt("touching", touching)


def snapped():
    # The mouse lets go 10.4 to the right, which overlaps t002 by 0.4; the
    # frame is put back on the grid, at 10, where it only touches. The check is
    # made on the outline that would be written.
    host, tables, tiles = campaign()
    said = move(host, tiles, "t001", 10.4)
    check("what is checked is the outline put back on the grid",
          where(tiles, "t001") == (10, 0, 20, 10), (where(tiles, "t001"), said))
    host, tables, tiles = campaign()
    said = move(host, tiles, "t001", 10.6)          # snaps to 11: overlaps
    check("and one that snaps over the neighbour is refused",
          where(tiles, "t001") == (0, 0, 10, 10), (where(tiles, "t001"), said))


attempt("snapped", snapped)


def corner():
    host, tables, tiles = campaign()
    K.put(tiles, box(10, 10, 20, 20), tile_id="t003")
    said = move(host, tiles, "t002", -10.0, 10.0)    # to 10..20 x 10..20
    check("a frame dropped exactly on top of another is refused",
          where(tiles, "t002") == (20, 0, 30, 10), said)
    said = move(host, tiles, "t002", -10.0, 0.0)     # to 10..20 x 0..10
    check("one meeting another only at a corner and an edge is moved",
          where(tiles, "t002") == (10, 0, 20, 10), (where(tiles, "t002"), said))


attempt("corner", corner)

print()
print("2. a new frame is not placed over another one")


def placing(centre_x, side=10.0):
    host, tables, tiles = campaign()
    host.tile_side = K.Spin(side)
    host.geometry.crs = None
    host.lock_view = K.Tick(False)
    host.select_tile = lambda tid: None
    host.use_brush = lambda: None
    host.free_tile_id = lambda: "t009"
    before = len(K.Bar.said)
    # the line create_tile logs once the frame is down names its centre and
    # its CRS, two things the kit has no use for otherwise
    K.Box.center = lambda b: Centre((b.b[0] + b.b[2]) / 2, (b.b[1] + b.b[3]) / 2)
    real = K.SA.crs_label
    K.SA.crs_label = lambda crs: "the campaign CRS"
    try:
        host.create_tile(Centre(centre_x, 5.0))
    finally:
        K.SA.crs_label = real
        del K.Box.center
    return tiles, K.Bar.said[before:]


class Centre(K.Pt):
    def toString(self, n): return "%.*f, %.*f" % (n, self.x(), n, self.y())


def creating():
    tiles, said = placing(15.0)            # 10..20 would touch both: fine
    check("a frame placed between two, touching both, is placed",
          tiles.featureCount() == 3, (tiles.featureCount(), said))
    tiles, said = placing(13.0)            # 8..18 over t001
    check("one placed half over t001 is not",
          tiles.featureCount() == 2, tiles.featureCount())
    check("and the refusal says which frame is in the way",
          any("no frame placed" in s and "overlap t001" in s for s in said),
          said)
    tiles, said = placing(15.0, side=14.0)  # 8..22 over both
    check("one over both names both",
          tiles.featureCount() == 2
          and any("t001, t002" in s for s in said), said)


attempt("creating", creating)

# ------------------------------------------------------------------- owner
print()
print("3. a frame is moved only by whose work it holds")


def own():
    host, tables, tiles = campaign()
    fid = mine(host, tables)
    pid = mine(host, tables, "points", Point(5.5, 5.5))
    said = move(host, tiles, "t001", 0.0, 12.0)
    check("a frame holding only my work of this pass is moved",
          where(tiles, "t001") == (0, 12, 10, 22), said)
    check("after the question with both answers",
          Ask.built == 1, Ask.built)
    check("and the polygon and the point travel with it",
          K.shape_of(tables["polygons"], fid).bounds == (1, 13, 4, 16)
          and K.shape_of(tables["points"], pid).coords[0] == (5.5, 17.5))


attempt("own", own)


def own_dropped():
    host, tables, tiles = campaign()
    fid = mine(host, tables)
    Ask.answer = 1
    try:
        move(host, tiles, "t001", 0.0, 12.0)
    finally:
        Ask.answer = 0
    check("'Move and delete them' still moves the frame and deletes its work",
          where(tiles, "t001") == (0, 12, 10, 22)
          and K.shape_of(tables["polygons"], fid) is None)


attempt("own_dropped", own_dropped)


def buttons():
    host, tables, tiles = campaign()
    mine(host, tables)
    seen = []
    real = Ask.addButton

    def spy(self, *a):
        seen.append(a[0] if a else None)
        return real(self, *a)
    Ask.addButton = spy
    try:
        move(host, tiles, "t001", 0.0, 12.0)
    finally:
        Ask.addButton = real
    check("the question still offers both answers",
          "Move with its contents" in seen and "Move and delete them" in seen,
          seen)


attempt("buttons", buttons)


def empty():
    host, tables, tiles = campaign(operator="OP2", pass_no=3, blind=True)
    said = move(host, tiles, "t001", 0.0, 12.0)
    check("an empty frame moves, whoever moves it, in any pass",
          where(tiles, "t001") == (0, 12, 10, 22), said)
    check("without a question", Ask.built == 0, Ask.built)


attempt("empty", empty)


def others(role, shape):
    host, tables, tiles = campaign()
    mine(host, tables)
    oid = mine(host, tables, role, shape, operator="Anna")
    said = move(host, tiles, "t001", 0.0, 12.0)
    check("%s by another operator: the frame is not moved" % role,
          where(tiles, "t001") == (0, 0, 10, 10), said)
    check("%s: nothing asked, nothing touched" % role,
          Ask.built == 0 and K.shape_of(tables[role], oid) is not None)
    check("%s: the refusal names the operator and the pass" % role,
          any("cannot be moved" in s and "1 mark by ANNA in pass 1" in s
              for s in said), said)
    return said


attempt("polygons", lambda: others("polygons", box(5, 5, 8, 8)))
attempt("lines", lambda: others("lines", box(5, 5, 8, 6)))
attempt("points", lambda: others("points", Point(6.5, 6.5)))
attempt("boxes", lambda: others("boxes", box(6, 6, 9, 9)))


def several():
    host, tables, tiles = campaign()
    for i in range(3):
        mine(host, tables, operator="ANNA", shape=box(i, 5, i + 1, 6))
    mine(host, tables, "points", Point(2.5, 2.5), operator="BEN", pass_no=2)
    said = move(host, tiles, "t001", 0.0, 12.0)
    check("every hand in the frame is named, with its pass",
          any("3 marks by ANNA in pass 1" in s and "1 mark by BEN in pass 2"
              in s for s in said), said)


attempt("several", several)


def earlier_pass():
    host, tables, tiles = campaign(pass_no=2)
    mine(host, tables, pass_no=1)
    said = move(host, tiles, "t001", 0.0, 12.0)
    check("my own work of an earlier pass holds the frame too",
          where(tiles, "t001") == (0, 0, 10, 10), said)
    check("and it is said as mine",
          any("1 mark by you (OP1) in pass 1" in s for s in said), said)
    check("with the rule in the words of this pass",
          any("own work of pass 2" in s for s in said), said)


attempt("earlier_pass", earlier_pass)


def unnamed():
    # A mark written before the operator field existed belongs to nobody
    # named; somebody whose box is empty is that same nobody.
    host, tables, tiles = campaign(operator="")
    K.put(tables["polygons"], box(1, 1, 4, 4), tile_id="t001",
          class_name="a", class_code=1)
    move(host, tiles, "t001", 0.0, 12.0)
    check("a mark with no operator and no pass is the unnamed operator's, "
          "in pass 1", where(tiles, "t001") == (0, 12, 10, 22))
    host, tables, tiles = campaign(operator="OP1")
    K.put(tables["polygons"], box(1, 1, 4, 4), tile_id="t001",
          class_name="a", class_code=1)
    said = move(host, tiles, "t001", 0.0, 12.0)
    check("and not OP1's", where(tiles, "t001") == (0, 0, 10, 10)
          and any("by UNNAMED in pass 1" in s for s in said), said)


attempt("unnamed", unnamed)


def blind():
    host, tables, tiles = campaign(operator="BEN", pass_no=2, blind=True)
    mine(host, tables, pass_no=2, operator="BEN")
    mine(host, tables, pass_no=1, operator="ANNA", shape=box(5, 5, 8, 8))
    said = move(host, tiles, "t001", 0.0, 12.0)
    check("blind pass: another reading in the frame holds it",
          where(tiles, "t001") == (0, 0, 10, 10), said)
    check("and the refusal says so",
          any("work of another reading" in s for s in said), said)
    check("without a name or a count",
          not any("ANNA" in s or "mark" in s for s in said), said)


attempt("blind", blind)


def not_blind_names():
    # Pass 2 with blind off shows the earlier passes, so naming them gives
    # nothing away.
    host, tables, tiles = campaign(operator="BEN", pass_no=2, blind=False)
    mine(host, tables, pass_no=1, operator="ANNA")
    said = move(host, tiles, "t001", 0.0, 12.0)
    check("pass 2 seen in the open: the names are given",
          any("by ANNA in pass 1" in s for s in said), said)


attempt("not_blind_names", not_blind_names)


def overlap_first():
    # A frame refused on both counts is refused for the overlap, which is
    # where it was dropped, and nothing is asked.
    host, tables, tiles = campaign()
    mine(host, tables, operator="ANNA")
    said = move(host, tiles, "t001", 15.0)
    check("refused on both counts: one refusal, the overlap, nothing asked",
          Ask.built == 0 and len([s for s in said if "cannot" in s
                                  or "not moved" in s]) == 1
          and any("overlap" in s for s in said), said)


attempt("overlap_first", overlap_first)

# ------------------------------------------------------------------ delete
print()
print("4. a frame is deleted only by whose work it holds")


def delete_others():
    host, tables, tiles = campaign()
    mine(host, tables)
    oid = mine(host, tables, "boxes", box(6, 6, 9, 9), operator="ANNA")
    said = delete(host, "t001")
    check("a frame holding another operator's box is not deleted",
          tiles.featureCount() == 2, tiles.featureCount())
    check("nothing is asked, the box is still there",
          Ask.asked == 0 and K.shape_of(tables["boxes"], oid) is not None)
    check("and the refusal names whose it is",
          any("cannot be deleted" in s and "1 mark by ANNA in pass 1" in s
              for s in said), said)


attempt("delete_others", delete_others)


def delete_blind():
    host, tables, tiles = campaign(operator="BEN", pass_no=2, blind=True)
    mine(host, tables, pass_no=1, operator="ANNA")
    said = delete(host, "t001")
    check("blind pass: the first reading keeps its frame",
          tiles.featureCount() == 2 and Ask.asked == 0, said)
    check("anonymously", any("another reading" in s for s in said)
          and not any("ANNA" in s for s in said), said)


attempt("delete_blind", delete_blind)


def delete_own():
    host, tables, tiles = campaign()
    fid = mine(host, tables)
    delete(host, "t001")
    check("my own frame is deleted after the question",
          Ask.asked == 1 and tiles.featureCount() == 1
          and K.shape_of(tables["polygons"], fid) is None)


attempt("delete_own", delete_own)


def delete_empty():
    host, tables, tiles = campaign(operator="BEN", pass_no=2, blind=True)
    delete(host, "t002")
    check("an empty frame is deleted by anybody",
          tiles.featureCount() == 1
          and [f["tile_id"] for f in tiles.getFeatures()] == ["t001"])


attempt("delete_empty", delete_empty)

# ------------------------------------------------------------------ the tool
print()
print("5. the frame tool")


class Crs(object):
    pass


class Settings(object):
    def __init__(self, crs): self.crs = crs
    def destinationCrs(self): return self.crs


class Canvas(object):
    def __init__(self, crs): self.s = Settings(crs)
    def mapSettings(self): return self.s


class Band(object):
    def __init__(self): self.colours = []
    def setColor(self, c): self.colours.append(c)
    def setFillColor(self, c): pass
    def setToGeometry(self, *a): pass
    def reset(self, *a): pass


class Colour(object):
    def __init__(self, *a): self.v = a
    def __eq__(self, o): return self.v == o.v
    def __repr__(self): return "Colour%r" % (self.v,)


class Ev(object):
    def __init__(self, x, y): self.p = K.Pt(x, y)
    def button(self): return T.Qt.MouseButton.LeftButton
    def pos(self): return self.p


class Tool(object):
    """TileTool's methods on a plain object, without a canvas behind it."""
    def __init__(self, host):
        self.section = host
        self.canvas = Canvas(host.geometry.crs)
        self.band = Band()
        self.dragging = self.start = self.pressed_at = None
        self.others = []

    def _layer_point(self, ev): return ev.pos()
    def setCursor(self, *a): pass


for _name in ("canvasPressEvent", "canvasMoveEvent", "paint_band"):
    setattr(Tool, _name, T.TileTool.__dict__[_name])


def tool_case():
    T.QgsGeometry = K.G
    T.QColor = Colour
    host, tables, tiles = campaign()
    host.geometry.crs = Crs()
    host.tile_at = lambda p: [f for f in tiles.getFeatures()
                              if f.geometry().s.contains(Point(p.x(), p.y()))][0]
    host.select_tile = lambda tid: None
    host.can_move_frames = lambda: True
    mine(host, tables, operator="ANNA")
    tool = Tool(host)
    before = len(K.Bar.said)
    tool.canvasPressEvent(Ev(5.0, 5.0))
    check("a frame holding another operator's work is not picked up",
          tool.dragging is None, tool.dragging)
    check("and the press says why", any("cannot be moved" in s
                                        for s in K.Bar.said[before:]))
    tool = Tool(host)
    tool.canvasPressEvent(Ev(25.0, 5.0))           # t002, empty
    check("an empty one is", tool.dragging is not None
          and tool.dragging["tile_id"] == "t002")
    check("and the others are read once, on the press, without itself",
          [f["tile_id"] for f in tool.others] == ["t001"], tool.others)
    tool.canvasMoveEvent(Ev(28.0, 5.0))             # 23..33: free ground
    free = tool.band.colours[-1]
    tool.canvasMoveEvent(Ev(18.0, 5.0))             # 13..23: over nothing
    check("the band stays yellow over free ground",
          tool.band.colours[-1] == free == Colour("#ffdc00"),
          tool.band.colours[-2:])
    tool.canvasMoveEvent(Ev(12.0, 5.0))             # 7..17: over t001
    check("and turns red over another frame",
          tool.band.colours[-1] == Colour("#e0281e"), tool.band.colours[-1])
    tool.canvasMoveEvent(Ev(15.0, 5.0))             # 10..20: touching
    check("and back to yellow where it only touches",
          tool.band.colours[-1] == Colour("#ffdc00"), tool.band.colours[-1])


attempt("tool", tool_case)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
