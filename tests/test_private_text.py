"""The helpers that keep the name of the person out of what is shared.

inside_folder writes a path the way a manifest keeps it: relative to its
folder when the file is inside it, as it was when it is not. from_folder
reads it back, and reads a manifest written before, with the whole path, as
it always did. relative_or_name says where a folder is seen from another, and
without_home writes the home folder of whoever runs the program as ~, in the
reports that are pasted into public issues.

The code is lifted out of the built file, as written.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import io
import os
import re
import shutil
import sys
import tempfile

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
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name
                for t in node.targets):
            return "".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("%s not found" % name)


g = {"os": os, "re": re, "sys": sys}
try:
    for name in ("long_path", "home_folder", "home_rest", "with_tilde",
                 "_LOGIN_KEYS", "_LOGIN_PAIR", "_LOGIN_LINK", "_VSI_NAME",
                 "clean_source", "inside_folder", "from_folder",
                 "relative_or_name", "without_home"):
        exec(take(name), g)
except AssertionError as err:
    check("the helpers are in the built file", False, err)
    sys.exit(1)
inside, outside = g["inside_folder"], g["from_folder"]

base = tempfile.mkdtemp(prefix="rl_private_")
try:
    folder = os.path.join(base, "camp")
    os.makedirs(os.path.join(folder, "sub"))
    here = os.path.join(folder, "ortho.tif")
    deep = os.path.join(folder, "sub", "o.tif")
    for p in (here, deep):
        open(p, "w").close()
    away = os.path.join(base, "elsewhere", "o.tif")

    print("inside_folder: a file in the folder is written relative to it")
    check("beside the manifest, its name", inside(here, folder) == "ortho.tif",
          inside(here, folder))
    check("deeper, with forward slashes", inside(deep, folder) == "sub/o.tif",
          inside(deep, folder))
    check("outside, as it was", inside(away, folder) == away)
    check("the folder itself, as it was", inside(folder, folder) == folder)
    check("a folder that only starts like it is not inside it",
          inside(folder + "_2" + os.sep + "o.tif", folder)
          == folder + "_2" + os.sep + "o.tif")
    check("a layer name after the bar is kept",
          inside(here + "|layername=x", folder) == "ortho.tif|layername=x",
          inside(here + "|layername=x", folder))
    for text in ("https://example.org/tiles/{z}.png", "type=xyz&url=http://x",
                 "relative.tif", "", None):
        check("%r is not a file of the folder" % (text,),
              inside(text, folder) == text)
    check("with no folder, as it was", inside(here, "") == here)

    print()
    print("from_folder: and back")
    check("a relative name is read from the folder",
          outside("ortho.tif", folder) == os.path.join(folder, "ortho.tif"),
          outside("ortho.tif", folder))
    check("a path inside, deeper",
          outside("sub/o.tif", folder) == os.path.join(folder, "sub", "o.tif"))
    check("an absolute path is what it was (a manifest of before)",
          outside(away, folder) == away and outside(here, folder) == here)
    check("a name the folder does not hold stays what the manifest said",
          outside("gone.tif", folder) == "gone.tif")
    check("a service is not joined to anything",
          outside("type=xyz&url=http://x", folder) == "type=xyz&url=http://x")
    check("nothing stays nothing",
          outside("", folder) == "" and outside(None, folder) is None)
    check("the layer name after the bar survives the trip",
          outside("ortho.tif|layername=x", folder)
          == os.path.join(folder, "ortho.tif") + "|layername=x")
    check("what was written is read back as the same file",
          os.path.samefile(outside(inside(deep, folder), folder), deep))

    print()
    print("relative_or_name")
    camp = os.path.join(base, "camp")
    corr = os.path.join(camp, "corrections", "fix")
    check("a campaign seen from its correction",
          g["relative_or_name"](camp, corr) == "../..",
          g["relative_or_name"](camp, corr))
    check("a folder seen from the same folder", g["relative_or_name"](
        camp, camp) == ".")

    print()
    print("without_home")
    home = os.path.expanduser("~")
    say = g["without_home"]
    check("the home folder is ~",
          say("cannot write %s" % os.path.join(home, "work", "x.gpkg"))
          == "cannot write ~%swork%sx.gpkg" % (os.sep, os.sep),
          say("cannot write %s" % os.path.join(home, "work", "x.gpkg")))
    check("with slashes the other way as well",
          say(home.replace("\\", "/") + "/work") == "~/work")
    check("whatever the case, where a path is not case sensitive",
          (say(home.upper() + "/w") == "~/w") if os.name == "nt" else True)
    check("every one of them in a text",
          say("%s and %s" % (home, home)) == "~ and ~")
    check("not the start of another folder's name",
          say(home + "2" + os.sep + "x") == home + "2" + os.sep + "x")
    check("a text with no home in it is as it was",
          say("D:\\data\\o.tif") == "D:\\data\\o.tif")
    check("and a number is a text", say(12) == "12")
finally:
    shutil.rmtree(base, ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
