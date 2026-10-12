"""The per-operator filter, taken out of the shipped file exactly as written.

Two things need checking and they are different from each other. The first is
that the brush and the renderer hide exactly the same polygons: if they
diverged, one of them would be drawing against geometries nobody can see. The
second is that no polygon becomes invisible to everyone, because that would be
work silently lost.

Written first against the original single-file prototype, where the same
four pieces (the operator's name, the quoting of text for SQL, the polygons of
one frame and the polygons of the whole campaign) had other names. In the
package they are tidy_operator() and operator_of() beside sql_text(), and the
two gates are scope_polygons() and all_polygons() on AnnotationSection. The
renderer side is not retyped here any more: the CASE WHEN is lifted out of
apply_filter() itself, so the day the two sides drift apart this suite is the
first to know, instead of agreeing with a copy of the expression that the
program stopped using.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import os as _os
import sqlite3
import sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

SRC = _os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)


def function(name, inside=None):
    for node in tree.body:
        if (inside is None and isinstance(node, ast.FunctionDef)
                and node.name == name):
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    # from the decorator, so a staticmethod stays one
                    first = min([sub.lineno] +
                                [d.lineno for d in sub.decorator_list])
                    t = "".join(lines[first - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s not found" % name)


def constant(name, inside):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                        and getattr(sub.targets[0], "id", None) == name):
                    return ast.literal_eval(sub.value)
    raise AssertionError("%s.%s not found" % (inside, name))


BLANK = constant("OPERATOR_BLANK", "AnnotationSection")


class AnnotationSection(object):
    OPERATOR_BLANK = BLANK


def unwrap(f):
    return f.__func__ if isinstance(f, staticmethod) else f


g = {"AnnotationSection": AnnotationSection}
exec(function("sql_text"), g)
exec(function("tidy_operator", inside="AnnotationSection"), g)
exec(function("operator_of", inside="AnnotationSection"), g)
sql_text = g["sql_text"]
tidy_operator = unwrap(g["tidy_operator"])
operator_of = unwrap(g["operator_of"])


def operator_name(text):
    """The panel's operator_name(), with the combo box replaced by its text."""
    return tidy_operator(text) or BLANK


def feature_named(v):
    return {"operator": v}


fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


print("normalising the name")
for raw, want in [("Massi", "MASSI"), ("  Massi  ", "MASSI"), ("", BLANK),
                  (None, BLANK), ("   ", BLANK), ("massi", "MASSI"),
                  ("colleague", "COLLEAGUE")]:
    got = operator_of(feature_named(raw))
    check("%r -> %r" % (raw, want), got == want, got)
check("the panel and the feature fold a name the same way",
      operator_name("  Massi ") == operator_of(feature_named("MASSI")))
check("an empty box is the same person as an empty field",
      operator_name("") == operator_of(feature_named(None)) == BLANK)

print()
print("quotes in the name")
check("a plain name is wrapped in quotes",
      sql_text("Massi") == "'Massi'", sql_text("Massi"))
check("the apostrophe is doubled",
      sql_text("D'Amico") == "'D''Amico'", sql_text("D'Amico"))

print()
print("renderer and brush hide the same rows")
# The operator clause exactly as apply_filter() writes it. QGIS and sqlite
# agree on coalesce, trim and upper, and on CASE WHEN, so the very same text
# can be run against an in memory table.
body = function("apply_filter", inside="AnnotationSection")
node = ast.parse(body)
EXPRESSION = None
for sub in ast.walk(node):
    if (isinstance(sub, ast.Constant) and isinstance(sub.value, str)
            and sub.value.startswith("CASE WHEN") and "operator" in sub.value):
        EXPRESSION = sub.value
check("apply_filter still writes the operator clause as a CASE WHEN",
      EXPRESSION is not None)
if EXPRESSION is None:
    print("FAILED: cannot go on without the expression")
    sys.exit(1)

db = sqlite3.connect(":memory:")
db.execute(
    "CREATE TABLE p (fid INTEGER, tile_id TEXT, pass_no INT, operator TEXT)")
