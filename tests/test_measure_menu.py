"""Measure: one key in each block, a menu behind it, grey until there is
something to measure.

What is checked, on the real panel with QGIS faked (correctkit):

- ANNOTATION CAMPAIGN and CORRECTION each have a Measure key, a push button
  with a menu that opens on the press, reached by Tab like the keys beside
  it, standing just before Check;
- it is grey while its block holds nothing, and its tooltip then says why
  in the words the other grey keys use; with a campaign or a correction
  open it can be pressed, and its tooltip says what it is for;
- the menu shows only the measures this build has, Compare two readings
  first among them: an entry whose function is not there is not shown at
  all, and a separator is shown only between two entries that are; with
  none, the menu holds one grey entry saying there is nothing to measure
  yet;
- an entry that cannot run is grey and its tooltip says why, one whose
  enabled function fails is grey and says so, and one that can run calls
  its start function with the panel;
- the blind gate refuses a reading the reader may not see, by the same rule
  as the Annotate filter, from the reading the panel holds, and says what
  happened, why and the way out.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correctkit as K                                             # noqa: E402

g, check = K.g, K.check
QtWidgets, QtCore = K.QtWidgets, K.QtCore


class Campaign:
    """An annotation campaign as far as the panel's line and keys go."""
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "aragona_2025")
    data = {"id": "abc123", "name": "aragona_2025", "with_tiles": True,
            "operator": "ANNA", "operators": ["ANNA", "BRUNO"],
            "classes": [{"name": "crust", "code": 1, "colour": "#b0651f"}],
            "grid": {"pixel_m": [0.05, 0.05], "crs": "EPSG:32633"}}
    group_name = "RasterLabel aragona_2025"
    def active_classes(self): return self.data["classes"]


class Book:
    folder = os.path.dirname(os.path.abspath(__file__))
    manifest_path = os.path.join(folder, "correction.json")
    working_path = os.path.join(folder, "m_corrected.tif")
    data = {"id": "c0ffee", "name": "landcover_fix", "operator": "ANN",
            "source": "/data/mask.tif", "classes": [
                {"name": "crops", "code": 3, "colour": "#e6c229"}]}


def entries(menu):
    """(text, enabled, tooltip) of a menu, separators as None."""
    out = []
    for act in menu.actions():
        out.append(None if act.isSeparator()
                   else (act.text(), act.isEnabled(), act.toolTip()))
    return out


def open_menu(button):
    """What the menu holds as it is opened."""
    menu = button.menu()
    menu.aboutToShow.emit()
    return entries(menu)


panel = g["Panel"]()
panel.update_enabled()

print("one Measure key in each block")
for name, key, check_key in (("ANNOTATION CAMPAIGN", panel.b_measure,
                              panel.b_check),
                             ("CORRECTION", panel.c_measure, panel.c_check)):
    check("%s has a Measure key" % name,
          isinstance(key, QtWidgets.QPushButton) and key.text() == "Measure",
          type(key).__name__)
    check("with a menu behind it", key.menu() is not None)
    check("and its grey entries say why",
          key.menu() is not None and key.menu().toolTipsVisible())
    check("reached by Tab, never taken by a click",
          key.focusPolicy() == QtCore.Qt.FocusPolicy.TabFocus)
    check("as tall as the keys beside it", key.height() == check_key.height(),
          (key.height(), check_key.height()))
    need = (g["text_width"](key.fontMetrics(), "Measure")
            + g["menu_room"](key))
    check("wide enough for its word and the arrow of its menu",
          key.minimumWidth() == 0 or key.width() >= need,
          (key.width(), need))

print()
print("grey while there is nothing to measure, saying why")
check("the campaign's Measure is grey with no campaign open",
      not panel.b_measure.isEnabled())
check("and says what the other keys of the block say",
      panel.b_measure.toolTip().startswith(
          "No annotation campaign is open: press New or Open in"),
      panel.b_measure.toolTip())
check("the correction's Measure is grey with no correction open",
      not panel.c_measure.isEnabled())
check("and says so as Close and Classes do",
      panel.c_measure.toolTip().split("\n\n")[0]
      == panel.c_classes.toolTip().split("\n\n")[0],
      (panel.c_measure.toolTip(), panel.c_classes.toolTip()))

panel.campaign = Campaign()
panel.update_enabled()
check("with a campaign open it can be pressed", panel.b_measure.isEnabled())
check("and its tooltip says what it is for",
      panel.b_measure.toolTip().startswith("Numbers for a paper"),
      panel.b_measure.toolTip())
