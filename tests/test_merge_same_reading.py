"""Polygons of one class, one reading and one frame that meet become one.

At the moment a new mark or a moved vertex makes them meet, in the same edit
command, so one Undo puts back exactly what stood there before. Here the real
paint(), settle_edits(), repair() and undo_stroke() run through editkit on GEOS:

  meet      an overlapping stroke, a stroke that shares a border, a stroke that
            bridges two polygons: one polygon each;
  corner    two polygons that touch at a single point stay two (their union is
            not one polygon);
  apart     another class, another operator, another pass, another frame: never
            merged, and never touched;
  vertex    a vertex dragged against a neighbour of its own class joins it, a
            corner touch does not, a neighbour of another class is trimmed as
            before;
  undo      one Undo gives back the very polygons that were there, with their
            ids, and so does one Undo of a vertex move's tidying;
  repair    an old campaign, with neighbours that were never merged, is merged
            by Repair in one step;
  attrs     the date of creation is the earliest of the parts, the rest is the
            same on every part by construction;
  order     where another reading lies over the same ground, no merge that would
            change which of them is drawn last;
  pixels    the mask burned from the table, in the order it is burned in, is the
            same with merging and without it, over a long random session;
  journal   one mark for a stroke, whatever it merged, and the recovery net is
            written after it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import random
import sys
import time

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
from shapely.wkt import loads as shapely_wkt

SA = K.SA
fails = []
SIDE = 20


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def start(rows=(), side=SIDE, frames=1, merging=True, operator="OP1"):
    """A section over a frame (or a row of them) with these polygons on disk:
    (shape, class, operator, pass, tile, created)."""
    polys = K.Layer("polygons")
    tiles = K.Layer("tiles")
    for i in range(frames):
        K.put(tiles, box(i * side, 0, (i + 1) * side, side),
              tile_id="t%03d" % (i + 1))
    code = {"a": 1, "b": 2, "c": 3}
    for shape, name, who, pass_no, tile, created in rows:
        K.put(polys, shape, class_name=name, class_code=code[name],
              tile_id=tile, pass_no=pass_no, operator=who, created=created)
    host = K.Host(polys, tiles, operator=operator)
    host.geometry.origin = (0.0, float(side))
    host.merging = merging
    host.marks = []
    host.note = lambda action, timing=None, **f: host.marks.append((action, f))
    polys.startEditing()
    host.remember_shapes()
    return host, polys


def row(shape, name="a", who="OP1", pass_no=1, tile="t001",
        created="2026-03-01T10:00:00"):
    return (shape, name, who, pass_no, tile, created)


def stroke(host, shape, name="a"):
    host.class_name = name
    host.paint(K.G(shape))
    K.Loop.run()


def shapes(polys, name=None, who=None):
    return [f._g.s for f in polys.getFeatures()
            if (name is None or f["class_name"] == name)
            and (who is None or f["operator"] == who)]


def snapshot(polys):
    """Everything the table holds, by id."""
    return {f.id(): (dict(f.values), f._g.s.wkt)
            for f in polys.getFeatures()}


# ------------------------------------------------------------ meeting ground
print("a stroke that overlaps a polygon of its class")
host, polys = start([row(box(0, 0, 5, 5))])
stroke(host, box(3, 3, 8, 8))
got = shapes(polys, "a")
check("one polygon", len(got) == 1, len(got))
check("of the union", got and abs(got[0].area - 46.0) < 1e-9,
      got[0].area if got else None)
check("and valid", got and got[0].is_valid)

print()
print("a stroke that only shares a border")
host, polys = start([row(box(0, 0, 5, 5))])
stroke(host, box(5, 0, 8, 5))
got = shapes(polys, "a")
check("one polygon of 40", len(got) == 1 and abs(got[0].area - 40.0) < 1e-9,
      [g.area for g in got])

print()
print("a stroke that bridges two polygons")
host, polys = start([row(box(0, 0, 4, 4), created="2026-03-02T10:00:00"),
                     row(box(8, 0, 12, 4), created="2026-03-01T09:00:00")])
before = polys.featureCount()
stroke(host, box(3, 1, 9, 3))
got = shapes(polys, "a")
check("three polygons become one", before == 2 and len(got) == 1
      and abs(got[0].area - 40.0) < 1e-9, [g.area for g in got])
dates = [f["created"] for f in polys.getFeatures()]
check("it carries the earliest date of creation of its parts",
      dates == ["2026-03-01T09:00:00"], dates)

print()
print("two polygons that touch at one point stay two")
host, polys = start([row(box(0, 0, 5, 5))])
only = [f.id() for f in polys.getFeatures()]
stroke(host, box(5, 5, 8, 8))
got = shapes(polys, "a")
check("two polygons", len(got) == 2, len(got))
check("and the first is the very feature it was",
      only[0] in {f.id() for f in polys.getFeatures()})
check("with the date it had", sorted(f["created"] for f in polys.getFeatures()
                                      )[0] == "2026-03-01T10:00:00")

print()
print("a hole closed by the merge makes a polygon with a hole, not two")
host, polys = start([row(box(2, 2, 9, 9).difference(box(4, 4, 7, 7)))])
stroke(host, box(6, 3, 8, 8))
got = shapes(polys, "a")
check("one polygon", len(got) == 1, len(got))

# ------------------------------------------------------- what is not merged
print()
print("another class, operator, pass or frame is not merged and not touched")
host, polys = start([row(box(0, 0, 5, 5), "b"),
                     row(box(0, 5, 5, 8), "a", "OP2"),
                     row(box(5, 0, 8, 5), "a", "OP1", 2),
                     row(box(20, 0, 25, 5), "a", "OP1", 1, "t002")],
                    frames=2)
host.by_operator.on = False          # every operator is in scope
snap = snapshot(polys)
stroke(host, box(5, 5, 9, 8), "a")
now = snapshot(polys)


def same(k):
    """The polygon kept its id and attributes and covers the same ground; a
    stroke that only touches it may write its outline again."""
    return (k in now and now[k][0] == snap[k][0]
            and shapely_wkt(now[k][1]).equals(shapely_wkt(snap[k][1])))


check("the four polygons are as they were", all(same(k) for k in snap),
      [k for k in snap if not same(k)])
check("and the stroke is a polygon of its own, a reading of its own",
      len(now) == len(snap) + 1, len(now))
host, polys = start([row(box(15, 0, 20, 5), "a", "OP1", 1, "t001"),
                     row(box(20, 0, 25, 5), "a", "OP1", 1, "t002")], frames=2)
stroke(host, box(10, 0, 20, 10))
ids = {(f["tile_id"]) for f in polys.getFeatures()}
check("a polygon of the next frame sharing a border is not joined",
      len(shapes(polys, "a")) == 2 and ids == {"t001", "t002"},
      [(f["tile_id"], f._g.s.area) for f in polys.getFeatures()])

print()
print("with merging switched off nothing is joined")
host, polys = start([row(box(0, 0, 5, 5))], merging=False)
stroke(host, box(3, 3, 8, 8))
check("two polygons stay two", len(shapes(polys, "a")) >= 2)

# ----------------------------------------------------------------- vertices
print()
print("a vertex dragged against a neighbour of its own class")
for label, target, want in [
        ("to share its border", box(5, 0, 10, 5), 1),
        ("into it", box(4, 0, 10, 5), 1),
        ("to touch at a corner", box(5, 5, 10, 10), 2),
        ("away from it", box(7, 0, 12, 5), 2)]:
    host, polys = start([row(box(0, 0, 5, 5)), row(box(6, 0, 10, 5))])
    two = [f.id() for f in polys.getFeatures()][1]
    polys.drag(two, target)
    K.Loop.run()
    got = shapes(polys, "a")
    check("%s: %d polygon%s" % (label, want, "" if want == 1 else "s"),
          len(got) == want, [g.area for g in got])
    if want == 1:
        check("   and the union is whole",
              abs(got[0].area - (25 + target.area - box(0, 0, 5, 5)
                                 .intersection(target).area)) < 1e-9,
              got[0].area)

print()
print("a vertex pushed into another class is trimmed as it always was")
host, polys = start([row(box(0, 0, 5, 5)), row(box(5, 0, 10, 5), "b")])
one = [f.id() for f in polys.getFeatures()][0]
polys.drag(one, box(0, 0, 7, 5))
K.Loop.run()
check("two polygons, a wins", len(shapes(polys)) == 2
      and abs(shapes(polys, "a")[0].area - 35) < 1e-9
      and abs(shapes(polys, "b")[0].area - 15) < 1e-9,
      [(f["class_name"], f._g.s.area) for f in polys.getFeatures()])

print()
print("one Undo of the tidying, then of the drag")
host, polys = start([row(box(0, 0, 5, 5)), row(box(6, 0, 10, 5))])
orig = snapshot(polys)
two = [f.id() for f in polys.getFeatures()][1]
polys.drag(two, box(4, 0, 10, 5))
K.Loop.run()
check("merged", polys.featureCount() == 1)
host.undo_stroke()
K.Loop.run()
step = snapshot(polys)
check("the first Undo puts back both polygons, the second as dragged",
      set(step) == set(orig) and step[two][1] != orig[two][1],
      sorted(step))
host.undo_stroke()
K.Loop.run()
check("the second Undo is the drag: both polygons as they were",
      snapshot(polys) == orig)

# --------------------------------------------------------------------- undo
print()
print("one Undo of a stroke gives back exactly what stood there")
host, polys = start([row(box(0, 0, 4, 4), created="2026-03-02T10:00:00"),
                     row(box(8, 0, 12, 4), created="2026-03-01T09:00:00"),
                     row(box(0, 8, 4, 12), "b")])
orig = snapshot(polys)
stroke(host, box(3, 1, 9, 3))
check("merged", len(shapes(polys, "a")) == 1)
host.undo_stroke()
check("Undo: the same polygons, ids, dates and shapes",
      snapshot(polys) == orig,
      (sorted(snapshot(polys)), sorted(orig)))
check("and a single command was on the stack to take back",
      polys.undoStack().index() == 0, polys.undoStack().index())

# ------------------------------------------------------------------- repair
print()
print("Repair joins the neighbours an old campaign never merged")
old = [row(box(0, 0, 5, 5)), row(box(5, 0, 10, 5)),
       row(box(10, 0, 15, 5)), row(box(15, 5, 18, 8)),   # corner touch
       row(box(0, 5, 5, 10), "b"), row(box(5, 5, 10, 10), "b"),
       row(box(0, 10, 5, 15), "a", "OP2")]
host, polys = start(old)
host.by_operator.on = True
orig = snapshot(polys)
K.Bar.said[:] = []
host.repair()
K.Loop.run()
a1 = [g for g in shapes(polys, "a", "OP1")]
check("the three in a row are one, the corner one stays",
      sorted(round(g.area) for g in a1) == [9, 75], [g.area for g in a1])
check("the two of class b are one", len(shapes(polys, "b")) == 1)
check("the other operator is as it was",
      len(shapes(polys, "a", "OP2")) == 1)
check("it said so", any("joined" in m for m in K.Bar.said), K.Bar.said)
host.undo_stroke()
check("one Undo gives them all back", snapshot(polys) == orig)

print()
print("Repair on a frame with nothing to join says nothing was joined")
host, polys = start([row(box(0, 0, 5, 5)), row(box(6, 0, 10, 5))])
K.Bar.said[:] = []
host.repair()
check("two polygons still", len(shapes(polys, "a")) == 2)
check("and no word of joining", not any("joined" in m for m in K.Bar.said),
      K.Bar.said)

# ------------------------------------------------------- another reading
print()
print("where another reading lies over the ground, the order of drawing decides")
# the other operator's polygon was saved after the first part: a new stroke is
# written after it, so standing for both would put the old ground on top of it
host, polys = start([row(box(0, 0, 5, 5)),
                     row(box(0, 0, 20, 20), "b", "OP2")])
host.by_operator.on = True
stroke(host, box(5, 0, 8, 5))
check("the stroke stays a polygon of its own",
      len(shapes(polys, "a")) == 2, len(shapes(polys, "a")))
# the other operator's polygon came first: nothing of ours changes sides
host, polys = start([row(box(0, 0, 20, 20), "b", "OP2"),
                     row(box(0, 0, 5, 5))])
stroke(host, box(5, 0, 8, 5))
check("or is joined when it does not change which is drawn last",
      len(shapes(polys, "a")) == 1, len(shapes(polys, "a")))

# --------------------------------------------------------------- the journal
print()
print("one mark and one recovery write for a stroke, merged or not")
host, polys = start([row(box(0, 0, 4, 4)), row(box(8, 0, 12, 4)),
                     row(box(0, 8, 4, 12))])
safe = host.panel.safe
stroke(host, box(3, 1, 9, 3))
check("one mark", [m[0] for m in host.marks] == ["stroke"], host.marks)
check("it says how many it joined",
      "merged 2" in host.marks[0][1].get("note", ""), host.marks)
check("the area is the stroke's, not the union's",
      abs(host.marks[0][1]["area_m2"] - 12.0) < 1e-9, host.marks[0][1])
check("the recovery file is written once after it", host.panel.safe == safe + 1,
      host.panel.safe - safe)
host, polys = start([row(box(0, 0, 5, 5)), row(box(6, 0, 10, 5))])
safe = host.panel.safe
two = [f.id() for f in polys.getFeatures()][1]
polys.drag(two, box(4, 0, 10, 5))
K.Loop.run()
check("a vertex move that joins is one mark and one write",
      [m[0] for m in host.marks] == ["vertex_edit"]
      and host.panel.safe == safe + 1, (host.marks, host.panel.safe - safe))
check("and the mark says it joined", "joined" in host.marks[0][1]["note"],
      host.marks)

# ------------------------------------------------------------------- speed
print()
print("a stroke among a few hundred polygons stays fast")
side = 100
cells = [row(box(x, y, x + 1, y + 1), "ab"[(x + y) % 2], tile="t001")
         for x in range(0, 30) for y in range(0, 30)]
host, polys = start(cells, side=side)
t0 = time.time()
stroke(host, box(10.5, 10.5, 12.5, 12.5), "a")
took = time.time() - t0
check("%d polygons, one stroke in %.2f s" % (len(cells), took), took < 5.0,
      took)

# ------------------------------------------------------------------- pixels
print()
print("the mask is the same with merging and without it")


def burn(polys, side=SIDE):
    """The frame, burned as a mask is: every pixel centre takes the class of
    the last polygon, in the order of the table, that covers it."""
    rows = sorted(polys.getFeatures(),
                  key=lambda f: SA.AnnotationSection.draw_rank(f.id()))
    mask = np.zeros((side, side), np.int32)
    for f in rows:
        s = f._g.s
        if s is None or s.is_empty:
            continue
        code = f["class_code"]
        minx, miny, maxx, maxy = s.bounds
        for r in range(max(0, int(side - maxy) - 1),
                       min(side, int(side - miny) + 2)):
            for c in range(max(0, int(minx) - 1), min(side, int(maxx) + 2)):
                if s.covers(Point(c + 0.5, side - r - 0.5)):
                    mask[r, c] = code
    return mask


def session(seed, merging, steps=60):
    rng = random.Random(seed)
    host, polys = start([row(box(0, 0, SIDE, SIDE), "b")], merging=merging)
    for _ in range(steps):
        x, y = rng.randrange(0, SIDE - 1), rng.randrange(0, SIDE - 1)
        w, h = rng.randrange(1, 8), rng.randrange(1, 8)
        shape = box(x, y, min(SIDE, x + w), min(SIDE, y + h))
        stroke(host, shape, rng.choice("abc"))
    return host, polys


worst, fewer = 0, 0
for seed in range(8):
    on, on_polys = session(seed, True)
    off, off_polys = session(seed, False)
    worst += int((burn(on_polys) != burn(off_polys)).sum())
    fewer += off_polys.featureCount() - on_polys.featureCount()
check("eight random sessions of sixty strokes: no pixel differs", worst == 0,
      worst)
check("and the table holds fewer polygons", fewer > 0, fewer)

print()
print("two readings together, in the order they are burned in")
rows = [row(box(0, 0, 20, 20), "b", "OP2"), row(box(0, 0, 6, 6)),
        row(box(0, 0, 20, 20), "c", "OP2", 1, "t001")]


def two_readings(merging):
    host, polys = start(rows, merging=merging)
    host.by_operator.on = True
    stroke(host, box(6, 0, 10, 6), "a")
    stroke(host, box(2, 5, 8, 12), "a")
    return polys


a, b = two_readings(True), two_readings(False)
check("the mask is the same", (burn(a) == burn(b)).all(),
      int((burn(a) != burn(b)).sum()))

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
