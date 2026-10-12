"""layers.json of a cutouts folder carries no name of whoever cut it.

The folder is a dataset: it is zipped, published and cited. Its layers.json
used to hold the whole path of every layer and of the grid, home folder and
user name included. Now the paths are the way from the folder (a layer in the
home folder, a folder in it too), or from ~ (a folder elsewhere), and a layer
that is a service has no password, user name or token in it. Read back, they
find the same layers; a file written before, with whole paths, still opens,
and is written again, once, the new way, on the next cut.

Real files out, read back; every file the cut writes is searched for the home
folder in the three spellings it can have. Needs the GDAL Python bindings.
QGIS is faked, see correctkit.py.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
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

home = os.path.expanduser("~")
root = tempfile.mkdtemp(prefix="rl_layers_private_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
stay = os.path.join(home, "rl_layers_private")        # in the home folder
data = os.path.join(stay, "data")
os.makedirs(data)
GT = (500000.0, 0.5, 0.0, 4100000.0, 0.0, -0.5)
NX, NY = 120, 80
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)


def write(path, arrays):
    h, w = arrays[0].shape
    ds = gdal.GetDriverByName("GTiff").Create(path, w, h, len(arrays),
                                              gdal.GDT_Byte)
    ds.SetGeoTransform(GT)
    ds.SetProjection(srs.ExportToWkt())
    for i, a in enumerate(arrays):
        ds.GetRasterBand(i + 1).WriteArray(a)
    ds = None


rng = np.random.default_rng(5)
ortho = os.path.join(data, "ortho.tif")
write(ortho, [rng.integers(30, 220, (NY, NX)).astype(np.uint8)
              for _ in range(3)])
SQUARE = K.Rect(500010.0, 4099970.0, 500030.0, 4099990.0)


def load(path, name):
    K.LOADED.clear()
    K.TREE.clear()
    K.add_layer(K.Layer(path, name, None), ticked=True)


def open_cutouts(folder):
    g["write_setting"](g["SETTINGS_ROOT"] + "/cutouts/folder", folder)
    panel = g["Panel"]()
    panel.toggle_module(3)
    return panel, panel.section


def layers_text(folder):
    with open(os.path.join(folder, "layers.json"), encoding="utf-8") as fh:
        return fh.read()


def spellings(path):
    return {path, path.replace("\\", "/"), path.replace("/", "\\"),
            path.replace("\\", "\\\\")}


def home_in(folder):
    """The files of the folder that spell the home folder, in any case."""
    found = []
    for where, _, names in os.walk(folder):
        for name in names:
            with open(os.path.join(where, name), "rb") as fh:
                body = fh.read().lower()
            if any(s.lower().encode() in body for s in spellings(home)):
                found.append(name)
    return found


try:
    print("a folder outside the home, a layer in it: from ~")
    out = os.path.join(root, "dataset")
    load(ortho, "ortho")
    panel, cut = open_cutouts(out)
    check("the first cutout is written", cut.export(SQUARE, nominal=20.0))
    book = json.loads(layers_text(out))
    check("the layer is written from ~ and the grid too",
          [e["source"] for e in book["layers"]] == ["~/rl_layers_private/data/ortho.tif"]
          and book["grid"] == "~/rl_layers_private/data/ortho.tif", book)
    check("no file of the folder spells the home folder", not home_in(out),
          home_in(out))
    panel.close_module()
    panel, cut = open_cutouts(out)
    check("read back, the folder finds its layer: tag and role as written",
          [(s["tag"], s["role"]) for s in cut.sources] == [("ortho", "image")],
          [(s["tag"], s["role"]) for s in cut.sources])
    check("and the record is the one in hand: nothing is said to differ",
          cut.layers_match(cut.read_layers(), cut.layers_record()))
    check("its paths are whole again in memory",
          os.path.normcase(cut.read_layers()["layers"][0]["source"])
          == os.path.normcase(ortho), cut.read_layers())
    panel.close_module()

    print()
    print("a folder in the home, the layer in it: the way from the folder")
    near = os.path.join(stay, "dataset")
    panel, cut = open_cutouts(near)
    check("a cutout is written", cut.export(SQUARE, nominal=20.0))
    book = json.loads(layers_text(near))
    check("the layer is written by its way from the folder",
          book["layers"][0]["source"] == "../data/ortho.tif"
          and book["grid"] == "../data/ortho.tif", book)
    check("no file of the folder spells the home folder", not home_in(near),
          home_in(near))
    panel.close_module()
    panel, cut = open_cutouts(near)
    check("read back, it finds the layer",
          [s["tag"] for s in cut.sources] == ["ortho"])
    panel.close_module()

    print()
    print("a record written before, with whole paths")
    old = os.path.join(root, "old")
    os.makedirs(old)
    with open(os.path.join(old, "layers.json"), "w", encoding="utf-8") as fh:
        json.dump({"layers": [{"source": ortho, "name": "ortho",
                               "role": "image", "tag": "mine",
                               "rgb": [1, 1, 1]}], "grid": ortho}, fh)
    panel, cut = open_cutouts(old)
    check("is read as it always was: the folder's tag is kept",
          [s["tag"] for s in cut.sources] == ["mine"],
          [s["tag"] for s in cut.sources])
    check("a cutout is written", cut.export(SQUARE, nominal=20.0))
    check("and the record is written again without the home folder",
          home_in(old) == [] and json.loads(layers_text(old))["grid"]
          == "~/rl_layers_private/data/ortho.tif", layers_text(old)[:300])
    panel.close_module()

    print()
    print("a layer that is a service")
    wms = ("contextualWMSLegend=0&crs=EPSG:32633&url=https://maps.example.org/"
           "wms&username=bob&password=s3cret&authcfg=a1b2c3&layers=ortho")
    record = {"layers": [{"source": wms, "tag": "wms", "role": "image"},
                         {"source": ortho, "tag": "o", "role": "image"}],
              "grid": wms}
    kept = cut.layers_to_write(record)
    text = json.dumps(kept)
    check("no user name, password or token is written",
          "s3cret" not in text and "bob" not in text, text)
    check("authcfg, which names a stored configuration, is", "a1b2c3" in text)
    check("and the same layer, with its login, is the folder's layer",
          cut.layers_match({"layers": kept["layers"][:1]},
                           {"layers": record["layers"][:1]}), kept)
finally:
    shutil.rmtree(stay, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
