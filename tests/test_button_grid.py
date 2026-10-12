"""The command buttons, all of one size, in columns that follow the width.

Two parts. First the arithmetic of the grid, run on real Qt with the real
buttons of the panel: how many columns at each width, how wide each one is,
where the right edge of the last column falls. Then the whole panel drawn at
several widths, so that the geometries tell us what the eye would see. None of
this is a check on the text of the source.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("RL_SRC", _BUILT)

TRIAL = r'''
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from qtbinding.QtWidgets import QApplication, QWidget, QPushButton
from qtbinding.QtCore import QRect

src = sys.argv[1]
code = open(src, encoding="utf-8").read()

# only the part we need: the constants, text_width/bold_metrics, dress,
# FlowLayout and bar. All the rest of the file wants QGIS.
import ast
tree = ast.parse(code)
lines = code.splitlines(True)
chunks = []
for node in tree.body:
    name = getattr(node, "name", None)
    if isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in (
                    "ICON_H", "PAD", "GROUP_GAP", "FREE_W", "WIDE_CELL",
                    "ICONS", "ICON_PX", "_icon_cache", "TIGHT_PAD"):
                chunks.append("".join(lines[node.lineno - 1:node.end_lineno]))
    if name in ("text_width", "bold_metrics", "dress", "FlowLayout", "bar",
                "theme_icon", "icon_for", "key_height", "button_pad",
                "KeyRow", "keypad", "key_need", "key_least", "menu_room"):
        chunks.append("".join(lines[node.lineno - 1:node.end_lineno]))

from qtbinding.QtWidgets import (QComboBox, QLayout, QMenu, QSizePolicy,
                                 QStyle, QStyleOptionButton, QVBoxLayout)
from qtbinding.QtGui import QFontMetrics, QFont, QIcon
from qtbinding.QtCore import QSize, Qt
g = {"QLayout": QLayout, "QSize": QSize, "QRect": QRect, "Qt": Qt, "QIcon": QIcon,
     "QVBoxLayout": QVBoxLayout,
     "QFontMetrics": QFontMetrics, "QFont": QFont, "QSizePolicy": QSizePolicy,
     "QStyle": QStyle, "QStyleOptionButton": QStyleOptionButton}
app = QApplication([])
exec("\n".join(chunks), g)
FlowLayout, bar, dress = g["FlowLayout"], g["bar"], g["dress"]

fails = []
def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)

def build(words, groups=None, counts=()):
    holder = QWidget()
    wanted = groups or [[w] for w in words]
    rows, i = [], 0
    for group in wanted:
        row = []
        for w in group:
            b = QPushButton(holder)
            dress(b, w)
            row.append(b)
        rows.append(row)
    flow = bar(rows, counts=counts)
    holder.setLayout(flow)
    return holder, flow, [b for row in rows for b in row]

CUT = ["Layers", "Cut", "All tiles", "Whole", "Undo", "Folder"]
holder, flow, buttons = build(CUT)

print("one single cell for all of them")
cell = flow.cell()[0]
widths = sorted({b.minimumWidth() for b in buttons})
check("the cell is the widest button (%d)" % cell,
      cell == max(widths), (cell, widths))
check("no button stays nailed to its own word",
      all(b.maximumWidth() > cell for b in buttons),
      [b.maximumWidth() for b in buttons])

print()
print("the columns follow the width")
seen = []
for room in range(cell, cell * 7, 7):
    cols = flow.columns(room)
    seen.append((room, cols))
    expected = max(1, min(len(CUT),
                          int((room + 4) // (cell + 4))))
    if cols != expected:
        check("at %d px -> %d columns" % (room, expected), False, cols)
check("the column count is always how many fit", not fails)
series = [c for _, c in seen]
check("it never goes back as the panel widens",
      all(b >= a for a, b in zip(series, series[1:])), series)
check("it starts at one", series[0] == 1, series[0])
check("it reaches six and stops there", max(series) == len(CUT), max(series))
for how_many in (2, 3, 4):
    where = [r for r, c in seen if c == how_many]
    check("there is a width with %d columns (%d px)"
          % (how_many, where[0] if where else -1), bool(where))

print()
print("inside a row they are all equal, and the row reaches the edge")
for w in (260, 300, 340, 420, 520, 620, 760, 900):
    holder.setGeometry(QRect(0, 0, w, 400))
    flow.setGeometry(QRect(0, 0, w, 400))
    cols = flow.columns(w)
    geo = [b.geometry() for b in buttons]
    first = geo[:cols]
    sizes = sorted({r.width() for r in first})
    check("%4d px, %d columns: they differ by one pixel at most"
          % (w, cols), sizes[-1] - sizes[0] <= 1, sizes)
    check("%4d px: all of one height" % w,
          len({r.height() for r in geo}) == 1,
          sorted({r.height() for r in geo}))
    check("%4d px: the columns do not touch" % w,
          all(first[i].right() < first[i + 1].left()
              for i in range(len(first) - 1)),
          [(r.left(), r.right()) for r in first])
    inside = all(r.right() <= w for r in geo)
    check("%4d px: nothing spills over" % w, inside,
          [(r.left(), r.right()) for r in geo if r.right() > w])
    # at panel widths the row does fill up: the WIDE_CELL cap only comes
    # into play when a short row gets stretched too far
    cap = int(flow.cell()[0] * g["WIDE_CELL"])
    if first and first[0].width() < cap:
        check("%4d px: the last column ends on the edge" % w,
              abs(first[-1].right() - (w - 1)) <= 1,
              (first[-1].right(), w - 1))

print()
print("a single row on a wide screen does not turn into a banner")
holder2, flow2, two = build(["Undo", "Save"])
holder2.setGeometry(QRect(0, 0, 1900, 100))
flow2.setGeometry(QRect(0, 0, 1900, 100))
cap = int(flow2.cell()[0] * g["WIDE_CELL"])
check("they stop at the cap", all(b.width() <= cap + 1 for b in two),
      [b.width() for b in two])

print()
print("a keypad held to its shape: three columns or six, never four or five")
KEYS = ["New", "Open", "Close", "Classes", "Export", "Check"]
holder3, flow3, keys = build(KEYS, [KEYS[:3], KEYS[3:]], counts=(3, 6))
cell3 = flow3.cell()[0]
counts_seen = sorted({flow3.columns(room)
                      for room in range(cell3 * 3 + 8, cell3 * 8, 5)})
check("only three and six", counts_seen == [3, 6], counts_seen)
check("below three it takes what fits",
      flow3.columns(cell3 * 2 + 4) == 2, flow3.columns(cell3 * 2 + 4))
for w in (cell3 * 3 + 40, cell3 * 5 + 30, cell3 * 6 + 60):
    holder3.setGeometry(QRect(0, 0, w, 200))
    flow3.setGeometry(QRect(0, 0, w, 200))
    right = max(b.geometry().right() for b in keys)
    check("%4d px: the rows meet the edge, however wide the keys get" % w,
          abs(right - (w - 1)) <= 1, (right, w - 1))

print()
print("a short last row is spread over the whole width, never left with a hole")
FIVE = ["New", "Open", "Close", "Classes", "Check"]
holder5, flow5, five = build(FIVE, [FIVE[:3], FIVE[3:]], counts=(3,))
for w in (260, 300, 340, 420, 520):
    holder5.setGeometry(QRect(0, 0, w, 200))
    flow5.setGeometry(QRect(0, 0, w, 200))
    first = [b.geometry() for b in five[:3]]
    last = [b.geometry() for b in five[3:]]
    check("%4d px: three on the first row, two on the second" % w,
          len({r.top() for r in first}) == 1 and len({r.top() for r in last}) == 1
          and last[0].top() > first[0].top())
    check("%4d px: the two share the row equally" % w,
          abs(last[0].width() - last[1].width()) <= 1,
          [r.width() for r in last])
    check("%4d px: and reach both edges, under the first and the last" % w,
          last[0].left() == first[0].left()
          and abs(last[1].right() - first[2].right()) <= 1,
          ([(r.left(), r.right()) for r in first],
           [(r.left(), r.right()) for r in last]))

print()
print("four keys are four in a row or two and two, never three and one")
FOUR = ["Polygon", "Round", "Line", "Points"]
holder4, flow4, four = build(FOUR, [FOUR], counts=(2, 4))
cell4 = flow4.cell()[0]
for room in range(cell4 * 2 + 4, cell4 * 5, 6):
    holder4.setGeometry(QRect(0, 0, room, 200))
    flow4.setGeometry(QRect(0, 0, room, 200))
    per_row = {}
    for b in four:
        per_row.setdefault(b.geometry().top(), []).append(b)
    shape = sorted(len(r) for r in per_row.values())
    if shape not in ([4], [2, 2]):
        check("at %d px the four are %s" % (room, shape), False)
        break
else:
    check("at every width the four are 4 or 2 + 2", True)

print()
print("the keypads: rows that share the width and keep every word whole")
KeyRow, keypad = g["KeyRow"], g["keypad"]
key_need, key_least = g["key_need"], g["key_least"]
holder6 = QWidget()
SHAPE = [["New", "Open", "Close"], ["Classes", "Measure", "Check"]]
rows6 = []
for words in SHAPE:
    row = []
    for w in words:
        b = QPushButton(holder6)
        if w == "Measure":
            # a key with a menu: the style's arrow is part of what it needs
            menu = QMenu(b)
            menu.addAction("x")
            b.setMenu(menu)
        dress(b, w)
        if w == "Measure":
            dressed_measure = b.width()
        row.append(b)
    rows6.append(row)
box6 = keypad(rows6)
holder6.setLayout(box6)
measure = rows6[1][1]
check("a key with a menu is dressed wider by the arrow of its menu",
      dressed_measure == g["text_width"](g["bold_metrics"](measure),
                                         "Measure")
      + g["button_pad"](measure) + g["menu_room"](measure),
      dressed_measure)
check("and needs it", key_need(measure) == g["text_width"](
    measure.fontMetrics(), "Measure") + g["button_pad"](measure)
    + g["menu_room"](measure) and g["menu_room"](measure) > 0,
      (key_need(measure), g["menu_room"](measure)))
needs = [[key_need(b) for b in r] for r in rows6]
leasts = [[key_least(b) for b in r] for r in rows6]
equal_w = max(max(n) * len(n) + 4 * (len(n) - 1) for n in needs)
fitted_w = max(sum(n) + 4 * (len(n) - 1) for n in needs)
tight_w = max(sum(n) + 4 * (len(n) - 1) for n in leasts)
check("the floor under the need is lower, never higher",
      all(l <= n for ln, nn in zip(leasts, needs) for l, n in zip(ln, nn)))
for room in sorted({equal_w + 40, equal_w, fitted_w, tight_w,
                    max(tight_w, fitted_w - 1)}):
    holder6.setGeometry(QRect(0, 0, room, 200))
    box6.setGeometry(QRect(0, 0, room, 200))
    for r, n, l in zip(rows6, needs, leasts):
        geo = [b.geometry() for b in r]
        words = [b.text() for b in r]
        check("%4d px %s: one row" % (room, words),
              len({x.top() for x in geo}) == 1, [x.top() for x in geo])
        check("%4d px %s: from edge to edge" % (room, words),
              geo[0].left() == 0 and abs(geo[-1].right() - (room - 1)) <= 1,
              (geo[0].left(), geo[-1].right(), room))
        check("%4d px %s: in order, never over each other" % (room, words),
              all(geo[i].right() < geo[i + 1].left()
                  for i in range(len(geo) - 1)))
        floor = n if room >= sum(n) + 4 * (len(n) - 1) else l
        check("%4d px %s: no key under what its word needs" % (room, words),
              all(x.width() >= f for x, f in zip(geo, floor)),
              ([x.width() for x in geo], floor))
        if room >= max(n) * len(n) + 4 * (len(n) - 1):
            widths = [x.width() for x in geo]
            check("%4d px %s: equal keys while they fit" % (room, words),
                  max(widths) - min(widths) <= 1, widths)
narrow = tight_w - 30
holder6.setGeometry(QRect(0, 0, narrow, 300))
promised = box6.heightForWidth(narrow) if box6.hasHeightForWidth() else -1
box6.setGeometry(QRect(0, 0, narrow, promised))
lines = sorted({b.geometry().top() for b in rows6[1]})
check("narrower than every word, a row wraps instead of cutting a word",
      len(lines) == 2 and all(b.geometry().right() <= narrow
                              for b in rows6[1]), lines)
bottom = max(b.geometry().bottom() for r in rows6 for b in r) + 1
check("and the keypad says how tall that makes it (%d, takes %d)"
      % (promised, bottom), abs(promised - bottom) <= 1)

holder7 = QWidget()
listing = QComboBox(holder7)
listing.setMinimumWidth(48)
keys7 = []
for w in ("Go", "Note", "Delete"):
    b = QPushButton(holder7)
    dress(b, w)
    keys7.append(b)
same = max(b.width() for b in keys7)
row7 = KeyRow(key_need, 4, filler=True, least=key_least)
row7.add(listing)
for b in keys7:
    b.setFixedWidth(same)
    row7.add(b)
holder7.setLayout(row7)
roomy = 48 + 3 * same + 12 + 60
for room in (roomy, 48 + 3 * max(key_need(b) for b in keys7) + 12,
             48 + sum(key_need(b) for b in keys7) + 12,
             48 + sum(key_least(b) for b in keys7) + 12):
    holder7.setGeometry(QRect(0, 0, room, 60))
    row7.setGeometry(QRect(0, 0, room, 60))
    geo = [listing.geometry()] + [b.geometry() for b in keys7]
    check("%4d px: the list, then Go, Note and Delete, inside the row"
          % room, all(geo[i].right() < geo[i + 1].left() for i in range(3))
          and geo[-1].right() <= room and listing.width() >= 48,
          [(x.left(), x.right()) for x in geo])
    if room == roomy:
        check("%4d px: with room the keys keep the width they were dressed "
              "to, and the list takes the rest" % room,
              {b.width() for b in keys7} == {same}
              and listing.width() == room - 3 * same - 12,
              ([b.width() for b in keys7], listing.width()))

print()
print("the height it declares is the height it then takes up")
for w in (260, 300, 420, 620, 900):
    promised = flow.heightForWidth(w)
    flow.setGeometry(QRect(0, 0, w, 500))
    bottom = max(b.geometry().bottom() for b in buttons) + 1
    check("%4d px: promises %d, takes up %d" % (w, promised, bottom),
          abs(promised - bottom) <= 1)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
'''

path = os.path.join(HERE, "_griglia.py")
open(path, "w").write(TRIAL)
outcome = subprocess.run([sys.executable, path, SRC], cwd=HERE)

# ---- and now the real panel, read off its geometries
READOUT = r'''
from qtbinding.QtWidgets import QPushButton
rows = {}
for b in panel.findChildren(QPushButton):
    if not b.isVisible() or b.height() < 2:
        continue
    p = b.mapTo(panel, b.rect().topLeft())
    rows.setdefault((b.parent(), p.y()), []).append(
        (p.x(), b.width(), b.text()))
for (parent, y), row in sorted(rows.items(), key=lambda kv: kv[0][1]):
    if len(row) < 2:
        continue
    widths = sorted({w for _, w, _ in row})
    print("ROW %2d  %-2d columns  widths %s  %s"
          % (y, len(row), widths,
             " ".join(t for _, _, t in sorted(row))))
'''
open(os.path.join(HERE, "_leggi.py"), "w").write(READOUT)

print()
print("the real panel, row by row")
ragged = 0
for w in (300, 340, 420, 560, 760):
    code = open(os.path.join(HERE, "harness2.py")).read()
    code = code.replace('panel.grab().save(out)',
                        'exec(open(r"%s").read())'
                        % os.path.join(HERE, "_leggi.py"))
    run = os.path.join(HERE, "_run_griglia.py")
    open(run, "w").write(code)
    env = dict(os.environ, RL_SRC=SRC)
    out = subprocess.run([sys.executable, run, str(w), "cutouts"],
                         capture_output=True, text=True, cwd=HERE, env=env)
    print("  --- %d px" % w)
    for line in out.stdout.splitlines():
        if line.startswith("ROW"):
            print("   " + line)
            widths = line.split("widths [")[1].split("]")[0]
            numbers = [int(n) for n in widths.split(",")]
            if max(numbers) - min(numbers) > 1:
                ragged += 1
                print("      NOT UNIFORM")
print()
print("ragged rows: %d" % ragged)
sys.exit(1 if (outcome.returncode or ragged) else 0)
