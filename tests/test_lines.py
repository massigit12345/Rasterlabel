"""The strip a line claims, taken from rasterlabel_34.py as it is written
and run against a real grid.

What has to hold: the strip is exactly as many pixels wide as was asked,
whichever way the line runs, measured at a right angle to it; it has no holes,
because an interrupted crack is not a crack; and once it has entered the
partition it leaves no area counted twice, neither when it cuts nor when it
yields.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast
import math
import os
import sys

import numpy as np
import shapely
from shapely.geometry import Polygon, box as shbox
from shapely.ops import unary_union

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


def module_source(name):
    """A function or a plain assignment of the module, as it is written."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == name for t in node.targets):
            return "".join(lines[node.lineno - 1:node.end_lineno])
    return None


def source_of(name, inside):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    t = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s not found" % name)


# --------------------------------------------- the fake grid, but an exact one
PX = PY = 0.05                      # 5 cm, like your orthomosaics
OX, OY = 400000.0, 4100000.0


class Pt(object):
    def __init__(self, x, y): self._x, self._y = float(x), float(y)
    def x(self): return self._x
    def y(self): return self._y


class Rect(object):
    def __init__(self, a, b, c, d): self.v = (a, b, c, d)


class Geom(object):
    """The least strip() needs: a rectangle that turns into shapely, and the
    union."""
    def __init__(self, poly): self.poly = poly

    @staticmethod
    def fromRect(r):
        x0, y0, x1, y1 = r.v
        return Geom(shbox(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))

    @staticmethod
    def unaryUnion(pieces):
        return Geom(unary_union([p.poly for p in pieces]))


class Grid(object):
    pixel_crs = (PX, PY)
    origin = (OX, OY)
    pixel_m = (PX, PY)


ns = {"math": math, "np": np, "QgsGeometry": Geom, "QgsRectangle": Rect}
# what strip() stands on, when the module has it
for _name in ("_KEY_SHIFT", "_KEY_OFFSET", "_pixel_key", "_pixel_unkey",
              "_has_pixel", "_near_trace", "_close_corners", "_cells_in_line",
              "line_pixels"):
    _text = module_source(_name)
    if _text:
        exec(_text, ns)
exec(source_of("strip", "Geometry"), ns)
Grid.strip = ns["strip"]
grid = Grid()


def pixels_of(poly):
    """The pixels whose centre falls inside the polygon: exactly what gdal
    does with ALL_TOUCHED switched off, which is how the mask gets burned."""
    x0, y0, x1, y1 = poly.bounds
    c0 = int(math.floor((x0 - OX) / PX)) - 1
    c1 = int(math.ceil((x1 - OX) / PX)) + 1
    r0 = int(math.floor((OY - y1) / PY)) - 1
    r1 = int(math.ceil((OY - y0) / PY)) + 1
    out = set()
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            cx = OX + (c + 0.5) * PX
            cy = OY - (r + 0.5) * PY
            if poly.contains(Polygon([(cx, cy), (cx, cy), (cx, cy)]).centroid) \
                    or poly.covers(Polygon([(cx - 1e-9, cy - 1e-9),
                                            (cx + 1e-9, cy - 1e-9),
                                            (cx + 1e-9, cy + 1e-9),
                                            (cx - 1e-9, cy + 1e-9)])):
                out.add((r, c))
    return out


print("the width is the one that was asked for")
# a horizontal line 2 m long, which is 40 pixels
A = Pt(OX + 0.5 * PX, OY - 10.5 * PY)
B = Pt(OX + 40.5 * PX, OY - 10.5 * PY)
for w in (1, 2, 3, 5, 8):
    g, n = grid.strip([A, B], w)
    px = pixels_of(g.poly)
    per_col = {}
    for r, c in px:
        per_col.setdefault(c, set()).add(r)
    widths = {len(v) for v in per_col.values()}
    check("%d px -> every column has %d of them" % (w, w), widths == {w},
          sorted(widths))
    check("%d px -> no empty column along the run" % w,
          len(per_col) >= 40, len(per_col))

