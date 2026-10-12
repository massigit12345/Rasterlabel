"""A blind second reader stays the second reader, module after module.

ANNA made the campaign; BRUNO reads it again, in pass 2, blind. He picked
himself and the pass in Annotate, then looked at Objects, or closed Annotate
and opened it again. Every Annotate was built anew from the campaign's
creator in pass 1, and the blind switch went with it: from then on BRUNO's
strokes were filed as ANNA's first reading and cut its polygons, and nothing
on the screen said so.

The real panel and the real modules are built, from the shipped file, on the
fakes of harness2, and the modules are opened and closed with the panel's own
toggle_module, the way the buttons do it. What has to hold:

  the session   operator, pass and blind switch survive Objects, and Annotate
                closed and opened again, and Objects stamps with them
  the campaign  they are remembered campaign by campaign, so the campaign
                opened again in another session draws as the same reading,
                and that reading is shown and confirmed before the first
                stroke; Cancel opens nothing
  one reader    a campaign with only its creator in pass 1 is never asked
                anything, today or after a restart
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("RL_SRC", _BUILT)

TRIAL = r'''
from qtbinding.QtWidgets import QMessageBox

fails = []
def check(name, cond, detail=""):
    print(("CHECK ok   " if cond else "CHECK FAIL ") + name +
          (("   " + str(detail)) if not cond else ""))
    if not cond:
        fails.append(name)

said = []
for _name in ("critical", "warning", "information"):
    setattr(QMessageBox, _name,
            staticmethod(lambda *a, **k: said.append(a[2] if len(a) > 2
                                                     else a) or 0))
QMessageBox.question = staticmethod(lambda *a, **k: said.append(a) or 0)


class Bar(object):
    def pushMessage(self, *a, **k): pass
    def __getattr__(self, n): return lambda *a, **k: None


class Face(object):
    def messageBar(self): return Bar()
    def __getattr__(self, n): return lambda *a, **k: None


g["iface"] = Face()
SESSION = g.get("SESSION", {})

DUO = {"id": "duo0001", "name": "duo", "with_tiles": True,
       "operator": "Anna", "operators": ["ANNA", "BRUNO"],
       "classes": CLASSES, "corrections": [], "cutouts": [],
       "grid": dict(Campaign.data["grid"])}
SOLO = {"id": "solo001", "name": "solo", "with_tiles": True,
        "operator": "carla", "classes": CLASSES, "corrections": [],
        "cutouts": [], "grid": dict(Campaign.data["grid"])}


def campaign_of(data):
    c = Campaign()
    c.data = data
    return c


def fresh_panel(data, answer):
    """A panel as a new QGIS session builds it, with the campaign open."""
    p = g["Panel"]()
    p.campaign = campaign_of(data)
    asked = []
    def ask(why, *a, **k):
        asked.append(why)
        return dict(answer) if answer is not None else None
    p.ask_reading = ask
    p.describe_campaign()
    p.update_enabled()
    return p, asked


def annotate(p):
    p.toggle_module(0)
    return p.section


def objects(p):
    p.toggle_module(2)
    return p.section


def set_reading(section, who, pass_no, blind):
    section.operator.setCurrentText(who)
    section.operator_changed()
    section.pass_no.setValue(pass_no)
    section.blind.setChecked(blind)


def reading_of(section):
    return (section.operator_name(), section.pass_no.value(),
            section.blind.isChecked())


print("SECTION BRUNO picks himself, pass 2, blind, in Annotate")
panel1, asked1 = fresh_panel(DUO, {"operator": "ANNA", "pass_no": 1,
                                   "blind": True})
a = annotate(panel1)
check("Annotate opens", a is not None and panel1.open_index == 0)
set_reading(a, "BRUNO", 2, True)
check("Annotate says BRUNO, pass 2, blind",
      reading_of(a) == ("BRUNO", 2, True), reading_of(a))
check("and hides the earlier passes", a.hiding())

print("SECTION he looks at Objects")
o = objects(panel1)
check("Objects opens", o is not None and panel1.open_index == 2)
check("the boxes are filed under BRUNO", panel1.who_is_drawing() == "BRUNO",
      panel1.who_is_drawing())
check("in pass 2", panel1.which_pass() == 2, panel1.which_pass())

print("SECTION and goes back to Annotate")
a = annotate(panel1)
check("Annotate opens again", a is not None and panel1.open_index == 0)
check("still BRUNO, pass 2, blind: not the creator in pass 1",
      reading_of(a) == ("BRUNO", 2, True), reading_of(a))
check("the earlier passes are still hidden", a.hiding())

print("SECTION closes Annotate and opens it again")
panel1.toggle_module(0)
check("closed", panel1.section is None)
a = annotate(panel1)
check("opened again as BRUNO, pass 2, blind",
      a is not None and reading_of(a) == ("BRUNO", 2, True),
      a is not None and reading_of(a))
a.operator.setCurrentText("bruno")
panel1.toggle_module(0)
a = annotate(panel1)
check("the typed name, in its written form",
      a is not None and a.operator_name() == "BRUNO",
      a is not None and a.operator_name())
check("asked once at most in this session", len(asked1) <= 1, asked1)
panel1.toggle_module(0)

print("SECTION the campaign opened again in this session")
again, asked_again = fresh_panel(DUO, {"operator": "ANNA", "pass_no": 1,
                                       "blind": True})
a = annotate(again)
check("BRUNO, pass 2, blind, remembered for the campaign",
      a is not None and reading_of(a) == ("BRUNO", 2, True),
      a is not None and reading_of(a))
check("not asked: BRUNO is who drew last in this session",
      not asked_again, asked_again)
again.toggle_module(0)

print("SECTION another day: QGIS started again")
SESSION["operator"] = None
later, asked_later = fresh_panel(DUO, {"operator": "BRUNO", "pass_no": 2,
                                       "blind": True})
a = annotate(later)
check("asked who is drawing before the first stroke", len(asked_later) == 1,
      asked_later)
check("and told what the campaign remembers",
      asked_later and "BRUNO, pass 2" in asked_later[0], asked_later)
check("Annotate opens as BRUNO, pass 2, blind",
      a is not None and reading_of(a) == ("BRUNO", 2, True),
      a is not None and reading_of(a))
o = objects(later)
check("Objects is not asked again", len(asked_later) == 1, asked_later)
check("and files the boxes under BRUNO, pass 2",
      (later.who_is_drawing(), later.which_pass()) == ("BRUNO", 2),
      (later.who_is_drawing(), later.which_pass()))
later.toggle_module(2)

print("SECTION another day, somebody else at the desk")
SESSION["operator"] = None
other, asked_other = fresh_panel(DUO, {"operator": "ANNA", "pass_no": 1,
                                       "blind": True})
o = objects(other)
check("Objects asks too", len(asked_other) == 1, asked_other)
check("and draws as the reading confirmed: ANNA, pass 1",
      (other.who_is_drawing(), other.which_pass()) == ("ANNA", 1),
      (other.who_is_drawing(), other.which_pass()))
other.toggle_module(2)

print("SECTION Cancel opens nothing")
SESSION["operator"] = None
cancel, asked_cancel = fresh_panel(DUO, None)
annotate(cancel)
check("asked", len(asked_cancel) == 1, asked_cancel)
check("and no module is open", cancel.section is None
      and cancel.open_index is None, cancel.open_index)
check("no error window", not said, said)

print("SECTION one reader: nothing is ever asked")
SESSION["operator"] = None
solo, asked_solo = fresh_panel(SOLO, {"operator": "X", "pass_no": 3,
                                      "blind": False})
a = annotate(solo)
check("Annotate opens without a word", a is not None and not asked_solo,
      asked_solo)
check("as the creator, pass 1",
      a is not None and (a.operator_name(), a.pass_no.value()) == ("CARLA", 1),
      a is not None and reading_of(a))
o = objects(solo)
check("Objects too", o is not None and not asked_solo, asked_solo)
check("filing the boxes under CARLA, pass 1",
      (solo.who_is_drawing(), solo.which_pass()) == ("CARLA", 1),
      (solo.who_is_drawing(), solo.which_pass()))
solo.toggle_module(2)
SESSION["operator"] = None
solo2, asked_solo2 = fresh_panel(SOLO, {"operator": "X", "pass_no": 3,
                                        "blind": False})
a = annotate(solo2)
check("and after a restart", a is not None and not asked_solo2
      and (a.operator_name(), a.pass_no.value()) == ("CARLA", 1),
      (asked_solo2, a is not None and reading_of(a)))

print("VERDICT %d" % len(fails))
'''


def main():
    trial = os.path.join(HERE, "_second_reader.py")
    with open(trial, "w", encoding="utf-8") as f:
        f.write(TRIAL)
    with open(os.path.join(HERE, "harness2.py"), encoding="utf-8") as f:
        code = f.read()
    code = code.replace('panel.grab().save(out)',
                        'exec(open(r"%s", encoding="utf-8").read())' % trial)
    run = os.path.join(HERE, "_run_second_reader.py")
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
