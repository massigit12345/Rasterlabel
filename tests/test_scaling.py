"""The arithmetic of stretching a rectangle by a corner, of putting a frame
back on whole pixels, and of measuring a frame whose outline changed after it
was painted, all taken out of the shipped file exactly as written and run
against real GDAL geometry.

What has to hold: the corner you do not touch must not move by even one pixel,
because that is the ground that is already annotated; the frame must land on
whole pixels; a polygon left hanging over the edge of a frame that shrank must
count only for the part inside it; and the handle on a corner must shrink with
a small rectangle, so that there is always a middle left to pick it up by.

Written first against the original single-file prototype, where all of it
lived in two places: a map tool that resized frames by their corners, with one
helper for the drag, one for the size of the handle and one for which corner a
click lands on, and a method that gave the two sides shown. A resize step then
snapped the result to the grid and cut the polygons on the new edge, and this
suite retyped that snapping instead of running it.

The package moved things around, and some of it went away on purpose:

  * Frames are no longer resized by the program. README, under known limits:
    "A frame cannot be resized once placed." So the resize step is gone, and
    with it the cutting of polygons on a shrunk edge and the writing of them
    back. A frame's outline can still change under the program, with the QGIS
    vertex tool, and when it does the program does not rewrite the polygons:
    it clips them to the frame at the moment it measures. That clipping, in
    refresh_coverage() (the figure on the panel) and measure_tile() (the
    side_m and closed columns written into the file), is what the shrink and
    coverage checks now run.
  * Stretching a rectangle by its corner lives on in BoxTool, the object box
    tool: _corner_grabbed() finds the corner under the click and answers the
    opposite one, the anchor, and the release builds QgsRectangle(anchor,
    point). The drag checks drive canvasPressEvent and canvasReleaseEvent
    themselves, so the arithmetic tested is the arithmetic the tool runs.
  * There is no handle-size helper any more: the reach of a corner is
    computed inside _corner_grabbed. The handle checks therefore probe it
    from the outside, clicking at so many screen pixels from a corner and
    seeing whether the corner is taken. The reach is measured in screen
    pixels, through _on_screen, and the same probes are run with the campaign
    in degrees on a canvas in metres and the other way round, where a reach
    measured in map units came out many times too large or many times too
    small.
  * Snapping to the grid is Geometry.regrid() (a frame put back on the grid
    after a move, keeping its size in pixels) and Geometry.snapped_square()
    (a frame placed on the grid in the first place). Both are run here, where
    the prototype's snapping was retyped and never ran program code at all.
  * The two sides shown are ObjectsSection.too_small(), which measures width
    and height for the width_m and height_m columns, and measure_tile(),
    which writes the width of a frame as side_m.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import math
import os as _os
import sys

from osgeo import ogr

ogr.UseExceptions()

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

SRC = _os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)


def function(name, inside=None):
    for node in tree.body:
        if (inside is None and isinstance(node, ast.FunctionDef)
                and node.name == name):
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    first = min([sub.lineno] +
                                [d.lineno for d in sub.decorator_list])
                    t = "".join(lines[first - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s.%s not found" % (inside, name))


def constant(name):
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", None) == name):
            return ast.literal_eval(node.value)
    raise AssertionError("%s not found" % name)


HANDLE_PX = constant("HANDLE_PX")
MOVE_PX = constant("MOVE_PX")


# --------------------------------------------------------------- the fakes
class Point(object):
    def __init__(self, x, y): self._x, self._y = float(x), float(y)
    def x(self): return self._x
    def y(self): return self._y


class Rect(object):
    """QgsRectangle as far as the code under test uses it. Built from four
    numbers or from two points, and normalised either way, as QGIS does."""
    def __init__(self, a, b, c=None, d=None):
        if c is None:
            a, b, c, d = a.x(), a.y(), b.x(), b.y()
        self.v = [min(a, c), min(b, d), max(a, c), max(b, d)]
    def xMinimum(self): return self.v[0]
    def yMinimum(self): return self.v[1]
    def xMaximum(self): return self.v[2]
    def yMaximum(self): return self.v[3]
    def width(self): return self.v[2] - self.v[0]
    def height(self): return self.v[3] - self.v[1]
    def area(self): return self.width() * self.height()
    def contains(self, p):
        return (self.v[0] <= p.x() <= self.v[2] and
                self.v[1] <= p.y() <= self.v[3])
    def __repr__(self):
        return "Rect(%.4f %.4f %.4f %.4f)" % tuple(self.v)


class Geom(object):
    """QgsGeometry backed by a real OGR geometry, so the clipping and the
    unions the program asks for are done by GDAL and not by this file."""
    def __init__(self, g): self.g = g

    @staticmethod
    def fromRect(r):
        return Geom(square(r.xMinimum(), r.yMinimum(),
                           r.xMaximum(), r.yMaximum()))

    @staticmethod
    def unaryUnion(pieces):
        out = pieces[0].g.Clone()
        for p in pieces[1:]:
            out = out.Union(p.g)
        return Geom(out)

    def intersection(self, other): return Geom(self.g.Intersection(other.g))
    def isEmpty(self): return self.g.IsEmpty()
    def area(self): return self.g.GetArea()

    def boundingBox(self):
        x0, x1, y0, y1 = self.g.GetEnvelope()
        return Rect(x0, y0, x1, y1)


def square(x0, y0, x1, y1):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)):
        ring.AddPoint_2D(x, y)
    p = ogr.Geometry(ogr.wkbPolygon)
    p.AddGeometry(ring)
    return p


class FakeMeasure(object):
    """measureLine on a plane: enough to check which pair of corners is used."""
    def measureLine(self, a, b):
        return math.hypot(b.x() - a.x(), b.y() - a.y())


class Qt(object):
    """The few Qt names the tools ask for, in the spelling Qt 5 and Qt 6
    share: Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier."""
    class MouseButton(object):
        LeftButton, RightButton = 1, 2

    class KeyboardModifier(object):
        ControlModifier = 4


class Crs(str):
    """A coordinate system known by its name. Two are the same when their
    names are; "degrees" and "metres" are told apart by Transform below."""
    def isValid(self): return True


# How many metres a degree is, near enough, for the fake transform below: a
# straight scaling, which is all a test of units needs.
METRES_PER_DEGREE = 111320.0


class Transform(object):
    """QgsCoordinateTransform between the two fake systems."""
    def __init__(self, source, target, project=None):
        self.factor = 1.0
        if source == "degrees" and target == "metres":
            self.factor = METRES_PER_DEGREE
        elif source == "metres" and target == "degrees":
            self.factor = 1.0 / METRES_PER_DEGREE

    def transform(self, p):
        return Point(p.x() * self.factor, p.y() * self.factor)


class Project(object):
    @staticmethod
    def instance(): return None


class Settings(object):
    def destinationCrs(self): return CANVAS.crs


class ToPixels(object):
    """QgsMapToPixel: canvas units to screen pixels, y downwards."""
    def transform(self, p):
        return Point(p.x() * CANVAS.scale, -p.y() * CANVAS.scale)


class Canvas(object):
    """A canvas at a fixed scale: so many screen pixels per unit of its own
    coordinate system, which is the campaign's unless a test says otherwise."""
    def __init__(self):
        self.scale = 40.0
        self.crs = Crs("crs")
    def mapUnitsPerPixel(self): return 1.0 / self.scale
    def mapSettings(self): return Settings()
    def getCoordinateTransform(self): return ToPixels()


