"""Exercise the catalogue and the fixed shape without QGIS.

Only the arithmetic and the files are real: the geometry classes are replaced
by small stand-ins that do exactly what the code asks of them."""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import csv
import os, sys, types, json, shutil, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtbinding import PyQt, QtCore, QtGui, QtWidgets

qgis = types.ModuleType("qgis"); qgis.PyQt = PyQt
sys.modules["qgis"] = qgis
sys.modules["qgis.PyQt"] = PyQt
utils = types.ModuleType("qgis.utils")
utils.iface = None          # the harness replaces it below
qgis.utils = utils
sys.modules["qgis.utils"] = utils
sys.modules["qgis.PyQt.QtCore"] = QtCore
sys.modules["qgis.PyQt.QtGui"] = QtGui
sys.modules["qgis.PyQt.QtWidgets"] = QtWidgets


class Dummy:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return lambda *a, **k: None


class Sig:
    def connect(self, *a, **k): pass
    def disconnect(self, *a, **k): pass


class Point:
    def __init__(self, x, y=None):
        if y is None: x, y = x.x(), x.y()
        self._x, self._y = float(x), float(y)
    def x(self): return self._x
    def y(self): return self._y


class Rect:
    def __init__(self, a, b=None, c=None, d=None):
        if b is None:
            self.v = list(a.v)
        elif c is None:
            self.v = [min(a.x(), b.x()), min(a.y(), b.y()),
                      max(a.x(), b.x()), max(a.y(), b.y())]
        else:
            self.v = [min(a, c), min(b, d), max(a, c), max(b, d)]
    def xMinimum(self): return self.v[0]
    def yMinimum(self): return self.v[1]
    def xMaximum(self): return self.v[2]
    def yMaximum(self): return self.v[3]
    def width(self): return self.v[2] - self.v[0]
    def height(self): return self.v[3] - self.v[1]


class Crs:
    def __init__(self, a=""):
        self._a = a
    def authid(self): return self._a
    def isValid(self): return bool(self._a)
    def isGeographic(self): return self._a == "EPSG:4326"
    def createFromWkt(self, w):
        self._a = "EPSG:32633" if w else ""
        return bool(w)
    def __eq__(self, o): return self._a == getattr(o, "_a", None)
    def __ne__(self, o): return not self.__eq__(o)


class Transform:
    """UTM 33N to degrees, near enough for a bounding box."""
    def __init__(self, *a, **k): pass
    def transform(self, p):
        return Point(9.0 + (p.x() - 400000.0) / 111320.0,
                     37.0 + (p.y() - 4100000.0) / 110540.0)
    def transformBoundingBox(self, r): return r


class Project:
    _one = None
    layersAdded = Sig(); layersRemoved = Sig()
    @classmethod
    def instance(cls):
        if cls._one is None: cls._one = cls()
        return cls._one
    def __getattr__(self, n): return lambda *a, **k: None


core = types.ModuleType("qgis.core")
for n in ("QgsRasterLayer", "QgsVectorLayer", "QgsFillSymbol", "QgsMarkerSymbol",
          "QgsLineSymbol", "QgsMessageLog", "Qgis",
          "QgsCategorizedSymbolRenderer", "QgsRendererCategory", "QgsGeometry",
          "QgsSingleSymbolRenderer", "QgsFeature", "QgsWkbTypes",
          "QgsFeatureRequest", "QgsPalettedRasterRenderer", "QgsDistanceArea",
          "QgsMultiBandColorRenderer", "QgsRuleBasedRenderer",
          "QgsUnitTypes", "QgsProperty", "QgsSymbolLayer",
          "QgsPalLayerSettings", "QgsTextFormat", "QgsTextBufferSettings",
          "QgsVectorLayerSimpleLabeling",
          "QgsPalLayerSettings", "QgsVectorLayerSimpleLabeling",
          "QgsTextFormat", "QgsTextBufferSettings", "QgsLineSymbol"):
    setattr(core, n, Dummy)
