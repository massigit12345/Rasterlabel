"""Passes are a list for each operator, and blind shows only the pass in hand.

What the author saw in a campaign of two operators:

  blind        pass 1 then pass 2 of one operator hid pass 1 (good), but going
               back to pass 1 showed pass 2 on top of it, which is no more
               blind than the other way round. With blind on the reader sees
               the pass being drawn and no other, earlier or later; with it
               off, every pass. Compare, the card and the report layers follow
               the same rule (campaign.hidden_from).
  list         "pass" was a free spin box: adding an operator while it stood
               on 2 left the new operator in pass 2. Now a campaign starts
               with one operator in pass 1, the box offers the passes the
               operator has (the manifest's, and those the tables already
               hold, so an old campaign keeps its own), the + next to it adds
               the next one, and an operator who is added starts at pass 1.
  open         the tables of a campaign just opened were drawn by the legend
               alone, every reading at once, until Annotate was pressed. The
               panel puts the filter of the reading it holds on them.
  boxes        Objects obeys the same three rules.

The real panel and the real modules are built, from the shipped file, on the
fakes of harness2, with tables of their own whose filters are run here through
sqlite as the renderer would run them.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_boxes_by_reading as boxes_suite  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = boxes_suite.SRC

# the fakes of the boxes suite: geometry, tables, a panel; its own cases follow
# the marker and are not run here
PRELUDE = boxes_suite.TRIAL[:boxes_suite.TRIAL.index(
    'print("SECTION BRUNO, pass 2, blind, set in Annotate')]

TRIAL = PRELUDE + r'''
import json

TABLE = ["class_name", "class_code", "tile_id", "pass_no", "operator",
         "created"]
saved = []


def tables_for(cid):
    polygons = Table(TABLE)
    boxes = Table(NAMES)
    LAYERS[(cid, "polygons")] = polygons
    LAYERS[(cid, "boxes")] = boxes
    return polygons, boxes


def seen(table):
    """The rows the renderer's filter lets through, run through sqlite."""
    exprs = table.expressions()
    if not exprs:
        return None
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE b (fid INTEGER, tile_id TEXT, pass_no INT, "
               "operator TEXT)")
    db.executemany("INSERT INTO b VALUES (?,?,?,?)", [
        (fid, f.values.get("tile_id"), f.values.get("pass_no"),
         f.values.get("operator")) for fid, f in table.rows.items()])
    try:
        return {r[0] for r in db.execute("SELECT fid FROM b WHERE " + exprs[0])}
    except sqlite3.Error as err:
        return "broken: %s" % err


def panel_of(data):
    c = campaign_of(data)
    c.save = lambda: saved.append(json.dumps(c.data))
    p = g["Panel"]()
    p.campaign = c
    # asked who is drawing, the answer is the reading already in hand
    p.ask_reading = lambda why, *a, **k: {
        "operator": p.reading()["operator"], "pass_no": p.reading()["pass"],
        "blind": p.reading()["blind"]}
    p.describe_campaign()
    p.update_enabled()
    return p


def fill(polygons, boxes):
    """ANNA reads in passes 1 and 2, BRUNO in pass 1; one old mark has no
    pass written at all, which is pass 1."""
    ids = {}
    ids["a1"] = polygons.add(Rect(0, 0, 10, 10), class_name="crust",
                             class_code=1, operator="ANNA", pass_no=1,
                             tile_id="")
    ids["a2"] = polygons.add(Rect(0, 0, 10, 10), class_name="crust",
                             class_code=1, operator="ANNA", pass_no=2,
                             tile_id="")
    ids["b1"] = polygons.add(Rect(0, 0, 10, 10), class_name="crust",
                             class_code=1, operator="BRUNO", pass_no=1,
                             tile_id="")
    ids["a0"] = polygons.add(Rect(0, 0, 10, 10), class_name="crust",
                             class_code=1, operator="anna", pass_no=None,
                             tile_id="")
    ids["xa1"] = boxes.add(Rect(0, 0, 5, 5), class_name="crust", class_code=1,
                           operator="ANNA", pass_no=1, tile_id="")
    ids["xa2"] = boxes.add(Rect(0, 0, 5, 5), class_name="crust", class_code=1,
                           operator="ANNA", pass_no=2, tile_id="")
    ids["xb1"] = boxes.add(Rect(0, 0, 5, 5), class_name="crust", class_code=1,
                           operator="BRUNO", pass_no=1, tile_id="")
    return ids


