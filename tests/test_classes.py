"""The legend gets changed while you draw, without leaving the map.

The annotation module is really built and the chips are really operated: double
click, type, enter. Then we look at what changed in the manifest, on the chip,
and in what had already been drawn.
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
from qtbinding.QtWidgets import QLineEdit, QMessageBox, QPushButton

fails = []
def check(name, cond, detail=""):
    print(("CHECK ok   " if cond else "CHECK FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)

# --- what the section asks of the panel and of the campaign
renamed = []
panel.rename_features = lambda: renamed.append(1) or 7
panel.describe_campaign = lambda: None
g["restyle"] = lambda campaign: None
saved = []
section.campaign.save = lambda: saved.append(1)
section.campaign.next_code = lambda: max(
    [c["code"] for c in section.campaign.data["classes"]] or [0]) + 1
section.apply_filter = lambda *a, **k: None
warnings = []
QMessageBox.warning = staticmethod(lambda *a, **k: warnings.append(a[2]) or 0)

def chip_for(code):
    for b in section._buttons:
        if getattr(b, "code", None) == code:
            return b
    return None

def box():
    # isVisible() is false until the event loop has run, and here it does not
    # run: isHidden() says what we need, that is, whether it was hidden on
    # purpose.
    for w in section.findChildren(QLineEdit):
        if w.__class__.__name__ == "NameBox" and not w.isHidden():
            return w
    return None

def names():
    return [c["name"] for c in section.campaign.data["classes"]]

print("SECTION the double click opens the name where it stands")
before = list(names())
chip = chip_for(1)
check("the chip for class 1 is there", chip is not None)
check("and it is a ClassChip, not just any button",
      chip.__class__.__name__ == "ClassChip", chip.__class__.__name__)
section.start_rename(1)
b = box()
check("a box opens", b is not None)
check("with the current name inside it", b and b.text() == before[0],
      b and b.text())
check("and the chip gets out of the way", chip.isHidden())
check("the box sits in the chip's own cell",
      section.class_grid.indexOf(b) >= 0)

print("SECTION enter keeps the name, and carries it onto what is drawn")
saved[:] = []
renamed[:] = []
b.setText("dry crust")
b.returnPressed.emit()
check("the manifest has the new name", names()[0] == "dry crust", names())
check("and it was written to disk", saved, saved)
check("what is drawn was renamed", renamed, renamed)
check("the class in hand follows the name",
      section.class_name == "dry crust", section.class_name)
check("the box is gone", box() is None)
check("and the chip is back, with the new name",
      chip_for(1) is not None and "dry" in chip_for(1).text(),
      chip_for(1) and chip_for(1).text())

print("SECTION Esc puts everything back as it was")
section.start_rename(1)
b = box()
b.setText("a thing never typed")
from qtbinding.QtGui import QKeyEvent
from qtbinding.QtCore import QEvent, Qt
b.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                          Qt.KeyboardModifier.NoModifier))
check("the box goes away", box() is None)
check("and the name did not change", names()[0] == "dry crust", names())
check("the chip is visible again", not chip_for(1).isHidden())

print("SECTION two classes cannot have the same name")
warnings[:] = []
second = section.campaign.data["classes"][1]["name"]
section.start_rename(1)
b = box()
b.setText(second)
b.returnPressed.emit()
check("it refuses", names()[0] == "dry crust", names())
check("and says why", warnings and "already a class" in warnings[0], warnings)

print("SECTION an empty name does not wipe the name")
section.start_rename(1)
b = box()
b.setText("   ")
b.returnPressed.emit()
check("the previous one stays", names()[0] == "dry crust", names())

print("SECTION the plus adds a class and lets you type its name")
how_many = len(section.campaign.data["classes"])
plus = [x for x in section._buttons if x.text() == "+"]
check("the plus is at the end of the chips", len(plus) == 1, len(plus))
saved[:] = []
plus[0].click()
from qtbinding.QtWidgets import QApplication
QApplication.processEvents()      # the deferred start_rename
check("one class more",
      len(section.campaign.data["classes"]) == how_many + 1,
      len(section.campaign.data["classes"]))
added = section.campaign.data["classes"][-1]
check("with the next number, never reused", added["code"] == how_many + 1,
      added)
check("and a colour of its own", added["colour"].startswith("#"), added)
check("written into the manifest", saved, saved)
check("it becomes the class in hand", section.class_name == added["name"],
      section.class_name)
check("and the name is already there to type", box() is not None)
b = box()
b.setText("efflorescence")
b.returnPressed.emit()
check("typing it works", names()[-1] == "efflorescence", names())

print("SECTION the chips are all where they belong")
rows = {}
for x in section._buttons:
    if not x.isHidden():
        p = x.mapTo(section, x.rect().topLeft())
        rows.setdefault(p.y(), []).append((p.x(), x.width(), x.text()))
overlaps = []
for y, row in rows.items():
    row.sort()
    for (x1, w1, t1), (x2, w2, t2) in zip(row, row[1:]):
        if x1 + w1 > x2 + 2:
            overlaps.append((t1, t2))
check("no chip sitting on top of another", not overlaps, overlaps)

print("SECTION the codes stop at 254, and a class past them is refused")
# A mask is one byte a pixel and 255 is kept for "ignore". There was no
# ceiling at all, and class 256 went into the mask as 0.
warnings[:] = []
editor = g["ClassEditor"](None, [{"name": "last but one", "colour": "#000000",
                                  "code": 253}], 254)
editor.add_blank()
check("the Classes window still gives 254", len(editor.rows) == 2
      and [c["code"] for c in editor.result()] == [253, 254],
      [c["code"] for c in editor.result()])
editor.add_blank()
check("and not 255", len(editor.rows) == 2, len(editor.rows))
check("saying why", warnings and "254" in warnings[-1] and "255" in warnings[-1],
      warnings)
editor.deleteLater()
section.campaign.data["classes"].append(
    {"name": "kept back", "colour": "#000000", "code": 254, "retired": True})
how_many = len(section.campaign.data["classes"])
warnings[:] = []
section.add_class()
check("the plus on the chips adds nothing past 254 either",
      len(section.campaign.data["classes"]) == how_many,
      section.campaign.data["classes"][-1])
check("and says why", warnings and "254" in warnings[-1], warnings)

print("VERDICT %d" % len(fails))
'''

open(os.path.join(HERE, "_classi.py"), "w").write(TRIAL)

code = open(os.path.join(HERE, "harness2.py")).read()
code = code.replace('panel.grab().save(out)',
                    'exec(open(r"%s").read())' % os.path.join(HERE,
                                                              "_classi.py"))
run = os.path.join(HERE, "_run_classi.py")
open(run, "w").write(code)
out = subprocess.run([sys.executable, run, "460", "annotation"],
                     capture_output=True, text=True, cwd=HERE,
                     env=dict(os.environ, RL_SRC=SRC))
text = out.stdout + out.stderr
for line in text.splitlines():
    if line.startswith("SECTION"):
        print()
        print(line[8:])
    elif line.startswith("CHECK"):
        print("  " + line[6:])
verdict = [l for l in text.splitlines() if l.startswith("VERDICT")]
if not verdict:
    print(text[-1500:])
    print("the trial did not reach the end")
    sys.exit(1)
how_many = int(verdict[0].split()[1])
print()
print("all pass" if not how_many else "FAILED: %d" % how_many)
sys.exit(1 if how_many else 0)
