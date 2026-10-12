"""Cutouts, the parts a user touches before anything is written.

  a rectangle dragged on the map is cut with no annotation campaign open,
  where every drag used to raise AttributeError, and a click is still a
  click;
  "Layers to cut" lists the layers in the order of the Layers panel, says
  which one sets the pixel grid and lets it be chosen, and has no band of
  empty space between the column titles and the rows;
  the log goes into the folder of the program, never into the cutouts folder
  (a dataset), when no campaign is open, and lets go when the module closes;
  the folder box losing focus does not forget what this session cut;
  a path past 260 characters is asked for in the form Windows can reach.

No GDAL: QGIS and the rasters are faked, see correctkit.py.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correctkit as K                                             # noqa: E402
from qtbinding import QtCore, QtWidgets                                # noqa: E402

g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_cutouts_window_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])

try:
    print("a rectangle dragged with no campaign open")
    source = open(K.SRC, encoding="utf-8").read()
    tree = ast.parse(source)
    lines = source.splitlines(True)
    node = [n for n in tree.body if isinstance(n, ast.ClassDef)
            and n.name == "CutoutTool"][0]
    space = dict(g)

    def rectangle(*a):
        if len(a) == 2:
            return K.Rect(a[0].x(), a[0].y(), a[1].x(), a[1].y())
        return K.Rect(*a)
    space["QgsRectangle"] = rectangle
    exec("".join(lines[node.lineno - 1:node.end_lineno]), space)
    Tool = space["CutoutTool"]

    class Side:
        def value(self): return 30.0

    class Section:
        """What the tool asks of the module, with no campaign open: there is
        no geometry to measure an area with."""
        geometry = None
        side = Side()
        def __init__(self): self.cut = []
        def square_at(self, p): return K.Rect(p.x() - 1, p.y() - 1,
                                              p.x() + 1, p.y() + 1)
        def export(self, rect, nominal=None): self.cut.append((rect, nominal))
        def undo(self): pass
        def stop_cutting(self): pass

    class Ev:
        def __init__(self, x, y, button=QtCore.Qt.MouseButton.LeftButton):
            self._p, self._b = QtCore.QPoint(x, y), button
        def pos(self): return self._p
        def button(self): return self._b

    section = Section()
    tool = Tool(None, section)
    # a canvas in degrees: a pixel of the screen is a millionth of a degree
    tool.toMapCoordinates = lambda p: K.Point(13.6 + p.x() * 1e-6,
                                              37.4 - p.y() * 1e-6)
    try:
        tool.canvasPressEvent(Ev(100, 100))
        tool.canvasReleaseEvent(Ev(260, 220))
        ok = True
    except Exception as err:
        ok = False
        print("      ", type(err).__name__, err)
    check("a drag is cut, with no campaign to measure it", ok
          and len(section.cut) == 1)
    if section.cut:
        rect, nominal = section.cut[-1]
        check("as the rectangle dragged, not as a square",
              nominal is None and abs(rect.width() - 160e-6) < 1e-12
              and abs(rect.height() - 120e-6) < 1e-12,
              (nominal, rect.width(), rect.height()))
    try:
        tool.canvasPressEvent(Ev(300, 300))
        tool.canvasReleaseEvent(Ev(301, 300))
        ok = True
    except Exception as err:
        ok = False
        print("      ", type(err).__name__, err)
    check("a click that moves by a pixel is still a click",
          ok and len(section.cut) == 2 and section.cut[-1][1] == 30.0,
          section.cut[-1:])
    tool.canvasPressEvent(Ev(10, 10))
    tool.canvasReleaseEvent(Ev(400, 12))
    check("and so is a drag no taller than a few pixels",
          len(section.cut) == 3 and section.cut[-1][1] == 30.0,
          section.cut[-1:])

    print()
    print("the layers in the order of the Layers panel")
    data = os.path.join(root, "data")
    for name in ("72_mappa", "aragona", "zeta"):
        K.write_map(os.path.join(data, name + ".tif"), [[1, 2], [3, 4]])
    mappa = K.add_layer(K.Layer(os.path.join(data, "72_mappa.tif"), "72_mappa"))
    aragona = K.add_layer(K.Layer(os.path.join(data, "aragona.tif"),
                                  "aragona"))
    zeta = K.add_layer(K.Layer(os.path.join(data, "zeta.tif"), "zeta"))

    class TreeNode:
        def __init__(self, lid): self.lid = lid
        def layerId(self): return self.lid

    order = [aragona.id(), mappa.id()]          # zeta is not in the tree
    K.Root.findLayers = lambda self: [TreeNode(i) for i in order]
    by_name = sorted([zeta, aragona, mappa], key=lambda l: l.name())
    got = [l.name() for l in g["in_tree_order"](by_name)]
    check("top of the tree first, a layer the tree does not hold last",
          got == ["aragona", "72_mappa", "zeta"], got)
    del K.Root.findLayers
    check("and a project with no tree to ask keeps the order it was given",
          [l.name() for l in g["in_tree_order"](by_name)]
          == [l.name() for l in by_name])

    print()
    print("Layers to cut")
    rasters = [aragona, mappa, zeta]
    dialog = g["CutoutSetup"](None, rasters, {})
    check("the rows come in the order given",
          [row[0].name() for row in dialog.rows] == ["aragona", "72_mappa",
                                                     "zeta"])
    check("the layer that sets the grid is shown, the first one by default",
          dialog.grid_from.currentText() == "aragona",
          dialog.grid_from.currentText())
    dialog.grid_from.setCurrentIndex(1)
    check("it can be chosen, and goes first in what is cut",
          [s["tag"] for s in dialog.result()][0] == "72_mappa",
          [s["tag"] for s in dialog.result()])
    check("the others keep the order of the panel",
          [s["tag"] for s in dialog.result()] == ["72_mappa", "aragona",
                                                  "zeta"])
    dialog.rows[1][1].setCurrentText("ignore")
    check("a grid layer set to ignore gives the grid to the first cut, "
          "and says so", [s["tag"] for s in dialog.result()][0] == "aragona"
          and "aragona sets it" in dialog.grid_note.text(),
          dialog.grid_note.text())
    again = g["CutoutSetup"](None, rasters, {}, grid_id=zeta.id())
    check("the grid chosen last time is chosen again",
          again.grid_from.currentText() == "zeta")

    # two maps of one model whose names share their first sixty letters: the
    # window made their names in the files with the old cut at 48, and gave
    # the second a "_2", so a layer not remembered by the folder lost its
    # ending here even where the panel kept it
    head = "aragona_orthomosaic_september_2025_the_whole_survey_area"
    longs = []
    for word in ("_disag_classes", "_disag_probabilities"):
        K.write_map(os.path.join(data, "long%d.tif" % len(longs)),
                    [[1, 2], [3, 4]])
        longs.append(K.add_layer(K.Layer(
            os.path.join(data, "long%d.tif" % len(longs)), head + word)))
    wide = g["CutoutSetup"](None, longs, {})
    tags = [row[4].text() for row in wide.rows]
    check("a long name keeps its ending in the window, and the two differ",
          tags[0].endswith("_disag_classes")
          and tags[1].endswith("_disag_probabilities")
          and len(set(tags)) == 2 and all(len(t) <= 48 for t in tags)
          and not any(t.endswith("_2") for t in tags), tags)
    for row in wide.rows:
        row[1].setCurrentText("classes")
    check("and what is accepted is what is shown, not cut again",
          [s["tag"] for s in wide.result()] == tags,
          [s["tag"] for s in wide.result()])
    wide.rows[0][4].setText(head + "_disag_classes_typed_by_hand_" * 3)
    got = wide.result()[0]["tag"]
    check("a name typed by hand is held to 48 letters and keeps its ending",
          len(got) <= 48 and got.endswith("_by_hand"), got)
    saved = {longs[0].id(): {"role": "classes", "tag": tags[0]}}
    back = g["CutoutSetup"](None, longs, saved)
    check("a tag the folder remembers comes back as it was",
          back.rows[0][4].text() == tags[0], back.rows[0][4].text())

    dialog.resize(720, 420)
    dialog.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    heads = [w for w in dialog.findChildren(QtWidgets.QLabel)
             if w.text() == "<b>cut as</b>"]
    combo = dialog.rows[0][1]
    gap = combo.mapTo(dialog, QtCore.QPoint(0, 0)).y() - (
        heads[0].mapTo(dialog, QtCore.QPoint(0, 0)).y() + heads[0].height())
    check("the column titles sit right above the rows",
          heads and heads[0].height() < 40 and gap < 20,
          (heads[0].height() if heads else None, gap))
    dialog.hide()

    print()
    print("the log, with Cutouts open and no campaign")
    panel = g["Panel"]()
    panel.toggle_module(3)
    cut = panel.section
    check("Cutouts is open", type(cut).__name__ == "CutoutsSection")
    folder = os.path.join(root, "dataset")
    cut.folder_box.setText(folder)
    cut.folder_changed()
    check("a folder that does not exist yet gets no log", g["_LOG"]["path"]
          is None, g["_LOG"]["path"])
    check("and nothing is written for it", not os.path.exists(folder))
    check("the folder becomes usable when the first cutout is made",
          cut.folder_is_usable())
    program = os.path.join(os.path.expanduser("~"), "RasterLabel")
    check("and from then on the log goes into the folder of the program",
          g["_LOG"]["path"] == os.path.join(program, "rasterlabel.log"),
          g["_LOG"]["path"])
    g["log"]("a line for the cutouts log")
    check("where it is written",
          "a line for the cutouts log" in open(
              os.path.join(program, "rasterlabel.log"),
              encoding="utf-8").read())
    check("and not in the dataset",
          not os.path.exists(os.path.join(folder, "rasterlabel.log")),
          os.listdir(folder))

    print()
    print("the folder box losing focus")
    cut.written.append(("cut_0001", []))
    cut.folder_box.editingFinished.emit()
    cut.folder_changed()
    check("does not forget what this session cut", cut.written ==
          [("cut_0001", [])], cut.written)
    cut.folder_box.setText(folder + os.sep)
    cut.folder_changed()
    check("nor does the same folder spelled with a slash at the end",
          len(cut.written) == 1)
    cut.folder_box.setText(os.path.join(root, "another"))
    cut.folder_changed()
    check("another folder does start afresh", cut.written == [])

    panel.close_module()
    for _ in range(3):
        QtWidgets.QApplication.processEvents()
    check("closing the module lets the log go", g["_LOG"]["path"] is None,
          g["_LOG"]["path"])

    print()
    print("paths past 260 characters")
    long_path = g["long_path"]
    short = os.path.join(root, "x.tif")
    check("a short path is left as it is", long_path(short) == short)
    deep = os.path.join(root, *(["folder_%02d_with_a_long_name" % i
                                 for i in range(10)]), "x.tif")
    if os.name == "nt":
        check("a long one is asked for with the prefix Windows wants",
              long_path(deep).startswith("\\\\?\\")
              and long_path(deep).endswith("x.tif"), long_path(deep)[:20])
        check("and once only", long_path(long_path(deep)) == long_path(deep))
    else:
        check("elsewhere a path is a path", long_path(deep) == deep)
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
