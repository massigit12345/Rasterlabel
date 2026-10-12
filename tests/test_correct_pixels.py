"""Correct changes the pixels it was told to change, and no others.

This is the module's whole promise. You load a class map an algorithm produced,
the program works on a copy of it, you pick which class is eligible and which
class you are holding, and then you draw generously: a stroke far bigger than
the mistake, confident that only the pixels of the chosen class inside it will
move. A brush that is careful about where you put it is a brush you have to be
careful with, and the point of this one is that you do not.

Nothing tested that. Every other part of the program has a suite that runs real
arithmetic; Correct was only ever built offscreen and had its buttons pressed.
So the decision is taken out of paint() by name and run against arrays whose
every pixel is known, which means this suite fails the moment somebody changes
what the brush is allowed to touch.

The arithmetic is lifted from the source rather than written out again here. A
copy would pass forever while the program drifted away from it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import os as _os

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os
import sys

import numpy as np

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
                    text = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in text.splitlines())
    raise AssertionError("%s not found" % name)


# ------------------------------------------------- the decision, lifted out
paint = take("paint", "CorrectionSection")
# from the start of that line, not from the middle of it, or the first line
# comes out with no indentation and dedent has nothing in common to remove
_at = paint.index("wanted = self.from_code")
start = paint.rindex("\n", 0, _at) + 1
_at = paint.index("pixels = int(change.sum())")
end = paint.rindex("\n", 0, _at) + 1
import textwrap
DECISION = textwrap.dedent(paint[start:end])

# Only three things are changed, and each one is a thing this file has to be
# able to see: where the eligible class comes from, where the class in hand
# comes from, and what "give up" looks like. The arithmetic itself is untouched,
# which is the whole point: if the program starts reaching for something new in
# here, the exec below raises instead of quietly testing less than this file
# claims to test.
DECISION = DECISION.replace("self.from_code", "target")
DECISION = DECISION.replace("self.current_code()", "into")
DECISION = DECISION.replace("self.nodata", "nodata")

_kept = []
for _line in DECISION.splitlines():
    _bare = _line.strip()
    if _bare.startswith(("iface.messageBar", "NAME,", "level=LEVEL_WARNING")):
        continue                       # the message bar is not under test
    if _bare == "return":
        pad = _line[:len(_line) - len(_line.lstrip())]
        _kept.append(pad + "refused.append('same class')")
        _kept.append(pad + "raise StopIteration")
        continue
    _kept.append(_line)
DECISION = "\n".join(_kept)


def decide(window, inside, target, into, nodata=None):
    """Run the program's own lines, and say which pixels they would change."""
    space = {"window": window, "inside": inside, "target": target,
             "into": into, "nodata": nodata, "refused": [], "np": np}
    try:
        exec(compile(DECISION, "<paint>", "exec"), space)
    except StopIteration:
        return None, space["refused"]
    return space.get("change"), space["refused"]


print("the lines under test came out of the program, not out of this file")
check("the eligible-class branch is there", "wanted = target" in DECISION
      or "wanted" in DECISION)
check("and the every-class branch, which spares only nodata",
      "valid = np.ones(window.shape, dtype=bool)" in DECISION
      and "valid = window != 0" not in DECISION)
check("and nothing of the panel is left in them",
      "self." not in DECISION, [l for l in DECISION.splitlines()
                                if "self." in l])

# ----------------------------------------------------------- the test ground
#
#   a class map with four classes and a hole of nodata, and a stroke drawn
#   generously across all of it
#
CROP, MUD, WATER, ROCK, NODATA = 1, 2, 3, 4, 255
window = np.array([
    [CROP,  CROP,  MUD,   MUD,   WATER],
    [CROP,  MUD,   MUD,   MUD,   WATER],
    [ROCK,  MUD,   MUD,   NODATA, WATER],
    [ROCK,  ROCK,  MUD,   NODATA, 0],
    [ROCK,  ROCK,  WATER, WATER, 0],
], dtype=np.uint8)
# the stroke: everything except the last column, which is outside it
inside = np.ones(window.shape, dtype=bool)
inside[:, 4] = False

print()
print("one class chosen: the brush is a selector")
# This is the thing being asked for. Draw far wider than the mistake, say "only
# mud", and only mud moves.
change, refused = decide(window.copy(), inside, MUD, WATER, nodata=NODATA)
check("something changes", change is not None and change.any())
hit = window[change]
check("every pixel it would change is of the chosen class",
      set(np.unique(hit).tolist()) == {MUD}, np.unique(hit).tolist())
check("it changes all of them that are inside the stroke",
      int(change.sum()) == int(((window == MUD) & inside).sum()),
      (int(change.sum()), int(((window == MUD) & inside).sum())))
