"""Sweep every module across every width and check that nothing is drawn on
top of anything else, nothing is cut off and no key is left alone on a row.
The panel is built for real; only QGIS underneath it is stubbed.

Three more things, about the look rather than the geometry. The stylesheet
must never name a combo box, a spin box, a line edit or a tick box, and must
paint a button only in a state: a rule that reaches the normal state of one
of them makes Qt draw it through the stylesheet, which took the arrows off
every spin box under Fusion and turned every button into a light slab in
Night Mapping. A button that cannot be pressed must read as one, plainly
fainter than one that can, in the light theme and in Night Mapping. And the
blocks a module does not belong to fold to one line.

And every control of the panel and of the module that is open can be
reached with Tab: the keys of a module used to be out of the chain, and the
keyboard stopped at the module and jumped to VIEW. Where the windows11 style
is there (Qt 6.7 and later, as QGIS 4 has it on Windows 11), the sweep runs
under it too: it keeps more room in a button and a number box than Fusion,
and widths written in for Fusion cut its words."""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The keys of the panel carry arrows and a minus sign, and a child that
# prints one into a cp1252 pipe dies on it: the children write UTF-8 and the
# pipes are read as UTF-8, whatever the console is.
CHILD = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
TEXT = {"encoding": "utf-8", "errors": "replace"}
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass
CHECK = r'''
from qtbinding.QtWidgets import (QPushButton, QLabel, QCheckBox, QComboBox,
                             QSpinBox, QDoubleSpinBox, QLineEdit, QToolButton,
                             QSlider)
KINDS = (QPushButton, QLabel, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox,
         QLineEdit, QToolButton, QSlider)

def leaves(w):
    out = []
    for child in w.findChildren(KINDS):
        if not child.isVisible() or child.width() < 2 or child.height() < 2:
            continue
        if child.findChildren(KINDS):
            continue
        r = child.rect()
        p = child.mapTo(panel, r.topLeft())
        out.append((child, p.x(), p.y(), child.width(), child.height()))
    return out

def text_width(fm, words):
    try:
        return fm.horizontalAdvance(words)
    except AttributeError:
        return fm.width(words)

bad = []
items = leaves(panel)
for i in range(len(items)):
    a, ax, ay, aw, ah = items[i]
    if ax < 0 or ay < 0 or ax + aw > panel.width() + 1:
        bad.append("outside the panel: %r %s" % (a.__class__.__name__,
                                                 (ax, ay, aw, ah)))
    for j in range(i + 1, len(items)):
        b, bx, by, bw, bh = items[j]
        if a.parent() is not b.parent():
            continue
        ox = min(ax + aw, bx + bw) - max(ax, bx)
        oy = min(ay + ah, by + bh) - max(ay, by)
        if ox > 2 and oy > 2:
            bad.append("%s %r over %s %r" % (a.__class__.__name__, a.text()[:18]
                       if hasattr(a, "text") else "", b.__class__.__name__,
                       b.text()[:18] if hasattr(b, "text") else ""))
# A tick box does not wrap its words: given less than it needs, it cuts them
# off at the edge without a sign, and nothing above catches it because
# nothing overlaps. A button is the same, and so is a label that does not
# wrap, unless it is one of the lines that cut themselves with an ellipsis.
for box in panel.findChildren(QCheckBox):
    if box.isVisible() and box.text() and \
            box.sizeHint().width() > box.width() + 1:
        bad.append("cut off: %r needs %d, has %d"
                   % (box.text(), box.sizeHint().width(), box.width()))
for b in panel.findChildren(QPushButton):
    if not b.isVisible() or not b.text():
        continue
    need = text_width(b.fontMetrics(), b.text()) + (
        0 if b.icon().isNull() else b.iconSize().width() + 4)
    if need + 4 > b.width() or b.fontMetrics().height() + 2 > b.height():
        bad.append("cut off: the button %r needs %d x %d, has %d x %d"
                   % (b.text(), need + 4, b.fontMetrics().height() + 2,
                      b.width(), b.height()))
for lab in panel.findChildren(QLabel):
    if not lab.isVisible() or lab.wordWrap() or not lab.text() \
            or "<" in lab.text() or not lab.text().strip():
        continue
    if lab.sizePolicy().horizontalPolicy() == \
            lab.sizePolicy().Policy.Ignored:
        continue                        # one of the lines cut to the width
    if text_width(lab.fontMetrics(), lab.text()) > lab.contentsRect().width() + 2:
        bad.append("cut off: the label %r" % lab.text()[:30])
# No key alone on a row with the edge of its row a cell away: in a row of
# equal keys, a short last row spreads over the whole width, and a group of
# four is four in a row or two and two, never three and one.
# Class chips and the keys of the pad that moves the view are not keys of a
# row: they sit in grids of their own, where a last chip alone is the end of
# a legend and the pad is a cross on purpose.
from qtbinding.QtWidgets import QGridLayout, QLayout
in_grid = set()
for grid in panel.findChildren(QGridLayout):
    for k in range(grid.count()):
        w = grid.itemAt(k).widget()
        if w is not None:
            in_grid.add(id(w))
rows = {}
for b in panel.findChildren(QPushButton):
    if not b.isVisible() or b.width() < 2 or id(b) in in_grid:
        continue
    p = b.mapTo(panel, b.rect().topLeft())
    rows.setdefault(b.parentWidget(), {}).setdefault(p.y(), []).append(
        (p.x(), b.width(), b.text()))
for parent, by_y in rows.items():
    if len(by_y) < 2:
        continue
    spans = {y: (min(x for x, _, _ in r), max(x + w for x, w, _ in r))
             for y, r in by_y.items()}
    widest = max(right - left for left, right in spans.values())
    for y, r in by_y.items():
        left, right = spans[y]
        if len(r) == 1 and right - left < widest - 8 and \
                max(len(o) for o in by_y.values()) > 1:
            bad.append("alone on its row: %r (%d of %d px)"
                       % (r[0][2], right - left, widest))
for line in bad[:6]:
    print("   OVERLAP", line)
print("VERDICT", "bad" if bad else "clean", panel.width(), panel.height())
'''

