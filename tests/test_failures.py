"""What happens when something goes wrong, and which QGIS this runs on.

Everything in here is really run: the functions are taken out of the source
and executed against real exceptions, and the window is built with Qt and
read back from its own widgets. The only checks on the source text sit at
the bottom, under the heading that says so, and they are there for one
purpose only, to make sure no old name was left behind in the file.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast
import os
import sqlite3
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtbinding import QtCore, QtGui, QtWidgets
from qtbinding.QtWidgets import QApplication, QLabel, QPlainTextEdit, QPushButton

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


def take(name):
    for node in tree.body:
        if getattr(node, "name", None) == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return "".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("%s not found" % name)


# ------------------------------------------------------------- the test bench
app = QApplication([])

said = []


class FakeGdal(object):
    @staticmethod
    def VersionInfo(_):
        return "3.8.4"


g = dict(vars(QtWidgets))
g.update(vars(QtCore))
g.update(vars(QtGui))
g.update({"os": os, "sys": sys, "time": __import__("time"),
          "traceback": __import__("traceback"), "platform": __import__("platform"),
          "gdal": FakeGdal, "NAME": "RasterLabel", "VERSION": "pre-1.0",
          "BUILD": "abcd1234", "SHAPE": "single file",
          "hashlib": __import__("hashlib"), "re": __import__("re"),
          "PREFIX": "rasterlabel",
          "log": lambda msg, loud=False: said.append(str(msg)),
          "iface": None})

for name in ("BUILT_FOR", "BUILT_FOR_NAME", "TRACE_LINES", "TROUBLE_W", "STORM_SECONDS",
             "first_attr", "first_of", "qgis_version", "qgis_version_text", "run_dialog",
             "qt_generation", "environment", "error_text", "TROUBLE_RULES",
             "diagnose", "Trouble", "_TROUBLE", "in_a_storm", "trouble",
             "window_of_qgis", "room_for", "shielded", "shield_tools",
             "tool_net", "home_folder", "home_rest", "_LOGIN_KEYS",
             "_LOGIN_PAIR", "_LOGIN_LINK", "_VSI_NAME", "clean_source",
             "without_home",
             "check_qgis", "OldQgis", "warn_old_qgis"):
    exec(take(name), g)


# ------------------------------------------------------ the names that move
print("the names QGIS moves from one house to another")


class NewQgis(object):
    class GeometryType(object):
        Polygon = "new"


class OldWkb(object):
    PolygonGeometry = "old"


g["Qgis"], g["QgsWkbTypes"] = NewQgis, OldWkb
first_of = g["first_of"]
check("takes the new name when it is there",
      first_of("Qgis.GeometryType.Polygon", "QgsWkbTypes.PolygonGeometry")
      == "new")

g["Qgis"] = types.SimpleNamespace()
check("falls back on the old one when the new one is missing",
      first_of("Qgis.GeometryType.Polygon", "QgsWkbTypes.PolygonGeometry")
      == "old")

g["QgsWkbTypes"] = types.SimpleNamespace()
check("returns None when neither of the two is there",
      first_of("Qgis.GeometryType.Polygon", "QgsWkbTypes.PolygonGeometry")
      is None)
check("a made-up name does not blow it up",
      first_of("SomethingThatNeverExisted.Ever") is None)


class Layer(object):
    class Property(object):
        Size = 0                       # the first of its kind, and worth 0


first_attr = g["first_attr"]
check("a member worth 0 is still found, not taken for missing",
      first_attr(Layer, "Property.Size", "PropertySize") == 0)
check("and the old spelling answers when the new one is not there",
      first_attr(types.SimpleNamespace(PropertySize=7), "Property.Size",
                 "PropertySize") == 7)
check("and None when the class itself is missing",
      first_attr(None, "Property.Size", "PropertySize") is None)

print()
print("which version of QGIS is underneath")
qgis_version = g["qgis_version"]
for number, expected in ((33600, (3, 36)), (32800, (3, 28)), (32211, (3, 22)),
                         (34000, (3, 40)), (40000, (4, 0))):
    g["Qgis"] = types.SimpleNamespace(QGIS_VERSION_INT=number,
                                      QGIS_VERSION="x")
    got = qgis_version()
    check("%d -> %s" % (number, expected), got == expected, got)

g["Qgis"] = types.SimpleNamespace(QGIS_VERSION="3.99.0-Master")
check("from a nightly it reads the string", qgis_version() == (3, 99),
      qgis_version())
g["Qgis"] = types.SimpleNamespace()
check("and if it says nothing the answer is (0, 0), older than anything",
      qgis_version() == (0, 0), qgis_version())

print()
print("the check at startup")
check_qgis = g["check_qgis"]
said[:] = []
g["Qgis"] = types.SimpleNamespace(QGIS_VERSION_INT=33600, QGIS_VERSION="3.36.3")
check("the 3.36 it was written on is fine", check_qgis() is True)
said[:] = []
g["Qgis"] = types.SimpleNamespace(QGIS_VERSION_INT=34000, QGIS_VERSION="3.40.0")
check("and so is everything that comes after it", check_qgis() is True)
said[:] = []
g["Qgis"] = types.SimpleNamespace(QGIS_VERSION_INT=32800, QGIS_VERSION="3.28.9")
outcome = check_qgis()
check("3.28 is not, and it says so", outcome is False)
check("naming both versions",
      any("3.28.9" in m and "3.36" in m for m in said), said)
said[:] = []
g["Qgis"] = types.SimpleNamespace()
check("a silent QGIS blocks nothing", check_qgis() is True)
g["Qgis"] = types.SimpleNamespace(QGIS_VERSION_INT=33600, QGIS_VERSION="3.36.3")

# --------------------------------------------------- from the error to advice
print()
print("from the error to the advice")
diagnose = g["diagnose"]

CASES = [
    (sqlite3.OperationalError("database is locked"),
     "held open", ["pencil", "OneDrive"]),
    (PermissionError(13, "Permission denied"),
     "refused permission", ["open in another program"]),
    (OSError(28, "No space left on device"),
     "disk is full", ["Free some room"]),
    (FileNotFoundError(2, "No such file or directory"),
     "not where it was", ["moved"]),
    (MemoryError("Unable to allocate 41.2 GiB for an array"),
     "not enough memory", ["scale"]),
    (RuntimeError("wrapped C/C++ object of type QgsVectorLayer has been "
                  "deleted"),
     "closed underneath", ["Close the panel"]),
    (AttributeError("type object 'Qgis' has no attribute 'GeometryType'"),
     "missing something", ["older QGIS"]),
    (ModuleNotFoundError("No module named 'osgeo'"),
     "GDAL is not on this Python", ["QGIS Python Console"]),
    (RuntimeError("'/x/y.tif' not recognized as being in a supported file "
                  "format."),
     "does not know how to read", ["damaged"]),
    (sqlite3.DatabaseError("database disk image is malformed"),
     "does not read as a GeoPackage", ["-wal"]),
]
for err, fragment, inside in CASES:
    sentence, remedies = diagnose(err, "Save")
    ok = fragment in sentence and all(
        any(word in r for r in remedies) for word in inside)
    check("%-22s -> %s" % (type(err).__name__, sentence[:46]), ok,
          (sentence, remedies))
    check("   and it offers something to do about it", len(remedies) >= 2,
          len(remedies))

sentence, remedies = diagnose(ValueError("something never seen before"), "Cut")
check("an error never seen before is not left without an answer",
      "Cut" in sentence and len(remedies) >= 2, (sentence, remedies))
check("and it says what was already saved is untouched",
      any("already saved" in r for r in remedies), remedies)

print()
print("the error number counts for more than the language of the system")
# The two Italian messages below are on purpose, and must stay in Italian:
# they stand in for a Windows that speaks something other than English, so
# that the only thing left to recognise the trouble by is the errno.
error_text = g["error_text"]
check("the errno lands in front of the message",
      error_text(PermissionError(13, "Accesso negato")).startswith("errno 13"),
      error_text(PermissionError(13, "Accesso negato")))
sentence, _ = diagnose(PermissionError(13, "Accesso negato"), "Save")
check("so an Italian Windows gets the very same advice",
      "refused permission" in sentence, sentence)
sentence, _ = diagnose(OSError(28, "Spazio esaurito sul dispositivo"), "Cut")
check("and a full disk too", "disk is full" in sentence, sentence)

# -------------------------------------------------------------------- the net
print()
print("the net under the buttons")
shielded = g["shielded"]
seen = []
g["trouble"] = lambda err, what, parent=None: seen.append((what, err))


class FakeEntry(object):
    def nothing(self):
        return "nothing"


def good(x):
    return x * 2


def bad():
    raise RuntimeError("broken")


check("a command that works passes its result through",
      shielded(good, "Save")(21) == 42)
seen[:] = []
outcome = shielded(bad, "Save")()
check("one that breaks propagates nothing", outcome is None)
check("and it ends up in the window under the name of the button",
      seen and seen[0][0] == "Save", seen)
check("the button is still something you can connect",
      callable(shielded(bad, "Save")))

print()
print("the net does not hand the slot arguments it cannot take")
# The real defect: clicked carries a bool. PyQt reads the signature of the
# slot and drops that bool by itself, but put a wrapper with *args in the
# middle and PyQt sees something that takes anything, hands over the bool,
# and every command in the program dies.
room_for = g["room_for"]


def no_args(): return "nothing"
def one_arg(a): return a
def two_args(a, b): return (a, b)
def star_args(*a): return a
def with_default(a=False): return a


for slot, expected in ((no_args, 0), (one_arg, 1), (two_args, 2),
                       (star_args, None), (with_default, 1),
                       (lambda: 1, 0), (lambda _=False: 1, 1)):
    named = getattr(slot, "__name__", "lambda")
    check("room_for(%s) = %s" % (named, expected),
          room_for(slot) == expected, room_for(slot))

check("a slot with no arguments survives a clicked(bool)",
      shielded(no_args, "Save")(False) == "nothing")
check("one that does want the argument gets it",
      shielded(one_arg, "Class")(False) is False)
check("and one that wants two gets both of them",
      shielded(two_args, "Vertex")(7, "g") == (7, "g"))
check("an open signature is left alone",
      shielded(star_args, "Move")(1, 2, 3) == (1, 2, 3))
check("a bound method counts without self",
      room_for(FakeEntry().nothing) == 0, room_for(FakeEntry().nothing))

# and now with real Qt, which is where the defect showed itself. QPushButton is
# imported again here, beside the checks that use it, because this block is the
# point of the suite and reads better whole.
from qtbinding.QtWidgets import QCheckBox
calls = []
b = QPushButton("Save")
b.clicked.connect(shielded(lambda: calls.append("pressed"), "Save"))
b.click()
check("a real button, really pressed, raises nothing",
      calls == ["pressed"], calls)
ticks = []
c = QCheckBox("blind")
c.stateChanged.connect(shielded(lambda: ticks.append("ticked"), "Blind"))
c.setChecked(True)
check("and a checkbox too", ticks == ["ticked"], ticks)

print()
print("the net under the mouse")


class FakeTool(object):
    def canvasPressEvent(self, ev):
        raise ValueError("crooked click")

    def canvasMoveEvent(self, ev):
        return "all right"


g["shield_tools"](FakeTool)
seen[:] = []
t = FakeTool()
check("a click that breaks never reaches Qt", t.canvasPressEvent(None) is None)
check("and it says which tool it was", seen and "Fake" in seen[0][0], seen)
check("what works keeps working as before",
      t.canvasMoveEvent(None) == "all right")
before = FakeTool.canvasPressEvent
g["shield_tools"](FakeTool)
check("wrapping twice does not wrap twice",
      FakeTool.canvasPressEvent is before)

print()
print("one window at a time, and never the same one twice in a row")
in_a_storm = g["in_a_storm"]
g["_TROUBLE"].update({"open": False, "signature": None, "when": 0.0})
err = RuntimeError("the same")
check("the first time it opens", in_a_storm(err, "Move") is False)
check("the second identical one does not", in_a_storm(err, "Move") is True)
check("a different one does, even straight away",
      in_a_storm(RuntimeError("another"), "Move") is False)
g["_TROUBLE"]["when"] = 0.0
check("and once the storm has passed it opens again",
      in_a_storm(RuntimeError("another"), "Move") is False)
g["_TROUBLE"].update({"open": True, "signature": None, "when": 0.0})
check("with a window already open no second one is opened",
      in_a_storm(RuntimeError("a third"), "Cut") is True)
g["_TROUBLE"]["open"] = False

# ----------------------------------------------------------------- the window
print()
print("the window, really built")
Trouble = g["Trouble"]
try:
    raise PermissionError(13, "Permission denied")
except PermissionError as real_error:
    window = Trouble(real_error, "Save")

texts = [w.text() for w in window.findChildren(QLabel)]
check("the title says which command did not finish",
      "Save" in window.windowTitle(), window.windowTitle())
check("the first line is the sentence in plain words",
      any("refused permission" in t for t in texts), texts[:2])
check("what the machine itself said is there too",
      any("PermissionError" in t for t in texts))
check("the remedies are numbered", any(t.startswith("1.") for t in texts),
      texts)
check("at least two", len([t for t in texts if t[:2] in ("1.", "2.")]) == 2)

detail = window.findChild(QPlainTextEdit)
check("the detail is there", detail is not None)
check("but it starts out closed", detail.isHidden())
window.fold.setChecked(True)
check("and the triangle opens it", not detail.isHidden())

report = window.report
for expected in ("RasterLabel pre-1.0", "build abcd1234", "single file", "QGIS",
                 "GDAL", "Python", "PermissionError"):
    check("the report contains %s" % expected, expected in report,
          report[:200])
check("and the traceback, with the file and the line",
      "Traceback" in report and "test_failures.py" in report, report[-300:])

buttons = [b.text() for b in window.findChildren(QPushButton)]
check("it can be copied", any("Copy" in b for b in buttons), buttons)
check("and saved", any("Save report" in b for b in buttons), buttons)
window.copy_report()
check("copying really does put it on the clipboard",
      QApplication.clipboard().text() == report)

print()
print("a very long report stays readable")
long_one = RuntimeError("x")
window2 = Trouble(long_one, "Whole raster")
check("the traceback is cut down to size",
      len(window2.report.splitlines()) < 80,
      len(window2.report.splitlines()))

print()
print("the old version comes in through the same door")
seen[:] = []
g["Qgis"] = types.SimpleNamespace(QGIS_VERSION_INT=32800, QGIS_VERSION="3.28.9")
g["warn_old_qgis"]()
check("it warns by way of the window", seen and seen[0][0] == "Startup",
      seen)
sentence, remedies = diagnose(g["OldQgis"](
    "QGIS 3.28.9 is older than the 3.36 Maidenhead this plugin was written "
    "on."), "Startup")
check("with a sentence of its own and not the generic one",
      "older than the one" in sentence, sentence)
check("and with the advice to update",
      any("Updating QGIS" in r for r in remedies), remedies)

# ----------------------------------- and here, admittedly, only the text
print()
print("checks on the source text (these are not real exercises)")
body = source.split("LEVEL_SUCCESS =", 1)[1]
for dead in ("QgsWkbTypes.PolygonGeometry", "QgsWkbTypes.LineGeometry",
             "Qgis.Info", "level=1,", ".exec_()"):
    check("%s is left nowhere in the body" % dead, dead not in body)
check("every command button goes through the net",
     "b.clicked.connect(shielded(slot, word))" in source)
check("and the panel starts from start(), not from main()",
      source.rstrip().endswith("start()"))

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
