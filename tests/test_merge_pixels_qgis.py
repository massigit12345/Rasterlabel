"""Merging same-class neighbours changes the polygons and not one pixel, in a
real QGIS.

The same session is drawn twice on two campaigns, once with merging switched
off and once as shipped: strokes of three classes over a frame, in two
readings (two passes of one operator, so that the readings lie over each other
and "the one drawn last wins" matters), and a vertex pulled against a
neighbour of its own class. Then everything that is burned from the tables is
burned and compared byte for byte:

  the mask of every reading and of all of them together, burned by GDAL from
  the table as Whole raster burns it (the same stencil);
  the dataset card's pixel counts and areas, for every product it describes
  (every reading, all together, the consensus);
  the share of the frame a reading covers.

What may differ, and is checked to: the number of polygons.

Needs QGIS; tests/run.py skips it where QGIS is missing and, with
RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgiskit as K  # noqa: E402
import numpy as np  # noqa: E402
from qgis.core import (QgsGeometry, QgsPointXY, QgsProject,  # noqa: E402
                       QgsRectangle)

print("QGIS %s" % K.QGIS_VERSION)
g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_merge_pixels_")
IMAGE = K.write_image(os.path.join(root, "data", "image.tif"))
PX = 0.1


def settle():
    for _ in range(5):
        K.app.processEvents()


def start(name, merging):
    QgsProject.instance().clear()
    settle()
    panel = K.new_panel()
    folder = K.fresh(os.path.join(root, name))
    campaign = K.new_campaign(panel, folder, K.layer_of(IMAGE), tiled=True,
                              name=name)
    section = K.annotate(panel)
    section.autosave.setValue(0)
    section.merging = merging
    section.create_tile(QgsPointXY(K.X0 + 10, K.Y0 - 10))
    return panel, campaign, section, folder


def rect(x0, y0, x1, y1):
    return QgsGeometry.fromRect(QgsRectangle(x0, y0, x1, y1))


def session(section, seed):
    """The same strokes whatever the switch says."""
    rng = random.Random(seed)
    bb = section.tile_geometry().boundingBox()
    names = ["mud", "water"]
    for pass_no in (1, 2):
        section.pass_no.setValue(pass_no)
        settle()
        for _ in range(25):
            x = bb.xMinimum() + rng.randrange(0, 170) * PX
            y = bb.yMinimum() + rng.randrange(0, 170) * PX
            w, h = rng.randrange(5, 40) * PX, rng.randrange(5, 40) * PX
            section.choose_class(rng.choice(names))
            section.paint(rect(x, y, min(x + w, bb.xMaximum()),
                               min(y + h, bb.yMaximum())), under=False)
    section.pass_no.setValue(1)
    settle()


def products(campaign, folder, section):
    section.save()
    package = os.path.join(folder, "annotation.gpkg")
    data = dict(campaign.data)
    card = g["card_gather_campaign"](data, folder, package)
    out = {}
    for p in card["products"]:
        out[p["tag"]] = (dict(p["counts"]), dict(p["m2"]))
    # the masks themselves, burned from the table as Whole burns them
    ds = g["gdal"].Open(IMAGE)
    gt, w, h = ds.GetGeoTransform(), ds.RasterXSize, ds.RasterYSize
    wkt = ds.GetProjection()
    masks = {}
    for tag, keep in [("all", None), ("ANNA_p1", {("ANNA", 1)}),
                      ("ANNA_p2", {("ANNA", 2)})]:
        stencil = g["Stencil"](package, "polygons", "class_code", wkt,
                               keep=keep)
        masks[tag] = stencil.burn_into(gt, w, h, wkt)
    coverage = {}
    for p_no in (1, 2):
        section.pass_no.setValue(p_no)
        settle()
        coverage[p_no] = section.measure_tile(
            section.tile_layer.getFeature(
                next(iter(section.tile_layer.getFeatures())).id()))
    section.pass_no.setValue(1)
    return out, masks, coverage


results = {}
for seed in (3, 11):
    for merging in (False, True):
        label = "seed %d, merging %s" % (seed, "on" if merging else "off")
        print()
        print(label)
        panel, campaign, section, folder = start(
            "s%d_%s" % (seed, "on" if merging else "off"), merging)
        lyr = K.find_mine(campaign.data["id"], "polygons")
        session(section, seed)
        check("polygons are in the table", lyr.featureCount() > 0)
        count = lyr.featureCount()
        results[(seed, merging)] = (count, products(campaign, folder, section))
        K.close_panel(panel)
        settle()
    off, on = results[(seed, False)], results[(seed, True)]
    check("seed %d: fewer polygons with merging (%d against %d)"
          % (seed, on[0], off[0]), on[0] < off[0])
    check("seed %d: the card's pixel counts and areas are the same" % seed,
          on[1][0] == off[1][0], (on[1][0], off[1][0]))
    for tag in off[1][1]:
        check("seed %d: the mask of %s is byte for byte the same"
              % (seed, tag),
              on[1][1][tag].tobytes() == off[1][1][tag].tobytes(),
              int((on[1][1][tag] != off[1][1][tag]).sum()))
    check("seed %d: and so is the share of the frame each reading covers"
          % seed, on[1][2] == off[1][2], (on[1][2], off[1][2]))

# ------------------------------------------------------------- a vertex move
print()
print("a vertex pulled against a neighbour of its own class")
shots = {}
for merging in (False, True):
    panel, campaign, section, folder = start(
        "drag_%s" % merging, merging)
    lyr = K.find_mine(campaign.data["id"], "polygons")
    bb = section.tile_geometry().boundingBox()
    x, y = bb.xMinimum(), bb.yMinimum()
    section.choose_class("mud")
    section.paint(rect(x + 1, y + 1, x + 3, y + 3), under=False)
    section.paint(rect(x + 4, y + 1, x + 6, y + 3), under=False)
    section.choose_class("water")
    section.paint(rect(x + 7, y + 1, x + 9, y + 3), under=False)
    before = lyr.featureCount()
    # the second rectangle, pulled left to share the first one's border
    mud = sorted((f for f in lyr.getFeatures() if f["class_name"] == "mud"),
                 key=lambda f: f.geometry().boundingBox().xMinimum())
    lyr.beginEditCommand("Moved vertex")
    second = mud[-1]
    sb = second.geometry().boundingBox()
    lyr.changeGeometry(second.id(), rect(x + 3, sb.yMinimum(), sb.xMaximum(),
                                         sb.yMaximum()))
    lyr.endEditCommand()
    settle()
    shots[merging] = (before, lyr.featureCount(),
                      products(campaign, folder, section))
    K.close_panel(panel)
    settle()
off, on = shots[False], shots[True]
check("the two rectangles are one polygon with merging (%d, was %d)"
      % (on[1], off[1]), on[1] == off[1] - 1, (on[1], off[1]))
check("the card is the same", on[2][0] == off[2][0], (on[2][0], off[2][0]))
check("and every mask", all(on[2][1][t].tobytes() == off[2][1][t].tobytes()
                            for t in off[2][1]))

shutil.rmtree(root, ignore_errors=True)
K.finish()
