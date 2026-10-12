"""No name used and never defined.

The check that was missing and that cost the most: five QGIS classes used
without being imported, a variable read inside a function where it does not
exist, and a message that named a variable which had disappeared two
versions earlier. All of them things Python only finds out about when it
walks over them, so they lived in the rare branches: the branch that moves
a filled box, the branch that filters by operator, the branch that writes
the number on the box. Three of them were inside a try, so instead of
breaking they switched a feature off in silence.

pyflakes walks over every branch without executing any of them. iface is
the one name that is let through: QGIS puts it in the console, and there is
no other way to have it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os
import re
import subprocess
import sys

SRC = os.environ.get("RL_SRC", _BUILT)

# Names that come from outside and cannot be imported: QGIS puts them in the
# namespace of the Python Console.
FROM_OUTSIDE = {"iface"}

# Imports that look useless and are not, with the reason why. An import that
# ends up in here without a written reason is an import to be removed.
KEPT = {
    "qgis.core.QgsWkbTypes":
        "read by name from first_of(), which asks this QGIS whether it "
        "still has the old spelling of the geometry types",
}

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


# pyflakes is not always there to be had. The Python inside a QGIS installer
# has none, and a pyflakes made for a newer Python dies on an older one with a
# traceback of its own (pyflakes 4 asks the ast of Python 3.9 for a Match
# node it does not have). Neither says anything about this program, so the
# pyflakes part is skipped, loudly, and the checks below it still run.
# RL_REQUIRE_PYFLAKES=1, which the build server sets, makes the skip a
# failure, so a pyflakes that went missing there cannot pass in silence.
REQUIRE_PYFLAKES = os.environ.get("RL_REQUIRE_PYFLAKES", "") not in ("", "0")
rows, why_not = [], None
try:
    import pyflakes
    pyflakes                       # it only has to be importable, and be seen
except ImportError:
    why_not = "pyflakes is not here: pip install pyflakes"
if why_not is None:
    out = subprocess.run([sys.executable, "-m", "pyflakes", SRC],
                         capture_output=True, text=True)
    if "Traceback (most recent call last)" in out.stderr:
        last = [r for r in out.stderr.splitlines() if r.strip()][-1:]
        why_not = ("pyflakes %s cannot run on Python %d.%d: %s"
                   % (getattr(pyflakes, "__version__", "?"),
                      sys.version_info[0], sys.version_info[1],
                      last[0].strip() if last else "it stopped"))
    else:
        rows = [r for r in (out.stdout + out.stderr).splitlines()
                if r.strip()]
if why_not is not None:
    print("SKIP the pyflakes checks: %s" % why_not)
    if REQUIRE_PYFLAKES:
        check("pyflakes runs here, as RL_REQUIRE_PYFLAKES asks", False,
              why_not)
    print()

unknown, unused, imported, other = [], [], [], []
for row in rows:
    m = re.match(r"^(.*?):(\d+):(\d+): (.*)$", row)
    if not m:
        other.append(row)
        continue
    _, number, _, said = m.groups()
    found = re.match(r"undefined name '([^']+)'", said)
    if found:
        if found.group(1) not in FROM_OUTSIDE:
            unknown.append((number, found.group(1)))
        continue
    found = re.match(r"'([^']+)' imported but unused", said)
    if found:
        imported.append((number, found.group(1)))
        continue
    found = re.match(r"local variable '([^']+)' is assigned to but never used",
                     said)
    if found:
        unused.append((number, found.group(1)))
        continue
    other.append(row)

if why_not is None:
    print("names used and never defined")
    check("none (apart from %s)" % ", ".join(sorted(FROM_OUTSIDE)), not unknown,
          unknown[:10])
    for number, name in unknown:
        print("        line %s: %s" % (number, name))

    print()
    print("useless imports")
    for number, name in imported:
        reason = KEPT.get(name)
        check("%s: kept on purpose" % name, reason is not None,
              "line %s, no reason written down" % number)
        if reason:
            print("        %s" % reason)
    if not imported:
        print("  ok   none")

    print()
    print("variables written and never read")
    check("none", not unused, unused)
    for number, name in unused:
        print("        line %s: %s" % (number, name))

    print()
    print("the rest of what pyflakes has to say")
    check("nothing", not other, other[:6])

# --------------------------------------------------------------------------
print()
print("a name looked up at run time is importable where it is looked up")
# pyflakes cannot see this one, and it is the one that bit. first_of() is handed
# a dotted name as a STRING and resolves it through globals(), so the class has
# to be imported in the module that calls it. Nothing in the syntax tree refers
# to QgsWkbTypes, so when the program was split into a package the import went
# with the tidying, pyflakes was happy, every suite passed, and the fallback that
# keeps the program working on QGIS older than 3.30 was quietly dead.
#
# So: every QGIS class named inside a string literal must be imported by the
# module that names it. A name in a comment or a docstring does not count, which
# is why the literals are taken from the syntax tree and not by grep.
import ast as _ast

PACKAGE = os.path.join(_ROOT, "rasterlabel")
_looked_up = re.compile(r"\b(Qgs[A-Za-z0-9]+|Qgis)\b")

if os.path.isdir(PACKAGE):
    missing = []
    for name in sorted(os.listdir(PACKAGE)):
        if not name.endswith(".py"):
            continue
        text = open(os.path.join(PACKAGE, name), encoding="utf-8").read()
        tree = _ast.parse(text)
        here = set()
        for node in tree.body:
            if isinstance(node, (_ast.Import, _ast.ImportFrom)):
                for alias in node.names:
                    here.add(alias.asname or alias.name)
        wanted = set()
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Constant) and isinstance(node.value, str):
                # a docstring is a string too, and a docstring is prose
                wanted |= set(_looked_up.findall(node.value))
        for word in sorted(wanted - here):
            # only count it when the string is handed to the resolver
            if "first_of" in text and word not in here:
                missing.append((name, word))
    check("every QGIS class named in a string is imported by that module",
          not missing,
          "; ".join("%s names %s and does not import it" % (f, w)
                    for f, w in missing))
else:
    print("  (the package is not beside this suite, so only the built file "
          "was looked at)")

print()
print("no path from somebody's own machine is in the repository")
# A path with a user name in it, or a scratch folder a file was once written
# in, says nothing to anybody else and tells the world whose disk it was. Two
# such paths reached the repository through the tests before anybody looked.
# Forbidden: a Windows user folder, a Linux home folder, a macOS user folder,
# and an absolute path under the two scratch roots, or either root alone, when
# it sits in a string, that is with a quote right before it (the bare root handed to
# os.path.join is as fixed a folder as one below it). A comment that names
# one of those roots in passing is prose and is left alone. The patterns are
# put together from pieces so this file does not match them.
import re as _re
_personal = _re.compile("|".join([
    r"[A-Za-z]:" + r"[\\/]+" + "Users" + r"[\\/]",
    "/" + "home" + r"/[^/\s\"']",
    "/" + "Users" + r"/[^/\s\"']",
    r"[\"']/(" + "tmp" + "|" + "mnt" + r")([\\/]|[\"'])",
]))
_found = []
if os.path.isdir(os.path.join(_ROOT, "rasterlabel")):
    for _top in ("rasterlabel", "tests", "tools", ".github"):
        for _dir, _subs, _files in os.walk(os.path.join(_ROOT, _top)):
            _subs[:] = [d for d in _subs if d != "__pycache__"]
            for _f in _files:
                if _f.startswith("_") and _top == "tests" and _f != "__init__.py":
                    continue                  # rebuilt on every run, ignored
                if not _f.endswith((".py", ".txt", ".md", ".yml", ".yaml")):
                    continue
                _p = os.path.join(_dir, _f)
                for _n, _l in enumerate(open(_p, encoding="utf-8",
                                             errors="replace"), 1):
                    if _personal.search(_l):
                        _found.append("%s:%d" % (os.path.relpath(_p, _ROOT), _n))
    for _f in ("README.md", "CONTRIBUTING.md", "CHANGELOG.md"):
        _p = os.path.join(_ROOT, _f)
        if os.path.exists(_p):
            for _n, _l in enumerate(open(_p, encoding="utf-8"), 1):
                if _personal.search(_l):
                    _found.append("%s:%d" % (_f, _n))
    check("no user folder, home folder or scratch path anywhere", not _found,
          ", ".join(_found[:10]))
else:
    print("  (the repository is not beside this suite, so nothing was walked)")

# ------------------------------------------------------------- Qt 5 and Qt 6
# One code base runs on QGIS 3 (PyQt5) and QGIS 4 (PyQt6). PyQt6 knows an
# enumeration member only through its enumeration: Qt.MouseButton.LeftButton,
# never Qt.LeftButton. PyQt5 takes both, so a short spelling works on the
# machine it was written on and stops the panel from opening on QGIS 4. The
# same goes for importing PyQt5 or PyQt6 by name instead of qgis.PyQt, for
# exec_(), which PyQt6 dropped, and for the "flags" classes such as
# Qt.Orientations, which PyQt6 removed in favour of the enumeration itself.
#
# Every Class.Member in the code (comments and text left out) is asked of the
# binding these suites run on: when Member is a value of an enumeration and
# not the enumeration itself, it is the short spelling.
import io as _io
import enum as _enum
import tokenize as _tokenize

_FLAG_CLASSES = {
    "Alignment", "ApplicationStates", "DockWidgetAreas", "DockWidgetFeatures",
    "Edges", "FindFlags", "ImageConversionFlags", "InputMethodHints",
    "ItemFlags", "KeyboardModifiers", "MatchFlags", "MouseButtons",
    "Orientations", "RenderHints", "StandardButtons", "TextInteractionFlags",
    "ToolBarAreas", "WindowFlags", "WindowStates"}


def _qt_offences(text, binding):
    """(line, what) for every Qt 5 only spelling in the code of text."""
    found = []
    toks = [t for t in _tokenize.generate_tokens(_io.StringIO(text).readline)
            if t.type not in (_tokenize.NL, _tokenize.NEWLINE,
                              _tokenize.COMMENT, _tokenize.INDENT,
                              _tokenize.DEDENT)]
    for i, t in enumerate(toks):
        if t.type == _tokenize.NAME and t.string in ("PyQt5", "PyQt6") and (
                i > 0 and toks[i - 1].string in ("import", "from")):
            found.append((t.start[0], "imports %s by name, not qgis.PyQt"
                          % t.string))
        if (t.string == "exec_" and i > 0 and toks[i - 1].string == "."
                and i + 1 < len(toks) and toks[i + 1].string == "("):
            found.append((t.start[0], "exec_(), which PyQt6 does not have"))
        if (t.type != _tokenize.NAME or i + 2 >= len(toks)
                or toks[i + 1].string != "." or toks[i + 2].type != _tokenize.NAME
                or (i > 0 and toks[i - 1].string == ".")):
            continue
        owner, member = t.string, toks[i + 2].string
        if owner != "Qt" and not re.match(r"^Q[A-Z]\w*$", owner):
            continue
        if owner.startswith(("Qgs", "Qgis")):
            continue
        if member in _FLAG_CLASSES:
            found.append((t.start[0], "%s.%s, a class PyQt6 removed"
                          % (owner, member)))
            continue
        if binding is None:
            continue
        cls = None
        for mod in (binding.QtCore, binding.QtGui, binding.QtWidgets):
            cls = getattr(mod, owner, None)
            if cls is not None:
                break
        if cls is None or not isinstance(cls, type):
            continue                       # not a Qt class: a QGIS one, a fake
        try:
            value = getattr(cls, member)
        except AttributeError:
            found.append((t.start[0], "%s.%s, which %s does not have"
                          % (owner, member, binding.NAME)))
            continue
        if isinstance(value, type):
            continue                       # the enumeration: the long form
        if isinstance(value, _enum.Enum) or (
                isinstance(value, int) and type(value) is not int
                and type(value) is not bool):
            found.append((t.start[0], "%s.%s, the short spelling of an "
                          "enumeration member" % (owner, member)))
    return found


try:
    import qtbinding as _binding
except ImportError:
    _binding = None
    print("  (no Qt binding here: only the names spelt out above are looked at)")
_sources = [SRC]
if os.path.isdir(os.path.join(_ROOT, "rasterlabel")):
    _sources += sorted(
        os.path.join(_ROOT, "rasterlabel", f)
        for f in os.listdir(os.path.join(_ROOT, "rasterlabel"))
        if f.endswith(".py"))
_qt = []
for _p in _sources:
    with open(_p, encoding="utf-8") as _fh:
        for _n, _what in _qt_offences(_fh.read(), _binding):
            _qt.append("%s:%d %s" % (os.path.relpath(_p, _ROOT), _n, _what))
check("every Qt name works on Qt 5 and Qt 6 alike (%s)"
      % (_binding.describe() if _binding else "no binding"), not _qt,
      "; ".join(_qt[:12]) + (" and %d more" % (len(_qt) - 12)
                              if len(_qt) > 12 else ""))
# And the check itself must still see what it is there for.
_probe = ("from PyQt5.QtCore import Qt\nb = Qt.LeftButton\n"
          "x = Qt.Orientations(0)\nd.exec_()\n")
_seen = _qt_offences(_probe, _binding)
check("the Qt check still catches the short spelling, PyQt5 and exec_()",
      len(_seen) == (4 if _binding else 3), _seen)

print()
print("a message level is the enum, never a bare number")
# PyQt5 let QgsMessageBar.pushMessage and QgsMessageLog.logMessage take a
# plain int for the level, so level=0 read as Info for years. PyQt6 checks the
# type and refuses the call: on QGIS 4 the first message of the session, the
# one that says a frame was placed, raised a TypeError instead. The suites ran
# against a stand-in message bar that took anything, which is why nothing
# noticed. LEVEL_INFO and its siblings in constants.py are the enum on both.
_numbered = []
if os.path.isdir(PACKAGE):
    for _name in sorted(os.listdir(PACKAGE)):
        if not _name.endswith(".py"):
            continue
        _tree = _ast.parse(open(os.path.join(PACKAGE, _name),
                                encoding="utf-8").read())
        for _node in _ast.walk(_tree):
            if not (isinstance(_node, _ast.Call) and getattr(
                    _node.func, "attr", None) in ("pushMessage", "logMessage",
                                                  "pushWidget")):
                continue
            _level = [k.value for k in _node.keywords if k.arg == "level"]
            if _node.func.attr == "logMessage" and len(_node.args) >= 3:
                _level.append(_node.args[2])
            if _node.func.attr == "pushMessage" and len(_node.args) >= 3:
                _level.append(_node.args[2])
            # pushWidget(widget, level, duration): the one Whole calls, and
            # the one this check did not look at. pushWidget(bar, 0) was
            # left behind there, and on QGIS 4 Whole wrote nothing at all.
            if _node.func.attr == "pushWidget" and len(_node.args) >= 2:
                _level.append(_node.args[1])
            for _value in _level:
                for _part in _ast.walk(_value):
                    if (isinstance(_part, _ast.Constant)
                            and type(_part.value) is int):
                        _numbered.append("%s:%d" % (_name, _node.lineno))
    check("every message level is LEVEL_INFO, LEVEL_WARNING and the like",
          not _numbered, ", ".join(_numbered))
else:
    print("  (the package is not beside this suite, so nothing was read)")

print()
print("what first_of() finds is compared with None, never taken as true")
# The check above looks at the call. This one looks at where the level came
# from. LEVEL_INFO was once first_of("Qgis.MessageLevel.Info", ...) or 0, and
# Info is worth 0, so on QGIS 4 the "or" threw the enum away and handed the
# message bar the bare 0 again. Every call site read LEVEL_INFO and passed the
# check above. The first member of an enumeration is often worth 0, so a
# lookup through first_of() or first_attr() is never the operand of and/or/not
# and never the test of an if, a while or a conditional expression.
_truthy = []


def _is_lookup(node):
    return (isinstance(node, _ast.Call)
            and getattr(node.func, "id", getattr(node.func, "attr", None))
            in ("first_of", "first_attr"))


if os.path.isdir(PACKAGE):
    for _name in sorted(os.listdir(PACKAGE)):
        if not _name.endswith(".py"):
            continue
        _tree = _ast.parse(open(os.path.join(PACKAGE, _name),
                                encoding="utf-8").read())
        for _node in _ast.walk(_tree):
            _tested = []
            if isinstance(_node, _ast.BoolOp):
                _tested = list(_node.values)
            elif isinstance(_node, _ast.UnaryOp) and isinstance(
                    _node.op, _ast.Not):
                _tested = [_node.operand]
            elif isinstance(_node, (_ast.If, _ast.While, _ast.IfExp,
                                    _ast.Assert)):
                _tested = [_node.test]
            for _value in _tested:
                if _is_lookup(_value):
                    _truthy.append("%s:%d" % (_name, _value.lineno))
    check("no first_of() or first_attr() result is taken as true or false",
          not _truthy, ", ".join(_truthy))
else:
    print("  (the package is not beside this suite, so nothing was read)")

print()
print("no line continuation was lost")
# A backslash and its line break that were turned into a run of spaces leave a
# line of one hundred and more columns that still runs, and hides the
# condition behind a screen of blanks. Ten spaces or more between two tokens
# of a line of code is never alignment in this code base (comments and text
# are not code and are left alone).


def _blank_runs(text):
    found = []
    prev = None
    for t in _tokenize.generate_tokens(_io.StringIO(text).readline):
        if t.type in (_tokenize.INDENT, _tokenize.DEDENT):
            prev = None
            continue
        if (prev is not None and prev.end[0] == t.start[0]
                and t.start[1] - prev.end[1] >= 10
                and t.type not in (_tokenize.COMMENT, _tokenize.NEWLINE,
                                   _tokenize.NL)):
            found.append(t.start[0])
        prev = t
    return found


_lost_probe = "x = (a" + " " * 17 + "or b)\n"
check("the check sees a lost continuation and leaves a comment alone",
      _blank_runs(_lost_probe) == [1]
      and _blank_runs("x = 1" + " " * 12 + "# not code\n") == []
      and _blank_runs("x = 'a" + " " * 12 + "b'\n") == [])
_lost = []
for _top in ("rasterlabel", "tools", "tests"):
    _folder = os.path.join(_ROOT, _top)
    if not os.path.isdir(_folder):
        continue
    for _f in sorted(os.listdir(_folder)):
        if not _f.endswith(".py"):
            continue
        with open(os.path.join(_folder, _f), encoding="utf-8") as _fh:
            for _n in _blank_runs(_fh.read()):
                _lost.append("%s/%s:%d" % (_top, _f, _n))
check("no line of code has a run of ten blanks inside it", not _lost,
      ", ".join(_lost[:10]))

print()
print("every suite takes a home of its own before anything else")
# A suite started by hand used the real home, and its Cutouts appended
# to the log of whoever ran it. scratch_home.py is the cure, and it only
# works when it is the first thing a suite imports.
_late = []
for _name in sorted(os.listdir(_HERE)):
    if not (_name.startswith("test_") and _name.endswith(".py")):
        continue
    _body = _ast.parse(open(os.path.join(_HERE, _name),
                            encoding="utf-8").read()).body
    _first = [n for n in _body
              if isinstance(n, (_ast.Import, _ast.ImportFrom))
              and getattr(n, "module", None) != "__future__"][:1]
    if not (_first and isinstance(_first[0], _ast.Import)
            and _first[0].names[0].name == "scratch_home"):
        _late.append(_name)
check("each one imports scratch_home first", not _late, ", ".join(_late))

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
