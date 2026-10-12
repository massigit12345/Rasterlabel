"""Setting a campaign aside for an overwrite: all of it or none of it.

New campaign in a folder that holds one asks "this REPLACES it", and moves the
manifest and the package out of the way under a stamped name instead of
deleting them. It moved the manifest first and the package second. When the
package could not be moved (another program has it open, a sync client, a
layer of another QGIS), the folder was left with an annotation.gpkg and a
campaign.json.replaced-<stamp>: no campaign.json, so Open campaign no longer
worked on it, and the message said only that the package was held, not that
the manifest had already gone.

The functions are taken from the built file and run against a folder on disk,
with the move refused where a real program would refuse it, so the suite does
not depend on which system it runs on holding a file open the same way.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import os
import shutil
import sys
import tempfile
import types
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
SRC = os.environ.get("RL_SRC") or os.path.join(ROOT, "dist", "rasterlabel.py")

source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)

fails = []
said = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def take(name):
    for node in tree.body:
        if getattr(node, "name", None) == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("%s not found" % name)


# the module the functions run in: the real os, except for the one move that
# is refused, and the two classes' file names
refused = []


class Os(object):
    path = os.path

    @staticmethod
    def replace(a, b):
        if os.path.basename(a) in refused:
            raise PermissionError(13, "The process cannot access the file "
                                  "because it is being used by another "
                                  "process")
        return os.replace(a, b)

    exists = staticmethod(os.path.exists)


q = {"os": Os, "datetime": datetime, "log": said.append,
     "release_file": lambda path: 0,
     "Campaign": types.SimpleNamespace(MANIFEST="campaign.json",
                                       PACKAGE="annotation.gpkg")}
exec(take("move_sidecars"), q)
exec(take("set_aside"), q)
set_aside = q["set_aside"]


made = []


def folder_with(*names):
    where = tempfile.mkdtemp(prefix="rl_aside_")
    made.append(where)
    for n in names:
        with open(os.path.join(where, n), "wb") as fh:
            fh.write(n.encode())
    return where


try:
    print("a package that cannot be moved leaves the campaign as it was")
    here = folder_with("campaign.json", "annotation.gpkg")
    refused[:] = ["annotation.gpkg"]
    try:
        set_aside(here)
        err = None
    except IOError as caught:
        err = str(caught)
    check("it raises", err is not None)
    check("the folder still has its manifest and its package, and nothing "
          "else", sorted(os.listdir(here)) == ["annotation.gpkg",
                                              "campaign.json"],
          sorted(os.listdir(here)))
    check("it names the file that is held", err and "annotation.gpkg" in err,
          err)
    check("and says nothing was changed", err and "Nothing was changed" in err,
          err)

    print()
    print("a manifest that cannot be moved puts the package back")
    here = folder_with("campaign.json", "annotation.gpkg",
                       "annotation.gpkg-wal")
    refused[:] = ["campaign.json"]
    try:
        set_aside(here)
        err = None
    except IOError as caught:
        err = str(caught)
    check("the folder is whole again", sorted(os.listdir(here)) == [
        "annotation.gpkg", "annotation.gpkg-wal", "campaign.json"],
        sorted(os.listdir(here)))
    check("what was in them is untouched",
          open(os.path.join(here, "annotation.gpkg-wal"), "rb").read()
          == b"annotation.gpkg-wal")
    check("and it says so", err and "Nothing was changed" in err, err)

    print()
    print("a sidecar that cannot be moved puts the package back too")
    here = folder_with("campaign.json", "annotation.gpkg",
                       "annotation.gpkg-wal", "annotation.gpkg-shm")
    refused[:] = ["annotation.gpkg-shm"]
    try:
        set_aside(here)
        err = None
    except IOError as caught:
        err = str(caught)
    check("package, wal, shm and manifest are all where they were",
          sorted(os.listdir(here)) == ["annotation.gpkg",
                                       "annotation.gpkg-shm",
                                       "annotation.gpkg-wal",
                                       "campaign.json"],
          sorted(os.listdir(here)))
    check("and the message names the sidecar", err and "-shm" in err, err)

    print()
    print("when the put-back itself fails, the message says what is where")
    here = folder_with("campaign.json", "annotation.gpkg")
    real = Os.replace

    def refuse_both(a, b):
        # the manifest is refused, and then the package cannot be put back
        if os.path.basename(a) == "campaign.json":
            raise PermissionError(13, "held")
        if ".replaced-" in os.path.basename(a):
            raise PermissionError(13, "held again")
        return os.replace(a, b)
    Os.replace = staticmethod(refuse_both)
    try:
        set_aside(here)
        err = None
    except IOError as caught:
        err = str(caught)
    Os.replace = staticmethod(real)
    check("it names the package, and where it went",
          err and "annotation.gpkg is now annotation.gpkg.replaced-" in err,
          err)
    check("and tells how to open the campaign again",
          err and "rename these by hand" in err, err)

    print()
    print("what must not have changed: a set aside that works")
    here = folder_with("campaign.json", "annotation.gpkg",
                       "annotation.gpkg-wal")
    refused[:] = []
    moved = set_aside(here)
    check("the manifest, the package and the wal are moved",
          len(moved) == 3 and not os.path.exists(
              os.path.join(here, "campaign.json"))
          and not os.path.exists(os.path.join(here, "annotation.gpkg"))
          and not os.path.exists(os.path.join(here, "annotation.gpkg-wal")),
          (moved, sorted(os.listdir(here))))
    check("the wal sits beside the package under the name SQLite looks for",
          sorted(os.listdir(here)) == sorted(moved)
          and any(m.startswith("annotation.gpkg.replaced-")
                  and m.endswith("-wal") for m in moved), moved)
    empty = folder_with()
    check("a folder with nothing to set aside is no error",
          set_aside(empty) == [])
finally:
    for d in made:
        shutil.rmtree(d, ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
