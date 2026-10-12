"""Cutouts from an empty panel: real files out, no campaign in.

Cutouts was written as a part of the annotation campaign. It could not be
opened without one, it kept its folder and its sizes in campaign.json, and it
appended a line to the manifest for every cutout. It is the one module that
needs no campaign at all: it cuts the raster layers on the map, on a window
you choose, into a folder. So this suite opens it on a panel with two rasters
and nothing else, cuts, and reads back what is on disk:

  every layer ticked on the map is cut, and one unticked is not;
  the image, the classes, their pictures, cutouts.csv, the footprints, the
  sampler note and shapes.json are in the folder, and nothing anywhere else;
  no campaign.json, no campaign folder, nothing named after a campaign;
  the classes picture is painted with the style of the classes layer;
  the side written in cutouts.csv is the side of the window, measured;
  a second cutout of the same side keeps the size of the first, from
  shapes.json;
  undo takes a cutout off the disk again.

Needs the GDAL Python bindings: the rasters, the GeoPackage and the PNGs are
real. QGIS is faked, see correctkit.py.
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

gdal.UseExceptions()
g, check = K.g, K.check

root = tempfile.mkdtemp(prefix="rl_cutouts_free_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
data = os.path.join(root, "data")
os.makedirs(data)
GT = (500000.0, 0.5, 0.0, 4100000.0, 0.0, -0.5)
NX, NY = 120, 80
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)


def write(path, arrays, gtype=gdal.GDT_Byte):
    ds = gdal.GetDriverByName("GTiff").Create(path, NX, NY, len(arrays), gtype)
    ds.SetGeoTransform(GT)
    ds.SetProjection(srs.ExportToWkt())
    for i, a in enumerate(arrays):
        ds.GetRasterBand(i + 1).WriteArray(a)
    ds = None


rng = np.random.default_rng(7)
ortho = os.path.join(data, "ortho.tif")
write(ortho, [rng.integers(30, 220, (NY, NX)).astype(np.uint8)
              for _ in range(3)])
truth_map = np.ones((NY, NX), np.uint8)
truth_map[:, 40:] = 4
truth = os.path.join(data, "truth.tif")
write(truth, [truth_map])
hidden = os.path.join(data, "hidden.tif")
write(hidden, [np.zeros((NY, NX), np.uint8)])

K.add_layer(K.Layer(ortho, "ortho"))
K.add_layer(K.Layer(truth, "truth", K.Paletted(None, 1, [
    K.Paletted.Class(1, "#ff0000", "sand"),
    K.Paletted.Class(4, "#0000ff", "sea")])))
K.add_layer(K.Layer(hidden, "hidden"), ticked=False)

panel = g["Panel"]()
out = os.path.join(root, "dataset")

try:
    print("Cutouts on a panel with no campaign")
    check("no campaign is open", panel.campaign is None)
    check("Cutouts can be pressed", panel.modules[3].isEnabled())
    panel.toggle_module(3)
    cut = panel.section
    check("it opens", type(cut).__name__ == "CutoutsSection", K.BOXES[-1:])
    roles = {s["tag"]: s["role"] for s in cut.sources}
    check("the rasters ticked on the map are cut, the unticked one is not",
          roles == {"ortho": "image", "truth": "classes"}, roles)
    cut.folder_box.setText(out)
    cut.folder_changed()
    cut.side.setValue(20.0)                 # forty pixels of half a metre

    print()
    print("one square, cut")
    square = K.Rect(500010.0, 4099970.0, 500030.0, 4099990.0)
    done = cut.export(square, nominal=20.0)
    check("the cutout is written", done, K.BOXES[-3:])
    files = K.everything_under(out)
    for name in ("cut_0001_ortho_image.tif", "cut_0001_ortho_image.png",
                 "cut_0001_truth_classes.tif", "cut_0001_truth_classes.png",
                 "cutouts.csv", "cutouts.gpkg", "sampler.json", "shapes.json"):
        check("%s is in the folder" % name, name in files, files)
    check("nothing of the hidden layer", not [f for f in files if "hidden" in f])
    image = gdal.Open(os.path.join(out, "cut_0001_ortho_image.tif"))
    check("the image is forty by forty pixels, on the grid",
          (image.RasterXSize, image.RasterYSize) == (40, 40)
          and image.GetGeoTransform()[0] == 500010.0,
          (image.RasterXSize, image.RasterYSize, image.GetGeoTransform()))
    check("in three bands of bytes", image.RasterCount == 3
          and image.GetRasterBand(1).DataType == gdal.GDT_Byte)
    image = None
    codes = gdal.Open(os.path.join(out, "cut_0001_truth_classes.tif")) \
        .ReadAsArray()
    check("the classes come out as they are", set(np.unique(codes)) == {1, 4}
          and (codes[:, :20] == 1).all() and (codes[:, 20:] == 4).all(),
          np.unique(codes))
    picture = gdal.Open(os.path.join(out, "cut_0001_truth_classes.png")) \
        .ReadAsArray()
    check("the classes picture is painted with the layer's own style",
          tuple(picture[:3, 5, 5]) == (255, 0, 0)
          and tuple(picture[:3, 5, 35]) == (0, 0, 255),
          (picture[:3, 5, 5], picture[:3, 5, 35]))

    rows = list(csv.DictReader(open(os.path.join(out, "cutouts.csv"),
                                    encoding="utf-8")))
    check("cutouts.csv has a row per layer", len(rows) == 2, rows)
    check("the side in it is measured on the window: 20 m",
          all(abs(float(r["side_m"]) - 20.0) < 1e-6 for r in rows),
          [r["side_m"] for r in rows])
    note = json.load(open(os.path.join(out, "sampler.json"), encoding="utf-8"))
    check("the sampler names no campaign", "campaign" not in note, sorted(note))
    check("and its classes are the style's",
          [(c["code"], c["name"]) for c in note["classes"]] ==
          [(1, "sand"), (4, "sea")], note["classes"])
    shapes = json.load(open(os.path.join(out, "shapes.json"), encoding="utf-8"))
    check("the size of the side is kept in shapes.json, in the folder",
          shapes == {"20.000@0.500000": [40, 40]}, shapes)

    print()
    print("a second square of the same side keeps the size")
    nudged = K.Rect(500050.2, 4099950.2, 500070.2, 4099970.2)
    check("it is written", cut.export(nudged, nominal=20.0))
    second = gdal.Open(os.path.join(out, "cut_0002_ortho_image.tif"))
    check("forty by forty, like the first",
          (second.RasterXSize, second.RasterYSize) == (40, 40),
          (second.RasterXSize, second.RasterYSize))
    second = None

    print()
    print("no campaign anywhere")
    everything = K.everything_under(root)
    check("no campaign.json was written", not [
        f for f in everything if f.endswith("campaign.json")], everything)
    check("nothing was written outside the dataset folder",
          all(f.startswith("dataset" + os.sep) or f.startswith("data" + os.sep)
              for f in everything), everything)
    check("the panel still has no campaign", panel.campaign is None)
    check("and the folder chosen is remembered by QGIS, not by a manifest",
          g["read_setting"]("rasterlabel/cutouts/folder", "") == out)

    print()
    print("undo takes it off the disk again")
    cut.undo()
    left = K.everything_under(out)
    check("the second cutout's files are gone",
          not [f for f in left if f.startswith("cut_0002")], left)
    check("the first one's are still there",
          "cut_0001_ortho_image.tif" in left)
    rows = list(csv.DictReader(open(os.path.join(out, "cutouts.csv"),
                                    encoding="utf-8")))
    check("and cutouts.csv lists only the first", {r["cutout"] for r in rows}
          == {"cut_0001"}, rows)
    panel.close_module()

    print()
    print("a prefix and a layer that begin with a minus")
    # csv_text puts a quote before the name in the file; the readers that
    # compare a name with a file name take it off, or every file is "gone"
    K.add_layer(K.Layer(ortho, "-dem"))
    dash = os.path.join(root, "dash")
    panel.toggle_module(3)
    cut = panel.section
    cut.folder_box.setText(dash)
    cut.folder_changed()
    cut.side.setValue(20.0)
    cut.prefix.setText("-cut")
    check("two cutouts are written", cut.export(square, nominal=20.0)
          and cut.export(nudged, nominal=20.0), K.BOXES[-3:])
    text = open(os.path.join(dash, "cutouts.csv"), encoding="utf-8").read()
    check("the name is quoted in the file", "'-cut_0001," in text
          and "'-dem" in text, text[:300])
    check("the names are read back as they were",
          cut.listed_names()[:1] == ["-cut_0001"]
          and "-cut_0002" in cut.listed_names(), cut.listed_names())
    check("every one is counted: its files are on disk",
          cut.count_existing() == 2 and cut.gone == [],
          (cut.count_existing(), cut.gone))
    check("the next name goes on from the last", cut.free_name()
          == "-cut_0003", cut.free_name())
    cut.undo()
    left = K.everything_under(dash)
    check("undo takes the files of the second away",
          not [f for f in left if f.startswith("-cut_0002")], left)
    text = open(os.path.join(dash, "cutouts.csv"), encoding="utf-8").read()
    check("and its rows from the manifest", "-cut_0002" not in text
          and "-cut_0001" in text, text[:300])
    check("the first is still counted", cut.count_existing() == 1
          and cut.gone == [], (cut.count_existing(), cut.gone))
    # a folder cut by a build from before wrote the name plainly
    check("one more is written", cut.export(nudged, nominal=20.0),
          K.BOXES[-1:])
    path = os.path.join(dash, "cutouts.csv")
    text = open(path, encoding="utf-8", newline="").read()
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace("'-cut_0002,", "-cut_0002,"))
    cut.undo()
    text = open(path, encoding="utf-8").read()
    check("undo takes a row written plainly too", "-cut_0002" not in text
          and "-cut_0001" in text, text[:300])
    panel.close_module()
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
