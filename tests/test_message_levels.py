"""The four message levels, handed to a real QGIS message bar and message log.

PyQt5 let QgsMessageBar.pushMessage and QgsMessageLog.logMessage take a plain
int for the level. PyQt6 checks the type and refuses one. LEVEL_INFO was once
first_of("Qgis.MessageLevel.Info", "Qgis.Info") or 0, and Info is worth 0, so
on QGIS 4 the "or" threw the enum away and every message at that level raised
a TypeError: placing a frame, saving, opening Correct. Every other suite runs
against a stand-in message bar that takes anything, and all of them passed
with the bug in place. Only the real classes can tell, so this one uses them.

What has to hold, on QGIS 3 and on QGIS 4: each LEVEL_* in the shipped file is
the enum and not a bare int, is worth the number the message bar has always
meant by it, and is taken by a real QgsMessageBar and a real QgsMessageLog.
And log() in the package, which swallows its own errors, really puts its line
in the message log.

Needs QGIS itself, its Python and its classes. tests/run.py skips it where
QGIS is missing and, with RL_REQUIRE_QGIS=1, fails it instead.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.environ.get("RL_ROOT") or os.path.dirname(_HERE)
SRC = os.environ.get("RL_SRC", os.path.join(_ROOT, "dist", "rasterlabel.py"))

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail != "" and not cond else ""))
    if not cond:
        fails.append(name)


def finish():
    print()
    print("FAILED: %d" % len(fails) if fails else "all pass")
    for f in fails:
        print("   " + f)
    sys.stdout.flush()
    # os._exit: the QGIS application object is not torn down, and a teardown
    # that crashes would turn a passing run into a failed one.
    os._exit(1 if fails else 0)


try:
    from qgis.core import (Qgis, QgsApplication, QgsMessageLog, QgsUnitTypes,
                           QgsWkbTypes)
    from qgis.gui import QgsMessageBar
except ImportError as e:
    print("QGIS is not importable here: %s" % e)
    sys.exit(1)

app = QgsApplication([], True)
app.initQgis()
print("QGIS %s" % Qgis.QGIS_VERSION)

# The lookups exactly as the shipped file writes them: the two resolvers, the
# helper and the four assignments, taken from its syntax tree and run against
# the real Qgis.
tree = ast.parse(open(SRC, encoding="utf-8").read())
wanted = []
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in (
            "first_attr", "first_of", "_level"):
        wanted.append(node)
    elif isinstance(node, ast.Assign) and any(
            getattr(t, "id", "").startswith("LEVEL_") for t in node.targets):
        wanted.append(node)
ns = {"Qgis": Qgis, "QgsUnitTypes": QgsUnitTypes, "QgsWkbTypes": QgsWkbTypes}
exec(compile(ast.Module(body=wanted, type_ignores=[]), SRC, "exec"), ns)

print()
print("each level is the enum, worth what it has always meant")
bar = QgsMessageBar()
for name, number in (("LEVEL_INFO", 0), ("LEVEL_WARNING", 1),
                     ("LEVEL_CRITICAL", 2), ("LEVEL_SUCCESS", 3)):
    level = ns.get(name)
    check("%s is in the shipped file" % name, level is not None)
    if level is None:
        continue
    check("%s is not a bare int" % name, type(level) is not int,
          type(level).__name__)
    check("%s is worth %d" % (name, number), level == number, repr(level))
    try:
        bar.pushMessage("RasterLabel", "a test", level=level, duration=1)
        pushed = ""
    except Exception as e:
        pushed = "%s: %s" % (type(e).__name__, e)
    check("a real message bar takes %s" % name, not pushed, pushed)
    # pushWidget, which Whole uses for its "writing the whole raster", takes
    # the level as its second argument. It was handed a bare 0 there, and on
    # QGIS 4 every Whole raster stopped on the TypeError.
    try:
        item = bar.createMessage("RasterLabel", "a test")
        bar.pushWidget(item, level)
        bar.popWidget(item)
        widget = ""
    except Exception as e:
        widget = "%s: %s" % (type(e).__name__, e)
    check("a real message bar takes %s as the level of a widget" % name,
          not widget, widget)
    try:
        QgsMessageLog.logMessage("a test", "RasterLabel", level)
        logged = ""
    except Exception as e:
        logged = "%s: %s" % (type(e).__name__, e)
    check("a real message log takes %s" % name, not logged, logged)

print()
print("log() in the package reaches the message log")
# log() catches whatever logMessage raises, so a level PyQt6 refuses lost the
# line without a word. The real logMessage is wrapped, not replaced: the call
# still goes to QGIS, and what QGIS made of it is kept. The log's own
# messageReceived signal would be the more direct witness, but a standalone
# QGIS 4 does not emit it, so it cannot be waited for here.


class _Witness:
    calls = []

    @staticmethod
    def logMessage(*args, **kwargs):       # noqa: N802 (the QGIS name)
        try:
            QgsMessageLog.logMessage(*args, **kwargs)
        except Exception as e:
            _Witness.calls.append("%s: %s" % (type(e).__name__, e))
            raise
        _Witness.calls.append("")


sys.path.insert(0, _ROOT)
try:
    from rasterlabel import errors
    errors.QgsMessageLog = _Witness
    errors.log("a line that has to arrive")
    check("log() handed its line to the message log", bool(_Witness.calls))
    check("and the message log took it", _Witness.calls == [""],
          _Witness.calls)
except Exception as e:
    check("the package imports under this QGIS", False,
          "%s: %s" % (type(e).__name__, e))

print()
print("the frames get their numbers")
# Same family of mistake, found by hand on QGIS 4.2 and 3.44: the label
# placement was QgsPalLayerSettings.OverPoint, which 3.44 turned into a point
# position of another enum, and the placement setter refused it. label_tiles
# caught the TypeError and logged it, so the only sign was frames drawn
# without their tile_id. It is run here on a real layer, with a real setter.
try:
    from qgis.core import QgsVectorLayer
    from rasterlabel import layers
    said = []
    layers.log = lambda msg, *a, **k: said.append(str(msg))
    frames = QgsVectorLayer("Polygon?crs=EPSG:4326&field=tile_id:string"
                            "&field=note:string", "frames", "memory")
    layers.label_tiles(frames)
    refused = [x for x in said if "cannot label" in x]
    check("label_tiles says nothing went wrong", not refused, refused)
    check("the labels are switched on", frames.labelsEnabled())
    placed = frames.labeling().settings().placement \
        if frames.labeling() is not None else None
    check("over the centre of the frame",
          placed == Qgis.LabelPlacement.OverPoint, repr(placed))
except Exception as e:
    check("the frames can be labelled under this QGIS", False,
          "%s: %s" % (type(e).__name__, e))

finish()