open(os.path.join(HERE, "_check.py"), "w").write(CHECK)

WIDTHS = [260, 280, 300, 340, 420, 520, 620, 700, 820, 960, 1100, 1300,
          1500, 1700, 1900]
CASES = [("harness2.py", ["{w}", "annotation"], "annotate"),
         ("harness2.py", ["{w}", "annotation", "settings"], "annotate+settings"),
         ("harness2.py", ["{w}", "annotation", "line", "settings"], "annotate line"),
         ("harness2.py", ["{w}", "annotation", "points", "settings"], "annotate points"),
         # thirty classes, the longest names a land cover has
         ("harness2.py", ["{w}", "annotation", "thirty"], "annotate thirty"),
         ("harness2.py", ["{w}", "correction", "settings"], "correction"),
         ("harness2.py", ["{w}", "objects", "settings"], "objects"),
         ("harness2.py", ["{w}", "objects", "thirty"], "objects thirty"),
         ("harness2.py", ["{w}", "cutouts", "settings"], "cutouts"),
         ("harness2.py", ["{w}", "cutouts", "free", "settings"], "cutouts free"),
         # the three blocks on their own: nothing open, the annotation
         # campaign open, a correction open with its module closed, and both
         ("harness2.py", ["{w}", "none", "free"], "nothing open"),
         ("harness2.py", ["{w}", "none", "free", "bare"], "no raster"),
         ("harness2.py", ["{w}", "none"], "campaign open"),
         ("harness2.py", ["{w}", "none", "free", "corrected"],
          "correction open"),
         ("harness2.py", ["{w}", "annotation", "corrected"], "both open"),
         ("harness2.py", ["{w}", "correction", "corrected", "settings"],
          "both, in Correct"),
         # and in QGIS's dark theme, whose stylesheet pads every button
         ("harness2.py", ["{w}", "annotation", "night", "settings"],
          "annotate, Night"),
         ("harness2.py", ["{w}", "correction", "free", "night"],
          "Correct, Night")]
NIGHT_WIDTHS = [260, 300, 340, 420, 520]
try:
    sys.path.insert(0, HERE)
    from qtbinding import QtWidgets as _QtW
    STYLES = [k for k in _QtW.QStyleFactory.keys() if k.lower() == "windows11"]
except Exception:
    STYLES = []
for _style in STYLES:
    CASES += [("harness2.py", ["{w}", "annotation", "settings",
                               "style=" + _style], "annotate, " + _style),
              ("harness2.py", ["{w}", "correction", "corrected", "settings",
                               "style=" + _style], "Correct, " + _style),
              ("harness2.py", ["{w}", "none", "free", "style=" + _style],
               "nothing open, " + _style)]

bad = 0
runs = 0
for script, args, name in CASES:
    for w in (NIGHT_WIDTHS if "night" in args
              or any(a.startswith("style=") for a in args) else WIDTHS):
        runs += 1
        code = open(os.path.join(HERE, script)).read()
        code = code.replace('panel.grab().save(out)',
                            'exec(open(r"%s").read())'
                            % os.path.join(HERE, "_check.py"))
        path = os.path.join(HERE, "_run.py")
        open(path, "w").write(code)
        out = subprocess.run([sys.executable, path] + [a.format(w=w) for a in args],
                             capture_output=True, cwd=HERE, env=CHILD, **TEXT)
        lines = [l for l in (out.stdout + out.stderr).splitlines()
                 if "VERDICT" in l or "OVERLAP" in l or "Traceback" in l]
        verdict = [l for l in lines if "VERDICT" in l]
        if not verdict or "clean" not in verdict[0]:
            bad += 1
            print("%-20s %5d  %s" % (name, w, " | ".join(lines) or "no verdict"))
            print((out.stdout + out.stderr)[-600:] if not verdict else "")
        else:
            print("%-20s %5d  ok  %s" % (name, w, verdict[0].split("clean")[1]))
