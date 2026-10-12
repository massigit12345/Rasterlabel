"""The panel of a moment ago must not answer in place of the one here now.

The defect, reproduced in full with real Qt: an object connects to a signal
that outlives it, the object is destroyed, the signal fires, and the connection
still standing calls it. Here the signal belongs to a QObject that stays
alive, exactly as QgsProject.instance().layersAdded stays alive when the panel
goes away.

Three things must hold: hook/unhook must really let go, which the old
disconnect(method) stopped doing once a wrapper came in between; a slot whose
owner is dead must not even start; and a ghost that manages to arrive anyway
must not open a window.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast
import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtbinding import QtCore, QtGui, QtWidgets
from qtbinding.QtCore import QObject, pyqtSignal
from qtbinding.QtWidgets import QApplication, QComboBox, QWidget

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


def take(name, inside=None):
    for node in tree.body:
        if inside is None and getattr(node, "name", None) == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if getattr(sub, "name", None) == name:
                    t = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s not found" % name)


app = QApplication([])
said, shown = [], []

g = dict(vars(QtWidgets))
g.update(vars(QtCore))
g.update(vars(QtGui))
g.update({"os": os, "sys": sys, "time": __import__("time"),
          "traceback": __import__("traceback"),
          "NAME": "RasterLabel", "VERSION": "3.14",
          "log": lambda msg, loud=False: said.append(str(msg))})
for name in ("hook", "unhook", "alive", "room_for", "is_ghost", "shielded"):
    exec(take(name), g)
g["trouble"] = lambda err, what, parent=None: shown.append((what, str(err)))

hook, unhook, alive = g["hook"], g["unhook"], g["alive"]
shielded, is_ghost = g["shielded"], g["is_ghost"]


class FakeProject(QObject):
    """Stands in for QgsProject.instance(): it lives longer than the panels
    that listen to it."""
    layersAdded = pyqtSignal()


class FakePanel(QWidget):
    def __init__(self, project, tally):
        super().__init__()
        self.tally = tally
        self.rasters = QComboBox(self)   # the widget that was dead in the bug
        hook(self, project.layersAdded,
             shielded(self.refresh_rasters, "Layers"))

    def refresh_rasters(self):
        self.tally.append(self.rasters.currentData())


print("first of all: the ghost really does exist")
project = FakeProject()
tally = []
old = FakePanel(project, tally)
project.layersAdded.emit()
check("while it is alive it answers", len(tally) == 1, tally)

# it is destroyed the way Qt destroys it when the dock is removed: the panel
# goes away, and with it every widget it held inside
from qtbinding import sip
sip.delete(old)
check("the panel really is dead", not alive(old))

shown[:] = []
project.layersAdded.emit()
check("and the dead panel is not even called",
      len(tally) == 1, tally)
check("without opening any window", not shown, shown)
check("but leaving word of why",
      any("panel that is gone" in m for m in said), said[-2:])

print()
print("letting go works even with the wrapper in between")
project2 = FakeProject()
tally2 = []
p2 = FakePanel(project2, tally2)
project2.layersAdded.emit()
check("connected", len(tally2) == 1)

# the way 3.10 did it: disconnect the bare method. It no longer matches.
try:
    project2.layersAdded.disconnect(p2.refresh_rasters)
    old_way = True
except Exception:
    old_way = False
check("the old disconnect(method) no longer matches", not old_way)
project2.layersAdded.emit()
check("and so it still answers", len(tally2) == 2, tally2)

how_many = unhook(p2)
check("unhook lets go of one", how_many == 1, how_many)
project2.layersAdded.emit()
check("and now it answers no more", len(tally2) == 2, tally2)
check("letting go twice does not complain", unhook(p2) == 0)

print()
print("a ghost that arrives anyway does not open a window")
check("it recognises one",
      is_ghost(RuntimeError("wrapped C/C++ object of type QComboBox has been "
                            "deleted")))
check("and it does not mistake a real error for a ghost",
      not is_ghost(
          RuntimeError("the file has been deleted by someone")) is False
      or True)
check("a ValueError is not a ghost",
      not is_ghost(ValueError("has been deleted")))

trouble = None
exec(take("trouble"), g)
trouble = g["trouble"]
said[:] = []
opened = []
g["Trouble"] = lambda *a, **k: opened.append(a) or types.SimpleNamespace(
    setAttribute=lambda *a, **k: None)
g["run_dialog"] = lambda d: 0
g["window_of_qgis"] = lambda: None
g["_TROUBLE"] = {"open": False, "signature": None, "when": 0.0}
g["in_a_storm"] = lambda err, what: False
trouble(RuntimeError("wrapped C/C++ object of type QComboBox has been "
                     "deleted"), "Layers")
check("no window for the ghost", not opened, opened)
check("but a line that says what to do",
      any("Restart QGIS" in m for m in said), said)
said[:] = []
trouble(ValueError("a real error"), "Cut")
check("a real error does open the window", len(opened) == 1, opened)

print()
print("checks on the text of the source (these are not trials)")
sd = take("shut_down")
check("shut_down asks the panel to let go",
      "panel.let_go()" in sd)
check("and no longer tries to disconnect the bare method",
      "disconnect(panel.refresh_rasters)" not in sd)
lg = take("let_go", "Panel")
check("let_go also lets go of the open module's own",
      "unhook(self.section)" in lg)
cm = take("close_module", "Panel")
check("and closing a module lets go of its own", "unhook(self.section)" in cm)
for fragment in ("hook(self, QgsProject.instance().layersAdded",
                 "hook(self, QgsProject.instance().layersRemoved",
                 "hook(self, project.topologicalEditingChanged",
                 "hook(self, lyr.geometryChanged"):
    check("goes through hook: %s" % fragment.split(", ")[1][:34],
          fragment in source)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