core.QgsPointXY = Point
core.QgsRectangle = Rect
core.QgsCoordinateReferenceSystem = Crs
core.QgsCoordinateTransform = Transform
core.QgsProject = Project
core.QgsApplication = Dummy
sys.modules["qgis.core"] = core

gui = types.ModuleType("qgis.gui")
for n in ("QgsMapTool", "QgsRubberBand", "QgsVertexMarker", "QgsMapCanvas"):
    setattr(gui, n, Dummy)
sys.modules["qgis.gui"] = gui

gdal = types.ModuleType("gdal")
gdal.GDT_Byte = 1; gdal.GCI_Undefined = 0; gdal.GA_Update = 1
for n in ("Open", "Warp", "RasterizeLayer", "GetDriverByName"):
    setattr(gdal, n, lambda *a, **k: None)
gdal.GetDataTypeSize = lambda t: 8
gdal.GetDataTypeName = lambda t: "Byte"
ogr = types.ModuleType("ogr")
for n in ("wkbPolygon", "wkbMultiPolygon", "wkbPoint", "wkbLinearRing", "wkbLineString", "wkbMultiLineString",
          "wkbUnknown", "OFTString", "OFTReal", "OFTInteger"):
    setattr(ogr, n, 0)
ogr.GetDriverByName = lambda n: Dummy()
ogr.Feature = Dummy; ogr.FieldDefn = Dummy; ogr.Geometry = Dummy
osgeo = types.ModuleType("osgeo")
osgeo.gdal = gdal; osgeo.ogr = ogr
osgeo.osr = types.ModuleType("osr"); osgeo.osr.SpatialReference = Dummy
sys.modules["osgeo"] = osgeo
sys.modules["osgeo.gdal"] = gdal
sys.modules["osgeo.ogr"] = ogr
sys.modules["osgeo.osr"] = osgeo.osr

app = QtWidgets.QApplication(sys.argv)
SRC = os.environ.get("RL_SRC", _BUILT)
code = open(SRC, encoding="utf-8").read().replace("\nmain()\n", "\n").replace("\nstart()\n", "\n")
g = {"__name__": "rasterlabel", "__file__": SRC, "iface": Dummy()}
exec(compile(code, SRC, "exec"), g)

snap = g["snap"]; Section = g["CutoutsSection"]
fails = []


def check(name, condition, detail=""):
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + detail) if detail and not condition else ""))
    if not condition:
        fails.append(name)


# ------------------------------------------------------------ the clipping
print("snap")
GT = (400000.0, 0.05, 0.0, 4100000.0, 0.0, -0.05)
SIZE = (4000, 4000)
inside = Rect(400010.0, 4099990.0, 400020.0, 4100000.0)
check("a frame inside the raster is 200 by 200",
      snap(GT, SIZE, inside)[2:] == (200, 200), str(snap(GT, SIZE, inside)))
over = Rect(399995.0, 4099990.0, 400005.0, 4100000.0)
check("clipped at the edge it loses the part outside",
      snap(GT, SIZE, over)[2:] == (100, 200), str(snap(GT, SIZE, over)))
check("unclipped it keeps its size",
      snap(GT, SIZE, over, clip=False)[2:] == (200, 200),
      str(snap(GT, SIZE, over, clip=False)))
check("and starts at a negative column",
      snap(GT, SIZE, over, clip=False)[0] == -100,
      str(snap(GT, SIZE, over, clip=False)))

# the case that started all this: the subtraction that misses by a billionth
drift = Rect(400010.0, 4099976.79999999, 400020.0, 4099986.8)
check("a coordinate that misses the edge by a billionth still gives 200",
      snap(GT, SIZE, drift)[2:] == (200, 200), str(snap(GT, SIZE, drift)))

# ------------------------------------------------------- one size for them all
print("the fixed shape")
FOLDER = tempfile.mkdtemp(prefix="rl_stac_")

CLASSES = [{"name": "crust", "code": 1, "colour": "#b0651f"},
           {"name": "water", "code": 3, "colour": "#2f6f9f"}]


