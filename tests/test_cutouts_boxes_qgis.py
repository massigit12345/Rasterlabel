"""The boxes of Objects leave the program as detection labels, from Cutouts.

Objects says it draws rectangles "for detection training", and until now
nothing carried them out except Export, which writes them as polygons in the
coordinates of the map. A detector wants pixels of the picture it is shown,
so Cutouts writes, for the images it cuts:

- boxes_coco.json for the whole folder: images, annotations with bbox
  [x, y, width, height] in the pixels of each image counted from the top
  left, category_id the class code of the campaign, and the categories;
- labels/<image>.txt in the YOLO form, "index cx cy w h" as fractions of the
  image, the index counting the campaign's classes from 0 in the order of
  their codes, and labels/classes.txt naming them.

What has to hold, on a real campaign with boxes of two readings, cut for
real:

  numbers    a box lands on the pixels it covers, in COCO and in YOLO
  clipped    a box over the edge of the cutout is cut to it and says so; one
             outside is not there
  reading    all readings together, or one: the boxes of the reading chosen
  folder     a second cutout is added to the same book; undo takes it out of
             the book and its YOLO files off the disk
  off        with the option unticked nothing is written
  no boxes   a campaign with none writes none of it

Needs QGIS itself (tests/run.py skips it where QGIS is missing and, with
RL_REQUIRE_QGIS=1, fails it).
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgiskit as K  # noqa: E402
from qgis.core import (QgsFeature, QgsGeometry, QgsPointXY,  # noqa: E402
                       QgsRectangle)

print("QGIS %s" % K.QGIS_VERSION)
check = K.check
root = tempfile.mkdtemp(prefix="rl_cutout_boxes_")
X0, Y0 = K.X0, K.Y0


def add_boxes(layer, boxes):
    """(operator, pass, code, xmin, ymin, xmax, ymax) rows, committed."""
    names = {c["code"]: c["name"] for c in K.CLASSES}
    layer.startEditing()
    for who, p, code, x0, y0, x1, y1 in boxes:
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromRect(QgsRectangle(x0, y0, x1, y1)))
        f["class_code"] = code
        f["class_name"] = names[code]
        f["operator"] = who
        f["pass_no"] = p
        f["tile_id"] = ""
        layer.addFeature(f)
    check("the boxes are committed", layer.commitChanges(),
          layer.commitErrors())


def text_of(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def cut_here(cut):
    """The 10 m square at the top left corner of the image: x from X0 to
    X0 + 10, y from Y0 - 10 to Y0, at 0.1 m a pixel."""
    return cut.export(cut.square_at(QgsPointXY(X0 + 5, Y0 - 5)),
                      nominal=float(cut.side.value()))


def label_files(folder):
    return sorted(f for f in os.listdir(folder) if f != "classes.txt")


try:
    image = K.layer_of(K.write_image(os.path.join(root, "data", "image.tif")))
    panel = K.new_panel()
    campaign = K.new_campaign(panel, os.path.join(root, "camp"), image)
    boxes_layer = K.find_mine(campaign.data["id"], "boxes")
    add_boxes(boxes_layer, [
        # inside: x 2..4 m, 3..6 m below the top edge -> pixels 20..40, 30..60
        ("ANNA", 1, 2, X0 + 2, Y0 - 6, X0 + 4, Y0 - 3),
        # over the right edge: x 9..12 m, 1..2 m below the top
        ("ANNA", 1, 1, X0 + 9, Y0 - 2, X0 + 12, Y0 - 1),
        # another reading's box, inside
        ("BRUNO", 1, 1, X0 + 5, Y0 - 9, X0 + 6, Y0 - 8),
        # outside the cutout altogether
        ("ANNA", 1, 1, X0 + 15, Y0 - 5, X0 + 16, Y0 - 4)])

    panel.toggle_module(3)
    cut = panel.section
    check("Cutouts opens on the campaign", type(cut).__name__ ==
          "CutoutsSection" and cut.campaign is not None)

    def only_the_image(d):
        for layer, role, band, rgb, tag, _, shape in d.rows:
            role.setCurrentText("image" if layer.id() == image.id()
                                else "ignore")
        return 1

    K.ANSWERS["CutoutSetup"] = only_the_image
    cut.pick_layers()
    out = os.path.join(root, "dataset")
    cut.folder_box.setText(out)
    cut.folder_changed()
    cut.side.setValue(10.0)
    check("the option is there, ticked", cut.boxes.isChecked())
    names = [cut.boxes_reading.itemText(i)
             for i in range(cut.boxes_reading.count())]
    check("and the readings to take the boxes from: all, or one",
          names == ["boxes of all readings together", "boxes of ANNA, pass 1",
                    "boxes of BRUNO, pass 1"], names)
    policy = K.QtWidgets.QComboBox.SizeAdjustPolicy
    check("a long name in that list is cut at the edge of the panel, not "
          "made wide",
          cut.boxes_reading.sizeAdjustPolicy()
          == policy.AdjustToMinimumContentsLengthWithIcon
          and cut.boxes_reading.sizeHint().width() < 300,
          (cut.boxes_reading.sizeAdjustPolicy(),
           cut.boxes_reading.sizeHint().width()))

    print()
    print("all readings together")
    check("the cutout is written", cut_here(cut), K.BOXES[-3:])
    coco_path = os.path.join(out, "boxes_coco.json")
    check("boxes_coco.json is in the folder", os.path.isfile(coco_path),
          sorted(os.listdir(out)))
    coco = read_json(coco_path)
    check("one image, with its size and its name",
          len(coco["images"]) == 1 and coco["images"][0]["width"] == 100
          and coco["images"][0]["height"] == 100
          and coco["images"][0]["file_name"].endswith("_image.tif"),
          coco["images"])
    check("three boxes: the one outside is not there",
          len(coco["annotations"]) == 3, coco["annotations"])
    by_code = {}
    for a in coco["annotations"]:
        by_code.setdefault(a["category_id"], []).append(a)
    inside = by_code[2][0]
    check("the box of class 2 is on pixels 20..40 across, 30..60 down",
          inside["bbox"] == [20.0, 30.0, 20.0, 30.0]
          and inside["area"] == 600.0, inside)
    check("and carries its reading and is not clipped",
          inside["attributes"]["operator"] == "ANNA"
          and inside["attributes"]["pass"] == 1
          and inside["attributes"]["clipped"] is False, inside)
    clipped = [a for a in by_code[1]
               if a["attributes"]["operator"] == "ANNA"][0]
    check("the box over the edge stops at pixel 100 and says so",
          clipped["bbox"] == [90.0, 10.0, 10.0, 10.0]
          and clipped["attributes"]["clipped"] is True, clipped)
    check("the categories are the campaign's classes, by their codes",
          [(c["id"], c["name"]) for c in coco["categories"]] ==
          [(1, "mud"), (2, "water")], coco["categories"])
    labels = os.path.join(out, "labels")
    txts = label_files(labels)
    check("one YOLO file for the image, named like it", len(txts) == 1
          and txts[0].endswith("_image.txt"), txts)
    lines = text_of(os.path.join(labels, txts[0])).splitlines()
    check("class 2 is index 1: centre 0.3, 0.45, size 0.2, 0.3",
          "1 0.300000 0.450000 0.200000 0.300000" in lines, lines)
    check("the clipped box is centred on what is left of it",
          "0 0.950000 0.150000 0.100000 0.100000" in lines, lines)
    check("three lines", len(lines) == 3, lines)
    check("classes.txt names the indices in the order of the codes",
          text_of(os.path.join(labels, "classes.txt")) == "mud\nwater\n")
    check("and the label files are among those undo takes away",
          any(p.endswith(".txt") for p in cut.written[-1][1]))

    print()
    print("one reading, and a second cutout in the same book")
    cut.boxes_reading.setCurrentIndex(names.index("boxes of ANNA, pass 1"))
    check("the second cutout is written", cut_here(cut), K.BOXES[-3:])
    coco = read_json(coco_path)
    check("two images now", len(coco["images"]) == 2
          and len({i["id"] for i in coco["images"]}) == 2, coco["images"])
    second = [i for i in coco["images"] if i["cutout"] == "cut_0002"][0]
    mine = [a for a in coco["annotations"] if a["image_id"] == second["id"]]
    check("only ANNA's two boxes are in it",
          len(mine) == 2 and {a["attributes"]["operator"] for a in mine}
          == {"ANNA"}, mine)
    check("the first cutout kept its three",
          len([a for a in coco["annotations"]
               if a["image_id"] != second["id"]]) == 3)
    check("annotation numbers are all different",
          len({a["id"] for a in coco["annotations"]}) == 5)
    check("two YOLO files", len(label_files(labels)) == 2)

    print()
    print("undo")
    cut.undo()
    coco = read_json(coco_path)
    check("the second cutout is out of the book", [i["cutout"]
          for i in coco["images"]] == ["cut_0001"] and len(
              coco["annotations"]) == 3, coco["images"])
    check("and its YOLO file is off the disk", len(label_files(labels)) == 1)

    print()
    print("the option off")
    cut.boxes.setChecked(False)
    before = text_of(coco_path)
    check("a third cutout is written", cut_here(cut), K.BOXES[-3:])
    check("and the book is as it was",
          text_of(coco_path) == before)
    check("with no YOLO file for it", len(label_files(labels)) == 1)
    cut.boxes.setChecked(True)

    def layers_as(roles, grid):
        """Answer the Layers window: a role by layer name, the grid layer."""
        def answer(d):
            for layer, role, band, rgb, tag, _, shape in d.rows:
                role.setCurrentText(roles.get(layer.name(), "ignore"))
            d.grid_from.setCurrentIndex(d.grid_from.findText(grid))
            return 1
        K.ANSWERS["CutoutSetup"] = answer
        cut.pick_layers()

    print()
    print("a layer that keeps its own grid, smaller than the window")
    # 50 pixels of 0.1 m from the same corner: 5 m of the 10 m window
    small = K.layer_of(K.write_image(os.path.join(root, "data", "small.tif"),
                                     n=50), show=False)
    layers_as({"image.tif": "image", "small.tif": "image"}, "image.tif")
    cut.common.setChecked(False)
    cut.boxes_reading.setCurrentIndex(0)
    check("the cutout is written", cut_here(cut), K.BOXES[-3:])
    cut_name = cut.written[-1][0]
    coco = read_json(coco_path)
    sizes = {i["file_name"]: (i["width"], i["height"], i["id"])
             for i in coco["images"] if i["cutout"] == cut_name}
    big = [v for k, v in sizes.items() if "image_tif" in k]
    little = [v for k, v in sizes.items() if "small_tif" in k]
    check("two images, 100 by 100 and 50 by 50", len(big) == 1
          and big[0][:2] == (100, 100) and len(little) == 1
          and little[0][:2] == (50, 50), sizes)
    inside_of = lambda image_id: [
        a for a in coco["annotations"] if a["image_id"] == image_id
        and a["category_id"] == 2]
    check("the box of class 2 is on the same pixels in the big one",
          [a["bbox"] for a in inside_of(big[0][2])] == [[20.0, 30.0, 20.0,
                                                          30.0]],
          inside_of(big[0][2]))
    check("and on the pixels of the small one, not stretched over fewer: "
          "20..40 across, 30..50 down",
          [a["bbox"] for a in inside_of(little[0][2])] == [[20.0, 30.0, 20.0,
                                                             20.0]],
          inside_of(little[0][2]))
    check("the box over the right edge of the window is not in the small "
          "one at all",
          len([a for a in coco["annotations"]
               if a["image_id"] == little[0][2]]) == 1, coco["annotations"])
    small_txt = [f for f in label_files(labels) if "small_tif" in f
                 and f.startswith(cut_name)]
    check("its YOLO line is a centre at 0.6, 0.8, size 0.4",
          small_txt and text_of(os.path.join(labels, small_txt[0])
                                ).splitlines() ==
          ["1 0.600000 0.800000 0.400000 0.400000"], small_txt)
    cut.undo()
    cut.common.setChecked(True)

    print()
    print("a layer in another system than the campaign")
    from osgeo import gdal
    wgs_path = os.path.join(root, "data", "wgs.tif")
    gdal.Warp(wgs_path, os.path.join(root, "data", "image.tif"),
              dstSRS="EPSG:4326")
    wgs = K.layer_of(wgs_path, show=False)
    layers_as({"wgs.tif": "image"}, "wgs.tif")
    check("the cutout is written", cut_here(cut), K.BOXES[-3:])
    cut_name = cut.written[-1][0]
    coco = read_json(coco_path)
    mine = [i for i in coco["images"] if i["cutout"] == cut_name]
    check("one image, from the layer in degrees", len(mine) == 1
          and mine[0]["file_name"].endswith("_image.tif")
          and "wgs" in mine[0]["file_name"], coco["images"])
    here = [a for a in coco["annotations"] if a["image_id"] == mine[0]["id"]]
    check("the boxes are there, not dropped for being in metres",
          len(here) == 3, here)
    w, h = mine[0]["width"], mine[0]["height"]
    land = [a for a in here if a["category_id"] == 2]
    near = lambda got, want: all(abs(g - v) < 0.03 for g, v in zip(got, want))
    check("and the box of class 2 is where it is on the ground: a fifth to "
          "two fifths across, three tenths to six tenths down",
          land and near([land[0]["bbox"][0] / w, land[0]["bbox"][1] / h,
                         land[0]["bbox"][2] / w, land[0]["bbox"][3] / h],
                        [0.2, 0.3, 0.2, 0.3]), land)
    wgs_txt = [f for f in label_files(labels) if f.startswith(cut_name)]
    check("with a YOLO file of three lines", len(wgs_txt) == 1 and len(
        text_of(os.path.join(labels, wgs_txt[0])).splitlines()) == 3,
          wgs_txt)
    cut.undo()
    panel.toggle_module(3)

    print()
    print("a campaign with no box")
    K.close_panel(panel)
    empty = K.new_panel()
    K.new_campaign(empty, os.path.join(root, "camp2"), image,
                   name="no boxes")
    empty.toggle_module(3)
    cut2 = empty.section
    cut2.pick_layers()
    out2 = os.path.join(root, "dataset2")
    cut2.folder_box.setText(out2)
    cut2.folder_changed()
    cut2.side.setValue(10.0)
    check("the cutout is written", cut_here(cut2), K.BOXES[-3:])
    check("and no detection file with it",
          not os.path.exists(os.path.join(out2, "boxes_coco.json"))
          and not os.path.exists(os.path.join(out2, "labels")),
          sorted(os.listdir(out2)))
    empty.toggle_module(3)
    K.close_panel(empty)

    print()
    print("a campaign with frames: only the ground inside them was read")
    # One frame of 10 m on the top left of the image, where the boxes are,
    # and a cutout over it and one beside it, over ground no frame covers.
    framed = K.new_panel()
    fc = K.new_campaign(framed, os.path.join(root, "camp3"), image,
                        tiled=True, name="framed")
    add_boxes(K.find_mine(fc.data["id"], "boxes"), [
        ("ANNA", 1, 2, X0 + 2, Y0 - 6, X0 + 4, Y0 - 3),
        ("ANNA", 1, 1, X0 + 12, Y0 - 16, X0 + 14, Y0 - 13)])
    drawing = K.annotate(framed)
    drawing.tile_side.setValue(10.0)
    drawing.create_tile(QgsPointXY(X0 + 5, Y0 - 5))
    check("one frame is placed and written",
          K.counts(os.path.join(root, "camp3", "annotation.gpkg"))
          .get("tiles") == 1,
          K.counts(os.path.join(root, "camp3", "annotation.gpkg")))
    framed.toggle_module(3)
    cut3 = framed.section
    check("Cutouts knows the campaign has frames", cut3.tiled)
    K.ANSWERS["CutoutSetup"] = only_the_image
    cut3.pick_layers()
    out3 = os.path.join(root, "dataset3")
    cut3.folder_box.setText(out3)
    cut3.folder_changed()
    cut3.side.setValue(10.0)
    check("the cutout over the frame is written", cut_here(cut3),
          K.BOXES[-3:])
    over_frame = cut3.written[-1][0]
    check("the cutout beside it, over ground no frame covers, is written too",
          cut3.export(cut3.square_at(QgsPointXY(X0 + 15, Y0 - 15)),
                      nominal=float(cut3.side.value())), K.BOXES[-3:])
    unread = cut3.written[-1][0]
    book3 = read_json(os.path.join(out3, "boxes_coco.json"))
    check("the image over the frame is in the book, with its box",
          [i["cutout"] for i in book3["images"]] == [over_frame]
          and len(book3["annotations"]) == 1
          and book3["annotations"][0]["category_id"] == 2, book3["images"])
    check("the image over ground nobody read is not among the images, and "
          "its box is not counted for the other",
          unread not in [i["cutout"] for i in book3["images"]])
    check("it is listed as unlabelled, with its cutout and why",
          [u["cutout"] for u in book3["unlabelled_images"]] == [unread]
          and book3["unlabelled_images"][0]["file_name"].endswith(
              "_image.tif")
          and book3["unlabelled_images"][0]["read_share"] == 0.0
          and "nobody read it" in book3["unlabelled_images"][0]["why"],
          book3.get("unlabelled_images"))
    labels3 = os.path.join(out3, "labels")
    txts3 = label_files(labels3)
    check("one label file, the one over the frame, and none for the other",
          len(txts3) == 1 and txts3[0].startswith(over_frame), txts3)
    check("the file over the frame holds its box",
          text_of(os.path.join(labels3, txts3[0])).splitlines()
          == ["1 0.300000 0.450000 0.200000 0.300000"], txts3)
    cut3.undo()
    book3 = read_json(os.path.join(out3, "boxes_coco.json"))
    check("undo of the one beside the frame takes it off the list",
          book3["unlabelled_images"] == [] and len(book3["images"]) == 1,
          book3)
    cut3.undo()
    book3 = read_json(os.path.join(out3, "boxes_coco.json"))
    check("and undo of the other takes out the image and its label file",
          book3["images"] == [] and label_files(labels3) == [],
          (book3, label_files(labels3)))
    framed.toggle_module(3)
    K.close_panel(framed)
finally:
    shutil.rmtree(root, ignore_errors=True)
K.finish()
