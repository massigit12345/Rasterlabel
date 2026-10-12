"""The modules that need neither QGIS nor GDAL, taken out of the shipped file.

agreement, stats, reports, journal, effort, card and design compute and
write; none of them draws or reads a raster. They are tested here the way
the other suites test the program, from dist/rasterlabel.py, what is
shipped, and without faking anything: the single file is cut at the
headers tools/bundle.py writes between its modules, and only the pieces
asked for are run, in their bundle order, in one namespace, the way the
single file runs them.

Three things go into that namespace first:

- the imports of the single file's header that are not QGIS, Qt or GDAL;
- of constants, every top-level statement that runs without QGIS, which is
  every plain number, word and table, and BUILD, which is the fingerprint
  of the very file read here;
- naming, which is plain Python.

So a constant a module asks for and constants does not define, or a name a
module borrows from a module it was not given, is a NameError here, not a
pass. A test that wants to know a module stays pure also asks
imports_of(name), which reads the module in the package and lists what it
imports.
"""
import ast
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
SRC = os.environ.get("RL_SRC") or os.path.join(ROOT, "dist", "rasterlabel.py")
PKG = os.path.join(ROOT, "rasterlabel")

_HEADER = re.compile(r"^# -{69}\n# ---- (\w+) -+\n# -{69}\n", re.M)
_OUTSIDE = ("qgis", "osgeo", "PyQt5", "PyQt6", "sip")


def sections():
    """{module name: its text in the single file}, and the header before."""
    text = open(SRC, encoding="utf-8").read()
    marks = list(_HEADER.finditer(text))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        # blank lines in front, so a traceback names the line of the file
        out[m.group(1)] = "\n" * text.count("\n", 0, m.end()) \
            + text[m.end():end]
    return text[:marks[0].start()] if marks else text, out


def _run_each(source, ns, quiet=True):
    """Run every top-level statement of source on its own, keeping the ones
    that work."""
    tree = ast.parse(source)
    for node in tree.body:
        code = compile(ast.Module(body=[node], type_ignores=[]), SRC, "exec")
        try:
            exec(code, ns)
        except Exception:
            if not quiet:
                raise


def load(*names):
    """A namespace with the named modules run in it, from the single file."""
    head, parts = sections()
    ns = {"__name__": "rasterlabel_pure", "__file__": SRC}
    for node in ast.parse(head).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mods = [node.module or ""] if isinstance(node, ast.ImportFrom) \
                else [a.name for a in node.names]
            if any(m.split(".")[0] in _OUTSIDE for m in mods):
                continue
            exec(compile(ast.Module(body=[node], type_ignores=[]), SRC,
                         "exec"), ns)
    _run_each(parts["constants"], ns)
    exec(compile(parts["naming"], SRC, "exec"), ns)
    order = list(parts)
    for name in sorted(names, key=order.index):
        exec(compile(parts[name], SRC, "exec"), ns)
    mod = types.ModuleType("rasterlabel_pure")
    mod.__dict__.update(ns)
    return mod


def imports_of(name):
    """(absolute imports, relative imports) of rasterlabel/<name>.py, as
    the top names of the modules: ["numpy", "math"], ["stats"]."""
    tree = ast.parse(open(os.path.join(PKG, name + ".py"),
                          encoding="utf-8").read())
    plain, sibling = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                plain.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                sibling.add((node.module or "").split(".")[0])
            else:
                plain.add((node.module or "").split(".")[0])
    return sorted(plain), sorted(sibling)


class Checks(object):
    """ok() and done(), in the voice of the other suites."""

    def __init__(self):
        self.fails = []

    def ok(self, name, cond, detail=""):
        print(("  ok   " if cond else "  FAIL ") + name +
              (("   " + str(detail)) if detail and not cond else ""))
        if not cond:
            self.fails.append(name)
        return cond

    def near(self, name, got, want, tol=1e-9):
        try:
            good = abs(float(got) - float(want)) <= tol
        except (TypeError, ValueError):
            good = False
        return self.ok(name, good, "got %r, want %r" % (got, want))

    def done(self):
        print()
        print("FAILED: %d" % len(self.fails) if self.fails else "all pass")
        for f in self.fails:
            print("   " + f)
        sys.exit(1 if self.fails else 0)


def isnan(v):
    try:
        return v != v
    except Exception:
        return False