class FakeCampaign:
    folder = FOLDER
    def __init__(self):
        self.data = {"id": "abc", "name": "aragona_2025", "with_tiles": True,
                     "classes": CLASSES}
        self.saves = 0
    def active_classes(self): return CLASSES
    def save(self): self.saves += 1


class Box:
    def __init__(self, on=True): self.on = on
    def isChecked(self): return self.on


# the section without the widget: only the methods under test
Shim = type("Shim", (object,), {
    n: Section.__dict__[n] for n in
    ("hold_shape", "write_sampler", "lonlat_footprint", "projection_of",
     "stac_folder", "stac_assets", "write_stac", "read_shapes",
     "write_shapes", "shapes_path", "missing_assets",
     "dump_json", "refresh_catalog", "class_order", "class_colours",
     "labels_note")})
s = Shim()
s.campaign = FakeCampaign()
s.folder = FOLDER
s.same_size = Box(True)
s.stac = Box(True)

check("the first cutout of a side decides the shape",
      Section.hold_shape(s, 10.0, 200, 200, 0.05) == (200, 200))
check("a later one of the same side is made to match",
      Section.hold_shape(s, 10.0, 201, 200, 0.05) == (200, 200))
check("another side keeps its own answer",
      Section.hold_shape(s, 20.0, 400, 400, 0.05) == (400, 400))
check("the same side on a coarser raster is not made to match the finer one",
      Section.hold_shape(s, 10.0, 50, 50, 0.20) == (50, 50))
check("and that coarser answer is then held too",
      Section.hold_shape(s, 10.0, 51, 50, 0.20) == (50, 50))
check("the finer one is untouched by all that",
      Section.hold_shape(s, 10.0, 201, 201, 0.05) == (200, 200))
check("with no resolution given the side alone is the key",
      Section.hold_shape(s, 30.0, 600, 600) == (600, 600))
# A pixel in degrees. Six decimals wrote 5.64e-07 as "0.000001", and every
# raster with a pixel between half a millionth and one and a half millionths
# of a degree took the size the first of them had decided.
check("a pixel in degrees has a key of its own",
      Section.hold_shape(s, 30.0, 601, 601, 5.6448e-07) == (601, 601))
check("and a raster twice as coarse in degrees does not take its size",
      Section.hold_shape(s, 30.0, 301, 301, 1.12896e-06) == (301, 301))
# The answers describe the folder, so they live in it. They used to be
# written into the campaign manifest, and Cutouts then could not run without
# a campaign to write to.
_shapes = json.load(open(os.path.join(FOLDER, "shapes.json"), encoding="utf-8"))
check("and the answers are in shapes.json in the folder, one per grid",
      _shapes == {"10.000@0.050000": [200, 200],
                  "20.000@0.050000": [400, 400],
                  "10.000@0.200000": [50, 50],
                  "30.000": [600, 600],
                  "30.000@5.6448e-07": [601, 601],
                  "30.000@1.12896e-06": [301, 301]}, str(_shapes))
check("and not in the campaign, which was not saved even once",
      "cutout_shape" not in s.campaign.data and s.campaign.saves == 0,
      "%s, %d saves" % (s.campaign.data.get("cutout_shape"), s.campaign.saves))

print("a folder cut under a campaign that kept the sizes")
OLD = tempfile.mkdtemp(prefix="rl_stac_old_")
s.folder = OLD
s.campaign.data["cutout_shape"] = {"10.000@0.050000": [201, 199]}
check("the sizes the campaign kept are taken once, when the folder has none",
      Section.hold_shape(s, 10.0, 200, 200, 0.05) == (201, 199))
s.campaign.data.pop("cutout_shape")
check("and from then on the folder has them itself",
      Section.hold_shape(s, 10.0, 200, 200, 0.05) == (201, 199))
check("without a campaign at all the folder is enough",
      (lambda c: (setattr(s, "campaign", None),
                  Section.hold_shape(s, 10.0, 200, 200, 0.05),
                  setattr(s, "campaign", c))[1])(s.campaign) == (201, 199))