CANVAS = Canvas()


class Band(object):
    def reset(self, *a): pass


class Hit(object):
    def __init__(self, rect): self.rect = rect
    def id(self): return 1
    def geometry(self): return Geom.fromRect(self.rect)


class BoxSection(object):
    """What BoxTool asks of the objects section: one picked box, and a note
    of the rectangle it is told to reshape the box into."""
    def __init__(self, rect, crs="crs"):
        self.rect = rect
        self.geometry = type("G", (), {"crs": Crs(crs)})()
        self.reshaped = None
    def selected_rect(self): return self.rect
    def box_at(self, p):
        return Hit(self.rect) if self.rect.contains(p) else None
    def select_box(self, fid): pass
    def assign_class_at(self, p): pass
    def reshape_box(self, rect): self.reshaped = rect
    def create_box(self, rect): self.reshaped = None


class ScreenPos(object):
    """Where on the screen a press or a release happened, as QPoint gives it."""
    def __init__(self, x, y): self.x, self.y = x, y
    def __sub__(self, other): return ScreenPos(self.x - other.x, self.y - other.y)
    def manhattanLength(self): return abs(self.x) + abs(self.y)


class Event(object):
    def __init__(self, point, button=Qt.MouseButton.LeftButton):
        self.point, self._button = point, button
    def button(self): return self._button
    def modifiers(self): return 0
    def pos(self):
        # the canvas scale turns metres into screen pixels, y downwards
        return ScreenPos(self.point.x() * CANVAS.scale,
                         -self.point.y() * CANVAS.scale)


