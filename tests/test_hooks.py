"""The places where the measuring modules plug in, run with nothing plugged
in and with a stand-in that records what it is told.

Correct (with QGIS faked, correctkit):

- with no hook registered a stroke, its undo, Save and Close do what they
  did, and the history keeps a place for what the hooks would keep;
- a hook registered in measure.CORRECT_HOOKS is built with the module and
  told of every stroke once it is on disk, with the window, the pixels
  inside it and the pixels changed, from what into what and how much; what
  it answers is kept with the stroke and handed back to it on undo; Save
  flushes it, Close flushes it and lets it go, once; the files it names
  beside the copy, and reports/, are the correction's own; at most two
  lines of what the hooks say go under the tally;
- a stroke that is not written is not told; a hook that fails is said in
  the log and the stroke stands; the hooks share what they are told, so one
  can leave a word for the next.

The layers of the reports:

- add_report_layer puts a report's layer in a group of its own, marked with
  the readings it shows, and a report run again replaces its own older
  layer;
- veil_report_layers switches off, and never removes, the layers that show
  a reading the reader may not see, by the rule of the Annotate filter, and
  leaves the others alone; the panel asks it with the reading it holds.

The frames (in a child, on the edit kit, with GEOS behind the geometry):

- a frame placed, moved or deleted is told to every listener of
  measure.FRAME_LISTENERS after its commit, with its boxes before and
  after; never when the commit fails; a listener that fails does not keep
  the others from hearing.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import correctkit as K                                             # noqa: E402
import numpy as np                                                 # noqa: E402

g, check = K.g, K.check

CROPS, ROADS, FOREST, NODATA = 3, 7, 12, 255
MAP = np.array([
    [CROPS, CROPS, CROPS, CROPS, ROADS, FOREST],
    [CROPS, CROPS, CROPS, CROPS, ROADS, FOREST],
    [ROADS, ROADS, ROADS, ROADS, ROADS, FOREST],
    [FOREST, FOREST, FOREST, FOREST, FOREST, FOREST],
], dtype=np.uint8)

root = tempfile.mkdtemp(prefix="rl_hooks_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
source = os.path.join(root, "data", "model.tif")
K.write_map(source, MAP, NODATA)
styled = K.Paletted(None, 1, [
    K.Paletted.Class(CROPS, "#e6c229", "crops"),
    K.Paletted.Class(ROADS, "#444444", "roads"),
    K.Paletted.Class(FOREST, "#1b7f2a", "forest")])
thematic = K.add_layer(K.Layer(source, "model", styled))
# a second map for the second correction: a map already corrected once is
# asked about before a second correction of it starts
source2 = os.path.join(root, "data", "model_b.tif")
K.write_map(source2, MAP, NODATA)
thematic2 = K.add_layer(K.Layer(source2, "model_b", styled))


def opened_in(folder, layer):
    def answer(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText(os.path.basename(folder))
        d.raster.setCurrentIndex(d.raster.findData(layer.id()))
        d.fill_bands()
        d.folder.setText(folder)
        d.operator.setText("ann")
        return 1
    return answer


def open_correct(folder, layer):
    K.ANSWERS["OpenCorrection"] = opened_in(folder, layer)
    K.ANSWERS["ConfirmClasses"] = lambda d: 1
    panel.toggle_module(1)
    return panel.section


def stroke(section, rows=(0, 2), cols=(0, 3)):
    inside = np.zeros((rows[1] - rows[0], cols[1] - cols[0]), bool)
    inside[:, :] = True
    section.mask_of = lambda geom: (cols[0], rows[0], inside)
    section.choose_from(CROPS)
    section.choose_class(FOREST)
    section.paint(K.Stroke())


panel = g["Panel"]()

# ------------------------------------------------------------ no hooks at all
print("Correct with no hook registered")
plain = os.path.join(root, "plain_fix")
# the hooks this build ships (the journal's) are taken out for this part:
# what is checked is Correct as it is with nothing plugged in
shipped = list(g["CORRECT_HOOKS"])
g["CORRECT_HOOKS"][:] = []
section = open_correct(plain, thematic)
check("Correct opened", type(section).__name__ == "CorrectionSection",
      type(section).__name__)
check("it holds no hook", section.stroke_hooks == [], section.stroke_hooks)
stroke(section)
copy = section.path
check("a stroke is made as before",
      (K.read_map(copy)[0:2, 0:3] == FOREST).all(), K.read_map(copy))
check("and the history keeps a place for what the hooks would keep",
      len(section.history) == 1 and section.history[-1][4] == [],
      section.history[-1][4:] if section.history else None)
section.undo()
check("undo puts it back", (K.read_map(copy) == MAP).all(), K.read_map(copy))
check("the slot after Save is there, and empty",
      isinstance(section.measure_slot, K.QtWidgets.QVBoxLayout)
      and section.measure_slot.count() == 0)
check("reports/ is the correction's own",
      "reports" in section.own_files(), section.own_files())
section.save()
panel.close_correction()
check("Save and Close go as before", panel.section is None)
g["CORRECT_HOOKS"][:] = shipped

# ------------------------------------------------------- a hook that records
print()
print("a hook, told of every stroke")
CALLS = []


class Recorder(object):
    """What a measuring module would be: it keeps what it is told."""

    def __init__(self, section):
        self.section = section
        self.n = 0
        CALLS.append(("built", type(section).__name__))

    def stroke(self, section, ctx):
        self.n += 1
        CALLS.append(("stroke", dict(ctx)))
        ctx["place"] = "P%d" % self.n          # a word for the next hook
        return "state %d" % self.n

    def undo(self, section, state):
        CALLS.append(("undo", state))

    def flush(self, section):
        CALLS.append(("flush",))

    def closing(self, section):
        CALLS.append(("closing",))

    def files(self, section):
        here = os.path.dirname(section.path)
        return [os.path.join(here, "model_b_corrected_reviewed.tif"),
                os.path.join(root, "elsewhere.tif")]

    def tally_lines(self, section):
        return ["reviewed %d strokes" % self.n, "second line", "third line"]


class Second(object):
    """A hook after it, which reads the word the first one left."""

    def __init__(self, section):
        pass

    def stroke(self, section, ctx):
        CALLS.append(("second", ctx.get("place")))
        return None


class Broken(object):
    """A hook that fails at everything it is asked."""

    def __init__(self, section):
        pass

    def stroke(self, section, ctx):
        raise RuntimeError("the sidecar is locked")

    def undo(self, section, state):
        raise RuntimeError("never reached: it kept nothing")


class Unbuildable(object):
    def __init__(self, section):
        raise RuntimeError("cannot be built")


kept = list(g["CORRECT_HOOKS"])
g["CORRECT_HOOKS"][:] = [("nowhere", Recorder), ("nowhere", "no_such_hook"),
                         ("nowhere", Unbuildable), ("nowhere", Broken),
                         ("nowhere", Second)]
try:
    fix = os.path.join(root, "hooked_fix")
    section = open_correct(fix, thematic2)
    hooks = section.stroke_hooks
    check("the hooks are built with the module, in their order; the one "
          "missing and the one that cannot be built are left out",
          [type(h).__name__ for h in hooks] == ["Recorder", "Broken",
                                               "Second"],
          [type(h).__name__ for h in hooks])
    check("and Correct opened all the same",
          type(section).__name__ == "CorrectionSection")
    del CALLS[:]
    stroke(section)
    told = [c for c in CALLS if c[0] == "stroke"]
    check("a stroke is told once, after it is on disk",
          len(told) == 1 and (K.read_map(section.path)[0:2, 0:3]
                              == FOREST).all(), CALLS)
    ctx = told[0][1] if told else {}
    check("with its window",
          (ctx.get("col"), ctx.get("row"), ctx.get("width"),
           ctx.get("height")) == (0, 0, 3, 2), ctx)
    check("the pixels inside it and the ones it changed",
          ctx.get("inside") is not None and ctx["inside"].shape == (2, 3)
          and int(ctx["change"].sum()) == 6, ctx.get("change"))
    check("from what into what, and how many",
          (ctx.get("from_code"), ctx.get("into"), ctx.get("pixels"))
          == (CROPS, FOREST, 6), ctx)
    check("its number and its middle",
          ctx.get("n") == section.operations == 1
          and (ctx.get("x"), ctx.get("y")) == (500004.0, 4099996.0), ctx)
    check("and every key the measuring modules read",
          set(ctx) >= {"col", "row", "width", "height", "inside", "change",
                       "from_code", "into", "pixels", "changed_m2",
                       "swept_m2", "n", "x", "y", "place"}, sorted(ctx))
    check("the hooks share it: the next one reads the word left for it",
          ("second", "P1") in CALLS, CALLS)
    check("what each kept is kept with the stroke, in their order",
          section.history[-1][4] == ["state 1", None, None],
          section.history[-1][4])
    check("a hook that failed is said in the log and the stroke stands",
          (K.read_map(section.path)[0:2, 0:3] == FOREST).all())
    tally = section.tally.text()
    check("two lines of what the hooks say go under the tally, no more",
          "reviewed 1 strokes" in tally and "second line" in tally
          and "third line" not in tally, tally)

    del CALLS[:]
    section.undo()
    check("undo gives each hook back what it kept, and nothing to the "
          "others", CALLS == [("undo", "state 1")], CALLS)
    check("and the pixels come back",
          (K.read_map(section.path) == MAP).all())

    del CALLS[:]
    section.write_stroke = lambda *a: False
    stroke(section)
    check("a stroke that could not be written is not told",
          not [c for c in CALLS if c[0] == "stroke"], CALLS)
    del section.write_stroke

    mine = section.own_files()
    check("the files a hook keeps beside the copy are the correction's own",
          "model_b_corrected_reviewed.tif" in mine, mine)
    check("one it names elsewhere is not", "elsewhere.tif" not in mine, mine)
    check("and reports/ is too", "reports" in mine, mine)

    del CALLS[:]
    section.save()
    check("Save flushes the hooks", CALLS == [("flush",)], CALLS)
    del CALLS[:]
    panel.close_correction()
    check("Close flushes them and lets them go",
          CALLS == [("flush",), ("closing",)], CALLS)
    del CALLS[:]
    section.close_dataset()
    check("once: closing again tells them nothing", CALLS == [], CALLS)
finally:
    g["CORRECT_HOOKS"][:] = kept

# --------------------------------------------------------- the report layers
print()
print("the layers of the reports")


class Group(object):
    """A group of the layers panel, with the groups and layers in it."""

    def __init__(self, name=""):
        self.name, self.groups, self.layers = name, {}, []

    def findGroup(self, name): return self.groups.get(name)

    def addGroup(self, name):
        self.groups[name] = Group(name)
        return self.groups[name]

    def addLayer(self, layer):
        self.layers.append(layer.id())
        K.TREE[layer.id()] = True
        return K.Node(layer.id())


TOP = {}
K.Node.itemVisibilityChecked = lambda self: K.TREE.get(self.lid, True)
K.Root.findGroup = lambda self, name: TOP.get(name)
K.Root.insertGroup = lambda self, i, name: TOP.setdefault(name, Group(name))


class Owner(object):
    data = {"id": "camp1"}
    group_name = "RasterLabel aragona"


def report_layer(lid):
    return K.Layer(os.path.join(root, lid + ".tif"), lid, lid=lid)


a = g["add_report_layer"](report_layer("pairs_1"), Owner(), "agreement",
                          "ANNA_p1_vs_BRUNO_p1", "pairs",
                          readings=[("ANNA", 1), ("BRUNO", 1)])
group = TOP["RasterLabel aragona"].findGroup("agreement ANNA p1 vs BRUNO p1")
check("a report's layer goes in a group of its own under its owner's",
      group is not None and group.layers == ["pairs_1"],
      {k: v.groups.keys() for k, v in TOP.items()})
check("marked as the owner's, with what it is and the readings it shows",
      a.customProperty("rasterlabel/campaign") == "camp1"
      and a.customProperty("rasterlabel/report") == "agreement"
      and a.customProperty("rasterlabel/readings") == "ANNA,1;BRUNO,1",
      a._props)
b = g["add_report_layer"](report_layer("pairs_2"), Owner(), "agreement",
                          "ANNA_p1_vs_BRUNO_p1", "pairs",
                          readings=[("ANNA", 1), ("BRUNO", 1)])
check("run again, the report's new layer replaces its older one",
      "pairs_1" not in K.LOADED and "pairs_2" in K.LOADED,
      sorted(K.LOADED))
own = g["add_report_layer"](report_layer("anna_only"), Owner(), "time",
                            None, "frames", readings=[("ANNA", 1)])
second = g["add_report_layer"](report_layer("anna_p2"), Owner(), "agreement",
                               "ANNA_p1_vs_ANNA_p2", "pairs",
                               readings=[("ANNA", 1), ("ANNA", 2)])
plain_layer = K.add_layer(report_layer("not_a_report"))
plain_layer.setCustomProperty("rasterlabel/campaign", "camp1")

n = g["veil_report_layers"]("camp1", ("ANNA", 1), True, True)
check("one operator at a time: the layer that shows BRUNO is switched off",
      K.TREE["pairs_2"] is False, dict(K.TREE))
check("blind shows only the pass in hand: the layer that shows ANNA's pass "
      "2 is switched off for the reader of pass 1",
      K.TREE["anna_p2"] is False, dict(K.TREE))
check("and the one that shows only her pass 1 stays on",
      K.TREE["anna_only"] is True, dict(K.TREE))
check("a layer of the campaign that is not a report is left alone",
      K.TREE["not_a_report"] is True)
check("nothing is taken out of the project",
      {"pairs_2", "anna_only", "anna_p2"} <= set(K.LOADED))
check("and it says how many are veiled", n == 2, n)
n = g["veil_report_layers"]("camp1", ("ANNA", 2), False, True)
check("a blind second pass: the layer that shows pass 1 goes off too",
      K.TREE["anna_p2"] is False and K.TREE["anna_only"] is False, n)
K.TREE["anna_p2"] = K.TREE["anna_only"] = K.TREE["pairs_2"] = True
n = g["veil_report_layers"]("camp1", ("ANNA", 1), False, False)
check("with the filter off nothing is switched off",
      n == 0 and all(K.TREE[l] for l in ("pairs_2", "anna_only", "anna_p2")),
      n)
n = g["veil_report_layers"]("other", ("ANNA", 1), True, True)
check("another campaign's veil does not touch these", n == 0
      and K.TREE["pairs_2"] is True, n)


class Campaign(object):
    data = {"id": "camp1", "operator": "ANNA", "operators": ["ANNA", "BRUNO"]}


panel.campaign = Campaign()
panel._reading = {"campaign": "camp1", "operator": "BRUNO", "pass": 1,
                  "blind": True, "by_operator": True}
n = panel.veil_reports()
check("the panel veils with the reading it holds: BRUNO may not see "
      "ANNA's layers", n == 3 and not K.TREE["anna_only"]
      and not K.TREE["pairs_2"], (n, dict(K.TREE)))
panel.campaign = None
check("and with no campaign open there is nothing to veil",
      panel.veil_reports() == 0)

# ------------------------------------------------------------- the frames
print()
print("the frames, told after their commit (in a child, on the edit kit)")
CHILD = r'''
import os, sys
sys.path.insert(0, sys.argv[1])
import editkit as K
from shapely.geometry import box

fails = []
def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


class Ask(object):
    Warning = Cancel = AcceptRole = DestructiveRole = 0
    answer = 0
    def __init__(self, *a): self.buttons = []
    def setIcon(self, *a): pass
    def setWindowTitle(self, *a): pass
    def setText(self, t): pass
    def setInformativeText(self, *a): pass
    def setDefaultButton(self, *a): pass
    def button(self, *a): return None
    def addButton(self, *a):
        b = object()
        self.buttons.append(b)
        return b
    def clickedButton(self): return self.buttons[Ask.answer]


Ask.Icon = Ask.StandardButton = Ask.ButtonRole = Ask
K.SA.QMessageBox = Ask
K.SA.run_dialog = lambda d: None
K.SA.crs_label = lambda crs: "the campaign CRS"

HEARD = []


def listener(section, kind, tid, before, after, feature):
    HEARD.append((kind, tid, before, after, feature is not None))


def failing(*a):
    raise RuntimeError("the journal is locked")


class Panel(K.Panel):
    def frame_listeners(self):
        return [failing, listener]


class Centre(K.Pt):
    def toString(self, n): return "%.*f, %.*f" % (n, self.x(), n, self.y())


def campaign():
    tables = {r: K.Layer(r) for r in ("polygons", "lines", "points", "boxes")}
    tiles = K.Layer("tiles")
    K.put(tiles, box(0, 0, 10, 10), tile_id="t001")
    K.put(tiles, box(20, 0, 30, 10), tile_id="t002")
    host = K.Host(tables["polygons"], tiles)
    host.layers.update(tables)
    host.panel = Panel()
    host.refresh_tiles = lambda: None
    host.tile_side = K.Spin(10.0)
    host.geometry.crs = None
    host.lock_view = K.Tick(False)
    host.select_tile = lambda tid: None
    host.use_brush = lambda: None
    host.free_tile_id = lambda: "t009"
    return host, tiles


def frame(tiles, tid):
    return [f for f in tiles.getFeatures() if f["tile_id"] == tid][0]


K.Box.center = lambda b: Centre((b.b[0] + b.b[2]) / 2, (b.b[1] + b.b[3]) / 2)

host, tiles = campaign()
host.create_tile(Centre(45.0, 5.0))
check("a frame placed is told, once, after its commit",
      HEARD == [("new", "t009", None, (40.0, 0.0, 50.0, 10.0), True)], HEARD)
check("and a listener that fails does not keep the next from hearing",
      len(HEARD) == 1)
del HEARD[:]
host, tiles = campaign()
tiles.commit_ok = False
host.create_tile(Centre(45.0, 5.0))
check("one whose commit fails is not told", HEARD == [], HEARD)

del HEARD[:]
host, tiles = campaign()
for lyr in host.layers.values():
    lyr.startEditing()
host.move_tile(frame(tiles, "t002"), 10.0, 0.0)
K.Loop.run()
check("a frame moved is told with where it was and where it is",
      HEARD == [("move", "t002", (20.0, 0.0, 30.0, 10.0),
                 (30.0, 0.0, 40.0, 10.0), True)], HEARD)
del HEARD[:]
host, tiles = campaign()
for lyr in host.layers.values():
    lyr.startEditing()
tiles.commit_ok = False
host.move_tile(frame(tiles, "t002"), 10.0, 0.0)
K.Loop.run()
check("a move whose commit fails is not told", HEARD == [], HEARD)

del HEARD[:]
host, tiles = campaign()
host._tile = "t002"
host.delete_tile()
check("a frame deleted is told with where it was",
      HEARD == [("delete", "t002", (20.0, 0.0, 30.0, 10.0), None, True)],
      HEARD)
del HEARD[:]
host, tiles = campaign()
host._tile = "t002"
tiles.commit_ok = False
host.delete_tile()
check("a delete whose commit fails is not told", HEARD == [], HEARD)

del HEARD[:]
host, tiles = campaign()
host.frame_event("import", "t010", None, (0.0, 0.0, 1.0, 1.0), None)
check("Import frames can tell them through the same door",
      HEARD == [("import", "t010", None, (0.0, 0.0, 1.0, 1.0), False)],
      HEARD)
host.panel = K.Panel()
host.frame_event("new", "t011", None, None, None)
check("with nobody listening it does nothing", len(HEARD) == 1, HEARD)

print("CHILD", "bad" if fails else "clean")
'''
child = os.path.join(tempfile.mkdtemp(prefix="rl_hooks_child_"), "frames.py")
with open(child, "w", encoding="utf-8") as f:
    f.write(CHILD)
env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
env.setdefault("RL_ROOT", os.path.dirname(HERE))
out = subprocess.run([sys.executable, child, HERE], capture_output=True,
                     env=env, encoding="utf-8", errors="replace")
for line in (out.stdout + out.stderr).splitlines():
    if line.startswith(("  ok", "  FAIL", "Traceback", "  File")) or \
            "Error" in line:
        print(line)
check("the frames: every case ran and held", "CHILD clean" in out.stdout,
      out.stderr[-600:])

# ------------------------------------------------------- the amber strip
print()
print("the amber strip says when measures are switched off (Annotate, drawn)")
STRIP = r'''
ASKED = []
def veil(*a, **k):
    ASKED.append(a)
    return VEILED[0]
VEILED = [2]
panel.veil_reports = veil
section.blind.setChecked(True)
section.pass_no.setValue(2)
section.show_blind()
LINE = "Measures that show work hidden from you are switched off."
print("ASKED", ASKED[-1] if ASKED else None)
print("WITH", LINE in section.blind_note.text() and not
      section.blind_note.isHidden())
VEILED[0] = 0
section.show_blind()
print("WITHOUT", LINE not in section.blind_note.text())
'''
probe = os.path.join(os.path.dirname(child), "strip.py")
with open(probe, "w", encoding="utf-8") as f:
    f.write(STRIP)
with open(os.path.join(HERE, "harness2.py"), encoding="utf-8") as f:
    code = f.read().replace('panel.grab().save(out)',
                            'exec(open(r"%s", encoding="utf-8").read())'
                            % probe)
runner = os.path.join(os.path.dirname(child), "run_strip.py")
with open(runner, "w", encoding="utf-8") as f:
    f.write(code.replace("_os.path.abspath(__file__)",
                         "_os.path.abspath(%r)"
                         % os.path.join(HERE, "harness2.py")))
env["PYTHONPATH"] = HERE + os.pathsep + env.get("PYTHONPATH", "")
out = subprocess.run([sys.executable, runner, "300", "annotation"],
                     capture_output=True, env=env, encoding="utf-8",
                     errors="replace", cwd=HERE)
said = {l.split(" ", 1)[0]: l.split(" ", 1)[1] for l in
        out.stdout.splitlines() if l.split(" ", 1)[0] in
        ("ASKED", "WITH", "WITHOUT") and " " in l}
check("Annotate asks the panel with its own reader and switches",
      said.get("ASKED") == "(('MG', 2), True, True)", (said,
                                                       out.stderr[-400:]))
check("a line in the strip while measures are switched off",
      said.get("WITH") == "True", said)
check("and none when nothing is", said.get("WITHOUT") == "True", said)

sys.exit(K.finish())