s.folder = FOLDER
shutil.rmtree(OLD, ignore_errors=True)

# --------------------------------------------------------------- the catalogue
print("the catalogue")
extent = Rect(400010.0, 4099990.0, 400020.0, 4100000.0)
gt = (400010.0, 0.05, 0.0, 4100000.0, 0.0, -0.05)
WKT = "PROJCS[\"WGS 84 / UTM zone 33N\"]"

shape, bbox = Section.lonlat_footprint(s, extent, WKT)
check("the footprint is a closed ring of five points",
      shape["type"] == "Polygon" and len(shape["coordinates"][0]) == 5
      and shape["coordinates"][0][0] == shape["coordinates"][0][-1])
check("in degrees", 8.9 < bbox[0] < 9.2 and 36.8 < bbox[1] < 37.2, str(bbox))
check("with no projection at all nothing is catalogued",
      Section.lonlat_footprint(s, extent, "") == (None, None))

proj = Section.projection_of(s, gt, 200, 200, WKT, extent)
check("proj:epsg is read from the projection", proj["proj:epsg"] == 32633,
      str(proj.get("proj:epsg")))
check("proj:shape is rows then columns", proj["proj:shape"] == [200, 200])
check("proj:transform is the affine, not the geotransform",
      proj["proj:transform"] == [0.05, 0.0, 400010.0, 0.0, -0.05, 4100000.0,
                                 0.0, 0.0, 1.0],
      str(proj["proj:transform"]))

assets = {"ref_image": (os.path.join(FOLDER, "cut_0001_ref_image.tif"),
                        g["GEOTIFF_TYPE"], ["data"], "the ground"),
          "truth_classes": (os.path.join(FOLDER, "cut_0001_truth_classes.tif"),
                            g["GEOTIFF_TYPE"], ["data"], "the class codes")}
# The files are there, as they are when a cutout has just been written: the
# catalogue links only items whose files are on disk.
for _path, _, _, _ in assets.values():
    open(_path, "wb").close()
s.sources = [{"id": "a", "role": "image"}, {"id": "b", "role": "classes"}]

written = Section.write_stac(s, "cut_0001", extent, gt, 200, 200, WKT, "t_003",
                             assets)
check("one document per cutout, not two", len(written) == 1, str(written))
check("and no label item beside it",
      not os.path.exists(os.path.join(FOLDER, "stac", "cut_0001_labels.json")))

item = json.load(open(os.path.join(FOLDER, "stac", "cut_0001.json")))
catalog = json.load(open(os.path.join(FOLDER, "stac", "catalog.json")))

check("the item is a Feature with an id", item["type"] == "Feature"
      and item["id"] == "cut_0001")
check("its assets point out of the stac folder",
      item["assets"]["ref_image"]["href"] == "../cut_0001_ref_image.tif")
check("every asset written is listed, and only those",
      sorted(item["assets"]) == ["ref_image", "truth_classes"],
      sorted(item["assets"]))
check("the label extension is gone", g["LABEL_EXT"] not in
      item.get("stac_extensions", []))
check("and so is every claim it carried",
      not [k for k in item["properties"] if k.startswith("label:")],
      [k for k in item["properties"] if k.startswith("label:")])
# The ignore value brings the raster and classification extensions with it,
# and an item with none claims neither: a field of an extension the item
# does not use is a claim about nothing.
check("with no ignore value, neither the raster nor the classification "
      "extension, nor rasterlabel:ignore_index",
      g["RASTER_EXT"] not in item.get("stac_extensions", [])
      and g["CLASSIFICATION_EXT"] not in item.get("stac_extensions", [])
      and "rasterlabel:ignore_index" not in item["properties"],
      str(item.get("stac_extensions")))
check("the roles that were cut are recorded",
      item["properties"]["rasterlabel:roles"] == ["classes", "image"],
      item["properties"].get("rasterlabel:roles"))