def duo(cid, passes=None):
    data = {"id": cid, "name": "duo", "with_tiles": True,
            "operator": "Anna", "operators": ["ANNA", "BRUNO"],
            "classes": CLASSES, "corrections": [], "cutouts": [],
            "grid": dict(Campaign.data["grid"])}
    if passes:
        data["passes"] = passes
    return data


def hold(panel, who, pass_no, blind=True, by_operator=True):
    panel.hold_reading(who, pass_no, blind, by_operator)


print("SECTION blind: only the pass in hand, whichever it is")
SESSION["operator"] = None
data = duo("pass0001", {"ANNA": [1, 2]})
polygons, boxes = tables_for(data["id"])
ids = fill(polygons, boxes)
panel = panel_of(data)
panel.toggle_module(0)
a = panel.section
check("Annotate opens", a is not None, said)
check("the tick says what it does",
      a.blind.text() == "blind: show only this pass", a.blind.text())
check("and no longer talks of earlier passes",
      "earlier passes" not in a.blind.text() + a.blind.toolTip(),
      a.blind.toolTip())
check("ANNA, pass 1, blind on", (a.operator_name(), a.pass_no.value(),
                                  a.blind.isChecked()) == ("ANNA", 1, True))
a.apply_filter()
check("pass 1 shows pass 1 and not pass 2 (and the mark with no pass is 1)",
      seen(polygons) == {ids["a1"], ids["a0"]}, seen(polygons))
check("the boxes too", seen(boxes) == {ids["xa1"]}, seen(boxes))
check("the strip names the pass that is hidden",
      "Pass 2 is hidden and stays untouched" in a.blind_note.text(),
      a.blind_note.text())
a.pass_no.setValue(2)
check("pass 2 shows pass 2 and not pass 1",
      seen(polygons) == {ids["a2"]}, seen(polygons))
check("the boxes too, in pass 2", seen(boxes) == {ids["xa2"]}, seen(boxes))
a.pass_no.setValue(1)
check("and going back to pass 1 hides pass 2 again",
      seen(polygons) == {ids["a1"], ids["a0"]}, seen(polygons))
a.blind.setChecked(False)
check("blind off: every pass of ANNA, none of BRUNO's",
      seen(polygons) == {ids["a1"], ids["a2"], ids["a0"]}, seen(polygons))
check("blind off: both boxes", seen(boxes) == {ids["xa1"], ids["xa2"]},
      seen(boxes))
check("blind off: no amber strip about passes",
      "DRAWING BLIND" not in a.blind_note.text(), a.blind_note.text())
a.blind.setChecked(True)

print("SECTION blind: Compare and the report layers follow the same rule")
hidden = g["hidden_from"]
check("pass 1 does not see pass 2", hidden(("ANNA", 1), ("ANNA", 2), True,
                                           True))
check("pass 2 does not see pass 1", hidden(("ANNA", 2), ("ANNA", 1), True,
                                           True))
check("its own pass is in sight", not hidden(("ANNA", 1), ("ANNA", 1), True,
                                             True))
check("blind off hides no pass", not hidden(("ANNA", 1), ("ANNA", 2), False,
                                            False))
check("a reader of one operator at a time still sees only theirs",
      hidden(("ANNA", 1), ("BRUNO", 1), True, False))
hold(panel, "ANNA", 1, True, False)
refusal = panel.blind_gate([("ANNA", 1), ("ANNA", 2)])
check("Compare pass 1 with pass 2 is refused to the reader of pass 1",
      refusal is not None and "pass 1" in refusal and "blind" in refusal,
      refusal)
hold(panel, "ANNA", 2, True, False)
check("and to the reader of pass 2",
      panel.blind_gate([("ANNA", 1), ("ANNA", 2)]) is not None)
hold(panel, "ANNA", 1, False, False)
check("blind off: both may be compared",
      panel.blind_gate([("ANNA", 1), ("ANNA", 2)]) is None)
hold(panel, "ANNA", 1, True, False)
check("the reports that show pass 2 are veiled for the reader of pass 1",
      g["hidden_from"](("ANNA", 1), ("ANNA", 2), False, True))
panel.toggle_module(0)

print("SECTION list: the box offers the passes the operator has")
SESSION["operator"] = None
data = duo("pass0002", {"ANNA": [1, 2]})
polygons, boxes = tables_for(data["id"])
ids = fill(polygons, boxes)
polygons.add(Rect(0, 0, 1, 1), class_name="crust", class_code=1,
             operator="BRUNO", pass_no=4, tile_id="")
panel = panel_of(data)
panel.toggle_module(0)
a = panel.section
check("ANNA has passes 1 and 2 and nothing else", a.pass_no.values() == [1, 2],
      a.pass_no.values())