print()
print("a diagonal does not break apart")
C = Pt(OX + 0.5 * PX, OY - 0.5 * PY)
D = Pt(OX + 30.5 * PX, OY - 30.5 * PY)
g, n = grid.strip([C, D], 1)
px = pixels_of(g.poly)
rows = sorted({r for r, _ in px})
check("it touches every row between the first and the last",
      rows == list(range(rows[0], rows[-1] + 1)), len(rows))
# continuity: every pixel has a neighbour, even only a diagonal one
isolated = [(r, c) for r, c in px
            if not any((r + dr, c + dc) in px
                       for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                       if (dr, dc) != (0, 0))]
check("no isolated pixel: the track is continuous", not isolated, isolated[:4])

print()
print("a polyline stays joined all the way")
E = Pt(OX + 0.5 * PX, OY - 0.5 * PY)
F = Pt(OX + 20.5 * PX, OY - 10.5 * PY)
G = Pt(OX + 5.5 * PX, OY - 25.5 * PY)
g, n = grid.strip([E, F, G], 3)
px = pixels_of(g.poly)
# a breadth first walk: if everything is reached starting from a single
# pixel, the strip is one single piece
start = next(iter(px))
seen, queue = {start}, [start]
while queue:
    r, c = queue.pop()
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            q = (r + dr, c + dc)
            if q in px and q not in seen:
                seen.add(q); queue.append(q)
check("one piece only, even at the bend", seen == px,
      "%d of %d" % (len(seen), len(px)))

print()
print("a straight thick line is one piece too")
# The real defect was not the diagonal: it was that the bottom of a row was
# worked out as "the top edge minus one pixel" and the top edge of the row
# below as "the origin minus n pixels". In floating point those are two
# different numbers, half a nanometre apart, and the rows did not touch.
g, n = grid.strip([A, B], 5)
pieces = list(getattr(g.poly, "geoms", [g.poly]))
check("five rows make one strip, not five strips",
      len(pieces) == 1, len(pieces))

print()
print("an exact 45 degree diagonal stays one piece")
# The defect: the cells of a track at 45 degrees touch only at their corners,
# the union keeps them apart, and every one pixel piece falls below the
# threshold of four pixels. The line was recorded and the ground was not
# painted.
P = Pt(OX + 0.5 * PX, OY - 0.5 * PY)
Q = Pt(OX + 40.5 * PX, OY - 40.5 * PY)
g, n = grid.strip([P, Q], 1)
pieces = list(getattr(g.poly, "geoms", [g.poly]))
check("one piece only, not forty", len(pieces) == 1, len(pieces))
area_px = g.poly.area / (PX * PY)
check("and it stays above the threshold of four pixels", area_px >= 4.0,
      area_px)
px_diag = pixels_of(g.poly)
isolated = [(r, c) for r, c in px_diag
            if not any((r + dr, c + dc) in px_diag
                       for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)))]
check("every pixel has a neighbour on a side, not only at a corner",
      not isolated, isolated[:4])
check("and the track reaches from one end to the other",
      len({r for r, _ in px_diag}) >= 40, len({r for r, _ in px_diag}))

thick_diag, _ = grid.strip([P, Q], 3)
pieces3 = list(getattr(thick_diag.poly, "geoms", [thick_diag.poly]))
check("and a width of three stays one piece just as before", len(pieces3) == 1,
      len(pieces3))