check("the tile is recorded", item["properties"]["rasterlabel:tile_id"] == "t_003")
check("with a campaign open its name is recorded too",
      item["properties"].get("rasterlabel:campaign") == "aragona_2025"
      and item["properties"].get("rasterlabel:campaign_id") == "abc")
check("the catalogue lists the one item",
      [l["href"] for l in catalog["links"] if l["rel"] == "item"]
      == ["cut_0001.json"],
      [l["href"] for l in catalog["links"] if l["rel"] == "item"])

Section.write_stac(s, "cut_0002", extent, gt, 200, 200, WKT, "t_004", assets)
catalog = json.load(open(os.path.join(FOLDER, "stac", "catalog.json")))
check("the catalogue now lists two", len(
    [l for l in catalog["links"] if l["rel"] == "item"]) == 2)
check("the catalogue is named after the folder, not after a campaign",
      catalog["id"] == g["tidy"](os.path.basename(FOLDER), "cutouts")
      and "campaign" not in catalog["description"], catalog["id"])
_kept = s.campaign
s.campaign = None
Section.write_stac(s, "cut_0003", extent, gt, 200, 200, WKT, None, assets)
_free = json.load(open(os.path.join(FOLDER, "stac", "cut_0003.json")))
s.campaign = _kept
check("with no campaign open the item names none",
      "rasterlabel:campaign" not in _free["properties"]
      and "rasterlabel:campaign_id" not in _free["properties"],
      sorted(_free["properties"]))
check("and is still a whole item", _free["id"] == "cut_0003"
      and _free["properties"]["rasterlabel:roles"] == ["classes", "image"])
os.remove(os.path.join(FOLDER, "stac", "cut_0003.json"))
os.remove(os.path.join(FOLDER, "stac", "cut_0002.json"))
Section.refresh_catalog(s)
catalog = json.load(open(os.path.join(FOLDER, "stac", "catalog.json")))
check("a file deleted by hand leaves no link behind",
      all(l["href"] != "cut_0002.json" for l in catalog["links"]))

# The roles are those of what was written, handed in by the caller, not those
# asked for: a session whose every cutout had left the image out wrote items
# saying "classes, image" over the assets of the classes alone.
only = {"truth_classes": assets["truth_classes"]}
Section.write_stac(s, "cut_0004", extent, gt, 200, 200, WKT, None, only,
                   roles=["classes"])
_four = json.load(open(os.path.join(FOLDER, "stac", "cut_0004.json")))
check("an item says only the roles really written",
      _four["properties"]["rasterlabel:roles"] == ["classes"]
      and sorted(_four["assets"]) == ["truth_classes"], _four["properties"])

# Cutout files deleted by hand while the item stays: the item is kept in the
# stac folder and left out of the catalogue, which must not send anybody to
# files that are not there.
os.remove(assets["ref_image"][0])
Section.refresh_catalog(s)
catalog = json.load(open(os.path.join(FOLDER, "stac", "catalog.json")))
linked = [l["href"] for l in catalog["links"] if l["rel"] == "item"]
check("an item whose files are gone is left out of the catalogue",
      "cut_0001.json" not in linked and "cut_0004.json" in linked, linked)
check("and its json is kept, never deleted",
      os.path.exists(os.path.join(FOLDER, "stac", "cut_0001.json")))
check("the reason is the file that is missing",
      Section.missing_assets(os.path.join(FOLDER, "stac", "cut_0001.json"))
      == ["cut_0001_ref_image.tif"])
open(assets["ref_image"][0], "wb").close()
Section.refresh_catalog(s)
catalog = json.load(open(os.path.join(FOLDER, "stac", "catalog.json")))
check("and it is linked again once the file is back",
      "cut_0001.json" in [l["href"] for l in catalog["links"]])

# ----------------------------------------------------------------- the sampler
# The note now describes the FOLDER, read back from cutouts.csv, not whichever
# cutout happened to be written last. So the test writes a manifest and checks
# that the note is true of what is in it.
print("the sampler note")
Shim.shapes_on_disk = Section.__dict__["shapes_on_disk"]
Shim.reference_wkt = Section.__dict__["reference_wkt"]
s.csv_path = os.path.join(FOLDER, "cutouts.csv")


