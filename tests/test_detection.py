"""Boxes as detection labels: the arithmetic, with nothing but Python.

rasterlabel/detection.py turns the boxes of a campaign into the pixels of the
images of a cutout, and builds the COCO book and the YOLO files. The cutting
itself, with a real campaign and real rasters, is tests/test_cutouts_boxes_qgis.py;
what is held here is the part that is only numbers:

  pixels    y runs down from the top edge, x across from the left; the pixel
            size comes from the image (width and height), so a layer on a grid
            of its own gets its own numbers
  clipped   a box over the edge is cut to it and says so; a box with less than
            a pixel left, or none, is not there
  classes   in the order of the codes, retired ones too, so an index never
            changes; a code the campaign does not list is added, not lost
  coco      bbox [x, y, w, h], area, category_id the code, ids from 1
  yolo      "index cx cy w h" as fractions of the image
  merge     a second cutout carries on the numbers; the same cutout again
            replaces itself; removing one takes its boxes with it
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purekit  # noqa: E402

rl = purekit.load("detection")
t = purekit.Checks()

CLASSES = [{"code": 3, "name": "rock"}, {"code": 1, "name": "mud"},
           {"code": 2, "name": "old", "retired": True}]
# an image of 100 x 50 pixels of half a metre: 50 m across, 25 m down
EXTENT = (1000.0, 2000.0, 1050.0, 2025.0)


def box(code, x0, y0, x1, y1, who="ANNA", p=1):
    return {"code": code, "operator": who, "pass": p, "tile_id": "",
            "extent": (x0, y0, x1, y1)}


print("one box, in pixels")
put = rl.det_pixels(box(1, 1010.0, 2005.0, 1020.0, 2010.0), EXTENT, 100, 50)
t.ok("x from the left, y down from the top: 20..40 across, 30..40 down",
     put == (20.0, 30.0, 40.0, 40.0, False), put)
put = rl.det_pixels(box(1, 1040.0, 2020.0, 1060.0, 2030.0), EXTENT, 100, 50)
t.ok("over the right and the top edge it is cut, and says so",
     put == (80.0, 0.0, 100.0, 10.0, True), put)
t.ok("outside altogether it is not there",
     rl.det_pixels(box(1, 1100.0, 2000.0, 1110.0, 2010.0), EXTENT, 100, 50)
     is None)
t.ok("less than a pixel left is not a box (half a pixel of a 0.5 m pixel)",
     rl.det_pixels(box(1, 1049.8, 2000.0, 1060.0, 2010.0), EXTENT, 100, 50)
     is None)
t.ok("a layer with a coarser pixel gets its own numbers: 50 x 25 pixels",
     rl.det_pixels(box(1, 1010.0, 2005.0, 1020.0, 2010.0), EXTENT, 50, 25)
     == (10.0, 15.0, 20.0, 20.0, False))
t.ok("an image with no size is nothing",
     rl.det_pixels(box(1, 1010.0, 2005.0, 1020.0, 2010.0), EXTENT, 0, 50)
     is None)

print()
print("the classes")
kinds = rl.det_classes(CLASSES, [box(9, 0, 0, 1, 1)])
t.ok("in the order of the codes, retired ones in, the strange code last",
     [(c["code"], c["name"], c["index"], c["retired"]) for c in kinds] ==
     [(1, "mud", 0, False), (2, "old", 1, True), (3, "rock", 2, False),
      (9, "code 9", 3, False)], kinds)

print()
print("the plan")
images = [{"file": "cut_0001_b_image.tif", "cutout": "cut_0001", "tag": "b",
           "width": 100, "height": 50, "extent": EXTENT},
          {"file": "cut_0001_a_image.tif", "cutout": "cut_0001", "tag": "a",
           "width": 50, "height": 25, "extent": EXTENT}]
boxes = [box(3, 1010.0, 2005.0, 1020.0, 2010.0),
         box(1, 1040.0, 2020.0, 1060.0, 2030.0, who="BRUNO"),
         box(1, 1100.0, 2000.0, 1110.0, 2010.0)]
plan = rl.det_plan(images, boxes, CLASSES)
coco = plan["coco"]
t.ok("the images are listed by file name, numbered from 1",
     [(i["id"], i["file_name"]) for i in coco["images"]] ==
     [(1, "cut_0001_a_image.tif"), (2, "cut_0001_b_image.tif")],
     coco["images"])
t.ok("two boxes inside, in each of the two images", plan["n_boxes"] == 4,
     plan["n_boxes"])
first = [a for a in coco["annotations"] if a["image_id"] == 2
         and a["category_id"] == 3][0]
t.ok("bbox is x, y, width, height, and the area is their product",
     first["bbox"] == [20.0, 30.0, 20.0, 10.0] and first["area"] == 200.0
     and first["iscrowd"] == 0, first)
t.ok("the reading is kept on the box",
     first["attributes"] == {"operator": "ANNA", "pass": 1, "clipped": False,
                             "tile_id": ""}, first)
t.ok("annotation numbers are 1 to 4",
     [a["id"] for a in coco["annotations"]] == [1, 2, 3, 4])
t.ok("the categories carry the codes and say which is retired",
     [(c["id"], c["name"], c["retired"]) for c in coco["categories"]] ==
     [(1, "mud", False), (2, "old", True), (3, "rock", False)],
     coco["categories"])
yolo = plan["yolo"]["cut_0001_b_image"].splitlines()
t.ok("YOLO: class 3 is index 2, centre 0.3, 0.7, size 0.2, 0.2",
     yolo[0] == "2 0.300000 0.700000 0.200000 0.200000", yolo)
t.ok("the cut box is centred on what is left of it: class 1 is index 0",
     yolo[1] == "0 0.900000 0.100000 0.200000 0.200000", yolo)
t.ok("one line per box inside, none for the box outside", len(yolo) == 2)
t.ok("classes.txt names the indices in order",
     plan["classes_txt"] == "mud\nold\nrock\n", plan["classes_txt"])
empty = rl.det_plan(images[:1], [], CLASSES)
t.ok("an image with no box has an empty file, so it is a negative sample",
     empty["yolo"]["cut_0001_b_image"] == "" and not empty["coco"]
     ["annotations"])
t.ok("with no frames given (a campaign without frames) nothing is unlabelled",
     plan["unlabelled"] == [] and coco["unlabelled_images"] == [])
t.ok("the book is plain JSON",
     json.loads(rl.det_coco_text(plan)) == json.loads(json.dumps(coco)))

print()
print("the book of the folder")
one = rl.det_merge(None, plan, "cut_0001")
t.ok("a first cutout makes the book", len(one["images"]) == 2
     and len(one["annotations"]) == 4)
second_images = [dict(images[0], file="cut_0002_a_image.tif",
                      cutout="cut_0002")]
plan2 = rl.det_plan(second_images, boxes[:1], CLASSES)
two = rl.det_merge(one, plan2, "cut_0002")
t.ok("the second carries the numbers on", [i["id"] for i in two["images"]]
     == [1, 2, 3] and [a["id"] for a in two["annotations"]]
     == [1, 2, 3, 4, 5], two)
t.ok("its box points at its image", two["annotations"][-1]["image_id"] == 3)
again = rl.det_merge(two, plan2, "cut_0002")
t.ok("the same cutout again replaces itself", len(again["images"]) == 3
     and len(again["annotations"]) == 5)
gone = rl.det_remove(again, "cut_0002")
t.ok("removing it takes its image and its box",
     [i["cutout"] for i in gone["images"]] == ["cut_0001"] * 2
     and len(gone["annotations"]) == 4)
t.ok("an unreadable book is an empty one",
     rl.det_remove("rubbish", "cut_0001")["images"] == []
     and len(rl.det_merge("rubbish", plan, "cut_0001")["images"]) == 2)
older = {"images": [], "annotations": [],
         "categories": [{"id": 7, "name": "gone", "supercategory": ""}]}
t.ok("a category an older cutout used stays in the book",
     7 in [c["id"] for c in rl.det_merge(older, plan, "cut_0001")
           ["categories"]])

print()
print("ground nobody read: the frames of the campaign")
# the image above is 1000..1050 across and 2000..2025 up; frames of 25 m
left = (1000.0, 2000.0, 1025.0, 2025.0)
right = (1025.0, 2000.0, 1050.0, 2025.0)
elsewhere = (3000.0, 3000.0, 3025.0, 3025.0)
t.ok("an image the frames cover is all read",
     rl.det_read_share(EXTENT, [left, right]) == 1.0)
t.ok("half covered is half read, and an image beside every frame none",
     abs(rl.det_read_share(EXTENT, [left]) - 0.5) < 1e-12
     and rl.det_read_share(EXTENT, [elsewhere]) == 0.0
     and rl.det_read_share(EXTENT, []) == 0.0)
t.ok("frames that touch add up and never count a piece twice",
     rl.det_read_share((1010.0, 2005.0, 1040.0, 2020.0), [left, right])
     == 1.0)
t.ok("an image with no ground is not read", rl.det_read_share(
    (1000.0, 2000.0, 1000.0, 2025.0), [left]) == 0.0)
over = dict(images[0], file="cut_0003_x_image.tif", cutout="cut_0003",
            tag="x", extent=(5000.0, 5000.0, 5050.0, 5025.0))
framed = rl.det_plan(images + [over], boxes, CLASSES, [left, right])
t.ok("an image over the frames is labelled as before: two images, four boxes",
     [i["file_name"] for i in framed["coco"]["images"]]
     == ["cut_0001_a_image.tif", "cut_0001_b_image.tif"]
     and framed["n_boxes"] == 4, framed["coco"]["images"])
t.ok("the image over ground nobody read has no label file at all",
     "cut_0003_x_image" not in framed["yolo"]
     and sorted(framed["yolo"]) == ["cut_0001_a_image", "cut_0001_b_image"],
     sorted(framed["yolo"]))
t.ok("and is listed as unlabelled, with its size, its cutout and why",
     [(u["file_name"], u["cutout"], u["layer"], u["width"], u["height"],
       u["read_share"]) for u in framed["unlabelled"]]
     == [("cut_0003_x_image.tif", "cut_0003", "x", 100, 50, 0.0)]
     and "nobody read it" in framed["unlabelled"][0]["why"],
     framed["unlabelled"])
t.ok("image numbers carry on with no gap where one was left out",
     [i["id"] for i in framed["coco"]["images"]] == [1, 2])
t.ok("the book says what the list is",
     "unlabelled_images" in framed["coco"]["info"])
t.ok("a campaign with frames and none placed reads nothing: every image is "
     "left out, no label file",
     rl.det_plan(images, boxes, CLASSES, [])["yolo"] == {}
     and len(rl.det_plan(images, boxes, CLASSES, [])["unlabelled"]) == 2)
t.ok("a frame that covers just under all of an image is not enough",
     len(rl.det_plan(images[:1], boxes, CLASSES, [
         (1000.0, 2000.0, 1050.0, 2025.0 - 0.2)])["unlabelled"]) == 1
     and len(rl.det_plan(images[:1], boxes, CLASSES, [
         (1000.0, 2000.0, 1050.0, 2025.0 - 0.1)])["unlabelled"]) == 0)
book = rl.det_merge(None, framed, "cut_0003")
t.ok("in the book of the folder it goes with its cutout", [
    u["cutout"] for u in book["unlabelled_images"]] == ["cut_0003"])
more = rl.det_merge(book, rl.det_plan(second_images, boxes[:1], CLASSES,
                                      [left, right]), "cut_0002")
t.ok("another cutout adds to the list and keeps it", [
    u["cutout"] for u in more["unlabelled_images"]] == ["cut_0003"]
    and [i["cutout"] for i in more["images"]]
    == ["cut_0001", "cut_0001", "cut_0002"])
t.ok("the same cutout again replaces its own entry",
     len(rl.det_merge(more, framed, "cut_0003")["unlabelled_images"]) == 1)
t.ok("undo takes the entry out of the list, and an older book with no list "
     "is still read",
     rl.det_remove(more, "cut_0003")["unlabelled_images"] == []
     and rl.det_remove({"images": [], "annotations": []},
                       "cut_0003")["unlabelled_images"] == []
     and rl.det_merge({"images": [], "annotations": [], "categories": []},
                      framed, "cut_0003")["unlabelled_images"][0]["cutout"]
     == "cut_0003")

t.done()
