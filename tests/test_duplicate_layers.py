"""The QGIS project keeps the layers, and reopening the campaign must not turn
them into two.

A saved project brings the RasterLabel layers back, pointing at the same
GeoPackage. If the program does not recognise them when the campaign is opened,
it adds a second group on top: two layers, one table, two styles, and the map
draws everything twice. Here the fake project already holds those layers, and
we watch what happens.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast
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


PACK = "/data/campaign/annotation.gpkg"
TABLES = [("tiles", 0, 0), ("polygons", 0, 0), ("lines", 0, 0),
          ("points", 0, 0), ("boxes", 0, 0)]


class Layer(object):
    """The little of a QgsVectorLayer that is needed here."""
    def __init__(self, path, table, ident, props=None, valid=True):
        self._s = "%s|layername=%s" % (path, table)
        self._id = ident
        self.props = dict(props or {})
        self.valid = valid
    def source(self): return self._s
    def id(self): return self._id
    def name(self): return self._id
    def isValid(self): return self.valid
    def customProperty(self, k, default=None):
        return self.props.get(k, default)
    def setCustomProperty(self, k, v): self.props[k] = v


class Project(object):
    def __init__(self, layers):
        self.layers = {l.id(): l for l in layers}
        self.removed = []
    def mapLayers(self): return dict(self.layers)
    def removeMapLayers(self, ids):
        self.removed.extend(ids)
        for i in ids:
            self.layers.pop(i, None)


PROJECT = {"p": None}
g = {"os": os, "TABLES": TABLES, "PREFIX": "rasterlabel",
     "log": lambda *a, **k: None,
     "QgsProject": type("Q", (), {"instance": staticmethod(
         lambda: PROJECT["p"])})}
g["_OWN_HANDS"] = [0]         # what own_hands counts with
exec(take("own_hands"), g)
exec(take("mark"), g)
exec(take("find_mine"), g)
exec(take("my_layers"), g)
exec(take("strays_of", "Panel"), g)
exec(take("claim_strays", "Panel"), g)
exec(take("file_key"), g)
exec(take("reads_file"), g)
exec(take("drop_stale"), g)


class FakeCampaign(object):
    package_path = PACK
    data = {"id": "abc123"}


class FakePanel(object):
    campaign = FakeCampaign()
    strays_of = g["strays_of"]
    claim_strays = g["claim_strays"]


print("a project that has never seen the campaign")
PROJECT["p"] = Project([])
p = FakePanel()
check("nothing to adopt", p.claim_strays() == (0, 0))

print()
print("the project brings the RasterLabel layers back")
# the way QGIS finds them again after a save: right source, properties lost
found = [Layer(PACK, t, "L%s" % t) for t, _, _ in TABLES]
PROJECT["p"] = Project(found)
p = FakePanel()
adopted, dropped = p.claim_strays()
check("it adopts all five of them", adopted == 5, adopted)
check("without dropping anything", dropped == 0, dropped)
check("and from here on the program finds them again",
     all(g["find_mine"]("abc123", t) is not None for t, _, _ in TABLES))
check("no layer was removed from the project",
      not PROJECT["p"].removed, PROJECT["p"].removed)

print()
print("two copies of the same table: this is what drew everything twice")
twins = ([Layer(PACK, "polygons", "old",
                {"rasterlabel/campaign": "abc123",
                 "rasterlabel/role": "polygons"}),
          Layer(PACK, "polygons", "new")]
         + [Layer(PACK, t, "L%s" % t)
            for t, _, _ in TABLES if t != "polygons"])
PROJECT["p"] = Project(twins)
p = FakePanel()
adopted, dropped = p.claim_strays()
check("only one is left", dropped == 1, dropped)
check("and the one left is the already marked one, not the other",
      "new" in PROJECT["p"].removed, PROJECT["p"].removed)
check("the one kept is still in the project",
      "old" in PROJECT["p"].mapLayers(), list(PROJECT["p"].mapLayers()))
check("the other tables were adopted", adopted == 4, adopted)

print()
print("three copies: one is left, not two")
PROJECT["p"] = Project([Layer(PACK, "polygons", "a"),
                        Layer(PACK, "polygons", "b"),
                        Layer(PACK, "polygons", "c")])
p = FakePanel()
adopted, dropped = p.claim_strays()
check("two dropped", dropped == 2, dropped)
check("one kept", len(PROJECT["p"].mapLayers()) == 1,
      list(PROJECT["p"].mapLayers()))

print()
print("what must not be touched")
other = Layer("/data/other_campaign/annotation.gpkg", "polygons", "someone")
raster = Layer("/data/ortho.tif", "", "raster")
PROJECT["p"] = Project([other, raster, Layer(PACK, "polygons", "mine")])
p = FakePanel()
adopted, dropped = p.claim_strays()
check("another campaign's package stays where it is",
      "someone" in PROJECT["p"].mapLayers(), PROJECT["p"].removed)
check("and a raster is not even looked at",
      "raster" in PROJECT["p"].mapLayers(), PROJECT["p"].removed)
check("our own is adopted", adopted == 1, adopted)

print()
print("the same file written two ways is the same file")
odd = Layer("/data/campaign/../campaign/annotation.gpkg", "polygons", "bent")
PROJECT["p"] = Project([odd, Layer(PACK, "polygons", "straight")])
p = FakePanel()
adopted, dropped = p.claim_strays()
check("recognised as one single file", dropped == 1, dropped)

print()
print("and the order matters: adopt first, then add")
ll = take("load_layers", "Panel")
i_claim = ll.find("self.claim_strays()")
i_add = ll.find("QgsVectorLayer(")
check("claim_strays comes before QgsVectorLayer",
      0 <= i_claim < i_add, (i_claim, i_add))

print()
print("a copied or moved campaign: the project's layers read the old place")
ROLES = [t for t, _, _ in TABLES]
OLD = "/data/original/annotation.gpkg"
marked = {"rasterlabel/campaign": "abc123"}
copied = [Layer(OLD, t, "old_" + t, dict(marked, **{"rasterlabel/role": t}))
          for t in ROLES]
moved = Layer("/gone/annotation.gpkg", "polygons", "gone",
              dict(marked, **{"rasterlabel/role": "polygons"}), valid=False)
keep = Layer(PACK, "lines", "right", dict(marked,
                                           **{"rasterlabel/role": "lines"}))
corr = Layer("/data/original/fix.tif", "", "corr",
             dict(marked, **{"rasterlabel/role": "correction:fix"}))
PROJECT["p"] = Project(copied + [moved, keep, corr])
gone = g["drop_stale"]("abc123", PACK, ROLES)
check("every layer of the campaign that reads another file goes",
      all("old_" + t in PROJECT["p"].removed for t in ROLES),
      PROJECT["p"].removed)
check("and one whose file is not there", "gone" in PROJECT["p"].removed,
      PROJECT["p"].removed)
check("the one that reads the campaign's own package stays",
      "right" in PROJECT["p"].mapLayers(), PROJECT["p"].removed)
check("and a layer of another role is not looked at",
      "corr" in PROJECT["p"].mapLayers(), PROJECT["p"].removed)
check("it says how many", gone == len(ROLES) + 1, gone)
check("find_mine then finds the right one, or none",
      g["find_mine"]("abc123", "lines") is keep
      and g["find_mine"]("abc123", "polygons") is None)
check("an invalid layer never reads the file, whatever its source says",
      not g["reads_file"](Layer(PACK, "points", "x", valid=False), PACK))
if os.name == "nt":
    check("on Windows the case and the slashes do not matter",
          g["file_key"]("C:/Data/Camp/annotation.gpkg")
          == g["file_key"](r"c:\data\camp\ANNOTATION.gpkg"))
    check("nor the long path prefix",
          g["file_key"](r"\\?\C:\data\a.gpkg")
          == g["file_key"](r"C:\data\a.gpkg"))
ll = take("load_layers", "Panel")
check("load_layers drops them before it adopts anything",
      0 <= ll.find("drop_stale(") < ll.find("self.claim_strays()"))
add = take("add_layer")
check("and add_layer reuses a layer only if it reads the same file",
      "reads_file(existing" in add)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
