"""Dragging a vertex drags a border: one side grows, the other gives way.

A vertex belongs to one polygon. Push it into the neighbour and the two
overlap; pull it back and they leave a gap. The overlap was already settled,
the edited polygon winning and the neighbour being trimmed. The gap was left
as unpainted ground, which is defensible written down and wrong under the
hand: half the drags grew a class and the other half punched a hole in the
frame, and which one you got depended on a direction nobody can see while
dragging. So the freed ground now goes to the polygon that shares the longest
stretch of border with it.

Two things are checked here and they are not the same kind of check.

The first is the rule itself, run on real geometry with shapely: the same
sequence of operations the program performs, on polygons whose every corner is
known, to show that the partition is closed afterwards whichever way the
border was dragged, and that the three exclusions hold. It is a model of the
rule, not the program's own code: give_back() is written in QGIS geometry and
there is no QGIS here. Where a model can pass while the program drifts away
from it, the second kind of check is what stands in the way.

The second is on the source of the shipped file: that give_back is called,
where it is called, and that each exclusion is written in it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import os as _os

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os
import sys

SRC = os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def source_of(name, inside):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if getattr(sub, "name", None) == name:
                    t = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s not found" % name)


try:
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
except ImportError:
    print("shapely is not installed, so the arithmetic half cannot run:")
    print("    pip install shapely")
    sys.exit(2)

A = "AnnotationSection"
TILE = box(0, 0, 10, 10)


def give_back(before, now, neighbours, tile=TILE):
    """The rule, in the order the program applies it.

    Returns the neighbours after the gift, and how many pieces were given.
    """
    freed = before.difference(now)
    if freed.is_empty:
        return neighbours, 0
    freed = freed.intersection(tile)                    # never outside the frame
    taken = unary_union([g for g in neighbours]) if neighbours else None
    if taken is not None and not taken.is_empty:
        freed = freed.difference(taken)                 # never what is painted
    if freed.is_empty:
        return neighbours, 0
    parts = [freed] if freed.geom_type == "Polygon" else list(freed.geoms)
    out, given = list(neighbours), 0
    for part in parts:
        if part.area <= 0:
            continue
        best, longest = None, 0.0
        for i, og in enumerate(out):
            along = og.boundary.intersection(part.boundary)
            if along.is_empty:
                continue
            if along.length > longest:
                best, longest = i, along.length
        if best is None:
            continue                                    # an honest hole
        out[best] = unary_union([out[best], part])
        given += 1
    return out, given


#  the ground: a frame of 10 by 10 split in two along x = 5
#
#     +--------+--------+        left, the class drawn with the brush
#     |  left  | right  |        right, the class Fill Gap laid down
#     +--------+--------+
left = box(0, 0, 5, 10)
right = box(5, 0, 10, 10)

print("the frame starts closed: no gap, no overlap")
check("the two cover the whole frame",
      abs(unary_union([left, right]).area - TILE.area) < 1e-9)
check("and share no ground", left.intersection(right).area == 0)

print()
print("a vertex pulled back: the border moves to x = 4")
pulled = Polygon([(0, 0), (4, 0), (4, 10), (0, 10)])
after, given = give_back(left, pulled, [right])
check("one piece is given away", given == 1, given)
check("the neighbour grew by exactly the strip",
      abs(after[0].area - (right.area + 10.0)) < 1e-9, after[0].area)
check("the frame is still covered edge to edge",
      abs(unary_union([pulled] + after).area - TILE.area) < 1e-9)
check("and still with no overlap",
      pulled.intersection(after[0]).area < 1e-12)

print()
print("the same drag the other way is not this function's business")
# pushed in, the edited polygon wins and the neighbour is trimmed: that is
# settle_edits, and give_back finds nothing to give because nothing was freed
pushed = Polygon([(0, 0), (6, 0), (6, 10), (0, 10)])
_, given = give_back(left, pushed, [right])
check("nothing is given away when the polygon only grew", given == 0, given)

print()
print("ground somebody has painted in the meantime is never given")
# the neighbour has already been redrawn over the strip by a stroke
already = box(4, 0, 10, 10)
after, given = give_back(left, pulled, [already])
check("there is nothing left to give", given == 0, given)
check("and the painted polygon is untouched",
      abs(after[0].area - already.area) < 1e-9)

print()
print("a hole in the middle of one polygon stays a hole")
#  a square doughnut: the polygon loses a square from its own middle, and that
#  square touches nobody else
middle = box(1, 4, 3, 6)
holed = left.difference(middle)
after, given = give_back(left, holed, [right])
check("nobody borders it, so nobody gets it", given == 0, given)
check("the neighbour is exactly as it was",
      abs(after[0].area - right.area) < 1e-9)

print()
print("between two neighbours, the longer border wins")
#     +----------------+
#     |      top       |        the strip freed by the drag runs along the
#     +-------+--------+        whole of the top's border and only touches
#     | small |  edit  |        a corner of small
top = box(0, 6, 10, 10)
small = box(0, 0, 2, 6)
edited = box(2, 0, 10, 6)
shrunk = box(2, 0, 10, 5)
after, given = give_back(edited, shrunk, [top, small])
check("one piece given", given == 1, given)
# the strip runs along 8 units of the top's border and 1 unit of small's
check("it went to the one sharing the longer border",
      abs(after[0].area - (top.area + 8.0)) < 1e-9, after[0].area)
check("and the one sharing a single unit of it got nothing",
      abs(after[1].area - small.area) < 1e-9, after[1].area)
check("the frame is covered again",
      abs(unary_union([shrunk] + after).area - TILE.area) < 1e-9)

print()
print("and the same, done twice in a row, does not drift")
once = box(0, 0, 4, 10)
after, _ = give_back(left, once, [right])
twice = box(0, 0, 3, 10)
after2, _ = give_back(once, twice, after)      # measured against the new shape
check("the second drag gives away only the second strip",
      abs(after2[0].area - (right.area + 20.0)) < 1e-9, after2[0].area)
check("the frame is still exactly covered",
      abs(unary_union([twice] + after2).area - TILE.area) < 1e-9)

print()
print("a vertex pushed INTO a neighbour it shared a border with")
# The case the trim exists for, and the one it skipped. In a closed partition
# the edited polygon shares its whole border with the neighbour before the
# drag, so the ground they share afterwards is not a polygon: it is a
# collection, the wedge plus the stretches of border still in common.
frame = box(0, 0, 10, 10)
orange = Polygon([(4, 4), (6, 4), (6, 6), (4, 6)])
yellow = frame.difference(orange)               # what Fill Gap lays down
pushed = Polygon([(4, 4), (6, 4), (8, 8), (4, 6)])
shared = yellow.intersection(pushed)
check("the shared ground is a collection, not a polygon",
      shared.geom_type == "GeometryCollection", shared.geom_type)
check("and it has area, so there is an overlap to settle",
      shared.area > 0, shared.area)
# the rule, as settle_edits now applies it: on area, whatever the type
trimmed = yellow.difference(pushed) if shared.area > 0 else yellow
check("trimmed, the two share no ground", trimmed.intersection(pushed).area
      < 1e-12)
check("and together they still cover the frame edge to edge",
      abs(unary_union([trimmed, pushed]).area - frame.area) < 1e-9)
# what the old test did with the same shapes
old_skips = shared.geom_type not in ("Polygon", "MultiPolygon")
check("the old test on the type would have skipped it", old_skips)

# --------------------------------------------------- and now the source itself
print()
print("the program really does this, and in this order")
settle = source_of("settle_edits", A)
back = source_of("give_back", A)
check("settle_edits calls it, with the polygon's own frame",
      "self.give_back(fid, g, scope, frame)" in settle)
check("the overlap with a neighbour is judged by its area",
      "or shared.area() <= 0):" in settle)
check("and no longer by its type, which skipped every shared border",
      "shared.type() != GEOM_POLYGON" not in settle)
check("after the trimming, not before",
      settle.find("trimmed += 1") < settle.find("self.give_back"))
check("it reads the neighbours back from the layer",
      "lyr.getFeature(other.id())" in back)
check("the gap is what the polygon stopped claiming",
      "freed = self.cut_away(before, now)" in back)
check("clipped to the frame", "freed.intersection(tile)" in back)
check("minus whatever is painted now",
      "self.cut_away(freed, taken)" in back)
check("the heir is the longest shared border",
      "if shared > longest:" in back
      and "self.geometry.shared_border(og, part)" in back)
check("and the border is taken from the geometry underneath, since "
      "QgsGeometry has no boundary()",
      "constGet().boundary()" in source_of("shared_border", "Geometry")
      and ".boundary()" not in back)
check("a piece nobody borders is left alone",
      "if best is None:" in back and "continue" in back)
check("the gift is a union, so the class keeps one polygon",
      "QgsGeometry.unaryUnion([heir.geometry(), part])" in back)

print()
print("and the shapes it compares against are kept fresh")
check("before the vertex tool is given the map",
      "self.remember_shapes()" in source_of("vertex_mode_changed", A))
check("after every stroke", "self.remember_shapes()" in source_of("ticked", A))
check("after every settled edit", "self.remember_shapes()" in settle)
check("and when the frame changes",
      "self.remember_shapes()" in source_of("tile_changed", A))
remember = source_of("remember_shapes", A)
# Every polygon, since a vertex can be dragged in any frame on screen; it was
# one frame's worth, and a drag in another frame had nothing to compare with.
check("it remembers every polygon, not only the frame in the list",
      "lyr.getFeatures()" in remember and "self.scope_polygons()" not in remember)
check("and Save remembers them again under their new ids",
      "self.remember_shapes()" in source_of("save", A))
check("and it copies them, rather than keeping a handle on the live feature",
      "QgsGeometry(f.geometry())" in remember)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
