"""rasterlabel.measure

The Measure menu, and the places where the measuring modules plug into the
rest of the program.

Every measure is written down here by name, never imported: the module that
does the work is looked up when the menu opens, and an entry whose function
is not there is simply not shown. So the menu holds what this build can do
and nothing else, and a module left out of a build costs nothing. The
same goes for the hooks: Correct and Annotate call them through this module
and do nothing when none is there.

The registries:

- CAMPAIGN_MEASURES and CORRECTION_MEASURES, the entries of the two Measure
  menus, in their order: (key, label, module, start, enabled). start(panel)
  runs the measure; enabled(panel) answers (True, "") or (False, why), and
  why is the tooltip of the grey entry. None is a separator, shown only
  between entries that are there.
- FRAME_LISTENERS: fn(section, kind, tile_id, before_bbox, after_bbox,
  feature), called by Annotate after a frame was placed, moved, deleted or
  imported, and only once the change is committed. kind is one of new,
  move, delete and import.
- CORRECT_HOOKS: classes, built once per Correct with the section. Every
  method is optional: stroke(section, ctx) -> state, undo(section, state),
  flush(section), closing(section), files(section) -> [paths] and
  tally_lines(section) -> [str].
- DOCTOR_CAMPAIGN and DOCTOR_CORRECTION: fn(owner) -> [findings], added to
  what Check says.
- CORRECTION_TOOLTIP_LINES: fn(book) -> a line or "", added to the tooltip of
  the correction's line in the panel.

A name stands for a function of the module named beside it. In place of a
name, a function itself may be given, which is how the suites register one.
"""
import importlib

from qgis.PyQt.QtWidgets import QMenu

from .errors import log, shielded
from .campaign import hidden_from, operator_word, pass_number, reading_label

# The words of the two menus. "agreement" is said only of people against
# people; the model is measured against the corrected map.
CAMPAIGN_MEASURES = [
    ("compare", "Compare two readings…", "ui_compare", "compare_start",
     "compare_enabled"),
    ("time", "Time…", "ui_time", "time_start", "time_enabled"),
    None,
    ("card", "Dataset card…", "ui_card", "card_start_campaign",
     "card_enabled_campaign"),
]
CORRECTION_MEASURES = [
    ("model_vs_corrected", "Model vs corrected…", "ui_mvc", "mvc_start",
     "mvc_enabled"),
    ("uncertainty", "Uncertainty report…", "ui_uncertainty",
     "unc_report_start", "unc_report_enabled"),
    ("time", "Time…", "ui_time", "time_start_correction",
     "time_enabled_correction"),
    None,
    ("card", "Dataset card…", "ui_card", "card_start_correction",
     "card_enabled_correction"),
]
FRAME_LISTENERS = [
    ("journal", "journal_frame_event"),
    ("design", "design_frame_event"),
]
CORRECT_HOOKS = [
    ("model_vs_corrected", "ReviewedHook"),
    ("ui_uncertainty", "UncertaintyHook"),
    ("journal", "CorrectJournalHook"),
]
DOCTOR_CAMPAIGN = [
    ("ui_compare", "compare_findings"),
    ("journal", "journal_findings"),
    ("design", "design_findings"),
    ("doctor", "reports_findings"),
]
DOCTOR_CORRECTION = [
    ("model_vs_corrected", "reviewed_findings"),
    ("uncertainty", "unc_findings"),
    ("journal", "journal_findings_correction"),
    ("doctor", "reports_findings"),
]
CORRECTION_TOOLTIP_LINES = [
    ("uncertainty", "unc_tooltip_line"),
]

# What the menu holds while no measure is in this build. One grey entry, the
# way QGIS shows a menu with nothing in it, rather than a key that opens
# nothing.
MEASURE_NOTHING_YET = "Nothing to measure yet"
# Said at most once per name per session: a module that cannot be imported
# is a fault worth one line, not one line at every opening of a menu.
_MEASURE_SAID = set()


def measure_resolve(module, name):
    """The function or class a registry names, or None when this build has
    none by that name. Never raises.

    In the package it is an attribute of the module named; in the single
    file every module shares one namespace, and it is a name in it."""
    if callable(name):
        return name
    if not isinstance(name, str) or not name:
        return None
    package = globals().get("__package__") or ""
    if not package:
        found = globals().get(name)
        return found if callable(found) else None
    try:
        mod = importlib.import_module("." + module, package)
    except Exception as err:
        if (module, name) not in _MEASURE_SAID:
            _MEASURE_SAID.add((module, name))
            log("the measure %s is not there: %s cannot be imported (%s)"
                % (name, module, err))
        return None
    found = getattr(mod, name, None)
    return found if callable(found) else None


def measure_all(registry):
    """What a registry of (module, name) pairs resolves to, in its order,
    with the names this build lacks left out."""
    out = []
    for module, name in registry:
        found = measure_resolve(module, name)
        if found is not None:
            out.append(found)
    return out