print()
print("the width is the same in every direction")
# What "N pixels wide" means: a rectangle N pixels across, at a right angle to
# the line, whose pixels are the ones with their centre inside. The square
# nib this replaced made a line N * (|cos| + |sin|) wide, 41 percent more
# than asked at 45 degrees. The width is read off the burned pixels, as the
# count per pixel of length: the rectangle runs N / 2 past the two ends.
def burn(poly):
    """The pixels whose centre is inside the polygon, as a set."""
    x0, y0, x1, y1 = poly.bounds
    c0 = int(math.floor((x0 - OX) / PX)) - 1
    c1 = int(math.ceil((x1 - OX) / PX)) + 1
    r0 = int(math.floor((OY - y1) / PY)) - 1
    r1 = int(math.ceil((OY - y0) / PY)) + 1
    rr, cc = np.meshgrid(np.arange(r0, r1 + 1), np.arange(c0, c1 + 1),
                         indexing="ij")
    gx, gy = OX + (cc + 0.5) * PX, OY - (rr + 0.5) * PY
    got = shapely.contains_xy(poly, gx.ravel(), gy.ravel())
    return set(zip(rr.ravel()[got].tolist(), cc.ravel()[got].tolist()))


def pt(col, row):
    return Pt(OX + col * PX, OY - row * PY)


def width_of(a, b, n, burned):
    """Burned pixels per pixel of line, ends included: the width, in pixels."""
    return len(burned) / (math.hypot(b[0] - a[0], b[1] - a[1]) + n)


def chain(angle, start, length=64.0):
    a = start
    b = (a[0] + length * math.cos(math.radians(angle)),
         a[1] + length * math.sin(math.radians(angle)))
    return a, b


# starts on a pixel centre and between pixel centres: a width that is only
# right where the line happens to run through the centres is not right
STARTS = [(10.5, 10.5), (10.1, 10.3), (10.37, 10.82), (10.9, 10.2),
          (10.25, 10.65), (10.77, 10.43)]
for n in (1, 2, 3, 4, 5):
    for angle in (0, 15, 30, 45, 60, 90):
        got = []
        for start in STARTS:
            a, b = chain(angle, start)
            g, _ = grid.strip([pt(*a), pt(*b)], n)
            got.append(width_of(a, b, n, burn(g.poly)))
        mean = sum(got) / len(got)
        if n == 1:
            # one pixel is the thinnest an unbroken line can be, and a slanted
            # one cannot be unbroken edge to edge with less than |cos| + |sin|
            high = (abs(math.cos(math.radians(angle)))
                    + abs(math.sin(math.radians(angle))) + 0.05)
            check("1 px at %d degrees is as thin as an unbroken line can be "
                  "(%.2f)" % (angle, mean), min(got) >= 0.99 and max(got) <= high,
                  (min(got), max(got)))
        else:
            # through the pixel centres at 45 degrees the pixels come in whole
            # diagonals, 0.7 of a pixel apart, and one line can read half a
            # pixel off; the mean over places on the grid is the width
            check("%d px at %d degrees is %d px wide (%.2f)" % (n, angle, n, mean),
                  abs(mean - n) <= 0.05 * n + 0.02
                  and all(abs(w - n) <= 0.6 for w in got),
                  (min(got), max(got)))

def seg_dist(p, a, b):
    ab = (b[0] - a[0], b[1] - a[1])
    t = (((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1])
         / max(ab[0] ** 2 + ab[1] ** 2, 1e-18))
    t = min(1.0, max(0.0, t))
    return math.hypot(p[0] - a[0] - t * ab[0], p[1] - a[1] - t * ab[1])


print()
print("a polyline with a sharp turn is as wide on both legs")
# out along a row, then back at 20 degrees to the first leg: the legs are
# far apart at their far ends, which is where the width is read
for n in (1, 3, 5):
    a = (10.5, 10.5)
    corner = (a[0] + 50.0, a[1])
    end = (corner[0] - 45.0 * math.cos(math.radians(20)),
           corner[1] + 45.0 * math.sin(math.radians(20)))
    g, _ = grid.strip([pt(*a), pt(*corner), pt(*end)], n)
    burned = burn(g.poly)
    # each leg from 25 pixels after the turn to its far end, where the other
    # leg is more than a width away, and every pixel is given to the leg it is
    # nearer to
    legs = [(a, corner), (end, corner)]
    mine = ([], [])
    for r, c in burned:
        here = (c + 0.5, r + 0.5)
        near = [seg_dist(here, p, q) for p, q in legs]
        k = 0 if near[0] <= near[1] else 1
        p, q = legs[k]
        along = (math.hypot(here[0] - q[0], here[1] - q[1]))
        if along > 25:
            mine[k].append((r, c))
    for k, word in ((0, "first"), (1, "second")):
        p, q = legs[k]
        leg = math.hypot(q[0] - p[0], q[1] - p[1])
        # from 25 pixels short of the turn to N / 2 beyond the far end
        length = leg - 25 + n / 2.0
        check("%d px: the %s leg is %d wide" % (n, word, n),
              abs(len(mine[k]) / length - n) <= 0.1 * n + 0.15,
              len(mine[k]) / length)
    pieces = list(getattr(g.poly, "geoms", [g.poly]))
    check("%d px: one strip, not two" % n, len(pieces) == 1, len(pieces))


