"""rasterlabel.detection

The boxes of a campaign as labels for detection training: COCO for the whole
folder of cutouts, and YOLO, one text file per image.

Objects draws rectangles, Export writes them as polygons in the system of the
raster and nothing else reads them. A detector wants them in the pixels of the
picture it is shown, and the pictures of a dataset are the cutouts, so they
are turned into pixels here, cutout by cutout.

- a box is the rectangle of the polygon, cut to the cutout: one that crosses
  its edge is clipped and says so (attributes.clipped), and one with less than
  a pixel left on either side is left out;
- the boxes are turned into the system of the cutout first, when the campaign
  is in another one, so a layer cut in a different system still gets them;
- pixels are counted from the top left corner, x to the right and y down, on
  the grid of the image the box is written for, so a layer that kept its own
  grid gets its own numbers;
- COCO: bbox is [x, y, width, height] in pixels, category_id is the code of
  the class in the campaign, which never changes (a class is retired, never
  renumbered);
- YOLO: the line is "index cx cy w h", the last four as fractions of the
  width and the height of the image, and the index counts the classes of the
  campaign from 0 in the order of their codes, retired ones included, so that
  an index means the same thing in every export and stays the same when a
  class is added later. classes.txt names the indices.

An image over ground that was read gets a label file whether or not a box
falls in it, and an empty one reads as a picture with nothing in it. In a
campaign with frames the ground that was read is the ground inside them, as
for the ignore value of Whole: an image the frames do not cover is over
ground nobody looked at, and a file saying "nothing here" would be a negative
sample that is not one. It gets no label file and no entry among the images
of the COCO book; it is listed under unlabelled_images instead, so that
whoever trains can leave it out (a YOLO tool reads a picture with no label
file as a picture with nothing in it too, so the list is the way to tell).
A campaign without frames has no unread ground to tell apart, and every image
gets its file.

Nothing here writes a file: det_plan gives the texts, and the caller puts them
down the way it puts down its other books.
"""
import json

import math

from osgeo import ogr, osr

from .campaign import operator_word, pass_number
from .constants import NAME, VERSION

DET_COCO_NAME = "boxes_coco.json"
DET_LABELS_FOLDER = "labels"
DET_CLASSES_NAME = "classes.txt"
# less than this much of a side left after clipping is not a box any more
DET_MIN_SIDE_PX = 1.0
# an image is over read ground when the frames cover more than this share of
# it, as a frame is closed above 99.5 % painted
DET_READ_SHARE = 0.995
DET_UNLABELLED_KEY = "unlabelled_images"
DET_UNLABELLED_WHY = ("the ground is outside the frames of the campaign: "
                      "nobody read it, so no box here does not mean there is "
                      "nothing here")


def det_turn(package_srs, wkt):
    """A transformation from the system the boxes are stored in to the one in
    `wkt`, or None when there is nothing to turn: one of them is not known, or
    they are the same. Raises ValueError when they differ and cannot be
    joined."""
    if package_srs is None or not wkt:
        return None
    here = package_srs.Clone()
    there = osr.SpatialReference()
    try:
        if there.SetFromUserInput(str(wkt)) != 0:
            return None
    except Exception:
        return None
    for srs in (here, there):
        try:
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        except Exception:
            pass
    if here.IsSame(there):
        return None
    try:
        turn = osr.CoordinateTransformation(here, there)
    except Exception as err:
        raise ValueError("the system of the boxes cannot be turned into the "
                         "system of the cutout: %s" % err)
    if turn is None:
        raise ValueError("the system of the boxes cannot be turned into the "
                         "system of the cutout")
    return turn


def det_envelope(geom, turn):
    """(xmin, ymin, xmax, ymax) of a geometry, in the system `turn` leads to
    when there is one. The edges are cut into pieces before they are turned,
    so that a straight edge that becomes a curve is followed."""
    if turn is not None:
        geom = geom.Clone()
        x0, x1, y0, y1 = geom.GetEnvelope()
        longest = max(x1 - x0, y1 - y0)
        if longest > 0:
            geom.Segmentize(longest / 8.0)
        if geom.Transform(turn) != 0:
            raise ValueError("a box cannot be put in the system of the cutout")
    x0, x1, y0, y1 = geom.GetEnvelope()
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        raise ValueError("a box has no place in the system of the cutout")
    return x0, y0, x1, y1