def manifest(rows):
    with open(s.csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cutout", "width_px", "height_px",
                    "xmin", "ymin", "xmax", "ymax"])
        for r in rows:
            w.writerow(r)


s.reference_wkt = lambda: WKT


class _Class:
    def __init__(self, value, color, label):
        self.value, self.color, self.label = value, color, label


class _Paletted:
    """A paletted style, the one QGIS gives a band with a colour table."""
    def type(self): return "paletted"
    def band(self): return 1
    def classes(self):
        return [_Class(3, "#2f6f9f", "water"), _Class(1, "#b0651f", "crust")]


class _Styled:
    def name(self): return "truth"
    def renderer(self): return _Paletted()


# The classes of the sampler are those of the layer cut as classes, as its
# style names them. They used to be the campaign legend, which numbers what
# is drawn by hand, not what that layer holds.
s.sources = [{"id": "a", "role": "image"},
             {"id": "b", "role": "classes", "band": 1, "layer": _Styled()}]
manifest([["cut_0001", 200, 200, 400010.0, 4099990.0, 400020.0, 4100000.0],
          ["cut_0002", 200, 200, 400010.0, 4099990.0, 400020.0, 4100000.0]])
Section.write_sampler(s)
note = json.load(open(os.path.join(FOLDER, "sampler.json")))
check("size is in pixels, rows first", note["size_pixels"] == [200, 200],
      str(note["size_pixels"]))
check("and repeated in ground units", note["size_crs"] == [10.0, 10.0],
      str(note["size_crs"]))
check("the resolution is there", note["res"] == [0.05, 0.05], str(note["res"]))
check("the crs is named", note["crs"] == "EPSG:32633")
check("with every piece the same shape it says so", note["every_piece_the_same"])
check("the class indices start at zero",
      [c["index"] for c in note["classes"]] == [0, 1]
      and [c["code"] for c in note["classes"]] == [1, 3])
check("and they are the classes layer's own, by its style",
      [c["name"] for c in note["classes"]] == ["crust", "water"],
      note["classes"])
check("the campaign is named only because one is open",
      note.get("campaign") == "aragona_2025")
_kept = s.campaign
s.campaign = None
Section.write_sampler(s)
_free = json.load(open(os.path.join(FOLDER, "sampler.json")))
s.campaign = _kept
check("with no campaign the sampler names none and is otherwise the same",
      "campaign" not in _free and _free["size_pixels"] == [200, 200])
s.sources = [{"id": "a", "role": "image"}]
Section.write_sampler(s)
_none = json.load(open(os.path.join(FOLDER, "sampler.json")))
check("with no classes layer the list is empty and the note says why",
      _none["classes"] == [] and "classes_note" in _none)
s.sources = [{"id": "a", "role": "image"},
             {"id": "b", "role": "classes", "band": 1, "layer": _Styled()}]
import numpy as _np
_cc = Section.class_colours(s, _Styled(), 1, _np.array([[0, 1, 3, 9]]))
check("the classes PNG takes the style's colours, and a colour of its own "
      "for a code the style does not name",
      {c["code"]: c["colour"] for c in _cc}.get(3) == "#2f6f9f"
      and {c["code"]: c["colour"] for c in _cc}.get(9) == g["thematic_colour"](9)
      and 0 not in {c["code"] for c in _cc}, _cc)
check("the torchgeo line is ready to paste",
      note["torchgeo"] == "GridGeoSampler(dataset, size=(200, 200), "
                          "stride=(200, 200), units=Units.PIXELS)",
      note["torchgeo"])

# a folder of two shapes: the note must admit it instead of describing one
manifest([["cut_0001", 200, 200, 400010.0, 4099990.0, 400020.0, 4100000.0],
          ["cut_0002", 200, 200, 400010.0, 4099990.0, 400020.0, 4100000.0],
          ["cut_0003", 300, 200, 400010.0, 4099990.0, 400025.0, 4100000.0]])