ns = {"HANDLE_PX": HANDLE_PX, "MOVE_PX": MOVE_PX, "QgsPointXY": Point, "QgsRectangle": Rect,
      "QgsGeometry": Geom, "Qt": Qt, "GEOM_POLYGON": 3,
      "QgsCoordinateTransform": Transform, "QgsProject": Project,
      "math": math, "canvas": lambda: CANVAS}


class Watch(object):
    """The stopwatch of a stroke, which this suite does not measure."""
    running = False
    def begin(self): pass
    def touch(self): pass
    def drop(self): pass
    def take(self): return None


# the time of a stroke is handed over around the call; here the call alone
ns["stroke_watch"] = lambda tool: Watch()
ns["stroke_handed"] = lambda section, watch, tool, call, *args: call(*args)


class Tool(object):
    """BoxTool with the canvas, the rubber bands and the CRS round trip faked;
    the three methods under test are the shipped ones."""
    def __init__(self, rect, crs="crs"):
        self.section = BoxSection(rect, crs)
        self.mode = self.origin = self.anchor = self.start_rect = None
        self.pressed_at = None
        self.band = Band()
    def _layer_point(self, ev): return ev.point
    def show_selection(self): pass


for name in ("_corner_grabbed", "canvasPressEvent", "canvasReleaseEvent"):
    exec(function(name, inside="BoxTool"), ns)
    setattr(Tool, name, ns[name])
# The helper that puts a point on the screen. It is taken when it is there;
# a build without it measured in map units, and the checks of mixed units
# below are the ones that say whether that was right.
try:
    exec(function("_on_screen", inside="BoxTool"), ns)
    Tool._on_screen = ns["_on_screen"]
except AssertionError:
    pass


def drag_corner(rect, handle, to):
    """Press exactly on a corner, release somewhere else, and return what the
    tool hands the section. handle is (0 or 1, 0 or 1): left/right, bottom/top."""
    ix, iy = handle
    at = Point(rect.xMaximum() if ix else rect.xMinimum(),
               rect.yMaximum() if iy else rect.yMinimum())
    t = Tool(rect)
    t.canvasPressEvent(Event(at))
    mode = t.mode
    t.canvasReleaseEvent(Event(to))
    return mode, t.section.reshaped


fails = []


def check(name, condition, detail=""):
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))
    if not condition:
        fails.append(name)


print("pulling a corner")
# a box of 10 m, on a 5 cm grid starting at a round coordinate
R = Rect(400000.0, 4099990.0, 400010.0, 4100000.0)
CORNERS = {(0, 0): "bottom left", (1, 0): "bottom right",
           (0, 1): "top left", (1, 1): "top right"}
for handle, label in CORNERS.items():
    # drag that corner 3 m outwards, away from the middle
    ix, iy = handle
    x = R.xMinimum() - 3 if ix == 0 else R.xMaximum() + 3
    y = R.yMinimum() - 3 if iy == 0 else R.yMaximum() + 3
    mode, out = drag_corner(R, handle, Point(x, y))
    check("%s: a press on the corner starts a resize" % label,
          mode == "resize" and out is not None, mode)
    if out is None:
        continue
    # the opposite corner must be exactly where it was
    ox = R.xMaximum() if ix == 0 else R.xMinimum()
    oy = R.yMaximum() if iy == 0 else R.yMinimum()
    kept = (abs((out.xMaximum() if ix == 0 else out.xMinimum()) - ox) < 1e-12 and
            abs((out.yMaximum() if iy == 0 else out.yMinimum()) - oy) < 1e-12)
    check("%s: the opposite corner does not move" % label, kept, out)
    check("%s: it is now 13 by 13" % label,
          abs(out.width() - 13) < 1e-9 and abs(out.height() - 13) < 1e-9,
          (out.width(), out.height()))

