"""The shapes a source scanner reads as a hard-coded password stay out.

plugins.qgis.org runs Bandit on every upload and lists B105, B106 and B107
(a literal that looks like a password) among the findings that block a
version. A reading's pass number is not a password, but a key named "pass" or
"pass_no" beside a literal is read as one, so the names are kept apart from
literals. This suite looks for the same shapes Bandit looks for, with the ast
module, in every file of the package, and runs Bandit itself over the folder
when it is installed (pip install bandit); without it that part says SKIP.

The shapes (the name matches pass, passwd, password, pwd, secret, token as a
whole word between underscores, in any case):
- a name or an attribute assigned a string: pass_no = "x"
- a dict key with a constant value: {"pass_no": ""}
- a subscript assigned a string: d["pass"] = "x"
- a name compared with a string: pass_no == "x"
- a call with a keyword of such a name and a string: f(pass_no="x")
- a function argument of such a name with a string default: def f(pass_no="")

Needs nothing but Python.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import importlib.util
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)[:800]) if not cond and detail != "" else ""))
    if not cond:
        fails.append(name)


WORDS = "(pas+wo?r?d|pass(phrase)?|pwd|token|secrete?)"
LOOKS = re.compile("(^{0}$|_{0}_|^{0}_|_{0}$)".format(WORDS), re.I)


def is_text(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def lookalikes(source):
    """[(line, what)] for the shapes above in the source text."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and is_text(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name) and LOOKS.search(t.id):
                    found.append((node.lineno, "assigned " + t.id))
                elif isinstance(t, ast.Attribute) and LOOKS.search(t.attr):
                    found.append((node.lineno, "assigned ." + t.attr))
                elif isinstance(t, ast.Subscript) and is_text(t.slice) \
                        and LOOKS.search(t.slice.value):
                    found.append((node.lineno, "assigned [%s]" % t.slice.value))
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if is_text(k) and LOOKS.search(k.value) \
                        and isinstance(v, ast.Constant):
                    found.append((k.lineno, "dict key " + k.value))
        elif isinstance(node, ast.Compare):
            if isinstance(node.left, ast.Name) and LOOKS.search(node.left.id) \
                    and is_text(node.comparators[0]):
                found.append((node.lineno, "compared " + node.left.id))
            elif isinstance(node.left, ast.Attribute) \
                    and LOOKS.search(node.left.attr) \
                    and is_text(node.comparators[0]):
                found.append((node.lineno, "compared ." + node.left.attr))
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg and LOOKS.search(kw.arg) and is_text(kw.value):
                    found.append((kw.value.lineno, "keyword " + kw.arg))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            pos = a.posonlyargs + a.args
            for arg, d in zip(pos[len(pos) - len(a.defaults):], a.defaults):
                if LOOKS.search(arg.arg) and is_text(d):
                    found.append((d.lineno, "default of " + arg.arg))
            for arg, d in zip(a.kwonlyargs, a.kw_defaults):
                if d is not None and LOOKS.search(arg.arg) and is_text(d):
                    found.append((d.lineno, "default of " + arg.arg))
    return found


print("the scanner of this suite sees what Bandit sees")
for src, n in [('pass_no = ""', 1), ('x.pass_no = "a"', 1),
               ('{"pass_no": ""}', 1), ('{"pass": 1}', 1),
               ('d["pass"] = "a"', 1), ('pass_no == "a"', 1),
               ('f(pass_no="a")', 1), ('def f(pass_no=""): pass', 1),
               ('{"pass_no": blank}', 0), ('pass_no = 1', 0),
               ('{"bypass": 1}', 0), ('passes = ""', 0),
               ('{"reading": 1}', 0)]:
    got = lookalikes(src)
    check("%-28s -> %d" % (src, n), len(got) == n, got)

print()
print("no file of the package has one")
folder = os.path.join(ROOT, "rasterlabel")
names = sorted(n for n in os.listdir(folder) if n.endswith(".py"))
check("the package is there", len(names) > 10, names)
for name in names:
    with open(os.path.join(folder, name), encoding="utf-8") as fh:
        got = lookalikes(fh.read())
    check(name, not got, got)
single = os.path.join(ROOT, "dist", "rasterlabel.py")
if os.path.exists(single):
    with open(single, encoding="utf-8") as fh:
        got = lookalikes(fh.read())
    check("the single file", not got, got)

print()
print("Bandit itself, where it is installed")
have_bandit = importlib.util.find_spec("bandit") is not None
if have_bandit:
    out = subprocess.run(
        [sys.executable, "-m", "bandit", "-r", folder, "-q", "-t",
         "B105,B106,B107", "-f", "txt"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("B105, B106 and B107 find nothing in the package",
          "Issue:" not in out.stdout, out.stdout[-800:])
else:
    print("  SKIP bandit is not installed (pip install bandit)")

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
