"""The ignore value: what a mask holds where nobody painted.

A mask has always held 0 where nobody painted. A loss that should leave
those pixels out has to be told which value they are, and three kinds of
ground are 0 for three reasons: outside every frame nobody looked; inside a
frame nobody painted, which in a "paint everything in the frame" campaign
is the class "none of these"; and where the readings of a consensus painted
and did not agree. The Whole raster can now write an ignore value (255 by
default) everywhere, or only outside the frames, and Cutouts can turn the
padding and a map's own nodata into it. It is recorded as GDAL nodata, in
the GeoTIFF metadata, in cutouts.csv, sampler.json and the STAC items.

Real GDAL, real GeoPackages, the whole program read from the built single
file with QGIS faked (correctkit with RL_KIT_REAL_GDAL). The fixture is a
100 x 100 grid of 1 m pixels in UTM 33 N, written in strips
of 16 rows so that the strips are exercised:

- one frame, t001, columns 0-59, not closed;
- ANNA in pass 1: class 1 on columns 0-29, class 2 on 30-44, class 3 on
  80-89 (outside the frame), a point of class 4 at column 70, row 50;
- unpainted: inside the frame columns 45-59, 1500 px; outside 60-79 and
  90-99, 3000 px.

A-M are the Whole raster, N1-N11 Cutouts. The default
is checked first and last: nothing chosen, nothing changes.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import json
import os
import re
import shutil
import sys
import tempfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import numpy as np                                                 # noqa: E402
from osgeo import gdal, ogr, osr                                   # noqa: E402
import correctkit as K                                             # noqa: E402
import impact as F                                                 # noqa: E402

g, check = K.g, K.check
g["STRIP_ROWS"] = 16
root = tempfile.mkdtemp(prefix="rl_ignore_index_")
W = H = 100
OX, OY = 1000.0, 2000.0
GRID = {"epsg": 32633, "origin": (OX, OY), "pixel": 1.0, "size": (W, H)}
GT = (OX, 1.0, 0.0, OY, 0.0, -1.0)
ANNA, BRUNO = ("ANNA", 1), ("BRUNO", 1)
CLASSES = [{"code": 1, "name": "mud", "colour": "#d95f02"},
           {"code": 2, "name": "crust", "colour": "#1b9e77"},
           {"code": 3, "name": "rill", "colour": "#7570b3"},
           {"code": 4, "name": "vent", "colour": "#e7298a"}]
COLOURS = {1: (200, 10, 0), 2: (0, 200, 10), 3: (10, 0, 200),
           4: (200, 200, 0), 255: (1, 2, 3)}
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)
WKT = srs.ExportToWkt()


def cols(c0, c1, r0=0, r1=H):
    return F.px_box(GRID, c0, r0, c1, r1)


FRAMES = [("t001", cols(0, 60), False)]
P1 = [("polygons", ANNA, 1, cols(0, 30)),
      ("polygons", ANNA, 2, cols(30, 45)),
      ("polygons", ANNA, 3, cols(80, 90), None),
      ("points", ANNA, 4, cols(70, 71, 50, 51), None)]


def campaign(name, marks, frames=FRAMES):
    folder = os.path.join(root, name)
    package = F.make_campaign(folder, GRID, frames, marks, classes=CLASSES,
                              name=name)
    return folder, package


def raster(path, bands=3, value=100, pixel=1.0, size=(W, H),
           dtype=gdal.GDT_Byte, array=None, nodata=None, origin=(OX, OY)):
    ds = gdal.GetDriverByName("GTiff").Create(path, size[0], size[1], bands,
                                              dtype)
    ds.SetGeoTransform((origin[0], pixel, 0.0, origin[1], 0.0, -pixel))
    ds.SetProjection(WKT)
    for b in range(bands):
        band = ds.GetRasterBand(b + 1)
        if array is not None:
            band.WriteArray(array)
        else:
            band.Fill(value + 20 * b)
        if nodata is not None:
            band.SetNoDataValue(nodata)
    ds = None
    return path


def counts(a):
    v, n = np.unique(a, return_counts=True)
    return {int(x): int(c) for x, c in zip(v.tolist(), n.tolist())}


ORTHO = raster(os.path.join(root, "ortho.tif"))
OUT = os.path.join(root, "whole")
os.makedirs(OUT)


def whole(package, choice, mode=None, ignore=None, kinds=("mask",),
          points_in=False, tag="x", driver="GTiff", ext=".tif", tally=None):
    """paint_whole as the Whole button hands it a recipe, without a layer:
    the file names, the arrays and what the files say about themselves."""
    outputs = [(k, os.path.join(OUT, "%s_%s%s" % (tag, k, ext
                                                 if k != "votes" else ".tif")),
                driver if k != "votes" else "GTiff") for k in kinds]
    src = gdal.Open(ORTHO)
    recipe = {"ds": src, "scale": 1, "rgb": [1, 2, 3],
              "limits": [(0.0, 255.0)] * 3, "alpha": 45,
              "colours": COLOURS, "outputs": outputs, "package": package,
              "want_lines": True, "want_points": True, "want_boxes": True,
              "points_in_mask": points_in, "dot_px": 1, "reading": choice}
    if mode is not None:
        recipe["unlabelled"] = mode
        recipe["ignore"] = ignore
    if tally is not None:
        recipe["tally"] = tally
    try:
        g["paint_whole"](recipe)
    finally:
        src = None
    out = {}
    for k, path, _ in outputs:
        ds = gdal.Open(path)
        band = ds.GetRasterBand(1)
        out[k] = {"array": ds.ReadAsArray(), "meta": ds.GetMetadata() or {},
                  "type": band.DataType, "nodata": band.GetNoDataValue(),
                  "path": path}
        band = None
        ds = None
    return out


folder1, P1_PACKAGE = campaign("p1", P1)
choices = g["reading_choices"](g["readings_in"](P1_PACKAGE))
ALL = choices[0]

try:
    print("A. nothing chosen: 0 where nobody painted, as always")
    before = whole(P1_PACKAGE, ALL, tag="before")["mask"]
    a = whole(P1_PACKAGE, ALL, "zero", None, tag="A")["mask"]
    m = a["array"]
    check("{0: 4500, 1: 3000, 2: 1500, 3: 1000}",
          counts(m) == {0: 4500, 1: 3000, 2: 1500, 3: 1000}, counts(m))
    check("one byte a pixel, and no nodata declared",
          a["type"] == gdal.GDT_Byte and a["nodata"] is None,
          (a["type"], a["nodata"]))
    check("it says 0 is unlabelled, and names no ignore value",
          a["meta"].get("RASTERLABEL_UNLABELLED") == "zero"
          and "RASTERLABEL_IGNORE_INDEX" not in a["meta"], a["meta"])
    check("the same pixels as a recipe that says nothing of it (the build "
          "before this one)", np.array_equal(m, before["array"])
          and before["nodata"] is None)
    hand = np.zeros((H, W), np.uint8)
    hand[:, 0:30], hand[:, 30:45], hand[:, 80:90] = 1, 2, 3
    check("and the pixels worked out by hand", np.array_equal(m, hand))

    print()
    print("B. the ignore value everywhere, 255")
    b = whole(P1_PACKAGE, ALL, "ignore", 255, tag="B")["mask"]
    m = b["array"]
    check("{255: 4500, 1: 3000, 2: 1500, 3: 1000}",
          counts(m) == {255: 4500, 1: 3000, 2: 1500, 3: 1000}, counts(m))
    check("still one byte, not two", b["type"] == gdal.GDT_Byte,
          gdal.GetDataTypeName(b["type"]))
    check("declared as the nodata", b["nodata"] == 255, b["nodata"])
    check("and said in the metadata",
          b["meta"].get("RASTERLABEL_IGNORE_INDEX") == "255"
          and b["meta"].get("RASTERLABEL_UNLABELLED") == "ignore"
          and "255 where nobody painted"
          in b["meta"].get("RASTERLABEL_UNLABELLED_RULE", ""), b["meta"])
    check("no 0 is left", int((m == 0).sum()) == 0)
    check("the reading tags are still there",
          b["meta"].get("RASTERLABEL_READING_MODE") == "all")

    print()
    print("C. 0 in the frames, the ignore value outside")
    c = whole(P1_PACKAGE, ALL, "frames", 255, tag="C")["mask"]
    m = c["array"]
    check("{0: 1500, 255: 3000, 1: 3000, 2: 1500, 3: 1000}",
          counts(m) == {0: 1500, 255: 3000, 1: 3000, 2: 1500, 3: 1000},
          counts(m))
    check("inside the frame, unpainted, is 0: 'none of these'",
          (m[:, 45:60] == 0).all())
    check("outside every frame, unpainted, is 255", (m[:, 60:80] == 255).all()
          and (m[:, 90:100] == 255).all())
    check("a polygon traced outside the frames keeps its class",
          (m[:, 80:90] == 3).all())
    check("the rule says both", c["meta"].get("RASTERLABEL_UNLABELLED")
          == "frames" and c["nodata"] == 255
          and "outside every frame" in c["meta"].get(
              "RASTERLABEL_UNLABELLED_RULE", ""), c["meta"])

    print()
    print("D. with the points in the mask: a sparse mask of points")
    d = whole(P1_PACKAGE, ALL, "ignore", 255, points_in=True, tag="D")["mask"]
    m = d["array"]
    check("the point is class 4, the ground round it 255",
          counts(m) == {255: 4499, 1: 3000, 2: 1500, 3: 1000, 4: 1}
          and int(m[50, 70]) == 4, counts(m))

    print()
    print("E, F. a negative ignore value, and one past a byte")
    e = whole(P1_PACKAGE, ALL, "ignore", -100, tag="E")["mask"]
    check("-100: 16 signed bits", e["type"] == gdal.GDT_Int16,
          gdal.GetDataTypeName(e["type"]))
    check("4500 pixels of -100, declared as nodata",
          int((e["array"] == -100).sum()) == 4500 and e["nodata"] == -100,
          (counts(e["array"]), e["nodata"]))
    f = whole(P1_PACKAGE, ALL, "ignore", 300, tag="F")["mask"]
    check("300: 16 bits unsigned", f["type"] == gdal.GDT_UInt16,
          gdal.GetDataTypeName(f["type"]))
    check("4500 pixels of 300", int((f["array"] == 300).sum()) == 4500
          and int((f["array"] == 1).sum()) == 3000, counts(f["array"]))

    print()
    print("G. the ignore value is never painted")
    pa = whole(P1_PACKAGE, ALL, "zero", None, kinds=("painted",),
               tag="Gzero")["painted"]
    pb = whole(P1_PACKAGE, ALL, "ignore", 255, kinds=("painted",),
               tag="Gign")["painted"]
    check("the painted image of A is the painted image of B",
          np.array_equal(pa["array"], pb["array"]))
    check("and a painted image carries no ignore value",
          "RASTERLABEL_IGNORE_INDEX" not in pb["meta"])

    print()
    print("H. which values are refused, and why")
    refusal = g["ignore_refusal"]
    for value, codes, refused in ((0, {1, 2, 3}, True), (1, (), True),
                                  (254, (), True), (255, {1, 2, 3}, False),
                                  (300, {300}, True), (70000, (), True),
                                  (-1, (), False), (-32768, (), False),
                                  (65535, (), False), (2.5, (), True),
                                  ("a", (), True)):
        said = refusal(value, codes)
        check("%r with codes %s: %s" % (value, sorted(codes) if codes else
                                        "none", "refused" if refused
                                        else "taken"),
              bool(said) == refused, said)
    check("0 points to the other choice",
          "0, as before" in refusal(0, ()))
    check("a code in use is named", "300" in refusal(300, {300}))

    print()
    print("I. a class that already uses 255: refused before any file")
    folder2, p2 = campaign("p2", P1 + [("polygons", ANNA, 255,
                                        cols(90, 95), None)])
    target = os.path.join(OUT, "I_mask.tif")
    try:
        whole(p2, ALL, "ignore", 255, tag="I")
        check("refused", False)
    except ValueError as err:
        check("refused, naming 255", "255" in str(err), str(err))
    check("and no mask is on disk", not os.path.exists(target))
    m = whole(p2, ALL, "ignore", 300, tag="I300")["mask"]["array"]
    check("another value goes through, and 255 stays the class it is",
          int((m == 255).sum()) == 500 and int((m == 300).sum()) == 4000,
          counts(m))

    print()
    print("J. a mark with no class code")
    folder3, p3 = campaign("p3", P1 + [("polygons", ANNA, 1, cols(95, 100),
                                        None)])
    ds = ogr.Open(p3, 1)
    lyr = ds.GetLayerByName("polygons")
    for feat in lyr:
        if feat.GetGeometryRef().GetEnvelope()[0] >= OX + 95 - 1e-9:
            feat.SetFieldNull("class_code")
            lyr.SetFeature(feat)
    lyr = None
    ds = None
    try:
        whole(p3, ALL, "ignore", 255, tag="J")
        check("refused with the ignore value", False)
    except ValueError as err:
        check("refused with the ignore value: 1 mark has no class code",
              "1 mark" in str(err) and "no class code" in str(err), str(err))
    check("and nothing was written",
          not os.path.exists(os.path.join(OUT, "J_mask.tif")))
    m = whole(p3, ALL, "zero", None, tag="Jzero")["mask"]["array"]
    check("with 0 it writes, as it always did", int((m == 0).sum()) == 4500,
          counts(m))

    print()
    print("K. a consensus: where the readings do not agree")
    k_frames = [("t001", cols(0, 60), True)]
    folder4, p4 = campaign("p4", [("polygons", ANNA, 1, cols(0, 30)),
                                  ("polygons", ANNA, 2, cols(30, 60)),
                                  ("polygons", BRUNO, 1, cols(0, 40)),
                                  ("polygons", BRUNO, 2, cols(40, 60))],
                           k_frames)
    cons = [ch for ch in g["reading_choices"](g["readings_in"](p4))
            if ch["mode"] == "consensus"][0]
    kz = whole(p4, cons, "zero", None, kinds=("mask", "votes"), tag="Kz")
    check("0: {1: 3000, 2: 2000, 0: 5000}", counts(kz["mask"]["array"])
          == {1: 3000, 2: 2000, 0: 5000}, counts(kz["mask"]["array"]))
    ki = whole(p4, cons, "ignore", 255, kinds=("mask", "votes"), tag="Ki")
    check("255: {1: 3000, 2: 2000, 255: 5000}", counts(ki["mask"]["array"])
          == {1: 3000, 2: 2000, 255: 5000}, counts(ki["mask"]["array"]))
    vds = gdal.Open(ki["votes"]["path"])
    votes, painted = (vds.GetRasterBand(1).ReadAsArray(),
                      vds.GetRasterBand(2).ReadAsArray())
    vds = None
    check("the votes say where: no majority at column 35, both painted it",
          int(votes[0, 35]) == 0 and int(painted[0, 35]) == 2,
          (votes[0, 35], painted[0, 35]))
    check("the votes carry no ignore value",
          ki["votes"]["nodata"] is None
          and "RASTERLABEL_IGNORE_INDEX" not in ki["votes"]["meta"])
    check("the rule says the disagreement too", "do not agree" in ki["mask"][
        "meta"].get("RASTERLABEL_UNLABELLED_RULE", ""), ki["mask"]["meta"])
    kf = whole(p4, cons, "frames", 255, kinds=("mask", "votes"), tag="Kf")
    m = kf["mask"]["array"]
    check("frames: {1: 3000, 2: 2000, 255: 5000}, and no 0",
          counts(m) == {1: 3000, 2: 2000, 255: 5000}, counts(m))
    check("the disputed columns 30-39 inside the frame are 255, not 0",
          (m[:, 30:40] == 255).all())

    print()
    print("L. the type of the mask")
    mt = g["mask_type"]
    for args, want in (((3, 0, None), gdal.GDT_Byte),
                       ((3, 0, 255), gdal.GDT_Byte),
                       ((254, 0, 255), gdal.GDT_Byte),
                       ((3, 0, 300), gdal.GDT_UInt16),
                       ((3, 0, -100), gdal.GDT_Int16),
                       ((300, 0, None), gdal.GDT_UInt16),
                       ((255, 0, None), gdal.GDT_UInt16),
                       ((255, 0, 255), gdal.GDT_UInt16),
                       ((3, 0, 70000), gdal.GDT_Int32),
                       ((40000, 0, -1), gdal.GDT_Int32)):
        check("mask_type%s is %s" % (args, gdal.GetDataTypeName(want)),
              mt(*args) == want, gdal.GetDataTypeName(mt(*args)))

    print()
    print("M. the word in the file name")
    tag = g["unlabelled_tag"]
    for args, want in ((("zero", None), ""), (("ignore", 255), "ign255"),
                       (("frames", 255), "ign255out"),
                       (("ignore", -100), "ignm100"),
                       (("zero", 255), "")):
        check("%s gives %r" % (args, want), tag(*args) == want, tag(*args))
    meta = g["unlabelled_metadata"]
    check("the metadata of 0 names no ignore value",
          "RASTERLABEL_IGNORE_INDEX" not in meta("zero", None))
    check("the metadata of frames does",
          meta("frames", 300)["RASTERLABEL_IGNORE_INDEX"] == "300")

    print()
    print("the parts: the stencil of the frames, settle, the tally")
    st = g["Stencil"](P1_PACKAGE, "tiles", None, WKT, value=1)
    inside = st.burn_into(GT, W, H, WKT)
    st.close()
    check("the frames burn 1 inside, 0 outside, whoever drew them",
          int(inside.sum()) == 6000 and (inside[:, :60] == 1).all())
    st = g["Stencil"](p3, "polygons", "class_code", WKT)
    check("a stencil knows the codes its marks carry, and the uncoded",
          st.codes == {0, 1, 2, 3} and st.uncoded == 1, (st.codes,
                                                         st.uncoded))
    st.close()
    settle = g["settle_unlabelled"]
    cls_ = np.array([[0, 1, 0, 0]], np.uint8)
    inside_ = np.array([[True, True, False, True]])
    disputed_ = np.array([[False, False, False, True]])
    check("settle: ignore everywhere", settle(cls_, "ignore", 255, np.uint8)
          .tolist() == [[255, 1, 255, 255]])
    check("settle: frames, with a disputed pixel inside",
          settle(cls_, "frames", 255, np.uint8, inside_, disputed_).tolist()
          == [[0, 1, 255, 255]])
    check("settle: 0 is left as it is", settle(cls_, "zero", 255, np.uint8)
          .tolist() == [[0, 1, 0, 0]])
    tally = {}
    whole(P1_PACKAGE, ALL, "ignore", 255, tag="T", tally=tally)
    check("the tally is what was written, value by value",
          tally.get("mask") == {255: 4500, 1: 3000, 2: 1500, 3: 1000},
          tally)
    folder5, p5 = campaign("p5", P1, frames=[])
    try:
        whole(p5, ALL, "frames", 255, tag="nofr")
        check("frames with no frames is refused", False)
    except ValueError as err:
        check("frames with no frames is refused", "no frames" in str(err),
              str(err))
    check("before any file", not os.path.exists(
        os.path.join(OUT, "nofr_mask.tif")))

    print()
    print("a mask as PNG keeps the value in its pixels")
    png = whole(P1_PACKAGE, ALL, "ignore", 255, tag="png", driver="PNG",
                ext=".png")["mask"]
    check("255 where nobody painted", counts(png["array"]).get(255) == 4500,
          counts(png["array"]))
    check("no scratch file left", not [n for n in os.listdir(OUT)
                                       if n.startswith("png_") and
                                       n.endswith(".part.tif")])

    print()
    print("per-reading closure, for the note of frames")
    shares = g["reading_shares"](p4)
    fc = g["frames_closed_for"]
    check("one frame, closed by both readings: closed for each, and for "
          "their consensus", fc(shares, {"readings": [ANNA]}) == (1, 1)
          and fc(shares, cons) == (1, 1))
    shared = os.path.join(root, "shared")
    sp = F.make_shared_campaign(shared)
    sh = g["reading_shares"](sp)
    check("the shared campaign: t002 is closed for ANNA, not for BRUNO",
          fc(sh, {"readings": [ANNA]}) == (3, 2)
          and fc(sh, {"readings": [BRUNO]}) == (3, 1), (
              fc(sh, {"readings": [ANNA]}), fc(sh, {"readings": [BRUNO]})))
    check("and for both together only t001 is",
          fc(sh, {"readings": [ANNA, BRUNO]}) == (3, 1))
    # a paired design: each frame read by two of four people. Only the
    # readings that covered a frame count in it, for a consensus; "all
    # readings together" still wants every one of them.
    CARLA, DINO = ("CARLA", 1), ("DINO", 1)
    four = [ANNA, BRUNO, CARLA, DINO]
    paired = {"f1": {ANNA: 1.0, BRUNO: 1.0}, "f2": {CARLA: 1.0, DINO: 1.0},
              "f3": {ANNA: 1.0, BRUNO: 0.4}, "f4": {}}
    vote = {"mode": "consensus", "readings": four}
    check("a paired design: a frame its two readers closed is closed for the "
          "consensus; one a reader left open, or nobody read, is not",
          fc(paired, vote) == (4, 2), fc(paired, vote))
    check("and for every reading together none is",
          fc(paired, {"mode": "all", "readings": four}) == (4, 0))

    # ---------------------------------------------------------- the dialog
    print()
    print("the Whole raster window: Where nobody painted")

    class Book:
        def __init__(self, folder, package, data):
            self.folder, self.package_path, self.data = folder, package, data
            self.stem = data.get("name", "x")

        def active_classes(self):
            return [c for c in self.data["classes"] if not c.get("retired")]

    def book(folder, package):
        with open(os.path.join(folder, "campaign.json"),
                  encoding="utf-8") as fh:
            return Book(folder, package, json.load(fh))

    class Keeper(K.QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.kept = {}

        def setting(self, key, default, kind=str):
            return self.kept.get(key, default)

        def keep_setting(self, key, value):
            self.kept[key] = value

    K.LOADED.clear()
    K.add_layer(K.Layer(ORTHO, "ortho"))
    keeper = Keeper()
    win = g["WholeRaster"](keeper, book(folder1, P1_PACKAGE), OUT)
    items = [win.unlabelled.itemData(i) for i in range(win.unlabelled.count())]
    check("three choices, 0 as before first", items == ["zero", "ignore",
                                                        "frames"], items)
    check("0 is chosen on a first use", win.chosen_unlabelled() == "zero")
    check("the ignore value is 255, and greyed while 0 is chosen",
          win.ignore_value.value() == 255
          and not win.ignore_value.isEnabled())
    check("the box is as wide as every number box",
          win.ignore_value.maximumWidth() == g["FIELD_W"])
    check("the note of 0 names who trains 0 as a class",
          "Segmentation Gym" in win.unlabelled_note.text())
    r = win.result()
    # The card counts every reading at full size, so Whole leaves it off on
    # a first use and stays as quick as it was; ticked once, it is
    # remembered.
    check("the result: 0, no ignore value, and no card on a first use",
          r["unlabelled"] == "zero" and r["ignore"] is None
          and "card" not in r["kinds"]
          and not win.want["card"].isChecked(),
          (r["unlabelled"], r["ignore"], r["kinds"]))
    win.want["card"].setChecked(True)
    check("ticked, the card is a kind", "card" in win.result()["kinds"])
    win.unlabelled.setCurrentIndex(1)
    check("the ignore value is open to change once it is chosen",
          win.ignore_value.isEnabled())
    note = win.unlabelled_note.text()
    check("its note warns of samgeo and Deepness",
          "samgeo" in note and "Deepness" in note and "255" in note, note)
    win.unlabelled.setCurrentIndex(2)
    note = win.unlabelled_note.text()
    check("frames: the note counts the frames not closed for the reading",
          "1 frame, 0 of them closed" in note and "not closed" in note, note)
    win.ignore_value.setValue(-100)
    win.shape.setCurrentIndex([w[1] for w in g["WHOLE_FORMATS"]]
                              .index("PNG"))
    check("a negative value as PNG: the mask goes as a GeoTIFF",
          "GeoTIFF" in win.unlabelled_note.text(), win.unlabelled_note.text())
    win.want["mask"].setChecked(False)
    check("without the mask the block is greyed",
          not win.unlabelled.isEnabled() and not win.ignore_value.isEnabled())
    check("and the result is 0", win.result()["unlabelled"] == "zero")
    win.want["mask"].setChecked(True)
    win.ignore_value.setValue(3)
    shown = len(K.BOXES)
    win.accept()
    check("a class code is refused with a warning, and the window stays",
          len(K.BOXES) == shown + 1 and K.BOXES[-1][0] == "warning"
          and "1 to 254" in K.BOXES[-1][1] and win.result() is not None
          and not keeper.kept, K.BOXES[-1:])
    win.ignore_value.setValue(255)
    win.unlabelled.setCurrentIndex(1)
    win.accept()
    check("a good value is kept on this machine, and so is the card",
          keeper.kept.get("whole_unlabelled") == "ignore"
          and keeper.kept.get("whole_ignore") == 255
          and keeper.kept.get("whole_card") is True, keeper.kept)
    again = g["WholeRaster"](keeper, book(folder1, P1_PACKAGE), OUT)
    check("and given back the next time",
          again.chosen_unlabelled() == "ignore"
          and again.ignore_value.value() == 255)
    bare = g["WholeRaster"](keeper, book(folder5, p5), OUT)
    item = bare.unlabelled.model().item(2)
    check("a campaign with no frames greys the frames choice, saying why",
          not item.isEnabled()
          and item.toolTip() == "the campaign has no frames")
    bare.unlabelled.setCurrentIndex(2)
    check("and it cannot be chosen by the back door",
          bare.chosen_unlabelled() == "zero")
    # Frames mode counts the frames closed for the reading chosen. In a
    # consensus the readings that count in a frame are the ones that covered
    # it: with each frame read by two of four people, a frame both closed is
    # closed for the consensus, and it used to ask all four of every frame.
    CARLA, DINO = ("CARLA", 1), ("DINO", 1)
    pair_frames = [("t001", cols(0, 30), False), ("t002", cols(30, 60), False)]
    pf, pp = campaign("paired", [
        ("polygons", ANNA, 1, cols(0, 30)),
        ("polygons", BRUNO, 1, cols(0, 30)),
        ("polygons", CARLA, 1, cols(30, 60)),
        ("polygons", DINO, 1, cols(30, 60))], frames=pair_frames)
    pair = g["WholeRaster"](keeper, book(pf, pp), OUT)
    modes = [c["mode"] for c in pair.choices]
    pair.reading.setCurrentIndex(modes.index("consensus"))
    pair.unlabelled.setCurrentIndex(2)
    note = pair.unlabelled_note.text()
    check("frames, a consensus of four readers who each read two frames and "
          "closed them: 2 frames, 2 closed, by the readings that read it",
          "2 frames, 2 of them closed by the readings that read it" in note
          and "not closed" not in note, note)
    pair.reading.setCurrentIndex(0)
    note = pair.unlabelled_note.text()
    check("all four together ask every reader of every frame: none is closed",
          "2 frames, 0 of them closed by every reading chosen" in note
          and "2 frames are not closed" in note, note)
    pf, pp = campaign("paired_open", [
        ("polygons", ANNA, 1, cols(0, 30)),
        ("polygons", BRUNO, 1, cols(0, 15)),
        ("polygons", CARLA, 1, cols(30, 60)),
        ("polygons", DINO, 1, cols(30, 60))], frames=pair_frames)
    pair = g["WholeRaster"](keeper, book(pf, pp), OUT)
    pair.reading.setCurrentIndex([c["mode"] for c in pair.choices]
                                 .index("consensus"))
    pair.unlabelled.setCurrentIndex(2)
    note = pair.unlabelled_note.text()
    check("a frame one of its two readers left half open is not closed for "
          "the consensus; the other still is",
          "2 frames, 1 of them closed by the readings that read it" in note
          and "1 frame is not closed" in note, note)
    check("the mask tick box says where the ignore value comes from",
          "ignore value" in win.want["mask"].toolTip())
    # The rasters are listed by name, and the first used to be the one
    # offered: after Compare, the map of the disagreement, which then came
    # out as "the raster" of the Whole, its 899 x 900 pixels and all.
    report = K.Layer(ORTHO, "aaa agreement disagreement", lid="report_map")
    report.setCustomProperty(g["REPORT_KEY"], "agreement")
    K.add_layer(report)
    offered = g["WholeRaster"](keeper, book(folder1, P1_PACKAGE), OUT)
    check("a map of a report is not the raster offered",
          offered.raster.count() >= 2
          and offered.raster.currentData() != "report_map",
          [offered.raster.itemText(i) for i in range(offered.raster.count())])
    check("and Cutouts starts it as ignore, by the same test",
          g["is_report_layer"](report)
          and not g["is_report_layer"](K.Layer(ORTHO, "ortho")))
    K.LOADED.pop("report_map", None)
    K.TREE.pop("report_map", None)

    # The manifest holds the reference raster by its way from the campaign's
    # folder. The window used to read it as it stood, from nowhere, never found
    # the campaign's own raster, and offered the first by name.
    other = raster(os.path.join(root, "aaa_other.tif"))
    K.add_layer(K.Layer(other, "aaa other", lid="aaa_other"))
    held = book(folder1, P1_PACKAGE)
    held.data["grid"] = dict(held.data["grid"], reference_raster=os.path.relpath(
        ORTHO, folder1).replace(os.sep, "/"))
    offered = g["WholeRaster"](keeper, held, OUT)
    names = [offered.raster.itemText(i) for i in range(offered.raster.count())]
    check("the window starts on the campaign's raster, found by its way from "
          "the folder", offered.raster.currentText() == "ortho",
          (offered.raster.currentText(), names))
    K.LOADED.pop("aaa_other", None)
    K.TREE.pop("aaa_other", None)

    # ------------------------------------------------------------- Cutouts
    print()
    print("Cutouts: the setting")

    class Turn:
        """UTM 33 N to degrees, near enough for a footprint."""
        def __init__(self, *a, **k): pass

        def transform(self, p):
            return K.Point(9.0 + (p.x() - 400000.0) / 111320.0,
                           37.0 + (p.y() - 4100000.0) / 110540.0)

        def transformBoundingBox(self, r):
            return r

    g["QgsCoordinateTransform"] = Turn
    K.HOME[0] = os.path.join(root, "project")
    os.makedirs(K.HOME[0])
    K.LOADED.clear()
    mask_a = whole(P1_PACKAGE, ALL, "zero", None, tag="maskA")["mask"]["path"]
    mask_b = whole(P1_PACKAGE, ALL, "ignore", 255, tag="maskB")["mask"][
        "path"]
    STYLE = [K.Paletted.Class(c["code"], c["colour"], c["name"])
             for c in CLASSES] + [K.Paletted.Class(255, "#000000", "ignore")]
    panel = g["Panel"]()
    panel.toggle_module(3)
    cut = panel.section
    check("Cutouts opens", type(cut).__name__ == "CutoutsSection")
    check("'unlabelled as ignore' is there, off", not cut.ignore_on.isChecked())
    check("its value is 255, greyed while it is off",
          cut.ignore_value.value() == 255 and not cut.ignore_value.isEnabled())
    check("between 'same size for all' and 'STAC catalogue'",
          cut.written_how.layout().indexOf(cut.row_ignore)
          == cut.written_how.layout().indexOf(cut.same_size) + 1
          and cut.written_how.layout().indexOf(cut.stac)
          == cut.written_how.layout().indexOf(cut.row_ignore) + 1)
    check("the tip warns of samgeo and Deepness",
          "samgeo" in cut.ignore_on.toolTip())
    check("tab focus for the box, strong for the number",
          cut.ignore_on.focusPolicy() == K.QtCore.Qt.FocusPolicy.TabFocus
          and cut.ignore_value.focusPolicy()
          == K.QtCore.Qt.FocusPolicy.StrongFocus)
    check("the number box is FIELD_W wide",
          cut.ignore_value.maximumWidth() == g["FIELD_W"])

    def use(*layers):
        K.LOADED.clear()
        K.TREE.clear()
        for layer in layers:
            K.add_layer(layer)
        cut.sources = cut.guess(list(layers))

    def into(name):
        folder = os.path.join(root, "cut_" + name)
        cut.folder_box.setText(folder)
        cut.folder_changed()
        return folder

    def click(c0, r0, side=40.0):
        """A click of the fixed side whose square starts at column c0 and
        row r0 of the 1 m grid. The square is centred on the click, rounded
        to whole pixels: its centre a hair before the middle lands it there
        on a grid of 1 m and of 2 m alike, and the rectangle clicked spans a
        few metres so that part of it is on the raster."""
        x = OX + c0 + side / 2.0 - 0.5
        y = OY - (r0 + side / 2.0 - 0.5)
        return cut.export(K.Rect(x - 3, y - 3, x + 3, y + 3), nominal=side)

    def read(path):
        ds = gdal.Open(path)
        band = ds.GetRasterBand(1)
        out = (ds.ReadAsArray(), band.DataType, band.GetNoDataValue(),
               ds.GetMetadata() or {})
        band = None
        ds = None
        return out

    def last(folder, suffix):
        names = sorted(n for n in os.listdir(folder) if n.endswith(suffix))
        return os.path.join(folder, names[-1]) if names else None

    def setting(on, value=255):
        cut.ignore_value.setValue(value)
        cut.ignore_on.setChecked(on)

    print()
    print("N1. a mask written with 255, cut past the edge of the raster")
    setting(False)
    use(K.Layer(mask_b, "mask", K.Paletted(None, 1, STYLE)))
    n1 = into("n1")
    check("cut", click(80, 0), K.SAID[-2:])
    tif = last(n1, "_mask_classes.tif")
    a, kind, nd, meta = read(tif)
    check("{3: 400, 255: 1200}: its own 255 and the padding",
          counts(a) == {3: 400, 255: 1200}, counts(a))
    check("one byte, nodata 255", kind == gdal.GDT_Byte and nd == 255,
          (kind, nd))
    check("the ignore value travels inside the cutout",
          meta.get("RASTERLABEL_IGNORE_INDEX") == "255"
          and meta.get("RASTERLABEL_READING_MODE") == "all", meta)
    rows = list(csv.DictReader(open(os.path.join(n1, "cutouts.csv"),
                                    encoding="utf-8")))
    check("cutouts.csv says it, in a column of its own",
          rows[-1]["ignore_index"] == "255", rows[-1])

    print()
    print("N8. sampler.json: the labels")
    note = json.load(open(os.path.join(n1, "sampler.json"), encoding="utf-8"))
    labels = note.get("labels") or {}
    check("ignore_index 255", labels.get("ignore_index") == 255, labels)
    check("and the loss told so", "ignore_index=255" in labels.get(
        "pytorch", "") and "ignore_index=255" in labels.get("torchgeo", "")
          and "ignore_index=255" in labels.get("mmsegmentation", ""), labels)
    check("255 is not a class, whatever the style calls it",
          255 not in [c["code"] for c in note["classes"]], note["classes"])
    check("num_classes is the highest code plus one",
          "num_classes=5" in labels.get("torchgeo", ""), labels)
    check("it is not a foreground, it says",
          "samgeo" in labels.get("meaning", ""), labels.get("meaning"))
    check("by layer", labels.get("ignore_index_by_layer") == {"mask": 255})

    print()
    print("N9. the STAC item")
    item = json.load(open(last(os.path.join(n1, "stac"), "_0001.json")
                          or os.path.join(n1, "stac", "cut_0001.json"),
                          encoding="utf-8"))
    asset = item["assets"]["mask_classes"]
    check("rasterlabel:ignore_index", item["properties"].get(
        "rasterlabel:ignore_index") == {"mask": 255}, item["properties"])
    check("raster:bands nodata 255", asset["raster:bands"][0].get("nodata")
          == 255 and asset["raster:bands"][0]["data_type"] == "uint8", asset)
    entry = [c for c in asset.get("classification:classes", [])
             if c["value"] == 255]
    check("a classification entry for 255, ignore, nodata",
          entry and entry[0]["name"] == "ignore"
          and entry[0]["nodata"] is True, asset.get("classification:classes"))
    check("the raster and classification extensions, not the label one",
          g["RASTER_EXT"] in item["stac_extensions"]
          and g["CLASSIFICATION_EXT"] in item["stac_extensions"]
          and g["LABEL_EXT"] not in item["stac_extensions"],
          item["stac_extensions"])
    check("every class name fits the pattern of the extension",
          all(re.match(r"^[0-9A-Za-z\-_]+$", c["name"])
              for c in asset["classification:classes"]))

    print()
    print("N11. the picture: the ignore value is see-through")
    png_path = last(n1, "_mask_classes.png")
    pic = gdal.Open(png_path).ReadAsArray()
    check("alpha 0 at every ignore pixel, 255 at every class pixel",
          (pic[3][a == 255] == 0).all() and (pic[3][a == 3] == 255).all())

    print()
    print("N2, N3. a mask written with 0, the setting on and off")
    use(K.Layer(mask_a, "mask", K.Paletted(None, 1, STYLE)))
    setting(True, 255)
    n2 = into("n2")
    check("cut columns 40-79", click(40, 0))
    a = read(last(n2, "_mask_classes.tif"))[0]
    check("{2: 200, 255: 1400}: its 0 is 'nobody painted'",
          counts(a) == {2: 200, 255: 1400}, counts(a))
    check("cut columns 80-119", click(80, 0))
    a, kind, nd, meta = read(last(n2, "_mask_classes.tif"))
    check("{3: 400, 255: 1200}", counts(a) == {3: 400, 255: 1200}, counts(a))
    check("and the cutout says it now holds 255",
          nd == 255 and meta.get("RASTERLABEL_IGNORE_INDEX") == "255"
          and meta.get("RASTERLABEL_UNLABELLED") == "ignore", meta)
    setting(False)
    n3 = into("n3")
    check("off: cut columns 80-119", click(80, 0))
    a, kind, nd, meta = read(last(n3, "_mask_classes.tif"))
    check("{3: 400, 0: 1200}, no nodata: as before",
          counts(a) == {3: 400, 0: 1200} and nd is None
          and "RASTERLABEL_IGNORE_INDEX" not in meta, (counts(a), nd))
    item = json.load(open(os.path.join(n3, "stac", "cut_0001.json"),
                          encoding="utf-8"))
    # The classes of the style are listed whether or not there is an ignore
    # value: a reader of the item cannot tell what a 3 is from the codes.
    # What an item without an ignore value does not carry is the ignore
    # value itself: no nodata, no entry marked as one.
    listed = item["assets"]["mask_classes"].get("classification:classes", [])
    check("off: the classes are in the item, none of them nodata, and no "
          "ignore value or nodata anywhere",
          g["CLASSIFICATION_EXT"] in item["stac_extensions"]
          and [c["value"] for c in listed] == sorted(
              c["value"] for c in listed) and len(listed) >= 2
          and not any(c.get("nodata") for c in listed)
          and "rasterlabel:ignore_index" not in item["properties"]
          and "nodata" not in item["assets"]["mask_classes"][
              "raster:bands"][0], (item["stac_extensions"], listed))
    note = json.load(open(os.path.join(n3, "sampler.json"), encoding="utf-8"))
    check("off: the sampler says 0 is unlabelled, and no ignore value",
          note["labels"]["ignore_index"] is None
          and note["labels"]["zero_is"] == "unlabelled", note["labels"])
    rows = list(csv.DictReader(open(os.path.join(n3, "cutouts.csv"),
                                    encoding="utf-8")))
    check("and its column is empty", rows[-1]["ignore_index"] == "")

    print()
    print("N4. a map made elsewhere: its 0 is a class and is kept")
    foreign = np.zeros((H, W), np.uint8)
    foreign[:, 50:] = 7
    fpath = raster(os.path.join(root, "foreign.tif"), bands=1, array=foreign)
    use(K.Layer(fpath, "foreign"))
    setting(True, 255)
    n4 = into("n4")
    check("cut columns -20 to 19", click(-20, 0))
    a, kind, nd, meta = read(last(n4, "_foreign_classes.tif"))
    check("{0: 800, 255: 800}: the padding is 255, the class 0 is 0",
          counts(a) == {0: 800, 255: 800}, counts(a))
    check("and its 0 is said to be a class",
          json.load(open(os.path.join(n4, "sampler.json"), encoding="utf-8"))
          ["labels"]["zero_is"] == "a class")

    print()
    print("N5. a map of 16 signed bits with a nodata of -1")
    signed = np.full((H, W), 5, np.int16)
    signed[:, 50:] = -1
    spath = raster(os.path.join(root, "signed.tif"), bands=1, array=signed,
                   dtype=gdal.GDT_Int16, nodata=-1)
    use(K.Layer(spath, "signed"))
    n5 = into("n5")
    check("cut columns 30-69", click(30, 0))
    a, kind, nd, meta = read(last(n5, "_signed_classes.tif"))
    check("{5: 800, 255: 800}: its nodata became 255",
          counts(a) == {5: 800, 255: 800}, counts(a))
    check("Int16, nodata 255", kind == gdal.GDT_Int16 and nd == 255,
          (gdal.GetDataTypeName(kind), nd))

    print()
    print("N6. a map that holds 255 itself: refused, nothing left")
    holds = np.full((H, W), 255, np.uint8)
    hpath = raster(os.path.join(root, "holds.tif"), bands=1, array=holds)
    use(K.Layer(hpath, "holds"))
    n6 = into("n6")
    shown = len(K.BOXES)
    check("refused", not click(30, 0))
    check("saying which layer, and the way out",
          len(K.BOXES) > shown and "holds 255 inside this cutout"
          in K.BOXES[-1][1] and "choose another value" in K.BOXES[-1][1],
          K.BOXES[-1:])
    check("and no file of it is in the folder",
          not [n for n in (os.listdir(n6) if os.path.isdir(n6) else [])
               if n.startswith("cut_")], os.listdir(n6)
          if os.path.isdir(n6) else [])

    print()
    print("N7. a map read onto a coarser grid: the padding is 255, not 0")
    coarse = raster(os.path.join(root, "coarse.tif"), bands=3, pixel=2.0,
                    size=(50, 50))
    sevens = raster(os.path.join(root, "sevens.tif"), bands=1,
                    array=np.full((H, W), 7, np.uint8))
    use(K.Layer(coarse, "coarse"), K.Layer(sevens, "sevens"))
    n7 = into("n7")
    check("cut", click(80, 0), K.SAID[-2:])
    a, kind, nd, meta = read(last(n7, "_sevens_classes.tif"))
    check("20 x 20 on the coarse grid: {7: 200, 255: 200}",
          a.shape == (20, 20) and counts(a) == {7: 200, 255: 200},
          (a.shape, counts(a)))

    print()
    print("N10. a cutouts.csv of an earlier build is brought up to date")
    n10 = into("n10")
    os.makedirs(n10, exist_ok=True)
    old = cut.CSV_COLUMNS[:-1]
    with open(os.path.join(n10, "cutouts.csv"), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(old)
        w.writerow(["cut_0090", "x", "image", "x", "1", "0", "", "", "0", "0",
                    "1", "1", "1", "1", "GTiff", "1.000", "2026-01-01"])
    cut.count = cut.count_existing()
    use(K.Layer(mask_b, "mask", K.Paletted(None, 1, STYLE)))
    check("cut", click(80, 0))
    with open(os.path.join(n10, "cutouts.csv"), newline="",
              encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    rows = list(csv.DictReader(open(os.path.join(n10, "cutouts.csv"),
                                    encoding="utf-8")))
    check("18 columns, ignore_index last", len(header) == 18
          and header[-1] == "ignore_index", header)
    check("the old row is kept, its new column empty",
          rows[0]["cutout"] == "cut_0090" and rows[0]["ignore_index"] == "",
          rows[0])
    check("the new one says 255", rows[-1]["ignore_index"] == "255",
          rows[-1])
    check("no temporary file is left",
          not os.path.exists(os.path.join(n10, "cutouts.csv.tmp")))

    print()
    print("a value no cutout may hold is refused before anything is cut")
    setting(True, 7)
    shown = len(K.BOXES)
    n12 = into("n12")
    check("7 is refused", not click(80, 0))
    check("with a warning that says why", len(K.BOXES) > shown
          and K.BOXES[-1][0] == "warning" and "1 to 254" in K.BOXES[-1][1],
          K.BOXES[-1:])
    check("and nothing is written", not os.path.isdir(n12) or not [
        n for n in os.listdir(n12) if n.startswith("cut_")])
    check("the setting is remembered on this machine",
          cut.setting("ignore_on", None, bool) is True
          and cut.setting("ignore_value", 0, int) == 7)
    setting(False)

    print()
    print("the STAC wrappers moved to project.py answer as before")
    rect = K.Rect(OX, OY - 40, OX + 40, OY)
    shape, bbox = cut.lonlat_footprint(rect, WKT)
    turn = Turn()
    check("a closed ring, turned into degrees", shape["type"] == "Polygon"
          and len(shape["coordinates"][0]) == 5
          and shape["coordinates"][0][0] == shape["coordinates"][0][-1]
          and abs(bbox[0] - turn.transform(K.Point(OX, 0)).x()) < 1e-6,
          bbox)
    proj = cut.projection_of(GT, 40, 40, WKT, rect)
    check("proj:shape and proj:transform", proj["proj:shape"] == [40, 40]
          and proj["proj:transform"][:3] == [1.0, 0.0, OX], proj)
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