a.operator.setCurrentText("BRUNO")
a.operator_changed()
check("BRUNO has pass 1 and the pass 4 his tables already hold",
      a.pass_no.values() == [1, 4], a.pass_no.values())
check("and stands on pass 1", a.pass_no.value() == 1, a.pass_no.value())
a.pass_no.setValue(4)
a.operator.setCurrentText("ANNA")
a.operator_changed()
check("back to ANNA, who has no pass 4, the box stands on pass 1",
      a.pass_no.value() == 1 and a.pass_no.values() == [1, 2],
      (a.pass_no.value(), a.pass_no.values()))
check("the panel holds that", panel.which_pass() == 1, panel.which_pass())

print("SECTION list: the + adds the next pass for this operator")
saved[:] = []
a.add_pass()
check("ANNA is in pass 3", a.pass_no.value() == 3, a.pass_no.value())
check("the box now offers 1, 2 and 3", a.pass_no.values() == [1, 2, 3],
      a.pass_no.values())
check("written into the manifest",
      data.get("passes", {}).get("ANNA") == [1, 2, 3], data.get("passes"))
check("and saved", len(saved) == 1, saved)
check("the panel holds the new pass", panel.which_pass() == 3,
      panel.which_pass())
check("BRUNO's passes are not touched",
      "BRUNO" not in (data.get("passes") or {}) or
      data["passes"]["BRUNO"] == [1], data.get("passes"))
check("blind is on in the new pass: pass 3 alone",
      a.blind.isChecked() and seen(polygons) == set(), seen(polygons))

print("SECTION list: an operator who is added starts at pass 1")
g["QInputDialog"].getText = staticmethod(lambda *a, **k: ("dario", True))
a.add_operator()
check("DARIO is drawing", a.operator_name() == "DARIO", a.operator_name())
check("in pass 1, not in pass 3", a.pass_no.value() == 1, a.pass_no.value())
check("with one pass to offer", a.pass_no.values() == [1], a.pass_no.values())
check("the panel holds pass 1 for DARIO", (panel.who_is_drawing(),
                                           panel.which_pass())
      == ("DARIO", 1), (panel.who_is_drawing(), panel.which_pass()))
a.add_pass()
a.operator.setCurrentText("ANNA")
a.operator_changed()
check("ANNA still has her three", a.pass_no.values() == [1, 2, 3],
      a.pass_no.values())
panel.toggle_module(0)

print("SECTION list: a campaign that starts has one operator in pass 1")
SESSION["operator"] = None
fresh = {"id": "pass0003", "name": "solo", "with_tiles": True,
         "operator": "carla", "classes": CLASSES, "corrections": [],
         "cutouts": [], "grid": dict(Campaign.data["grid"])}
tables_for(fresh["id"])
panel = panel_of(fresh)
panel.toggle_module(0)
a = panel.section
check("CARLA, with pass 1 only", (a.operator_name(), a.pass_no.values())
      == ("CARLA", [1]), (a.operator_name(), a.pass_no.values()))
check("an old manifest, with no list, is read as it was",
      "passes" not in fresh)
panel.toggle_module(0)

print("SECTION list: the window that asks who is drawing")
panel = panel_of(duo("pass0004", {"ANNA": [1, 2]}))
tables_for("pass0004")
d = g["WhoIsDrawing"](None, "why", ["ANNA", "BRUNO"],
                      {"operator": "ANNA", "pass": 2, "blind": True},
                      panel.passes_for)
check("it offers ANNA's passes and stands on hers",
      (d.pass_no.values(), d.pass_no.value()) == ([1, 2], 2),
      (d.pass_no.values(), d.pass_no.value()))
check("its tick says the same as Annotate's",
      d.blind.text() == "blind: show only this pass", d.blind.text())
d.operator.setCurrentText("BRUNO")
check("BRUNO is offered pass 1 alone", (d.pass_no.values(), d.pass_no.value())
      == ([1], 1), (d.pass_no.values(), d.pass_no.value()))
d.add_pass()
check("the + of the window makes his pass 2",
      (d.pass_no.values(), d.chosen()["pass_no"]) == ([1, 2], 2),
      (d.pass_no.values(), d.chosen()))
panel.register_pass("BRUNO", 2)
check("and the panel writes it down", panel.campaign.data["passes"]["BRUNO"]
      == [1, 2], panel.campaign.data.get("passes"))
check("an old campaign's passes show with no list at all",
      panel.passes_for("BRUNO") == [1, 2])

