"""Objects knows the readings: whose box it is, in which pass, and who may
touch it.

Objects used to know none of it. Every box was stamped with the campaign's
creator and pass 1, whoever drew it, so the boxes of a second reading went
out under the first one in the export of each reading and in the consensus;
in a blind pass the first reading's boxes stayed in sight, because the
filter of the readings was put on polygons, lines and points and never on
the boxes; and a second reader who pressed on an object the first one had
boxed picked that box up and moved it.

The real panel and the real Objects module are built, from the shipped file,
on the fakes of harness2, with a boxes table of their own. BRUNO picks
himself and pass 2, blind, in Annotate, and goes to Objects, as a second
reader does. What has to hold:

  stamped   a box he draws is BRUNO's, pass 2
  hidden    the filter on the boxes shows his reading and nothing else, run
            here through sqlite as the renderer would run it
  refused   ANNA's box under the cursor is not picked up: a press there
            draws a box of his own; moving, stretching, reclassing or
            deleting hers is refused with a message, and hers is unchanged
  his own   his own box is picked up and moved as before
  old       a campaign of one reader whose boxes table has no pass and a
            name written in lower case works as it always did
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
import math
import sqlite3
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
messages = []


class Bar(object):
    def pushMessage(self, *a, **k): messages.append(a[1] if len(a) > 1 else a)
    def __getattr__(self, n): return lambda *a, **k: None


class Face(object):
    def messageBar(self): return Bar()
    def __getattr__(self, n): return lambda *a, **k: None


g["iface"] = Face()
SESSION = g.get("SESSION", {})


# ------------------------------------------------- geometry, just enough
class Pt(object):
    def __init__(self, x, y): self._x, self._y = float(x), float(y)
    def x(self): return self._x
    def y(self): return self._y


class Rect(object):
    def __init__(self, a, b, c=None, d=None):
        if c is None:
            a, b, c, d = a.x(), a.y(), b.x(), b.y()
        self.v = (min(a, c), min(b, d), max(a, c), max(b, d))
    def xMinimum(self): return self.v[0]
    def yMinimum(self): return self.v[1]
    def xMaximum(self): return self.v[2]
    def yMaximum(self): return self.v[3]
    def width(self): return self.v[2] - self.v[0]
    def height(self): return self.v[3] - self.v[1]
    def area(self): return self.width() * self.height()
    def center(self):
        return Pt((self.v[0] + self.v[2]) / 2, (self.v[1] + self.v[3]) / 2)


class Geom(object):
    def __init__(self, rect=None, point=None):
        self.rect, self.point = rect, point
    @staticmethod
    def fromPointXY(p): return Geom(point=p)
    @staticmethod
    def fromRect(r): return Geom(rect=r)
    def intersects(self, other):
        p = other.point
        r = self.rect
        return (r.v[0] <= p.x() <= r.v[2]) and (r.v[1] <= p.y() <= r.v[3])
    def boundingBox(self): return self.rect


class Measure(object):
    def measureLine(self, a, b): return math.hypot(b.x() - a.x(), b.y() - a.y())


g["QgsGeometry"] = Geom
g["QgsPointXY"] = Pt
g["Geometry"].measure = Measure()
g["Geometry"].pixel_crs = (0.05, 0.05)


# ------------------------------------------------- a table, just enough
class Fields(object):
    def __init__(self, names): self._n = list(names)
    def names(self): return list(self._n)
    def indexOf(self, n): return self._n.index(n) if n in self._n else -1
    def __iter__(self): return iter(Field(n) for n in self._n)


class Field(object):
    def __init__(self, n): self.n = n
    def name(self): return self.n


class Feature(object):
    def __init__(self, fields, fid=None, **values):
        self._fields = fields if isinstance(fields, Fields) else Fields(fields)
        self.values = {}
        self.fid = fid
        self.g = None
        for k, v in values.items():
            self[k] = v
    def fields(self): return self._fields
    def __getitem__(self, k):
        if k not in self._fields.names():
            raise KeyError(k)
        return self.values.get(k)
    def __setitem__(self, k, v):
        if k not in self._fields.names():
            raise KeyError(k)
        self.values[k] = v
    def setGeometry(self, g_): self.g = g_
    def geometry(self): return self.g
    def hasGeometry(self): return self.g is not None
    def id(self): return self.fid


class Rule(object):
    def __init__(self): self.expr = ""
    def filterExpression(self): return self.expr
    def setFilterExpression(self, e): self.expr = e


class Rules(object):
    def __init__(self): self.kids = [Rule()]
    def rootRule(self): return self
    def children(self): return self.kids


class Renderer(object):
    @staticmethod
    def convertFromRenderer(old): return Rules()


g["QgsFeature"] = Feature
g["QgsRuleBasedRenderer"] = Renderer
g["style_by_class"] = lambda *a, **k: None


class Table(object):
    def __init__(self, names):
        self._fields = Fields(names)
        self.rows = {}
        self.rules = None
        self.next = 1
        self.editing = False
    def fields(self): return self._fields
    def add(self, rect, **values):
        f = Feature(self._fields, self.next, **values)
        f.setGeometry(Geom(rect=rect))
        self.rows[self.next] = f
        self.next += 1
        return f.fid
    def getFeatures(self, *a): return iter(list(self.rows.values()))
    def getFeature(self, fid):
        return self.rows.get(fid) or Feature(self._fields, None)
    def addFeature(self, f):
        f.fid = self.next
        self.rows[self.next] = f
        self.next += 1
        return True
    def changeGeometry(self, fid, g_): self.rows[fid].setGeometry(g_)
    def changeAttributeValue(self, fid, index, value):
        self.rows[fid].values[self._fields.names()[index]] = value
    def deleteFeature(self, fid): self.rows.pop(fid, None)
    def isEditable(self): return self.editing
    def startEditing(self): self.editing = True; return True
    def isModified(self): return False
    def renderer(self): return None
    def setRenderer(self, r): self.rules = r
    def subsetString(self): return ""
    def expressions(self):
        return [] if self.rules is None else \
            [r.expr for r in self.rules.rootRule().children()]
    def __getattr__(self, n): return lambda *a, **k: None


NAMES = ["class_name", "class_code", "tile_id", "pass_no", "operator",
         "width_m", "height_m", "created"]
LAYERS = {}
g["find_mine"] = lambda cid, role, *a, **k: LAYERS.get((cid, role))

DUO = {"id": "duo0002", "name": "duo", "with_tiles": True,
       "operator": "Anna", "operators": ["ANNA", "BRUNO"],
       "classes": CLASSES, "corrections": [], "cutouts": [],
       "grid": dict(Campaign.data["grid"])}


def campaign_of(data):
    c = Campaign()
    c.data = data
    return c


def fresh_panel(data, answer):
    p = g["Panel"]()
    p.campaign = campaign_of(data)
    p.ask_reading = lambda why, *a, **k: dict(answer)
    p.describe_campaign()
    p.update_enabled()
    return p


def geometry_of(table, fid):
    return table.rows[fid].geometry().boundingBox().v


print("SECTION BRUNO, pass 2, blind, set in Annotate, then Objects")
SESSION["operator"] = None
panel = fresh_panel(DUO, {"operator": "ANNA", "pass_no": 1, "blind": True})
panel.toggle_module(0)
a = panel.section
a.operator.setCurrentText("BRUNO")
a.operator_changed()
a.pass_no.setValue(2)
a.blind.setChecked(True)
panel.toggle_module(0)
# the tables are there from here on: Annotate is drawn on the harness's
# empty project, as harness2 always draws it
boxes = Table(NAMES)
polygons = Table(["class_name", "class_code", "tile_id", "pass_no",
                  "operator", "created"])
LAYERS[(DUO["id"], "boxes")] = boxes
LAYERS[(DUO["id"], "polygons")] = polygons
anna = boxes.add(Rect(0, 0, 10, 10), class_name="crust", class_code=1,
                 operator="ANNA", pass_no=1, tile_id="")
anna_p2 = boxes.add(Rect(100, 100, 110, 110), class_name="crust",
                    class_code=1, operator="Anna", pass_no=2, tile_id="")
panel.toggle_module(2)
o = panel.section
check("Objects opens", o is not None and panel.open_index == 2, said)

print("SECTION stamped")
o.choose_class("crust")
before = set(boxes.rows)
o.create_box(Rect(20, 20, 30, 30))
new = sorted(set(boxes.rows) - before)
check("one box drawn", len(new) == 1, new)
bruno = new[0] if new else None
check("it is BRUNO's", bruno and boxes.rows[bruno]["operator"] == "BRUNO",
      bruno and boxes.rows[bruno].values)
check("in pass 2", bruno and boxes.rows[bruno]["pass_no"] == 2,
      bruno and boxes.rows[bruno].values)

print("SECTION hidden")
exprs = boxes.expressions()
check("the boxes are filtered", len(exprs) == 1, exprs)
db = sqlite3.connect(":memory:")
db.execute("CREATE TABLE b (fid INTEGER, tile_id TEXT, pass_no INT, "
           "operator TEXT)")
db.executemany("INSERT INTO b VALUES (?,?,?,?)",
               [(1, "", 1, "ANNA"), (2, "", 2, "Anna"), (3, "", 2, "BRUNO"),
                (4, "", 1, "BRUNO"), (5, "", 2, " bruno ")])
shown = set()
if exprs:
    try:
        shown = {r[0] for r in db.execute("SELECT fid FROM b WHERE "
                                          + exprs[0])}
    except sqlite3.Error as err:
        shown = "broken: %s" % err
check("only BRUNO's pass 2 is in sight, however his name was written",
      shown == {3, 5}, shown)
check("the polygons are filtered the same way",
      polygons.expressions() and "pass_no" in polygons.expressions()[0],
      polygons.expressions())
check("the tally counts what is in sight", "1 boxes" in o.tally.text(),
      o.tally.text())
label = getattr(o, "reading_label", None)
label = label.text() if label is not None else ""
check("and the module says who is drawing", "BRUNO, pass 2" in label, label)

print("SECTION refused")
messages[:] = []
hit = o.box_at(Pt(5, 5))
check("ANNA's box is not picked up", hit is None,
      hit is not None and hit.values)
hit = o.box_at(Pt(105, 105))
check("nor her box of pass 2", hit is None, hit is not None and hit.values)
o.select_box(anna)
o.reshape_box(Rect(50, 50, 60, 60))
check("moving it, even when picked up some other way, is refused",
      geometry_of(boxes, anna) == (0, 0, 10, 10), geometry_of(boxes, anna))
check("with a message", any("another reading" in str(m) for m in messages),
      messages)
o.select_box(anna)
o.delete_selected()
check("deleting it is refused", anna in boxes.rows)
o.choose_class("water")
o.assign_class_at(Pt(5, 5))
check("reclassing it is refused", boxes.rows[anna]["class_name"] == "crust",
      boxes.rows[anna].values)
check("and nothing of hers changed",
      boxes.rows[anna]["operator"] == "ANNA"
      and boxes.rows[anna]["pass_no"] == 1)

print("SECTION his own")
hit = o.box_at(Pt(25, 25))
check("his box is picked up", hit is not None and hit.id() == bruno,
      hit is not None and hit.values)
# every edit of a box is written into the recovery net, as a stroke is
net = []
panel.keep_safe = lambda: net.append(1)
o.select_box(bruno)
o.reshape_box(Rect(40, 40, 52, 52))
check("and moved", bruno and geometry_of(boxes, bruno) == (40, 40, 52, 52),
      bruno and geometry_of(boxes, bruno))
check("a stretched box is in the recovery net", len(net) == 1, net)
o.assign_class_at(Pt(45, 45))
check("and reclassed", boxes.rows[bruno]["class_name"] == "water",
      boxes.rows[bruno].values)
check("a reclassed box is in the recovery net", len(net) == 2, net)
o.select_box(bruno)
o.delete_selected()
check("and deleted", bruno not in boxes.rows)
check("a deleted box is in the recovery net", len(net) == 3, net)
net[:] = []
o.select_box(anna)
o.reshape_box(Rect(50, 50, 60, 60))
check("a refused edit changes nothing, so the net is not asked", not net, net)
panel.toggle_module(2)

print("SECTION old: one reader, no pass column, a name in lower case")
SESSION["operator"] = None
OLD = {"id": "old0001", "name": "old", "with_tiles": True,
       "operator": "carla", "classes": CLASSES, "corrections": [],
       "cutouts": [], "grid": dict(Campaign.data["grid"])}
old = Table([n for n in NAMES if n != "pass_no"])
LAYERS[(OLD["id"], "boxes")] = old
mine = old.add(Rect(0, 0, 10, 10), class_name="crust", class_code=1,
               operator="carla", tile_id="")
panel2 = fresh_panel(OLD, {"operator": "X", "pass_no": 3, "blind": False})
asked = []
panel2.ask_reading = lambda *a, **k: asked.append(a) or None
panel2.toggle_module(2)
o = panel2.section
check("Objects opens without a question", o is not None and not asked,
      asked)
hit = o.box_at(Pt(5, 5)) if o is not None else None
check("her box is picked up", hit is not None and hit.id() == mine)
o.select_box(mine)
o.reshape_box(Rect(1, 1, 12, 12))
check("and moved", geometry_of(old, mine) == (1, 1, 12, 12),
      geometry_of(old, mine))
o.choose_class("crust")
before = set(old.rows)
o.create_box(Rect(20, 20, 30, 30))
added = sorted(set(old.rows) - before)
check("a new box is CARLA's", added and old.rows[added[0]]["operator"]
      == "CARLA", added and old.rows[added[0]].values)
check("and is hers to move", o.box_at(Pt(25, 25)) is not None)
check("the tally counts both", "2 boxes" in o.tally.text(), o.tally.text())
panel2.toggle_module(2)
check("no error window", not said, said)

print("VERDICT %d" % len(fails))
'''


def main():
    trial = os.path.join(HERE, "_boxes_by_reading.py")
    with open(trial, "w", encoding="utf-8") as f:
        f.write(TRIAL)
    with open(os.path.join(HERE, "harness2.py"), encoding="utf-8") as f:
        code = f.read()
    code = code.replace('panel.grab().save(out)',
                        'exec(open(r"%s", encoding="utf-8").read())' % trial)
    run = os.path.join(HERE, "_run_boxes_by_reading.py")
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
