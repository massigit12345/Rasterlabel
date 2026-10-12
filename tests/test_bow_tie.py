"""A vertex dragged across its own polygon's edge does not jam the program.

QGIS's vertex tool lets a vertex cross an edge of the polygon it belongs to.
What comes out is a bow tie, a ring that crosses itself, and GEOS refuses to do
arithmetic with it. Reported from a real session, word for word from the
console:

    a polygon of class 2 could not be cut and was left as it is: press Repair
    a polygon of class 3 could not be cut and was left as it is: press Repair
    0 overlaps resolved

Three faults made that loop. cut_away retried with only the polygon being cut
repaired, never the one cutting, so when the bow tie was the cutter the retry
failed exactly as the first try had. settle_edits repaired the bow tie in a
local variable and left it in the layer, so every later cut failed against it
again. And Repair went through the same cut_away, failed the same way, printed
"press Repair" from inside itself, and reported zero overlaps as if all were
well.

The first half of this suite runs the geometry for real, with GEOS through
shapely, on the shapes of that session, and shows which retry works and which
does not. It is the arithmetic of the bug, not the program's own code: that is
QGIS geometry and there is no QGIS here. The second half reads the shipped file
to make sure the program does what the first half shows has to be done.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import os as _os

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os
import sys

SRC = os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def source_of(name, inside):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if getattr(sub, "name", None) == name:
                    t = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s not found" % name)


try:
    from shapely.geometry import Polygon, box
    from shapely.validation import make_valid
except ImportError:
    print("shapely is not installed:  pip install shapely")
    sys.exit(2)


def attempt(fn):
    try:
        out = fn()
        return out if out is not None and not out.is_empty else None
    except Exception:
        return None                     # what QGIS returns as a null geometry


A = "AnnotationSection"

#  The session: a pink square, and a green polygon one of whose vertices was
#  dragged across its own edge and over the pink.
pink = box(0, 0, 4, 4)
green = Polygon([(3, 1), (8, 5), (8, 1), (3, 5)])

print("the shape the vertex tool left behind")
check("the green outline crosses itself", not green.is_valid)

print()
print("cutting the pink with the bow tie, the way the brush and Repair do")
check("the plain cut fails", attempt(lambda: pink.difference(green)) is None)
check("repairing only the one being cut, as the retry used to, still fails",
      attempt(lambda: make_valid(pink).difference(green)) is None)
both = attempt(lambda: make_valid(pink).difference(make_valid(green)))
check("repairing both sides works", both is not None)
check("and gives the pink back minus what the green really covers",
      both is not None and abs(both.area - (16 - make_valid(green)
                                            .intersection(pink).area)) < 1e-9,
      both.area if both is not None else None)

print()
print("the bow tie untangled is what it encloses, and it can be cut again")
lobes = make_valid(green)
parts = list(lobes.geoms) if lobes.geom_type == "MultiPolygon" else [lobes]
check("two polygons, one per lobe", len(parts) == 2, len(parts))
check("both valid", all(p.is_valid for p in parts))
check("together the same ground the outline enclosed",
      abs(sum(p.area for p in parts) - lobes.area) < 1e-9)
check("and once it is written back, the plain cut works the first time",
      attempt(lambda: pink.difference(lobes)) is not None)

# ------------------------------------------------------------ the program
print()
print("the program repairs both sides on the retry")
cut = source_of("cut_away", A)
check("the retry repairs the cutter as well",
      "geom.makeValid().difference(union.makeValid())" in cut)
check("the old one-sided retry is gone",
      "geom.makeValid().difference(union)\n" not in cut)
check("and a failure there no longer raises past it", "except Exception:" in cut)

print()
print("the bow tie is written back, not repaired in a variable")
unt = source_of("untangle", A)
check("it asks GEOS whether the outline is valid", "g.isGeosValid()" in unt)
check("and writes the repaired shape into the layer",
      "lyr.changeGeometry(fid, pieces[0])" in unt)
# piece_of, not new_feature: the lobe keeps the class, the frame, the pass and
# the operator of the polygon it came from (test_hand_edits_run runs it)
check("the second lobe becomes a polygon of the same class and reading",
      "self.piece_of(extra, f)" in unt)
check("through leftovers(), so a lobe below four pixels stays: it was ground",
      "self.geometry.leftovers(g.makeValid())" in unt)
settle = source_of("settle_edits", A)
check("settle_edits untangles the edited outline",
      "self.untangle(lyr, fid)" in settle)
check("after reading the whole of it, so both lobes trim their neighbours",
      settle.find("g = g.makeValid()") < settle.find("self.untangle(lyr, fid)"))

print()
print("Repair untangles first, and does not recommend itself")
rep = source_of("repair", A)
i_untangle = rep.find("self.untangle(lyr, f.id())")
i_cut = rep.find("self.cut_away(")
check("every outline in the frame is untangled", i_untangle >= 0)
check("before anything is cut", 0 <= i_untangle < i_cut, (i_untangle, i_cut))
check("a single bow tie alone in the frame is still repaired, not "
      "'nothing to repair'", "if len(here) < 2 and not untangled:" in rep)
check("its cuts are quiet: no 'press Repair' printed from inside Repair",
      "self.cut_away(g, claimed, f, quiet=True)" in rep)
check("a cut that still fails is counted",
      "stuck += 1" in rep)
check("and said, with what to do about it",
      "could not be cut even repaired" in rep)
check("and its ground is still claimed, so the next polygon is cut against it",
      "claimed = claimed.combine(g.makeValid())" in rep)
check("the message is a warning when something was left, not a calm zero",
      "worry = holes > 0.01 or stuck" in rep)

print()
print("and Check sees it")
check("the report counts outlines that cross themselves",
      "if not g.isGeosValid():" in source and "cross%s itself" in source)
check("and sends to Repair, which can now do it",
      "untangles the outline into the polygons it" in source)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
