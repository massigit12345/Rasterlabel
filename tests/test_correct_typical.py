"""The thematic maps people really load, through Correct, one after another.

test_correct_thematic corrects one map, the five bands a model of ours
writes. Most maps that come to Correct are not that: they are the one band
a classifier wrote through GDAL or rasterio, with no style and no nodata;
or one with a colour table inside; or a .qml beside it; or sixteen bits with
codes in the thousands; or the class in the second or third band of a stack;
or a table of class names beside the pixels, as ArcGIS and its classifiers
write it, in the .aux.xml or as a .tif.vat.dbf; or a BigTIFF, tiled and
compressed, or striped and raw; or a cloud optimised GeoTIFF.

So each of those is built here, with real GDAL, and walked the whole way a
user walks it: a new correction, the classes window, three strokes, one of
them undone, Save, the classes window again with a class renamed, Close,
opened again, Close. And then, for each:

  the window offered the band the classes are in, and showed the names and
  colours the map carries: its style, its attribute table, its colour table
  and category names, or "class 7" when it carries none, never the number
  alone that QGIS labels a colour table with;
  the corrected map has the structure of the map: the same bands, types,
  nodata, names, grid, tiles or strips, compression, interleave, and a
  BigTIFF stays a BigTIFF;
  every pixel nobody painted is byte for byte the map's, in every band;
  the record beside it marks exactly the pixels that changed;
  its .qml draws the class band in the classes of the correction, its
  colour table and category names say the same, and so does its attribute
  table and its own .tif.vat.dbf, when the map had them, with the pixel
  counts of the corrected map and the class added in the correction: they
  used to keep the names and the counts of the map before it was corrected;
  the map and every file beside it are byte for byte what they were.

Needs the GDAL Python bindings. QGIS is faked, see correctkit.py; the same
maps are opened in a real QGIS by test_correct_typical_qgis.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

os.environ["RL_KIT_REAL_GDAL"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                                 # noqa: E402
from osgeo import gdal, ogr, osr                                   # noqa: E402
import correctkit as K                                             # noqa: E402

gdal.UseExceptions()
g = K.g

NX, NY = 96, 72
GT = (500000.0, 2.0, 0.0, 4100000.0, 0.0, -2.0)
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)
WKT = srs.ExportToWkt()
NAMED = [(1, "#1f78b4", "water"), (2, "#e6c229", "crops"),
         (3, "#444444", "roads"), (4, "#1b7f2a", "forest")]
rng = np.random.default_rng(7)

root = tempfile.mkdtemp(prefix="rl_correct_typical_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])


# ------------------------------------------------------------ the maps
def class_array(codes, nodata=None, dtype=np.uint8):
    """Classes in columns, so a stroke knows what it crosses, salted with
    the others, and a corner of nodata when the map has a nodata value."""
    a = np.empty((NY, NX), dtype)
    for i, c in enumerate(codes):
        a[:, i * NX // len(codes):(i + 1) * NX // len(codes)] = c
    salt = rng.random((NY, NX)) < 0.15
    a[salt] = np.array(codes, dtype)[rng.integers(0, len(codes), salt.sum())]
    if nodata is not None:
        a[NY - 8:, NX - 10:] = nodata
    return a


def make(path, arrays, dtype=gdal.GDT_Byte, nodata=None, options=(),
         names=None, cog=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    drv = gdal.GetDriverByName("MEM" if cog else "GTiff")
    ds = drv.Create("" if cog else path, NX, NY, len(arrays), dtype,
                    [] if cog else list(options))
    ds.SetGeoTransform(GT)
    ds.SetProjection(WKT)
    for b, a in enumerate(arrays, start=1):
        band = ds.GetRasterBand(b)
        band.WriteArray(a)
        if nodata is not None:
            band.SetNoDataValue(nodata)
        if names:
            band.SetDescription(names[b - 1])
    if cog:
        gdal.GetDriverByName("COG").CreateCopy(path, ds, 0, list(options))
    ds = None


def colour_table_of(entries):
    ct = gdal.ColorTable()
    for c, col, _ in entries:
        q = K.QtGui.QColor(col)
        ct.SetColorEntry(c, (q.red(), q.green(), q.blue(), 255))
    return ct


def counts_of(a, nodata=None):
    v, n = np.unique(a, return_counts=True)
    return {int(x): int(k) for x, k in zip(v, n) if x != nodata}


def add_rat(path, entries, counts, colours=True, band=1):
    """A Raster Attribute Table the way a classifier writes one: Value,
    Count, Class_Name and the colour in Red, Green, Blue. Through a handle
    that writes: the GDAL of QGIS 3.44 and 4 drops a table set on a TIFF
    opened only to be read."""
    ds = gdal.Open(path, gdal.GA_Update)
    rat = gdal.RasterAttributeTable()
    rat.CreateColumn("Value", gdal.GFT_Integer, gdal.GFU_MinMax)
    rat.CreateColumn("Count", gdal.GFT_Integer, gdal.GFU_PixelCount)
    rat.CreateColumn("Class_Name", gdal.GFT_String, gdal.GFU_Name)
    if colours:
        rat.CreateColumn("Red", gdal.GFT_Integer, gdal.GFU_Red)
        rat.CreateColumn("Green", gdal.GFT_Integer, gdal.GFU_Green)
        rat.CreateColumn("Blue", gdal.GFT_Integer, gdal.GFU_Blue)
    rat.SetRowCount(len(entries))
    for i, (c, col, name) in enumerate(entries):
        rat.SetValueAsInt(i, 0, c)
        rat.SetValueAsInt(i, 1, counts.get(c, 0))
        rat.SetValueAsString(i, 2, name)
        if colours:
            q = K.QtGui.QColor(col)
            for k, v in enumerate((q.red(), q.green(), q.blue())):
                rat.SetValueAsInt(i, 3 + k, v)
    ds.GetRasterBand(band).SetDefaultRAT(rat)
    ds = None


def add_vat(path, entries, counts):
    """<map>.tif.vat.dbf, the way ArcGIS writes it."""
    out = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(
        path + ".vat.dbf")
    lyr = out.CreateLayer(os.path.basename(path) + ".vat", None, ogr.wkbNone)
    for name, kind in (("Value", ogr.OFTInteger), ("Count", ogr.OFTInteger),
                       ("ClassName", ogr.OFTString), ("Red", ogr.OFTInteger),
                       ("Green", ogr.OFTInteger), ("Blue", ogr.OFTInteger)):
        lyr.CreateField(ogr.FieldDefn(name, kind))
    for c, col, name in entries:
        f = ogr.Feature(lyr.GetLayerDefn())
        q = K.QtGui.QColor(col)
        for k, v in (("Value", c), ("Count", counts.get(c, 0)),
                     ("ClassName", name), ("Red", q.red()),
                     ("Green", q.green()), ("Blue", q.blue())):
            f.SetField(k, v)
        lyr.CreateFeature(f)
    out = None


def write_qml(path, band, entries):
    with open(os.path.splitext(path)[0] + ".qml", "w", encoding="utf-8") as f:
        f.write('<qgis><pipe><rasterrenderer type="paletted" band="%d" '
                'opacity="1"><colorPalette>%s</colorPalette></rasterrenderer>'
                '</pipe></qgis>' % (band, "".join(
                    '<paletteEntry value="%d" color="%s" label="%s"/>'
                    % e for e in entries)))


def paletted(band, entries):
    """The style QGIS gives a layer of this map, as the fakes hold one."""
    return K.Paletted(None, band, [K.Paletted.Class(c, col, name)
                                   for c, col, name in entries])


def by(entries, what):
    return {c: (col if what == "colour" else name) for c, col, name in entries}


CASES = []


def case(name, codes, build, band=1, nodata=None, names=None, colours=None,
         origin=None, renderer=None):
    CASES.append(dict(name=name, codes=codes, build=build, band=band,
                      nodata=nodata, names=names or {}, colours=colours or {},
                      origin=origin, renderer=renderer))


# (1) one band of bytes, as a classifier writes it through GDAL or rasterio:
# no style, no colour table, no nodata
case("byte, nothing else", [1, 2, 3, 4, 5],
     lambda p: make(p, [class_array([1, 2, 3, 4, 5])]),
     names={c: "class %d" % c for c in range(1, 6)}, origin="value")
case("byte with a class 0", [0, 1, 2, 3],
     lambda p: make(p, [class_array([0, 1, 2, 3])], options=["COMPRESS=LZW"]),
     names={0: "class 0"}, origin="value")


# (2) a colour table inside the file; QGIS styles it paletted, every entry
# labelled with its own number, or with the category names when it has them
def with_table(p, category_names=None):
    make(p, [class_array([1, 2, 3, 4])], nodata=0 if category_names else None)
    ds = gdal.Open(p, gdal.GA_Update)
    ds.GetRasterBand(1).SetColorTable(colour_table_of(NAMED))
    if category_names:
        ds.GetRasterBand(1).SetRasterCategoryNames(category_names)
    ds = None


case("byte with a colour table", [1, 2, 3, 4], with_table,
     names={c: "class %d" % c for c in range(1, 5)},
     colours=by(NAMED, "colour"),
     renderer=paletted(1, [(c, col, str(c)) for c, col, _ in NAMED]))
case("byte with a colour table, no style", [1, 2, 3, 4], with_table,
     colours=by(NAMED, "colour"), origin="colour table")
case("byte with a colour table and category names", [1, 2, 3, 4],
     lambda p: with_table(p, ["nodata"] + [n for _, _, n in NAMED]),
     nodata=0, names=by(NAMED, "name"), colours=by(NAMED, "colour"),
     origin="colour table")


# (3) a .qml beside it
def with_qml(p):
    make(p, [class_array([1, 2, 3, 4])], nodata=255)
    write_qml(p, 1, NAMED)


case("byte with a .qml", [1, 2, 3, 4], with_qml, nodata=255,
     names=by(NAMED, "name"), colours=by(NAMED, "colour"), origin="style",
     renderer=paletted(1, NAMED))

# (4) sixteen bits, codes in the thousands, three kinds of nodata
for nd in (0, 255, 65535):
    case("uint16, nodata %d" % nd, [100, 2000, 65000],
         lambda p, nd=nd: make(
             p, [class_array([100, 2000, 65000], nd, np.uint16)],
             dtype=gdal.GDT_UInt16, nodata=nd,
             options=["COMPRESS=DEFLATE", "TILED=YES"]),
         nodata=nd, names={100: "class 100", 65000: "class 65000"})


# (5) a stack whose class band is not the first
case("three bands, the class third", [1, 2, 3, 4],
     lambda p: make(p, [rng.integers(1, 101, (NY, NX)).astype(np.uint8),
                        rng.integers(1, 256, (NY, NX)).astype(np.uint8),
                        class_array([1, 2, 3, 4], 0)], nodata=0,
                    options=["COMPRESS=LZW", "INTERLEAVE=BAND"],
                    names=["probability", "entropy", "class"]),
     band=3, nodata=0)


def stack_with_qml(p):
    make(p, [rng.integers(0, 101, (NY, NX)).astype(np.uint8),
             class_array([1, 2, 3, 4]),
             rng.integers(0, 256, (NY, NX)).astype(np.uint8)],
         options=["COMPRESS=LZW", "INTERLEAVE=PIXEL"])
    write_qml(p, 2, NAMED)


case("three bands with no names, the .qml on band 2", [1, 2, 3, 4],
     stack_with_qml, band=2, names=by(NAMED, "name"),
     renderer=paletted(2, NAMED))
def stack_with_names(p):
    make(p, [rng.integers(1, 101, (NY, NX)).astype(np.uint8),
             class_array([1, 2, 3, 4], 0),
             rng.integers(1, 256, (NY, NX)).astype(np.uint8)], nodata=0,
         options=["COMPRESS=LZW"], names=["probability", "class", "entropy"])
    ds = gdal.Open(p)
    ds.GetGeoTransform()
    ds.GetRasterBand(2).SetRasterCategoryNames(
        ["nodata"] + [n for _, _, n in NAMED])
    ds = None


# the names of the classes of band 2, in the .aux.xml: GDAL reads them only
# once the .aux.xml is in, which the classes window did not wait for
case("three bands, category names on band 2", [1, 2, 3, 4], stack_with_names,
     band=2, nodata=0, names=by(NAMED, "name"), origin="colour table")
case("three bands of floats, the class second", [1, 2, 3],
     lambda p: make(p, [rng.random((NY, NX)).astype(np.float32),
                        class_array([1, 2, 3], -9999, np.float32),
                        rng.random((NY, NX)).astype(np.float32)],
                    dtype=gdal.GDT_Float32, nodata=-9999,
                    options=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES"],
                    names=["probability", "classification", "entropy"]),
     band=2, nodata=-9999)


# (6) the class names in an attribute table
def with_rat(p, colours=True, uint16=False):
    if uint16:
        a = class_array([100, 2000, 65000], 65535, np.uint16)
        make(p, [a], dtype=gdal.GDT_UInt16, nodata=65535)
        add_rat(p, [(100, "#1f78b4", "water"), (2000, "#e6c229", "crops"),
                    (65000, "#1b7f2a", "forest")], counts_of(a, 65535))
        return
    a = class_array([1, 2, 3, 4])
    make(p, [a], nodata=0, options=["COMPRESS=LZW"])
    add_rat(p, NAMED, counts_of(a, 0), colours=colours)


def stack_with_rat(p):
    a = class_array([1, 2, 3, 4], 0)
    make(p, [rng.integers(1, 101, (NY, NX)).astype(np.uint8), a,
             rng.integers(1, 256, (NY, NX)).astype(np.uint8)], nodata=0,
         options=["COMPRESS=LZW"])
    add_rat(p, NAMED, counts_of(a, 0), band=2)


def with_vat(p):
    a = class_array([1, 2, 3, 4])
    make(p, [a], nodata=0)
    add_vat(p, NAMED, counts_of(a, 0))


case("byte with an attribute table", [1, 2, 3, 4], with_rat, nodata=0,
     names=by(NAMED, "name"), colours=by(NAMED, "colour"),
     origin="attribute table")
case("byte with an attribute table of names only", [1, 2, 3, 4],
     lambda p: with_rat(p, colours=False), nodata=0, names=by(NAMED, "name"),
     origin="attribute table")
case("uint16 with an attribute table", [100, 2000, 65000],
     lambda p: with_rat(p, uint16=True), nodata=65535,
     names={100: "water", 2000: "crops", 65000: "forest"},
     origin="attribute table")
# a stack keeps its tables in the .aux.xml, which the handle Correct holds
# open writes when it closes: its table is rewritten once it has
case("three bands, an attribute table on band 2", [1, 2, 3, 4],
     stack_with_rat, band=2, nodata=0, names=by(NAMED, "name"),
     colours=by(NAMED, "colour"), origin="attribute table")
case("byte with a .tif.vat.dbf", [1, 2, 3, 4], with_vat, nodata=0,
     names=by(NAMED, "name"), colours=by(NAMED, "colour"),
     origin="attribute table")
# QGIS 3.44 and 4 style a .vat.dbf paletted, with its names and colours of
# their own: the colours of the table are the map's
case("byte with a .tif.vat.dbf, styled by QGIS 4", [1, 2, 3, 4], with_vat,
     nodata=0, names=by(NAMED, "name"), colours=by(NAMED, "colour"),
     origin="style",
     renderer=paletted(1, [(c, "#%06x" % (0x123456 * c), n)
                           for c, _, n in NAMED]))

# (7) BigTIFF, tiled and compressed; and strips, uncompressed
for comp in ("LZW", "DEFLATE"):
    case("BigTIFF, %s, tiled" % comp, [1, 2, 3, 4],
         lambda p, comp=comp: make(
             p, [class_array([1, 2, 3, 4], 255)], nodata=255,
             options=["COMPRESS=%s" % comp, "TILED=YES", "BLOCKXSIZE=32",
                      "BLOCKYSIZE=32", "BIGTIFF=YES"]), nodata=255)
case("strips, uncompressed", [1, 2, 3, 4],
     lambda p: make(p, [class_array([1, 2, 3, 4])], options=["BLOCKYSIZE=8"]))

# (8) a cloud optimised GeoTIFF
case("cloud optimised GeoTIFF", [1, 2, 3, 4],
     lambda p: make(p, [class_array([1, 2, 3, 4], 0)], nodata=0, cog=True,
                    options=["COMPRESS=DEFLATE", "BLOCKSIZE=32",
                             "OVERVIEWS=AUTO", "OVERVIEW_RESAMPLING=MODE"]),
     nodata=0)


# ------------------------------------------------------------ looking
def structure(path):
    ds = gdal.Open(path)
    out = {"size": (ds.RasterXSize, ds.RasterYSize),
           "gt": ds.GetGeoTransform(), "srs": ds.GetProjection(),
           "layout": {k: v for k, v in
                      (ds.GetMetadata("IMAGE_STRUCTURE") or {}).items()
                      if k in ("COMPRESSION", "INTERLEAVE", "PREDICTOR")},
           "bands": [(gdal.GetDataTypeName(ds.GetRasterBand(b).DataType),
                      ds.GetRasterBand(b).GetNoDataValue(),
                      ds.GetRasterBand(b).GetDescription(),
                      tuple(ds.GetRasterBand(b).GetBlockSize()))
                     for b in range(1, ds.RasterCount + 1)]}
    ds = None
    with open(path, "rb") as f:
        out["bigtiff"] = f.read(4) in (b"II\x2b\x00", b"MM\x00\x2b")
    return out


def arrays(path):
    ds = gdal.Open(path)
    out = [ds.GetRasterBand(b).ReadAsArray() for b in range(1, ds.RasterCount + 1)]
    ds = None
    return out


def palette_of(qml):
    r = ET.parse(qml).getroot().find("pipe/rasterrenderer")
    return (r.get("type"), int(r.get("band")),
            [(int(e.get("value")), e.get("color"), e.get("label"))
             for e in r.find("colorPalette")])


def files_of(folder):
    out = {}
    for n in sorted(os.listdir(folder)):
        with open(os.path.join(folder, n), "rb") as f:
            out[n] = f.read()
    return out


class NamedProvider(K.Provider):
    """Band names as QGIS gives them, "Band 3: class", from the file."""
    def generateBandName(self, b):
        ds = gdal.Open(self.layer.path)
        name = ds.GetRasterBand(b).GetDescription()
        ds = None
        return "Band %d" % b + (": " + name if name else "")


class Named(K.Layer):
    def dataProvider(self):
        return NamedProvider(self)


def rows_of(d):
    return [(r["value"].value(), r["swatch"].property("colour"),
             r["name"].text(), r["origin"].text()) for r in d.rows]


def walk(c):
    tag = c["name"]

    def check(what, cond, detail=""):
        K.check("%s: %s" % (tag, what), cond, detail)

    print()
    print(tag)
    stem = "map_%02d" % len(seen_names)
    seen_names.append(tag)
    data = os.path.join(root, stem, "data")
    src = os.path.join(data, stem + ".tif")
    PATHS[tag] = src
    c["build"](src)
    folder = os.path.join(root, stem, "correction")
    before = files_of(data)
    src_struct = structure(src)
    src_arrays = arrays(src)
    ds = gdal.Open(src)
    SOURCE_INTERP[tag] = ds.GetRasterBand(c["band"]).GetColorInterpretation()
    had_table = ds.GetRasterBand(c["band"]).GetColorTable() is not None
    is_byte = ds.GetRasterBand(c["band"]).DataType == gdal.GDT_Byte
    ds = None
    band = c["band"]
    K.LOADED.clear()
    layer = K.add_layer(Named(src, stem, renderer=c["renderer"],
                              lid="layer_" + stem))
    panel = g["Panel"]()
    seen = {}

    def new(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText("fix")
        d.raster.setCurrentIndex(d.raster.findData(layer.id()))
        d.fill_bands()
        seen["offered"] = d.band.currentData()
        d.band.setCurrentIndex(d.band.findData(band))
        d.folder.setText(folder)
        d.operator.setText("ann")
        return 1

    def confirm(d):
        seen["rows"] = rows_of(d)
        d.add_blank()
        d.rows[-1]["name"].setText("burnt area")
        seen["added"] = d.rows[-1]["value"].value()
        seen["complaints"] = d.complaints()
        return 0 if seen["complaints"] else 1

    K.ANSWERS["OpenCorrection"] = new
    K.ANSWERS["ConfirmClasses"] = confirm
    panel.toggle_module(1)
    section = panel.section
    check("Correct opened on it", type(section).__name__ == "CorrectionSection",
          (K.BOXES[-2:], K.UNEXPECTED))
    if type(section).__name__ != "CorrectionSection":
        return
    check("the window offered the class band", seen["offered"] == band,
          seen["offered"])
    rows = seen["rows"]
    print("  the classes window: %s" % rows)
    check("it lists every code of the map, and nodata is none",
          [r[0] for r in rows] == sorted(c["codes"]) and not seen["complaints"],
          (rows, seen["complaints"]))
    for code, want in c["names"].items():
        check("class %d is named %r" % (code, want),
              [r[2] for r in rows if r[0] == code] == [want], rows)
    for code, want in c["colours"].items():
        check("class %d is %s" % (code, want),
              [r[1] for r in rows if r[0] == code] == [want], rows)
    if c["origin"]:
        check("read from its %s" % c["origin"],
              {r[3] for r in rows} == {c["origin"]}, rows)

    copy = section.path
    manifest = panel.correction.manifest_path
    codes = sorted(c["codes"])
    added = seen["added"]
    w = NX // len(codes)

    def stroke(col, row, wide, tall, frm, into):
        inside = np.ones((tall, wide), bool)
        section.mask_of = lambda geom: (col, row, inside)
        section.choose_from(frm)
        section.choose_class(into)
        section.paint(K.Stroke())

    stroke(2, 2, 10, 10, None, added)
    first = arrays(copy)[band - 1]
    section.undo()
    stroke(w, 10, w, 20, codes[1], codes[0])
    stroke(4, 40, 16, 10, None, added)
    section.save()
    check("the undone stroke had changed the copy",
          not np.array_equal(first, src_arrays[band - 1]))

    def again(d):
        for r in d.rows:
            if r["value"].value() == codes[0]:
                r["name"].setText("renamed")
        return 1
    K.ANSWERS["ConfirmClasses"] = again
    panel.correction_classes()
    panel.close_correction()
    check("closed", panel.correction is None)
    book = panel.read_correction(manifest)
    panel.start_correction(book)
    panel.show_correction()
    check("it opens again", type(panel.section).__name__ == "CorrectionSection")
    panel.close_correction()
    classes = json.load(open(manifest, encoding="utf-8"))["classes"]
    check("its classes carry the rename and the class added",
          any(x["code"] == codes[0] and x["name"] == "renamed" for x in classes)
          and any(x["code"] == added and x["name"] == "burnt area"
                  for x in classes), classes)

    # the corrected map has the structure of the map
    after = structure(copy)
    for k in ("size", "gt", "srs", "layout", "bigtiff"):
        check("the copy has the %s of the map" % k, after[k] == src_struct[k],
              (src_struct[k], after[k]))
    check("band for band: type, nodata, name, blocks",
          after["bands"] == src_struct["bands"],
          (src_struct["bands"], after["bands"]))
    now = arrays(copy)
    check("every other band is byte for byte the map's",
          all(now[b].tobytes() == src_arrays[b].tobytes()
              for b in range(len(now)) if b != band - 1))
    marks = arrays(os.path.join(os.path.dirname(copy),
                                book.data["changes"]))[0].astype(bool)
    was, got = src_arrays[band - 1], now[band - 1]
    check("every pixel nobody painted is the map's",
          got[~marks].tobytes() == was[~marks].tobytes())
    check("the record marks exactly the pixels that changed",
          np.array_equal(marks, was != got), (int(marks.sum()),
                                              int((was != got).sum())))
    check("and the strokes wrote what they were told",
          set(np.unique(got[marks]).astype(int).tolist()) == {codes[0], added},
          np.unique(got[marks]))
    want = [(x["code"], x["colour"], x["name"]) for x in classes]
    kind, qband, palette = palette_of(os.path.splitext(copy)[0] + ".qml")
    check("its .qml draws the class band in the classes of the correction",
          (kind, qband, palette) == ("paletted", band, want),
          (kind, qband, palette))
    ds = gdal.Open(copy)
    ds.GetGeoTransform()        # GDAL reads the .aux.xml only from here on
    b = ds.GetRasterBand(band)
    ct = b.GetColorTable()
    names = list(b.GetCategoryNames() or [])
    check("its category names are the correction's",
          all(names[x["code"]] == x["name"] for x in classes), names[:8])
    if (ds.RasterCount == 1 or band == 1) and (is_byte or had_table):
        check("and so is its colour table",
              ct is not None and all(
                  "#%02x%02x%02x" % ct.GetColorEntry(x["code"])[:3]
                  == x["colour"] for x in classes),
              ct and [ct.GetColorEntry(i) for i in range(min(ct.GetCount(),
                                                             8))])
    elif ds.RasterCount == 1 or band == 1:
        # A TIFF gives a band of sixteen bits a table of 65536 entries, and
        # QGIS 3.36 then takes ten seconds to open the map: one that came
        # with no table gets none
        check("a band wider than a byte that came with no colour table is "
              "given none", ct is None and b.GetColorInterpretation()
              == SOURCE_INTERP[tag], (ct, b.GetColorInterpretation()))
    else:
        # GDAL reads a table back on band 1 only: one written further down
        # was never seen again and made the band a palette with no colours
        check("a class band further down has no colour table GDAL cannot "
              "read, and keeps its colour interpretation",
              ct is None and b.GetColorInterpretation()
              == SOURCE_INTERP[tag], (ct, b.GetColorInterpretation()))
    b = ct = None
    ds = None
    counts = counts_of(got, c["nodata"])
    real = {x["code"]: x for x in classes}
    tables = []
    if g["attribute_table"](src, band) is not None:
        tables.append(("attribute table", g["attribute_table"](copy, band)))
    if os.path.exists(src + ".vat.dbf"):
        tables.append((".tif.vat.dbf", g["table_of_vat"](copy)))
    for what, table in tables:
        check("the copy has its own %s" % what, table is not None)
        if table is None:
            continue
        told = g["classes_of_table"](table)
        roles = g["table_roles"](table)
        check("its %s names the correction's classes" % what,
              {k: v["name"] for k, v in told.items()}
              == {k: v["name"] for k, v in real.items()}, told)
        if roles["red"] is not None:
            check("in their colours", {k: v["colour"] for k, v in told.items()}
                  == {k: v["colour"] for k, v in real.items()}, told)
        if roles["count"] is not None:
            have = {int(r[roles["value"]]): int(r[roles["count"]])
                    for r in table["rows"]}
            check("with the pixel counts of the corrected map",
                  have == {k: counts.get(k, 0) for k in real}, (have, counts))
    check("the map and every file beside it are byte for byte as they were",
          files_of(data) == before, sorted(files_of(data)))
    panel.close()


seen_names = []
PATHS = {}
SOURCE_INTERP = {}
try:
    for c in CASES:
        walk(c)

    print()
    print("a few things on their own")
    big = PATHS["BigTIFF, LZW, tiled"]
    K.check("a BigTIFF is known by its header",
            g["is_bigtiff"](gdal.Open(big))
            and not g["is_bigtiff"](gdal.Open(PATHS["byte, nothing else"])))
    table = {"columns": [{"name": "Histogram", "kind": "real", "usage": 0},
                         {"name": "Red", "kind": "real", "usage": 0},
                         {"name": "Green", "kind": "real", "usage": 0},
                         {"name": "Blue", "kind": "real", "usage": 0},
                         {"name": "Class_Names", "kind": "text", "usage": 0}],
             "rows": [[10.0, 0.0, 0.0, 0.0, ""], [5.0, 1.0, 0.5, 0.0, "a"]]}
    K.check("a table with no column of values is read by row, its colours "
            "from 0 to 1",
            g["classes_of_table"](table) == {
                0: {"name": "", "colour": "#000000"},
                1: {"name": "a", "colour": "#ff8000"}},
            g["classes_of_table"](table))
    rows = g["table_rows_for"](table, [{"code": 1, "name": "b",
                                        "colour": "#00ff00"},
                                       {"code": 3, "name": "c",
                                        "colour": "#0000ff"}], {1: 7, 3: 2})
    K.check("and rewritten by row, to the highest code",
            rows == [[0.0, 0.0, 0.0, 0.0, ""], [7.0, 0.0, 1.0, 0.0, "b"],
                     [0.0, 0.0, 0.0, 0.0, ""], [2.0, 0.0, 0.0, 1.0, "c"]],
            rows)
    ranged = gdal.RasterAttributeTable()
    ranged.CreateColumn("Min", gdal.GFT_Real, gdal.GFU_Min)
    ranged.CreateColumn("Max", gdal.GFT_Real, gdal.GFU_Max)
    ranged.CreateColumn("Name", gdal.GFT_String, gdal.GFU_Name)
    ranged.SetRowCount(2)
    binned = gdal.RasterAttributeTable()
    binned.CreateColumn("Name", gdal.GFT_String, gdal.GFU_Name)
    binned.SetRowCount(2)
    binned.SetLinearBinning(10.0, 5.0)
    plain = gdal.RasterAttributeTable()
    plain.CreateColumn("Name", gdal.GFT_String, gdal.GFU_Name)
    plain.SetRowCount(2)
    plain.SetLinearBinning(0.0, 1.0)
    K.check("a table of ranges, the legend of a continuous band, is not read "
            "as classes", g["table_of_rat"](ranged) is None
            and g["table_of_rat"](binned) is None
            and g["table_of_rat"](plain) is not None)
    # ArcGIS writes a .vat.dbf of Value and Count alone: a row for every
    # class and a name for none, and the window must not say it names them.
    bare = os.path.join(root, "bare", "data", "bare.tif")
    a = np.resize(np.array([[1, 2], [3, 3]], np.uint8), (NY, NX))
    make(bare, [a])
    out = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(
        bare + ".vat.dbf")
    lyr = out.CreateLayer("bare.tif.vat", None, ogr.wkbNone)
    for name in ("Value", "Count"):
        lyr.CreateField(ogr.FieldDefn(name, ogr.OFTInteger))
    for v in (1, 2, 3):
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("Value", v)
        f.SetField("Count", 1)
        lyr.CreateFeature(f)
    f = lyr = out = None
    notes = []
    got = g["thematic_classes"](a, None, None, 1, bare, notes)
    K.check("a table of values and counts alone names no class",
            [(x["code"], x["name"], x["origin"]) for x in got]
            == [(1, "class 1", "value"), (2, "class 2", "value"),
                (3, "class 3", "value")]
            and not any("names" in n for n in notes), (got, notes))
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
