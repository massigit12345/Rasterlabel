"""The boxes are in the order the work is in, and the short rows fill the bar.

Two things, and both are about the hand rather than the eye.

The order first. On a tiled campaign nothing can be drawn until a frame has
been placed and picked up, so FRAME is the first group, with the frame in
hand right under Tiles and Move, and the two locks sit directly under it;
then what leaves a mark, then what mends it, then Save. A panel whose groups
are in a different order from the work makes everybody read it top to bottom
every time instead of reaching.

Then the width. The groups that hold one or two buttons give them the whole
bar: half each for Tiles and Move, half each for Frames and Marks, all of it
for Save. A group of four is four equal keys in a row, or two rows of two,
never three and one. A button dressed to the width of its own word floats
somewhere in a wide bar and has to be aimed at; a button that is half the bar
is always in the same place and can be hit without looking. Fitts's law is
not a matter of taste.

Then the blocks of the panel itself, which are the same claim one level up:
the annotation campaign's line, its keys in rows of three, two and two with
Measure just before Check, and Annotate and Objects side by side as halves of
the bar; then CORRECTION, whose own New, Open and Close stand exactly under
the campaign's, its line, its Classes, Measure and Check sharing their row,
and Correct across the bar; then Cutouts across the bar on its
own; then VIEW, one low row with the button that detaches the panel in it.
While a module is open it sits right under the block that owns it, and the
other blocks fold to one line: their name, what they hold, and an arrow.
Measured with nothing open, with the campaign open, with a correction open
in Correct, with both, and with each module.

The panel is built for real, at several widths, with only QGIS stubbed under
it, because this is a claim about geometry and geometry has to be measured.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHILD = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
TEXT = {"encoding": "utf-8", "errors": "replace"}

CHECK = r'''
from qtbinding.QtWidgets import QPushButton, QComboBox, QLabel

def find(word):
    for b in section.findChildren(QPushButton):
        if b.text() == word and b.isVisible():
            return b
    return None

def top(w):
    return w.mapTo(section, w.rect().topLeft()).y()

def left(w):
    return w.mapTo(section, w.rect().topLeft()).x()

bad = []
names = ["Tiles", "Move", "Frames", "Marks", "Polygon", "Round", "Line",
         "Points", "Vertices", "Fill Gap", "Repair", "Undo", "Save", "Go",
         "Note", "Delete"]
found = {n: find(n) for n in names}
missing = [n for n, b in found.items() if b is None]
if missing:
    bad.append("not on the panel: %s" % ", ".join(missing))
else:
    order = ["Tiles", "Go", "Frames", "Polygon", "Vertices", "Save"]
    ys = [top(found[n]) for n in order]
    for i in range(len(order) - 1):
        if not ys[i] < ys[i + 1]:
            bad.append("%s (y=%d) is not above %s (y=%d)"
                       % (order[i], ys[i], order[i + 1], ys[i + 1]))
    # the frame in hand: its list, then Go, Note and Delete, on one row
    # under Tiles and Move, Delete last
    tiles = section.tiles
    row = [found[n] for n in ("Go", "Note", "Delete")]
    if len({top(b) for b in row}) != 1 or abs(top(tiles) - top(row[0])) > 3:
        bad.append("the frame in hand is not one row")
    if not left(tiles) < left(row[0]) < left(row[1]) < left(row[2]):
        bad.append("the frame row is not list, Go, Note, Delete")
    # the pairs: same row, same width, and between them the whole bar
    for a, b in (("Tiles", "Move"), ("Frames", "Marks")):
        wa, wb = found[a], found[b]
        if top(wa) != top(wb):
            bad.append("%s and %s are not on the same row" % (a, b))
        if abs(wa.width() - wb.width()) > 2:
            bad.append("%s is %dpx and %s is %dpx: not halves"
                       % (a, wa.width(), b, wb.width()))
        box = wa.parentWidget()
        span = (left(wb) + wb.width()) - left(wa)
        if span < box.width() - 14:
            bad.append("%s and %s span %d of a %dpx box"
                       % (a, b, span, box.width()))
    save = found["Save"]
    box = save.parentWidget()
    if save.width() < box.width() - 14:
        bad.append("Save is %dpx in a %dpx box" % (save.width(), box.width()))
    if save.height() <= found["Undo"].height():
        bad.append("Save is no taller than the keys")
    # the groups of four: one row of four, or two rows of two, all equal
    for group in (("Polygon", "Round", "Line", "Points"),
                  ("Vertices", "Fill Gap", "Repair", "Undo")):
        keys = [found[n] for n in group]
        rows = sorted({top(k) for k in keys})
        widths = sorted({k.width() for k in keys})
        if len(rows) not in (1, 2) or widths[-1] - widths[0] > 1:
            bad.append("%s: %d rows, widths %s" % (group[0], len(rows), widths))
        if len(rows) == 2 and [sum(1 for k in keys if top(k) == y)
                               for y in rows] != [2, 2]:
            bad.append("%s is not two and two" % group[0])
    # and none of them is still nailed to the width of its own word
    for n in ("Tiles", "Move", "Frames", "Marks", "Save"):
        b = found[n]
        if b.minimumWidth() == b.maximumWidth():
            bad.append("%s is still a fixed width" % n)
for line in bad:
    print("   BAD", line)
print("VERDICT", "bad" if bad else "clean", panel.width())
'''

open(os.path.join(HERE, "_order.py"), "w", encoding="utf-8").write(CHECK)

BLOCKS = r'''
from qtbinding.QtWidgets import QPushButton, QLabel
bad = []

def at(w):
    p = w.mapTo(panel, w.rect().topLeft())
    return p.x(), p.y(), w.width(), w.height()

def card_of(w):
    while w is not None and w not in panel.cards:
        w = w.parentWidget()
    return w

ann, cor, obj, cut = panel.modules
campaign_keys = [panel.b_new, panel.b_open, panel.b_close, panel.b_classes,
                 panel.b_export, panel.b_measure, panel.b_check]
correction_keys = [panel.c_new, panel.c_open, panel.c_close,
                   panel.c_classes, panel.c_measure, panel.c_check]
# While a module is open, the blocks that do not own it fold to one line:
# their name, what they hold beside it, and an arrow. Everything else in
# them, the line under the name, the keys and the module buttons, goes.
owner = None if panel.section is None else \
    {0: 1, 1: 2, 2: 1, 3: 3}.get(panel.open_index)
own = {1: [panel.campaign_state, ann, obj] + campaign_keys,
       2: [panel.correction_state, cor] + correction_keys,
       3: [panel.cutouts_state, cut]}
for block, widgets in own.items():
    card = panel.folds[block][0]
    folded = owner is not None and owner != block
    shown = [w for w in widgets if w.isVisible()]
    if folded:
        if shown:
            bad.append("block %d is folded but shows %s" % (
                block, [getattr(w, "text", lambda: "?")()[:12] for w in shown]))
        if not (card.aside.isVisible() and card.toggle.isVisible()):
            bad.append("block %d folded without its line and its arrow" % block)
        if card.height() > 26:
            bad.append("block %d is %d px tall folded: not one line"
                       % (block, card.height()))
        # Folded, the line leaves out what the name of the block already
        # says: 'no annotation campaign open' was cut to 'no annotati…'
        # beside ANNOTATION CAMPAIGN at 260 pixels.
        if block == 1:
            want = "none open" if panel.campaign is None else \
                "aragona_2025 · %d classes" % len(
                    panel.campaign.active_classes())
        elif block == 2:
            want = "none open" if panel.correction is None else \
                "landcover_fix · %d classes" % len(
                    panel.correction.data["classes"])
        else:
            want = "saves no campaign"
        if card.aside.full_text() != want:
            bad.append("block %d folded says %r, not %r"
                       % (block, card.aside.full_text(), want))
        if not card.aside.toolTip():
            bad.append("block %d folded has no tooltip" % block)
    else:
        if len(shown) != len(widgets):
            bad.append("block %d hides %s" % (block, [
                getattr(w, "text", lambda: "?")()[:12] for w in widgets
                if not w.isVisible()]))
        if card.aside.isVisible():
            bad.append("block %d is open and still says its line twice" % block)
# top to bottom, in the order of the work
order = []
if owner in (None, 1):
    order += [("campaign line", panel.campaign_state),
              ("campaign keys", panel.b_new), ("Annotate", ann)]
if owner in (None, 2):
    order += [("correction line", panel.correction_state),
              ("correction keys", panel.c_new), ("Correct", cor)]
if owner in (None, 3):
    order += [("cutouts line", panel.cutouts_state), ("Cutouts", cut)]
for (na, a), (nb, b) in zip(order, order[1:]):
    if not at(a)[1] + at(a)[3] <= at(b)[1]:
        bad.append("%s is not above %s" % (na, nb))
# the cards in their order, and the module straight under its owner
plan = [0, 1, 2, 3, 5]
if owner is not None:
    plan.insert(plan.index(owner) + 1, 4)
tops = [at(panel.cards[i])[1] for i in plan if panel.cards[i].isVisible()]
if tops != sorted(tops):
    bad.append("the cards are not stacked in their order: %s" % tops)
if owner is not None:
    body = panel.body
    under = panel.cards[owner]
    if not body.isVisible():
        bad.append("the module is not shown")
    elif at(body)[1] < at(under)[1] + at(under)[3] or \
            at(body)[1] - (at(under)[1] + at(under)[3]) > 24:
        bad.append("the module is not right under its block (%d, %d)"
                   % (at(under)[1] + at(under)[3], at(body)[1]))
elif panel.body.isVisible():
    bad.append("an empty module card is shown")
# Annotate and Objects: one row, halves of their block
if owner in (None, 1):
    box = card_of(ann).width()
    xa, ya, wa, ha = at(ann)
    xo, yo, wo, ho = at(obj)
    if ya != yo:
        bad.append("Annotate and Objects are not on one row")
    if abs(wa - wo) > 2:
        bad.append("Annotate %d and Objects %d are not halves" % (wa, wo))
    if (xo + wo) - xa < box - 2:
        bad.append("Annotate and Objects span %d of %d" % ((xo + wo) - xa, box))
    if ha <= panel.b_new.height():
        bad.append("the module buttons are no taller than the keys")
# Correct and Cutouts across their blocks
for name, b, block in (("Correct", cor, 2), ("Cutouts", cut, 3)):
    if owner in (None, block) and b.width() < card_of(b).width() - 2:
        bad.append("%s is %d in a block of %d"
                   % (name, b.width(), card_of(b).width()))
# the two keypads in the same columns, and every row of keys reaching both
# edges: no hole where a key is not
if owner is None:
    for a, b in ((panel.b_new, panel.c_new), (panel.b_open, panel.c_open),
                 (panel.b_close, panel.c_close)):
        if at(a)[0] != at(b)[0] or abs(a.width() - b.width()) > 1:
            bad.append("%s of CORRECTION is not under the campaign's (%s, %s)"
                       % (b.text(), at(a), at(b)))
    # The keypads, row by row: the campaign's three, two and two, the
    # correction's three and three, Measure always just before Check and
    # Check ending the keypad. Every row meets both edges of its block;
    # its keys are equal whenever an equal share holds every word, and
    # never narrower than their word (and the arrow of Measure's menu).
    def rows_of(keys):
        by_y = {}
        for b in keys:
            by_y.setdefault(at(b)[1], []).append(b)
        return [sorted(r, key=lambda b: at(b)[0])
                for _, r in sorted(by_y.items())]

    def word_room(b):
        return (g["text_width"](b.fontMetrics(), b.text())
                + g["menu_room"](b) + 4)

    for name, keys, shape in (
            ("ANNOTATION CAMPAIGN", campaign_keys,
             [["New", "Open", "Close"], ["Classes", "Export"],
              ["Measure", "Check"]]),
            ("CORRECTION", correction_keys,
             [["New", "Open", "Close"], ["Classes", "Measure", "Check"]])):
        rows = rows_of(keys)
        words = [[b.text() for b in r] for r in rows]
        if words != shape:
            bad.append("the keys of %s are %s, not %s" % (name, words, shape))
            continue
        card = card_of(keys[0])
        left_edge = at(card)[0]
        right_edge = left_edge + card.width()
        for r in rows:
            x0 = at(r[0])[0]
            x1 = at(r[-1])[0] + r[-1].width()
            if abs(x0 - left_edge) > 1 or abs(x1 - right_edge) > 2:
                bad.append("%s: the row %s runs %d to %d in a block of %d "
                           "to %d" % (name, [b.text() for b in r], x0, x1,
                                      left_edge, right_edge))
            for b in r:
                if b.width() < word_room(b):
                    bad.append("%s: %s is %d px, its word needs %d"
                               % (name, b.text(), b.width(), word_room(b)))
            span = x1 - x0 - 4 * (len(r) - 1)
            fits = max(g["key_need"](b) for b in r) * len(r) <= span
            widths = [b.width() for b in r]
            if fits and max(widths) - min(widths) > 1:
                bad.append("%s: the row %s is not of equal keys: %s"
                           % (name, [b.text() for b in r], widths))
            if len({at(b)[1] for b in r}) != 1:
                bad.append("%s: a row of keys is not one row" % name)
    if panel.b_measure.menu() is None or panel.c_measure.menu() is None:
        bad.append("a Measure key has no menu")
# VIEW: one low row, the pad and then the step, the keyboard and Detach
view = panel.cards[5]
pad_keys = [b for b in view.findChildren(QPushButton)
            if b is not panel.b_float and b.isVisible()]
if card_of(panel.b_float) is not view:
    bad.append("Detach is not in VIEW")
if len(pad_keys) != 7:
    bad.append("VIEW has %d keys besides Detach" % len(pad_keys))
low = max(at(b)[1] + at(b)[3] for b in pad_keys)
right = max(at(b)[0] + at(b)[2] for b in pad_keys)
if at(panel.b_float)[1] >= low or at(panel.step)[0] < right:
    bad.append("the step, the keyboard and Detach are not beside the pad")
if view.height() > 180:
    bad.append("VIEW is %d px tall" % view.height())
words = [l.text() for l in view.findChildren(QLabel) if l.isVisible()]
if not any("PgUp" in w for w in words):
    bad.append("VIEW does not say what the keyboard does")
if any(c is not None and getattr(c, "objectName", lambda: "")() == "PANEL"
       for c in panel.cards):
    bad.append("a PANEL block is still there")
# the lines say what is open
want = "no correction open" if panel.correction is None else "landcover_fix"
if want not in panel.correction_state.text():
    bad.append("CORRECTION says %r" % panel.correction_state.text())
want = "no annotation campaign open" if panel.campaign is None \
    else "aragona_2025"
if want not in panel.campaign_state.text():
    bad.append("the campaign line says %r" % panel.campaign_state.text())
# the arrow of a folded block opens it, and closes it again
if owner is not None:
    other = [b for b in (1, 2, 3) if b != owner][0]
    card = panel.folds[other][0]
    card.toggle.click()
    app.processEvents()
    opened = all(w.isVisible() for w in own[other]) and not card.aside.isVisible()
    card.toggle.click()
    app.processEvents()
    closed = not any(w.isVisible() for w in own[other])
    if not (opened and closed):
        bad.append("the arrow of block %d does not unfold it and fold it back"
                   % other)
    # and so does a click anywhere on its line, as on QGIS's own groups
    try:
        import importlib
        from qtbinding import PyQt
        from qtbinding.QtCore import QPoint, Qt
        QTest = importlib.import_module(PyQt.__name__ + ".QtTest").QTest
    except Exception:
        QTest = None
    if QTest is not None:
        head = card.head
        QTest.mouseClick(head, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(4, head.height() // 2))
        app.processEvents()
        opened = all(w.isVisible() for w in own[other])
        QTest.mouseClick(head, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier,
                         QPoint(4, head.height() // 2))
        app.processEvents()
        closed = not any(w.isVisible() for w in own[other])
        if not (opened and closed):
            bad.append("a click on the line of block %d does not unfold it"
                       % other)
for line in bad:
    print("   BAD", line)
print("VERDICT", "bad" if bad else "clean", panel.width())
'''
open(os.path.join(HERE, "_blocks.py"), "w", encoding="utf-8").write(BLOCKS)

WIDTHS = [260, 300, 380, 520, 700, 960]
fails = []


def run(check, args):
    code = open(os.path.join(HERE, "harness2.py"), encoding="utf-8").read()
    code = code.replace('panel.grab().save(out)',
                        'exec(open(r"%s", encoding="utf-8").read())'
                        % os.path.join(HERE, check))
    path = os.path.join(HERE, "_run_order.py")
    open(path, "w", encoding="utf-8").write(code)
    out = subprocess.run([sys.executable, path] + args,
                         capture_output=True, cwd=HERE, env=CHILD, **TEXT)
    text = out.stdout + out.stderr
    verdict = [l for l in text.splitlines() if l.startswith("VERDICT")]
    return bool(verdict) and verdict[0].split()[1] == "clean", text


def show(text):
    for line in text.splitlines():
        if line.strip().startswith(("BAD", "Traceback", "  File")) \
                or "Error" in line:
            print("          " + line.strip()[:160])


print("the groups of the annotation module")
for w in WIDTHS:
    ok, text = run("_order.py", [str(w), "annotation"])
    print(("  ok   " if ok else "  FAIL ") + "at %d pixels wide" % w)
    if not ok:
        fails.append(w)
        show(text)

print()
print("the blocks")
# A correction is open only while Correct is, so the two states with one
# open have Correct open under CORRECTION.
STATES = [(["none", "free"], "nothing open"), (["none"], "campaign open"),
          (["correction", "free"], "correction open"),
          (["correction", "corrected"], "both open, in Correct"),
          (["annotation"], "Annotate"), (["objects"], "Objects"),
          (["cutouts"], "Cutouts"), (["annotation", "thirty"],
                                     "Annotate, thirty classes"),
          # Cutouts the first thing opened on a new panel, no campaign ever
          # opened: the campaign's folded line was empty
          (["cutouts", "free", "fresh"], "Cutouts first, fresh panel"),
          # Night Mapping pads every button and widens every spin box: the
          # VIEW row still has to hold at the narrowest
          (["none", "free", "night"], "nothing open, Night Mapping"),
          (["annotation", "night"], "Annotate, Night Mapping")]
for args, name in STATES:
    for w in (260, 300, 340, 380, 420, 520):
        ok, text = run("_blocks.py", [str(w)] + args)
        print(("  ok   " if ok else "  FAIL ") + "%s, %d pixels wide"
              % (name, w))
        if not ok:
            fails.append("%s at %d" % (name, w))
            show(text)

for leftover in ("_order.py", "_blocks.py", "_run_order.py"):
    try:
        os.remove(os.path.join(HERE, leftover))
    except OSError:
        pass

print()
print("FAILED at %s" % fails if fails else "all pass")
sys.exit(1 if fails else 0)
