"""The "see through" row of Correct holds in a narrow dock with a wide font.

At 260 pixels with DejaVu, the font a Linux desktop gives the panel (half
as wide again as Segoe UI), the word, the slider and the number box shared
one row: the slider came to 22 pixels, a handle and no track, and the box
ended a pixel from the edge of the panel. Now the row is one line while the
slider keeps the width of its own word (measured with the font in use), and
two when it does not: the word and the box on the first, the slider the
whole width of the second.

What is checked, in the panel built for real (QGIS is stubbed underneath
it), with the fonts of the machine, across widths from 260 to 900 pixels and
in the light theme, a dark palette and Night Mapping:

  the slider is never narrower than its word, as fontMetrics measures it;
  on one line the word, the slider and the box are in that order with no
  overlap and the box ends where the next row of the section ends;
  on two lines the slider is under the word and the box, from the left edge
  to the right edge of the box;
  the row is tall enough for the three: nothing of it is drawn over the
  tick box below it.

And the layout on its own, in a plain window, with the font at three sizes
and every width from the least the row asks for to well past the widest.

Run it with QT_QPA_FONTDIR at a folder with the DejaVu fonts to see the
panel as Ubuntu draws it (the build server does, tests/test_layout.py and
tests/test_panel_order.py are run that way too).
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHILD = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
TEXT = {"encoding": "utf-8", "errors": "replace"}
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

PANEL = r'''
from qtbinding.QtWidgets import QLabel, QApplication

def text_width(fm, words):
    try:
        return fm.horizontalAdvance(words)
    except AttributeError:
        return fm.width(words)

word = [l for l in section.findChildren(QLabel) if l.text() == "see through"][0]
slider, box, below = section.through, section.through_box, section.tuck

def at(widget):
    p = widget.mapTo(panel, widget.rect().topLeft())
    return p.x(), p.y(), widget.width(), widget.height()

def look(width):
    bad = []
    least = text_width(word.fontMetrics(), "see through")
    wx, wy, ww, wh = at(word)
    sx, sy, sw, sh = at(slider)
    bx, by, bw, bh = at(box)
    tx, ty, tw, th = at(below)
    tag = "%d px: " % width
    if sw < least:
        bad.append(tag + "the slider is %d wide, its word %d" % (sw, least))
    if bx + bw > tx + tw:
        bad.append(tag + "the box ends at %d, the row below at %d"
                   % (bx + bw, tx + tw))
    one_line = sy < wy + wh and sy + sh > wy
    if one_line:
        if not wx + ww <= sx <= sx + sw <= bx:
            bad.append(tag + "word %s slider %s box %s are not in order"
                       % ((wx, ww), (sx, sw), (bx, bw)))
    else:
        if sy < max(wy + wh, by + bh):
            bad.append(tag + "the slider is not under the word and the box")
        if sx != wx or sx + sw != bx + bw:
            bad.append(tag + "the slider is %s, the row %s"
                       % ((sx, sx + sw), (wx, bx + bw)))
    if max(wy + wh, by + bh, sy + sh) > ty + 1:
        bad.append(tag + "the row runs into the tick box below it")
    return bad, ("one line" if one_line else "two lines")

problems, shapes = [], []
for width in (260, 280, 300, 340, 420, 520, 700, 900):
    panel.setFixedWidth(width)
    for _ in range(3):
        panel.resize(width, max(panel.heightForWidth(width),
                                panel.sizeHint().height()))
        QApplication.processEvents()
    bad, shape = look(width)
    problems += bad
    shapes.append("%d:%s" % (width, "1" if shape == "one line" else "2"))
for line in problems[:6]:
    print("   ROW", line)
print("ROWS", "bad" if problems else "clean", " ".join(shapes))
'''

ALONE = r'''
from qtbinding.QtCore import QRect
from qtbinding.QtGui import QFont
from qtbinding.QtWidgets import (QApplication, QLabel, QSlider, QSpinBox,
                                 QVBoxLayout, QWidget)
SliderRow = g["SliderRow"]
from qtbinding.QtCore import Qt

def text_width(fm, words):
    try:
        return fm.horizontalAdvance(words)
    except AttributeError:
        return fm.width(words)

problems = []
for points in (9, 12, 16):
    host = QWidget()
    font = QFont(host.font())
    font.setPointSize(points)
    host.setFont(font)
    word = QLabel("see through", host)
    word.setFixedWidth(text_width(word.fontMetrics(), "see through") + 6)
    slider = QSlider(Qt.Orientation.Horizontal, host)
    box = QSpinBox(host)
    box.setSuffix(" %")
    box.setFixedWidth(box.sizeHint().width())
    least = lambda: text_width(word.fontMetrics(), "see through")
    row = SliderRow(least)
    row.add(word, slider, box)
    outer = QVBoxLayout(host)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addLayout(row)
    # the least the row asks for, and the width it is happiest at
    need = row.minimumSize().width()
    happy = row.sizeHint().width()
    if not need <= happy:
        problems.append("%d pt: minimum %d past the size hint %d"
                        % (points, need, happy))
    for width in range(need, happy + 400, 5):
        host.setFixedWidth(width)
        host.resize(width, row.heightForWidth(width))
        host.show()
        QApplication.processEvents()
        w, s, b = word.geometry(), slider.geometry(), box.geometry()
        tag = "%d pt, %d px:" % (points, width)
        if s.width() < least():
            problems.append("%s slider %d, its word %d" % (tag, s.width(),
                                                           least()))
        if b.right() + 1 > width or s.right() + 1 > width or s.left() < 0:
            problems.append("%s outside the row: slider %s box %s"
                            % (tag, s, b))
        if s.top() < w.bottom() and s.bottom() > w.top():       # one line
            if not (w.right() < s.left() and s.right() < b.left()):
                problems.append("%s one line, out of order or touching: "
                                "%s %s %s" % (tag, w, s, b))
        elif s.top() <= max(w.bottom(), b.bottom()):
            problems.append("%s two lines, the slider is not under: %s %s %s"
                            % (tag, w, s, b))
        if row.heightForWidth(width) < max(w.bottom(), s.bottom(),
                                           b.bottom()) + 1:
            problems.append("%s the height asked for is short of the row"
                            % tag)
    # more room than the happy width never makes it two lines, and the
    # narrowest room makes it two
    host.setFixedWidth(happy + 200)
    host.resize(happy + 200, 50)
    QApplication.processEvents()
    if slider.geometry().top() >= word.geometry().bottom():
        problems.append("%d pt: two lines with room for one" % points)
    host.setFixedWidth(need)
    host.resize(need, row.heightForWidth(need))
    QApplication.processEvents()
    host.close()
for line in problems[:6]:
    print("   ALONE", line)
print("ALONE", "bad" if problems else "clean")
'''

open(os.path.join(HERE, "_see_panel.py"), "w").write(PANEL)
open(os.path.join(HERE, "_see_alone.py"), "w").write(ALONE)

THEMES = [[], ["dark"], ["night"]]
bad = 0
runs = 0
print("the row in the panel, in the fonts of this machine")
for theme in THEMES:
    code = open(os.path.join(HERE, "harness2.py")).read()
    code = code.replace('panel.grab().save(out)', 'exec(open(r"%s").read())'
                        % os.path.join(HERE, "_see_panel.py"))
    path = os.path.join(HERE, "_run.py")
    open(path, "w").write(code)
    runs += 1
    out = subprocess.run([sys.executable, path, "260", "correction", "free"]
                         + theme, capture_output=True, cwd=HERE, env=CHILD,
                         **TEXT)
    text = out.stdout + out.stderr
    lines = [l for l in text.splitlines() if "ROW" in l or "Traceback" in l]
    name = theme[0] if theme else "light"
    ok = any("ROWS clean" in l for l in lines)
    print("  %s  %-5s %s" % ("ok  " if ok else "FAIL", name,
                             " | ".join(l.strip() for l in lines)
                             or text[-400:]))
    if not ok:
        bad += 1

print()
print("the layout alone, at three sizes of font")
code = open(os.path.join(HERE, "harness2.py")).read()
code = code.replace('panel.grab().save(out)', 'exec(open(r"%s").read())'
                    % os.path.join(HERE, "_see_alone.py"))
open(os.path.join(HERE, "_run.py"), "w").write(code)
runs += 1
out = subprocess.run([sys.executable, os.path.join(HERE, "_run.py"), "300",
                      "none", "free"], capture_output=True, cwd=HERE,
                     env=CHILD, **TEXT)
text = out.stdout + out.stderr
lines = [l for l in text.splitlines() if "ALONE" in l or "Traceback" in l
         or "Error" in l]
ok = any(l.strip() == "ALONE clean" for l in lines)
print("  %s  %s" % ("ok  " if ok else "FAIL", " | ".join(
    l.strip() for l in lines) or text[-400:]))
if not ok:
    bad += 1

for leftover in ("_see_panel.py", "_see_alone.py", "_run.py"):
    try:
        os.remove(os.path.join(HERE, leftover))
    except OSError:
        pass
print()
print("%d of %d bad" % (bad, runs))
sys.exit(1 if bad else 0)
