"""The layers that end up in QGIS carry the name of the campaign.

Actually run: the part of Campaign that builds the names is taken from the
source and executed against real manifests, the awkward ones included. At the
bottom, declared as such, three checks on the text of the source to verify
that load_layers really does use the name and that the exported files use the
same one.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast
import os
import re
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


g = {"re": re, "NAME": "RasterLabel"}
exec(take("tidy"), g)
# stem and layer_name are properties of Campaign: take them and mount them on
# a fake class that has nothing but a manifest, which is all they read.
src = take("stem", "Campaign") + "\n" + take("layer_name", "Campaign")
src = src.replace("@property\n", "")
exec(src, g)


class Fake(object):
    def __init__(self, name):
        self.data = {"name": name}
    stem = property(g["stem"])
    layer_name = g["layer_name"]


TABLES = ("tiles", "polygons", "lines", "points", "boxes")

print("the campaign name in front of every table")
c = Fake("aragona_2025")
for t in TABLES:
    got = c.layer_name(t)
    check("%-8s -> %s" % (t, "aragona_2025_" + t), got == "aragona_2025_" + t,
          got)

print()
print("an awkward name does not make an awkward layer")
for name, expected in (("north site 2026", "north_site_2026"),
                       ("Aragona 2025 (test)", "Aragona_2025_test"),
                       ("  spaces  around  ", "spaces_around"),
                       ("city'/north", "city_north"),
                       ("perc%ent&and+signs", "perc_ent_and_signs"),
                       ("", "campaign"),
                       ("____", "campaign")):
    got = Fake(name).stem
    check("%-24r -> %s" % (name, expected), got == expected, got)

check("a manifest with no name blows nothing up",
      Fake(None).stem == "campaign", Fake(None).stem)
long_name = "x" * 200
check("a very long name is cut short", len(Fake(long_name).stem) == 48,
      len(Fake(long_name).stem))

print()
print("two campaigns open together no longer have two layers alike")
a = Fake("aragona_2025")
b = Fake("licata_2026")
dupes = [t for t in TABLES if a.layer_name(t) == b.layer_name(t)]
check("no name in common", not dupes, dupes)

print()
print("the name of the layer is the name of the file that comes out")
# write_vectors writes stem_table.ext, and stem is now the same as layer_name
for t in TABLES:
    expected = "%s_%s" % (a.stem, t)
    check("%-8s: layer %s, file %s.gpkg" % (t, a.layer_name(t), expected),
          a.layer_name(t) == expected)

print()
print("checks on the text of the source (these are not trials)")
ll = take("load_layers", "Panel")
check("load_layers asks the campaign for the name",
      "self.campaign.layer_name(table)" in ll)
check("and it sets it again on a layer already in the project",
      "live.setName(wanted)" in ll)
check("the table keeps its real name inside the package",
      "layername=%s" % "%s" in ll or "layername=" in ll)
check("the export uses the same stem as the layers",
      source.count("stem = self.campaign.stem") == 3)
check("and nobody recomputes it on their own",
      'stem = tidy(self.campaign.data.get("name"' not in source)
add = take("add_layer")
check("the layers are found again by property, not by name",
      "find_mine(campaign.data[\"id\"], role)" in add and ".name()" not in add)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