check("the correction's stays grey", not panel.c_measure.isEnabled())
panel.correction = Book()
panel.update_enabled()
check("with a correction open the correction's can be pressed too",
      panel.c_measure.isEnabled())
check("and names its own block",
      "this correction" in panel.c_measure.toolTip(),
      panel.c_measure.toolTip())

print()
print("the menu holds what this build has, and nothing else")
for name, registry in (("campaign", g["CAMPAIGN_MEASURES"]),
                       ("correction", g["CORRECTION_MEASURES"])):
    named = [e for e in registry if e is not None]
    check("the %s registry names its measures" % name, len(named) >= 3,
          named)
    found = [e[0] for e in named if g["measure_resolve"](e[2], e[3])]
    check("and Time is in the %s registry" % name, "time" in found, found)
found = [e[0] for e in g["CAMPAIGN_MEASURES"]
         if e is not None and g["measure_resolve"](e[2], e[3])]
check("Compare two readings is in this build", "compare" in found, found)
said = open_menu(panel.b_measure)
check("and in the campaign's menu, first",
      said and said[0][0] == "Compare two readings…", said)
check("grey with one reading in the campaign, saying why",
      said and not said[0][1] and said[0][2].startswith(
          "Compare needs two readings."), said)
by = {s[0]: s for s in said if s}
check("the campaign's menu holds Time too",
      "Time…" in by, said)
check("grey while the campaign has no journal yet, and saying why",
      not by["Time…"][1] and "No journal yet" in by["Time…"][2]
      and "first stroke" in by["Time…"][2], by.get("Time…"))
said = open_menu(panel.c_measure)
by = {s[0]: s for s in said if s}
check("and so does the correction's, grey with no stroke on record",
      "Time…" in by and not by["Time…"][1]
      and "no stroke" in by["Time…"][2], said)
check("the correction's menu holds Uncertainty report…, after Model vs "
      "corrected, grey until the uncertainty is chosen in Correct",
      "Uncertainty report…" in by and not by["Uncertainty report…"][1]
      and [s[0] for s in said if s][:2] == ["Model vs corrected…",
                                           "Uncertainty report…"], said)
check("the tooltip of the key names it",
      "time" in panel.b_measure.toolTip(), panel.b_measure.toolTip())
# With none of its measures there, a menu holds one grey entry. Every
# measure of the registries is taken out for the moment, whichever this
# build has.
kept_c, kept_r = list(g["CAMPAIGN_MEASURES"]), list(g["CORRECTION_MEASURES"])
g["CAMPAIGN_MEASURES"][:] = [("gone", "Gone…", "nowhere", "not_there",
                              None)]
g["CORRECTION_MEASURES"][:] = [None, ("gone", "Gone…", "nowhere",
                                      "not_there", None)]
try:
    said = open_menu(panel.b_measure)
    check("with none of them, the campaign's menu holds one grey entry",
          said == [(g["MEASURE_NOTHING_YET"], False,
                    said[0][2] if said else "")], said)
    check("which says there is nothing to measure yet",
          said and said[0][0] == "Nothing to measure yet", said)
    said = open_menu(panel.c_measure)
    check("and so does the correction's",
          len(said) == 1 and said[0][0] == "Nothing to measure yet"
          and not said[0][1], said)
    panel.update_enabled()
    check("the tooltip of the key says so too",
          "Nothing can be measured yet" in panel.b_measure.toolTip(),
          panel.b_measure.toolTip())
finally:
    g["CAMPAIGN_MEASURES"][:] = kept_c
    g["CORRECTION_MEASURES"][:] = kept_r
    panel.update_enabled()
for registry, wanted in (
        ("FRAME_LISTENERS", {"journal_frame_event"}),
        ("CORRECT_HOOKS", {"CorrectJournalHook"}),
        ("DOCTOR_CAMPAIGN", {"journal_findings", "reports_findings",
                             "compare_findings"}),
        ("DOCTOR_CORRECTION", {"journal_findings_correction",
                               "reports_findings"})):
    found = {f.__name__ for f in g["measure_all"](g[registry])}
    check("%s holds what this build registers" % registry, wanted <= found,
          found)
check("CORRECTION_TOOLTIP_LINES resolves to the line of the uncertainty",
      [f.__name__ for f in g["measure_all"](g["CORRECTION_TOOLTIP_LINES"])]
      == ["unc_tooltip_line"],
      g["measure_all"](g["CORRECTION_TOOLTIP_LINES"]))

print()
print("entries that are there, in their order")
RAN = []


def start_compare(p):
    RAN.append(("compare", p))


def can_compare(p):
    return False, "Compare needs two readings. This campaign holds one."


def start_time(p):
    RAN.append(("time", p))