# and inwards, which is a shrink
_, out = drag_corner(R, (0, 0), Point(400004.0, 4099994.0))
check("dragging a corner inwards shrinks it",
      out is not None and abs(out.width() - 6) < 1e-9
      and abs(out.height() - 6) < 1e-9, out)
check("and still holds the far corner",
      out is not None and abs(out.xMaximum() - 400010.0) < 1e-12 and
      abs(out.yMaximum() - 4100000.0) < 1e-12, out)

# dragged past the far corner it must not turn inside out
_, out = drag_corner(R, (0, 0), Point(400015.0, 4100005.0))
check("dragged past the far corner it stays a rectangle",
      out is not None and out.width() > 0 and out.height() > 0, out)
check("pivoting on the corner that was held",
      out is not None and abs(out.xMinimum() - 400010.0) < 1e-12 and
      abs(out.yMinimum() - 4100000.0) < 1e-12, out)

# a click on a corner that wobbles a few pixels is a click, not a stretch
wobble = (MOVE_PX - 1) / CANVAS.scale / 2.0
mode, out = drag_corner(R, (0, 0), Point(R.xMinimum() + wobble,
                                         R.yMinimum() + wobble))
check("a click on a corner that wobbles under MOVE_PX picks it up",
      mode == "resize", mode)
check("and leaves the box exactly as it was", out is None, out)
# nor does a click in the middle that wobbles move the box
t = Tool(R)
t.canvasPressEvent(Event(Point(400005.0, 4099995.0)))
mode = t.mode
t.canvasReleaseEvent(Event(Point(400005.0 + wobble, 4099995.0 + wobble)))
check("a click in the middle that wobbles does not move the box",
      mode == "move" and t.section.reshaped is None, (mode, t.section.reshaped))
# and a stretch only just over the threshold still counts
over = (MOVE_PX + 2) / CANVAS.scale / 2.0
_, out = drag_corner(R, (0, 0), Point(R.xMinimum() - over,
                                      R.yMinimum() - over))
check("a stretch just over MOVE_PX still reshapes the box",
      out is not None and out.width() > R.width(), out)

print()
print("landing on whole pixels")
X0, Y0, PX, PY = 400000.0, 4100000.0, 0.05, 0.05


class Grid(object):
    """The part of Geometry that regrid() and snapped_square() read."""
    pixel_crs = (PX, PY)
    pixel_m = (PX, PY)
    origin = (X0, Y0)


gns = {"QgsGeometry": Geom, "QgsRectangle": Rect}
exec(function("regrid", inside="Geometry"), gns)
exec(function("snapped_square", inside="Geometry"), gns)


def regrid(rect):
    g, wide = gns["regrid"](Grid(), rect)
    return g.boundingBox(), wide


def in_pixels(r):
    return (int(round((r.xMinimum() - X0) / PX)),
            int(round((Y0 - r.yMaximum()) / PY)),
            int(round((r.xMaximum() - X0) / PX)),
            int(round((Y0 - r.yMinimum()) / PY)))


def on_grid(r):
    """Every edge is origin plus a whole number of pixels, to the last bit."""
    c0, r0, c1, r1 = in_pixels(r)
    return (r.xMinimum() == X0 + c0 * PX and r.xMaximum() == X0 + c1 * PX and
            r.yMaximum() == Y0 - r0 * PY and r.yMinimum() == Y0 - r1 * PY)


base = Rect(400010.0, 4099990.0, 400020.0, 4100000.0)
snapped, wide = regrid(base)
check("a frame already on the grid comes back identical",
      all(abs(a - b) < 1e-9 for a, b in zip(snapped.v, base.v)), snapped)
c0, r0, c1, r1 = in_pixels(snapped)
check("and it is 200 by 200 pixels",
      (c1 - c0, r1 - r0) == (200, 200) and wide == 200, (c1 - c0, r1 - r0))

