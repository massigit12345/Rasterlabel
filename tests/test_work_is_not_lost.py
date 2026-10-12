"""Work does not get lost.

A handful of ways in which an hour of drawing could disappear without a
message, each one reproduced. The functions are taken from the source and
run against fake geometries that behave like the QGIS ones in the case
that matters: a difference GEOS cannot compute does not raise, it returns
a null geometry, and that, read as "nothing is left", becomes a deletion.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast
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


def take(name, inside=None):
    for node in tree.body:
        if inside is None and getattr(node, "name", None) == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if getattr(sub, "name", None) == name:
                    t = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s not found" % name)


# ---------------------------------------------------------- fake geometries
class Geom(object):
    """The bare minimum of QgsGeometry, plus the fault: broken=True makes
    every difference fail, exactly as GEOS does on a ring that touches
    itself."""

    def __init__(self, area=10.0, broken=False, null=False):
        self._a = float(area)
        self.broken = broken
        self.null = null

    def isNull(self):
        return self.null

    def isEmpty(self):
        return self.null or self._a <= 0

    def area(self):
        return 0.0 if self.null else self._a

    def difference(self, other):
        if self.broken:
            return Geom(0, null=True)        # GEOS has failed
        return Geom(max(self._a - other.area(), 0.0))

    def makeValid(self):
        return Geom(self._a, broken=False)

    def buffer(self, *a):
        return self

    def intersects(self, other):
        return True


said = []
g = {"log": lambda msg, loud=False: said.append(str(msg))}
exec(take("cut_away", "AnnotationSection"), g)
cut_away = g["cut_away"]


class Fake(object):
    cut_away = g["cut_away"]


print("a difference that fails does not delete the polygon that was there")
s = Fake()
good = s.cut_away(Geom(100.0), Geom(5.0))
check("a normal difference gives back the remainder", good is not None
      and abs(good.area() - 95.0) < 1e-9, good and good.area())

class Unfixable(Geom):
    """Broken, and broken still after makeValid: the hopeless case."""
    def makeValid(self):
        return self


said[:] = []
hopeless = Unfixable(10000.0, broken=True)
outcome = s.cut_away(hopeless, Geom(5.0))
check("one that fails and fails again once repaired gives back None",
      outcome is None, outcome)
check("and it says so, instead of losing ten thousand pixels in silence",
      any("left as it is" in m for m in said), said)


class Fixable(Geom):
    """Fails while broken, succeeds once repaired: the commoner case."""
    def makeValid(self):
        return Geom(self._a, broken=False)


said[:] = []
r = s.cut_away(Fixable(500.0, broken=True), Geom(20.0))
check("if repairing it works, the cut is made", r is not None
      and abs(r.area() - 480.0) < 1e-9, r and r.area())
check("without bothering anybody", not said, said)

# ------------------------------------------- the union before the slaughter
print()
print("neighbours are not deleted before the union is known to have worked")
am = take("_merge_group", "AnnotationSection")
i_union = am.find("unaryUnion")
i_parts = am.find("self.geometry.leftovers(union)")
i_del = am.find("deleteFeatures")
check("the parts are worked out before anything is deleted",
      0 <= i_union < i_parts < i_del, (i_union, i_parts, i_del))
check("and if the union is not one polygon the neighbours stay where they are",
      "len(pieces) != 1" in am and "leave them" in am)
check("the new piece is already in the table before any merge is tried",
      "addFeature" in take("add_piece", "AnnotationSection")
      and "addFeature" not in am)

# ----------------------------------------------------- the coverage per pass
print()
print("two readings of the same cell do not make two hundred per cent")


def share(polygons, tile_area):
    """The part of measure_tile that decides: the fullest pass wins."""
    per_pass = {}
    for reading, a in polygons:
        per_pass[reading] = per_pass.get(reading, 0.0) + a
    painted = max(per_pass.values()) if per_pass else 0.0
    return (painted / tile_area) if tile_area else 0.0


check("one pass only, half done -> 0.5",
      abs(share([(1, 50.0)], 100.0) - 0.5) < 1e-9)
check("a pass closed -> 1.0", abs(share([(1, 100.0)], 100.0) - 1.0) < 1e-9)
closed_plus_begun = share([(1, 100.0), (2, 20.0)], 100.0)
check("first one closed and second just begun -> 1.0, not 1.2",
      abs(closed_plus_begun - 1.0) < 1e-9, closed_plus_begun)
check("and the second one on its own is not declared closed",
      share([(2, 20.0)], 100.0) < 0.995)
mt = take("measure_tile", "AnnotationSection")
check("measure_tile counts per reading", "per_reading" in mt)
check("and takes the fullest one", "max(per_reading.values())" in mt)

# -------------------------------------------- checks on the source text
print()
print("checks on the source text (these are not trials)")

cm = take("close_module", "Panel")
check("closing a module saves what it has in hand",
      "self.section.unsaved()" in cm and "self.section.save()" in cm)
i_save = cm.find("self.section.save()")
i_del = cm.find("deleteLater")
check("and saves it before taking it apart", 0 <= i_save < i_del,
      (i_save, i_del))

cc = take("close_campaign", "Panel")
check("closing the campaign looks at the layers, not just the module",
      "self.pending_layers()" in cc)
check("and if it cannot save, it closes nothing",
      "nothing was\\n\"\n                        \"closed" in cc
      or "nothing was" in cc)

pl = take("pending_layers", "Panel")
check("full buffers are recognised from the layer",
      "isEditable()" in pl and "isModified()" in pl)

mv = take("move_tile", "AnnotationSection")
i_commit = mv.find("tiles.commitChanges()")
i_wipe = mv.find("self._carry_or_drop(held, carry, mx, my)")
check("the tile is moved before its contents are taken away",
      0 <= i_commit < i_wipe, (i_commit, i_wipe))
check("and the lock on the marks holds here too",
      "self.marks_locked()" in mv)

rf = take("rename_features", "Panel")
check("renaming a class writes to disk", "commitChanges()" in rf)
check("and says so if it cannot", "could not be written" in rf)

it = take("import_tiles", "AnnotationSection")
check("importing tiles checks the commit",
      "if not lyr.commitChanges():" in it)
check("and no longer announces more successes than there were",
      it.find("if not lyr.commitChanges():")
      < it.rfind("QMessageBox.information"))
check("and writes the log and the manifest only once the frames are on disk",
      it.find("if not lyr.commitChanges():")
      < it.find("design_manifest_entry(")
      and it.find("if not lyr.commitChanges():")
      < it.find("design_log_rows("))
check("a failed commit is in the log too, as not written",
      "design_not_written(" in it)

import ast as _ast
_t = _ast.parse(source)
for _n in _t.body:
    if isinstance(_n, _ast.ClassDef) and _n.name == "AnnotationSection":
        _without = []
        for _s in _n.body:
            if getattr(_s, "name", "") in ("paint", "close_holes", "repair",
                                           "draw_line", "drop_point",
                                           "remove_point_at", "reclass_point_at",
                                           "reclassify_at"):
                _body = "".join(lines[_s.lineno - 1:_s.end_lineno])
                if "self.ticked()" not in _body:
                    _without.append(_s.name)
        check("every road that changes the drawing arms the autosave",
              not _without, _without)

el = take("project_ellipsoid")
check("an ellipsoid of 'NONE' counts as absent", '"NONE"' in el)
check("and WGS84 is what we fall back to", '"WGS84"' in el)

rc = take("refresh_coverage", "AnnotationSection")
check("the coverage is clipped to the tile", ".intersection(tile)" in rc)

se = take("settle_edits", "AnnotationSection")
# Settled inside the edited polygon's own reading, not the one in hand: a
# vertex dragged in another frame is now settled there (test_hand_edits_run
# runs it), and another pass or operator is still never touched.
check("a vertex is settled among the polygons of its own reading",
      "reading = self.reading_of(f)" in se
      and "self.reading_of(r) == reading" in se)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
