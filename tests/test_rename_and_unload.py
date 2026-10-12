"""A class renamed from any window, and a plugin unloaded with a campaign open.

Two things that went wrong on the way out of an edit, each run with the real
method on a layer that edits the way QGIS's does (editkit), and each seen
failing here before it was fixed.

The rename. Panel.rename_features writes the new class name into every
feature, as one command on each table, and commits. With the marks locked, the
lock follows the undo stacks, and a commit that fails leaves the command on
the stack: the lock took it for an edit and walked it back. The rename in the
class bar told the lock it was the program's own edit; the Classes window
called rename_features without saying so, and the features lost the new name
while the legend kept it. The map paints by name, so they vanished from it.

The unload. Unloading the plugin, which the Plugin Manager also does before an
upgrade, left the campaign's layers in the project with the polygons and the
frames still in edit mode, owned by a program that was no longer there.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import sys

if not os.environ.get("RL_ROOT"):
    print("set RL_ROOT to the repository root")
    sys.exit(2)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import editkit as K
except ImportError as err:
    print("cannot build the kit: %s (pip install shapely)" % err)
    sys.exit(2)
from shapely.geometry import box

from rasterlabel import panel as P

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


said = []
P.log = lambda msg, loud=False: said.append(str(msg))


def campaign():
    polys = K.Layer("polygons")
    tiles = K.Layer("tiles")
    K.put(tiles, box(0, 0, 10, 10), tile_id="t001")
    a = K.put(polys, box(0, 0, 5, 10), class_name="a", class_code=1,
              tile_id="t001", pass_no=1, operator="OP1")
    b = K.put(polys, box(5, 0, 10, 10), class_name="b", class_code=2,
              tile_id="t001", pass_no=1, operator="OP1")
    host = K.Host(polys, tiles)
    polys.startEditing()
    host.remember_shapes()
    return host, polys, tiles, {"a": a, "b": b}


class Shell(object):
    """The panel, as far as the two methods under test reach into it."""
    rename_features = P.Panel.rename_features
    # absent before the fix, and the checks below say what that costs
    leave_layers = getattr(P.Panel, "leave_layers", None)
    pending_layers = P.Panel.pending_layers
    keep_safe = P.Panel.keep_safe

    def __init__(self, campaign, section=None, layers=None):
        self.campaign = campaign
        self.section = section
        self.recovery = None
        self.layers = layers or {}


def tables(layers):
    P.find_mine = lambda cid, role: layers.get(role)


# ---------------------------------------------------------- the rename
print("a class renamed from the Classes window, under the lock, with a commit "
      "that fails")
host, polys, tiles, ids = campaign()
host.lock_marks.setChecked(True)
host.locks_changed()
tables({"polygons": polys})
panel = Shell(host.campaign, section=host)
host.campaign.data["classes"][1]["name"] = "renamed"   # the legend, saved
polys.commit_ok = False                                 # the package refuses
said[:] = []
K.Bar.said[:] = []
renamed = panel.rename_features()
K.Loop.run()                                            # the lock looks
check("the rename reached the feature", renamed == 1, renamed)
check("the features keep the new name once the lock has looked",
      polys.getFeature(ids["b"])["class_name"] == "renamed",
      polys.getFeature(ids["b"])["class_name"])
check("the failure is said, and the rename waits to be saved",
      any("still waiting to be saved" in m for m in said), said)
check("nothing was announced as a mark put back",
      not any("put back" in str(m) for m in K.Bar.said), K.Bar.said)
check("the section is no longer marked as settling",
      host._settling is False, host._settling)
polys.drag(ids["a"], box(0, 0, 9, 10))                  # a drag, still locked
K.Loop.run()
check("and the lock still puts back a drag made after it",
      abs(K.shape_of(polys, ids["a"]).area - 50) < 1e-9,
      K.shape_of(polys, ids["a"]).area)
check("without taking the rename with it",
      polys.getFeature(ids["b"])["class_name"] == "renamed",
      polys.getFeature(ids["b"])["class_name"])

print()
print("the same rename, with a commit that works")
host, polys, tiles, ids = campaign()
host.lock_marks.setChecked(True)
host.locks_changed()
tables({"polygons": polys})
panel = Shell(host.campaign, section=host)
host.campaign.data["classes"][1]["name"] = "renamed"
renamed = panel.rename_features()
K.Loop.run()
check("the new name is written",
      polys.saved[ids["b"]]["class_name"] == "renamed",
      polys.saved[ids["b"]]["class_name"])
polys.drag(ids["a"], box(0, 0, 9, 10))
K.Loop.run()
check("and the lock holds afterwards",
      abs(K.shape_of(polys, ids["a"]).area - 50) < 1e-9,
      K.shape_of(polys, ids["a"]).area)

print()
print("a rename with no module open, or with one that holds no lock")
host, polys, tiles, ids = campaign()
tables({"polygons": polys})
host.campaign.data["classes"][1]["name"] = "renamed"
check("with no module open it renames", Shell(host.campaign).rename_features()
      == 1)


class Other(object):
    """Correct, Objects, Cutouts: no marks lock."""


other = Other()
host.campaign.data["classes"][1]["name"] = "again"
check("with another module open it renames",
      Shell(host.campaign, section=other).rename_features() == 1)
check("and leaves that module alone", not hasattr(other, "_settling"),
      vars(other))

# ---------------------------------------------------------- the unload
print()
print("unloading the plugin with a campaign open")
from rasterlabel import launch as LA                    # noqa: E402
from rasterlabel import plugin as PL                    # noqa: E402


class Net(object):
    """The recovery snapshot: what it was last asked to hold."""
    def __init__(self):
        self.held = None

    def note(self, pending):
        self.held = [role for role, _ in pending]


host, polys, tiles, ids = campaign()
lines, points, boxes = K.Layer("lines"), K.Layer("points"), K.Layer("boxes")
layers = {"polygons": polys, "tiles": tiles, "lines": lines,
          "points": points, "boxes": boxes}
tables(layers)
tiles.startEditing()                     # the frames, as Annotate leaves them
polys.beginEditCommand("stroke")         # and a stroke not yet saved
polys.addFeature(K.Feature(polys.fields(), None, box(0, 0, 1, 1),
                           class_name="a", class_code=1, tile_id="t001",
                           pass_no=1, operator="OP1"))
polys.endEditCommand()
points.startEditing()                    # a table whose commit will fail
points.beginEditCommand("point")
points.addFeature(K.Feature(points.fields(), None, box(0, 0, 1, 1),
                            class_name="a", class_code=1, tile_id="t001",
                            pass_no=1, operator="OP1"))
points.endEditCommand()
points.commit_ok = False


class Closing(Shell):
    """What shut_down asks of the panel, recorded."""
    closed = 0

    def close_module(self):
        Closing.closed += 1

    def let_go(self):
        return 0


panel = Closing(host.campaign, layers=layers)
panel.recovery = Net()
LA._RASTERLABEL = (object(), object(), panel)
plugin = PL.RasterLabelPlugin(iface=None)
said[:] = []
try:
    plugin.unload()
    raised = None
except Exception as err:
    raised = err
check("unload does not raise", raised is None, raised)
check("the panel was shut down first", Closing.closed == 1, Closing.closed)
check("and forgotten", getattr(LA, "_RASTERLABEL", None) is None)
check("the polygons are out of edit mode", not polys.isEditable())
check("the frames are out of edit mode", not tiles.isEditable())
check("the stroke that was waiting is on disk",
      len(polys.saved) == 3, len(polys.saved))
check("a table that was not being edited is left alone",
      not lines.isEditable())
check("a table that cannot be saved keeps its buffer and its edit mode",
      points.isEditable() and points.isModified())
check("and the recovery snapshot holds it", panel.recovery.held == ["points"],
      panel.recovery.held)
check("and the log says so",
      any("could not be saved" in m and "points" in m for m in said), said)

print()
print("unloading with no campaign open, and with no panel at all")
LA._RASTERLABEL = (object(), object(), Closing(None))
try:
    PL.RasterLabelPlugin(iface=None).unload()
    ok = True
except Exception as err:
    ok, why = False, err
check("no campaign: nothing to end, nothing raised", ok, locals().get("why"))
LA._RASTERLABEL = None
try:
    PL.RasterLabelPlugin(iface=None).unload()
    ok = True
except Exception as err:
    ok, why = False, err
check("no panel: nothing raised", ok, locals().get("why"))

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