# pull each corner by 2.73 m, a number that is not a whole pixel
for handle, label in CORNERS.items():
    ix, iy = handle
    x = base.xMaximum() + 2.73 if ix else base.xMinimum() - 2.73
    y = base.yMaximum() + 2.73 if iy else base.yMinimum() - 2.73
    _, pulled = drag_corner(base, handle, Point(x, y))
    out, wide = regrid(pulled)
    b = in_pixels(out)
    # the untouched corner, in pixels and in coordinates
    kc = (b[0] if ix else b[2], b[3] if iy else b[1])
    want = (c0 if ix else c1, r1 if iy else r0)
    check("%s pulled: the untouched corner keeps its exact pixel" % label,
          kc == want, (kc, want))
    kx = out.xMinimum() if ix else out.xMaximum()
    ky = out.yMinimum() if iy else out.yMaximum()
    wx = base.xMinimum() if ix else base.xMaximum()
    wy = base.yMinimum() if iy else base.yMaximum()
    check("%s pulled: the untouched edges keep their exact coordinate" % label,
          abs(kx - wx) < 1e-12 and abs(ky - wy) < 1e-12, out)
    check("%s pulled: it grew by a whole number of pixels, 255" % label,
          (b[2] - b[0], b[3] - b[1]) == (255, 255) and on_grid(out),
          (b[2] - b[0], b[3] - b[1]))
    check("%s pulled: which is 12.75 m a side" % label,
          abs(out.width() - 12.75) < 1e-9 and abs(out.height() - 12.75) < 1e-9,
          (out.width(), out.height()))

g, side_px = gns["snapped_square"](Grid(), Point(400013.37, 4099991.11), 12.73)
placed = g.boundingBox()
check("a frame placed with a side of 12.73 m is 255 whole pixels",
      side_px == 255 and abs(placed.width() - 12.75) < 1e-9, (side_px, placed))
check("and every edge of it falls on a pixel edge", on_grid(placed), placed)

print()
print("what a shrink does to the polygons")


class Feature(dict):
    def __init__(self, geom, **kw):
        dict.__init__(self, kw)
        self.g = geom
    def geometry(self): return self.g
    def hasGeometry(self): return self.g is not None
    def id(self): return 7


class Label(object):
    text = ""
    def setText(self, t): self.text = t


class Campaign(object):
    def active_classes(self):
        return [{"name": "rock", "colour": "#888888"}]


class Measures(object):
    measure = FakeMeasure()
    def area(self, g): return g.area()


class Panel(object):
    """AnnotationSection as refresh_coverage() sees it, with one frame."""
    tiled = True
    def __init__(self, frame, polygons):
        self.frame, self.polygons_ = frame, polygons
        self.geometry = Measures()
        self.campaign = Campaign()
        self.coverage = Label()
        self.pc = None
    def tile_geometry(self): return self.frame
    def scope_polygons(self): return self.polygons_
    # one reading: every polygon here is the operator's in the panel
    def reading_polygons(self): return self.polygons_
    def point_count(self): return 0
    def suggest(self, pc, n): self.pc = pc


cns = {"QgsGeometry": Geom}
exec(function("refresh_coverage", inside="AnnotationSection"), cns)


def coverage(frame, *polys):
    p = Panel(Geom(frame), [Feature(Geom(x), class_name="rock") for x in polys])
    cns["refresh_coverage"](p)
    return p.pc, p.coverage.text


frame_new = square(400010.0, 4099995.0, 400015.0, 4100000.0)   # the 5 m frame
inside = square(400011.0, 4099996.0, 400012.0, 4099997.0)      # wholly inside
across = square(400014.0, 4099994.0, 400016.0, 4099996.0)      # over the edge
outside = square(400017.0, 4099991.0, 400018.0, 4099992.0)     # wholly outside

pc, _ = coverage(frame_new, inside)
check("one inside is left alone: 1 m2 of 25 is 4 %", abs(pc - 4.0) < 1e-9, pc)
pc, _ = coverage(frame_new, across)
check("one across the edge is cut, not dropped: 1 of its 4 m2 counts",
      abs(pc - 4.0) < 1e-9, pc)
pc, _ = coverage(frame_new, outside)
check("one wholly outside counts for nothing", pc == 0, pc)
pc, _ = coverage(frame_new, inside, across, outside)
check("the three together are the 2 m2 inside the frame", abs(pc - 8.0) < 1e-9,
      pc)