print()

# ---------------------------------------------------------------- the look
LOOK = r'''
import re
from qtbinding.QtWidgets import QPushButton
NEVER = ("QComboBox", "QSpinBox", "QDoubleSpinBox", "QLineEdit", "QCheckBox",
         "QAbstractSpinBox", "QRadioButton")
problems = []
for name in ("stylesheet", "label_sheet"):
    sheet = re.sub(r"/\*.*?\*/", "", g[name](), flags=re.S)
    for head in re.findall(r"([^{}]+)\{", sheet):
        for selector in head.split(","):
            selector = selector.strip()
            base = re.split(r"[:\[#\s.]", selector)[0]
            if base in NEVER:
                problems.append("%s names %s" % (name, selector))
            if base == "QPushButton" and selector == "QPushButton":
                problems.append("%s paints every button: %s" % (name, selector))
            if base == "QPushButton" and ":" not in selector \
                    and "[" not in selector and "#" not in selector:
                problems.append("%s paints the normal button: %s"
                                % (name, selector))
for p in problems:
    print("   LOOK", p)

def ink(button):
    """How far the words of a button stand from what is behind them: the
    colour most of the button is filled with against the pixel of the
    words that is furthest from it."""
    # cut out of the whole panel, so the button stands on what the panel
    # paints under it and not on a background of its own
    corner = button.mapTo(panel, button.rect().topLeft())
    image = SHOT.copy(QtCore.QRect(corner.x(), corner.y(), button.width(),
                                   button.height()))
    counts = {}
    for y in range(2, image.height() - 2):
        for x in range(2, image.width() - 2):
            c = image.pixel(x, y)
            counts[c] = counts.get(c, 0) + 1
    ground = max(counts, key=counts.get)
    fill = QtGui.QColor(ground)
    best = 1.0
    for c in counts:
        best = max(best, g["contrast"](QtGui.QColor(c), fill))
    return best, fill.name()

SHOT = panel.grab().toImage()
on = [b for b in (panel.b_open, panel.c_open, panel.b_check)
      if b.isVisible() and b.isEnabled()]
off = [b for b in (panel.b_close, panel.c_close, panel.c_check, panel.b_export)
       if b.isVisible() and not b.isEnabled()]
if not on or not off:
    print("   LOOK no pair to compare")
else:
    lit = min(ink(b)[0] for b in on)
    grey = max(ink(b)[0] for b in off)
    print("CONTRAST enabled %.2f, disabled %.2f" % (lit, grey))
    if not grey * 1.5 <= lit:
        print("   LOOK a grey button reads almost as a live one: %.2f against %.2f"
              % (grey, lit))
    # and a grey button has no slab of its own: it stands on the panel
    window = g["palette_colours"]()["window"]
    for b in off:
        level, fill = ink(b)
        if g["contrast"](fill, window) > 1.25:
            print("   LOOK %r is a slab of %s on %s" % (b.text(), fill, window))
print("LOOKED")
'''
open(os.path.join(HERE, "_look.py"), "w").write(LOOK)

print("the look: what the stylesheet names, and how grey a grey button is")
looks = 0
for theme in ([], ["night"], ["dark"]):
    for w in (300, 420):
        code = open(os.path.join(HERE, "harness2.py")).read()
        code = code.replace('panel.grab().save(out)',
                            'exec(open(r"%s").read())'
                            % os.path.join(HERE, "_look.py"))
        path = os.path.join(HERE, "_run.py")
        open(path, "w").write(code)
        out = subprocess.run([sys.executable, path, str(w), "none", "free"]
                             + theme, capture_output=True, cwd=HERE, env=CHILD, **TEXT)
        text = out.stdout + out.stderr
        said = [l for l in text.splitlines() if "LOOK" in l or "CONTRAST" in l]
        ok = "LOOKED" in text and not [l for l in said if "   LOOK" in l]
        name = "light" if not theme else theme[0]
        print("  %s  %-6s %d px  %s" % ("ok  " if ok else "FAIL", name, w,
                                        " | ".join(l.strip() for l in said)))
        if not ok:
            looks += 1
            if "LOOKED" not in text:
                print(text[-800:])