def det_boxes(package, readings=None, wkt=None):
    """The boxes of a package: [{code, operator, pass, tile_id, extent}] with
    extent (xmin, ymin, xmax, ymax) in the system of the campaign, or in the
    one in `wkt` when that is given and is another. `readings` is a set of
    (operator, pass), or None for every reading. Raises when the boxes cannot
    be put in the system asked for: left as they were they would land
    nowhere on the cutout, and every file would say there is nothing in it."""
    out = []
    ds = ogr.Open(package)
    if ds is None:
        return out
    try:
        layer = ds.GetLayerByName("boxes")
        if layer is None:
            return out
        turn = det_turn(layer.GetSpatialRef(), wkt)
        defn = layer.GetLayerDefn()
        names = [defn.GetFieldDefn(i).GetName()
                 for i in range(defn.GetFieldCount())]

        def field(f, name):
            return f.GetField(name) if name in names else None

        for f in layer:
            geom = f.GetGeometryRef()
            if geom is None or geom.IsEmpty():
                continue
            who = operator_word(field(f, "operator"))
            when = pass_number(field(f, "pass_no"))
            if readings is not None and (who, when) not in readings:
                continue
            code = field(f, "class_code")
            out.append({"code": int(code) if code is not None else 0,
                        "operator": who, "pass": when,
                        "tile_id": field(f, "tile_id") or "",
                        "extent": det_envelope(geom, turn)})
    finally:
        ds = None
    return out


def det_frames(package, wkt=None):
    """The frames of a package as boxes (xmin, ymin, xmax, ymax), in the
    system of the campaign or, when `wkt` is another system, in that one: the
    rectangle that holds each frame. [] when the package holds none. Raises
    when the frames cannot be put in the system asked for, as det_boxes."""
    out = []
    ds = ogr.Open(package)
    if ds is None:
        return out
    try:
        layer = ds.GetLayerByName("tiles")
        if layer is None:
            return out
        turn = det_turn(layer.GetSpatialRef(), wkt)
        for f in layer:
            geom = f.GetGeometryRef()
            if geom is None or geom.IsEmpty():
                continue
            out.append(det_envelope(geom, turn))
    finally:
        ds = None
    return out


def det_read_share(extent, frames):
    """How much of the ground of an image, (xmin, ymin, xmax, ymax), lies
    inside the frames, 0 to 1. Frames may touch and never overlap, so the
    pieces of the image they cover are added up."""
    xmin, ymin, xmax, ymax = extent
    whole = (xmax - xmin) * (ymax - ymin)
    if not whole > 0:
        return 0.0
    got = 0.0
    for fx0, fy0, fx1, fy1 in frames:
        w = min(xmax, fx1) - max(xmin, fx0)
        h = min(ymax, fy1) - max(ymin, fy0)
        if w > 0 and h > 0:
            got += w * h
    return min(got / whole, 1.0)


def det_classes(classes, boxes):
    """The classes of the campaign in the order of their codes, each as
    {code, name, index, retired}, and after them a class for every code the
    boxes hold that the campaign does not list, so no box is lost."""
    out = []
    seen = set()
    for c in sorted(classes or [], key=lambda c: c["code"]):
        seen.add(int(c["code"]))
        out.append({"code": int(c["code"]), "name": c.get("name") or "",
                    "retired": bool(c.get("retired"))})
    for code in sorted({b["code"] for b in boxes} - seen):
        out.append({"code": code, "name": "code %d" % code, "retired": False})
    for i, c in enumerate(out):
        c["index"] = i
    return out


def det_pixels(box, extent, width, height):
    """A box in the pixels of an image whose edges are `extent` (xmin, ymin,
    xmax, ymax) and whose size is width by height: (x0, y0, x1, y1, clipped),
    or None when nothing of it is left."""
    xmin, ymin, xmax, ymax = extent
    if width <= 0 or height <= 0 or xmax <= xmin or ymax <= ymin:
        return None
    sx = (xmax - xmin) / float(width)
    sy = (ymax - ymin) / float(height)
    bx0, by0, bx1, by1 = box["extent"]
    x0, x1 = (bx0 - xmin) / sx, (bx1 - xmin) / sx
    y0, y1 = (ymax - by1) / sy, (ymax - by0) / sy
    cx0, cx1 = min(max(x0, 0.0), width), min(max(x1, 0.0), width)
    cy0, cy1 = min(max(y0, 0.0), height), min(max(y1, 0.0), height)
    if cx1 - cx0 < DET_MIN_SIDE_PX or cy1 - cy0 < DET_MIN_SIDE_PX:
        return None
    clipped = (cx0 != x0 or cx1 != x1 or cy0 != y0 or cy1 != y1)
    return cx0, cy0, cx1, cy1, clipped