# a polygon painted over the whole frame before it shrank
pc, text = coverage(frame_new, square(400010.0, 4099993.0, 400017.0, 4100000.0))
check("and what is left is inside the new frame: never over 100 %",
      abs(pc - 100.0) < 1e-9, pc)
check("with nothing left unpainted", "0.00 m2" in text, text)

# The same rule in what is written into the file. closed is 1 only over
# 99.5 %, so a polygon counted whole instead of clipped would close a frame
# that still has a hole in it.


class Field(object):
    def __init__(self, n): self.n = n
    def name(self): return self.n


class Fields(list):
    def indexOf(self, n):
        return [f.name() for f in self].index(n) if n in self.names() else -1
    def names(self): return [f.name() for f in self]


class Layer(object):
    def __init__(self, features=()):
        self.features = list(features)
        self.written = {}
    def fields(self): return Fields([Field("tile_id"), Field("side_m"),
                                     Field("closed")])
    def getFeatures(self): return iter(self.features)
    def isEditable(self): return True
    def startEditing(self): pass
    def changeAttributeValue(self, fid, index, value):
        self.written[self.fields()[index].name()] = value


class Blank(object):
    OPERATOR_BLANK = "UNNAMED"


mns = {"QgsPointXY": Point, "QgsGeometry": Geom, "AnnotationSection": Blank,
       "CLOSED_SHARE": constant("CLOSED_SHARE")}
for _name in ("measure_tile", "operator_of", "pass_of"):
    exec(function(_name, inside="AnnotationSection"), mns)


class Section(object):
    """AnnotationSection as measure_tile() sees it: the frame is closed
    reading by reading, a pass and an operator, read as the class reads
    them."""
    operator_of = mns["operator_of"]
    pass_of = mns["pass_of"]

    def __init__(self, polygons):
        self.tile_layer = Layer()
        self.polygons = Layer(polygons)
        self.geometry = Measures()


def measured(frame, *polys):
    s = Section([Feature(Geom(x), tile_id="T1", pass_no=1) for x in polys])
    mns["measure_tile"](s, Feature(Geom(frame), tile_id="T1"))
    return s.tile_layer.written


# 24.5 of 25 m2 inside, and a strip across the edge whose whole area would
# take the sum past the threshold
almost = square(400010.0, 4099995.0, 400014.9, 4100000.0)
over = square(400014.95, 4099990.0, 400020.0, 4100000.0)
w = measured(frame_new, almost, over)
check("a frame with a hole is not written as closed, whatever hangs over it",
      w.get("closed") == 0, w)
left = square(400010.0, 4099995.0, 400012.5, 4100000.0)
right = square(400012.5, 4099994.0, 400016.0, 4100000.0)
w = measured(frame_new, left, right)
check("a polygon across the edge still closes the frame with its inner part",
      w.get("closed") == 1, w)
w = measured(frame_new, almost, outside)
check("a polygon wholly outside closes nothing", w.get("closed") == 0, w)

print()
print("the coverage that gets written into the file")
# a frame enlarged from 5 m to 7 m with the vertex tool, annotated only over
# the original 5
old_frame = square(400010.0, 4099995.0, 400015.0, 4100000.0)
big_frame = square(400010.0, 4099993.0, 400017.0, 4100000.0)
painted = old_frame.Clone()
pc, _ = coverage(old_frame, painted)
check("before enlarging it reads 100 %", abs(pc - 100.0) < 1e-9, pc)
w = measured(old_frame, painted)
check("and the file says closed, 5 m a side",
      w.get("closed") == 1 and w.get("side_m") == 5.0, w)
pc, text = coverage(big_frame, painted)
check("after enlarging it reads 51.02 %", abs(pc - 100 * 25 / 49) < 1e-9, pc)
check("so the ring, 24 m2 of the frame, is shown as not annotated",
      "24.00 m2" in text, text)
w = measured(big_frame, painted)
check("and the file says open, with the side it has now and not the old one",
      w.get("closed") == 0 and w.get("side_m") == 7.0, w)

print()
print("the handle shrinks with the box")