def start_card(p):
    RAN.append(("card", p))


def broken(p):
    raise RuntimeError("the journal is not readable")


kept = list(g["CAMPAIGN_MEASURES"])
g["CAMPAIGN_MEASURES"][:] = [
    None,
    ("compare", "Compare two readings…", "nowhere", start_compare,
     can_compare),
    ("missing", "Not built…", "nowhere", "no_such_function", None),
    ("time", "Time…", "nowhere", start_time, lambda p: (True, "")),
    None, None,
    ("broken", "Broken…", "nowhere", start_time, broken),
    ("card", "Dataset card…", "nowhere", start_card, lambda p: True),
    None,
    ("gone", "Gone…", "nowhere", "not_there_either", "nor_this"),
]
try:
    said = open_menu(panel.b_measure)
    texts = [s[0] if s else None for s in said]
    check("an entry whose function is not there is not shown",
          "Not built…" not in texts and "Gone…" not in texts, texts)
    check("the others are, in the order of the registry, a separator only "
          "between two that are",
          texts == ["Compare two readings…", "Time…", None, "Broken…",
                    "Dataset card…"], texts)
    by = {s[0]: s for s in said if s}
    check("an entry that cannot run is grey",
          not by["Compare two readings…"][1])
    check("and its tooltip is the reason it gave",
          by["Compare two readings…"][2]
          == "Compare needs two readings. This campaign holds one.",
          by["Compare two readings…"][2])
    # Qt answers an action's own text for a tooltip never set (Qt 6 with
    # the ellipsis taken off), and a menu shows no tooltip that only
    # repeats the entry
    check("one that can run is not grey, and says nothing more",
          by["Time…"][1] and by["Time…"][2] in ("", "Time…", "Time"),
          by["Time…"])
    check("an enabled function that answers a bare True is taken at its "
          "word", by["Dataset card…"][1])
    check("one whose enabled function fails is grey and says so",
          not by["Broken…"][1]
          and "the journal is not readable" in by["Broken…"][2],
          by["Broken…"])
    actions = {a.text(): a for a in panel.b_measure.menu().actions()}
    actions["Time…"].trigger()
    check("choosing an entry runs its start function with the panel",
          RAN == [("time", panel)], RAN)
    panel.update_enabled()
    check("the tooltip of the key names what this build can measure",
          "compare two readings, time, broken, dataset card"
          in panel.b_measure.toolTip(), panel.b_measure.toolTip())
    panel.campaign = None
    panel.update_enabled()
    check("and with the campaign closed the key is grey again",
          not panel.b_measure.isEnabled())
finally:
    g["CAMPAIGN_MEASURES"][:] = kept

print()
print("the blind gate")
panel.campaign = Campaign()
panel._reading = {"campaign": "abc123", "operator": "ANNA", "pass": 1,
                  "blind": True, "by_operator": True}
said = panel.blind_gate([("ANNA", 1), ("BRUNO", 1)])
check("one operator at a time hides BRUNO's work from ANNA: refused",
      said is not None and "BRUNO, pass 1" in said, said)
check("the refusal says what, why and the way out",
      said is not None and "ANNA is drawing pass 1" in said
      and "one operator at a time" in said and "would show it" in said
      and "Settings" in said, said)
check("ANNA's own reading is never hidden from her",
      panel.blind_gate([("ANNA", 1)]) is None)
check("and names are compared as the filter compares them",
      panel.blind_gate([(" anna ", "1")]) is None)
panel._reading.update(by_operator=False)
check("with the filter off nothing is hidden",
      panel.blind_gate([("ANNA", 1), ("BRUNO", 1)]) is None)
panel._reading["pass"] = 2
said = panel.blind_gate([("ANNA", 1), ("ANNA", 2)])
check("a blind second pass may not see the first",
      said is not None and "ANNA, pass 1" in said and "'blind'" in said,
      said)
panel._reading.update(blind=False)
check("and may once blind is off",
      panel.blind_gate([("ANNA", 1), ("ANNA", 2)]) is None)
said = g["measure_blind_gate"](
    panel, [("BRUNO", 1)], "card", "write the card")
check("the card asks the same gate, and the filter off lets it through",
      said is None)
panel._reading.update(by_operator=True)
said = g["measure_blind_gate"](
    panel, [("BRUNO", 1)], "card", "write the card")
check("the card's refusal names the card and its verb",
      said is not None and "The card would show it" in said
      and said.endswith("then write the card."), said)
panel.campaign = None
check("with no campaign open there is no reader, and nothing is refused",
      panel.blind_gate([("BRUNO", 1)]) is None)

sys.exit(K.finish())