def det_plan(images, boxes, classes, frames=None):
    """What to write. `images` is a list of {file, cutout, tag, extent,
    width, height}. `frames` is the frames of the campaign as boxes
    (det_frames), or None for a campaign without frames: with them, an image
    the frames do not cover is over ground nobody read and is left without a
    label file and without a place among the images of the book. Returns
    {coco: dict, yolo: {file stem: text}, classes_txt: text, n_boxes: int,
    unlabelled: [the images left out, with the share the frames cover]}."""
    kinds = det_classes(classes, boxes)
    index = {c["code"]: c["index"] for c in kinds}
    coco_images, coco_boxes, yolo, unlabelled = [], [], {}, []
    n = 0
    for image in sorted(images, key=lambda i: i["file"]):
        if frames is not None:
            share = det_read_share(image["extent"], frames)
            if not share > DET_READ_SHARE:
                unlabelled.append({
                    "file_name": image["file"],
                    "width": int(image["width"]),
                    "height": int(image["height"]),
                    "cutout": image["cutout"], "layer": image["tag"],
                    "read_share": round(share, 4),
                    "why": DET_UNLABELLED_WHY})
                continue
        n += 1
        coco_images.append({"id": n, "file_name": image["file"],
                            "width": int(image["width"]),
                            "height": int(image["height"]),
                            "cutout": image["cutout"], "layer": image["tag"]})
        lines = []
        for box in boxes:
            put = det_pixels(box, image["extent"], image["width"],
                             image["height"])
            if put is None:
                continue
            x0, y0, x1, y1, clipped = put
            w, h = x1 - x0, y1 - y0
            coco_boxes.append({
                "id": len(coco_boxes) + 1, "image_id": n,
                "category_id": box["code"],
                "bbox": [round(x0, 2), round(y0, 2), round(w, 2),
                         round(h, 2)],
                "area": round(w * h, 2), "iscrowd": 0,
                "attributes": {"operator": box["operator"],
                               "pass": box["pass"], "clipped": clipped,
                               "tile_id": box["tile_id"]}})
            lines.append("%d %.6f %.6f %.6f %.6f" % (
                index[box["code"]], (x0 + x1) / 2.0 / image["width"],
                (y0 + y1) / 2.0 / image["height"],
                w / float(image["width"]), h / float(image["height"])))
        yolo[image["file"].rsplit(".", 1)[0]] = \
            "".join(l + "\n" for l in lines)
    coco = {
        "info": {"description": "boxes drawn in %s, in the pixels of the "
                                "cutouts" % NAME,
                 "version": VERSION, "bbox": "x, y, width, height from the "
                 "top left corner of the image",
                 DET_UNLABELLED_KEY: "images over ground outside the frames "
                 "of the campaign, which nobody read: they have no boxes and "
                 "no label file, and are not pictures with nothing in them. "
                 "Leave them out of training."},
        "images": coco_images, "annotations": coco_boxes,
        "categories": [{"id": c["code"], "name": c["name"],
                        "supercategory": "", "retired": c["retired"]}
                       for c in kinds],
        DET_UNLABELLED_KEY: unlabelled}
    return {"coco": coco, "yolo": yolo, "n_boxes": len(coco_boxes),
            "unlabelled": unlabelled,
            "classes_txt": "".join("%s\n" % c["name"] for c in kinds)}


def det_coco_text(plan):
    return json.dumps(plan["coco"], indent=1) + "\n"


def det_remove(book, cutout):
    """The COCO book without the images of a cutout and their boxes."""
    if not isinstance(book, dict):
        return {"images": [], "annotations": [], "categories": [],
                DET_UNLABELLED_KEY: []}
    gone = {i.get("id") for i in book.get("images") or []
            if i.get("cutout") == cutout}
    out = dict(book)
    out["images"] = [i for i in book.get("images") or []
                     if i.get("id") not in gone]
    out["annotations"] = [a for a in book.get("annotations") or []
                          if a.get("image_id") not in gone]
    out[DET_UNLABELLED_KEY] = [i for i in book.get(DET_UNLABELLED_KEY) or []
                               if i.get("cutout") != cutout]
    return out


def det_merge(book, plan, cutout):
    """The book of the folder with the cutout of `plan` added to it, in place
    of an earlier one of the same name. Each cutout keeps the boxes the
    campaign held when it was cut, like its other files; numbers carry on from
    the highest in the book, so none is used twice. The categories are the
    campaign's as they stand now, and a category an older cutout still uses
    stays."""
    out = det_remove(book, cutout)
    new = plan["coco"]
    top_image = max([i.get("id") or 0 for i in out["images"]] or [0])
    top_box = max([a.get("id") or 0 for a in out["annotations"]] or [0])
    ids = {}
    for image in new["images"]:
        top_image += 1
        ids[image["id"]] = top_image
        out["images"].append(dict(image, id=top_image))
    for box in new["annotations"]:
        top_box += 1
        out["annotations"].append(dict(box, id=top_box,
                                       image_id=ids[box["image_id"]]))
    out[DET_UNLABELLED_KEY] = (out.get(DET_UNLABELLED_KEY) or []) \
        + list(new.get(DET_UNLABELLED_KEY) or [])
    kept = {c["id"]: c for c in (book or {}).get("categories") or []
            } if isinstance(book, dict) else {}
    kept.update({c["id"]: c for c in new["categories"]})
    out["categories"] = [kept[k] for k in sorted(kept)]
    out["info"] = new["info"]
    return out