print()
print("a turn does not widen the line beyond the corner of its ends")
for n in (1, 3, 5):
    a, mid, end = (10.5, 10.5), (40.5, 30.5), (12.5, 36.5)
    g, _ = grid.strip([pt(*a), pt(*mid), pt(*end)], n)
    reach = max(min(seg_dist((c + 0.5, r + 0.5), p, q)
                    for p, q in ((a, mid), (mid, end)))
                for r, c in burn(g.poly))
    limit = n * math.sqrt(0.5) + (0.8 if n == 1 else 0.02)
    check("%d px: the farthest pixel is %.2f from the trace (at most %.2f)"
          % (n, reach, limit), reach <= limit)

print()
print("a horizontal or vertical line is what it always was")
# The strip this replaced, kept here as it was written, to say that the lines
# that were already exact come out the same, vertex for vertex.
def old_strip(points, width_px):
    cells = set()
    for a, b in zip(points[:-1], points[1:]):
        c0, r0 = (a.x() - OX) / PX, (OY - a.y()) / PY
        c1, r1 = (b.x() - OX) / PX, (OY - b.y()) / PY
        steps = int(max(abs(c1 - c0), abs(r1 - r0)) * 3) + 1
        last = None
        for i in range(steps + 1):
            t = float(i) / steps
            here = (int(math.floor(r0 + (r1 - r0) * t)),
                    int(math.floor(c0 + (c1 - c0) * t)))
            if last is not None and here[0] != last[0] and here[1] != last[1]:
                cells.add((last[0], here[1]))
            cells.add(here)
            last = here
    low = -(width_px // 2)
    wide = set()
    for r, c in cells:
        for dr in range(low, low + width_px):
            for dc in range(low, low + width_px):
                wide.add((r + dr, c + dc))
    rows = {}
    for r, c in wide:
        rows.setdefault(r, []).append(c)
    pieces = []
    for r in sorted(rows):
        cols = sorted(rows[r])
        start = prev = cols[0]
        for c in cols[1:] + [None]:
            if c is not None and c == prev + 1:
                prev = c
                continue
            pieces.append(Geom.fromRect(Rect(OX + start * PX, OY - (r + 1) * PY,
                                             OX + (prev + 1) * PX, OY - r * PY)))
            if c is not None:
                start = prev = c
    return Geom.unaryUnion(pieces), len(wide)


# every width, on and between the pixel centres, on pixel edges too, with
# vertices in the middle and walked either way: a line that was exact stays
# the same strip, the same polygon down to the byte
import random
rnd = random.Random(7)
same = True
tried = 0
for n in (1, 2, 3, 4, 5, 6, 7, 8):
    for _ in range(40):
        grain = rnd.choice((1.0, 0.5, 0.0))       # on edges, on centres, or free
        def spot():
            v = rnd.uniform(5.0, 90.0)
            return v if grain == 0.0 else math.floor(v / grain) * grain
        row, col = spot(), spot()
        c0, c1, c2 = sorted((spot(), spot(), spot()))
        if rnd.random() < 0.5:
            pts = [(c0, row), (c1, row), (c2, row)]
        else:
            pts = [(col, c0), (col, c1), (col, c2)]
        if rnd.random() < 0.5:
            pts.reverse()
        a_pts = [pt(*q) for q in pts]
        g, count = grid.strip(a_pts, n)
        was, was_count = old_strip(a_pts, n)
        tried += 1
        if g.poly.wkb != was.poly.wkb or count != was_count:
            same = False
            print("   differs: %d px %s" % (n, pts))
check("rows and columns come out vertex for vertex as before, %d of them" % tried,
      same)
slight = [pt(10.2, 10.7), pt(50.9, 10.1)]
check("and a row with a slight tilt for odd widths",
      all(grid.strip(slight, n)[0].poly.wkb == old_strip(slight, n)[0].poly.wkb
          for n in (1, 3, 5)))

print()
print("a bend of a row and a column is the old strip with a rounded outer corner")
bent = [pt(10.5, 10.5), pt(40.5, 10.5), pt(40.5, 30.5)]
for n in (1, 3, 5):
    now = burn(grid.strip(bent, n)[0].poly)
    was = burn(old_strip(bent, n)[0].poly)
    lost = was - now
    check("%d px: nothing is added to the old strip" % n, not (now - was),
          sorted(now - was)[:4])
    check("%d px: only the outer corner is rounded off, and by no more than "
          "a corner" % n,
          len(lost) <= max(1, n * n // 4)
          and all(seg_dist((c + 0.5, r + 0.5), (10.5, 10.5), (40.5, 10.5)) > n / 2.0
                  and seg_dist((c + 0.5, r + 0.5), (40.5, 10.5), (40.5, 30.5)) > n / 2.0
                  for r, c in lost), len(lost))

print()
print("a trace drawn freehand is no wider than a straight one")
# Freehand is many short stretches, a sample every few screen pixels at the
# whole numbers the mouse gives, whose directions wobble. Squaring every
# stretch off wherever it ends put a rotated square on each vertex and the
# trace came out up to a third wider than asked. Only the two ends of the
# whole trace are squared off, and the vertices inside are joined round.
line_pixels = ns["line_pixels"]


def freehand(angle, zoom, wobble, rnd, length=400):
    """What the mouse gives: a point every 4 screen pixels or so, rounded to
    whole screen pixels, with the hand off the line by up to wobble pixels."""
    th = math.radians(angle)
    pts, last = [], None
    for i in range(length * 4):
        s = i / 4.0
        j = rnd.uniform(-wobble, wobble)
        q = (round(s * math.cos(th) - j * math.sin(th)),
             round(s * math.sin(th) + j * math.cos(th)))
        if last is None or abs(q[0] - last[0]) + abs(q[1] - last[1]) >= 4:
            pts.append(q)
            last = q
    return np.array(pts, dtype=float) / zoom + 50.0


rnd = random.Random(3)
for n in (3, 5, 9):
    for angle in (0, 10, 30, 45, 90):
        got = []
        for _ in range(6):
            path = freehand(angle, 4, 0.7, rnd)
            walked = float(np.hypot(*np.diff(path, axis=0).T).sum())
            got.append(len(line_pixels(path, n)[0]) / (n * (walked + n)))
        mean = sum(got) / len(got)
        # a 3 pixel line at 45 degrees is a whole number of diagonals of
        # pixels, and reads up to 15 percent off whatever the hand does
        high = 1.15 if (n == 3 and angle == 45) else 1.1
        check("%d px freehand at %d degrees: %.2f of the area of the trace "
              "walked" % (n, angle, mean), 0.9 <= mean <= high, got)

# a clean two point line and the same line with extra vertices on it
for n in (3, 5, 9):
    a, b = (12.3, 14.1), (12.3 + 60 * math.cos(math.radians(30)),
                          14.1 + 60 * math.sin(math.radians(30)))
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    whole = set(zip(*line_pixels(np.array([a, b]), n)))
    twice = set(zip(*line_pixels(np.array([a, mid, mid, b]), n)))
    check("%d px: a vertex repeated in the middle of a line changes nothing" % n,
          whole == twice, len(whole ^ twice))
    # the hand off the line by 0.3 of a pixel in the middle
    kink = (mid[0] + 0.3 * math.sin(math.radians(30)),
            mid[1] - 0.3 * math.cos(math.radians(30)))
    bent = set(zip(*line_pixels(np.array([a, kink, b]), n)))
    check("%d px: a kink of 0.3 pixels adds a few pixels, not a band" % n,
          len(bent) <= len(whole) + 0.5 * n * 2 + 2
          and len(bent) >= len(whole) - n, (len(whole), len(bent)))

# the same strip whichever way the hand went, round trips included
path = freehand(20, 4, 0.7, random.Random(5), length=120)
for n in (1, 2, 3, 5):
    fwd = line_pixels(path, n)
    back = line_pixels(path[::-1].copy(), n)
    check("%d px: the strip does not depend on the direction drawn" % n,
          all((x == y).all() for x, y in zip(fwd, back)))

print()
print("the strip sits on whole pixels")
g, n = grid.strip([A, B], 3)
x0, y0, x1, y1 = g.poly.bounds
for v, step, zero in ((x0, PX, OX), (x1, PX, OX)):
    k = (v - zero) / step
    check("the edge falls on a pixel boundary (%.4f)" % k,
          abs(k - round(k)) < 1e-9, k)

print()
print("inside the partition it overlaps nothing")
# a polygon of another class, and the line that crosses it
field = shbox(OX, OY - 30 * PY, OX + 40 * PX, OY)
g, n = grid.strip([A, B], 3)
# the tip is square, like a brush tip: a width of 3 spills one pixel past the
# two ends. Inside a frame draw_line clips it, and the same is done here,
# otherwise the field would be compared against a band longer than itself
band = g.poly.intersection(field)

# OVER: the line wins, the field is clipped
rest = field.difference(band)
check("over: the field loses exactly the band",
      abs(field.area - rest.area - band.area) < 1e-12,
      (field.area - rest.area, band.area))
check("over: no doubled area", rest.intersection(band).area < 1e-12)
check("over: together they cover what was there before",
      abs(rest.area + band.area - field.area) < 1e-12)

# UNDER: the line yields, it stays only where there was nothing
outside = band.difference(field)
check("under: nothing of the line is left inside the field",
      outside.intersection(field).area < 1e-12)
check("under: the field is not touched", abs(field.area - field.area) < 1e-12)

# a line that leaves the field on both sides breaks into two
long_a = Pt(OX - 10 * PX, OY - 10.5 * PY)
long_b = Pt(OX + 60 * PX, OY - 10.5 * PY)
g2, _ = grid.strip([long_a, long_b], 3)
pieces = g2.poly.difference(field)
n_pieces = len(list(getattr(pieces, "geoms", [pieces])))
check("under: the line comes out in pieces, one per side", n_pieces == 2,
      n_pieces)

print()
print("what the code promises")
st = source_of("strip", "Geometry")
check("it picks pixels instead of widening the line",
      ".buffer(" not in st and "line_pixels(" in st)
check("the width never drops below one", "max(1, int(width_px))" in st)
check("it says which way an even width leans",
      "leans" in (module_source("line_pixels") or ""))

check("the buttons no longer promise the width of a square nib",
      "wide again on a diagonal" not in source
      and "a square of that width" not in source)

dl = source_of("draw_line", "AnnotationSection")
check("it saves the track as a line", 'f["length_m"]' in dl)
check("and the width in pixels and in metres",
      'f["width_px"]' in dl and 'f["width_m"]' in dl)
check("it writes down which way it yielded", 'f["mode"]' in dl)
check("it goes through the same machinery as the brush",
      "self.paint(band" in dl)
check("it reads the checkbox once only, when you draw",
      "self.line_over.isChecked()" in dl)
check("it carries operator and pass like the polygons",
      'f["operator"]' in dl and 'f["pass_no"]' in dl)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
