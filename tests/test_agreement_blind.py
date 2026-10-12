"""Compare two readings never shows a blind reader the other reading.

What is checked, on the real panel with QGIS and GDAL faked (correctkit):

- hidden_from, the rule, case by case: one operator at a time hides the
  other operators in every pass; blind hides every other pass, the earlier
  ones and the later ones alike;
- the same rule is the one Annotate's filter applies: apply_filter still
  builds its two clauses on the operator and on "pass_no" under hiding(),
  and hiding() is just the blind switch, so the two cannot
  drift apart (read from the built file, as test_filter_survives does);
- Measure ▸ Compare two readings… refuses, with no window shown, while
  the filter hides one of the two readings from the reader in hand, Annotate
  open; the refusal says what, why and the way out;
- with the filter off and Annotate closed, the window offers both, and a
  reading with frames touched but not closed is said, with its frames, and
  asked about, Cancel first: Cancel runs nothing, Compare runs it;
- the readings the reader may not see are not offered at all;
- the layers of a report are marked with the readings they show, and the
  panel's veil switches them off for a reader who may not see one of them.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correctkit as K                                             # noqa: E402

g, check = K.g, K.check
QtWidgets = K.QtWidgets

print("hidden_from, case by case")
hf = g["hidden_from"]
check("ANNA in pass 1, one operator at a time and blind: BRUNO's pass 1 "
      "is hidden", hf(("ANNA", 1), ("BRUNO", 1), True, True))
check("and her own is not", not hf(("ANNA", 1), ("ANNA", 1), True, True))
check("ANNA in pass 2, blind, all operators: her pass 1 is hidden",
      hf(("ANNA", 2), ("ANNA", 1), False, True))
check("and BRUNO's pass 2 is not", not hf(("ANNA", 2), ("BRUNO", 2), False,
                                          True))
check("ANNA in pass 1, blind, all operators: BRUNO's pass 1 is not hidden, "
      "but her own pass 2 is: blind shows only the pass in hand, "
      "whichever it is", not hf(("ANNA", 1), ("BRUNO", 1), False, True)
      and hf(("ANNA", 1), ("ANNA", 2), False, True))
check("ANNA in pass 1, not blind: no pass is hidden",
      not hf(("ANNA", 1), ("ANNA", 2), False, False))
check("ANNA in pass 3, one operator at a time, not blind: BRUNO's pass 3 is "
      "hidden", hf(("ANNA", 3), ("BRUNO", 3), True, False))
check("and her pass 1 is not", not hf(("ANNA", 3), ("ANNA", 1), True, False))

print()
print("the rule is the filter's own")
source = open(K.SRC, encoding="utf-8").read()
tree = ast.parse(source)


def method(cls, name):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    return ast.get_source_segment(source, sub)
    return ""


def function(name):
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    return ""


flt = method("AnnotationSection", "apply_filter")
check("apply_filter is there", bool(flt))
check("its first clause: the operator, by operator_name(), under 'one "
      "operator at a time'",
      "if self.by_operator.isChecked():" in flt
      and "upper(trim(\\\"operator\\\"))" in flt
      and "sql_text(self.operator_name())" in flt, flt[:400])
check("its other clause: the pass, under hiding()",
      "if self.hiding():" in flt
      and "coalesce(\\\"pass_no\\\", 1) = %d" in flt
      and "self.pass_no.value()" in flt, flt[-1200:])
hiding = method("AnnotationSection", "hiding")
check("hiding() is the blind switch, in any pass",
      "return bool(self.blind.isChecked())" in hiding
      and "pass_no.value() > 1" not in hiding, hiding)
rule = function("hidden_from")
check("hidden_from says the same two things",
      "(one_operator and op != who)" in rule
      and "(blind and p != when)" in rule, rule)

print()
print("refused while the filter hides a reading")


class Section(object):
    """Annotate as far as Compare asks: saved, nothing pending."""
    def unsaved(self): return False
    def save(self): pass


class Campaign(object):
    # a folder that need not exist, and not a deep one: Compare asks whether
    # QGIS could open the GeoPackage at the end of the path it is given, and
    # a checkout in a deep folder of Windows would be refused
    folder = os.path.join(tempfile.gettempdir(), "aragona_blind")
    package_path = os.path.join(folder, "annotation.gpkg")
    data = {"id": "blind1", "name": "aragona_blind", "with_tiles": True,
            "operator": "ANNA", "operators": ["ANNA", "BRUNO"],
            "classes": [{"code": 1, "name": "crater", "colour": "#2a78d6"},
                        {"code": 2, "name": "mud flow", "colour": "#eb6834"}],
            "grid": {"origin": [500000.0, 4140010.0],
                     "pixel_crs": [0.05, 0.05], "pixel_m": [0.05, 0.05],
                     "crs": "EPSG:32633"}}
    group_name = "RasterLabel: aragona_blind"
    def active_classes(self): return self.data["classes"]
    def save(self): pass


def marks_of(*readings):
    return {r: {"polygons": {"n": 2, "codes": {1, 2},
                             "frames": {"t001": (2, "2026-10-01T10:00:00",
                                                 "2026-10-01T10:05:00")},
                             "no_frame": 0, "first": None, "last": None,
                             "size_px": 1}} for r in readings}


PLANS = []


def fake_plan(data, package, a, b, rule="closed", points_in=False,
              marks=None, shares=None, frames=None):
    plan = {"A": tuple(a), "B": tuple(b), "kind": "inter",
            "frame_rule": rule, "asked_rule": rule, "points_in": points_in,
            "untiled": False, "notes": [], "refusal": None, "codes": [0, 1, 2],
            "counts": {"closed": 1, "touched": 2}, "delay": {},
            "frames": [], "used": ["t001"],
            "left_out": [{"tile_id": "t002", "reason": "B 81.0 %"}],
            "unfinished": {"A": [], "B": [("t002", 0.81)]}}
    PLANS.append(plan)
    return plan


RUNS = []
g["cmp_marks"] = lambda package, tables=None: marks_of(("ANNA", 1),
                                                       ("BRUNO", 1))
g["cmp_plan"] = fake_plan
g["reading_shares"] = lambda package, tile_ids=None: {}
g["cmp_frames"] = lambda package: []
g["compare_run"] = lambda panel, recipe: RUNS.append(recipe) or None

panel = g["Panel"]()
panel.campaign = Campaign()
panel.annotation = Section()
panel._reading = {"campaign": "blind1", "operator": "ANNA", "pass": 1,
                  "blind": True, "by_operator": True}
panel.update_enabled()
panel.b_measure.menu().aboutToShow.emit()
actions = {a.text(): a for a in panel.b_measure.menu().actions()}
check("Compare two readings is in the Measure menu",
      "Compare two readings…" in actions, list(actions))
check("and can be chosen, with two readings in the campaign",
      "Compare two readings…" in actions
      and actions["Compare two readings…"].isEnabled())
del K.BOXES[:]
del K.ASKED[:]
actions["Compare two readings…"].trigger()
check("ANNA drawing with one operator at a time: no window is shown",
      "CompareSetup" not in K.ASKED, K.ASKED)
said = [t for kind, t in K.BOXES if kind == "warning"]
check("it is refused, and says so", len(said) == 1, K.BOXES)
text = said[0] if said else ""
check("what: ANNA is drawing, BRUNO's pass 1 is hidden from her",
      "ANNA is drawing pass 1" in text and "BRUNO, pass 1" in text, text)
check("why: the agreement map would show it",
      "agreement map would show it" in text, text)
check("and the way out", "Untick" in text and "then compare" in text, text)
check("nothing ran", not RUNS and not PLANS, (RUNS, PLANS))

print()
print("a blind second pass may not compare with the first")
panel._reading = {"campaign": "blind1", "operator": "ANNA", "pass": 2,
                  "blind": True, "by_operator": False}
g["cmp_marks"] = lambda package, tables=None: marks_of(("ANNA", 1),
                                                       ("ANNA", 2))
del K.BOXES[:]
del K.ASKED[:]
g["compare_start"](panel)
check("ANNA in a blind pass 2: refused, no window",
      "CompareSetup" not in K.ASKED
      and any("ANNA, pass 1" in t for _, t in K.BOXES), (K.ASKED, K.BOXES))

print()
print("Annotate closed, the filter off: asked about the unfinished reading")
panel.annotation = None
panel._reading = {"campaign": "blind1", "operator": "ANNA", "pass": 1,
                  "blind": True, "by_operator": False}
g["cmp_marks"] = lambda package, tables=None: marks_of(("ANNA", 1),
                                                       ("BRUNO", 1),
                                                       ("CARLA", 2))
OFFERED = []


def answer_setup(dialog):
    OFFERED.append([dialog.a.itemData(i) for i in range(dialog.a.count())]
                   + [dialog.b.itemData(i) for i in range(dialog.b.count())])
    OFFERED.append(dialog.go.isEnabled())
    return 1


QUESTIONS = []


def answer(click):
    def f(box):
        QUESTIONS.append(box.text())
        for b in box.buttons():
            if b.text().replace("&", "") == click:
                b.click()
        return 0
    return f


del K.BOXES[:]
K.ANSWERS["CompareSetup"] = answer_setup
K.ANSWERS["QMessageBox"] = answer("Cancel")
g["compare_start"](panel)
check("the window is shown", bool(OFFERED), K.UNEXPECTED)
check("A is ANNA, B BRUNO: two operators in one pass",
      OFFERED and OFFERED[0][:2] == [["ANNA", 1], ["BRUNO", 1]]
      or OFFERED and OFFERED[0] == [["ANNA", 1], ["BRUNO", 1], ["BRUNO", 1]],
      OFFERED)
check("and Compare can be pressed", len(OFFERED) > 1 and OFFERED[1])
check("the unfinished reading is asked about", len(QUESTIONS) == 1,
      QUESTIONS)
q = QUESTIONS[0] if QUESTIONS else ""
check("naming it and its frames",
      "BRUNO, pass 1 has 1 frame touched but not closed (t002 81 %)" in q, q)
check("saying they are left out, and who must not see the map",
      "They are left out." in q
      and "Whoever is still reading must not see this map." in q, q)
check("and how many frames would be compared", "Compare the 1 closed "
      "frame?" in q, q)
check("Cancel runs nothing", not RUNS, RUNS)
K.ANSWERS["CompareSetup"] = answer_setup
K.ANSWERS["QMessageBox"] = answer("Compare")
g["compare_start"](panel)
check("Compare runs it, on the plan asked for",
      len(RUNS) == 1 and RUNS[0]["plan"]["A"] == ("ANNA", 1)
      and RUNS[0]["plan"]["B"] == ("BRUNO", 1), RUNS)

print()
print("the readings a reader may not see are not offered")
panel._reading = {"campaign": "blind1", "operator": "ANNA", "pass": 2,
                  "blind": True, "by_operator": False}
g["cmp_marks"] = lambda package, tables=None: marks_of(
    ("ANNA", 1), ("ANNA", 2), ("BRUNO", 2))
del OFFERED[:]
K.ANSWERS["CompareSetup"] = answer_setup
K.ANSWERS["QMessageBox"] = answer("Cancel")
g["compare_start"](panel)
offered = [tuple(r) for r in (OFFERED[0] if OFFERED else [])]
check("ANNA in a blind pass 2 is offered pass 2 only, never pass 1",
      offered and ("ANNA", 1) not in offered
      and set(offered) <= {("ANNA", 2), ("BRUNO", 2)}, offered)
K.ANSWERS.pop("CompareSetup", None)
K.ANSWERS.pop("QMessageBox", None)

print()
print("the maps of a report are veiled for a reader who may not see them")


class Group(object):
    def __init__(self, name=""):
        self.name, self.groups, self.layers = name, {}, []
    def findGroup(self, name): return self.groups.get(name)
    def addGroup(self, name):
        self.groups[name] = Group(name)
        return self.groups[name]
    def addLayer(self, layer):
        self.layers.append(layer.id())
        K.TREE[layer.id()] = True
        return K.Node(layer.id())


TOP = {}
K.Node.itemVisibilityChecked = lambda self: K.TREE.get(self.lid, True)
K.Root.findGroup = lambda self, name: TOP.get(name)
K.Root.insertGroup = lambda self, i, name: TOP.setdefault(name, Group(name))


class MapLayer(K.Layer):
    count = [0]

    def __init__(self, source, name, provider=None):
        MapLayer.count[0] += 1
        super().__init__(source, name, lid="map%d" % MapLayer.count[0])
    def loadNamedStyle(self, path): return ("", True)
    def saveNamedStyle(self, path): return ("", True)


g["QgsRasterLayer"] = MapLayer
g["QgsVectorLayer"] = MapLayer
g["compare_vector_styles"] = lambda gpkg: {}
g["compare_style_layer"] = lambda layer, part: None
result = {"folder": os.path.join(Campaign.folder, "reports", "agreement",
                                 "ANNA_p1_vs_BRUNO_p1_x"),
          "files": {"disagreement": "a_disagreement.tif",
                    "pairs": "a_pairs.tif", "vectors": "a.gpkg"},
          "plan": {"A": ("ANNA", 1), "B": ("BRUNO", 1)},
          "label": "ANNA_p1_vs_BRUNO_p1"}
panel._reading = {"campaign": "blind1", "operator": "ANNA", "pass": 1,
                  "blind": True, "by_operator": False}
loaded = g["compare_layers"](panel, panel.campaign, result, True)
check("four maps are loaded: two rasters, the polygons and the frames",
      len(loaded) == 4, loaded)
check("each marked as an agreement report showing ANNA and BRUNO",
      all(l.customProperty("rasterlabel/report") == "agreement"
          and l.customProperty("rasterlabel/readings") == "ANNA,1;BRUNO,1"
          for l in loaded), [l._props for l in loaded])
group = TOP[Campaign.group_name].findGroup("agreement ANNA p1 vs BRUNO p1")
check("in a group of their own under the campaign's",
      group is not None and len(group.layers) == 4)
check("the disagreement map and the polygons on, the pairs and the frames "
      "off", [K.TREE[l.id()] for l in loaded] == [True, False, True, False],
      [K.TREE[l.id()] for l in loaded])
panel._reading = {"campaign": "blind1", "operator": "BRUNO", "pass": 1,
                  "blind": True, "by_operator": True}
n = panel.veil_reports()
check("BRUNO drawing one operator at a time: every one is switched off",
      n == 4 and not any(K.TREE[l.id()] for l in loaded),
      (n, [K.TREE[l.id()] for l in loaded]))
check("and none is taken out of the project",
      all(l.id() in K.LOADED for l in loaded))

sys.exit(K.finish())
