"""Strokes of one class merge on a real map, and a frame name cannot break a filter.

Two things that worked on every test campaign and failed on real ground.

The first is the merge. add_merging found the neighbours of a stroke through a
buffer of 1e-9 around it. Every suite drew near (0, 0), where that is a hair.
A real campaign is in UTM, with coordinates around 500 000 east and 4 100 000
north, where two neighbouring doubles are already a few 1e-10 apart, and GEOS
hands back an EMPTY polygon for a buffer that small. Nothing intersects an
empty polygon: two strokes of the same class that overlapped were written as
two polygons on top of each other, and Check reported the overlap the brush had
just made. Here the real paint() and add_merging() run through editkit, on
GEOS, at the coordinates a survey actually has.

The second is the frame filter. apply_filter() wrote the frame name between
two apostrophes, without doubling the ones inside it, while the operator name
next to it went through sql_text(). The names are generated as t001, t002, but
they are read back from a GeoPackage that can be edited by hand, and one name
with an apostrophe left the whole expression broken. A broken filter in QGIS
hides nothing, so a blind second pass showed the first. The expressions the
real apply_filter() hands to the renderer are run here against sqlite, which
reads the same quoting as QGIS.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import sqlite3
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

SA = K.SA
fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def stroke_on(ox, oy, px, first, second, frame=None):
    """One polygon of class a already on disk, a second stroke of class a
    painted with the real paint(). Returns the polygons of class a after it,
    as shapely shapes."""
    polys = K.Layer("polygons")
    tiles = K.Layer("tiles")
    frame = frame or box(ox - 100 * px, oy - 100 * px,
                         ox + 100 * px, oy + 100 * px)
    K.put(tiles, frame, tile_id="t001")
    K.put(polys, first, class_name="a", class_code=1, tile_id="t001",
          pass_no=1, operator="OP1")
    host = K.Host(polys, tiles, px=px)
    host.geometry.origin = (frame.bounds[0], frame.bounds[3])
    polys.startEditing()
    host.remember_shapes()
    host.class_name = "a"
    host.paint(K.G(second))
    K.Loop.run()
    return [f._g.s for f in polys.getFeatures() if f["class_name"] == "a"]


# ------------------------------------------------------------------ the merge
print("two overlapping strokes of one class become one polygon, wherever they are")
# The case seen on the real campaign: a 3 x 3 polygon, then a 3 x 0.5 stroke
# that overlaps it by 0.5 x 0.5, in EPSG:32633 at 500000 / 4100000.
for ox, oy in [(0.0, 0.0), (1e3, 1e3), (1e5, 1e5), (500000.0, 4100000.0),
               (500123.25, 4100456.75), (1e6, 1e6), (4.1e6, 4.1e6),
               (-500000.0, -4100000.0)]:
    shapes = stroke_on(ox, oy, 0.5,
                       box(ox, oy, ox + 3, oy + 3),
                       box(ox + 2.5, oy, ox + 5.5, oy + 0.5))
    want = 9.0 + 1.5 - 0.25
    check("at %.2f / %.2f: one polygon of %.2f" % (ox, oy, want),
          len(shapes) == 1 and abs(shapes[0].area - want) < 1e-6,
          [round(s.area, 4) for s in shapes])

print()
print("a stroke that only shares a border merges too")
for ox, oy in [(0.0, 0.0), (500000.0, 4100000.0)]:
    shapes = stroke_on(ox, oy, 0.5,
                       box(ox, oy, ox + 3, oy + 3),
                       box(ox + 3, oy, ox + 5, oy + 1))
    check("at %.0f / %.0f: border to border, one polygon" % (ox, oy),
          len(shapes) == 1 and abs(shapes[0].area - 11.0) < 1e-6,
          [round(s.area, 4) for s in shapes])

print()
print("a border a hair apart is still a neighbour, a pixel apart is not")
# A border worked out twice can come back a few units in the last place
# apart. On a map that is a few 1e-10 m, and the old buffer was smaller
# than the gap it was there to bridge. The union does not close such a gap
# (GEOS keeps the two apart), so this is asked of the neighbour test itself.
ox, oy = 500000.0, 4100000.0
near = getattr(SA, "within_reach", None)
check("the neighbour test is one function", near is not None)
if near is not None:
    here = K.G(box(ox, oy, ox + 3, oy + 3))
    reach = SA.merge_reach(K.make_geometry(0.5), here)
    check("a gap of a few nanometres is bridged",
          near(K.G(box(ox + 3 + 3e-9, oy, ox + 5, oy + 1)), here, reach))
    check("a gap of a whole pixel is not",
          not near(K.G(box(ox + 3.5, oy, ox + 5.5, oy + 1)), here, reach))
shapes = stroke_on(ox, oy, 0.5, box(ox, oy, ox + 3, oy + 3),
                   box(ox + 3.5, oy, ox + 5.5, oy + 1))
check("painted a pixel apart, the two strokes stay two polygons",
      len(shapes) == 2, [round(s.area, 4) for s in shapes])

print()
print("in degrees, with a pixel of a few metres")
ox, oy, px = 13.5612, 37.3087, 1e-5
shapes = stroke_on(ox, oy, px, box(ox, oy, ox + 30 * px, oy + 30 * px),
                   box(ox + 25 * px, oy, ox + 55 * px, oy + 5 * px))
check("two overlapping strokes in degrees merge", len(shapes) == 1,
      [s.area for s in shapes])
shapes = stroke_on(ox, oy, px, box(ox, oy, ox + 30 * px, oy + 30 * px),
                   box(ox + 31 * px, oy, ox + 55 * px, oy + 5 * px))
check("and a pixel apart they stay two", len(shapes) == 2,
      [s.area for s in shapes])

print()
print("the reach is a share of a pixel, never a fixed number")
reach_of = getattr(SA, "merge_reach", None)
check("the reach is worked out in one place", reach_of is not None)
if reach_of is None:
    def reach_of(geometry, geom):
        return 1e-9                   # what it was, so the checks below say so
g = K.make_geometry(0.5)
r_utm = reach_of(g, K.G(box(500000, 4100000, 500003, 4100003)))
check("on a 0.5 m pixel in UTM it is a thousandth of the pixel",
      abs(r_utm - 5e-4) < 1e-12, r_utm)
check("and the buffer it asks for is not empty there",
      not K.G(box(500000, 4100000, 500003, 4100003)).buffer(r_utm, 1).isEmpty())
g0 = K.make_geometry(0.5)
g0.pixel_crs = (0.0, 0.0)
r0 = reach_of(g0, K.G(box(4.1e6, 4.1e6, 4.1e6 + 3, 4.1e6 + 3)))
check("with no pixel size it stays well above the rounding",
      r0 > 1e-8 and not K.G(box(4.1e6, 4.1e6, 4.1e6 + 3, 4.1e6 + 3))
      .buffer(r0, 1).isEmpty(), r0)


# --------------------------------------------------------- the frame filter
print()
print("a frame name with quotes in it does not break the view")


class Rule(object):
    def __init__(self, expr=""): self.expr = expr
    def filterExpression(self): return self.expr
    def setFilterExpression(self, e): self.expr = e


class Root(object):
    def __init__(self): self.kids = [Rule(""), Rule("\"class_code\" = 1")]
    def children(self): return self.kids


class Rules(object):
    def __init__(self): self.root = Root()
    def rootRule(self): return self.root


class Renderer(object):
    @staticmethod
    def convertFromRenderer(old): return Rules()


class Shown(object):
    """A layer as apply_filter and filter_layer read it: its fields, and the
    renderer it ends up with."""
    def __init__(self, names):
        self.fields_ = K.Fields(K.Field(n) for n in names)
        self.rules = None
    def fields(self): return self.fields_
    def renderer(self): return None
    def setRenderer(self, r): self.rules = r
    def triggerRepaint(self): pass
    def subsetString(self): return ""
    def isEditable(self): return True
    def id(self): return "x"

    def expressions(self):
        if self.rules is None:
            return []
        return [r.expr for r in self.rules.rootRule().children()]


SA.QgsRuleBasedRenderer = Renderer
SA.style_by_class = lambda *a, **k: None


class Viewer(object):
    OPERATOR_BLANK = SA.AnnotationSection.OPERATOR_BLANK
    tidy_operator = staticmethod(SA.AnnotationSection.tidy_operator)
    operator_name = SA.AnnotationSection.operator_name
    apply_filter = SA.AnnotationSection.apply_filter
    filter_layer = SA.AnnotationSection.filter_layer

    def __init__(self, tile_id, operator="OP1"):
        names = ["class_name", "class_code", "tile_id", "pass_no", "operator"]
        self.tables = {"polygons": Shown(names), "lines": Shown(names),
                       "points": Shown(names), "boxes": Shown(names)}
        self.tiled = True
        self._tile = tile_id
        self.by_operator = K.Tick(True)
        self.only_current = K.Tick(True)
        self.blind = K.Tick(True)
        self.pass_no = K.Spin(2)
        self.operator = K.Combo(operator)
        self.campaign = type("C", (), {})()
        self.campaign.active_classes = lambda: []

    @property
    def polygons(self): return self.tables["polygons"]
    def layer(self, role): return self.tables[role]
    def current_tile_id(self): return self._tile
    def hiding(self):
        return bool(self.blind.isChecked() and self.pass_no.value() > 1)
    def show_blind(self): pass


db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE p (fid INTEGER, class_code INT, tile_id TEXT, "
           "pass_no INT, operator TEXT)")
ROWS = [(1, 1, "t001", 2, "OP1"), (2, 1, "t001", 1, "OP1"),
        (3, 1, "D'Ag", 2, "OP1"), (4, 1, "D'Ag", 1, "OP1"),
        (5, 1, 'the "big" one', 2, "OP1"), (6, 1, 'the "big" one', 1, "OP1"),
        (7, 1, "t'0''1", 2, "OP1")]
db.executemany("INSERT INTO p VALUES (?,?,?,?,?)", ROWS)


def shown(expr):
    try:
        return {r[0] for r in db.execute("SELECT fid FROM p WHERE " + expr)}
    except sqlite3.Error as err:
        return "broken: %s" % err


for tile, want in [("t001", {1}), ("D'Ag", {3}), ('the "big" one', {5}),
                   ("t'0''1", {7})]:
    v = Viewer(tile)
    v.apply_filter()
    for role in ("polygons", "lines", "points", "boxes"):
        exprs = v.tables[role].expressions()
        check("%s, %s: the filter is applied" % (tile, role),
              len(exprs) == 2 and all("tile_id" in e for e in exprs), exprs)
        if exprs:
            got = shown(exprs[0])
            check("%s, %s: it shows this frame's pass 2 alone" % (tile, role),
                  got == want, (got, exprs[0]))

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
