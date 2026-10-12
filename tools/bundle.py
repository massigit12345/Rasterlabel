"""Fold the package back into one file.

RasterLabel is read as a package and run as a package when it is installed as a
QGIS plugin. It is also pasted into the Python Console as a single file, which is
how most people will meet it and how it is developed. Rather than keep two copies
of twelve thousand lines, the single file is built from the package by this
script: the modules are concatenated in the order the package itself imports
them, the imports between modules are dropped because after the concatenation
every name is already in the one namespace, and the imports of everything else
are collected into one block at the top.

    python3 tools/bundle.py                  # writes dist/rasterlabel.py
    python3 tools/bundle.py --check           # says whether dist is up to date

The order below is a promise, and the one the package makes too: nothing in a
module needs a name from a module further down at the moment it is imported.
"""
import argparse
import ast
import io
import os
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG = os.path.join(ROOT, "rasterlabel")

ORDER = [
    "constants", "compat", "naming", "project", "errors", "stats",
    "agreement", "reports", "view", "layout", "theme", "widgets", "design",
    "campaign", "detection", "journal", "rasters", "geometry", "layers", "recovery",
    "report_rasters", "correction", "effort", "compare", "model_vs_corrected",
    "card", "uncertainty", "tools", "dialogs", "ui_compare", "ui_time",
    "ui_mvc", "ui_card", "ui_uncertainty", "ui_import_frames",
    "sections_annotate", "sections_correct", "sections_cutouts",
    "sections_objects", "export", "doctor", "measure", "panel",
    "processing_provider", "launch",
]

BANNER = '''# =====================================================================
#  RasterLabel %(version)s
#
#  A QGIS panel for drawing labels on a raster: areas, lines and points, with a
#  legend of your own, saved as real geometry in a GeoPackage and exportable as
#  the masks a training run needs.
#
#  Paste these two lines into the QGIS Python Console:
#      p = r"...\\rasterlabel.py"
#      exec(compile(open(p, encoding="utf-8").read(), p, "exec"))
#
#  THIS FILE IS BUILT, NOT WRITTEN. It is the package under rasterlabel/ folded
#  into one file by tools/bundle.py, in this order:
#      %(order)s
#  Edit the modules, then run tools/bundle.py. Editing this file means losing
#  the edit the next time anybody builds.
#
#  Copyright (C) 2026 Massimiliano Guastella. Free software under the GNU
#  General Public License, version 2 or (at your option) any later version;
#  WITHOUT ANY WARRANTY. See LICENSE. SPDX-License-Identifier: GPL-2.0-or-later
# =====================================================================
'''


# The last line of the single file is what makes pasting it into the console do
# something. The package has no such line: there, the plugin's classFactory or
# the console calls start() itself, which is why this lives in the builder and
# not in launch.py.
FOOTER = """

# ---------------------------------------------------------------------
#  Pasted into the console, this is the line that puts the panel up. It takes
#  any panel from an earlier paste down first and gives back every signal it
#  was holding, so reloading after a change needs no restart.
# ---------------------------------------------------------------------
start()
"""


def read(name):
    path = os.path.join(PKG, name + ".py")
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def version_of():
    """The one place the version is written: rasterlabel/constants.py."""
    for node in ast.parse(read("constants")).body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if getattr(t, "id", None) == "VERSION":
                    return node.value.value
    return "unknown"


