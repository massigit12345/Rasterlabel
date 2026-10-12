"""The vertex moved by hand, and the per-operator filter, taken from
rasterlabel_33.py exactly as they are written.

What has to hold: a vertex shared by two classes moves one polygon only;
after the move no overlap is left, because the polygon in hand wins; and
where the vertex was pulled back a gap is left unannotated, which is an
honest outcome and has to be measured, not hidden.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast, os
import sqlite3
import sys

from shapely.geometry import Polygon

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


def source_of(name, inside=None):
    for node in tree.body:
        if inside is None and isinstance(node, ast.FunctionDef) and node.name == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    t = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s not found" % name)


g = {}
exec(source_of("sql_text"), g)
sql_text = g["sql_text"]


def norm(v):
    """tidy_operator: spaces off, all upper case, then the sentinel."""
    return (v or "").strip().upper() or "UNNAMED"


print("the operator name, always in upper case")
for a, b in [("Massi", "MASSI"), ("  Massi ", "MASSI"), ("massi", "MASSI"),
             ("MASSI", "MASSI"), ("", "UNNAMED"), (None, "UNNAMED"),
             ("   ", "UNNAMED"), ("de luca", "DE LUCA")]:
    check("%r -> %r" % (a, b), norm(a) == b, norm(a))
check("the apostrophe is doubled", sql_text("D'Amico") == "'D''Amico'",
      sql_text("D'Amico"))

print()
print("brush and renderer hide the same rows")
EXPR = ("CASE WHEN coalesce(trim(operator), '') = '' THEN 'UNNAMED' "
        "ELSE upper(trim(operator)) END = %s")
ROWS = [(1, "t1", 1, "Massi"), (2, "t1", 1, " Massi "),
        (3, "t1", 1, "colleague"),
        (4, "t1", 1, None), (5, "t1", 1, ""), (6, "t1", 2, "Massi"),
        (7, "t2", 1, "Massi"), (8, "t1", 1, "D'Amico"), (9, "t1", 1, "massi")]
con = sqlite3.connect(":memory:")
con.execute("CREATE TABLE p (fid INT, tile_id TEXT, pass_no INT, operator TEXT)")
con.executemany("INSERT INTO p VALUES (?,?,?,?)", ROWS)


def brush(op, tile, pass_no):
    return {r[0] for r in ROWS
            if r[1] == tile and r[2] == pass_no and norm(r[3]) == op}


def renderer(op, tile, pass_no):
    q = ("SELECT fid FROM p WHERE " + EXPR % sql_text(op)
         + " AND tile_id = '%s' AND pass_no = %d" % (tile, pass_no))
    return {r[0] for r in con.execute(q)}


for op in ["MASSI", "COLLEAGUE", "UNNAMED", "D'AMICO"]:
    a, b = brush(op, "t1", 1), renderer(op, "t1", 1)
    check("'%s' sees the same rows from both sides" % op, a == b, (a, b))
check("the two with no name sit together under 'UNNAMED'",
      brush("UNNAMED", "t1", 1) == {4, 5}, brush("UNNAMED", "t1", 1))
check("'Massi' and 'massi' are the same person",
      brush("MASSI", "t1", 1) == {1, 2, 9}, brush("MASSI", "t1", 1))
seen = set()
for op in {norm(r[3]) for r in ROWS}:
    for t in {r[1] for r in ROWS}:
        for p in {r[2] for r in ROWS}:
            seen |= brush(op, t, p)
check("no row is invisible to everybody", seen == {r[0] for r in ROWS},
      sorted({r[0] for r in ROWS} - seen))

print()
print("the vertex moved: one class moves, the other does not")


def poly(*pts):
    return Polygon([(float(x), float(y)) for x, y in pts])


# two classes touching along x = 5, inside a 10 by 10 tile
TILE = poly((0, 0), (10, 0), (10, 10), (0, 10))
A = poly((0, 0), (5, 0), (5, 10), (0, 10))        # class 1, on the left
B = poly((5, 0), (10, 0), (10, 10), (5, 10))      # class 2, on the right

check("before the edit they only touch",
      A.intersection(B).area == 0.0, A.intersection(B).area)
check("and together they fill the tile",
      abs(A.area + B.area - TILE.area) < 1e-9)


def settle(moved, others):
    """settle_edits: the polygon in hand wins, the others get clipped."""
    dropped, kept, clipped = [], [], 0
    for o in others:
        if not o.intersects(moved):
            kept.append(o)
            continue
        shared = o.intersection(moved)
        if shared.is_empty or shared.area <= 0:
            kept.append(o)                       # they only touch
            continue
        rest = o.difference(moved)
        clipped += 1
        if rest.is_empty:
            dropped.append(o)
        else:
            kept.append(rest)
    return kept, clipped, dropped


print()
print("  pushing into the neighbour")
# the top right vertex of A goes from (5,10) to (7,10): A enters B
A_pushed = poly((0, 0), (5, 0), (7, 10), (0, 10))
overlap = A_pushed.intersection(B).area
check("without settling an overlap would be left", overlap > 0, overlap)
kept, clipped, dropped = settle(A_pushed, [B])
check("the neighbour gets clipped", clipped == 1, clipped)
B2 = kept[0]
check("afterwards no area is counted twice",
      A_pushed.intersection(B2).area < 1e-9,
      A_pushed.intersection(B2).area)
check("and the tile stays full: pushing opens no gap",
      abs(A_pushed.area + B2.area - TILE.area) < 1e-9,
      A_pushed.area + B2.area)
check("the neighbour lost exactly what the other one gained",
      abs((B.area - B2.area) - (A_pushed.area - A.area)) < 1e-9)

print()
print("  pulling away from the neighbour")
# the vertex goes from (5,10) to (3,10): A retreats, B does not follow
A_pulled = poly((0, 0), (5, 0), (3, 10), (0, 10))
kept, clipped, dropped = settle(A_pulled, [B])
check("there is nothing to clip", clipped == 0, clipped)
B3 = kept[0]
covered = A_pulled.area + B3.area
hole = TILE.area - covered
check("a gap is left, and not an overlap", hole > 0, hole)
check("the gap is as big as the retreat: 10 m2", abs(hole - 10.0) < 1e-9, hole)
check("no doubled area here either",
      A_pulled.intersection(B3).area < 1e-9)
check("coverage drops to 90%", abs(100 * covered / TILE.area - 90) < 1e-9,
      100 * covered / TILE.area)

print()
print("  a neighbour swallowed whole disappears")
small = poly((5, 0), (6, 0), (6, 1), (5, 1))
big = poly((0, 0), (9, 0), (9, 9), (0, 9))
kept, clipped, dropped = settle(big, [small])
check("it is deleted instead of being left with zero area",
      len(dropped) == 1, len(dropped))

print()
print("  a neighbour cut in two becomes two polygons")
band = poly((4, 0), (6, 0), (6, 10), (4, 10))
blade = poly((0, 4), (10, 4), (10, 6), (0, 6))
rest = band.difference(blade)
pieces = list(getattr(rest, "geoms", [rest]))
check("two pieces are left", len(pieces) == 2, len(pieces))
check("and together they make the right area",
      abs(sum(p.area for p in pieces) - (band.area - 4.0)) < 1e-9)

print()
print("the doughnut: the small one inside the big one")
outer = poly((0, 0), (10, 0), (10, 10), (0, 10))
inner = poly((4, 4), (6, 4), (6, 6), (4, 6))
doughnut = outer.difference(inner)
check("the big one becomes a doughnut with one inner ring",
      len(doughnut.interiors) == 1, len(doughnut.interiors))
check("the net area is the right one, the hole is not counted",
      abs(doughnut.area - (100.0 - 4.0)) < 1e-9, doughnut.area)
check("the small one and the big one never overlap",
      doughnut.intersection(inner).area < 1e-9)
check("and together they cover everything with nothing left over",
      abs(doughnut.area + inner.area - 100.0) < 1e-9)
check("the order they are drawn in does not change the result",
      abs(doughnut.union(inner).area - 100.0) < 1e-9)

print()
print("what the code actually promises")
C = "AnnotationSection"
s = source_of("settle_edits", inside=C)
# Touching along a border means sharing a line, which has no area. The test
# used to ask for the type as well, and that skipped the real case: a vertex
# pushed into a neighbour it shared a border with leaves a collection of the
# wedge and the shared lines, which is not of type polygon. Asked of the area
# alone, a touch is still skipped and a push is no longer.
check("it skips the neighbours that only touch, by the area of what they share",
      "or shared.area() <= 0):" in s)
check("and not by its type, which also skipped every real push",
      "PolygonGeometry" not in s and "GEOM_POLYGON" not in s)
check("it has the guard against re-entering", "_settling" in s)
# The putting back moved into hold_marks(), which also stops QGIS's undo and
# redo; test_hand_edits_run drives a drag, a redo and an undo against the lock.
i_lock = s.find("marks_locked(say=False)")
i_hold = s.find("self.hold_marks()")
check("with the lock closed the vertex is put back",
      0 <= i_lock < i_hold, (i_lock, i_hold))
check("and it says so, instead of leaving a silent overlap",
      "the marks are locked: what moved was put back" in source)
check("it deletes the neighbour left with nothing", "deleteFeature" in s)
check("it puts the detached pieces back in play", "addFeature" in s)
check("it refreshes the coverage at the end", "refresh_coverage" in s)
check("it honours the switch", "settle_edits_on" in s)

w = source_of("keep_vertices_free", inside=C)
check("it puts topological editing back down",
      "setTopologicalEditing(False)" in w)
check("and it tells the user", "pushMessage" in w)

n = source_of("note_geometry_change", inside=C)
check("it defers the work out of the signal", "QTimer.singleShot" in n)
check("it does not react to its own edits", "_settling" in n)

sp = source_of("scope_polygons", inside=C)
check("the gap tool filters by operator",
      "operator_of" in sp and "by_operator" in sp)
ap = source_of("all_polygons", inside=C)
check("all_polygons does not look at the operator",
      "operator" not in ap.split('"""')[2])