Section.write_sampler(s)
note = json.load(open(os.path.join(FOLDER, "sampler.json")))
check("the commonest shape is the one offered", note["size_pixels"] == [200, 200],
      str(note["size_pixels"]))
check("but it no longer claims they are all alike",
      not note["every_piece_the_same"])
check("and both shapes are listed with their counts",
      sorted((d["height"], d["width"], d["n"]) for d in note["shapes_found"])
      == [(200, 200, 2), (200, 300, 1)],
      str(note["shapes_found"]))
check("the warning is in the note",
      "more than one shape" in note["note"], note["note"][-90:])

# a window 300 wide and 200 tall, to be sure rows and columns never swap
manifest([["cut_0001", 300, 200, 400010.0, 4099990.0, 400025.0, 4100000.0]])
Section.write_sampler(s)
note = json.load(open(os.path.join(FOLDER, "sampler.json")))
check("a 300 wide by 200 tall window is written as 200 by 300",
      note["size_pixels"] == [200, 300], str(note["size_pixels"]))
check("and in metres as 10 by 15",
      note["size_crs"] == [10.0, 15.0], str(note["size_crs"]))

# ------------------------------------------------------- the pieces counted
# A cutout of two layers has two rows in cutouts.csv and is one piece: the
# note counted files, so a folder of three cutouts of two layers said six.
print("the pieces are cutouts, not files")
manifest([["cut_0001", 200, 200, 400010.0, 4099990.0, 400020.0, 4100000.0],
          ["cut_0001", 200, 200, 400010.0, 4099990.0, 400020.0, 4100000.0],
          ["cut_0002", 200, 200, 400010.0, 4099990.0, 400020.0, 4100000.0],
          ["cut_0002", 200, 200, 400010.0, 4099990.0, 400020.0, 4100000.0],
          ["cut_0003", 300, 200, 400010.0, 4099990.0, 400025.0, 4100000.0],
          ["cut_0003", 200, 200, 400010.0, 4099990.0, 400020.0, 4100000.0]])
Section.write_sampler(s)
note = json.load(open(os.path.join(FOLDER, "sampler.json")))
check("two layers a cutout: 3 cutouts, not 6 files",
      sum(d["n"] for d in note["shapes_found"]) == 4
      and sorted((d["height"], d["width"], d["n"])
                 for d in note["shapes_found"]) == [(200, 200, 3),
                                                    (200, 300, 1)],
      str(note["shapes_found"]))
check("the commonest shape is the one that most cutouts have",
      note["size_pixels"] == [200, 200], str(note["size_pixels"]))

# ------------------------------------------------------------ written whole
print("the books are written whole or not at all")
atomic = g["write_atomic"]
target = os.path.join(FOLDER, "whole.json")
synced = []
_fsync = os.fsync
os.fsync = lambda fd: synced.append(fd) or _fsync(fd)
try:
    atomic(target, "first")
finally:
    os.fsync = _fsync
check("the text is there, and the disk was asked for it", open(
    target).read() == "first" and len(synced) == 1, synced)
check("with no temporary file beside it",
      not os.path.exists(target + ".tmp"))


def refuse(a, b):
    raise OSError("the rename is refused")


_replace = os.replace
os.replace = refuse
try:
    try:
        atomic(target, "second")
        raised = False
    except OSError:
        raised = True
finally:
    os.replace = _replace
check("a rename that fails raises", raised)
check("and leaves the old file as it was, not half of the new one",
      open(target).read() == "first")
check("and takes its temporary file away",
      not os.path.exists(target + ".tmp"))

before = open(os.path.join(FOLDER, "sampler.json")).read()
manifest([["cut_0001", 300, 300, 400010.0, 4099990.0, 400025.0, 4100005.0]])
os.replace = refuse
try:
    Section.write_sampler(s)
finally:
    os.replace = _replace
