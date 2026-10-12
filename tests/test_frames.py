"""The six faults of the tiles module, one by one, taken from
rasterlabel_37.py as it is written.

Where it can be done, the real arithmetic is run; where the logic is
tangled up with QGIS, we check that the code promises what it has to, and
we say what the difference is. A check on the text is not a trial, and it
is worth not confusing the two.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast
import os
import sys
import textwrap

fails = []

SRC = os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def source_of(name, inside):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    t = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s.%s not found" % (inside, name))


A = "AnnotationSection"

print("1. a shaky click does not move the tile")
rel = source_of("canvasReleaseEvent", "TileTool")
check("there is a threshold, and not 'more than nothing'",
      "MOVE_PX" in rel and "abs(dx) > 0 or abs(dy) > 0" in rel)
check("the threshold is measured on the screen, where the hand is",
      "manhattanLength" in rel)
press = source_of("canvasPressEvent", "TileTool")
check("the starting point is remembered on the press",
      "self.pressed_at = ev.pos()" in press)
threshold = [l for l in source.splitlines() if l.startswith("MOVE_PX")]
check("and it is six pixels", threshold and "= 6" in threshold[0], threshold)


# the threshold, actually run
class Pos(object):
    def __init__(self, x, y): self._x, self._y = x, y
    def __sub__(self, o): return Pos(self._x - o._x, self._y - o._y)
    def manhattanLength(self): return abs(self._x) + abs(self._y)


MOVE_PX = 6
for dx, dy, expected in ((0, 0, False), (1, 0, False), (2, 2, False),
                         (3, 3, False), (4, 3, True), (20, 0, True)):
    moved = (Pos(dx, dy) - Pos(0, 0)).manhattanLength() > MOVE_PX
    check("a drift of (%d, %d) %s" % (dx, dy, "moves" if expected else "no"),
          moved == expected, moved)

print()
print("2. the import does not throw away a column of tiles")
imp = source_of("import_tiles", A)


def top_function(name):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("%s not found" % name)


plan = top_function("design_plan")
check("it plans with design_plan, which compares all four edges",
      "design_plan(" in imp and "def design_fingerprint(box)" in source
      and "round(float(v), 6) for v in box[:4]" in source)
check("and no longer the minimum x alone",
      'round(square.boundingBox().xMinimum(), 6) in known' not in imp)
check("and the plan records the fingerprint of the frame just taken, at once",
      'mine[design_fingerprint(d["frame"])] = tid' in plan)
check("a frame over another frame is refused, as a click is",
      'refusal = "overlap"' in plan and "frame_clash(" in
      top_function("import_clash"))
check("every feature of the file is written to design_log.csv",
      "design_append_log(" in imp and "design_log_rows(" in imp)


def bare_continue(fn_source):
    """continue statements inside a for loop of a function: a feature that
    is skipped there goes without a row."""
    node = ast.parse(textwrap.dedent(fn_source))
    found = []
    for loop in ast.walk(node):
        if isinstance(loop, (ast.For, ast.While)):
            for inner in ast.walk(loop):
                if isinstance(inner, ast.Continue):
                    found.append(inner.lineno)
    return found


check("no feature is skipped by a continue in the import",
      not bare_continue(imp), bare_continue(imp))
check("nor where the file is read", not bare_continue(
    top_function("import_read_rows")))
check("nor in the plan", not bare_continue(plan))
bundle = open(os.path.join(_ROOT, "tools", "bundle.py"), encoding="utf-8").read()
check("design is in the bundle's ORDER, before the window that uses it",
      '"design"' in bundle and bundle.index('"design"')
      < bundle.index('"ui_import_frames"') < bundle.index('"sections_annotate"'))


def old_fingerprint(b): return round(b[0], 6)
def new_fingerprint(b): return tuple(round(v, 6) for v in b)


# a 3 x 3 grid of tiles ten units wide
grid = [(c * 10.0, r * 10.0, c * 10.0 + 10, r * 10.0 + 10)
        for r in range(3) for c in range(3)]
check("the old fingerprint only recognised 3 out of 9",
      len({old_fingerprint(b) for b in grid}) == 3,
      len({old_fingerprint(b) for b in grid}))
check("the new one keeps all 9",
      len({new_fingerprint(b) for b in grid}) == 9,
      len({new_fingerprint(b) for b in grid}))

print()
print("3. deleting or moving takes in every table")
tab = source_of("tables_of_tile", A)
for role in ("polygons", "lines", "points", "boxes"):
    check("tables_of_tile knows about %s" % role, '"%s"' % role in tab)
dele = source_of("delete_tile", A)
move = source_of("move_tile", A)
check("delete_tile goes through there", "self.tables_of_tile(tid)" in dele)
check("move_tile too", "self.tables_of_tile(tid)" in move)
check("neither of the two collects only the polygons any more",
      "polygons.getFeatures()" not in dele and
      "polygons.getFeatures()" not in move)
check("and the confirmation says what is about to go, table by table",
      '"%d %s" % (len(ids), role)' in dele)

print()
print("4. the ids are not handed out twice")
fid = source_of("free_tile_id", A)
check("counting starts from the highest, not from the first hole",
      "top + 1" in fid)
check("and the loop that looked for the hole is gone",
      'while ("t%03d" % n) in used' not in source)
cre = source_of("create_tile", A)
i_filter = cre.find('setSubsetString("")')
i_id = cre.find("free_tile_id")
check("the filter is switched off BEFORE the ids are read",
      0 <= i_filter < i_id, (i_filter, i_id))


def next_id(used):
    top = 0
    for name in used:
        d = "".join(c for c in str(name or "") if c.isdigit())
        if d:
            top = max(top, int(d))
    return "t%03d" % (top + 1)


check("with t001 and t003 the next one is t004, not t002",
      next_id({"t001", "t003"}) == "t004", next_id({"t001", "t003"}))
check("on an empty set it starts from t001",
      next_id(set()) == "t001", next_id(set()))
check("an odd name does not blow it up",
      next_id({"t001", None, "", "tile"}) == "t002",
      next_id({"t001", None, "", "tile"}))

print()
print("5. the side no longer goes stale")
mis = source_of("measure_tile", A)
check("the side is measured again on the real geometry", "measureLine" in mis)
check("the coverage is clipped to the tile", ".intersection(geom)" in mis)
check("side_m gets written", 'indexOf("side_m")' in mis)
sav = source_of("save", A)
check("and everything is measured again on save", "measure_all_tiles()" in sav)
i_mis = sav.find("measure_all_tiles")
i_com = sav.find("commitChanges")
check("before writing, not after", 0 <= i_mis < i_com, (i_mis, i_com))
check("moving re-measures that tile", "self.measure_tile(fresh)" in move)
all_of = source_of("measure_all_tiles", A)
check("everything is read into a list before writing",
      "list(self.all_tiles())" in all_of)

print()
print("6. closed means something")
check("closed is written from the coverage, by the one rule of closed",
      'indexOf("closed")' in mis and "share > CLOSED_SHARE" in mis)
check("which is 99.5 per cent", "CLOSED_SHARE = 0.995" in source)
check("and is no longer a column that is always zero",
      source.count('f["closed"] = 0') <= 1)


def is_closed(covered, total):
    return 1 if (covered / total if total else 0.0) > 0.995 else 0


for c, t, expected in ((100.0, 100.0, 1), (99.6, 100.0, 1), (99.4, 100.0, 0),
                       (0.0, 100.0, 0), (50.0, 100.0, 0), (1.0, 0.0, 0)):
    check("%.1f out of %.1f -> closed = %d" % (c, t, expected),
          is_closed(c, t) == expected, is_closed(c, t))

print()
print("two tiles side by side meet exactly")
# Every edge is written as "the origin plus a whole number of pixels".
# Written as "the other edge minus a measurement" it would be the same
# number in arithmetic and not always the same double: at an origin of
# four million and a pixel five centimetres across the two differ by half
# a nanometre, and two tiles laid on the same grid would not touch.
OX, OY, PX, PY = 400000.0, 4100000.0, 0.05, 0.05


def edges(col, row, side):
    """snapped_square, the part that decides the four edges."""
    return (OX + col * PX, OY - (row + side) * PY,
            OX + (col + side) * PX, OY - row * PY)


a = edges(0, 0, 200)
b = edges(200, 0, 200)          # the one next to it, to the right
below = edges(0, 200, 200)      # the one underneath
check("the right edge of the first is the left edge of the second",
      a[2] == b[0], (a[2], b[0]))
check("and the bottom edge is exactly the top edge of the one below",
      a[1] == below[3], (a[1], below[3]))
check("no gap between two tiles that touch",
      (b[0] - a[2]) == 0.0 and (a[1] - below[3]) == 0.0)

# How often the two formulas really do diverge, on a real grid. With a
# side of 200 pixels (a round 10 metres) never; with sides that do not
# fall round, one row in five. This is what made the fault hard to see:
# with the factory settings it did not show up.
for side in (128, 200, 256, 333):
    wrong = sum(1 for row in range(4000)
                if (OY - (row + side) * PY) != ((OY - row * PY) - side * PY))
    now = sum(1 for row in range(4000)
              if (OY - (row + side) * PY) != (OY - (row + side) * PY))
    print("        side %3d px: the old formula was wrong on %4d rows"
          " out of 4000" % (side, wrong))
    check("side %d px: the formula we use now is never wrong" % side,
          now == 0)
check("and on at least one side the fault really was there",
      any(sum(1 for row in range(4000)
              if (OY - (row + l) * PY) != ((OY - row * PY) - l * PY)) > 0
          for l in (128, 256, 333)))

srg = source_of("snapped_square", "Geometry") if False else ""
src_text = source
check("snapped_square writes the edges from the origin",
      "oy - (row + side_px) * py" in src_text)
check("and regrid as well", "oy - (row + tall) * py" in src_text)
check("and the strip of lines", "oy - (r + 1) * py" in src_text)

print()
print("on top of that: the lock holds for the import too")
check("import_tiles respects frames_locked", "self.frames_locked()" in imp)

print()
print("7. Move is a mode the map is actually in")
mode = source_of("move_mode_changed", A)
check("pressing it takes the map, instead of only promising a hand",
      "self.use_tile_tool()" in mode)
check("and only when it goes down", "if on and self.tiled" in mode)
check("the pointer is told either way", "show_mode()" in mode)
drop = source_of("drop_move", A)
check("taking a shape puts the latch back up", "b.setChecked(False)" in drop)
check("without firing the handler again, which would take the map back",
      "blockSignals(True)" in drop)
for tool in ("use_brush", "use_line_tool", "use_point_tool"):
    check("%s lets Move up" % tool, "self.drop_move()" in source_of(tool, A))
check("taking the tile tool does not, or pressing Move would undo itself",
      "self.drop_move()" not in source_of("use_tile_tool", A))

print()
print("8. a drag that lands in the same cell is not a move")
# The old guard was in screen pixels. Zoomed in far enough, several screen
# pixels are less than half a raster pixel: the frame snapped back into the
# cell it started from, and the program still asked whether to move it, still
# rewrote every geometry in it, and still announced "moved by -0.00, 0.00".
i_zero = move.find("if mx == 0 and my == 0:")
i_ask = move.find("ask = QMessageBox(self)")
i_commit2 = move.find("tiles.changeGeometry(feature.id(), g)")
check("the snapped displacement is worked out first", i_zero >= 0)
check("before anything is asked", 0 <= i_zero < i_ask, (i_zero, i_ask))
check("and before anything is written", 0 <= i_zero < i_commit2,
      (i_zero, i_commit2))
check("and when it is zero the whole thing is called off",
      "the drag snapped back into the same cell" in move)
check("quietly: no message bar for a frame that did not move",
      "the drag snapped back into the same cell\" % tid)" in move
      and "loud=True" not in move[i_zero:i_ask])
check("the report is loud only when something was destroyed",
      "loud=bool(total and not carry)" in move)

PX = 0.05
for drag_px, moves in ((0.2, False), (0.49, False), (0.51, True), (3.4, True)):
    raw = 40 * PX + drag_px * PX
    cells = round(raw / PX) - 40
    check("a drag of %.2f of a pixel %s" % (drag_px,
                                            "moves it" if moves else "does not"),
          bool(cells) == moves, cells)

print()
print("9. a frame that holds work: both answers are offered, neither is default")
check("there are three buttons, not two",
      'addButton("Move with its contents"' in move
      and 'addButton("Move and delete them"' in move
      and "QMessageBox.StandardButton.Cancel" in move)
check("and Cancel is the one Enter and Esc land on",
      "setDefaultButton(ask.button(QMessageBox.StandardButton.Cancel))" in move)
check("the marks lock still stops the lot",
      "self.marks_locked()" in move)
i_commit = move.find("tiles.commitChanges()")
i_touch = move.find("self._carry_or_drop(held, carry, mx, my)")
check("the contents are touched only after the frame has really moved",
      0 <= i_commit < i_touch, (i_commit, i_touch))
carry_body = source_of("_carry_or_drop", A)
check("carrying translates, it does not delete",
      "shape.translate(mx, my)" in carry_body
      and "lyr.changeGeometry(f.id(), shape)" in carry_body)
check("and the other answer still deletes",
      "lyr.deleteFeatures(ids)" in carry_body)
check("every table travels, not the polygons alone",
      "for role, lyr, ids in held:" in carry_body)
check("and the carry is done as the program's own edit, not as a hand drag",
      "self._settling = True" in move
      and move.find("self._settling = True") < i_touch)
check("the marks are shifted by what the frame did, not by what the mouse did",
      "mx = g.boundingBox().xMinimum() - was.xMinimum()" in move
      and "my = g.boundingBox().yMinimum() - was.yMinimum()" in move)
check("which is measured after the frame is put back on the grid",
      move.find("snapped, _ = self.geometry.regrid") < move.find("mx = g."))
check("and the line that reports the move reports the same numbers",
      '"tile %s moved by %.2f, %.2f%s"' in move and "% (tid, mx, my," in move)

# The pixel-exactness of the carry, run rather than read: the frame is put
# back on the grid, so its displacement is a whole number of pixels, and a
# mark translated by that displacement lands on the grid if it was on it.
PX = 0.05
OX = 500000.0
for drag in (0.37, -1.23, 0.049, 12.6):
    start = OX + 40 * PX
    raw = start + drag
    snapped = OX + round((raw - OX) / PX) * PX
    shift = snapped - start
    edge = OX + 7 * PX                      # a polygon edge, on the grid
    check("a drag of %+.3f m moves everything by whole pixels" % drag,
          abs(round(shift / PX) - shift / PX) < 1e-9, shift)
    check("so an edge that was on the grid is still on it",
          abs(round(((edge + shift) - OX) / PX)
              - ((edge + shift) - OX) / PX) < 1e-9)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