af = source_of("apply_filter", inside=C)
check("the renderer filters by operator", "sql_text" in af)
dt = source_of("delete_tile", inside=C)
# It used to say how many of the polygons were hidden, and delete them all the
# same; a frame holding work that is not the operator's own is now refused.
check("a frame holding other work is refused, not confirmed",
      "frame_refusal(" in dt)
sg = source_of("suggest", inside=C)
for k in ["small and sharp", "Fill Gap", "Frame complete", "Pick a class"]:
    check("the next-step line says: %s" % k, k in sg)

# Every bold word in the yellow line has to be a command that really exists
# in the panel. It used to say "+ here", a button gone for versions, and
# whoever went looking for it concluded that the tile size could not be
# chosen at all.
import re as _re
labels = set()
for piece in _re.findall(r'_(?:act|tool|latch|word)\(\s*\n?\s*"([^"]+)"', source):
    labels.add(piece)
# a tick box is a QCheckBox, or a WrapTick, whose words wrap
for piece in _re.findall(r'(?:QCheckBox|WrapTick)\(\s*"([^"]+)"', source):
    labels.add(piece)
for piece in _re.findall(r'_field_box\("([^"]+)"', source):
    labels.add(piece)
labels |= {"Go", "Settings", "Note", "Delete"}
bolds = [g.strip() for g in _re.findall(r"<b>(.*?)</b>", sg)]
check("there are bold words to check", len(bolds) > 4,
      bolds)
