"""Press the buttons, do not only draw them.

The trial that was missing, and that cost two broken releases: the panel was
built and photographed at fifteen widths, but nobody ever clicked on it. A Qt
signal carries an argument with it (clicked carries a bool) and a slot that
does not want it fails the moment it receives it, which shows up only when you
press.

Here the panel is really built, with a fake QGIS underneath, and then every
button, every checkbox and every drop-down of every module is operated. The
modal windows are plugged, otherwise the trial would stop at the first one; the
trouble window is replaced by a recorder, so an error becomes a line instead of
a window.

A click into thin air can fail for legitimate reasons: there is no raster,
there is no campaign. Those are counted and shown but they fail nothing. The
only failures are arity errors: "takes 1 positional argument but 2 were given",
which is exactly the defect that gave rise to this trial.
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

# The panel has arrow buttons, and the sweep prints the label of every button
# it presses. On Windows a pipe is written in the locale's encoding, cp1252,
# which has no arrows: the child died on its first print with a
# UnicodeEncodeError, and with only PYTHONIOENCODING set it was this process
# that died instead, because it decoded the pipe as cp1252, got None back and
# then tried to add None to a string. So the child is told to write UTF-8, the
# pipe is read as UTF-8, and this process replaces what its own output cannot
# carry rather than dying on it. None of it depends on the caller having set
# PYTHONUTF8, which is how the suite passed on one machine and failed on the
# next.
CHILD_ENV = dict(os.environ, RL_SRC=SRC, PYTHONUTF8="1",
                 PYTHONIOENCODING="utf-8")
try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

SWEEP = r'''
from qtbinding.QtWidgets import (QPushButton, QToolButton, QCheckBox, QComboBox,
                             QMessageBox, QFileDialog, QInputDialog, QDialog,
                             QColorDialog, QSpinBox, QDoubleSpinBox)

# --- every window that waits for an answer gets one straight away
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
QColorDialog.getColor = staticmethod(lambda *a, **k: None)
QDialog.exec = lambda self, *a, **k: 0
QDialog.exec_ = lambda self, *a, **k: 0
g["run_dialog"] = lambda d: 0

# --- an iface that answers, otherwise half the commands trip over the
#     message bar instead of over whatever they are trying to do
class FakeBar(object):
    def pushMessage(self, *a, **k): pass
    def clearWidgets(self, *a, **k): pass

class Iface(object):
    def messageBar(self): return FakeBar()
    def mainWindow(self): return None
    def mapCanvas(self): return g.get("canvas", lambda: None)()
    def layerTreeView(self): return None
    def addDockWidget(self, *a, **k): pass
    def removeDockWidget(self, *a, **k): pass

g["iface"] = Iface()

# --- and a fake campaign that is a little less fake
import tempfile
camp = panel.campaign
if camp is not None:            # "free" opens none
    camp.folder = tempfile.mkdtemp(prefix="click_")
    camp.package_path = os.path.join(camp.folder, "annotation.gpkg")
    camp.manifest_path = os.path.join(camp.folder, "campaign.json")
    camp.group_name = "RasterLabel: aragona_2025"
    camp.next_code = lambda: 9
    camp.reconcile = lambda: []
    camp.active_classes = lambda: CLASSES

# --- the trouble window becomes a recorder
troubles = []
def record(err, what, parent=None):
    troubles.append((what, type(err).__name__, str(err)))
g["trouble"] = record
import builtins
builtins.RL_TROUBLES = troubles

def operable(w):
    out = []
    for b in w.findChildren(QPushButton) + w.findChildren(QToolButton):
        if not b.isEnabled():
            continue
        if b.menu() is not None:
            # A key with a menu (Measure) opens it on the press and waits
            # there for a choice, which offscreen nobody makes: its entries
            # are what it does, so each one is chosen instead.
            out.append(("menu", b, b.text()))
        else:
            out.append(("click", b, b.text() or b.toolTip()[:20]))
    for c in w.findChildren(QCheckBox):
        if c.isEnabled():
            out.append(("toggle", c, c.text()))
    for c in w.findChildren(QComboBox):
        if c.isEnabled() and c.count() > 1:
            out.append(("index", c, "combo"))
    for s in w.findChildren(QSpinBox) + w.findChildren(QDoubleSpinBox):
        if s.isEnabled():
            out.append(("step", s, "spin"))
    return out

done = 0
for kind, widget, name in operable(panel):
    done += 1
    try:
        if kind == "click":
            widget.click()
        elif kind == "menu":
            widget.menu().aboutToShow.emit()
            for act in widget.menu().actions():
                if act.isEnabled() and not act.isSeparator():
                    act.trigger()
        elif kind == "toggle":
            widget.toggle()
        elif kind == "index":
            widget.setCurrentIndex(
                (widget.currentIndex() + 1) % widget.count())
        else:
            widget.setValue(widget.value() + widget.singleStep())
    except Exception as err:
        troubles.append((name, type(err).__name__, str(err)))

print("PRESSED %d" % done)
for what, kind, message in troubles:
    print("TROUBLE %s | %s | %s"
          % (what, kind, message.replace("\n", " ")[:120]))
print("DONE")
'''

with open(os.path.join(HERE, "_sweep.py"), "w", encoding="utf-8") as f:
    f.write(SWEEP)

CASES = [("annotation", []), ("annotation", ["settings"]),
         ("correction", ["settings"]), ("objects", ["settings"]),
         ("cutouts", ["settings"]),
         # the blocks' own buttons, with no module and no correction open,
         # and with a correction open in Correct
         ("none", []), ("correction", ["corrected", "settings"]),
         # nothing open at all, with a raster and without; a long legend;
         # Cutouts with no campaign. With a module open the other blocks are
         # folded, and their arrows are pressed like everything else: a
         # folded block opened by hand puts its own keys in the sweep too.
         ("none", ["free"]), ("none", ["free", "bare"]),
         ("annotation", ["thirty"]), ("cutouts", ["free", "settings"]),
         ("objects", ["night"])]

arity, others, pressed = [], [], 0
for which, extra in CASES:
    with open(os.path.join(HERE, "harness2.py"), encoding="utf-8") as f:
        code = f.read()
    code = code.replace('panel.grab().save(out)',
                        'exec(open(r"%s", encoding="utf-8").read())'
                        % os.path.join(HERE, "_sweep.py"))
    run = os.path.join(HERE, "_run_click.py")
    with open(run, "w", encoding="utf-8") as f:
        f.write(code)
    out = subprocess.run([sys.executable, run, "420", which] + extra,
                         capture_output=True, encoding="utf-8",
                         errors="replace", cwd=HERE, env=CHILD_ENV)
    text = (out.stdout or "") + (out.stderr or "")
    if "DONE" not in text:
        arity.append((which, "the trial did not reach the end",
                      text.strip().splitlines()[-3:]))
        continue
    for line in text.splitlines():
        if line.startswith("PRESSED"):
            n = int(line.split()[1])
            pressed += n
            print("  %-22s %3d commands operated"
                  % (which + " ".join(extra), n))
        elif line.startswith("TROUBLE "):
            parts = [p.strip() for p in line[8:].split("|", 2)]
            while len(parts) < 3:
                parts.append("?")
            what, kind, message = parts
            row = (which, what, kind, message)
            if kind == "TypeError" and "positional argument" in message:
                arity.append(row)
            else:
                others.append(row)

print()
print("arity errors (these fail the trial): %d" % len(arity))
for r in arity:
    print("   FAIL %s" % (r,))
print()
print("other stumbles, legitimate or not (these fail nothing): %d"
      % len(others))
for r in others[:12]:
    print("   note %-12s %-16s %s" % (r[1][:12], r[2], r[3][:80]))

print()
print("%d commands pressed in all" % pressed)
print("all pass" if not arity else "FAILED")
sys.exit(1 if arity else 0)
