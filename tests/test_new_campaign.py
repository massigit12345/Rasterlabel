"""Open QGIS, load an image, save the campaign in the project folder,
annotate.

The New dialog is really built, with Qt and with fake rasters that answer
the way the real ones do, and we read what it proposes: where the folder
comes from, tiled or free, how many classes. Three walls that were there
up to 3.16, one proof each.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast
import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtbinding import QtCore, QtGui, QtWidgets
from qtbinding.QtWidgets import QApplication

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
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if inside is None and isinstance(t, ast.Name) and t.id == name:
                    return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if getattr(sub, "name", None) == name:
                    t = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s not found" % name)


app = QApplication([])

# ------------------------------------------------------------ the test bench
class Crs(object):
    def __init__(self, code="EPSG:32633"):
        self.code = code
    def isValid(self):
        return bool(self.code)
    def authid(self):
        return self.code


class Raster(object):
    def __init__(self, name, w, h, code="EPSG:32633",
                 path="/data/photo.tif"):
        self._n, self._w, self._h = name, w, h
        self._c, self._p = Crs(code), path
    def name(self): return self._n
    def width(self): return self._w
    def height(self): return self._h
    def crs(self): return self._c
    def source(self): return self._p
    def id(self): return self._n


PROJECT_HOME = {"home": ""}


class Project(object):
    @staticmethod
    def instance():
        return Project()
    def homePath(self):
        return PROJECT_HOME["home"]
    def mapLayer(self, ident):
        return RASTERS.get(ident)


g = dict(vars(QtWidgets))
g.update(vars(QtCore))
g.update(vars(QtGui))
g.update({"os": os, "re": __import__("re"), "sys": sys,
          "NAME": "RasterLabel", "QgsProject": Project,
          "log": lambda *a, **k: None,
          "shielded": lambda slot, what: slot,
          "run_dialog": lambda d: 0,
          "pixel_on_the_ground": lambda l: (0.05, 0.05),
          "crs_label": lambda c: c.authid() or "no coordinate system",
          "source_of": lambda l: l.source(),
          "describe_existing": lambda f: (None, {}),
          # what the file says beyond the layer: nothing, for these fakes
          "raster_notes": lambda l: [],
          "crs_not_in_file": lambda l: None,
          "ClassEditor": object})
exec(take("tidy"), g)
# the pieces every window of the program is built from: its title, the
# button beside a folder, the hairline
for piece in ("titled", "browse", "rule"):
    exec(take(piece), g)
for const_name in ("BIG_RASTER_PX", "FIRST_CLASS", "TILE_SIDE_PX"):
    exec(take(const_name), g)
exec(take("Campaign").split("\n\n")[0].split("class Campaign")[0] or "", g)
g["Campaign"] = types.SimpleNamespace(MANIFEST="campaign.json")
exec(take("NewCampaign"), g)
NewCampaign = g["NewCampaign"]

ORTHO = Raster("ortho_mosaic", 18000, 14000)
import tempfile
PHOTO_FOLDER = tempfile.mkdtemp(prefix="images_")
PHOTO = Raster("kittens", 1200, 800, code="",
               path=os.path.join(PHOTO_FOLDER, "kittens.jpg"))
SMALL = Raster("sentinel_chip", 512, 512)
RASTERS = {r.name(): r for r in (ORTHO, PHOTO, SMALL)}


def open_dialog(rasters, home=""):
    PROJECT_HOME["home"] = home
    d = NewCampaign(None, rasters)
    return d


print("the folder comes out already filled in")
project_home = os.path.abspath(os.path.join(os.sep, "tmp"))
d = open_dialog([ORTHO], home=project_home)
expected = os.path.join(project_home, "campaign")
check("from the project folder, plus the name", d.folder.text() == expected,
      d.folder.text())

d.name.setText("survey 2025")
d.name.textEdited.emit("survey 2025")
check("and it follows the name as you type it",
      d.folder.text() == os.path.join(project_home, "survey_2025"),
      d.folder.text())
check("with the name tidied up, not with the spaces still in it",
      " " not in os.path.basename(d.folder.text()))

d.folder.setText("D:/elsewhere")
d.folder.textEdited.emit("D:/elsewhere")
d.name.setText("third name")
d.name.textEdited.emit("third name")
check("but as soon as you touch it by hand it stops following",
      d.folder.text() == "D:/elsewhere", d.folder.text())

# QGIS spells the folder of a project with slashes. Joined to a backslash
# that was a path with both in it, in the box and on the manifest.
slashed = project_home.replace(os.sep, "/")
d = open_dialog([ORTHO], home=slashed)
check("a project folder with slashes gives a folder spelled one way",
      d.folder.text() == os.path.normpath(os.path.join(slashed, "campaign"))
      and not ("/" in d.folder.text() and "\\" in d.folder.text()),
      d.folder.text())

print()
print("project not saved: it falls back on the image's folder")
d = open_dialog([PHOTO], home="")
check("the raster's folder", d.folder.text()
      == os.path.join(PHOTO_FOLDER, "campaign"), d.folder.text())

print()
print("tiled or free, the raster proposes it")
d = open_dialog([ORTHO], home=project_home)
check("an 18000 x 14000 orthomosaic asks for tiles", d.tiled.isChecked())
check("and it writes down why", "18000 x 14000" in d.info.text(),
      d.info.text())

d = open_dialog([PHOTO], home=project_home)
check("a jpg with no coordinate system starts free", d.free.isChecked())
check("and says so instead of doing it behind your back",
      "no coordinate system" in d.info.text(), d.info.text())
check("warning that the measurements are not metres",
      "not metres" in d.info.text(), d.info.text())

d = open_dialog([SMALL], home=project_home)
check("a georeferenced 512 x 512 cutout starts free",
      d.free.isChecked(), d.info.text())
check("because it is finished in one go",
      "in one go" in d.info.text(), d.info.text())

print()
print("but it stays a proposal")
d = open_dialog([ORTHO], home=project_home)
d.free.setChecked(True)
d.free.clicked.emit(True)
d.show_grid()
check("chosen by hand, the raster does not swap it back under you",
      d.free.isChecked())

print()
print("Ok can be pressed without having invented a legend")
d = open_dialog([ORTHO], home=project_home)
check("there is one class already", len(d.classes) == 1, d.classes)
check("it is called class 1", d.classes[0]["name"] == "class 1", d.classes)
check("and it has a colour", d.classes[0]["colour"].startswith("#"),
      d.classes)
check("the summary invites you to rename it",
      "rename" in d.summary.text(), d.summary.text())

stopped = []
g["QMessageBox"].warning = staticmethod(
    lambda *a, **k: stopped.append(a[2] if len(a) > 2 else a) or 0)
d.folder.setText(os.path.join(project_home, "ok_test"))
d.check()
check("and check() no longer stops on the legend",
      not any("class" in str(f) for f in stopped), stopped)

print()
print("the raster proposed is the one in hand, not the first by name")
# The list is by name, and Ok pressed straight away made the grid of the
# campaign, for good, on whichever raster sorted first: five centimetres where
# the picture on screen was ten.
FIRST = Raster("a_first_by_name", 800, 600)
SECOND = Raster("m_selected_in_the_tree", 900, 700)
THIRD = Raster("z_top_of_the_tree", 1000, 800)
BY_NAME = [FIRST, SECOND, THIRD]
RASTERS.update({r.name(): r for r in BY_NAME})


class Node(object):
    def __init__(self, ident):
        self._id = ident
    def layerId(self):
        return self._id


class Root(object):
    def findLayers(self):
        # the Layers panel, top first: not the order of the names
        return [Node("z_top_of_the_tree"), Node("a_first_by_name"),
                Node("m_selected_in_the_tree")]


class Tree(object):
    @staticmethod
    def instance():
        return types.SimpleNamespace(layerTreeRoot=lambda: Root())


class Window(object):
    active = None
    def activeLayer(self):
        return self.active


window = Window()
q = {"iface": window, "QgsProject": Tree}
exec(take("in_tree_order"), q)
exec(take("proposed_raster"), q)
pick = q["proposed_raster"]
check("with a raster selected in the tree, that one",
      (setattr(window, "active", SECOND), pick(BY_NAME))[1] is SECOND)
check("a selected layer that is no raster of the list is no reason",
      (setattr(window, "active", types.SimpleNamespace(id=lambda: "vector")),
       pick(BY_NAME))[1] is THIRD)
window.active = None
check("with nothing selected, the one on top of the tree, not the first "
      "by name", pick(BY_NAME) is THIRD)
check("the panel's own box, set to another by hand, counts before the tree",
      pick(BY_NAME, chosen="m_selected_in_the_tree") is SECOND)
check("but its first entry is only where the box starts, and says nothing",
      pick(BY_NAME, chosen="a_first_by_name") is THIRD)
check("an empty list proposes nothing", pick([]) is None)
q["iface"] = None
check("and without a window to ask, the tree still decides",
      pick(BY_NAME) is THIRD)

d = NewCampaign(None, BY_NAME, "m_selected_in_the_tree")
check("the window opens on the raster handed to it",
      d.chosen_raster() is SECOND, d.raster.currentText())
d = NewCampaign(None, BY_NAME, "gone")
check("a name that is not in the list changes nothing",
      d.chosen_raster() is FIRST, d.raster.currentText())
d = NewCampaign(None, BY_NAME)
check("and with none the window is what it was",
      d.chosen_raster() is FIRST)
check("the panel hands the window the raster in hand",
      "proposed_raster(rasters, self.rasters.currentData())"
      in take("new_campaign", "Panel"))

print()
print("what must not have changed")
check("an empty folder is still refused",
      "Choose a folder" in take("check", "NewCampaign"))
check("without a raster there is no starting",
      "A reference raster is needed" in take("check", "NewCampaign"))
check("and overwriting a campaign still asks",
      "REPLACES it" in take("check", "NewCampaign"))

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
