"""Cutouts on the grids people really have: real files out, the window read
back.

Each of these came out wrong, and each without a word:

  a click of 10 m on 5 cm pixels was 201 by 201, not the 200 the side box
  said, 30 m on 10 m pixels was 4 by 4, forty metres, and shapes.json then
  held that size for every later cutout of the side;
  a click on a layer with no coordinate system stopped with "cannot convert
  float NaN to integer", because the ruler took its units for degrees, and
  cutouts.csv wrote its side as nan;
  the padding past the edge of an image with no nodata was black, the same
  black as the ground, with nothing in the GeoTIFF to tell them apart;
  a layer stored bottom row first could not set the grid: every click was
  "outside the first layer";
  a map of classes stored as JPEG had its compression noise copied into the
  cutouts as classes, and nothing said so;
  the type a map of classes is cut in was in no catalogue;
  a picture with no georeference, which QGIS draws at y = -row, was cut on
  the grid GDAL answers for it, rows going up: every click was "outside the
  first layer";
  a layer on a rotated grid set the grid of the cutouts as if it were north
  up, and the cutouts held other pixels than the ones under the rectangle.

Needs the GDAL Python bindings: the rasters, the GeoPackage and the PNGs are
real. QGIS is faked, see correctkit.py.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import json
import math
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

root = tempfile.mkdtemp(prefix="rl_cutouts_grids_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
data = os.path.join(root, "data")
os.makedirs(data)
X0, Y0 = 500000.0, 4100000.0
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)
UTM = srs.ExportToWkt()


def write(name, arrays, gt, gtype=gdal.GDT_Byte, wkt=UTM, nodata=None,
          driver="GTiff"):
    path = os.path.join(data, name)
    h, w = arrays[0].shape
    mem = gdal.GetDriverByName("MEM").Create("", w, h, len(arrays), gtype)
    mem.SetGeoTransform(gt)
    if wkt:
        mem.SetProjection(wkt)
    for i, a in enumerate(arrays):
        mem.GetRasterBand(i + 1).WriteArray(a)
        if nodata is not None:
            mem.GetRasterBand(i + 1).SetNoDataValue(nodata)
    options = ["QUALITY=75"] if driver == "JPEG" else []
    gdal.GetDriverByName(driver).CreateCopy(path, mem, 0, options)
    mem = None
    return path


def pattern(h, w, bands=3):
    yy, xx = np.indices((h, w))
    return [((xx * (3 + b) + yy * (5 + b)) % 250 + 3).astype(np.uint8)
            for b in range(bands)]


class Nowhere(K.Crs):
    """A layer with no coordinate system: a picture, or a world file with no
    .prj that GDAL reads."""
    def __init__(self): super().__init__("")


class Layer(K.Layer):
    def __init__(self, path, name, renderer=None, system=None):
        super().__init__(path, name, renderer)
        self.system = system
    def crs(self): return self.system if self.system is not None else K.Crs()


VIEW = [K.Crs()]


class Canvas(object):
    def extent(self): return K.Dummy()
    def mapSettings(self):
        m = K.Dummy()
        m.destinationCrs = lambda: VIEW[0]
        return m
    def __getattr__(self, n): return lambda *a, **k: None


g["canvas"] = lambda: Canvas()


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


class NanRuler(object):
    """What QGIS's QgsDistanceArea answers when it is given an ellipsoid and
    no valid system: the coordinates taken for degrees, NaN past 90."""
    def setSourceCrs(self, *a): pass
    def setEllipsoid(self, *a): pass
    def measureLine(self, a, b): return float("nan")


def paletted(codes):
    colours = ["#e6194b", "#3cb44b", "#0082c8", "#ffe119", "#911eb4"]
    return K.Paletted(None, 1, [K.Paletted.Class(c, colours[i % 5], "c%d" % c)
                                for i, c in enumerate(codes)])


def open_cutouts(folder, layers, view=None):
    K.LOADED.clear()
    K.TREE.clear()
    for layer in layers:
        K.add_layer(layer)
    VIEW[0] = view if view is not None else K.Crs()
    panel = g["Panel"]()
    panel.toggle_module(3)
    cut = panel.section
    if cut is None:
        print("Cutouts did not open:", K.BOXES[-3:], K.SAID[-3:])
    cut.folder_box.setText(folder)
    cut.folder_changed()
    for box in (cut.png, cut.common, cut.same_size, cut.stac):
        box.setChecked(True)
    # the layer that sets the grid goes first, the way Layers sorts them
    want = [layer.id() for layer in layers]
    cut.sources.sort(key=lambda s: want.index(s["id"]))
    return panel, cut


def square(cx, cy, side):
    """A square of the side measured on the ground, as square_at gives it:
    a little more than the side in projected metres, 10.004 for 10, and on
    no pixel edge."""
    half = side * 1.0004 / 2.0
    return K.Rect(cx - half, cy - half, cx + half, cy + half)


def size_of(path):
    ds = gdal.Open(path)
    out = (ds.RasterXSize, ds.RasterYSize)
    ds = None
    return out


def rows_of(folder):
    with open(os.path.join(folder, "cutouts.csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cut_at(cut, rect, nominal):
    try:
        return cut.export(rect, nominal=nominal)
    except Exception as err:
        print("      [the cutout raised %s: %s]" % (type(err).__name__, err))
        return False


try:
    print("a click is the square the side box says")
    ortho = write("ortho5.tif", pattern(600, 600), (X0, 0.05, 0, Y0, 0, -0.05))
    for same in (True, False):
        out = os.path.join(root, "click_%s" % ("same" if same else "free"))
        panel, cut = open_cutouts(out, [Layer(ortho, "ortho")])
        cut.same_size.setChecked(same)
        cut.side.setValue(10.0)
        check("the side box says 200 px", cut.side_px.text().startswith(
            "200 px"), cut.side_px.text())
        for k, (cx, cy) in enumerate(((X0 + 15.013, Y0 - 14.977),
                                      (X0 + 12.338, Y0 - 16.021))):
            done = cut_at(cut, square(cx, cy, 10.0), 10.0)
            path = os.path.join(out, "cut_%04d_ortho_image.tif" % (k + 1))
            got = size_of(path) if done else None
            check("click %d%s: 200 by 200, as the box says"
                  % (k + 1, "" if same else " (same size off)"),
                  got == (200, 200), got)
        if same:
            shapes = json.load(open(os.path.join(out, "shapes.json"),
                                    encoding="utf-8"))
            check("and shapes.json keeps 200 by 200 for the side",
                  shapes == {"10.000@0.050000": [200, 200]}, shapes)
            ds = gdal.Open(os.path.join(out, "cut_0001_ortho_image.tif"))
            gt = ds.GetGeoTransform()
            ds = None
            check("centred on the click, on the grid of the layer",
                  abs(gt[0] - (X0 + 10.0)) < 1e-9
                  and abs(gt[3] - (Y0 - 10.0)) < 1e-9, gt)
        panel.close_module()

    s2 = write("s2.tif", [np.full((30, 30), 500, np.uint16)] * 4,
               (X0, 10.0, 0, Y0, 0, -10.0), gdal.GDT_UInt16)
    out = os.path.join(root, "click_s2")
    panel, cut = open_cutouts(out, [Layer(s2, "s2")])
    cut.side.setValue(30.0)
    done = cut_at(cut, square(X0 + 153.0, Y0 - 147.0, 30.0), 30.0)
    got = size_of(os.path.join(out, "cut_0001_s2_image.tif")) if done else None
    check("30 m on 10 m pixels is 3 by 3, thirty metres, not forty",
          got == (3, 3), got)
    panel.close_module()

    oblong = write("px5x7.tif", pattern(300, 300), (X0, 0.05, 0, Y0, 0, -0.07))
    out = os.path.join(root, "click_5x7")
    panel, cut = open_cutouts(out, [Layer(oblong, "px5x7")])
    cut.side.setValue(5.0)
    done = cut_at(cut, square(X0 + 7.51, Y0 - 10.49, 5.0), 5.0)
    got = size_of(os.path.join(out, "cut_0001_px5x7_image.tif")) if done \
        else None
    check("5 m on pixels of 5 by 7 cm is 100 by 71: the same ground both ways",
          got == (100, 71), got)
    panel.close_module()

    print()
    print("a click on a layer with no coordinate system")
    photo = write("photo.tif", pattern(150, 200), (X0, 0.25, 0, Y0, 0, -0.25),
                  wkt="")
    out = os.path.join(root, "no_system")
    panel, cut = open_cutouts(out, [Layer(photo, "photo", system=Nowhere())],
                              view=Nowhere())
    # what QGIS hands back with an ellipsoid and no system
    cut.measure = NanRuler()
    measured = g["ground_measure"]
    g["ground_measure"] = lambda crs: NanRuler()
    cut.side.setValue(25.0)
    try:
        rect = cut.square_at(K.Point(X0 + 20.0, Y0 - 15.0))
        finite = all(math.isfinite(v) for v in (
            rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()))
    except Exception as err:
        rect, finite = None, False
        print("      [square_at raised %s]" % err)
    check("the square of a click has finite corners", finite,
          rect and (rect.xMinimum(), rect.xMaximum()))
    check("its side in the units of the layer, one to a metre",
          finite and abs(rect.width() - 25.0) < 1e-9,
          rect and rect.width())
    done = finite and cut_at(cut, rect, 25.0)
    check("the click is cut", done, K.BOXES[-2:])
    if done:
        check("100 by 100 pixels of 0.25",
              size_of(os.path.join(out, "cut_0001_photo_image.tif"))
              == (100, 100))
        side = rows_of(out)[0]["side_m"]
        check("and cutouts.csv has a number for its side, not nan",
              side == "25.000", side)
    g["ground_measure"] = measured
    panel.close_module()

    print()
    print("a picture with no georeference")
    # QGIS draws it one unit a pixel, y = -row; GDAL answers (0, 1, 0, 0, 0,
    # 1) for it, rows going up, and every click on it was "outside the first
    # layer"
    picture = os.path.join(data, "scan.png")
    bands = pattern(120, 160)
    mem = gdal.GetDriverByName("MEM").Create("", 160, 120, 3, gdal.GDT_Byte)
    for i, a in enumerate(bands):
        mem.GetRasterBand(i + 1).WriteArray(a)
    gdal.GetDriverByName("PNG").CreateCopy(picture, mem, 0)
    mem = None
    out = os.path.join(root, "picture")
    panel, cut = open_cutouts(out, [Layer(picture, "scan", system=Nowhere())],
                              view=Nowhere())
    cut.side.setValue(20.0)
    rect = cut.square_at(K.Point(60.0, -40.0))
    done = cut_at(cut, rect, 20.0)
    check("a click on it is cut", done, K.BOXES[-2:] + K.SAID[-2:])
    if done:
        ds = gdal.Open(os.path.join(out, "cut_0001_scan_image.tif"))
        got = ds.ReadAsArray() if ds is not None else None
        gt = ds.GetGeoTransform() if ds is not None else None
        ds = None
        check("20 by 20 pixels, the ones under the click",
              got is not None and got.shape == (3, 20, 20)
              and (got == np.stack(bands)[:, 30:50, 50:70]).all(),
              got is not None and got.shape)
        check("on the grid QGIS draws it on, y = -row",
              gt is not None and abs(gt[0] - 50.0) < 1e-9
              and abs(gt[3] + 30.0) < 1e-9 and gt[5] == -1.0, gt)
    panel.close_module()

    print()
    print("a layer on a rotated grid sets the grid")
    turned = write("ortho_rotated.tif", pattern(200, 200),
                   (X0, 0.05 * math.cos(0.3), -0.05 * math.sin(0.3), Y0,
                    -0.05 * math.sin(0.3), -0.05 * math.cos(0.3)))
    out = os.path.join(root, "rotated")
    panel, cut = open_cutouts(out, [Layer(turned, "turned")])
    cut.side.setValue(2.0)
    del K.BOXES[:]
    done = cut_at(cut, square(X0 + 3.0, Y0 - 3.0, 2.0), 2.0)
    check("a click is refused, not cut on a north-up grid that is not its own",
          not done and not os.path.exists(
              os.path.join(out, "cut_0001_turned_image.tif")), K.BOXES[-2:])
    check("and the window says it is rotated and how to warp it north-up",
          any("rotated pixel grid" in str(b) and "north-up" in str(b)
              for b in K.BOXES), K.BOXES[-2:])
    panel.close_module()

    print()
    print("past the edge of an image with no nodata")
    small = write("ortho_small.tif", pattern(400, 400),
                  (X0, 0.05, 0, Y0, 0, -0.05))
    odd = write("ortho_7cm.tif", pattern(286, 286),
                (X0 + 0.03, 0.07, 0, Y0 - 0.02, 0, -0.07))
    out = os.path.join(root, "padding")
    panel, cut = open_cutouts(out, [Layer(small, "small"),
                                    Layer(odd, "odd")])
    cut.side.setValue(10.0)
    # A frame of 10 m on the pixel edges at the corner of the image, kept at
    # its full size by "same size for all", which pads it past the edge.
    try:
        done = cut.export(K.Rect(X0 + 14.0, Y0 - 6.0, X0 + 24.0, Y0 + 4.0),
                          quiet=True, tile_id="T1", nominal=10.0)
    except Exception as err:
        done = False
        print("      [the cutout raised %s: %s]" % (type(err).__name__, err))
    check("a frame at the corner is cut, at full size", done, K.BOXES[-2:])
    if done:
        path = os.path.join(out, "cut_0001_small_image.tif")
        ds = gdal.Open(path)
        band = ds.GetRasterBand(1)
        mask = band.GetMaskBand().ReadAsArray()
        values = ds.ReadAsArray()
        flags = band.GetMaskFlags()
        ds = None
        gt = (X0 + 14.0, 0.05, 0, Y0 + 4.0, 0, -0.05)
        rows, cols = np.indices((200, 200))
        past = (cols >= 120) | (rows < 80)
        check("the file has a mask of its own",
              flags == gdal.GMF_PER_DATASET, flags)
        check("0 over the padding, 255 over the image",
              (mask[past] == 0).all() and (mask[~past] == 255).all(),
              (np.unique(mask[past]).tolist(), np.unique(mask[~past]).tolist()))
        source = np.stack(pattern(400, 400))
        check("and the pixels of the image are the image's",
              np.array_equal(values[:, 80:, :120], source[:, :120, 280:]))
        check("no .msk beside it", not os.path.exists(path + ".msk"),
              K.everything_under(out))
        ds = gdal.Open(os.path.join(out, "cut_0001_odd_image.tif"))
        mask = ds.GetRasterBand(1).GetMaskBand().ReadAsArray()
        flags = ds.GetRasterBand(1).GetMaskFlags()
        ds = None
        xs = gt[0] + (np.arange(200) + 0.5) * 0.05
        beyond = xs > X0 + 0.03 + 286 * 0.07 + 0.07
        check("a resampled image is masked past its edge too",
              flags == gdal.GMF_PER_DATASET and (mask[:, beyond] == 0).all()
              and (mask[100:, :50] == 255).all(), flags)
    panel.close_module()

    print()
    print("a layer stored bottom row first sets the grid")
    stored = pattern(400, 400)
    down = write("north_down.tif", stored, (X0, 0.05, 0, Y0 - 20.0, 0, 0.05))
    codes = np.zeros((80, 80), np.uint8)
    codes[:, :40] = 1
    codes[:, 40:] = 2
    classes = write("classes.tif", [codes], (X0, 0.25, 0, Y0, 0, -0.25))
    out = os.path.join(root, "north_down")
    panel, cut = open_cutouts(out, [Layer(down, "down"),
                                    Layer(classes, "classes",
                                          paletted([1, 2]))])
    cut.side.setValue(5.0)
    K.SAID[:] = []
    done = cut_at(cut, square(X0 + 10.0, Y0 - 10.0, 5.0), 5.0)
    check("a click in the middle is cut", done, K.SAID[-2:])
    if done:
        ds = gdal.Open(os.path.join(out, "cut_0001_down_image.tif"))
        gt, values = ds.GetGeoTransform(), ds.ReadAsArray()
        ds = None
        check("its cutout is written top row first, like every other",
              gt[5] < 0 and abs(gt[3] - (Y0 - 7.5)) < 1e-9, gt)
        check("with the very pixels of the layer, the right way up",
              np.array_equal(values, np.stack(stored)[:, ::-1][
                  :, 150:250, 150:250]))
        ds = gdal.Open(os.path.join(out, "cut_0001_classes_classes.tif"))
        check("and the map beside it is on the same grid",
              ds.GetGeoTransform() == gt
              and (ds.RasterXSize, ds.RasterYSize) == (100, 100))
        ds = None
    panel.close_module()

    print()
    print("a map of classes stored as JPEG")
    blocky = ((np.indices((160, 160)) // 20).sum(0) % 4 + 1).astype(np.uint8)
    lossy = write("classes.jpg", [blocky], (X0, 0.25, 0, Y0, 0, -0.25),
                  driver="JPEG")
    out = os.path.join(root, "lossy")
    panel, cut = open_cutouts(out, [Layer(lossy, "landcover",
                                          paletted([1, 2, 3, 4]))])
    K.SAID[:] = []
    check("is cut", cut_at(cut, K.Rect(X0 + 2, Y0 - 12, X0 + 12, Y0 - 2),
                           None))
    said = [m for m in K.SAID if "which is lossy" in m]
    check("and the message bar says its codes carry compression noise",
          len(said) == 1 and "JPEG" in said[0], K.SAID)
    cut_at(cut, K.Rect(X0 + 20, Y0 - 32, X0 + 30, Y0 - 22), None)
    check("once a session, not at every cutout",
          len([m for m in K.SAID if "which is lossy" in m]) == 1, K.SAID)
    panel.close_module()

    print()
    print("the catalogue says the type of what it lists")
    wide = np.full((80, 80), 101, np.uint16)
    wide[:, 40:] = 404
    u16 = write("classes_u16.tif", [wide], (X0, 0.25, 0, Y0, 0, -0.25),
                gdal.GDT_UInt16)
    out = os.path.join(root, "types")
    panel, cut = open_cutouts(out, [Layer(small, "small"),
                                    Layer(u16, "wide", paletted([101, 404]))])
    check("is cut", cut_at(cut, K.Rect(X0 + 5, Y0 - 15, X0 + 15, Y0 - 5),
                           None))
    item = json.load(open(os.path.join(out, "stac", "cut_0001.json"),
                          encoding="utf-8"))
    assets = item.get("assets", {})
    check("the classes are listed in uint16, the type they are cut in",
          assets.get("wide_classes", {}).get("raster:bands")
          == [{"data_type": "uint16"}], assets.get("wide_classes"))
    check("the image band by band in its own type",
          assets.get("small_image", {}).get("raster:bands")
          == [{"data_type": "uint8"}] * 3, assets.get("small_image"))
    check("under the raster extension",
          any("/raster/" in e for e in item.get("stac_extensions", [])),
          item.get("stac_extensions"))
    ds = gdal.Open(os.path.join(out, "cut_0001_wide_classes.tif"))
    check("and the file is what the catalogue says",
          gdal.GetDataTypeName(ds.GetRasterBand(1).DataType) == "UInt16"
          and set(np.unique(ds.ReadAsArray()).tolist()) == {101, 404})
    ds = None
    panel.close_module()
finally:
    shutil.rmtree(g.get("long_path", str)(root), ignore_errors=True)

sys.exit(K.finish())
