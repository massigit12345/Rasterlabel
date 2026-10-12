"""Strokes QGIS throws away keep their recovery file.

Closing QGIS with strokes not yet saved goes in this order: QGIS asks, table
by table, whether to save the edits; it closes the project, which takes every
layer out of it; and only then does it unload the plugins. By the time the
panel closed its module and looked at the buffers, a Discard had emptied
them, or the project had gone with them. Seeing nothing pending, the net
deleted its file, the one copy of that work left anywhere, and the log said
"Nothing was saved or lost, and the campaign is still open". That is how a
real campaign ended an evening with three strokes painted, no polygon in its
package and an empty recovery folder.

Now a buffer emptied without a save, by a rollback or by its layer leaving the
project, has its file set aside for the next Open campaign to offer back. What
this program rolls back or removes on purpose, under own_hands, is not that,
and neither is a save: those still empty the net. And taking the panel down no
longer says that nothing was saved or lost.

What is real here: keep_safe, watch, layers_leaving, buffer_let_go and
pending_layers of Panel, borrowed unchanged, the Recovery that writes the
files, and own_hands. What is a model: the layers, their signals and the
project, with only what those methods read.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import io
import os
import shutil
import sys
import tempfile

if not os.environ.get("RL_ROOT"):
    print("set RL_ROOT to the repository root")
    sys.exit(2)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_imports                                             # noqa: E402
harness_imports            # it builds the fakes on import

from rasterlabel import panel as P                                 # noqa: E402
from rasterlabel import recovery as R                              # noqa: E402
from rasterlabel.errors import own_hands                           # noqa: E402
from qgis.core import QgsProject                                   # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


# ---------------------------------------------------------------- the model
class Signal(object):
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def disconnect(self, slot):
        self.slots.remove(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class Geom(object):
    def __init__(self, wkt):
        self._wkt = wkt

    def asWkt(self):
        return self._wkt

    def isNull(self):
        return False


class Feature(object):
    def __init__(self, n):
        self.values = {"class_name": "crust", "class_code": 1}
        self._g = Geom("POLYGON ((%d 0, %d 0, %d 1, %d 0))" % (n, n + 1, n, n))

    def geometry(self):
        return self._g

    def __getitem__(self, key):
        return self.values[key]


class Field(object):
    def __init__(self, name):
        self._n = name

    def name(self):
        return self._n


class Buffer(object):
    def __init__(self):
        self.added = {}

    def addedFeatures(self):
        return dict(self.added)

    def changedGeometries(self):
        return {}

    def deletedFeatureIds(self):
        return []

    def changedAttributeValues(self):
        return {}


class Layer(object):
    """A campaign table: an edit buffer, a rollback that says so first, a
    commit that writes the buffer to a 'disk' and empties it."""

    def __init__(self, role):
        self.role = role
        self._id = role + "_id"
        self.props = {"rasterlabel/campaign": "camp", "rasterlabel/role": role}
        self.editing = True
        self.buf = Buffer()
        self.disk = 0
        self.beforeRollBack = Signal()

    def id(self):
        return self._id

    def name(self):
        return self.role

    def customProperty(self, key, default=None):
        return self.props.get(key, default)

    def fields(self):
        return [Field("class_name"), Field("class_code")]

    def editBuffer(self):
        return self.buf if self.editing else None

    def isEditable(self):
        return self.editing

    def isModified(self):
        return self.editing and bool(self.buf.added)

    def stroke(self):
        n = len(self.buf.added) + 1
        self.buf.added[-n] = Feature(n)

    def rollBack(self):
        self.beforeRollBack.emit()
        self.buf = Buffer()
        self.editing = False
        return True

    def commitChanges(self):
        self.disk += len(self.buf.added)
        self.buf = Buffer()
        self.editing = False
        return True


class Project(object):
    def __init__(self):
        self.layers = {}
        self.layersWillBeRemoved = Signal()

    def mapLayers(self):
        return dict(self.layers)

    def removeMapLayers(self, ids):
        self.layersWillBeRemoved.emit(list(ids))
        for i in ids:
            self.layers.pop(i, None)

    def clear(self):
        self.removeMapLayers(list(self.layers))


PROJECT = Project()
QgsProject.instance = classmethod(lambda cls: PROJECT)
P.QgsProject.instance = classmethod(lambda cls: PROJECT)


class Campaign(object):
    def __init__(self, folder):
        self.folder = folder
        self.data = {"id": "camp", "name": "camp"}


class Shell(object):
    """The panel, as far as the net under the buffers reads it."""

    def __init__(self, folder):
        self.campaign = Campaign(folder)
        self.recovery = R.Recovery(folder, "camp")
        PROJECT.layersWillBeRemoved.connect(self.layers_leaving)

    def let_go(self):
        for signal, handler in self.__dict__.pop("_hooks", []):
            try:
                signal.disconnect(handler)
            except Exception:
                pass
        try:
            PROJECT.layersWillBeRemoved.disconnect(self.layers_leaving)
        except Exception:
            pass


for name in ("keep_safe", "watch", "layers_leaving", "buffer_let_go",
             "pending_layers"):
    setattr(Shell, name, getattr(P.Panel, name))


def files(folder):
    where = os.path.join(folder, R.RECOVERY_FOLDER)
    if not os.path.isdir(where):
        return []
    return sorted(n for n in os.listdir(where) if n.endswith(R.SNAPSHOT_SUFFIX))


def start(*roles):
    folder = tempfile.mkdtemp(prefix="rl_let_go_")
    PROJECT.layers = {}
    layers = {}
    for role in roles:
        lyr = Layer(role)
        PROJECT.layers[lyr.id()] = lyr
        layers[role] = lyr
    shell = Shell(folder)
    return folder, shell, layers


def draw(shell, lyr, n=3):
    for _ in range(n):
        lyr.stroke()
        shell.keep_safe()           # what every stroke does


def close_qgis(shell, answer):
    """QgisApp::fileExit: the question for each table with edits, the
    project closed, the plugin unloaded."""
    for lyr in list(PROJECT.layers.values()):
        if lyr.isEditable() and lyr.isModified():
            if answer == "Save":
                lyr.commitChanges()
            elif answer == "Discard":
                lyr.rollBack()
    PROJECT.clear()
    shell.keep_safe()               # shut_down does this on the way out
    shell.let_go()


def waiting(folder, shell):
    return R.snapshots_waiting(folder, shell.recovery.session, "camp")


# ----------------------------------------------------------------- the cases
print("closing QGIS, the strokes not saved, Discard answered")
folder, shell, L = start("polygons", "lines")
draw(shell, L["polygons"])
check("three strokes are in the net", len(files(folder)) == 1, files(folder))
close_qgis(shell, "Discard")
left = waiting(folder, shell)
check("the file is still there after the plugin went",
      len(files(folder)) == 1 and len(left) == 1, files(folder))
if left:
    head, rows = left[0][1], left[0][2]
    check("with the three strokes in it", len(rows) == 3, len(rows))
    check("and how they were let go of, for the question at the next open",
          "discarded" in head.get("let_go", ""), head)
shutil.rmtree(folder, ignore_errors=True)

print()
print("closing QGIS, the layers taken out of the project with their edits")
folder, shell, L = start("polygons")
draw(shell, L["polygons"], 2)
close_qgis(shell, None)
left = waiting(folder, shell)
check("the file is kept, with both strokes",
      len(left) == 1 and len(left[0][2]) == 2, files(folder))
check("and it says they left with the project",
      left and "out of the project" in left[0][1].get("let_go", ""),
      left and left[0][1])
shutil.rmtree(folder, ignore_errors=True)

print()
print("closing QGIS, Save answered")
folder, shell, L = start("polygons")
draw(shell, L["polygons"])
close_qgis(shell, "Save")
check("the strokes are on disk", L["polygons"].disk == 3, L["polygons"].disk)
check("and the net is empty: nothing would be offered twice",
      files(folder) == [], files(folder))
shutil.rmtree(folder, ignore_errors=True)

print()
print("closing the campaign without saving, as asked: this program's own")
folder, shell, L = start("polygons")
draw(shell, L["polygons"])
with own_hands():
    L["polygons"].rollBack()
    PROJECT.removeMapLayers(list(PROJECT.layers))
shell.recovery.clear()              # what close_campaign does next
shell.keep_safe()
check("nothing is kept: the No meant no", files(folder) == [], files(folder))
shutil.rmtree(folder, ignore_errors=True)

print()
print("one table discarded, another still being drawn")
folder, shell, L = start("polygons", "lines")
draw(shell, L["polygons"], 2)
draw(shell, L["lines"], 1)
L["polygons"].rollBack()
check("two files: the polygons set aside, the lines still in the net",
      len(files(folder)) == 2, files(folder))
left = waiting(folder, shell)
check("only the polygons are offered back",
      len(left) == 1 and [r["role"] for r in left[0][2]] == ["polygons"] * 2,
      left and [r["role"] for r in left[0][2]])
mine = os.path.join(folder, R.RECOVERY_FOLDER,
                    shell.recovery.session + R.SNAPSHOT_SUFFIX)
check("and the lines are in this session's own file",
      os.path.exists(mine) and len(R.read_snapshot(mine)[1]) == 1)
L["lines"].commitChanges()
shell.keep_safe()
check("saving the lines empties the net and leaves the set-aside file alone",
      not os.path.exists(mine) and len(waiting(folder, shell)) == 1,
      files(folder))
L["polygons"].editing = True
draw(shell, L["polygons"], 1)
check("new strokes after it go in a new file, not over the kept one",
      len(files(folder)) == 2
      and len(R.read_snapshot(left[0][0])[1]) == 2, files(folder))
shutil.rmtree(folder, ignore_errors=True)

print()
print("a rollback with nothing in the buffer is no news")
folder, shell, L = start("polygons")
draw(shell, L["polygons"], 1)
L["polygons"].commitChanges()
shell.keep_safe()
L["polygons"].editing = True
L["polygons"].rollBack()
shell.keep_safe()
check("nothing is kept", files(folder) == [], files(folder))
shutil.rmtree(folder, ignore_errors=True)

print()
print("a project read again: the same table, as another object")
folder, shell, L = start("polygons")
draw(shell, L["polygons"], 1)
old = L["polygons"]
fresh = Layer("polygons")           # same id, nobody listens to it yet
PROJECT.layers[fresh.id()] = fresh
draw(shell, fresh, 2)
fresh.rollBack()
left = waiting(folder, shell)
check("its rollback is heard and the strokes are set aside",
      len(left) == 1 and "discarded" in left[0][1].get("let_go", ""),
      files(folder))
count = len(shell.__dict__.get("_hooks", []))
shell.keep_safe()
fresh.editing = True
fresh.stroke()
shell.keep_safe()
check("and a table already listened to is not hooked again",
      len(shell.__dict__.get("_hooks", [])) == count,
      (count, len(shell.__dict__.get("_hooks", []))))
shutil.rmtree(folder, ignore_errors=True)

print()
print("what the panel says when it is taken down")
launch = io.open(os.path.join(os.environ["RL_ROOT"], "rasterlabel", "launch.py"),
                 encoding="utf-8").read()
check("shut_down marks the panel before the dock goes",
      launch.index("panel.taken_down = True")
      < launch.index("iface.removeDockWidget(dock)"))
check("and closed() says nothing then: 'nothing was saved or lost' was not "
      "true on the way out", 'getattr(panel, "taken_down", False)' in launch)
panel = io.open(os.path.join(os.environ["RL_ROOT"], "rasterlabel", "panel.py"),
                encoding="utf-8").read()
check("the question at the next open says QGIS let go of them",
      "QGIS let go of them before they were saved" in panel)
check("close_campaign rolls back under own_hands",
      "with own_hands():\n                        lyr.rollBack()" in panel)

print()
print("FAILED: %d" % len(fails) if fails else "all of them pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