for word in bolds:
    if _re.match(r"^\d+\.$", word) or word.endswith("%"):
        continue
    if word.startswith("%"):
        continue
    check("the yellow line names a command that exists: %r" % word,
          word in labels, sorted(labels))
check("'+ here' is gone", "+ here" not in sg)

print()
print("the + button and the campaign roster")
ko = source_of("known_operators", inside=C)
check("it reads the roster from the manifest", '"operators"' in ko)
check("it still honours the old single field", '"operator"' in ko)
check("and the names already in the polygons", "operator_of" in ko)
check("it never comes back empty", 'or ["OPERATOR 1"]' in ko)

ao = source_of("add_operator", inside=C)
check("it asks for the name with a dialog", "QInputDialog.getText" in ao)
check("it refuses the reserved name", "OPERATOR_BLANK" in ao)
check("it upper-cases the name", "tidy_operator" in ao)
check("and the duplicate becomes an exact comparison",
      "in self.known_operators()" in ao)
check("it writes to the manifest", "self.campaign.save()" in ao)
check("and it says so when it cannot", "QMessageBox.warning" in ao)
check("it refreshes the view afterwards", "operator_changed" in ao)

rf = source_of("refill_operator_box", inside=C)
check("it silences the signals while rebuilding",
      "blockSignals(True)" in rf and "blockSignals(False)" in rf)
check("and it puts whoever was drawing back on top",
      "setCurrentText(keep)" in rf)

pi = source_of("person_icon")
canvas = source_of("_canvas")
drawn = source_of("_icon")
check("the icon is drawn, not a file",
      "_icon(size, paint)" in pi and "QPixmap" in canvas
      and "drawEllipse" in pi)
check("and drawn for the pixels of the screen it is on",
      "setDevicePixelRatio" in canvas and "devicePixelRatio()" in drawn)
check("at every ratio, so no Qt scales a drawing",
      "addPixmap" in drawn and "1.0, 2.0" in drawn)
check("and it takes its colour from the theme", "palette_colours" in pi)


def add(names, name):
    """add_operator: the part that decides, without the dialog."""
    name = norm(name) if (name or "").strip() else ""
    if not name or name == "UNNAMED":
        return names, "rejected"
    if name in names:
        return names, "already there"
    return names + [name], "added"


base = ["MASSI"]
for name, expected in [("colleague", "added"), ("  Anna  ", "added"),
                       ("massi", "already there"),
                       ("MASSI", "already there"),
                       ("MaSsI", "already there"), ("", "rejected"),
                       ("   ", "rejected"), ("unnamed", "rejected"),
                       ("UNNAMED", "rejected")]:
    _, outcome = add(base, name)
    check("%-10r -> %s" % (name, expected), outcome == expected, outcome)
final, _ = add(base, " anna maria ")
check("cleaned up and upper-cased", final == ["MASSI", "ANNA MARIA"], final)

up = source_of("upper_as_typed", inside=C)
check("the box transforms while you type", "upper()" in up)
check("and it does not lose the cursor", "setCursorPosition" in up)
check("it calls itself again", "blockSignals" in up)
to = source_of("tidy_operator", inside=C)
check("one single function normalizes", ".strip().upper()" in to)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