print()
print("blocks fold to one line under a module that is not theirs")
FOLD = r'''
heights = {}
for block, (card, parts) in panel.folds.items():
    folded = card.aside.isVisible()
    heights[block] = (folded, card.height())
owner = {0: 1, 1: 2, 2: 1, 3: 3}[panel.open_index]
wrong = []
for block, (folded, tall) in heights.items():
    if folded != (block != owner):
        wrong.append("block %d folded=%s" % (block, folded))
    if folded and tall > 26:
        wrong.append("block %d is %d px tall folded" % (block, tall))
for w in wrong:
    print("   FOLD", w)
print("FOLDED", "bad" if wrong else "clean")
'''
open(os.path.join(HERE, "_fold.py"), "w").write(FOLD)
folds = 0
for which in ("annotation", "objects", "correction", "cutouts"):
    code = open(os.path.join(HERE, "harness2.py")).read()
    code = code.replace('panel.grab().save(out)',
                        'exec(open(r"%s").read())'
                        % os.path.join(HERE, "_fold.py"))
    path = os.path.join(HERE, "_run.py")
    open(path, "w").write(code)
    extra = ["corrected"] if which == "correction" else []
    out = subprocess.run([sys.executable, path, "300", which] + extra,
                         capture_output=True, cwd=HERE, env=CHILD, **TEXT)
    text = out.stdout + out.stderr
    ok = "FOLDED clean" in text
    print("  %s  %s" % ("ok  " if ok else "FAIL", which))
    if not ok:
        folds += 1
        print("\n".join(l for l in text.splitlines() if "FOLD" in l
                        or "Error" in l)[-600:])

print()
print("every control is reached by Tab")
TABS = r'''
from qtbinding.QtCore import Qt
from qtbinding.QtWidgets import (QPushButton, QToolButton, QCheckBox,
                                 QComboBox, QSpinBox, QDoubleSpinBox,
                                 QLineEdit, QSlider, QAbstractSpinBox)
KINDS = (QPushButton, QToolButton, QCheckBox, QComboBox, QSpinBox,
         QDoubleSpinBox, QLineEdit, QSlider)
out = []
for w in panel.findChildren(KINDS):
    if not w.isVisible() or not w.isEnabled():
        continue
    if isinstance(w, QLineEdit) and isinstance(
            w.parentWidget(), (QAbstractSpinBox, QComboBox)):
        continue                    # the box's own editor, reached with it
    policy = w.focusPolicy()
    tab = Qt.FocusPolicy.TabFocus
    try:
        reached = (policy & tab) == tab
    except TypeError:
        reached = (int(policy.value) & int(tab.value)) == int(tab.value)
    if not reached:
        words = getattr(w, "text", lambda: "")() or w.toolTip()[:30]
        out.append("%s %r" % (type(w).__name__, words))
# and the chain itself reaches the module: from the panel, Tab gets to a
# key of the module before it comes back round
seen, w = set(), panel.nextInFocusChain()
while w is not None and w is not panel and id(w) not in seen:
    seen.add(id(w))
    w = w.nextInFocusChain()
inside = [b for b in section.findChildren(QPushButton)
          if b.isVisible() and b.isEnabled()]
if inside and not any(id(b) in seen for b in inside):
    out.append("the chain never enters the module")
for line in out[:8]:
    print("   TAB", line)
print("TABBED", "bad" if out else "clean", len(out))
'''
open(os.path.join(HERE, "_tabs.py"), "w").write(TABS)
tabs = 0
for which, extra in (("annotation", ["settings"]), ("objects", ["settings"]),
                     ("correction", ["corrected", "settings"]),
                     ("cutouts", ["settings"])):
    code = open(os.path.join(HERE, "harness2.py")).read()
    code = code.replace('panel.grab().save(out)',
                        'exec(open(r"%s").read())'
                        % os.path.join(HERE, "_tabs.py"))
    path = os.path.join(HERE, "_run.py")
    open(path, "w").write(code)
    out = subprocess.run([sys.executable, path, "300", which] + extra,
                         capture_output=True, cwd=HERE, env=CHILD, **TEXT)
    text = out.stdout + out.stderr
    ok = "TABBED clean" in text
    print("  %s  %s" % ("ok  " if ok else "FAIL", which))
    if not ok:
        tabs += 1
        print("\n".join(l for l in text.splitlines() if "TAB" in l
                        or "Error" in l)[-800:])

for leftover in ("_check.py", "_look.py", "_fold.py", "_tabs.py", "_run.py"):
    try:
        os.remove(os.path.join(HERE, leftover))
    except OSError:
        pass
print()
print("%d of %d bad, %d looks wrong, %d folds wrong, %d out of Tab's reach"
      % (bad, runs, looks, folds, tabs))
sys.exit(1 if (bad or looks or folds or tabs) else 0)