check("nothing outside the stroke is touched", not change[:, 4].any())
check("the other classes are left alone",
      not change[(window == CROP) | (window == ROCK)].any())
check("and the nodata hole is left alone", not change[window == NODATA].any())

after = window.copy()
after[change] = WATER
check("after the stroke there is no mud left inside it",
      not ((after == MUD) & inside).any())
check("and the mud outside it is untouched",
      (after[:, 4] == window[:, 4]).all())
check("nothing became a class nobody asked for",
      set(np.unique(after).tolist()) <= {CROP, WATER, ROCK, NODATA, 0},
      np.unique(after).tolist())

print()
print("the same stroke, a different class chosen, moves different pixels")
other, _ = decide(window.copy(), inside, ROCK, CROP, nodata=NODATA)
check("only rock this time",
      set(np.unique(window[other]).tolist()) == {ROCK},
      np.unique(window[other]).tolist())
check("and it is a different set of pixels than the mud stroke",
      not (other & change).any())

print()
print("asking to change a class into itself is refused, not silently applied")
change, refused = decide(window.copy(), inside, MUD, MUD, nodata=NODATA)
check("nothing is changed", change is None, change)
check("and it says why", refused == ["same class"], refused)

print()
print("every class chosen: the brush is a boundary")
# A correction's classes are the map's own, and zero is one of them unless it
# is the nodata value: a land cover map numbered from zero has a real class
# there. So one zero goes inside the stroke, where the brush can reach it.
ground = window.copy()
ground[0, 0] = 0
change, _ = decide(ground.copy(), inside, None, WATER, nodata=NODATA)
check("something changes", change is not None and change.any())
check("the nodata hole is still left alone",
      not change[ground == NODATA].any())
check("zero inside the stroke is a class, and it changes",
      bool(change[0, 0]))
check("nothing outside the stroke is touched", not change[:, 4].any())
check("everything inside the stroke that is not nodata or already water "
      "changes",
      int(change.sum())
      == int((inside & (ground != NODATA) & (ground != WATER)).sum()),
      int(change.sum()))
check("what was already water is not counted as work",
      not change[ground == WATER].any())

print()
print("with no nodata declared, nothing in the stroke is spared")
change, _ = decide(ground.copy(), inside, None, CROP, nodata=None)
check("the hole is treated as a class like any other",
      change[ground == NODATA].any())
check("and so is zero", bool(change[0, 0]))

print()
print("when zero is the nodata value, zero is what is spared")
change, _ = decide(ground.copy(), inside, None, CROP, nodata=0)
check("the zero inside the stroke is left alone", not change[0, 0])
check("and 255, no longer nodata, is a class the boundary covers",
      change[ground == NODATA].any())

print()
print("the brush never reaches outside the stroke, whatever is asked of it")
for target in (None, CROP, MUD, WATER, ROCK, NODATA, 0):
    change, _ = decide(window.copy(), inside, target, 7, nodata=NODATA)
    if change is None:
        continue
    if change[~inside].any():
        check("target %r stays inside the stroke" % target, False)
        break
else:
    check("every one of the seven choices stays inside the stroke", True)

print()
print("and the panel really does offer that choice")
build = take("build", "CorrectionSection")
check("there is a row of FROM chips for which class to change",
      "self.from_grid = QGridLayout()" in build)
check("'any class' is the first of them, standing for no code",
      '[{"code": None, "name": ANY_CLASS}] + list(self.classes())' in source)
check("and one per class, carrying its code",
      "lambda _=False, k=code: self.choose_from(k)" in source)
check("the tooltips say what the two kinds mean",
      "whatever the stroke covers becomes" in source
      and "leaves every other class alone" in source)

print()
print("the original is never the thing being changed")
bc = take("build_copy")
check("the chosen layer is opened to be read", "src = open_raster(source)" in bc)
check("and a new file is made for the copy, from it",
      "_translate(tmp, src" in bc)
check("nothing is ever written back to the source",
      "WriteArray" not in bc and "GA_Update" not in bc.split("_translate")[0])
check("and the copy gains no band: it is the map, band for band",
      "FLAG_BAND_NAME" not in bc and "bandList" not in bc)
pw = take("paint", "CorrectionSection")
ws = take("write_stroke", "CorrectionSection")
check("the brush writes to the copy's band",
      "self.write_stroke(after, marks_after, col, row" in pw
      and "write_window(self.path, self.band_no, values" in ws)
check("and marks what a person moved in the record beside it",
      "marks_after[change] = 1" in pw
      and "write_window(self.changes_path, 1, marks" in ws)
check("while the original is not touched by it", "self.source" not in pw)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
