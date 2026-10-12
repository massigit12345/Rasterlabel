"""The export of the whole raster, actually run: a real GeoTIFF, a real
GeoPackage, real gdal.

Two things matter more than the rest. That the mask and the image line up
pixel for pixel, because otherwise they are no use together. And that it all
works on an image with no coordinate system too, because the idea is to
annotate any raster, not only orthomosaics.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import os
import shutil
import sys
import tempfile

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()

SRC = os.environ.get("RL_SRC", _BUILT)

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


# ------------------------------------------------- the module, with no QGIS
import ast
tree = ast.parse(open(SRC, encoding="utf-8").read())
lines = open(SRC, encoding="utf-8").read().splitlines(True)


def take(name):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("%s not found" % name)


def have(name):
    return any(isinstance(node, (ast.FunctionDef, ast.ClassDef))
               and node.name == name for node in tree.body)


import math as _m
g = {"gdal": gdal, "ogr": ogr, "osr": osr, "np": np, "os": os, "math": _m,
     "IOError": IOError, "MAX_CLASS_CODE": 254, "OPERATOR_BLANK": "UNNAMED",
     "VERSION": "test", "log": lambda m, loud=False: print("      [log]", m)}
for n in ("Stencil", "open_for_write", "long_path", "landed", "finish_write",
          "paint_whole", "mask_type", "vote", "majority", "operator_word",
          "pass_number", "reading_label", "reading_rule", "reading_metadata"):
    exec(take(n), g)
# What paint_whole calls since the grid of a picture, a rotated raster and
# the scratch file of a PNG were put right. A build from before has none of
# them and does not call them, and this suite then says what it gets wrong
# instead of stopping at the first name it cannot find.
for n in ("pixel_grid", "pixel_holding", "put_picture", "scratch_of",
          "drop_scratch",
          # and what a mask says where nobody painted, since there is a
          # choice of what it holds there (test_ignore_index has the rest)
          "unlabelled_metadata", "unlabelled_rule", "ignore_refusal",
          "settle_unlabelled", "_tally_add", "class_array"):
    if have(n):
        exec(take(n), g)
g["PICTURE_GRID"] = (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)
g["STRIP_ROWS"] = 64          # small strips on purpose: that way the loop runs
paint_whole = g["paint_whole"]

W, H = 300, 200
PX = 0.05
OX, OY = 400000.0, 4100000.0
tmp = tempfile.mkdtemp(prefix="whole_")


def make_raster(path, georeferenced=True):
    ds = gdal.GetDriverByName("GTiff").Create(path, W, H, 3, gdal.GDT_UInt16)
    rng = np.random.default_rng(7)
    for i in range(3):
        a = np.full((H, W), 8000 + i * 2000, np.uint16)
        a += rng.integers(0, 400, (H, W)).astype(np.uint16)
        ds.GetRasterBand(i + 1).WriteArray(a)
    if georeferenced:
        ds.SetGeoTransform((OX, PX, 0, OY, 0, -PX))
        srs = osr.SpatialReference(); srs.ImportFromEPSG(32633)
        ds.SetProjection(srs.ExportToWkt())
    else:
        # what QGIS gives a photograph: one pixel per unit, origin at zero
        ds.SetGeoTransform((0.0, 1.0, 0.0, 0.0, 0.0, -1.0))
    ds.FlushCache(); ds = None


def make_package(path, georeferenced=True):
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.CreateDataSource(path)
    srs = None
    if georeferenced:
        srs = osr.SpatialReference(); srs.ImportFromEPSG(32633)

    def put(name, kind, shapes, size=None):
        lyr = ds.CreateLayer(name, srs, kind, ["GEOMETRY_NAME=geom"])
        lyr.CreateField(ogr.FieldDefn("class_code", ogr.OFTInteger))
        if size is not None:
            lyr.CreateField(ogr.FieldDefn("size_px", ogr.OFTInteger))
        d = lyr.GetLayerDefn()
        for wkt, code in shapes:
            f = ogr.Feature(d)
            f.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
            f.SetField("class_code", code)
            if size is not None:
                f.SetField("size_px", size)
            lyr.CreateFeature(f)
            f = None

    if georeferenced:
        # a class 2 square in the top left corner, 40 by 40 pixels
        x0, y0 = OX, OY
        quad = "POLYGON((%f %f,%f %f,%f %f,%f %f,%f %f))" % (
            x0, y0, x0 + 40 * PX, y0, x0 + 40 * PX, y0 - 40 * PX,
            x0, y0 - 40 * PX, x0, y0)
        line = "LINESTRING(%f %f,%f %f)" % (
            x0 + 5 * PX, y0 - 100 * PX, x0 + 250 * PX, y0 - 100 * PX)
        point = "POINT(%f %f)" % (x0 + 200 * PX, y0 - 30 * PX)
        box = "POLYGON((%f %f,%f %f,%f %f,%f %f,%f %f))" % (
            x0 + 100 * PX, y0 - 140 * PX, x0 + 160 * PX, y0 - 140 * PX,
            x0 + 160 * PX, y0 - 180 * PX, x0 + 100 * PX, y0 - 180 * PX,
            x0 + 100 * PX, y0 - 140 * PX)
    else:
        quad = "POLYGON((0 0,40 0,40 -40,0 -40,0 0))"
        line = "LINESTRING(5 -100,250 -100)"
        point = "POINT(200 -30)"
        box = "POLYGON((100 -140,160 -140,160 -180,100 -180,100 -140))"

    put("polygons", ogr.wkbMultiPolygon, [(quad, 2)])
    put("lines", ogr.wkbMultiLineString, [(line, 3)])
    put("points", ogr.wkbPoint, [(point, 4)], size=9)
    put("boxes", ogr.wkbPolygon, [(box, 5)])
    ds = None


COLOURS = {2: (235, 104, 52), 3: (27, 175, 122), 4: (237, 161, 0),
           5: (0, 131, 0)}


def run(folder, ds, scale, kinds, driver=".tif", gdriver="GTiff", **extra):
    outputs = [(k, os.path.join(folder, "%s_%d%s" % (k, scale, driver)),
                "GTiff" if k == "mask" else gdriver) for k in kinds]
    recipe = {"ds": ds, "scale": scale, "rgb": [1, 2, 3],
              "limits": [(7000.0, 11000.0)] * 3, "alpha": 45,
              "colours": COLOURS, "outputs": outputs,
              "package": os.path.join(folder, "annotation.gpkg"),
              "want_lines": True, "want_points": True, "want_boxes": True,
              "points_in_mask": False, "dot_px": 3}
    recipe.update(extra)
    return paint_whole(recipe)


print("a georeferenced orthomosaic")
folder = os.path.join(tmp, "geo")
os.makedirs(folder)
raster = os.path.join(folder, "ortho.tif")
make_raster(raster, True)
make_package(os.path.join(folder, "annotation.gpkg"), True)

ds = gdal.Open(raster)
written, size = run(folder, ds, 1, ["painted", "mask", "plain", "figure"])
ds = None
check("four files come out", len(written) == 4, len(written))
check("of the size of the raster", size == (W, H), size)

m = gdal.Open(os.path.join(folder, "mask_1.tif"))
mask = m.GetRasterBand(1).ReadAsArray()
gt = m.GetGeoTransform()
check("the mask has one band only", m.RasterCount == 1, m.RasterCount)
check("and the same grid as the original",
      abs(gt[0] - OX) < 1e-9 and abs(gt[1] - PX) < 1e-12, gt[:2])
check("the class 2 square is there, 40 by 40 pixels",
      int((mask == 2).sum()) == 1600, int((mask == 2).sum()))
check("the line does not go into the mask", int((mask == 3).sum()) == 0,
      int((mask == 3).sum()))
check("nor do the points, until you ask for them",
      int((mask == 4).sum()) == 0, int((mask == 4).sum()))
check("where there is nothing the mask is zero",
      int((mask == 0).sum()) == W * H - 1600, int((mask == 0).sum()))
m = None

a = gdal.Open(os.path.join(folder, "painted_1.tif")).ReadAsArray()
b = gdal.Open(os.path.join(folder, "plain_1.tif")).ReadAsArray()
check("the plain image and the painted one are the same size",
      a.shape == b.shape == (3, H, W), (a.shape, b.shape))
differs = (a != b).any(axis=0)
check("they differ where the square is",
      differs[:40, :40].all(), int(differs[:40, :40].sum()))
# the line runs exactly on the border between row 99 and row 100: which of
# the two takes it is up to gdal, and it is not something worth having an
# opinion about. So look for the row, instead of assuming which one it is.
line_row = [r for r in (99, 100)
            if differs[r, 60:250].all()]
check("and along the line too, all of it", len(line_row) == 1, line_row)
line_row = line_row[0] if line_row else 99
check("in a corner with nothing in it they are identical",
      not differs[190:, 260:].any(), int(differs[190:, 260:].sum()))
row = a[:, line_row, 120]
check("the line is painted solid, not translucent",
      tuple(int(v) for v in row) == COLOURS[3], tuple(int(v) for v in row))
inside = a[:, 10, 10]
check("the area instead is translucent: not the pure colour",
      tuple(int(v) for v in inside) != COLOURS[2],
      tuple(int(v) for v in inside))

print()
print("the scale")
ds = gdal.Open(raster)
written, size = run(folder, ds, 2, ["mask", "painted"])
ds = None
check("at half scale half a raster comes out", size == (W // 2, H // 2), size)
m2 = gdal.Open(os.path.join(folder, "mask_2.tif"))
gt2 = m2.GetGeoTransform()
check("the pixel doubles", abs(gt2[1] - 2 * PX) < 1e-12, gt2[1])
check("the origin stays the same", abs(gt2[0] - OX) < 1e-9, gt2[0])
mask2 = m2.GetRasterBand(1).ReadAsArray()
check("the square is 20 by 20 now", int((mask2 == 2).sum()) == 400,
      int((mask2 == 2).sum()))
m2 = None

print()
print("the points inside the mask, when you ask for them")
ds = gdal.Open(raster)
run(folder, ds, 1, ["mask"], driver="_pm.tif", points_in_mask=True)
ds = None
mp = gdal.Open(os.path.join(folder, "mask_1_pm.tif")).ReadAsArray()
check("now the point is there, and it covers its 9 by 9 pixels",
      int((mp == 4).sum()) == 81, int((mp == 4).sum()))
check("and the square has not moved", int((mp == 2).sum()) == 1600,
      int((mp == 2).sum()))

print()
print("an image with no coordinate system")
folder2 = os.path.join(tmp, "photo")
os.makedirs(folder2)
photo = os.path.join(folder2, "kittens.tif")
make_raster(photo, False)
make_package(os.path.join(folder2, "annotation.gpkg"), False)
ds = gdal.Open(photo)
try:
    written2, size2 = run(folder2, ds, 1, ["painted", "mask"])
    worked = True
except Exception as err:
    written2, size2, worked = [], (0, 0), False
    print("      exception:", err)
ds = None
check("it comes out all the same", worked and len(written2) == 2,
      len(written2))
check("of the right size", size2 == (W, H), size2)
if worked:
    mm = gdal.Open(os.path.join(folder2, "mask_1.tif"))
    check("with no projection, like the original", not mm.GetProjection(),
          mm.GetProjection()[:40])
    mk = mm.GetRasterBand(1).ReadAsArray()
    check("and the annotation landed in the right place",
          int((mk == 2).sum()) == 1600, int((mk == 2).sum()))
    mm = None

print()
print("the PNG and the JPEG")
folder3 = os.path.join(tmp, "images")
os.makedirs(folder3)
shutil.copy(os.path.join(folder, "annotation.gpkg"), folder3)
ds = gdal.Open(raster)
w3, _ = run(folder3, ds, 1, ["painted"], driver=".png", gdriver="PNG")
w4, _ = run(folder3, ds, 1, ["painted"], driver=".jpg", gdriver="JPEG")
ds = None
check("the PNG gets written", os.path.getsize(w3[0]) > 0, w3)
check("the JPEG too", os.path.getsize(w4[0]) > 0, w4)
png = gdal.Open(w3[0])
check("the PNG has three byte bands",
      png.RasterCount == 3 and png.GetRasterBand(1).DataType == gdal.GDT_Byte,
      png.RasterCount)
png = None

print()
print("if something goes wrong no half-written file is left behind")
folder4 = os.path.join(tmp, "broken")
os.makedirs(folder4)
shutil.copy(os.path.join(folder, "annotation.gpkg"), folder4)
ds = gdal.Open(raster)
bad = os.path.join(folder4, "painted_1.tif")
recipe = {"ds": ds, "scale": 1, "rgb": [1, 2, 3],
          "limits": [(7000.0, 11000.0)] * 3, "alpha": 45, "colours": COLOURS,
          "outputs": [("painted", bad, "GTiff"),
                      ("mask", os.path.join(folder4, "no", "m.tif"), "GTiff")],
          "package": os.path.join(folder4, "annotation.gpkg"),
          "want_lines": True, "want_points": True, "want_boxes": True,
          "points_in_mask": False, "dot_px": 3}
try:
    paint_whole(recipe)
    blew_up = False
except Exception:
    blew_up = True
ds = None
check("the impossible write raises an error", blew_up)
check("and the file already opened is taken away",
      not os.path.exists(bad), bad)

print()
print("a picture with no georeferencing at all, as PNGs and JPEGs come")
# Nothing but pixels: no world file, no .aux.xml. GDAL answers its default,
# (0, 1, 0, 0, 0, 1), rows going up; QGIS draws the picture, and the
# annotation is drawn, at y = -row. The mask used to be burned on GDAL's
# answer and came out empty, the painted image the same as the plain one.
folder5 = os.path.join(tmp, "bare")
os.makedirs(folder5)
bare = os.path.join(folder5, "photo.png")
mem = gdal.GetDriverByName("MEM").Create("", W, H, 3, gdal.GDT_Byte)
for i in range(3):
    mem.GetRasterBand(i + 1).Fill(60 + 40 * i)
gdal.GetDriverByName("PNG").CreateCopy(bare, mem)
mem = None
probe = gdal.Open(bare)
check("GDAL knows no geotransform for it",
      probe.GetGeoTransform(can_return_null=True) is None,
      probe.GetGeoTransform(can_return_null=True))
probe = None
make_package(os.path.join(folder5, "annotation.gpkg"), False)
ds = gdal.Open(bare)
run(folder5, ds, 1, ["painted", "mask", "plain"],
    limits=[(0.0, 255.0)] * 3)
ds = None
mm = gdal.Open(os.path.join(folder5, "mask_1.tif"))
mk = mm.GetRasterBand(1).ReadAsArray()
check("the mask holds the square drawn on it, 40 by 40, top left",
      int((mk == 2).sum()) == 1600 and bool((mk[:40, :40] == 2).all()),
      int((mk == 2).sum()))
check("on the grid QGIS draws the picture on, y = -row",
      tuple(mm.GetGeoTransform()) == (0.0, 1.0, 0.0, 0.0, 0.0, -1.0),
      mm.GetGeoTransform())
mm = None
a5 = gdal.Open(os.path.join(folder5, "painted_1.tif")).ReadAsArray()
b5 = gdal.Open(os.path.join(folder5, "plain_1.tif")).ReadAsArray()
check("and the painted image carries it",
      bool((a5 != b5).any(axis=0)[:40, :40].all()),
      int((a5 != b5).any(axis=0)[:40, :40].sum()))

print()
print("a rotated raster: every strip, every corner, every point")
# A Helmert world file, or an aerial product delivered rotated. The strips
# moved down y only, the spatial filter was the box of two corners, and the
# points were squares of gt[1] by gt[5] in map units: polygons went missing,
# in the first strip too, and points landed on the wrong pixels.
folder6 = os.path.join(tmp, "rotated")
os.makedirs(folder6)
turn = _m.radians(30)
RGT = (OX, PX * _m.cos(turn), PX * _m.sin(turn),
       OY, PX * _m.sin(turn), -PX * _m.cos(turn))
rotated = os.path.join(folder6, "rotated.tif")
rds = gdal.GetDriverByName("GTiff").Create(rotated, W, H, 3, gdal.GDT_Byte)
rds.SetGeoTransform(RGT)
utm = osr.SpatialReference()
utm.ImportFromEPSG(32633)
rds.SetProjection(utm.ExportToWkt())
for i in range(3):
    rds.GetRasterBand(i + 1).Fill(90)
rds = None


def on_grid(col, row):
    return tuple(gdal.ApplyGeoTransform(RGT, col, row))


SQUARES = [(5, 5, 2), (5, 270, 3), (52, 140, 4), (170, 5, 5),
           (170, 270, 2), (120, 20, 3)]          # row, col of the corner, code
DOTS = [(100, 60, 4), (190, 200, 5)]             # row, col of the pixel, code
pkg = ogr.GetDriverByName("GPKG").CreateDataSource(
    os.path.join(folder6, "annotation.gpkg"))
lyr = pkg.CreateLayer("polygons", utm, ogr.wkbMultiPolygon,
                      ["GEOMETRY_NAME=geom"])
lyr.CreateField(ogr.FieldDefn("class_code", ogr.OFTInteger))
for row, col, code in SQUARES:
    ring = "%s" % ",".join("%r %r" % on_grid(c, r) for c, r in (
        (col, row), (col + 24, row), (col + 24, row + 24), (col, row + 24),
        (col, row)))
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt("MULTIPOLYGON(((%s)))" % ring))
    f.SetField("class_code", code)
    lyr.CreateFeature(f)
    f = None
lyr = pkg.CreateLayer("points", utm, ogr.wkbPoint, ["GEOMETRY_NAME=geom"])
lyr.CreateField(ogr.FieldDefn("class_code", ogr.OFTInteger))
lyr.CreateField(ogr.FieldDefn("size_px", ogr.OFTInteger))
for row, col, code in DOTS:
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt(
        "POINT(%r %r)" % on_grid(col + 0.5, row + 0.5)))
    f.SetField("class_code", code)
    f.SetField("size_px", 3)
    lyr.CreateFeature(f)
    f = None
lyr = pkg = None

# what the mask must hold: the polygons burned in one go on the raster's own
# grid, and every point as the 3 by 3 pixels around its own
want = gdal.GetDriverByName("MEM").Create("", W, H, 1, gdal.GDT_Byte)
want.SetGeoTransform(RGT)
pkg = ogr.Open(os.path.join(folder6, "annotation.gpkg"))
gdal.RasterizeLayer(want, [1], pkg.GetLayerByName("polygons"),
                    options=["ATTRIBUTE=class_code"])
pkg = None
expected = want.GetRasterBand(1).ReadAsArray()
want = None
for row, col, code in DOTS:
    expected[row - 1:row + 2, col - 1:col + 2] = code
ds = gdal.Open(rotated)
run(folder6, ds, 1, ["mask"], want_lines=False, want_boxes=False,
    points_in_mask=True)
ds = None
got = gdal.Open(os.path.join(folder6, "mask_1.tif")).ReadAsArray()
for row, col, code in SQUARES:
    inside = expected == code
    near = np.zeros_like(inside)
    near[max(0, row - 30):row + 55, max(0, col - 30):col + 55] = True
    inside &= near
    check("the square at row %d, column %d is all there" % (row, col),
          int(inside.sum()) > 0 and bool((got[inside] == code).all()),
          "%d of %d px" % (int((got[inside] == code).sum()), int(inside.sum())))
for row, col, code in DOTS:
    check("the point at row %d, column %d covers its 3 by 3 pixels"
          % (row, col),
          bool((got[row - 1:row + 2, col - 1:col + 2] == code).all())
          and int((got == code).sum()) == int((expected == code).sum()),
          got[row - 1:row + 2, col - 1:col + 2].tolist())
check("and the mask is the annotation burned on the rotated grid, "
      "pixel for pixel", bool((got == expected).all()),
      "%d px differ" % int((got != expected).sum()))

print()
print("a PNG is painted into a scratch file on disk, not held in memory")
# In memory the painted image, the plain one and the mask were held whole,
# about seven bytes a pixel: 8 GB for a photograph of 40000 x 30000.
folder7 = os.path.join(tmp, "scratch")
os.makedirs(folder7)
target = os.path.join(folder7, "probe.png")
probe = g["open_for_write"]("PNG", target, 50, 40, 3,
                            (0.0, 1.0, 0.0, 0.0, 0.0, -1.0), "")
check("what a PNG is painted into is a GeoTIFF on disk",
      probe.GetDriver().ShortName == "GTiff", probe.GetDriver().ShortName)
check("beside the PNG",
      any(f.startswith("probe.png") and f != "probe.png"
          for f in os.listdir(folder7)), os.listdir(folder7))
probe = None
if "drop_scratch" in g:
    g["drop_scratch"](target)
check("and it goes when it is dropped", not os.listdir(folder7),
      os.listdir(folder7))
shutil.copy(os.path.join(folder, "annotation.gpkg"), folder7)
ds = gdal.Open(raster)
png7, _ = run(folder7, ds, 1, ["painted", "mask"], driver=".png",
              gdriver="PNG")
tif7, _ = run(folder7, ds, 1, ["painted"])
ds = None
left = [f for f in os.listdir(folder7) if ".part" in f]
check("no scratch file is left once the PNG is written", not left, left)
check("and the PNG holds the very pixels of the GeoTIFF",
      np.array_equal(gdal.Open(png7[0]).ReadAsArray(),
                     gdal.Open(tif7[0]).ReadAsArray()))
broken = os.path.join(tmp, "scratch_broken")
os.makedirs(broken)
shutil.copy(os.path.join(folder, "annotation.gpkg"), broken)
ds = gdal.Open(raster)
recipe = {"ds": ds, "scale": 1, "rgb": [1, 2, 3],
          "limits": [(7000.0, 11000.0)] * 3, "alpha": 45, "colours": COLOURS,
          "outputs": [("painted", os.path.join(broken, "painted.png"), "PNG"),
                      ("mask", os.path.join(broken, "no", "m.png"), "PNG")],
          "package": os.path.join(broken, "annotation.gpkg"),
          "want_lines": True, "want_points": True, "want_boxes": True,
          "points_in_mask": False, "dot_px": 3}
try:
    paint_whole(recipe)
except Exception:
    pass
ds = None
check("a PNG that fails leaves neither itself nor its scratch file",
      os.listdir(broken) == ["annotation.gpkg"], os.listdir(broken))

shutil.rmtree(tmp, ignore_errors=True)
print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