print("SECTION open: the tables are filtered before Annotate is pressed")
SESSION["operator"] = None
data = duo("pass0005", {"ANNA": [1, 2]})
polygons, boxes = tables_for(data["id"])
ids = fill(polygons, boxes)
panel = panel_of(data)
hold(panel, "ANNA", 2, True, True)
check("nothing is filtered yet", seen(polygons) is None, seen(polygons))
panel.filter_for_reading()
check("the polygons show ANNA's pass 2 and nothing else",
      seen(polygons) == {ids["a2"]}, seen(polygons))
check("the boxes too", seen(boxes) == {ids["xa2"]}, seen(boxes))
before = list(polygons.expressions()), list(boxes.expressions())
panel.toggle_module(0)
after = list(polygons.expressions()), list(boxes.expressions())
check("Annotate then writes the very same filters", before == after,
      (before, after))
panel.toggle_module(0)
hold(panel, "BRUNO", 1, True, True)
panel.filter_for_reading()
check("a campaign opened as BRUNO, pass 1 shows BRUNO's pass 1",
      seen(polygons) == {ids["b1"]}, seen(polygons))
check("load_layers filters the tables by the reading in hand",
      "filter_for_reading" in repr(g["Panel"].load_layers.__code__.co_names))

print("SECTION boxes: Objects follows the same rules")
SESSION["operator"] = None
data = duo("pass0006", {"ANNA": [1, 2]})
polygons, boxes = tables_for(data["id"])
ids = fill(polygons, boxes)
panel = panel_of(data)
hold(panel, "ANNA", 1, True, True)
panel.toggle_module(2)
o = panel.section
check("Objects opens", o is not None and panel.open_index == 2, said)
check("pass 1 blind: only ANNA's pass 1 box", seen(boxes) == {ids["xa1"]},
      seen(boxes))
check("ANNA's pass 2 box is not hers to touch now",
      o.box_at(Pt(2, 2)) is not None and o.is_hidden(boxes.rows[ids["xa2"]]),
      o.is_hidden(boxes.rows[ids["xa2"]]))
hold(panel, "ANNA", 2, True, True)
o.apply_filter()
check("pass 2 blind: only the pass 2 box", seen(boxes) == {ids["xa2"]},
      seen(boxes))
check("the line under the tally says only this pass is shown",
      "only the boxes of this pass" in o.reading_label.text(),
      o.reading_label.text())
hold(panel, "ANNA", 2, False, True)
o.apply_filter()
check("blind off: both of ANNA's boxes", seen(boxes) == {ids["xa1"],
                                                         ids["xa2"]},
      seen(boxes))
panel.toggle_module(2)

print("SECTION close: the map is drawn again once the layers are gone")
calls = []


class Canvas(object):
    def refreshAllLayers(self): calls.append("refreshAllLayers")
    def refresh(self): calls.append("refresh")


class Eye(object):
    def mapCanvas(self): return Canvas()
    def messageBar(self): return Bar()
    def __getattr__(self, n): return lambda *a, **k: None


g["iface"] = Eye()
g["refresh_canvas"]()
check("refreshAllLayers is asked", calls == ["refreshAllLayers"], calls)
code = g["drop_layers"].__code__.co_names
check("and dropping the layers asks for it", "refresh_canvas" in code, code)

print("VERDICT %d" % len(fails))
'''


def main():
    trial = os.path.join(HERE, "_passes_by_operator.py")
    with open(trial, "w", encoding="utf-8") as f:
        f.write(TRIAL)
    with open(os.path.join(HERE, "harness2.py"), encoding="utf-8") as f:
        code = f.read()
    code = code.replace('panel.grab().save(out)',
                        'exec(open(r"%s", encoding="utf-8").read())' % trial)
    run = os.path.join(HERE, "_run_passes_by_operator.py")
    with open(run, "w", encoding="utf-8") as f:
        f.write(code)
    out = subprocess.run([sys.executable, run, "460", "none"],
                         capture_output=True, cwd=HERE,
                         env=dict(os.environ, RL_SRC=SRC, PYTHONUTF8="1",
                                  PYTHONIOENCODING="utf-8"),
                         encoding="utf-8", errors="replace")
    text = out.stdout + out.stderr
    for line in text.splitlines():
        if line.startswith("SECTION"):
            print()
            print(line[8:])
        elif line.startswith("CHECK"):
            print("  " + line[6:])
    verdict = [l for l in text.splitlines() if l.startswith("VERDICT")]
    if not verdict:
        print(text[-2500:])
        print("the trial did not reach the end")
        return 1
    how_many = int(verdict[0].split()[1])
    print()
    print("all pass" if not how_many else "FAILED: %d" % how_many)
    return 1 if how_many else 0


if __name__ == "__main__":
    sys.exit(main())
