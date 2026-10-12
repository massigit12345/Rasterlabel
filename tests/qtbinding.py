"""The Qt binding the suites run on: PyQt5 or PyQt6.

The program itself never names either one. It imports from qgis.PyQt, and
QGIS maps that to PyQt5 on QGIS 3 and to PyQt6 on QGIS 4. The suites that
build a fake QGIS have to do the same mapping by hand, and this is the one
place where it is done, so that the same suites run on both.

Which one: RL_QT=5 or RL_QT=6 when it is set, otherwise PyQt5 if it is
installed, otherwise PyQt6. The binding is used as it comes, with only the
two moves QGIS itself makes on top of it:

- on PyQt5, QAction, QActionGroup and QShortcut are also offered from QtGui,
  which is where Qt 6 keeps them and where the program imports them from.
  QGIS 3 does the same in its qgis.PyQt.QtGui.
- nothing is added on PyQt6. QGIS 4 still lends QAction to QtWidgets and
  puts back a few names PyQt6 removed, such as Qt.Orientations; leaving them
  out here means a suite fails if the program ever leans on them.

What it gives: PyQt (the package), QtCore, QtGui, QtWidgets, sip, and QT,
5 or 6. The three modules can also be imported by name, as in
"from qtbinding.QtWidgets import QPushButton", so a suite reads the way it
did when it said PyQt5.
"""
import importlib
import os
import sys

_wanted = os.environ.get("RL_QT", "").strip()
if _wanted not in ("", "5", "6"):
    raise ImportError("RL_QT must be 5 or 6, not %r" % _wanted)

_tried = []
PyQt = None
for _name in (["PyQt" + _wanted] if _wanted else ["PyQt5", "PyQt6"]):
    try:
        PyQt = importlib.import_module(_name)
        break
    except ImportError as e:
        _tried.append("%s: %s" % (_name, e))
if PyQt is None:
    raise ImportError("no Qt binding for the suites (%s). pip install PyQt5, "
                      "or PyQt6" % "; ".join(_tried))

QtCore = importlib.import_module(PyQt.__name__ + ".QtCore")
QtGui = importlib.import_module(PyQt.__name__ + ".QtGui")
QtWidgets = importlib.import_module(PyQt.__name__ + ".QtWidgets")
sip = importlib.import_module(PyQt.__name__ + ".sip")
for _mod in ("QtCore", "QtGui", "QtWidgets", "sip"):
    sys.modules[__name__ + "." + _mod] = globals()[_mod]
QT = int(QtCore.QT_VERSION_STR.split(".")[0])
NAME = PyQt.__name__

if QT == 5:
    for _cls in ("QAction", "QActionGroup", "QShortcut"):
        if not hasattr(QtGui, _cls):
            setattr(QtGui, _cls, getattr(QtWidgets, _cls))


def describe():
    """One line for the head of a run: which binding, which Qt."""
    return "%s %s on Qt %s" % (NAME, QtCore.PYQT_VERSION_STR,
                               QtCore.QT_VERSION_STR)