def grabs(scale, rect, dx, dy, which="any"):
    """Whether a click dx, dy screen pixels from the bottom left corner,
    towards the inside, takes a corner: any corner, or with which="bottom
    left" that corner in particular, known by its anchor being the top right."""
    CANVAS.scale = scale
    t = Tool(rect)
    at = Point(rect.xMinimum() + dx / scale, rect.yMinimum() + dy / scale)
    got = t._corner_grabbed(at)
    if which == "any":
        return got is not None
    return got is not None and (got.x(), got.y()) == (rect.xMaximum(),
                                                      rect.yMaximum())


def handle(scale, rect):
    """The reach of the bottom left corner on screen, found by clicking
    further and further along the diagonal, in tenths of a pixel. Only that
    corner counts: on a small box the next corner's square would otherwise
    carry on the count and the reach would come out as the whole diagonal."""
    reach = 0.0
    for tenth in range(1, 400):
        if grabs(scale, rect, tenth / 10.0, tenth / 10.0, "bottom left"):
            reach = tenth / 10.0
        else:
            break
    return reach


small = Rect(400000.0, 4099997.5, 400002.5, 4100000.0)     # 2.5 m
big = Rect(400000.0, 4099990.0, 400010.0, 4100000.0)       # 10 m

# 40 px per metre: the small box is 100 px wide
m = handle(40.0, small)
check("zoomed in, the small box gets the full handle",
      abs(m - HANDLE_PX) <= 0.1, (m, HANDLE_PX))
# 8 px per metre: the small box is only 20 px wide
m = handle(8.0, small)
check("zoomed out, the handle shrinks to a third of the side",
      abs(m - 20.0 / 3.0) <= 0.1, m)
check("and it is always smaller than half the box, so a middle is left",
      m * 2 < 20.0 and not grabs(8.0, small, 10.0, 10.0), m)
CANVAS.scale = 8.0
t = Tool(small)
t.canvasPressEvent(Event(Point(400001.25, 4099998.75)))
check("so a press in the middle of it picks it up instead of resizing it",
      t.mode == "move", t.mode)
check("the big box is unaffected at the same zoom",
      abs(handle(8.0, big) - HANDLE_PX) <= 0.1, handle(8.0, big))
check("at an absurd zoom the handle never goes below three pixels",
      grabs(8.0, Rect(400000.0, 4099999.9, 400000.1, 4100000.0), 2.9, 2.9))

print()
print("which corner is taken")
CANVAS.scale = 40.0
t = Tool(big)
# two pixels from the bottom left corner, inside: the anchor is the top right
got = t._corner_grabbed(Point(big.xMinimum() + 2 / 40.0,
                              big.yMinimum() + 2 / 40.0))
check("a click two pixels from a corner takes that corner",
      got is not None and (got.x(), got.y()) == (big.xMaximum(), big.yMaximum()),
      got and (got.x(), got.y()))
got = t._corner_grabbed(Point(400005.0, 4099995.0))
check("a click in the middle takes no corner at all", got is None, got)
got = t._corner_grabbed(Point(big.xMinimum() - 4 / 40.0,
                              big.yMinimum() - 4 / 40.0))
check("a corner is reachable from outside the box too",
      got is not None and (got.x(), got.y()) == (big.xMaximum(), big.yMaximum()),
      got)
for (ix, iy), label in CORNERS.items():
    cx = big.xMaximum() if ix else big.xMinimum()
    cy = big.yMaximum() if iy else big.yMinimum()
    got = t._corner_grabbed(Point(cx, cy))
    want = (big.xMinimum() if ix else big.xMaximum(),
            big.yMinimum() if iy else big.yMaximum())
    check("on the %s corner the anchor is the opposite one" % label,
          got is not None and (got.x(), got.y()) == want, got)

print()
print("the reach is in pixels whatever the units of the two systems")
# A campaign in degrees on a canvas in metres, at 0.05 m a pixel: a box of two
# metres is forty pixels wide on screen, so a click in its middle is twenty
# pixels from every corner and must pick it up, not stretch it.
CANVAS.crs, CANVAS.scale = Crs("metres"), 20.0
side = 2.0 / METRES_PER_DEGREE
in_degrees = Rect(13.0, 37.0, 13.0 + side, 37.0 + side)
t = Tool(in_degrees, "degrees")
middle = Point(13.0 + side / 2, 37.0 + side / 2)
got = t._corner_grabbed(middle)
check("campaign in degrees, canvas in metres: the middle takes no corner",
      got is None, got and (got.x(), got.y()))
