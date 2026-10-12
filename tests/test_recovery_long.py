"""The safety net works in a deep folder.

The recovery file lives in <campaign folder>/recovery/<session>.jsonl and is
written through <name>.part. With a campaign folder of 227 to 235 characters
the folder itself is below the 248 at which long_path() takes over, so every
path built from it by hand was above the 260 that Windows refuses without the
\\\\?\\ prefix: the net could not make its folder, write its file, find it
again at the next open or keep it after a restore, and said nothing but one
line in the log. The one folder in the range where the whole campaign works
and the net does not.

Here the folder is made 236 characters long (on Windows; elsewhere the paths
are what they are and the suite only shows the net still works), and the
Recovery class and the readers that look for what it left are run for real.
The code is lifted out of the built file, as written.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import io
import json
import os
import shutil
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
SRC = os.environ.get("RL_SRC") or os.path.join(ROOT, "dist", "rasterlabel.py")
source = io.open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)

fails = []


def check(name, cond, detail=""):
    cond = bool(cond)
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)[:300]) if not cond else ""))
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


said = []
g = {"os": os, "io": io, "json": json, "time": time, "uuid": uuid,
     "NAME": "RasterLabel", "VERSION": "t", "BUILD": "t",
     "log": lambda m, loud=False: said.append(str(m))}
for name in ("long_path", "RECOVERY_FOLDER", "SNAPSHOT_SUFFIX",
             "RESTORED_SUFFIX", "DISCARDED_SUFFIX", "MANY_PENDING",
             "_is_null", "_recovery_session", "Recovery", "snapshots_waiting",
             "read_snapshot", "keep_snapshot", "snapshots_set_aside"):
    exec(take(name), g)
long_path = g["long_path"]

base = tempfile.mkdtemp(prefix="rl_recovery_long_")
try:
    folder = base
    n = 0
    while len(folder) < 236:
        n += 1
        room = min(40, 236 - len(folder) - 1)
        if room < 1:
            break
        folder = os.path.join(folder, "d" * room)
    os.makedirs(long_path(folder), exist_ok=True)
    print("a campaign folder of %d characters" % len(folder))
    net = g["Recovery"](folder, "cid")
    check("the file of the net would be past the limit of Windows",
          len(net.path) > 260 or os.name != "nt", len(net.path))
    row = {"role": "polygons", "what": "added", "wkt": "POLYGON ((0 0,1 0,1 1,0 0))",
           "fields": {"class_name": "a"}}
    head = {"program": "RasterLabel", "campaign": "cid", "session": net.session,
            "features": 1}
    text = "\n".join(json.dumps(r) for r in [head, row]) + "\n"
    try:
        net._write(text)
        wrote = True
    except OSError as err:
        wrote = err
    check("the net writes its file", wrote is True, wrote)
    check("and it is there", os.path.exists(long_path(net.path)))
    check("no .part is left behind",
          not os.path.exists(long_path(net.path + ".part")))

    other = g["Recovery"](folder, "cid")
    waiting = g["snapshots_waiting"](folder, session=other.session,
                                     campaign_id="cid")
    check("the next open finds what the last session left",
          len(waiting) == 1 and waiting[0][2][0]["what"] == "added",
          (waiting, said))
    kept = g["keep_snapshot"](net.path)
    check("a restored file is kept under its new name",
          kept is not None and os.path.exists(long_path(kept))
          and not os.path.exists(long_path(net.path)), (kept, said))
    check("and Check lists it",
          len(g["snapshots_set_aside"](folder, "cid")) == 1)

    net2 = g["Recovery"](folder, "cid")
    net2._write(text)
    net2.last = text
    check("a net with nothing pending takes its file away",
          net2.clear() == 0 and not os.path.exists(long_path(net2.path)),
          said)
    net3 = g["Recovery"](folder, "cid")
    net3._write(text)
    net3.last = text
    before = net3.path
    marked = net3.set_aside("discard")
    check("one let go of is kept where it is, marked",
          marked == before and os.path.exists(long_path(marked)), said)
    with io.open(long_path(marked), encoding="utf-8") as fh:
        check("with how it was let go of in its first line",
              json.loads(fh.readline()).get("let_go") == "discard")
finally:
    shutil.rmtree(long_path(base), ignore_errors=True)
    if os.path.exists(long_path(base)):
        # a path past the limit that rmtree could not reach by its plain name
        os.system('rd /s /q "%s"' % long_path(base)) if os.name == "nt" else None

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
