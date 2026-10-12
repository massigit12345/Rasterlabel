"""The filter on the view is never silently dropped.

What is shown is a rule based renderer built in apply_filter(): the operator,
the pass and the current frame are filter expressions on its rules. restyle()
hands the layer a plain categorized renderer instead, so every call to it wipes
all three, and a call that does not put them back leaves the panel in the one
state it must never be in: the map showing every operator and every pass while
the brush, Fill Gap and the coverage still see one of each.

That is not a hypothetical. Pressing + to add a class did exactly this. The
frame then read 100% covered with another operator's polygon lying across it,
Fill Gap painted underneath work that was in plain sight, and the amber strip
announced "polygons by OPERATOR 1 that you cannot see" over polygons anybody
could see. Nothing in the file was wrong; everything on the screen was.

So the rule is mechanical and is checked mechanically: a function that calls
restyle() calls apply_filter() too. It is a static check on the shipped file,
which means a new call site added in a year is caught by this suite on the day
it is written rather than by somebody annotating a campaign.
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


def body(node):
    return "".join(lines[node.lineno - 1:node.end_lineno])


def calls(node, name):
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if isinstance(f, ast.Name) and f.id == name:
                return True
            if isinstance(f, ast.Attribute) and f.attr == name:
                return True
    return False


def method(name, inside):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if getattr(sub, "name", None) == name:
                    return sub
    raise AssertionError("%s.%s not found" % (inside, name))


print("every place that restyles puts the filter back")
# The definition of restyle itself is not a call site, and neither is a
# function that only hands the name on.
offenders = []
seen = 0
for node in ast.walk(tree):
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    if node.name == "restyle":
        continue
    if not calls(node, "restyle"):
        continue
    seen += 1
    # the panel has no module of its own to filter with when none is open:
    # filter_for_reading is the module's apply_filter, or the panel's
    if not (calls(node, "apply_filter") or calls(node, "filter_for_reading")):
        offenders.append(node.name)
check("there is something to check at all", seen >= 3, seen)
check("and not one of them forgets", not offenders, offenders)

print()
print("the two that forgot, by name, so they cannot forget again")
add = method("add_class", "AnnotationSection")
check("add_class restyles", calls(add, "restyle"))
check("and filters again straight after", calls(add, "apply_filter"))
start = method("__init__", "AnnotationSection")
check("the module filters the moment it opens, before anything is looked at",
      calls(start, "apply_filter"))
check("and measures the coverage of what it has just filtered",
      calls(start, "refresh_coverage"))
text = body(start)
check("in that order: filter, then measure",
      text.index("apply_filter") < text.rindex("refresh_coverage"))

print()
print("the brush and the renderer are still filtering on the same three things")
scope = body(method("scope_polygons", "AnnotationSection"))
rend = body(method("apply_filter", "AnnotationSection"))
# The renderer clauses are SQL inside Python strings, so the double quotes
# around a column name are backslashed in the source. Matched as they are
# written, not as they read.
OPERATOR_SQL = r'upper(trim(\"operator\"))'
for word, in_scope, in_renderer in (
        ("the pass", 'f["pass_no"] != p', r'coalesce(\"pass_no\", 1) = %d'),
        ("the frame", 'f["tile_id"] != tid',
         r'\"tile_id\" = %s" % sql_text(self.current_tile_id())'),
        ("the operator", "self.operator_of(f) != mine", OPERATOR_SQL)):
    check("%s: the brush filters on it" % word, in_scope in scope)
    check("%s: and so does the view" % word, in_renderer in rend, rend[:0])
check("the operator clause is written once, in apply_filter",
      source.count(OPERATOR_SQL) == 1, source.count(OPERATOR_SQL))

print()
print("the Check button counts overlaps the same way the brush does")
# Two operators reading one frame cover it twice on purpose. Grouped by frame
# and pass alone, every pair of their polygons was reported in red as sharing
# ground, on a campaign where nothing was wrong, with the advice to press
# Repair underneath it. Measured on a real campaign: four such pairs, up to
# 81% of the frame each, and exactly one genuine overlap inside one operator's
# own reading.
shape = None
for node in tree.body:
    if getattr(node, "name", None) in ("check_shape", "shape_check",
                                       "check_geometry"):
        shape = body(node)
if shape is None:
    shape = source[source.index("per_frame = {}"):]
check("the overlap grouping names the operator",
      'key = (f["tile_id"], pass_number(f["pass_no"]), who)' in shape)
check("read through the same upper casing the brush uses",
      'who = operator_word(f["operator"])' in shape)
check("and the report says two readings are not an overlap",
      "meant to cover it twice" in source)

print()
print("and the amber strip is written by the same call, so it cannot lie")
check("apply_filter ends by saying what is hidden",
      "self.show_blind()" in rend)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
