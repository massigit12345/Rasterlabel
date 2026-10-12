"""The vector layers held in memory use the driver GDAL still has.

GDAL 3.11 folded the "Memory" vector driver into "MEM" and prints a
deprecation warning, once, the first time anything asks for the old name; it
will stop answering to it. Whole and Export burn the campaign through such a
layer, so the day the name goes they would stop. This suite is the first and
only thing its process does with GDAL, which is what lets it see that one
warning.

The code under test is lifted out of the built file as written."""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast
import os
import sys

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()

SRC = os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)


def take(name):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) \
                and node.name == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("%s not found" % name)


fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


g = {"gdal": gdal, "ogr": ogr, "osr": osr, "np": np, "os": os,
     "log": lambda m, loud=False: print("      [log]", m)}
for n in ("Stencil", "mask_type", "burn"):
    exec(take(n), g)

heard = []
gdal.PushErrorHandler(lambda kind, number, text: heard.append(text))
try:
    wkt = osr.SpatialReference()
    wkt.ImportFromEPSG(32633)
    square = ogr.CreateGeometryFromWkt(
        "POLYGON((0 0,4 0,4 -4,0 -4,0 0))")

    class Shape(object):
        def asWkb(self):
            return square.ExportToWkb()

    painted = g["burn"]([(Shape(), 7)], (0.0, 1.0, 0.0, 0.0, 0.0, -1.0),
                        8, 8, wkt.ExportToWkt())
    # a build from before has no in_memory, and this suite then says what
    # it gets wrong instead of stopping at the missing name
    make = getattr(g["Stencil"], "in_memory", None)
    memory = make("t") if make is not None else None
    layer = memory.CreateLayer("g", None, ogr.wkbUnknown)         if memory is not None else None
finally:
    gdal.PopErrorHandler()

print("a vector layer in memory")
check("burn still paints the square: 16 pixels of 7",
      int((painted == 7).sum()) == 16 and int((painted != 0).sum()) == 16,
      int((painted == 7).sum()))
check("and the layer of a stencil can be made and used",
      memory is not None and layer is not None)
old = [t for t in heard if "deprecat" in t.lower() or "'Memory'" in t]
check("GDAL has nothing to say about a deprecated driver", not old, old)

print()
print("FAILED: %d" % len(fails) if fails else "all of them pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