check("sampler.json survives a write that fails",
      open(os.path.join(FOLDER, "sampler.json")).read() == before)
check("with no temporary file left",
      not os.path.exists(os.path.join(FOLDER, "sampler.json.tmp")))
Section.write_sampler(s)
check("and is written when nothing refuses", json.load(open(os.path.join(
    FOLDER, "sampler.json")))["size_pixels"] == [300, 300])

item_path = os.path.join(FOLDER, "stac", "cut_0001.json")
before = open(item_path).read()
os.replace = refuse
try:
    written = Section.dump_json(s, item_path, {"id": "other"})
finally:
    os.replace = _replace
check("a STAC item survives a write that fails, and the call says nothing "
      "was written", open(item_path).read() == before and written == [],
      written)

# ------------------------------------------------------------- the moments
print("the date of an item")
s.sources = [{"id": "a", "role": "image"}, {"id": "b", "role": "classes"}]
Section.write_stac(s, "cut_0005", extent, gt, 200, 200, WKT, None, assets)
item = json.load(open(os.path.join(FOLDER, "stac", "cut_0005.json")))
props = item["properties"]
check("no layer says when: datetime is null, with a start and an end that "
      "are the moment of the cutting",
      props["datetime"] is None and props["start_datetime"]
      == props["end_datetime"] == props["created"], props)
check("and the item says that is what they are",
      "cutting" in props["rasterlabel:datetime_is"], props)
s.sources = [{"id": "a", "role": "image", "moment": "2025-03-14T10:22:31Z"},
             {"id": "b", "role": "classes"}]
Section.write_stac(s, "cut_0006", extent, gt, 200, 200, WKT, None, assets)
props = json.load(open(os.path.join(FOLDER, "stac", "cut_0006.json")))[
    "properties"]
check("one layer says when: that is the datetime, and nothing more is claimed",
      props["datetime"] == "2025-03-14T10:22:31Z"
      and "start_datetime" not in props
      and "rasterlabel:datetime_is" not in props
      and props["created"] != props["datetime"], props)
s.sources = [{"id": "a", "role": "image", "moment": "2025-03-14T10:22:31Z"},
             {"id": "b", "role": "image", "moment": "2025-03-20T08:00:00Z"}]
Section.write_stac(s, "cut_0007", extent, gt, 200, 200, WKT, None, assets)
props = json.load(open(os.path.join(FOLDER, "stac", "cut_0007.json")))[
    "properties"]
check("two layers, two dates: a range, and no single datetime",
      props["datetime"] is None
      and props["start_datetime"] == "2025-03-14T10:22:31Z"
      and props["end_datetime"] == "2025-03-20T08:00:00Z", props)
ring = json.load(open(os.path.join(FOLDER, "stac", "cut_0007.json")))[
    "geometry"]["coordinates"][0]
check("the footprint runs counter-clockwise",
      sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:])) > 0,
      ring)

# what is read off a file that says when it was taken
class _Dated:
    def __init__(self, **items): self.items = items
    def GetMetadata(self): return dict(self.items)


moment = g["source_moment"]
check("the TIFF date tag, taken as UTC",
      moment(_Dated(TIFFTAG_DATETIME="2025:03:14 10:22:31"))
      == "2025-03-14T10:22:31Z")
check("an acquisition time written by a producer",
      moment(_Dated(ACQUISITIONDATETIME="2024-07-01T09:30:00Z"))
      == "2024-07-01T09:30:00Z")
check("a file that says nothing says nothing",
      moment(_Dated()) == "" and moment(_Dated(TIFFTAG_DATETIME="unknown"))
      == "")


print()
print("FAILED: %d" % len(fails) if fails else "all of them pass")
for f in fails:
    print("   " + f)
# Removed at the end, not left behind. This folder used to be a fixed one
# under /tmp, which on Windows is a tmp folder at the root of the drive,
# and every run left its files there.
shutil.rmtree(FOLDER, ignore_errors=True)
sys.exit(1 if fails else 0)