ROWS = [
    (1, "10", 1, "MASSI"),
    (2, "10", 1, "  Massi  "),    # written with spaces and lower case
    (3, "10", 1, "colleague"),
    (4, "10", 1, None),           # no operator at all
    (5, "10", 1, ""),             # empty string
    (6, "11", 1, "colleague"),
    (7, "10", 2, "Massi"),        # a different pass
    (8, "10", 1, "D'Amico"),      # with the apostrophe
]
db.executemany("INSERT INTO p VALUES (?,?,?,?)", ROWS)


def from_the_brush(op, tile, pass_no):
    """scope_polygons(), the same condition rewritten over plain rows."""
    mine = operator_name(op)
    return {r[0] for r in ROWS
            if r[1] == tile and r[2] == pass_no
            and operator_of(feature_named(r[3])) == mine}


def from_the_renderer(op, tile, pass_no):
    cond = [EXPRESSION % (sql_text(BLANK), sql_text(operator_name(op))),
            "\"tile_id\" = '%s'" % tile, "\"pass_no\" = %d" % pass_no]
    q = "SELECT fid FROM p WHERE " + " AND ".join(cond)
    return {r[0] for r in db.execute(q)}


for op in ["Massi", "colleague", "", "D'Amico"]:
    a, b = from_the_brush(op, "10", 1), from_the_renderer(op, "10", 1)
    check('"%s" sees the same rows from both sides' % op, a == b, (a, b))

check("Massi sees his two, the spaced one included",
      from_the_brush("Massi", "10", 1) == {1, 2},
      from_the_brush("Massi", "10", 1))
check("the colleague sees only his own",
      from_the_brush("colleague", "10", 1) == {3},
      from_the_brush("colleague", "10", 1))
check('the two with no name both end up under "%s"' % BLANK,
      from_the_brush("", "10", 1) == {4, 5},
      from_the_brush("", "10", 1))
check("the name with the apostrophe does not break the renderer",
      from_the_renderer("D'Amico", "10", 1) == {8},
      from_the_renderer("D'Amico", "10", 1))

print()
print("no polygon invisible to everyone")
seen = set()
for op in {operator_of(feature_named(r[3])) for r in ROWS}:
    for tile in {r[1] for r in ROWS}:
        for pass_no in {r[2] for r in ROWS}:
            seen |= from_the_brush(op, tile, pass_no)
everything = {r[0] for r in ROWS}
check("every row is visible to somebody", seen == everything,
      sorted(everything - seen))

print()
print("the filter does not change the file")
before = list(db.execute("SELECT * FROM p ORDER BY fid"))
for op in ["Massi", "colleague", ""]:
    from_the_renderer(op, "10", 1)
check("after all the reading the rows are untouched",
      list(db.execute("SELECT * FROM p ORDER BY fid")) == before)

print()
print("all_polygons ignores operator and pass")
code = function("all_polygons", inside="AnnotationSection").split('"""')[2]
check("it does not name the operator", "operator" not in code)
check("it does not name the pass", "pass_no" not in code)

print()
print("the places that must see everything really do")
for method in ["move_tile", "delete_tile"]:
    s = function(method, inside="AnnotationSection")
    check("%s reaches the whole frame through tables_of_tile" % method,
          "tables_of_tile(" in s)
check("others_here counts what is hidden out of all_polygons",
      "all_polygons(" in function("others_here", inside="AnnotationSection"))

for method in ["paint", "close_holes", "reclassify_at", "refresh_coverage"]:
    s = function(method, inside="AnnotationSection")
    check("%s goes through the filtered gate" % method,
          "scope_polygons(" in s and "all_polygons(" not in s)

print()
print("joining neighbours keeps to one reading, whatever is on screen")
s = function("_joined_with", inside="AnnotationSection")
check("it keys the neighbours by class and by the reading read off the polygon",
      "self.reading_of(other)" in s and "class_name" in s)
check("and reads the whole table, never what the operator box lets through",
      "scope_polygons(" not in s and "all_polygons(" not in s)

print()
print("scope_polygons filters by operator")
s = function("scope_polygons", inside="AnnotationSection")
check("it compares the operator", "self.operator_of(f) != mine" in s)
check("and it uses the same normaliser as the renderer",
      "self.operator_name()" in s)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