def split_module(name):
    """What it borrows from outside, what it defines, and the rest of its text.

    Three things come back. The imports of the outside world, as structured
    pieces rather than lines of text, so that twenty modules asking for Qt in
    twenty different groupings become one import at the top instead of twenty
    overlapping ones. The names it defines at the top level, which is how the
    collision check below knows that two modules have each defined set_aside.
    And its body, with the imports and its own docstring taken out.
    """
    source = read(name)
    lines = source.splitlines(True)
    tree = ast.parse(source)
    plain, froms, defines, aliases, drop = [], [], [], [], set()
    for node in tree.body:
        span = range(node.lineno - 1, node.end_lineno)
        if isinstance(node, ast.ImportFrom) and node.level:
            # A name from a sibling module: after the concatenation it is simply
            # there. Except when it was renamed on the way in, which the bundle
            # has to do by hand.
            for a in node.names:
                if a.asname:
                    aliases.append((a.asname, a.name))
            drop.update(span)
            continue
        if isinstance(node, ast.Import):
            for a in node.names:
                plain.append((a.name, a.asname))
            drop.update(span)
            continue
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                froms.append((node.module, a.name, a.asname))
            drop.update(span)
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str) and node is tree.body[0]:
            drop.update(span)            # the module's own docstring
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            defines.append(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            # Every way a top level statement can bind a name, not only the
            # plain one. doctor.py binds OK, NOTE and BAD in a single tuple and
            # compat.py binds iface inside an except handler; a guard that
            # cannot see those would let a future collision through silently,
            # which is the one failure this guard exists to prevent.
            for t in (node.targets if isinstance(node, ast.Assign)
                      else [node.target]):
                for sub_node in ast.walk(t):
                    if isinstance(sub_node, ast.Name):
                        defines.append(sub_node.id)
        elif isinstance(node, (ast.Try, ast.If, ast.For, ast.While,
                               ast.With)):
            # A name bound inside a top level try, if or loop is a top level
            # name too. compat.py binds iface in an except handler and in the
            # try beside it, which is exactly the shape this missed.
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    defines.append(sub.id)
                elif isinstance(sub, (ast.Import, ast.ImportFrom)):
                    for a in sub.names:
                        defines.append((a.asname or a.name).split(".")[0])
                elif isinstance(sub, (ast.FunctionDef, ast.ClassDef)):
                    defines.append(sub.name)
    body = "".join(l for i, l in enumerate(lines) if i not in drop)
    return plain, froms, defines, aliases, body.strip("\n")


def import_block(plain, froms):
    """One import per module, with the union of every name anybody asked for."""
    out = []
    for name, asname in sorted(set(plain)):
        out.append("import %s%s" % (name, " as %s" % asname if asname else ""))
    out.append("")
    by_module = {}
    for module, name, asname in froms:
        by_module.setdefault(module, set()).add(
            name + (" as %s" % asname if asname else ""))
    for module in sorted(by_module, key=lambda m: (m.startswith("qgis"), m)):
        names = sorted(by_module[module], key=lambda s: (s.lower(), s))
        one = "from %s import %s" % (module, ", ".join(names))
        if len(one) <= 79:
            out.append(one)
            continue
        head = "from %s import (" % module
        wrapped = textwrap.wrap(", ".join(names), width=78 - len(head),
                                break_long_words=False)
        out.append(head + wrapped[0])
        for extra in wrapped[1:]:
            out.append(" " * len(head) + extra)
        out[-1] += ")"
    return "\n".join(out) + "\n"


def build():
    plain, froms, pieces, seen = [], [], [], {}
    clash = []
    for name in ORDER:
        p, f, defines, aliases, body = split_module(name)
        plain.extend(p)
        froms.extend(f)
        for d in defines:
            # Assigning the same name twice inside one module is ordinary Python
            # and the module is the one deciding what it means. Two modules both
            # claiming it is the thing one flat namespace cannot hold.
            if d in seen and seen[d] != name and not d.startswith("_"):
                clash.append("%s is defined in both %s and %s"
                             % (d, seen[d], name))
            seen[d] = name
        head = ("# %s\n# ---- %s %s\n# %s\n"
                % ("-" * 69, name, "-" * max(1, 64 - len(name)), "-" * 69))
        if aliases:
            # from .x import y as z becomes z = y, because after the
            # concatenation y is already in this one namespace
            body = ("# the names this module had under another spelling\n"
                    + "".join("%s = %s\n" % (a, b) for a, b in aliases)
                    + "\n" + body)
        pieces.append(head + "\n" + body + "\n")
    if clash:
        # Two modules may each have a set_aside; one flat namespace may not. The
        # package would not notice, the single file would silently use whichever
        # came last, and the two would stop being the same program.
        raise SystemExit("the single file cannot be built:\n  "
                         + "\n  ".join(clash))
    head = BANNER % {"version": version_of(),
                     "order": "\n#      ".join(
                         ", ".join(ORDER[i:i + 4]) for i in range(0, len(ORDER), 4))}
    return (head + "\n" + import_block(plain, froms) + "\n\n"
            + "\n".join(pieces) + FOOTER)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "rasterlabel.py"))
    ap.add_argument("--check", action="store_true",
                    help="do not write: say whether what is there is current")
    args = ap.parse_args()
    text = build()
    compile(text, args.out, "exec")      # never ship something that will not parse
    if args.check:
        try:
            # Read the way it is written, with no translation of line endings,
            # so a copy with Windows line endings shows up as out of date
            # instead of passing
            with io.open(args.out, encoding="utf-8", newline="\n") as fh:
                current = fh.read()
        except IOError:
            print("%s is not there: run tools/bundle.py" % args.out)
            return 1
        if current != text:
            print("%s is out of date: run tools/bundle.py" % args.out)
            return 1
        print("%s is current" % args.out)
        return 0
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    # Always "\n", whatever the system writing it uses. The build fingerprint is
    # taken from the bytes of this file, and one built on Windows has to be the
    # same file, byte for byte, as one built on Linux from the same commit.
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("%s: %d lines from %d modules"
          % (args.out, text.count("\n"), len(ORDER)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
