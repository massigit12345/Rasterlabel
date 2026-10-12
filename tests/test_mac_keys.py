"""The key a hint names is the key that does it.

Qt maps the Ctrl modifier to the Command key on a Mac, so the tools check for
Ctrl and the person presses Cmd. A tooltip that says "Ctrl+click picks FROM"
names a key that does nothing there, in the one place a newcomer looks for
how the tool works.

ctrl_name() is the one place that knows which name to print. Every text a
person reads that names the key goes through it; the words of comments and of
docstrings, which nobody reads in the program, are left as they are.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import io
import os
import sys
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


def take(name):
    for node in tree.body:
        if getattr(node, "name", None) == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("%s not found" % name)


print("the name of the key")
try:
    code = take("ctrl_name")
except AssertionError:
    check("ctrl_name is in the built file", False)
    sys.exit(1)
for platform, want in (("darwin", "Cmd"), ("win32", "Ctrl"),
                       ("linux", "Ctrl"), ("linux2", "Ctrl")):
    ns = {"sys": types.SimpleNamespace(platform=platform)}
    exec(code, ns)
    check("on %s it is %s" % (platform, want), ns["ctrl_name"]() == want,
          ns["ctrl_name"]())

print()
print("no text a person reads names Ctrl by itself")
# every string constant of the program, but the docstrings and the comments
# (a comment is not in the tree at all)
docstrings = set()
for node in ast.walk(tree):
    if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                         ast.AsyncFunctionDef)):
        body = node.body
        if body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            docstrings.add(id(body[0].value))
named = []
for node in ast.walk(tree):
    if isinstance(node, ast.Constant) and isinstance(node.value, str) \
            and id(node) not in docstrings \
            and ("Ctrl" in node.value or "Control+" in node.value):
        named.append((node.lineno, node.value.strip()[:70]))
# the helper itself spells both names
named = [n for n in named if n[1] not in ("Cmd", "Ctrl")
         and not n[1].startswith('"Cmd" if')]
check("the texts that name the key use the helper", not named, named)

print()
print("and the places that had it do call it")
check("the hints of Annotate, Correct and Objects name the key through it",
      source.count("ctrl_name()") >= 9, source.count("ctrl_name()"))

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