def measure_entries(registry):
    """The entries of a menu registry this build has: (key, label, start,
    enabled), with None where a separator stands between two of them. An
    entry is there when its start function is; one without an enabled
    function is always on."""
    out = []
    for entry in registry:
        if entry is None:
            if out and out[-1] is not None:
                out.append(None)
            continue
        key, label, module, start, enabled = entry
        run = measure_resolve(module, start)
        if run is None:
            continue
        out.append((key, label, run, measure_resolve(module, enabled)))
    while out and out[-1] is None:
        out.pop()
    return out


def measure_registry(owner):
    return CAMPAIGN_MEASURES if owner == "campaign" else CORRECTION_MEASURES


def measure_state(enabled, panel):
    """(on, why) from an entry's enabled function, which may be missing, may
    answer a bare bool, and may raise: a measure that cannot say whether it
    can run is grey and says why, it does not take the menu down."""
    if enabled is None:
        return True, ""
    try:
        said = enabled(panel)
    except Exception as err:
        log("cannot tell whether a measure can run: %s" % err)
        return False, "Cannot tell whether this can run: %s" % err
    if isinstance(said, tuple):
        on = bool(said[0]) if said else False
        why = str(said[1]) if len(said) > 1 and said[1] else ""
        return on, why
    return bool(said), ""


def measure_tooltip(owner):
    """The tooltip of the Measure key while it can be pressed: what it is
    for, and the measures this build has."""
    labels = [e[1].rstrip("…").rstrip(".") for e in
              measure_entries(measure_registry(owner)) if e is not None]
    what = "campaign" if owner == "campaign" else "correction"
    if not labels:
        return ("Numbers for a paper, from what is in this %s.\n"
                "Nothing can be measured yet." % what)
    return ("Numbers for a paper, from what is in this %s: %s.\n"
            "Each writes a folder under reports/ and changes nothing in the "
            "%s." % (what, ", ".join(l[0].lower() + l[1:] for l in labels),
                     what))


def measure_fill(menu, owner, panel):
    """The entries of a Measure menu, filled again each time it opens so
    that a grey entry says why as things are now."""
    menu.clear()
    entries = measure_entries(measure_registry(owner))
    if not entries:
        act = menu.addAction(MEASURE_NOTHING_YET)
        act.setEnabled(False)
        act.setToolTip("No measure is part of this build.")
        return []
    actions = []
    for entry in entries:
        if entry is None:
            menu.addSeparator()
            continue
        key, label, run, enabled = entry
        on, why = measure_state(enabled, panel)
        act = menu.addAction(label)
        act.setObjectName("measure_" + key)
        act.setEnabled(on)
        act.setToolTip(why if not on else "")
        act.triggered.connect(shielded(
            lambda _=False, f=run: f(panel), label.rstrip("…")))
        actions.append(act)
    return actions


def measure_menu(button, owner, panel):
    """The menu behind a Measure key. It opens on the press, the way QGIS's
    own buttons with a menu do, and a grey entry shows its reason when the
    pointer rests on it."""
    menu = QMenu(button)
    menu.setToolTipsVisible(True)
    menu.aboutToShow.connect(shielded(
        lambda: measure_fill(menu, owner, panel), "Measure"))
    button.setMenu(menu)
    # filled once now as well, so the menu has its size before it is opened
    measure_fill(menu, owner, panel)
    return menu


#  Blind readers
# =====================================================================
def measure_hidden(panel, readings):
    """The readings, out of these, that the reading the panel holds may not
    see: the same rule as the filter of Annotate and Objects, from the same
    state (who is drawing, the pass, one operator at a time, blind)."""
    held = panel.reading() if callable(getattr(panel, "reading", None)) \
        else None
    if not held:
        return []
    reader = (held.get("operator"), held.get("pass") or 1)
    one = bool(held.get("by_operator", True))
    blind = bool(held.get("blind", True))
    out = []
    for r in readings or []:
        r = (operator_word(r[0]), pass_number(r[1]))
        if hidden_from(reader, r, one, blind) and r not in out:
            out.append(r)
    return out


def measure_blind_gate(panel, readings, what="agreement map",
                       verb="compare"):
    """None when the reading in hand may see every one of these readings;
    otherwise the refusal, which says what happened, why and the way out.
    Compare and a campaign's card ask it before they read anything."""
    hidden = measure_hidden(panel, readings)
    if not hidden:
        return None
    held = panel.reading() or {}
    who = operator_word(held.get("operator"))
    p = pass_number(held.get("pass"))
    switches = []
    if held.get("by_operator", True):
        switches.append("one operator at a time")
    if held.get("blind", True):
        switches.append("blind")
    names = [reading_label(r) for r in hidden]
    words = names[0] if len(names) == 1 else \
        ", ".join(names[:-1]) + " and " + names[-1]
    return ("%s is drawing pass %d with %s on, so %s %s hidden from %s. The "
            "%s would show it. Untick %s under Annotate's Settings, or change "
            "who is drawing to the reading whose work this is, then %s."
            % (who, p, " and ".join(switches) or "the filter", words,
               "is" if len(names) == 1 else "are", who, what,
               " and ".join("'%s'" % s for s in switches) or "the filter",
               verb))