t.canvasPressEvent(Event(middle))
check("so a press there picks the box up", t.mode == "move", t.mode)
near = Point(13.0 + 2 * 0.05 / METRES_PER_DEGREE,
             37.0 + 2 * 0.05 / METRES_PER_DEGREE)
got = Tool(in_degrees, "degrees")._corner_grabbed(near)
# the anchor is worked out as min + max - corner, which in degrees this small
# is exact only to the last bit or two, so it is compared to within 1e-12
check("and a click two pixels from a corner still takes it",
      got is not None and abs(got.x() - in_degrees.xMaximum()) < 1e-12
      and abs(got.y() - in_degrees.yMaximum()) < 1e-12,
      got and (got.x(), got.y()))
far = Point(13.0 + 12 * 0.05 / METRES_PER_DEGREE,
            37.0 + 12 * 0.05 / METRES_PER_DEGREE)
check("but not one twelve pixels away, past the handle",
      Tool(in_degrees, "degrees")._corner_grabbed(far) is None)

# The other way round: a campaign in metres on a canvas in degrees, at the
# same 0.05 m a pixel. Measured in map units the reach was ten pixels' worth
# of degrees read as metres, under a micrometre, and no corner could be taken.
CANVAS.crs, CANVAS.scale = Crs("degrees"), 20.0 * METRES_PER_DEGREE
in_metres = Rect(400000.0, 4099998.0, 400002.0, 4100000.0)
got = Tool(in_metres, "metres")._corner_grabbed(Point(400000.1, 4099998.1))
check("campaign in metres, canvas in degrees: a corner two pixels away is taken",
      got is not None and (got.x(), got.y()) == (in_metres.xMaximum(),
                                                 in_metres.yMaximum()),
      got and (got.x(), got.y()))
got = Tool(in_metres, "metres")._corner_grabbed(Point(400001.0, 4099999.0))
check("and the middle still takes none", got is None,
      got and (got.x(), got.y()))
m = 0.0
for tenth in range(1, 400):
    d = tenth / 10.0 * 0.05
    g2 = Tool(in_metres, "metres")._corner_grabbed(
        Point(400000.0 + d, 4099998.0 + d))
    if g2 is not None and (g2.x(), g2.y()) == (in_metres.xMaximum(),
                                               in_metres.yMaximum()):
        m = tenth / 10.0
    else:
        break
check("and the reach is the full handle, in pixels, as on a single system",
      abs(m - HANDLE_PX) <= 0.1, (m, HANDLE_PX))
CANVAS.crs, CANVAS.scale = Crs("crs"), 40.0

print()
print("the sides that get shown")
ons = {"QgsPointXY": Point}
exec(function("too_small", inside="ObjectsSection"), ons)


class Spin(object):
    def __init__(self, v): self.v = v
    def value(self): return self.v


class Objects(object):
    def __init__(self, measure):
        self.smallest = Spin(0.1)
        self.geometry = type("G", (), {"measure": measure,
                                       "pixel_crs": (PX, PY),
                                       "pixel_m": (PX, PY)})()


_, lx, ly = ons["too_small"](Objects(FakeMeasure()), Rect(0, 0, 12.75, 9.0))
check("the first number is the width and the second the height",
      abs(lx - 12.75) < 1e-9 and abs(ly - 9.0) < 1e-9, (lx, ly))


class Broken(object):
    def measureLine(self, a, b): return 0.0


_, lx, ly = ons["too_small"](Objects(Broken()), Rect(0, 0, 12.75, 9.0))
check("and they stay in that order when the ellipsoid gives up",
      abs(lx - 12.75) < 1e-9 and abs(ly - 9.0) < 1e-9, (lx, ly))
w = measured(square(0, 0, 12.75, 9.0))
check("the side written for a frame is its width",
      w.get("side_m") == 12.75, w)

print()
print("FAILED: %d" % len(fails) if fails else "all of them pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
