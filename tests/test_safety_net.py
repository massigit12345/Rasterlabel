"""The net under the edit buffers, and the doctor.

What is tested here is the part that only matters on the worst day: a snapshot
written after every stroke, readable by a person, surviving a write that was
interrupted half way, and offered back at the next open. Also that the log reaches
a file, and that the check button exists and reports without changing anything.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import io
import json
import os
import shutil
import sys
import tempfile

ROOT = os.environ.get("RL_ROOT")
if not ROOT:
    print("set RL_ROOT to the repository root")
    sys.exit(2)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_imports
harness_imports            # it builds the fakes on import

from rasterlabel import recovery                                   # noqa: E402
from rasterlabel import errors                                     # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


# ---------------------------------------------------------------- the fakes
class Geom(object):
    def __init__(self, wkt="POLYGON ((0 0, 1 0, 1 1, 0 0))", null=False):
        self._wkt = wkt
        self.null = null

    def isNull(self):
        return self.null

    def asWkt(self):
        return self._wkt


class Field(object):
    def __init__(self, name):
        self._n = name

    def name(self):
        return self._n


class Fields(object):
    def __init__(self, names):
        self._f = [Field(n) for n in names]

    def __iter__(self):
        return iter(self._f)


class Feature(object):
    def __init__(self, values, geom=None):
        self.values = dict(values)
        self._g = geom if geom is not None else Geom()

    def geometry(self):
        return self._g

    def __getitem__(self, key):
        return self.values[key]


class Buffer(object):
    def __init__(self, added=None, moved=None, gone=None, edited=None):
        self._a = added or {}
        self._m = moved or {}
        self._g = gone or []
        self._e = edited or {}

    def addedFeatures(self):
        return self._a

    def changedGeometries(self):
        return self._m

    def deletedFeatureIds(self):
        return self._g

    def changedAttributeValues(self):
        return self._e


class Layer(object):
    def __init__(self, names, buf):
        self._names = names
        self._buf = buf

    def fields(self):
        return Fields(self._names)

    def editBuffer(self):
        return self._buf


NAMES = ["class_name", "class_code", "tile_id", "pass_no", "operator", "created"]


def one_polygon(name="crust", code=1):
    return Feature({"class_name": name, "class_code": code, "tile_id": "t1",
                    "pass_no": 1, "operator": "MASSI", "created": "now"})


folder = tempfile.mkdtemp(prefix="rl_net_")
try:
    print("a stroke is written down at once, and can be read by a person")
    net = recovery.Recovery(folder, "abc123")
    pending = [("polygons", Layer(NAMES, Buffer({-1: one_polygon(),
                                                 -2: one_polygon("mud", 2)})))]
    n = net.note(pending)
    check("two things were written", n == 2, n)
    check("the file is there", os.path.exists(net.path), net.path)
    check("and no half written part is left beside it",
          not os.path.exists(net.path + ".part"))
    head, rows = recovery.read_snapshot(net.path)
    check("the header says which build and which campaign",
          head.get("campaign") == "abc123" and head.get("build"), head)
    check("both things came back", len(rows) == 2, len(rows))
    check("with their geometry as text",
          all(r["wkt"].startswith("POLYGON") for r in rows), rows[:1])
    check("and their fields",
          rows[0]["fields"]["operator"] == "MASSI", rows[0]["fields"])
    check("it is one JSON object per line, which a person can read",
          all(json.loads(l) for l in io.open(net.path, encoding="utf-8")
              if l.strip()))

    print()
    print("writing the same thing twice does not rewrite the file")
    before = os.path.getmtime(net.path)
    again = net.note(pending)
    check("it says the same count", again == 2, again)

    print()
    print("a moved vertex is recorded against the feature it belongs to")
    net2 = recovery.Recovery(folder, "abc123")
    moved = [("polygons", Layer(NAMES, Buffer({}, {57: Geom("POLYGON ((1 1, 2 1, 2 2, 1 1))")})))]
    net2.note(moved)
    _, rows = recovery.read_snapshot(net2.path)
    check("one entry", len(rows) == 1, rows)
    check("it knows it is a move", rows[0]["what"] == "moved", rows[0])
    check("and which feature", rows[0]["fid"] == 57, rows[0])

    print()
    print("nothing pending means no file: a stale net frightens people")
    net2.note([("polygons", Layer(NAMES, Buffer({}, {})))])
    check("the file is gone", not os.path.exists(net2.path))

    print()
    print("a snapshot cut off in the middle of a line still gives up its work")
    net3 = recovery.Recovery(folder, "abc123")
    net3.note([("polygons", Layer(NAMES, Buffer({-1: one_polygon(),
                                                 -2: one_polygon("mud", 2),
                                                 -3: one_polygon("salt", 3)})))])
    whole = io.open(net3.path, encoding="utf-8").read()
    cut = whole[:whole.rindex("\n", 0, len(whole) - 1) + 20]
    io.open(net3.path, "w", encoding="utf-8").write(cut)
    head, rows = recovery.read_snapshot(net3.path)
    check("the header survived", bool(head), head)
    check("and the two whole entries did too", len(rows) == 2, len(rows))

    print()
    print("what is waiting, and whose it is")
    waiting = recovery.snapshots_waiting(folder)
    check("both files with content are waiting", len(waiting) == 2,
          [os.path.basename(p) for p, _, _ in waiting])
    waiting = recovery.snapshots_waiting(folder, net.session)
    check("a session does not find its own net", len(waiting) == 1,
          [os.path.basename(p) for p, _, _ in waiting])
    line = recovery.describe_snapshot(*recovery.read_snapshot(net.path))
    check("and it can be described in one line",
          "polygons" in line and "build" in line, line)

    print()
    print("what was taken away is written down as well as what was put down")
    # This is the one that matters. add_merging, which runs on most brush
    # strokes, deletes the neighbours of the same class and adds one merged
    # polygon in their place. A snapshot that records the addition and not the
    # deletions puts the merged polygon back beside the three it replaced: the
    # same ground claimed twice, in a program whose first rule is that two marks
    # never share ground.
    net4 = recovery.Recovery(folder, "abc123")
    merged = Layer(NAMES, Buffer(added={-1: one_polygon("crust", 1)},
                                 gone=[11, 12, 13]))
    net4.note([("polygons", merged)])
    _, rows = recovery.read_snapshot(net4.path)
    kinds = sorted(r["what"] for r in rows)
    check("four entries, not one", len(rows) == 4, kinds)
    check("one addition", kinds.count("added") == 1, kinds)
    check("and three removals", kinds.count("deleted") == 3, kinds)
    check("each removal names the feature it took away",
          sorted(r["fid"] for r in rows if r["what"] == "deleted") == [11, 12, 13],
          [r.get("fid") for r in rows if r["what"] == "deleted"])
    line = recovery.describe_snapshot(*recovery.read_snapshot(net4.path))
    check("and the question says so, instead of calling them all drawings",
          "3 removals" in line, line)

    print()
    print("a feature added and deleted in the same session is not a removal")
    net5 = recovery.Recovery(folder, "abc123")
    net5.note([("polygons", Layer(NAMES, Buffer(gone=[-4, 7])))])
    _, rows = recovery.read_snapshot(net5.path)
    check("the negative id is left out: it never reached the file",
          [r["fid"] for r in rows] == [7], [r.get("fid") for r in rows])

    print()
    print("an attribute changed in the buffer is written down too")
    net6 = recovery.Recovery(folder, "abc123")
    net6.note([("polygons", Layer(NAMES, Buffer(
        edited={9: {0: "dry crust"}})))])
    _, rows = recovery.read_snapshot(net6.path)
    check("one entry", len(rows) == 1, rows)
    check("it knows it is a change", rows[0]["what"] == "attrs", rows[0])
    check("by name, not by column number",
          rows[0]["fields"] == {"class_name": "dry crust"}, rows[0])
    for leftover in (net4, net5, net6):
        recovery.keep_snapshot(leftover.path)

    print()
    print("a snapshot belonging to another campaign is not offered back")
    other = recovery.Recovery(folder, "a-different-campaign")
    other.note(pending)
    seen = recovery.snapshots_waiting(folder, "", "abc123")
    check("it is left alone",
          all(h.get("campaign") == "abc123" for _, h, _ in seen),
          [h.get("campaign") for _, h, _ in seen])
    check("and asking without naming a campaign still finds everything",
          len(recovery.snapshots_waiting(folder)) > len(seen))
    recovery.keep_snapshot(other.path)

    print()
    print("a snapshot that has been dealt with is kept, not deleted")
    kept = recovery.keep_snapshot(net.path)
    check("renamed", kept and kept.endswith(".restored"), kept)
    check("the original is gone", not os.path.exists(net.path))
    check("and the work is still there", os.path.exists(kept))

    print()
    print("a snapshot discarded is kept too, and Check can find both")
    turned_down = recovery.Recovery(folder, "abc123")
    turned_down.note(pending)
    gone = recovery.keep_snapshot(turned_down.path,
                                  recovery.DISCARDED_SUFFIX)
    check("renamed .discarded", gone and gone.endswith(".discarded"), gone)
    check("and not offered again",
          not any(p == turned_down.path or p == gone for p, _, _ in
                  recovery.snapshots_waiting(folder, "", "abc123")))
    aside = recovery.snapshots_set_aside(folder, "abc123")
    kinds = sorted((os.path.basename(p), how) for p, how, _, _ in aside)
    check("the files set aside are listed, each with how",
          (os.path.basename(gone), "discarded") in kinds
          and (os.path.basename(kept), "restored") in kinds, kinds)
    check("with what is in them",
          all(rows for _p, how, _h, rows in aside if how == "discarded"))
    check("and not another campaign's",
          all(h.get("campaign") in ("abc123", None) for _, _, h, _ in aside),
          [h.get("campaign") for _, _, h, _ in aside])

    print()
    print("the net never brings the program down")
    broken = recovery.Recovery(os.path.join(folder, "no", "such", "place"), "x")
    broken.folder = "\0 not a path"
    out = broken.note(pending)
    check("a folder it cannot write returns None instead of raising", out is None)

    print()
    print("the log reaches a file that outlives the session")
    path = errors.log_to(folder)
    check("it says where it is", path and os.path.basename(path) ==
          errors.LOG_NAME, path)
    errors.log("something worth keeping")
    text = io.open(path, encoding="utf-8").read()
    check("the line is in the file", "something worth keeping" in text)
    check("with a time in front of it", text.splitlines()[-1][:4].isdigit(),
          text.splitlines()[-1][:20])
    check("and the build is at the top", "build" in text.splitlines()[0])
    errors.log_to(None)
    errors.log("after the campaign was closed")
    check("nothing is written once the campaign is closed",
          "after the campaign" not in io.open(path, encoding="utf-8").read())
finally:
    shutil.rmtree(folder, ignore_errors=True)
    errors.log_to(None)

# ------------------------------------------------------ the doctor, and the text
print()
print("the doctor says something sensible with no campaign open")
from rasterlabel import doctor                                     # noqa: E402

text, bad, notes = doctor.report(None)
check("it produces a report", len(text) > 200, len(text))
check("it names the build", "build" in text)
check("it says what is running", "WHAT IS RUNNING" in text)
check("it says no annotation campaign is open",
      "no annotation campaign is open" in text)
# And as a note, not an alarm: Correct and Cutouts are used with no campaign.
check("and that Correct and Cutouts do not need one",
      "Correct and Cutouts do not" in text)
check("and finds nothing broken in the machine itself", bad == 0, bad)

print()
print("checks on the text of the package")
src = io.open(os.path.join(ROOT, "dist", "rasterlabel.py"), encoding="utf-8").read()
check("every stroke arms the net", "self.panel.keep_safe()" in src)
check("the net records removals", "deletedFeatureIds()" in src)
check("and changes to what was already there", "changedAttributeValues()" in src)
check("a restore replays removals before new marks",
      '"deleted": 0' in src and '"added": 3' in src)
check("the panel has a Check button", '"Check"' in src)
check("opening a campaign offers back what was never saved",
      "def offer_recovery" in src)
check("and it asks rather than putting things back by itself",
      "Put them back?" in src)
check("a declined recovery keeps the file",
      "keep_snapshot(path)" in src)
check("and the question has a Discard beside Not now, which renames nothing",
      'addButton("Discard"' in src
      and "keep_snapshot(path, DISCARDED_SUFFIX)" in src)
check("the log file starts when a campaign opens", "log_to(" in src)
check("the doctor changes nothing: no commit, no write, in its own module",
      "commitChanges" not in io.open(
          os.path.join(ROOT, "rasterlabel", "doctor.py"), encoding="utf-8").read())

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
