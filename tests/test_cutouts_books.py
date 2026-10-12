"""The books of a cutouts folder: what it was cut from, what was being cut
when the session ended, and what its catalogue says.

Real files out, read back. QGIS is faked, see correctkit.py.

  The layers of a folder are written into it (layers.json) and the next
  session cuts the same ones, as the same, on the same grid, whatever is
  ticked on the map and in whatever order the Layers panel has them today.
  Before, they were chosen afresh at every session from the tree, and the
  same folder was fed by different layers on different days. A change is said
  once, before the cut it concerns, and kept.
  A cutout being written when the process dies, which is a crash and not an
  exception, leaves files that cutouts.csv does not list. A note in the
  folder says one was in the making, and the next session takes its files
  away and takes its name again.
  sampler.json, shapes.json and the STAC items are written whole or not at
  all.
  The STAC item says the date of the image when a layer says it, and is
  honest about it when none does; the classes are labels; a layer on a grid
  of its own says so; the footprint runs counter-clockwise; the classes of
  the style are listed whether or not there is an ignore value.

Needs the GDAL Python bindings.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import json
import os
import shutil
import sys
import tempfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                                 # noqa: E402
from osgeo import gdal, osr                                        # noqa: E402
import correctkit as K                                             # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "fixtures", "stac"))
import minischema                                                  # noqa: E402

gdal.UseExceptions()
g, check = K.g, K.check


class Transform(object):
    """QgsCoordinateTransform, by PROJ, between the kit's systems, which are
    known by their codes: what the catalogue needs to put a cutout in
    degrees."""
    def __init__(self, a, b, *rest):
        ends = []
        for crs in (a, b):
            one = osr.SpatialReference()
            one.ImportFromEPSG(int(crs.authid().split(":")[1]))
            one.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            ends.append(one)
        self.t = osr.CoordinateTransformation(*ends)

    def transform(self, p):
        x, y, _ = self.t.TransformPoint(p.x(), p.y())
        return K.Point(x, y)


g["QgsCoordinateTransform"] = Transform

root = tempfile.mkdtemp(prefix="rl_cutouts_books_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
data = os.path.join(root, "data")
os.makedirs(data)
GT = (500000.0, 0.5, 0.0, 4100000.0, 0.0, -0.5)
NX, NY = 120, 80
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)


def write(path, arrays, gt=GT, metadata=None):
    h, w = arrays[0].shape
    ds = gdal.GetDriverByName("GTiff").Create(path, w, h, len(arrays),
                                              gdal.GDT_Byte)
    ds.SetGeoTransform(gt)
    ds.SetProjection(srs.ExportToWkt())
    for i, a in enumerate(arrays):
        ds.GetRasterBand(i + 1).WriteArray(a)
    if metadata:
        ds.SetMetadata(metadata)
    ds = None


rng = np.random.default_rng(11)
rgb = [rng.integers(30, 220, (NY, NX)).astype(np.uint8) for _ in range(3)]
ortho = os.path.join(data, "ortho.tif")
write(ortho, rgb)
dated = os.path.join(data, "dated.tif")
write(dated, rgb, metadata={"TIFFTAG_DATETIME": "2025:03:14 10:22:31"})
second = os.path.join(data, "second.tif")
write(second, [rng.integers(0, 255, (NY, NX)).astype(np.uint8)])
coarse = os.path.join(data, "coarse.tif")
write(coarse, [rng.integers(0, 255, (NY // 2, NX // 2)).astype(np.uint8)
               for _ in range(3)], gt=(500000.0, 1.0, 0.0, 4100000.0, 0.0, -1.0))
truth_map = np.ones((NY, NX), np.uint8)
truth_map[:, 40:] = 4
truth = os.path.join(data, "truth.tif")
write(truth, [truth_map])
STYLE = [K.Paletted.Class(1, "#ff0000", "sand"),
         K.Paletted.Class(4, "#0000ff", "sea")]


def load(*layers):
    """The project holds exactly these layers, each (path, name, ticked)."""
    K.LOADED.clear()
    K.TREE.clear()
    for path, name, ticked in layers:
        style = K.Paletted(None, 1, STYLE) if name == "truth" else None
        K.add_layer(K.Layer(path, name, style), ticked=ticked)


def open_cutouts(folder):
    """A session: the panel made, Cutouts opened on the folder it remembers.
    The folder is in the settings first, as for a person who was cutting
    into it yesterday."""
    g["write_setting"](g["SETTINGS_ROOT"] + "/cutouts/folder", folder)
    panel = g["Panel"]()
    panel.toggle_module(3)
    cut = panel.section
    if cut is None:
        print("Cutouts did not open:", K.BOXES[-3:], K.SAID[-3:])
    return panel, cut


def choose(roles, grid=None, tags=None):
    """Answer the Layers window: role by layer name, the grid layer, and the
    names the files are given."""
    def answer(dialog):
        for layer, role, band, rgb_, tag, holder, shape in dialog.rows:
            role.setCurrentText(roles.get(layer.name(), "ignore"))
            if tags and layer.name() in tags:
                tag.setText(tags[layer.name()])
        if grid is not None:
            dialog.grid_from.setCurrentIndex(
                dialog.grid_from.findText(grid))
        return 1
    K.ANSWERS["CutoutSetup"] = answer


def layers_file(folder):
    path = os.path.join(folder, "layers.json")
    return json.load(open(path, encoding="utf-8")) \
        if os.path.exists(path) else None


def listing(folder):
    return K.everything_under(folder)


SQUARE = K.Rect(500010.0, 4099970.0, 500030.0, 4099990.0)
SQUARE_2 = K.Rect(500050.2, 4099950.2, 500070.2, 4099970.2)

try:
    # ---------------------------------------------------------- the layers
    print("the layers of a folder, chosen by hand")
    out = os.path.join(root, "dataset")
    load((ortho, "ortho", True), (second, "second", True),
         (truth, "truth", True))
    panel, cut = open_cutouts(out)
    check("with nothing remembered the tree decides: the three, in its order",
          [s["tag"] for s in cut.sources] == ["ortho", "second", "truth"],
          [s["tag"] for s in cut.sources])
    check("and a folder that does not exist yet has no layers.json",
          layers_file(out) is None)
    choose({"truth": "classes", "ortho": "image"}, grid="truth",
           tags={"truth": "gt"})
    cut.pick_layers()
    check("the window's answer: truth first, as gt, and ortho",
          [(s["tag"], s["role"]) for s in cut.sources]
          == [("gt", "classes"), ("ortho", "image")],
          [(s["tag"], s["role"]) for s in cut.sources])
    check("a folder that is not there yet is not made for a note",
          not os.path.isdir(out))
    check("the first cutout is written", cut.export(SQUARE, nominal=20.0),
          K.BOXES[-3:])
    book = layers_file(out)
    check("layers.json is in the folder now", book is not None)
    book = book or {"layers": [], "left_out": []}
    check("it names the files the layers come from, in order, the grid "
          "first, by their way from the folder (a path of this machine is "
          "not shared with the dataset)",
          [e["source"] for e in book["layers"]]
          == ["../data/truth.tif", "../data/ortho.tif"]
          and book["grid"] == "../data/truth.tif", book["layers"])
    kept = cut.read_layers()
    check("and read back they are the files themselves",
          [os.path.normcase(e["source"]) for e in kept["layers"]]
          == [os.path.normcase(truth), os.path.normcase(ortho)]
          and os.path.normcase(kept["grid"]) == os.path.normcase(truth),
          kept["layers"])
    check("with role, tag and band or bands",
          [(e["role"], e["tag"]) for e in book["layers"]]
          == [("classes", "gt"), ("image", "ortho")]
          and book["layers"][0]["band"] == 1
          and book["layers"][1]["rgb"] == [1, 2, 3], book["layers"])
    check("no temporary file is left in the folder",
          not [f for f in listing(out) if f.endswith(".tmp")], listing(out))
    check("no note of a cutout in the making either",
          "cutting.pending" not in listing(out), listing(out))
    panel.close_module()

    print()
    print("the next day: other layers ticked, the Layers panel upside down")
    load((truth, "truth", False), (second, "second", True),
         (ortho, "ortho", True))
    panel, cut = open_cutouts(out)
    check("the folder's layers, as they were, with the grid first",
          [(s["tag"], s["role"]) for s in cut.sources]
          == [("gt", "classes"), ("ortho", "image")],
          [(s["tag"], s["role"]) for s in cut.sources])
    check("the one that is not among them stays out, ticked as it is",
          "second" not in [s["tag"] for s in cut.sources])
    check("the layer unticked on the map is cut all the same: it is the "
          "folder's", "gt" in [s["tag"] for s in cut.sources])
    told = len(K.SAID)
    check("the second cutout is written", cut.export(SQUARE_2, nominal=20.0))
    check("and nothing is said: it is the same dataset",
          not [m for m in K.SAID[told:] if "other layers" in m], K.SAID[told:])
    rows = list(csv.DictReader(open(os.path.join(out, "cutouts.csv"),
                                    encoding="utf-8")))
    check("both cutouts have the same layers, in the same roles",
          sorted((r["cutout"], r["tag"], r["role"]) for r in rows)
          == [("cut_0001", "gt", "classes"), ("cut_0001", "ortho", "image"),
              ("cut_0002", "gt", "classes"), ("cut_0002", "ortho", "image")],
          rows)
    panel.close_module()

    print()
    print("a change of layers is said before the cut, once, and kept")
    load((truth, "truth", True), (second, "second", True),
         (ortho, "ortho", True))
    panel, cut = open_cutouts(out)
    choose({"truth": "classes", "ortho": "image", "second": "image"},
           grid="ortho")
    cut.pick_layers()
    told = len(K.SAID)
    check("the third cutout is written", cut.export(SQUARE, nominal=20.0))
    said = [m for m in K.SAID[told:] if "other layers" in m]
    check("the message bar says the folder was cut from other layers",
          len(said) == 1 and "gt as classes" in said[0], K.SAID[told:])
    book = layers_file(out)
    check("layers.json has the new choice now",
          [e["tag"] for e in book["layers"]] == ["ortho", "second", "gt"],
          book)
    told = len(K.SAID)
    check("the fourth cutout is written", cut.export(SQUARE_2, nominal=20.0))
    check("and the same change is not said again",
          not [m for m in K.SAID[told:] if "other layers" in m])
    panel.close_module()

    print()
    print("a folder with nothing to compare with")
    plain = os.path.join(root, "plain")
    os.makedirs(plain)
    load((ortho, "ortho", True))
    panel, cut = open_cutouts(plain)
    told = len(K.SAID)
    check("a first cutout into a folder with no record", cut.export(
        SQUARE, nominal=20.0))
    check("says nothing", not [m for m in K.SAID[told:] if "other" in m])
    check("and writes the record", layers_file(plain) is not None)
    panel.close_module()

    print()
    print("choosing another folder takes its layers")
    load((truth, "truth", True), (second, "second", True),
         (ortho, "ortho", True))
    panel, cut = open_cutouts(plain)
    check("the folder with ortho alone cuts ortho alone",
          [s["tag"] for s in cut.sources] == ["ortho"],
          [s["tag"] for s in cut.sources])
    fresh = os.path.join(root, "fresh")
    cut.folder_box.setText(fresh)
    cut.folder_changed()
    check("a folder with no record leaves the layers as they are",
          [s["tag"] for s in cut.sources] == ["ortho"])
    cut.folder_box.setText(out)
    cut.folder_changed()
    check("one with a record gives its layers, grid first",
          [s["tag"] for s in cut.sources] == ["ortho", "second", "gt"],
          [s["tag"] for s in cut.sources])
    panel.close_module()

    print()
    print("two layers of one file")
    twice = os.path.join(root, "twice")
    load((ortho, "ortho", True))
    panel, cut = open_cutouts(twice)
    check("cut once", cut.export(SQUARE, nominal=20.0))
    panel.close_module()
    load((ortho, "ortho", True), (ortho, "ortho copy", True))
    panel, cut = open_cutouts(twice)
    check("the folder's layer is cut once, not under one name twice",
          [s["tag"] for s in cut.sources] == ["ortho"],
          [s["tag"] for s in cut.sources])
    panel.close_module()

    print()
    print("a layers.json that is damaged, and one that names files not here")
    broken = os.path.join(root, "broken")
    os.makedirs(broken)
    with open(os.path.join(broken, "layers.json"), "w") as f:
        f.write('{"layers": [{"source": ')
    load((ortho, "ortho", True), (truth, "truth", True))
    panel, cut = open_cutouts(broken)
    check("is read as nothing: the tree decides",
          [s["tag"] for s in cut.sources] == ["ortho", "truth"],
          [s["tag"] for s in cut.sources])
    panel.close_module()
    missing = os.path.join(root, "missing")
    os.makedirs(missing)
    with open(os.path.join(missing, "layers.json"), "w") as f:
        json.dump({"layers": [
            {"source": os.path.join(data, "gone.tif"), "role": "image",
             "tag": "gone", "rgb": [1, 2, 3]},
            {"source": truth, "role": "image", "tag": "gt", "rgb": [9, 9, 9],
             "driver": "BMP"}]}, f)
    panel, cut = open_cutouts(missing)
    check("a layer that is no longer in the project is passed over, the "
          "one that is keeps its tag, and the one the folder does not know "
          "is not cut",
          [s["tag"] for s in cut.sources] == ["gt"],
          [s["tag"] for s in cut.sources])
    gt_source = cut.sources[0]
    check("a band that does not exist and a format we do not write are "
          "not taken", gt_source["rgb"] != [9, 9, 9]
          and gt_source.get("driver") is None, gt_source)
    panel.close_module()

    # ---------------------------------------------------- a crash in the middle
    print()
    print("a cutout being written when the process dies")
    crash = os.path.join(root, "crash")
    load((ortho, "ortho", True), (truth, "truth", True))
    panel, cut = open_cutouts(crash)
    check("a first cutout is written whole", cut.export(SQUARE, nominal=20.0))
    before = listing(crash)
    check("with no note left behind", "cutting.pending" not in before, before)
    original = cut.cut_classes

    def dies(*a, **k):
        original(*a, **k)               # the classes land on the disk
        raise KeyboardInterrupt("the process is killed here")

    cut.cut_classes = dies
    try:
        cut.export(SQUARE_2, nominal=20.0)
        stopped = False
    except KeyboardInterrupt:
        stopped = True
    check("the second one is stopped in the middle (not an exception: "
          "nothing cleans up after a crash)", stopped)
    after = listing(crash)
    left = sorted(set(after) - set(before))
    check("its files are on the disk", any(
        f.startswith("cut_0002_") for f in after), after)
    check("cutouts.csv does not list it",
          {r["cutout"] for r in csv.DictReader(open(
              os.path.join(crash, "cutouts.csv"), encoding="utf-8"))}
          == {"cut_0001"})
    check("but a note in the folder says it was in the making",
          "cutting.pending" in after
          and json.load(open(os.path.join(crash, "cutting.pending"),
                             encoding="utf-8"))["cutout"] == "cut_0002", left)
    panel.close_module()

    print("   ... and the next session")
    panel, cut = open_cutouts(crash)
    after = listing(crash)
    check("the files of the cutout that was not finished are gone",
          not [f for f in after if f.startswith("cut_0002")], after)
    check("so is the note", "cutting.pending" not in after, after)
    check("the first cutout is untouched",
          [f for f in after if f.startswith("cut_0001")]
          == [f for f in before if f.startswith("cut_0001")])
    check("and it is counted: one", cut.count == 1, cut.count)
    check("the message bar says what was taken away", any(
        "cut_0002 was being written" in m for m in K.SAID), K.SAID[-3:])
    check("the name is free again: the next cutout is cut_0002",
          cut.export(SQUARE_2, nominal=20.0) and os.path.exists(os.path.join(
              crash, "cut_0002_ortho_image.tif")), listing(crash))
    panel.close_module()

    print()
    print("a note left behind by a cutout that did finish")
    with open(os.path.join(crash, "cutting.pending"), "w") as f:
        json.dump({"cutout": "cut_0001", "when": "2025-01-01T00:00:00"}, f)
    mine = listing(crash)
    panel, cut = open_cutouts(crash)
    after = listing(crash)
    check("only the note goes: the cutout is in cutouts.csv, so it is whole",
          [f for f in after if f != "cutting.pending"]
          == [f for f in mine if f != "cutting.pending"]
          and "cutting.pending" not in after, set(mine) ^ set(after))
    panel.close_module()

    print()
    print("a manifest that cannot be read says nothing, and nothing is removed")
    # cutouts.csv held open or damaged: it cannot be told whether the cutout
    # the note names is listed, and a cutout that is listed must never go
    panel, cut = open_cutouts(crash)
    mine = [f for f in listing(crash) if f != "cutting.pending"]
    csv_path = os.path.join(crash, "cutouts.csv")
    parked = csv_path + ".parked"
    os.replace(csv_path, parked)
    os.mkdir(csv_path)              # exists, and cannot be opened as a file
    try:
        with open(os.path.join(crash, "cutting.pending"), "w") as f:
            json.dump({"cutout": "cut_0001", "when": "2025-01-01T00:00:00"}, f)
        cut.settle_interrupted()
        after = listing(crash)
    finally:
        os.rmdir(csv_path)
        os.replace(parked, csv_path)
    check("the files of the cutout are all still there",
          all(f in after for f in mine if f != "cutouts.csv"),
          set(mine) - set(after))
    check("the note goes", "cutting.pending" not in after, after)
    panel.close_module()

    print()
    print("a cutout that raises an exception leaves nothing, as before")
    load((ortho, "ortho", True), (truth, "truth", True))
    boom = os.path.join(root, "boom")
    panel, cut = open_cutouts(boom)
    original = cut.cut_classes

    def fails_(*a, **k):
        original(*a, **k)
        raise ValueError("a layer refuses")

    cut.cut_classes = fails_
    check("refused", cut.export(SQUARE, nominal=20.0) is False)
    left = [f for f in listing(boom) if f.startswith("cut_")
            or f == "cutting.pending"]
    check("no file, no note", not left, left)
    panel.close_module()

    print()
    print("QGIS spells the folder of the project with slashes")
    load((ortho, "ortho", True))
    panel, cut = open_cutouts(os.path.join(root, "slashes"))
    kept_home = K.HOME[0]
    K.HOME[0] = kept_home.replace(os.sep, "/")
    default = cut.default_folder()
    K.HOME[0] = kept_home
    check("the default folder is spelled one way, not with both",
          not ("/" in default and "\\" in default)
          and os.path.normcase(default) == os.path.normcase(os.path.join(
              kept_home, "cutouts")), default)
    panel.close_module()

    # --------------------------------------------------------- the catalogue
    print()
    print("the STAC item")
    cat = os.path.join(root, "catalog")
    load((ortho, "ortho", True), (coarse, "coarse", True),
         (truth, "truth", True))
    panel, cut = open_cutouts(cat)
    cut.stac.setChecked(True)
    cut.common.setChecked(False)
    choose({"ortho": "image", "coarse": "image", "truth": "classes"},
           grid="ortho")
    cut.pick_layers()
    check("a cutout with a layer on a grid of its own", cut.export(
        SQUARE, nominal=None), K.BOXES[-3:])
    item = json.load(open(os.path.join(cat, "stac", "cut_0001.json"),
                          encoding="utf-8"))
    props, assets = item["properties"], item["assets"]
    check("no layer says when it was taken, so there is no datetime to "
          "claim: null, with a start and an end",
          props.get("datetime") is None and props.get("start_datetime")
          and props.get("end_datetime"), props)
    check("and the item says what those two are",
          "moment of the cutting" in props.get("rasterlabel:datetime_is", ""),
          props)
    check("the cutting has its own date, created",
          props.get("created") == props.get("start_datetime"), props)
    check("the classes are labels, and data",
          assets["truth_classes"]["roles"] == ["data", "labels"],
          assets["truth_classes"]["roles"])
    check("the image is data only", assets["ortho_image"]["roles"] == ["data"])
    check("the item says the grid of the first layer: 40 by 40 at 0.5 m",
          props["proj:shape"] == [40, 40] and props["proj:transform"][0] == 0.5,
          (props.get("proj:shape"), props.get("proj:transform")))
    own = assets["coarse_image"]
    check("the layer on a grid of its own says so: 20 by 20 at 1 m",
          own.get("proj:shape") == [20, 20]
          and own.get("proj:transform", [0])[0] == 1.0, own)
    check("with its own box, in the units of the system",
          own.get("proj:bbox") is not None and abs(
              own["proj:bbox"][2] - own["proj:bbox"][0] - 20.0) < 1e-9, own)
    check("the layers on the grid of the item say nothing of their own",
          "proj:shape" not in assets["ortho_image"]
          and "proj:shape" not in assets["truth_classes"])
    check("the item holds against the projection extension, v1.1.0",
          not minischema.validate(item, "projection"),
          minischema.validate(item, "projection"))
    ring = item["geometry"]["coordinates"][0]
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))
    check("the footprint runs counter-clockwise, as GeoJSON asks",
          len(ring) == 5 and area > 0, ring)
    classes = assets["truth_classes"].get("classification:classes") or []
    check("the classes of the style are listed with no ignore value: "
          "values, names, titles",
          [(c["value"], c["title"]) for c in classes]
          == [(1, "sand"), (4, "sea")], classes)
    check("none of them is nodata", not any(c.get("nodata") for c in classes))
    note = json.load(open(os.path.join(cat, "sampler.json"), encoding="utf-8"))
    check("sampler.json counts the pieces: 2 shapes of 1 cutout each, not "
          "the four files",
          sorted((s["height"], s["width"], s["n"])
                 for s in note["shapes_found"]) == [(20, 20, 1), (40, 40, 1)],
          note["shapes_found"])
    check("and lists the classes", [c["name"] for c in note["classes"]]
          == ["sand", "sea"], note["classes"])
    panel.close_module()

    print()
    print("a layer that says when it was taken")
    when = os.path.join(root, "when")
    load((dated, "dated", True))
    panel, cut = open_cutouts(when)
    cut.stac.setChecked(True)
    check("cut", cut.export(SQUARE, nominal=20.0))
    props = json.load(open(os.path.join(when, "stac", "cut_0001.json"),
                           encoding="utf-8"))["properties"]
    check("the datetime of the item is that moment, not the cutting",
          props.get("datetime") == "2025-03-14T10:22:31Z"
          and "start_datetime" not in props, props)
    check("the cutting is the date it was created",
          props.get("created") and props["created"] != props["datetime"])
    panel.close_module()
finally:
    shutil.rmtree(g.get("long_path", str)(root), ignore_errors=True)

sys.exit(K.finish())
