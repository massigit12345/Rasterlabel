"""A frame marked closed is closed: a stroke over a polygon leaves no hole.

An "over" stroke cuts what it crosses out of the polygons under it. What it
leaves of a polygon was handed to Geometry.parts(), which throws away every
piece under four pixels, and a piece that small is still ground: a few pixel
centres fall in it. The polygon lost them, no other polygon had them, and the
frame was still reported as closed. Fill Gap looked for the hole with the same
parts() and answered "no holes". The mask burned from such a frame has pixels
of 0 inside it, which a mask meant for training reads as "not any class".

Here the real paint(), add_merging(), close_holes(), give_back() and untangle()
run through editkit on GEOS, and a mask is burned from what is left, by pixel
centres as GDAL does when it burns a polygon.
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
import numpy as np
from shapely.geometry import Point, box

SA = K.SA
fails = []

SIDE = 20           # the frame is SIDE x SIDE pixels of one unit


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def burned(layer):
    """The mask of the frame: for every pixel centre, the code of the polygon
    that holds it, 0 where none does."""
    shapes = [(f._g.s, f["class_code"]) for f in layer.getFeatures()
              if f._g.s is not None and not f._g.s.is_empty]
    out = np.zeros((SIDE, SIDE), np.int32)
    for row in range(SIDE):
        for col in range(SIDE):
            centre = Point(col + 0.5, SIDE - row - 0.5)
            for shape, code in shapes:
                if shape.covers(centre):
                    out[row, col] = code
                    break
    return out


def start():
    """A frame wholly of class b, and the section drawing in it."""
    polys = K.Layer("polygons")
    tiles = K.Layer("tiles")
    K.put(tiles, box(0, 0, SIDE, SIDE), tile_id="t001")
    K.put(polys, box(0, 0, SIDE, SIDE), class_name="b", class_code=2,
          tile_id="t001", pass_no=1, operator="OP1")
    host = K.Host(polys, tiles)
    host.geometry.origin = (0.0, float(SIDE))
    polys.startEditing()
    host.remember_shapes()
    return host, polys


def over(host, shape, name="a"):
    """A stroke in over mode with the real paint()."""
    host.class_name = name
    host.paint(K.G(shape))
    K.Loop.run()


# ------------------------------------------------- a sliver inside the stroke
print("an over stroke with a small island of the old class left inside it")
host, polys = start()
# a ring of class a around an island of b two pixels big: the island is what
# the stroke leaves of b apart from the rest of the frame
ring = box(5, 5, 12, 12).difference(box(8, 8, 10, 9))
over(host, ring)
mask = burned(polys)
check("no pixel of the frame is left at 0", int((mask == 0).sum()) == 0,
      np.argwhere(mask == 0).tolist())
check("the island is still class b", mask[SIDE - 9, 8] == 2
      and mask[SIDE - 9, 9] == 2, mask[SIDE - 9, 8:10].tolist())
check("and the ring is class a", mask[SIDE - 6, 6] == 1)
sizes = sorted(round(f._g.s.area, 3) for f in polys.getFeatures()
               if f["class_name"] == "b")
check("the island is a polygon of its own, below four pixels",
      sizes[0] < 4 * 1.0, sizes)

print()
print("a small polygon next to a stroke is not lost, painting or merging")
polys2 = K.Layer("polygons")
tiles2 = K.Layer("tiles")
K.put(tiles2, box(0, 0, SIDE, SIDE), tile_id="t001")
# b is a strip three pixels long and one high in the corner, a covers the rest
K.put(polys2, box(0, 0, SIDE, SIDE).difference(box(0, 0, 3, 1)),
      class_name="a", class_code=1, tile_id="t001", pass_no=1, operator="OP1")
K.put(polys2, box(0, 0, 3, 1), class_name="b", class_code=2,
      tile_id="t001", pass_no=1, operator="OP1")
host2 = K.Host(polys2, tiles2)
host2.geometry.origin = (0.0, float(SIDE))
polys2.startEditing()
host2.remember_shapes()
# a stroke of class c over the middle of the frame, away from the strip: the
# strip must come through the cut of the polygons around it untouched
over(host2, box(8, 8, 14, 14), "c")
mask2 = burned(polys2)
check("the strip is still there after a stroke elsewhere",
      (mask2[SIDE - 1, 0:3] == 2).all(), mask2[SIDE - 1, 0:3].tolist())
check("and nothing is at 0", int((mask2 == 0).sum()) == 0)
# now a stroke of the same class b that merges with the strip, and one of c
# over a neighbour of a small polygon: the small polygon is not swallowed
over(host2, box(2.5, 0, 6, 3), "b")
mask2 = burned(polys2)
check("a stroke that merges with a small polygon keeps what it covered",
      int((mask2 == 0).sum()) == 0, np.argwhere(mask2 == 0).tolist())
check("and the strip is class b still", (mask2[SIDE - 1, 0:3] == 2).all(),
      mask2[SIDE - 1, 0:3].tolist())

print()
print("a stroke that cuts the polygon in two leaves both halves")
host3, polys3 = start()
# a vertical band of class a with a thin side of b left at each edge
over(host3, box(1, 0, SIDE - 1, SIDE))
mask3 = burned(polys3)
check("two columns of b stay at the edges, nothing at 0",
      int((mask3 == 0).sum()) == 0 and (mask3[:, 0] == 2).all()
      and (mask3[:, SIDE - 1] == 2).all(), np.argwhere(mask3 == 0).tolist())

print()
print("a vertex dragged over a neighbour leaves it a sliver, and it stays")
polys6 = K.Layer("polygons")
tiles6 = K.Layer("tiles")
K.put(tiles6, box(0, 0, SIDE, SIDE), tile_id="t001")
pocket = box(17, 0, 20, 1)
big = K.put(polys6, box(0, 0, SIDE, SIDE).difference(pocket), class_name="a",
            class_code=1, tile_id="t001", pass_no=1, operator="OP1")
K.put(polys6, pocket, class_name="b", class_code=2, tile_id="t001",
      pass_no=1, operator="OP1")
host6 = K.Host(polys6, tiles6)
host6.geometry.origin = (0.0, float(SIDE))
polys6.startEditing()
host6.remember_shapes()
# the border of a is pushed across the pocket, up to its last pixel
polys6.drag(big, box(0, 0, SIDE, SIDE).difference(box(19, 0, 20, 1)))
K.Loop.run()
mask6 = burned(polys6)
check("the pixel of b that is left is still b, not 0",
      mask6[SIDE - 1, 19] == 2, mask6[SIDE - 1, 17:20].tolist())
check("and nothing in the frame is at 0", int((mask6 == 0).sum()) == 0,
      np.argwhere(mask6 == 0).tolist())

# -------------------------------------------------- Fill Gap finds small holes
print()
print("Fill Gap finds a hole of one or two pixels")
polys4 = K.Layer("polygons")
tiles4 = K.Layer("tiles")
K.put(tiles4, box(0, 0, SIDE, SIDE), tile_id="t001")
hole = box(8, 8, 10, 9)
K.put(polys4, box(0, 0, SIDE, SIDE).difference(hole), class_name="b",
      class_code=2, tile_id="t001", pass_no=1, operator="OP1")
host4 = K.Host(polys4, tiles4)
host4.geometry.origin = (0.0, float(SIDE))
host4.close_holes = SA.AnnotationSection.__dict__["close_holes"].__get__(host4)
host4.class_name = "a"
host4.current_code = lambda: 1
asked = []


class Boxes(object):
    class StandardButton(object):
        Yes = "yes"
        No = "no"
        Save = "save"
        Discard = "discard"
        Cancel = "cancel"

    @staticmethod
    def question(parent, title, text, *a, **k):
        asked.append(text)
        return "yes"


real_boxes = SA.QMessageBox
SA.QMessageBox = Boxes
try:
    before = burned(polys4)
    check("the mask has two pixels at 0 before", int((before == 0).sum()) == 2,
          int((before == 0).sum()))
    polys4.startEditing()
    host4.close_holes()
    K.Loop.run()
finally:
    SA.QMessageBox = real_boxes
after = burned(polys4)
check("Fill Gap asked about it instead of saying there are no holes",
      len(asked) == 1 and "1 unpainted area" in asked[0], asked)
check("and the mask has no pixel at 0 afterwards",
      int((after == 0).sum()) == 0, np.argwhere(after == 0).tolist())

print()
print("the dust of a border worked out twice is not a hole")
polys5 = K.Layer("polygons")
tiles5 = K.Layer("tiles")
K.put(tiles5, box(0, 0, SIDE, SIDE), tile_id="t001")
K.put(polys5, box(0, 0, SIDE, 10), class_name="b", class_code=2,
      tile_id="t001", pass_no=1, operator="OP1")
K.put(polys5, box(0, 10 + 1e-9, SIDE, SIDE), class_name="a", class_code=1,
      tile_id="t001", pass_no=1, operator="OP1")
host5 = K.Host(polys5, tiles5)
host5.geometry.origin = (0.0, float(SIDE))
host5.close_holes = SA.AnnotationSection.__dict__["close_holes"].__get__(host5)
host5.class_name = "a"
shown = []
Boxes.question = staticmethod(lambda *a, **k: shown.append(a) or "yes")
SA.QMessageBox = Boxes
try:
    K.Bar.said[:] = []
    host5.close_holes()
finally:
    SA.QMessageBox = real_boxes
check("a hair-thin gap between two borders says no holes",
      not shown and any("no holes" in m for m in K.Bar.said),
      (shown, K.Bar.said))

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
