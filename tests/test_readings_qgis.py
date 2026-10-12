"""Readings in a real QGIS: the map on opening, the passes, the map on closing.

What the author saw while testing a campaign of two operators in two passes:

  open     reopening the campaign drew every reading at once, in odd
           overlapping colours, until Annotate was pressed. The tables are
           now filtered by the reading the panel holds the moment they are
           loaded, and the filter is the one Annotate writes;
  blind    with blind on, pass 1 showed pass 2 on top of it. Now only the
           pass in hand is drawn, earlier or later; the report layers that
           show another pass are switched off in the layer tree;
  passes   a list for each operator, written into the manifest and read back
           by a panel of another session; the + makes the next one, and an
           operator who is added starts at pass 1;
  close    the layers of a closed campaign left the layer tree but their
           polygons stayed drawn until the map was panned or zoomed. The map
           is drawn again once they are gone, and the bands of a tool that
           was mid stroke are wiped.

Needs QGIS; tests/run.py skips it where QGIS is missing and, with
RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgiskit as K  # noqa: E402
from qgis.core import (QgsExpression, QgsExpressionContext,  # noqa: E402
                       QgsExpressionContextUtils, QgsFeature, QgsGeometry,
                       QgsPointXY, QgsProject, QgsRuleBasedRenderer,
                       QgsVectorLayer)

print("QGIS %s" % K.QGIS_VERSION)
root = tempfile.mkdtemp(prefix="rl_readings_")
IMAGE = K.write_image(os.path.join(root, "data", "image.tif"))


def settle():
    for _ in range(5):
        K.app.processEvents()


def start(name):
    QgsProject.instance().clear()
    settle()
    image = K.layer_of(IMAGE)
    panel = K.new_panel()
    folder = K.fresh(os.path.join(root, name))
    campaign = K.new_campaign(panel, folder, image, name=name)
    return panel, campaign, folder


def finish(panel):
    K.close_panel(panel)
    QgsProject.instance().clear()
    settle()


def draw(campaign, operator, pass_no, x):
    """One square polygon of a reading, written into the table."""
    lyr = K.find_mine(campaign.data["id"], "polygons")
    f = QgsFeature(lyr.fields())
    f["class_name"] = "mud"
    f["class_code"] = 1
    f["operator"] = operator
    f["pass_no"] = pass_no
    f.setGeometry(K.square(K.X0 + x, K.Y0 - 10, 5))
    lyr.startEditing()
    lyr.addFeature(f)
    lyr.commitChanges()
    return lyr


def drawn(lyr):
    """What the layer draws, by its own renderer: (operator, pass) of every
    feature that a rule lets through, and the colours it uses."""
    renderer = lyr.renderer()
    out, colours = set(), set()
    if not isinstance(renderer, QgsRuleBasedRenderer):
        return None, None
    context = QgsExpressionContext()
    context.appendScope(QgsExpressionContextUtils.layerScope(lyr))
    rules = [(r.filterExpression(), r.symbol()) for r in
             renderer.rootRule().children()]
    for f in lyr.getFeatures():
        context.setFeature(f)
        for text, symbol in rules:
            if not text or QgsExpression(text).evaluate(context):
                out.add((f["operator"], f["pass_no"]))
                colours.add(symbol.color().name())
    return out, colours


def filters(lyr):
    renderer = lyr.renderer()
    if not isinstance(renderer, QgsRuleBasedRenderer):
        return None
    return sorted(r.filterExpression() for r in renderer.rootRule().children())


# ------------------------------------------------------------------ opening
print()
print("open: the map is filtered before Annotate is pressed")
panel, campaign, folder = start("open")
cid = campaign.data["id"]
for who, p, x in (("ANNA", 1, 10), ("ANNA", 2, 20), ("BRUNO", 1, 30)):
    draw(campaign, who, p, x)
campaign.data["operators"] = ["ANNA", "BRUNO"]
campaign.data["passes"] = {"ANNA": [1, 2]}
campaign.save()
panel.hold_reading("ANNA", 2, True, True)
K.close_panel(panel)
QgsProject.instance().clear()
settle()

panel = K.new_panel()
K.open_campaign(panel, folder)
polys = K.find_mine(cid, "polygons")
K.check("the campaign is open and its polygons are in the project",
        panel.campaign is not None and polys is not None)
shown, colours = drawn(polys)
K.check("opened as ANNA, pass 2, the map draws ANNA's pass 2 and nothing "
        "else", shown == {("ANNA", 2)}, shown)
before = filters(polys)
K.check("a rule based renderer is on the table", before is not None)
section = K.annotate(panel)
polys = K.find_mine(cid, "polygons")
K.check("Annotate opens", section is not None, K.SAID[-3:])
K.check("and writes the very filter the opening had put",
        filters(polys) == before, (before, filters(polys)))
K.check("and draws the same colours", drawn(polys)[1] == colours,
        (colours, drawn(polys)[1]))
section.pass_no.setValue(1)
shown, _ = drawn(K.find_mine(cid, "polygons"))
K.check("going back to pass 1 draws pass 1 and not pass 2",
        shown == {("ANNA", 1)}, shown)
section.blind.setChecked(False)
shown, _ = drawn(K.find_mine(cid, "polygons"))
K.check("blind off draws both passes of ANNA and nobody else's",
        shown == {("ANNA", 1), ("ANNA", 2)}, shown)
panel.toggle_module(0)
K.check("Annotate closed", panel.section is None)
shown, _ = drawn(K.find_mine(cid, "polygons"))
K.check("the filter stays on the tables when the module is closed",
        shown == {("ANNA", 1), ("ANNA", 2)}, shown)
finish(panel)

# ------------------------------------------------------------------- blind
print()
print("blind: the report layers that show another pass are switched off")
panel, campaign, folder = start("veil")
layer = QgsVectorLayer("Polygon?crs=EPSG:32633", "agreement", "memory")
K.g["add_report_layer"](layer, campaign, "agreement", "ANNA p1 vs p2",
                        "pairs", readings=[("ANNA", 1), ("ANNA", 2)])
root_node = QgsProject.instance().layerTreeRoot()
node = root_node.findLayer(layer.id())
K.check("the report layer is in the tree, on",
        node is not None and node.itemVisibilityChecked())
panel.hold_reading("ANNA", 1, True, True)
n = panel.veil_reports()
K.check("a reader of pass 1, blind, has it switched off",
        n == 1 and not node.itemVisibilityChecked(), n)
node.setItemVisibilityChecked(True)
panel.hold_reading("ANNA", 2, True, True)
n = panel.veil_reports()
K.check("so does a reader of pass 2", n == 1 and
        not node.itemVisibilityChecked(), n)
node.setItemVisibilityChecked(True)
panel.hold_reading("ANNA", 1, False, True)
n = panel.veil_reports()
K.check("blind off: nothing is veiled", n == 0 and
        node.itemVisibilityChecked(), n)
refusal = panel.blind_gate([("ANNA", 1), ("ANNA", 2)])
K.check("and Compare may take both", refusal is None, refusal)
panel.hold_reading("ANNA", 1, True, True)
refusal = panel.blind_gate([("ANNA", 1), ("ANNA", 2)])
K.check("blind on, Compare is refused, naming the switch",
        refusal is not None and "blind" in refusal, refusal)
finish(panel)

# ------------------------------------------------------------------ passes
print()
print("passes: a list for each operator, kept in the manifest")
panel, campaign, folder = start("passes")
campaign.data["operators"] = ["ANNA", "BRUNO"]
campaign.save()
section = K.annotate(panel)
K.check("the campaign starts with one operator in pass 1",
        (section.operator_name(), section.pass_no.values(),
         section.pass_no.value()) == ("ANNA", [1], 1),
        (section.operator_name(), section.pass_no.values()))
section.add_pass()
K.check("the + makes pass 2 and stands on it",
        section.pass_no.values() == [1, 2] and section.pass_no.value() == 2,
        (section.pass_no.values(), section.pass_no.value()))
section.operator.setCurrentText("BRUNO")
section.operator_changed()
K.check("BRUNO starts at pass 1, with nothing else on offer",
        (section.pass_no.value(), section.pass_no.values()) == (1, [1]),
        (section.pass_no.value(), section.pass_no.values()))
section.operator.setCurrentText("ANNA")
section.operator_changed()
K.check("ANNA keeps hers", section.pass_no.values() == [1, 2])
K.check("the panel holds the pass", panel.which_pass() == 1,
        panel.which_pass())
read = K.g["Campaign"].open(folder)
K.check("the manifest on disk has the list",
        read.data.get("passes") == {"ANNA": [1, 2]}, read.data.get("passes"))
finish(panel)
panel = K.new_panel()
K.open_campaign(panel, folder)
section = K.annotate(panel)
K.check("another session offers the same passes",
        section.operator_name() == "ANNA" and section.pass_no.values()
        == [1, 2], (section.operator_name(), section.pass_no.values()))
finish(panel)

# ------------------------------------------------------------------ closing
print()
print("close: the map is drawn again, and the bands are wiped")
panel, campaign, folder = start("close")
draw(campaign, "ANNA", 1, 10)
section = K.annotate(panel)
calls = []
canvas = K.iface.canvas
canvas.refreshAllLayers = lambda: calls.append("refreshAllLayers")
canvas.refresh = lambda: calls.append("refresh")
brush = section.brush
# a stroke being drawn when the module is closed, with the tool no longer in
# hand: nothing else would wipe its band
canvas.unsetMapTool(brush)
brush.band.addPoint(QgsPointXY(K.X0 + 1, K.Y0 - 1))
brush.band.addPoint(QgsPointXY(K.X0 + 2, K.Y0 - 1))
brush.band.addPoint(QgsPointXY(K.X0 + 2, K.Y0 - 2))
K.check("a band is on the canvas", brush.band.numberOfVertices() > 0)
calls[:] = []
panel.toggle_module(0)
K.check("closing Annotate wipes the band",
        brush.band.numberOfVertices() == 0, brush.band.numberOfVertices())
calls[:] = []
panel.close_campaign()
K.check("the layers have left the project",
        K.find_mine(campaign.data["id"], "polygons") is None)
K.check("and the canvas is asked to draw again, after they went",
        "refreshAllLayers" in calls, calls)
finish(panel)

shutil.rmtree(root, ignore_errors=True)
K.finish()
