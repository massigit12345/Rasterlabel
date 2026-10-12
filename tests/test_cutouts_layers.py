"""Cutouts of an orthomosaic of seven bands and a map of classes, real files.

The case that started this: a survey of seven bands of sixteen bits, nodata
65535, in WGS 84 with a TOWGS84 of seven zeros, which GDAL reads as a BOUNDCRS,
and beside it a map of classes of five bands of bytes in plain EPSG:4326, on
the same grid. Every cutout came out with the classes alone, in whichever
order the two layers stood in the Layers panel: the two systems were compared
by definition, the definitions differ, and the image was left out with a
warning that the next message covered. This suite cuts the two with both
orders of the tree and reads back what is on disk:

  both layers are written, whichever is on top, and the one on top sets the
  grid;
  the image is the source as it is: seven bands, UInt16, nodata 65535 on
  every band, red, green and blue on the first three, the same numbers;
  its PNG is a picture of the style, transparent where there is no data;
  no file carries the BOUNDCRS on: they are all in EPSG:4326 by its code;
  a classes layer written as PNG keeps its codes and gets a coloured copy;
  a layer in a system that really is another is reprojected onto the grid,
  with the common grid on or off;
  a layer with no system beside one that has one is left out, and the panel,
  the message and the catalogue say what was written, not what was asked;
  the cut is logged in the folder of the program, not in the cutouts folder;
  the books: losing focus does not forget the session, undo takes the
  footprint and the sampler note with it, and cutouts deleted by hand are
  counted, reported and never overwritten, their STAC items kept and left
  out of the catalogue;
  a folder whose paths run past 260 characters still gets its cutout.

Needs the GDAL Python bindings: the rasters, the GeoPackage and the PNGs are
real. QGIS is faked, see correctkit.py; the two QGIS functions that compare
systems on the ground are stood in for by the same questions asked of PROJ.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import json
import os
import shutil
import struct
import sys
import tempfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                                 # noqa: E402
from osgeo import gdal, ogr, osr                                   # noqa: E402
import correctkit as K                                             # noqa: E402
from qtbinding import QtGui                                            # noqa: E402

gdal.UseExceptions()
g, check = K.g, K.check

root = tempfile.mkdtemp(prefix="rl_cutouts_layers_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
data = os.path.join(root, "data")
os.makedirs(data)

W, H = 160, 120
OX, OY = 13.5990013256354, 37.3761109187442
PX, PY = 5.64480000000066e-07, 4.50487999999668e-07
STRIP = 20                         # columns of nodata on the left of the image


def boundcrs_image(path):
    """Seven bands of UInt16 with the geokeys of the real survey, written by
    hand because GDAL drops a TOWGS84 of zeros when it writes one itself."""
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:H, 0:W]
    bands = [(2000 + 300 * b + xx * 7 + yy * 3
              + rng.integers(0, 3000, (H, W))).astype(np.uint16)
             for b in range(7)]
    img = np.stack(bands, axis=-1)
    img[:, :STRIP, :] = 65535
    pix = img.astype("<u2").tobytes()
    doubles = [0.0174532925199433, 6378137.0, 298.257223563, 0.0] + [0.0] * 7
    keys = [(1024, 0, 1, 2), (1025, 0, 1, 1), (2048, 0, 1, 4326),
            (2049, 34737, 7, 0), (2050, 0, 1, 6326), (2051, 0, 1, 8901),
            (2054, 0, 1, 9102), (2055, 34736, 1, 0), (2056, 0, 1, 7030),
            (2057, 34736, 1, 1), (2059, 34736, 1, 2), (2061, 34736, 1, 3),
            (2062, 34736, 7, 4), (4099, 0, 1, 9001)]
    gkd = [1, 1, 0, len(keys)]
    for k in keys:
        gkd += list(k)
    entries = [(256, 3, [W]), (257, 3, [H]), (258, 3, [16] * 7),
               (259, 3, [1]), (262, 3, [2]), (273, 4, [0]), (277, 3, [7]),
               (278, 3, [H]), (279, 4, [len(pix)]), (284, 3, [1]),
               (338, 3, [0, 0, 0, 0]), (339, 3, [1] * 7),
               (33550, 12, [PX, PY, 0.0]),
               (33922, 12, [0.0, 0.0, 0.0, OX, OY, 0.0]),
               (34735, 3, gkd), (34736, 12, doubles),
               (34737, 2, list(b"WGS 84|\x00")),
               (42113, 2, list(b"65535\x00"))]
    fmt = {2: "B", 3: "H", 4: "I", 12: "d"}
    data_off = 8 + 2 + len(entries) * 12 + 4
    blobs, ifd, strip_pos = b"", struct.pack("<H", len(entries)), None
    for tag, typ, vals in entries:
        raw = struct.pack("<%d%s" % (len(vals), fmt[typ]), *vals)
        if len(raw) <= 4:
            ifd += struct.pack("<HHI", tag, typ, len(vals)) + raw.ljust(4, b"\0")
            if tag == 273:
                strip_pos = len(ifd) - 4
        else:
            ifd += struct.pack("<HHII", tag, typ, len(vals),
                               data_off + len(blobs))
            blobs += raw + (b"\0" if len(raw) % 2 else b"")
    ifd += struct.pack("<I", 0)
    ifd = (ifd[:strip_pos] + struct.pack("<I", data_off + len(blobs))
           + ifd[strip_pos + 4:])
    with open(path, "wb") as f:
        f.write(b"II*\x00" + struct.pack("<I", 8) + ifd + blobs + pix)
    return img


def classes_map(path, wkt=None):
    codes = np.ones((H, W), np.uint8)
    codes[:, 40:80] = 2
    codes[:, 80:120] = 3
    codes[:, 120:] = 4
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds = gdal.GetDriverByName("GTiff").Create(path, W, H, 5, gdal.GDT_Byte)
    ds.SetGeoTransform((OX, PX, 0.0, OY, 0.0, -PY))
    ds.SetProjection(wkt or srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(codes)
    ds.GetRasterBand(1).SetDescription("classe")
    for b in range(2, 6):
        ds.GetRasterBand(b).WriteArray(np.zeros((H, W), np.uint8))
    ds = None
    return codes


IMAGE = os.path.join(data, "aragona_settembre_2025.tif")
CLASSES = os.path.join(data, "72_mappa_2025_47riquadri_fold.tif")
source = boundcrs_image(IMAGE)
codes = classes_map(CLASSES)
image_wkt = gdal.Open(IMAGE).GetProjection()
check("the synthetic image is read by GDAL as a BOUNDCRS",
      "BOUNDCRS" in gdal.Open(IMAGE).GetSpatialRef().ExportToWkt(
          ["FORMAT=WKT2"]), image_wkt[:60])


# ------------------------------------------------------- systems, on PROJ
class System(K.Crs):
    """A coordinate system known by its WKT, and by its code when it has one.
    == compares the definitions, which is what QGIS does and what used to
    leave the image out."""
    def __init__(self, wkt, authid=""):
        super().__init__(authid)
        self._wkt = wkt
    def isValid(self): return bool(self._wkt)
    def toWkt(self, *a): return self._wkt
    def description(self): return "WGS 84 bound to WGS 84" if not self._a \
        else self._a
    def __eq__(self, o):
        return isinstance(o, System) and (o._wkt, o._a) == (self._wkt, self._a)
    def __ne__(self, o): return not self.__eq__(o)


def epsg(code):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(code)
    return System(srs.ExportToWkt(), "EPSG:%d" % code)


def proj_same_ground(a, b, near=None):
    """same_ground() asked of PROJ: a point of a moved into b stays put."""
    sa, sb = osr.SpatialReference(), osr.SpatialReference()
    sa.ImportFromWkt(a.toWkt())
    sb.ImportFromWkt(b.toWkt())
    for s in (sa, sb):
        s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    if bool(sa.IsGeographic()) != bool(sb.IsGeographic()):
        return False
    x, y = near if near is not None else (OX, OY)
    out = osr.CoordinateTransformation(sa, sb).TransformPoint(x, y)
    return abs(out[0] - x) < 1e-9 and abs(out[1] - y) < 1e-9


def proj_named_crs(crs, near=None):
    """named_crs() asked of PROJ: a code it is sure of, the same on the
    ground."""
    if crs is None or not crs.isValid() or crs.authid():
        return crs
    srs = osr.SpatialReference()
    srs.ImportFromWkt(crs.toWkt())
    for match, confidence in srs.FindMatches() or []:
        if confidence < 100:
            continue
        code = "%s:%s" % (match.GetAuthorityName(None),
                          match.GetAuthorityCode(None))
        if code.startswith("EPSG:"):
            candidate = epsg(int(code[5:]))
            if proj_same_ground(crs, candidate, near):
                return candidate
    return crs


class AnySystem(System):
    """QgsCoordinateReferenceSystem as the catalogue and the sampler use it:
    made from a code or read from a WKT, named by PROJ when it can."""
    def __init__(self, text=""):
        if text.upper().startswith("EPSG:"):
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(int(text[5:]))
            super().__init__(srs.ExportToWkt(), text.upper())
        else:
            super().__init__("", "")
    def createFromWkt(self, wkt):
        srs = osr.SpatialReference()
        if not wkt or srs.ImportFromWkt(wkt) != 0:
            return False
        self._wkt = wkt
        srs.AutoIdentifyEPSG()
        code = srs.GetAuthorityCode(None)
        self._a = "EPSG:%s" % code if code and "BOUNDCRS" not in \
            srs.ExportToWkt(["FORMAT=WKT2"]) else ""
        return True


class Transform:
    """QgsCoordinateTransform, by PROJ."""
    def __init__(self, a, b, *rest):
        sa, sb = osr.SpatialReference(), osr.SpatialReference()
        sa.ImportFromWkt(a.toWkt())
        sb.ImportFromWkt(b.toWkt())
        for one in (sa, sb):
            one.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        self.t = osr.CoordinateTransformation(sa, sb)
    def transform(self, p):
        x, y, _ = self.t.TransformPoint(p.x(), p.y())
        return K.Point(x, y)
    def transformBoundingBox(self, r):
        a = self.transform(K.Point(r.xMinimum(), r.yMinimum()))
        b = self.transform(K.Point(r.xMaximum(), r.yMaximum()))
        return K.Rect(a.x(), a.y(), b.x(), b.y())


g["QgsCoordinateReferenceSystem"] = AnySystem
g["QgsCoordinateTransform"] = Transform
g["same_ground"] = proj_same_ground
g["named_crs"] = proj_named_crs
g["crs_label"] = lambda crs, near=None: (
    proj_named_crs(crs).authid() or "a custom system")


class Provider(K.Provider):
    """Band names as QGIS makes them: "Band 1: classe" when the band has a
    description, which is how the map of classes is told from an image."""
    def generateBandName(self, b):
        ds = gdal.Open(self.layer.path)
        text = ds.GetRasterBand(b).GetDescription()
        ds = None
        return "Band %d: %s" % (b, text) if text else "Band %d" % b


class Layer(K.Layer):
    def __init__(self, path, name, system, renderer=None):
        super().__init__(path, name, renderer)
        self.system = system
    def crs(self): return self.system
    def dataProvider(self): return Provider(self)


class Contrast:
    def __init__(self, low, high): self.low, self.high = low, high
    def minimumValue(self): return self.low
    def maximumValue(self): return self.high


class Bands(g["QgsMultiBandColorRenderer"]):
    """The style of the image: bands 3, 2, 1 stretched between two values,
    and, when given a picture, the picture QGIS would draw."""
    def __init__(self, drawn=None):
        self.drawn = drawn
    def type(self): return "multibandcolor"
    def redBand(self): return 3
    def greenBand(self): return 2
    def blueBand(self): return 1
    def redContrastEnhancement(self): return Contrast(4000, 9000)
    def greenContrastEnhancement(self): return Contrast(4000, 9000)
    def blueContrastEnhancement(self): return Contrast(4000, 9000)
    def block(self, band, extent, w, h):
        return None if self.drawn is None else self.drawn(extent, w, h)


class Block:
    def __init__(self, image): self._image = image
    def isValid(self): return True
    def image(self): return self._image


def painted(extent, w, h):
    """What a renderer hands back: an ARGB picture of the window, opaque
    orange where the image has data and transparent over the strip."""
    image = QtGui.QImage(w, h, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QtGui.QColor(255, 128, 0, 255))
    left = int(round((OX + STRIP * PX - extent.xMinimum()) / PX))
    for x in range(max(0, min(left, w))):
        for y in range(h):
            image.setPixelColor(x, y, QtGui.QColor(0, 0, 0, 0))
    return Block(image)


IMAGE_SYSTEM = System(image_wkt)
CLASSES_SYSTEM = epsg(4326)
check("the two systems differ by definition", IMAGE_SYSTEM != CLASSES_SYSTEM)
check("and are one on the ground",
      proj_same_ground(IMAGE_SYSTEM, CLASSES_SYSTEM)
      and proj_named_crs(IMAGE_SYSTEM).authid() == "EPSG:4326")

# The Layers panel, top first, which the kit's project does not have.
TREE_ORDER = []


class TreeNode:
    def __init__(self, lid): self.lid = lid
    def layerId(self): return self.lid


K.Root.findLayers = lambda self: [TreeNode(i) for i in TREE_ORDER]

VIEW = [CLASSES_SYSTEM]


class Canvas(object):
    def extent(self): return K.Dummy()
    def mapSettings(self):
        m = K.Dummy()
        m.destinationCrs = lambda: VIEW[0]
        return m
    def __getattr__(self, n): return lambda *a, **k: None


g["canvas"] = lambda: Canvas()


def load(image_on_top, drawn=None, classes_path=CLASSES,
         classes_system=CLASSES_SYSTEM, names=None):
    K.LOADED.clear()
    K.TREE.clear()
    names = names or ("aragona_settembre_2025", "72_mappa_2025_47riquadri_fold")
    img = K.add_layer(Layer(IMAGE, names[0], IMAGE_SYSTEM,
                            Bands(drawn)))
    cls = K.add_layer(Layer(classes_path, names[1],
                            classes_system, K.Paletted(None, 1, [
                                K.Paletted.Class(1, "#333333", "fango"),
                                K.Paletted.Class(2, "#dddddd", "secco"),
                                K.Paletted.Class(3, "#d4a050", "suolo"),
                                K.Paletted.Class(4, "#2e8b57", "verde")])))
    TREE_ORDER[:] = ([img.id(), cls.id()] if image_on_top
                     else [cls.id(), img.id()])
    VIEW[0] = IMAGE_SYSTEM if image_on_top else CLASSES_SYSTEM
    return img, cls


def window(c0, r0, c1, r1):
    """The rectangle of these columns and rows of the two rasters."""
    return K.Rect(OX + c0 * PX, OY - r1 * PY, OX + c1 * PX, OY - r0 * PY)


def rows_of(folder):
    with open(os.path.join(folder, "cutouts.csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def code_of(path):
    ds = gdal.Open(path)
    srs = ds.GetSpatialRef()
    return srs.GetAuthorityCode(None) if srs is not None else None


def open_cutouts(folder):
    # The folder first, in the settings, as a person who had been cutting
    # into it would have it: a Cutouts that opens on the folder of the last
    # scenario takes the layers that folder remembers (layers.json), and
    # these scenarios are each a fresh folder.
    g["write_setting"](g["SETTINGS_ROOT"] + "/cutouts/folder", folder)
    panel = g["Panel"]()
    panel.toggle_module(3)
    cut = panel.section
    if cut is None:
        print("Cutouts did not open:", K.BOXES[-3:], K.SAID[-3:])
    cut.folder_box.setText(folder)
    cut.folder_changed()
    for box in (cut.png, cut.common, cut.same_size, cut.stac):
        box.setChecked(True)
    return panel, cut


IMG_TAG, CLS_TAG = "aragona_settembre_2025", "72_mappa_2025_47riquadri_fold"
PICK = window(10, 10, 70, 60)          # half on the nodata strip, 60 x 50

try:
    for on_top in (True, False):
        word = "the image on top" if on_top else "the classes on top"
        print()
        print("GeoTIFF, %s" % word)
        load(on_top)
        out = os.path.join(root, "geotiff_%s" % ("image" if on_top else "cls"))
        panel, cut = open_cutouts(out)
        top = IMG_TAG if on_top else CLS_TAG
        check("the layer on top of the tree sets the grid",
              cut.sources[0]["tag"] == top, [s["tag"] for s in cut.sources])
        check("both layers are to be cut", sorted(
            (s["tag"], s["role"]) for s in cut.sources)
            == [(CLS_TAG, "classes"), (IMG_TAG, "image")], cut.sources)
        K.SAID[:] = []
        done = cut.export(PICK, nominal=None)
        check("the cutout is written", done, K.BOXES[-3:])
        files = K.everything_under(out)
        for name in ("cut_0001_%s_image.tif" % IMG_TAG,
                     "cut_0001_%s_image.png" % IMG_TAG,
                     "cut_0001_%s_classes.tif" % CLS_TAG,
                     "cut_0001_%s_classes.png" % CLS_TAG):
            check("%s is written" % name, name in files, files)
        check("nothing was left out", cut.skipped == {}, cut.skipped)
        check("the message says what was cut, and nothing was left out",
              [m for m in K.SAID if "cut_0001 written" in m
               and "left out" not in m and "as image" in m
               and "as classes" in m], K.SAID[-3:])

        tif = os.path.join(out, "cut_0001_%s_image.tif" % IMG_TAG)
        ds = gdal.Open(tif)
        check("the image has its seven bands", ds.RasterCount == 7,
              ds.RasterCount)
        check("in UInt16, its own type",
              gdal.GetDataTypeName(ds.GetRasterBand(1).DataType) == "UInt16")
        check("with its nodata on every band",
              [ds.GetRasterBand(b).GetNoDataValue() for b in range(1, 8)]
              == [65535.0] * 7)
        check("red, green and blue on the first three bands",
              [ds.GetRasterBand(b).GetColorInterpretation()
               for b in (1, 2, 3)] == [gdal.GCI_RedBand, gdal.GCI_GreenBand,
                                       gdal.GCI_BlueBand],
              [gdal.GetColorInterpretationName(
                  ds.GetRasterBand(b).GetColorInterpretation())
               for b in (1, 2, 3)])
        got = ds.ReadAsArray()
        want = source[10:60, 10:70, :].transpose(2, 0, 1)
        check("the very numbers of the source, every band",
              got.shape == want.shape and np.array_equal(got, want),
              got.shape)
        check("on the grid of the window",
              abs(ds.GetGeoTransform()[0] - (OX + 10 * PX)) < 1e-12
              and abs(ds.GetGeoTransform()[1] - PX) < 1e-15)
        ds = None
        check("in EPSG:4326 by its code, the binding is not carried on",
              code_of(tif) == "4326", gdal.Open(tif).GetProjection()[:80])
        cls_tif = os.path.join(out, "cut_0001_%s_classes.tif" % CLS_TAG)
        check("the classes keep their codes",
              np.array_equal(gdal.Open(cls_tif).ReadAsArray(),
                             codes[10:60, 10:70]))
        check("and are in EPSG:4326 too", code_of(cls_tif) == "4326")
        # It used to open grey: the classes of the layer's style went into
        # the PNG beside it and nowhere in the GeoTIFF.
        ds = gdal.Open(cls_tif)
        ct = ds.GetRasterBand(1).GetColorTable()
        names = list(ds.GetRasterBand(1).GetCategoryNames() or [])
        check("they carry the classes of the layer's style as a colour table",
              ct is not None and ct.GetColorEntry(3)[:3] == (0xd4, 0xa0, 0x50)
              and ct.GetColorEntry(4)[:3] == (0x2e, 0x8b, 0x57),
              ct and [ct.GetColorEntry(i) for i in range(ct.GetCount())])
        check("and category names, so a GIS opens them in colour",
              names[1:5] == ["fango", "secco", "suolo", "verde"], names)
        check("with the codes untouched by it",
              np.array_equal(ds.ReadAsArray(), codes[10:60, 10:70]))
        ds = None
        png = gdal.Open(os.path.join(out, "cut_0001_%s_image.png" % IMG_TAG))
        picture = png.ReadAsArray()
        check("the picture of the image has four bands of bytes",
              png.RasterCount == 4
              and png.GetRasterBand(1).DataType == gdal.GDT_Byte)
        check("transparent over the nodata, opaque elsewhere",
              (picture[3, :, :STRIP - 10] == 0).all()
              and (picture[3, :, STRIP - 10:] == 255).all())
        expected = np.clip((source[10:60, 10:70, 2].astype(float) - 4000)
                           / 5000.0, 0, 1) * 255
        check("stretched by the style: band 3 in red, by its limits",
              np.abs(picture[0, :, 20:].astype(float)
                     - expected[:, 20:]).max() <= 1.0)
        rows = rows_of(out)
        check("cutouts.csv has a row for each layer written",
              sorted(r["role"] for r in rows) == ["classes", "image"], rows)
        image_row = [r for r in rows if r["role"] == "image"][0]
        check("and the image row lists all seven bands",
              image_row["bands"] == "1 2 3 4 5 6 7", image_row["bands"])
        check("and how its picture was made",
              image_row["stretch"] == "layer limits", image_row["stretch"])
        item = json.load(open(os.path.join(out, "stac", "cut_0001.json"),
                              encoding="utf-8"))
        check("the STAC item has the roles really written",
              item["properties"]["rasterlabel:roles"] == ["classes", "image"])
        check("every asset it lists is on disk", all(
            os.path.exists(os.path.normpath(os.path.join(out, "stac",
                                                         a["href"])))
            for a in item["assets"].values()), sorted(item["assets"]))
        check("it is in EPSG:4326", item["properties"].get("proj:epsg") == 4326,
              item["properties"].get("proj:epsg"))
        gpkg = ogr.Open(os.path.join(out, "cutouts.gpkg"))
        check("the footprint is in EPSG:4326 too",
              gpkg.GetLayer(0).GetSpatialRef().GetAuthorityCode(None) == "4326")
        gpkg = None
        log_file = os.path.join(os.path.expanduser("~"), "RasterLabel",
                                "rasterlabel.log")
        check("the cut is in the log of the program",
              os.path.exists(log_file) and "cut_0001 written"
              in open(log_file, encoding="utf-8").read(), K.everything_under(out))
        check("and no log is left in the cutouts folder",
              not os.path.exists(os.path.join(out, "rasterlabel.log")))
        panel.close_module()

    print()
    print("the picture is the one QGIS draws, when it can draw it")
    load(True, drawn=painted)
    out = os.path.join(root, "styled")
    panel, cut = open_cutouts(out)
    check("written", cut.export(PICK, nominal=None))
    picture = gdal.Open(os.path.join(out, "cut_0001_%s_image.png" % IMG_TAG)) \
        .ReadAsArray()
    check("in the colours of the style",
          tuple(picture[:3, 5, 40]) == (255, 128, 0), picture[:, 5, 40])
    check("and transparent where QGIS draws nothing",
          (picture[3, :, :10] == 0).all() and (picture[3, :, 10:] == 255).all())
    check("the manifest says so", [r["stretch"] for r in rows_of(out)
                                   if r["role"] == "image"]
          == ["as styled in QGIS"], rows_of(out))
    panel.close_module()

    print()
    print("PNG for both layers")
    load(True)
    out = os.path.join(root, "png")
    panel, cut = open_cutouts(out)
    for s in cut.sources:
        s["driver"] = "PNG"
    check("written", cut.export(PICK, nominal=None))
    files = K.everything_under(out)
    codes_png = gdal.Open(os.path.join(out, "cut_0001_%s_classes.png" % CLS_TAG))
    check("the classes PNG keeps the codes, one band",
          codes_png.RasterCount == 1
          and np.array_equal(codes_png.ReadAsArray(), codes[10:60, 10:70]))
    colour = os.path.join(out, "cut_0001_%s_classes_colour.png" % CLS_TAG)
    check("and a coloured copy is written beside it", os.path.exists(colour),
          files)
    painted_ = gdal.Open(colour).ReadAsArray()
    check("in the colours of the style",
          tuple(painted_[:3, 5, 50]) == (0xdd, 0xdd, 0xdd), painted_[:, 5, 50])
    img_png = gdal.Open(os.path.join(out, "cut_0001_%s_image.png" % IMG_TAG))
    check("the image as PNG is its picture, with alpha",
          img_png.RasterCount == 4)
    check("and no second picture of it",
          "cut_0001_%s_image_image.png" % IMG_TAG not in files
          and len([f for f in files if f.endswith("_image.png")]) == 1, files)
    panel.close_module()

    print()
    print("a layer in a system that really is another is reprojected")
    # The map of classes in UTM 33N beside the image in degrees. It used to be
    # left out of every cutout, so a map and an image in two systems could
    # not be cut together at all.
    utm = os.path.join(data, "utm.tif")
    gdal.Warp(utm, CLASSES, dstSRS="EPSG:32633", resampleAlg="near")
    for common in (True, False):
        load(True, classes_path=utm, classes_system=epsg(32633))
        out = os.path.join(root, "elsewhere_%s" % ("common" if common
                                                   else "own"))
        panel, cut = open_cutouts(out)
        cut.common.setChecked(common)
        K.SAID[:] = []
        check("written", cut.export(PICK, nominal=None))
        check("nothing is left out", cut.skipped == {}, cut.skipped)
        cls_tif = os.path.join(out, "cut_0001_%s_classes.tif" % CLS_TAG)
        img_tif = os.path.join(out, "cut_0001_%s_image.tif" % IMG_TAG)
        ok = os.path.exists(cls_tif) and os.path.exists(img_tif)
        check("the classes are written beside the image%s"
              % ("" if common else ", with the common grid off"), ok,
              K.everything_under(out))
        if ok:
            got = gdal.Open(cls_tif)
            check("on the grid of the image, in its system",
                  got.GetGeoTransform() == gdal.Open(img_tif).GetGeoTransform()
                  and code_of(cls_tif) == "4326",
                  (got.GetGeoTransform(), code_of(cls_tif)))
            agree = float((got.ReadAsArray() == codes[10:60, 10:70]).mean())
            check("on the same ground: the classes agree with the map",
                  agree > 0.97, agree)
            got = None
            row = [r for r in rows_of(out) if r["role"] == "classes"][0]
            check("and cutouts.csv says they were resampled",
                  row["resampled"] == "1", row)
        check("the message bar says it is reprojected",
              [m for m in K.SAID if "reprojected" in m and CLS_TAG in m],
              K.SAID)
        panel.close_module()

    print()
    print("a layer with no system beside one that has one is left out")
    load(True, classes_path=utm, classes_system=System(""))
    out = os.path.join(root, "elsewhere")
    panel, cut = open_cutouts(out)
    K.SAID[:] = []
    check("written", cut.export(PICK, nominal=None))
    check("the classes are left out, and the reason is kept",
          CLS_TAG in cut.skipped and "EPSG:4326" in cut.skipped[CLS_TAG],
          cut.skipped)
    check("the panel says so beside the layer",
          "left out of the last cutout" in cut.state.text(), cut.state.text())
    check("so does the message that says the cutout is written",
          [m for m in K.SAID if "cut_0001 written" in m and "left out" in m],
          K.SAID)
    item = json.load(open(os.path.join(out, "stac", "cut_0001.json"),
                          encoding="utf-8"))
    check("and the catalogue claims the image only",
          item["properties"]["rasterlabel:roles"] == ["image"],
          item["properties"]["rasterlabel:roles"])
    panel.close_module()

    print()
    print("the books")
    load(True)
    out = os.path.join(root, "books")
    panel, cut = open_cutouts(out)
    # A click is as many pixels as the side box says, the side over the
    # pixel measured on the ground. The kit's ruler measures in the units of
    # the system, degrees here, so the pixel QGIS measures on the ellipsoid
    # stands in for it: about 5 cm each way at this latitude, and a side of
    # 1.5 m is thirty of them, the width of each window below.
    measured = g["pixel_on_the_ground"]
    g["pixel_on_the_ground"] = lambda layer: (0.05, 0.05)
    check("first", cut.export(window(30, 10, 60, 40), nominal=1.5))
    check("second", cut.export(window(70, 10, 100, 40), nominal=1.5))
    check("third", cut.export(window(110, 10, 140, 40), nominal=1.5))
    shapes = json.load(open(os.path.join(out, "shapes.json"), encoding="utf-8"))
    check("the size of a side in degrees has a key of its own",
          shapes == {"1.500@5.6448e-07": [30, 30]}, shapes)
    # The folder box loses focus: Qt sends editingFinished, which used to
    # forget the whole session.
    cut.folder_box.editingFinished.emit()
    cut.folder_changed()
    check("losing focus on the folder box forgets nothing",
          len(cut.written) == 3, len(cut.written))
    cut.undo()
    left = K.everything_under(out)
    check("undo takes the third cutout away",
          not [f for f in left if f.startswith("cut_0003")], left)
    gpkg = ogr.Open(os.path.join(out, "cutouts.gpkg"))
    feet = [f.GetField("cutout") for f in gpkg.GetLayer(0)]
    gpkg = None
    check("and its footprint", feet == ["cut_0001", "cut_0002"], feet)
    note = json.load(open(os.path.join(out, "sampler.json"), encoding="utf-8"))
    # two cutouts of two layers each: the note counts the pieces, not the
    # four files they are made of
    check("and the sampler note no longer counts it",
          sum(s["n"] for s in note["shapes_found"]) == 2, note["shapes_found"])

    # cut_0002 deleted by hand in Explorer: the files go, the books stay.
    for f in K.everything_under(out):
        if f.startswith("cut_0002_"):
            os.remove(os.path.join(out, f))
    other = os.path.join(root, "other")
    cut.folder_box.setText(other)
    cut.folder_changed()
    cut.folder_box.setText(out)
    cut.folder_changed()
    check("the cutouts whose files are gone are counted out",
          cut.count == 1 and cut.gone == ["cut_0002"], (cut.count, cut.gone))
    check("and the panel says so", "no longer on disk" in cut.state.text()
          and "cut_0002" in cut.state.text(), cut.state.text())
    check("the books themselves are left as they were",
          os.path.exists(os.path.join(out, "stac", "cut_0002.json"))
          and "cut_0002" in {r["cutout"] for r in rows_of(out)})
    check("the next one does not take the name of the one deleted",
          cut.export(window(70, 60, 100, 90), nominal=1.5)
          and os.path.exists(os.path.join(
              out, "cut_0003_%s_image.tif" % IMG_TAG)),
          K.everything_under(out))
    item2 = json.load(open(os.path.join(out, "stac", "cut_0002.json"),
                           encoding="utf-8"))
    check("so the STAC item of the deleted one is not written over",
          item2["id"] == "cut_0002")
    catalog = json.load(open(os.path.join(out, "stac", "catalog.json"),
                             encoding="utf-8"))
    linked = [l["href"] for l in catalog["links"] if l["rel"] == "item"]
    check("and it is left out of the catalogue, which links the others",
          linked == ["cut_0001.json", "cut_0003.json"], linked)

    # Everything of cut_0003 but its STAC item deleted by hand, csv row too:
    # the name is still spoken for by stac/.
    for f in K.everything_under(out):
        if f.startswith("cut_0003_"):
            os.remove(os.path.join(out, f))
    with open(os.path.join(out, "cutouts.csv"), encoding="utf-8") as f:
        keep = [l for l in f if not l.startswith("cut_0003,")]
    with open(os.path.join(out, "cutouts.csv"), "w", encoding="utf-8",
              newline="") as f:
        f.writelines(keep)
    check("a name whose STAC item is still there is never used again",
          cut.free_name() == "cut_0004", cut.free_name())
    g["pixel_on_the_ground"] = measured
    panel.close_module()

    print()
    print("layers named at length")
    # two maps of one survey, whose names share their first sixty letters
    # and differ at the end: cut at 48 letters they were one name, and the
    # second took a "_2" and lost what it was
    HEAD = "aragona_orthomosaic_september_2025_the_whole_survey_area"
    LONG_IMG, LONG_CLS = HEAD + "_rgb", HEAD + "_disag_classes"
    load(True, names=(LONG_IMG, LONG_CLS))
    out = os.path.join(root, "long_names")
    panel, cut = open_cutouts(out)
    tags = {s["role"]: s["tag"] for s in cut.sources}
    check("a long name keeps its ending: the image", tags.get("image", "")
          .endswith("_rgb"), tags)
    check("and the classes, with their role and their word",
          tags.get("classes", "").endswith("_disag_classes"), tags)
    check("every tag fits in 48 letters and the two differ",
          all(len(t) <= 48 for t in tags.values())
          and len(set(tags.values())) == 2, tags)
    check("and neither is the old one, cut at 48 and numbered",
          not any(t.endswith("_2") for t in tags.values())
          and LONG_CLS[:48] not in tags.values(), tags)
    done = cut.export(PICK, nominal=None)
    check("the cutout is written", done, K.BOXES[-3:])
    files = K.everything_under(out)
    for role, ext in (("image", "tif"), ("classes", "tif")):
        name = "cut_0001_%s_%s.%s" % (tags[role], role, ext)
        check("%s is written, whole" % name, name in files, files)
    got = {r["role"]: r for r in rows_of(out)}
    check("cutouts.csv says the same tags and the full layer names",
          {k: (v["tag"], v["layer"]) for k, v in got.items()}
          == {"image": (tags["image"], LONG_IMG),
              "classes": (tags["classes"], LONG_CLS)}, got)
    panel.close_module()
    panel, cut = open_cutouts(out)
    check("the folder remembers them: the same tags the next time",
          {s["role"]: s["tag"] for s in cut.sources} == tags,
          [s["tag"] for s in cut.sources])
    panel.close_module()
    # a folder cut by an older version has its tag cut at 48 letters in
    # layers.json, and keeps it
    old_tag = LONG_CLS[:48]
    path = os.path.join(out, "layers.json")
    with open(path, encoding="utf-8") as f:
        book = json.load(f)
    for entry in book["layers"]:
        if entry.get("role") == "classes":
            entry["tag"] = old_tag
    with open(path, "w", encoding="utf-8") as f:
        json.dump(book, f)
    panel, cut = open_cutouts(out)
    check("a folder cut before keeps the old name of its layer",
          {s["role"]: s["tag"] for s in cut.sources}.get("classes")
          == old_tag, [s["tag"] for s in cut.sources])
    panel.close_module()

    if os.name == "nt":
        print()
        print("a folder past 260 characters")
        load(True)
        deep = os.path.join(root, *(["a_rather_long_folder_name_%02d" % i
                                     for i in range(9)]))
        check("the folder is deep enough", len(deep) > 260, len(deep))
        panel, cut = open_cutouts(deep)
        done = cut.export(PICK, nominal=None)
        check("the cutout is written, not abandoned", done, K.BOXES[-2:])
        check("its rows are in the manifest", len([
            1 for l in open(g.get("long_path", str)(
                os.path.join(deep, "cutouts.csv")),
                            encoding="utf-8")]) == 3)
        panel.close_module()
finally:
    shutil.rmtree(g.get("long_path", str)(root), ignore_errors=True)

sys.exit(K.finish())
