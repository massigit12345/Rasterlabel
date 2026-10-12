"""A table opened in a spreadsheet must not run what a person typed into it.

A class called =HYPERLINK("http://...","click") is a name to RasterLabel and a
formula to Excel, LibreOffice and Sheets, which run any cell that begins with
=, +, - or @ (and a tab or a carriage return in front of one) when the file is
opened. Class names, layer names and operator names are typed by people and
end up in cutouts.csv, operations.csv, journal.csv, design_log.csv, the
places of Uncertainty, every report's tables and the CSV export.

csv_text puts a single quote in front of such a text and touches nothing
else: not a number, not a number written as digits (a negative coordinate
must stay a number), not a cell that is empty. The readers that compare a
cell with a name take the quote off again, so a class called -water is the
same class after a trip through the file.

Every writer is run for real, with a name that is a formula in each place a
name goes, and the file is read back as raw text. The code is lifted out of
the built file, as written.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import csv
import io
import math
import os
import shutil
import sys
import tempfile
import types

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


def take(name, inside=None):
    for node in tree.body:
        if inside is None and getattr(node, "name", None) == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.Assign) and inside is None:
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if getattr(sub, "name", None) == name:
                    t = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s not found" % name)


said = []
g = {"os": os, "re": __import__("re"), "sys": sys, "io": io, "csv": csv,
     "math": math, "json": __import__("json"),
     "log": lambda m, loud=False: said.append(str(m))}
for name in ("_FORMULA_START", "_PLAIN_NUMBER", "csv_text", "csv_untext",
             "csv_untext_row", "long_path", "report_cell", "_report_replace",
             "report_csv", "journal_cell", "journal_read", "design_append_log",
             "design_read_log", "_unc_cell", "defuse_csv", "tally_operations",
             "time_read_operations", "unc_read_operations"):
    try:
        exec(take(name), g)
    except AssertionError:
        print("  FAIL %s is not in the built file" % name)
        fails.append(name)
        g[name] = None
g["DESIGN_LOG_COLUMNS"] = ["when", "action", "tile_id", "operator", "note"]
csv_text, csv_untext = g["csv_text"], g["csv_untext"]
BAD = ['=HYPERLINK("http://example.org","x")', "+1+1", "-2+3", "@SUM(A1)",
       "\t=1", "\r=1", "=cmd|' /C calc'!A0"]

# ---------------------------------------------------------------- the helper
print("csv_text: text that would run is quoted, nothing else is touched")
if csv_text is None:
    sys.exit(1)
for cell in BAD:
    check("%r gets a quote" % cell, csv_text(cell) == "'" + cell,
          csv_text(cell))
for value in ("class 1", "water", "a=b", "x-1", "", "'=already", "2026-10-09",
              "C:/data/x.tif", "naïve"):
    check("%r is left alone" % value, csv_text(value) == value, csv_text(value))
for number in (-3, 0, 12, -0.25, 3.5, True, None, 1e-9, -1e30):
    check("the number %r stays a number" % (number,),
          csv_text(number) is number or csv_text(number) == number,
          csv_text(number))
for digits in ("-3", "-0.25", "+7", "1e-3", "-1.5E+10", ".5", "-.5", "42."):
    check("digits %r stay a number" % digits, csv_text(digits) == digits,
          csv_text(digits))
for cell in BAD + ["water", "-water", "-3"]:
    check("the quote comes off again: %r" % cell,
          csv_untext(csv_text(cell)) == cell, csv_untext(csv_text(cell)))
check("a name that merely begins with a quote is not unquoted",
      csv_untext("'tis") == "'tis" and csv_untext("'-3") == "'-3")

root = tempfile.mkdtemp(prefix="rl_csv_safety_")


def raw(path):
    with io.open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def cells(path):
    with io.open(path, encoding="utf-8", newline="") as fh:
        return [c for row in csv.reader(fh) for c in row]


def nothing_runs(path, what):
    """No cell of the file begins with a formula character, bar numbers."""
    loose = [c for c in cells(path)
             if c.startswith(("=", "+", "-", "@", "\t", "\r"))
             and not g["_PLAIN_NUMBER"].match(c.strip())]
    check("%s: no cell begins like a formula" % what, not loose, loose)


try:
    # ------------------------------------------------------------- reports
    print()
    print("report_csv: every report's tables")
    path = os.path.join(root, "per_class.csv")
    g["report_csv"](path, ["code", "name", "=HEADER()"],
                    [[-1, '=1+1', -0.5], [2, "@x", 3.25], [3, "water", None]])
    nothing_runs(path, "per_class.csv")
    rows = list(csv.reader(io.open(path, encoding="utf-8", newline="")))
    check("a negative number is written as it was", rows[1][0] == "-1"
          and rows[1][2] == "-0.5", rows[1])
    check("the name keeps its text behind the quote", rows[1][1] == "'=1+1",
          rows[1])
    check("an ordinary name is written as it was", rows[3][1] == "water")

    # ------------------------------------------------------------- journal
    print()
    print("journal.csv")
    jpath = os.path.join(root, "journal.csv")
    with io.open(jpath, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["seq", "operator", "mono_ms", "dur_ms", "class_name"])
        w.writerow([g["journal_cell"](7), g["journal_cell"]("=EVIL()"),
                    g["journal_cell"](12.5), g["journal_cell"](-3),
                    g["journal_cell"]("-water")])
    nothing_runs(jpath, "journal.csv")
    back = g["journal_read"](jpath)
    check("the journal reads the name back as it was",
          back and back[0]["operator"] == "=EVIL()"
          and back[0]["class_name"] == "-water", back)
    check("and its numbers as numbers", back and back[0]["seq"] == 7)

    # --------------------------------------------------------- design log
    print()
    print("design_log.csv")
    dpath = os.path.join(root, "design_log.csv")
    check("written", g["design_append_log"](
        dpath, [["2026-10-09", "import", "t001", "=EVIL()", "-1"]]))
    nothing_runs(dpath, "design_log.csv")
    back = g["design_read_log"](dpath)
    check("read back as it was", back and back[0]["operator"] == "=EVIL()"
          and back[0]["note"] == "-1", back)

    # ----------------------------------------------------------- places
    print()
    print("the places of Uncertainty")
    check("a name in a place is quoted",
          g["_unc_cell"]("note", "=EVIL()") == "'=EVIL()")
    check("a number is not", g["_unc_cell"]("mean_u", -0.5) == "-0.500000")
    check("a negative whole number is not", g["_unc_cell"]("n", -3) == "-3")

    # ---------------------------------------------- operations.csv (Correct)
    print()
    print("operations.csv, one row per stroke")
    ops = os.path.join(root, "operations.csv")
    write_log = take("write_log", "CorrectionSection")
    ns = dict(g, csv_text=csv_text, now=lambda: "2026-10-09T10:00:00")
    ns["__name__"] = "m"
    exec(write_log, ns)
    centre = types.SimpleNamespace(x=lambda: -12.5, y=lambda: 4100000.0)
    geom = types.SimpleNamespace(centroid=lambda: types.SimpleNamespace(
        asPoint=lambda: centre))
    me = types.SimpleNamespace(
        operations=3, from_code=1, class_name="=EVIL()", log_path=ops,
        LOG_COLUMNS=["n", "when", "operator", "into", "only", "pixels",
                     "swept_m2", "changed_m2", "x", "y", "col", "row",
                     "width", "height"],
        classes=lambda: [{"code": 1, "name": "-water"}],
        operator_name=lambda: "@ANNA")
    ns["write_log"](me, geom, 10, 4.0, 2.5, 1, 2, 3, 4)
    nothing_runs(ops, "operations.csv")
    row = list(csv.DictReader(io.open(ops, encoding="utf-8", newline="")))[0]
    check("the x coordinate is still a number", row["x"] == "-12.500000", row)
    check("the class and the operator are quoted",
          row["into"] == "'=EVIL()" and row["operator"] == "'@ANNA"
          and row["only"] == "'-water", row)
    check("the tally reads the pair of classes back as it was",
          list(g["tally_operations"](ops)["pairs"]) == ["-water -> =EVIL()"],
          g["tally_operations"](ops)["pairs"])
    check("the time report reads the operator back as it was",
          g["time_read_operations"](ops)[0]["operator"] == "@ANNA")
    check("so does Uncertainty",
          g["unc_read_operations"](ops)[0]["into"] == "=EVIL()")

    # ------------------------------------------------------- cutouts.csv
    print()
    print("cutouts.csv, whose layer column is a layer name")
    cpath = os.path.join(root, "cutouts.csv")
    append_csv = take("append_csv", "CutoutsSection")
    ns2 = dict(g, csv_text=csv_text, ValueError=ValueError)
    exec(append_csv, ns2)
    COLUMNS = ["cutout", "tag", "role", "layer", "bands", "xmin", "ymin",
               "width_px", "when"]
    cut = types.SimpleNamespace(csv_path=cpath, CSV_COLUMNS=COLUMNS,
                                upgrade_csv=lambda: COLUMNS)
    ns2["append_csv"](cut, [{"cutout": "c_0001", "tag": "a", "role": "image",
                             "layer": "=HYPERLINK(\"x\")", "bands": "1,2,3",
                             "xmin": -500.25, "ymin": 4100000,
                             "width_px": 256, "when": "2026-10-09"}])
    nothing_runs(cpath, "cutouts.csv")
    row = list(csv.DictReader(io.open(cpath, encoding="utf-8", newline="")))[0]
    check("the coordinates stay numbers", row["xmin"] == "-500.25", row)
    check("the layer is quoted", row["layer"].startswith("'="), row)

    # ----------------------------------------------------- the vector CSV
    print()
    print("the CSV export, written by GDAL and made safe after it")
    epath = os.path.join(root, "export.csv")
    with io.open(epath, "w", encoding="utf-8", newline="") as fh:
        fh.write('WKT,class_name,class_code,area\n'
                 '"POLYGON ((0 0,1 0,1 1,0 0))",=EVIL(),1,-2.5\n'
                 '"POLYGON ((0 0,1 0,1 1,0 0))","-water",2,3\n')
    check("it changed the cell that was a formula, and only that one",
          g["defuse_csv"](epath) == 2)
    nothing_runs(epath, "the export")
    back = list(csv.DictReader(io.open(epath, encoding="utf-8", newline="")))
    check("the geometry is as it was", back[0]["WKT"].startswith("POLYGON ("))
    check("the negative area is still a number", back[0]["area"] == "-2.5")
    ok = os.path.join(root, "fine.csv")
    text = 'WKT,class_name\r\n"POLYGON ((0 0,1 1))",water\r\n'
    with io.open(ok, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    check("a file with nothing to change is not rewritten",
          g["defuse_csv"](ok) == 0 and raw(ok) == text)
    folder = os.path.join(root, "many")
    os.makedirs(folder)
    for n in ("a.csv", "b.csv"):
        shutil.copy(epath if n == "a.csv" else ok, os.path.join(folder, n))
    with io.open(epath, "w", encoding="utf-8", newline="") as fh:
        fh.write("class_name\n=EVIL()\n")
    shutil.copy(epath, os.path.join(folder, "a.csv"))
    check("given the folder GDAL makes of several tables, it does each file",
          g["defuse_csv"](folder) == 1)
    nothing_runs(os.path.join(folder, "a.csv"), "a table of the folder")

    # a polygon of a large campaign is a cell longer than the 128 KB the csv
    # module allows, and the file is read a row at a time
    big = os.path.join(root, "big.csv")
    wkt = "POLYGON ((%s))" % ",".join("%d %d" % (i, i) for i in range(40000))
    with io.open(big, "w", encoding="utf-8", newline="") as fh:
        fh.write('WKT,class_name\r\n"%s",water\r\n"%s",=EVIL()\r\n'
                 % (wkt, wkt))
    limit = csv.field_size_limit()
    check("the geometry is longer than the csv module's own limit",
          len(wkt) > limit)
    check("a cell of that size is read, and the formula after it is found",
          g["defuse_csv"](big) == 1)
    check("the limit of the csv module is as it was",
          csv.field_size_limit() == limit)
    text = raw(big)
    check("the geometry is whole and the cell is quoted",
          text.count('"%s"' % wkt) == 2 and "\r\n\"%s\",'=EVIL()" % wkt
          in text, text[-40:])
    check("the line ends are the ones GDAL wrote",
          text.count("\r\n") == 3 and text.count("\n") == 3, text[-40:])
    check("and no temporary file is left", not os.path.exists(big + ".tmp"))
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("every place that writes a CSV goes through it")
for where, inside in (("report_cell", None), ("report_csv", None),
                      ("journal_cell", None), ("design_append_log", None),
                      ("_unc_cell", None), ("write_log", "CorrectionSection"),
                      ("append_csv", "CutoutsSection")):
    check("%s calls csv_text" % where, "csv_text(" in take(where, inside))
check("and the export is made safe after GDAL writes it",
      "defuse_csv(target)" in take("write_vectors"))

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
