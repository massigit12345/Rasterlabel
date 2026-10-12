"""The Import frames window, drawn offscreen at the widths it must hold.

harness2 builds the panel with QGIS stubbed; in its place this suite opens
ImportFrames on an AcATaMa-like sample of 120 points, three of them refused
(two over another frame, one off the raster), and draws it at 300 px, the
narrowest it may be made, and at 420 px, the width it opens at, in the light
theme, a dark Fusion palette and QGIS's Night Mapping. At each:

- the window can be as narrow as 300 px: nothing asks for more, so the
  dock or the screen never has to scroll it sideways;
- every label wraps, and none is cut: each is as tall as its words need at
  its width;
- nothing is drawn past the right edge;
- what will happen is said ("117 added", the refusals with the frames they
  are about) and the key reads "Import 117".

With RL_SHOTS set to a folder, each drawing is saved there as a PNG.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHILD = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
TEXT = {"encoding": "utf-8", "errors": "replace"}
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

DRAW = r'''
import os as _os
from qtbinding.QtWidgets import (QLabel, QWidget, QComboBox, QLineEdit,
                                 QPushButton, QRadioButton)

O, P = (500000.0, 4200000.0), (0.5, 0.5)
EXTENT = (500000.0, 4199500.0, 500500.0, 4200000.0)
rows = []
for i in range(120):
    x = 500012.0 + (i % 12) * 40.0
    y = 4199985.0 - (i // 12) * 40.0
    rows.append({"fid": i + 1, "kind": "point", "bbox": (x, y, x, y),
                 "transform_ok": True, "attrs": {"id": i + 1},
                 "parts": 1})
# two draws half over the first frame, one off the raster
for j, (x, y) in enumerate(((500016.0, 4199985.0), (500018.0, 4199981.0),
                            (501000.0, 4199900.0))):
    rows[117 + j] = dict(rows[117 + j], bbox=(x, y, x, y))


def planner(choice):
    return g["design_plan"](rows, [], inside=g["design_inside_box"](EXTENT),
                            settings_side_px=20,
                            own_side=choice["own_side"], origin=O, pixel=P,
                            mapping=choice["mapping"],
                            design_typed=choice["design_text"])


source = {"name": "draws_2024.gpkg", "what": "120 points, EPSG:32633",
          "note": ""}
d = g["ImportFrames"](panel, source, ["fid", "id"],
                      [("map_2024", "layer_1")], 10.0, 20, False, planner,
                      can_own_side=False)
d.typed.setText("stratified random, AcATaMa, n=120")
d.refresh()
bad = []
said = d.preview.text()
if not said.startswith("117 added"):
    bad.append("the preview says %r" % said[:60])
if "overlap with t001" not in said or "outside the raster" not in said:
    bad.append("the refusals are not said: %r" % said)
if d.go.text() != "Import 117" or not d.go.isEnabled():
    bad.append("the key reads %r" % d.go.text())
choice = d.result()
if choice["mapping"]["sample_id"] != "id" or choice["words"]["design"] != "typed":
    bad.append("the choice is %r" % choice)
for w in (300, 420):
    d.show()
    app.processEvents()
    least = d.minimumWidth()
    if least > 300:
        bad.append("at %d px the window needs %d px" % (w, least))
    d.resize(w, 100)
    app.processEvents()
    d.resize(w, max(d.height(), d.minimumHeight(),
                    d.layout().totalHeightForWidth(w)
                    if d.layout().hasHeightForWidth() else 0))
    app.processEvents()
    if d.width() != w:
        bad.append("asked for %d px, the window is %d" % (w, d.width()))
    for label in d.findChildren(QLabel):
        if not label.isVisible() or not label.text():
            continue
        if not label.wordWrap():
            bad.append("%r does not wrap" % label.text()[:30])
        need = label.heightForWidth(label.width())
        if need > label.height() + 1:
            bad.append("at %d px %r is cut: %d of %d px"
                       % (w, label.text()[:30], label.height(), need))
    for child in d.findChildren((QLabel, QComboBox, QLineEdit, QPushButton,
                                 QRadioButton)):
        if not child.isVisible():
            continue
        right = child.mapTo(d, child.rect().topRight()).x()
        if right > d.width():
            bad.append("at %d px %s %r ends at %d"
                       % (w, type(child).__name__,
                          getattr(child, "text", lambda: "")()[:20], right))
    shots = _os.environ.get("RL_SHOTS")
    if shots:
        theme = "night" if "night" in sys.argv else (
            "dark" if "dark" in sys.argv else "light")
        d.grab().save(_os.path.join(shots, "import_frames_%s_%d.png"
                                    % (theme, w)))
for b in bad:
    print("   DRAWN", b)
print("VERDICT", "bad" if bad else "clean")
'''

fails = []
draw = os.path.join(HERE, "_import_frames_draw.py")
with open(draw, "w", encoding="utf-8") as fh:
    fh.write(DRAW)
for theme in ([], ["dark"], ["night"]):
    code = open(os.path.join(HERE, "harness2.py"), encoding="utf-8").read()
    code = code.replace('panel.grab().save(out)',
                        'exec(open(r"%s", encoding="utf-8").read())' % draw)
    path = os.path.join(HERE, "_import_frames_run.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(code)
    out = subprocess.run([sys.executable, path, "300", "none", "free"]
                         + theme, capture_output=True, cwd=HERE, env=CHILD,
                         **TEXT)
    text = out.stdout + out.stderr
    name = theme[0] if theme else "light"
    good = "VERDICT clean" in text
    print("  %s  %s, 300 and 420 px" % ("ok  " if good else "FAIL", name))
    if not good:
        fails.append(name)
        print("\n".join(l for l in text.splitlines()
                        if "DRAWN" in l or "Error" in l or "Traceback" in l
                        or "VERDICT" in l) or text[-1500:])
for leftover in (draw, os.path.join(HERE, "_import_frames_run.py")):
    try:
        os.remove(leftover)
    except OSError:
        pass

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
sys.exit(1 if fails else 0)
