"""The package imports as a package, and the single file is built from it.

Two things are checked here that no other suite can check, because every other
suite reads one file and execs it.

First, that `import rasterlabel` works: that each module can be imported on its
own, that the imports between them have no cycle, and that nothing happens at
import time beyond defining things. A plugin that builds a widget while QGIS is
still starting is a plugin that fails on somebody else's machine.

Second, that dist/rasterlabel.py is the package and not an older copy of it. The
single file is what most people will paste into the console; shipping one that no
longer matches the modules is the most ordinary way for a build to lie.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import io
import os
import subprocess
import sys

ROOT = os.environ.get("RL_ROOT")
if not ROOT:
    print("set RL_ROOT to the repository root")
    sys.exit(2)
PKG = os.path.join(ROOT, "rasterlabel")

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


# ------------------------------------------------------------ the fakes
# Enough of QGIS, Qt, numpy and GDAL to let the modules be imported. Nothing is
# called: this suite is about import time only.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_imports
harness_imports            # it builds the fakes on import

# ------------------------------------------------------------ the modules
ORDER = [
    "constants", "compat", "naming", "project", "errors", "stats",
    "agreement", "reports", "view", "layout", "theme", "widgets", "design",
    "campaign", "detection", "journal", "rasters", "geometry", "layers", "recovery",
    "report_rasters", "correction", "effort", "compare", "model_vs_corrected",
    "card", "uncertainty", "tools", "dialogs", "ui_compare", "ui_time",
    "ui_mvc", "ui_card", "ui_uncertainty", "ui_import_frames",
    "sections_annotate", "sections_correct", "sections_cutouts",
    "sections_objects", "export", "doctor", "measure", "panel",
    "processing_provider", "launch", "plugin",
]

print("every module is on the list, and every name on the list is a module")
there = sorted(f[:-3] for f in os.listdir(PKG)
               if f.endswith(".py") and f != "__init__.py")
check("no module is missing from the order",
      not [m for m in there if m not in ORDER],
      [m for m in there if m not in ORDER])
check("and the order names no module that is not there",
      not [m for m in ORDER if m not in there],
      [m for m in ORDER if m not in there])

print()
print("nothing runs at import: only definitions at the top level")
ALLOWED = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef,
           ast.Assign, ast.AnnAssign, ast.Try, ast.If, ast.Expr)
for m in there:
    tree = ast.parse(io.open(os.path.join(PKG, m + ".py"), encoding="utf-8").read())
    loose = [type(n).__name__ for n in tree.body if not isinstance(n, ALLOWED)]
    calls = [n for n in tree.body
             if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
    check("%s.py has no loose statement" % m, not loose, loose)
    check("%s.py calls nothing at the top level" % m, not calls,
          [getattr(c.value.func, "id", "?") for c in calls])

print()
print("the imports between the modules point one way only")
owner = {}
for m in there:
    tree = ast.parse(io.open(os.path.join(PKG, m + ".py"), encoding="utf-8").read())
    for n in tree.body:
        if isinstance(n, ast.ImportFrom) and n.level:
            owner.setdefault(m, set()).add(n.module)
rank = {m: i for i, m in enumerate(ORDER)}
back = []
for m, deps in owner.items():
    for d in deps:
        if d in rank and m in rank and rank[d] > rank[m]:
            back.append("%s needs %s" % (m, d))
check("no module needs one that comes after it", not back, back)

print()
print("importing the package does not raise")
for m in ORDER:
    try:
        __import__("rasterlabel." + m)
        ok, why = True, ""
    except Exception as err:
        ok, why = False, "%s: %s" % (type(err).__name__, err)
    check("import rasterlabel.%s" % m, ok, why)

try:
    import rasterlabel
    check("import rasterlabel", True)
    check("and it offers classFactory", callable(rasterlabel.classFactory))
    check("and says which build it is",
          isinstance(rasterlabel.BUILD, str) and len(rasterlabel.BUILD) >= 6,
          getattr(rasterlabel, "BUILD", None))
except Exception as err:
    check("import rasterlabel", False, err)

print()
print("the single file in dist is the package, not an older copy of it")
out = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "bundle.py"),
                      "--check"], capture_output=True, text=True, cwd=ROOT)
check("tools/bundle.py --check is happy", out.returncode == 0,
      (out.stdout + out.stderr).strip())

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
