"""Rasters at different resolutions, on different origins, in different
systems. Real GDAL, real files, and the arithmetic lifted out of rasterlabel.py
as written.

The question being asked: when the cutout module reads several layers onto one
grid, do the pieces really stack, and does the class raster keep its codes."""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast, os, shutil, sys, tempfile

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()

SRC = os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)
WANTED = ("on_edge", "snap", "window_transform", "aligned", "read_on_grid",
          "north_up", "north_up_of", "resampling_for", "burn", "Stencil", "write_tif", "landed",
          "long_path", "MAX_WINDOW_PX", "MIN_AREA_PX", "pixel_grid",
          "PICTURE_GRID")
pieces = []
for node in tree.body:
    name = getattr(node, "name", None)
    if isinstance(node, ast.Assign):
        name = getattr(node.targets[0], "id", None)
    if name in WANTED:
        pieces.append("".join(lines[node.lineno - 1:node.end_lineno]))

g = {"os": os, "np": np, "gdal": gdal, "ogr": ogr, "osr": osr,
     "log": lambda m: print("      [log]", m)}
exec("\n".join(pieces), g)
snap, window_transform = g["snap"], g["window_transform"]
aligned, read_on_grid = g["aligned"], g["read_on_grid"]
write_tif, on_edge = g["write_tif"], g["on_edge"]

FOLDER = tempfile.mkdtemp(prefix="rl_mixed_")

fails = []


def check(name, condition, detail=""):
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))
    if not condition:
        fails.append(name)


def make(path, gt, w, h, bands, epsg=32633, dtype=gdal.GDT_Byte, fill=None):
    ds = gdal.GetDriverByName("GTiff").Create(path, w, h, bands, dtype)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    for b in range(1, bands + 1):
        band = ds.GetRasterBand(b)
        if fill is not None:
            band.WriteArray(fill if fill.ndim == 2 else fill[b - 1])
        else:
            col = np.arange(w, dtype=np.uint8)
            band.WriteArray(np.tile(col, (h, 1)) * (b * 7 % 251))
    ds.FlushCache()
    ds = None
    return path


# the reference: 5 cm pixels, origin on a round number
FINE = os.path.join(FOLDER, "fine.tif")
FINE_GT = (400000.0, 0.05, 0.0, 4100000.0, 0.0, -0.05)
make(FINE, FINE_GT, 800, 800, 3)

# a second image at 20 cm, four fine pixels to one of its own, same origin
COARSE = os.path.join(FOLDER, "coarse.tif")
COARSE_GT = (400000.0, 0.20, 0.0, 4100000.0, 0.0, -0.20)
make(COARSE, COARSE_GT, 200, 200, 3)

# and a third at 7 cm, which divides into nothing, on an origin of its own
ODD = os.path.join(FOLDER, "odd.tif")
ODD_GT = (399999.93, 0.07, 0.0, 4100000.11, 0.0, -0.07)
make(ODD, ODD_GT, 600, 600, 3)

# a class map at 5 cm: three bands of codes, so nearest neighbour is the only
# resampling that may be used on it
codes = np.zeros((800, 800), np.uint8)
codes[:400] = 1
codes[400:] = 3
codes[200:260, 200:260] = 7
CLASSES = os.path.join(FOLDER, "classes.tif")
make(CLASSES, FINE_GT, 800, 800, 1, fill=codes)

print("what the grids are")
for path in (FINE, COARSE, ODD):
    ds = gdal.Open(path)
    gt = ds.GetGeoTransform()
    print("   %-10s %.3f m, origin %.2f %.2f, %d x %d"
          % (os.path.basename(path), gt[1], gt[0], gt[3],
             ds.RasterXSize, ds.RasterYSize))
    ds = None

print()
print("which grids count as the same grid")
check("a raster is on its own grid", aligned(FINE_GT, FINE_GT))
check("four to one, same origin, is not the same grid",
      not aligned(FINE_GT, COARSE_GT))
check("the odd one is not either", not aligned(FINE_GT, ODD_GT))
shifted = (FINE_GT[0] + 20 * 0.05, 0.05, 0.0, FINE_GT[3] - 13 * 0.05, 0.0, -0.05)
check("a whole number of pixels away is still the same grid",
      aligned(FINE_GT, shifted))
half = (FINE_GT[0] + 0.025, 0.05, 0.0, FINE_GT[3], 0.0, -0.05)
check("half a pixel away is not", not aligned(FINE_GT, half))

print()
print("one cutout, three rasters, one grid")


class Rect(object):
    def __init__(self, a, b, c, d):
        self.v = [a, b, c, d]
    def xMinimum(self): return self.v[0]
    def yMinimum(self): return self.v[1]
    def xMaximum(self): return self.v[2]
    def yMaximum(self): return self.v[3]


# a frame of 10 m, taken on the fine grid: 200 by 200 of its pixels
rect = Rect(400010.0, 4099990.0, 400020.0, 4100000.0)
first = gdal.Open(FINE)
col, row, w, h = snap(first.GetGeoTransform(), (800, 800), rect)
check("the frame is 200 by 200 fine pixels", (w, h) == (200, 200), (w, h))
gt = window_transform(first.GetGeoTransform(), col, row)

arrays = {}
for name, path in (("fine", FINE), ("coarse", COARSE), ("odd", ODD)):
    ds = gdal.Open(path)
    array, nodata, resampled = read_on_grid(ds, [1, 2, 3], gt, w, h)
    arrays[name] = array
    check("%s comes back %d by %d whatever its own pixel is"
          % (name, h, w), array.shape == (3, h, w), array.shape)
    check("%s says whether it had to be resampled" % name,
          bool(resampled) == (name != "fine"), resampled)
    ds = None

check("every layer of the cutout has exactly the same shape",
      len({a.shape for a in arrays.values()}) == 1,
      {k: v.shape for k, v in arrays.items()})

print()
print("the class map is never blurred")
ds = gdal.Open(CLASSES)
array, nodata, resampled = read_on_grid(ds, [1], gt, w, h)
present = set(np.unique(array[0]).tolist())
check("only codes that exist come back", present <= {0.0, 1.0, 3.0, 7.0},
      sorted(present))
ds = None

# the same class map read onto the coarse grid, which is the case that would
# invent a code halfway between two if anything but nearest were used
coarse_first = gdal.Open(COARSE)
c_col, c_row, cw, ch = snap(COARSE_GT, (200, 200), rect)
c_gt = window_transform(COARSE_GT, c_col, c_row)
check("the same frame is 50 by 50 coarse pixels", (cw, ch) == (50, 50),
      (cw, ch))
ds = gdal.Open(CLASSES)
array, nodata, resampled = read_on_grid(ds, [1], c_gt, cw, ch)
present = set(np.unique(array[0]).tolist())
check("read four times coarser, still no invented code",
      present <= {0.0, 1.0, 3.0, 7.0}, sorted(present))
check("and it did have to resample", resampled)
ds = None

print()
print("the ground under a pixel is the same ground in every layer")
# the top left corner of the window, in ground coordinates, read out of each
# array at the same row and column
probe_r, probe_c = 40, 60
x = gt[0] + (probe_c + 0.5) * gt[1]
y = gt[3] + (probe_r + 0.5) * gt[5]
for name, path in (("fine", FINE), ("coarse", COARSE), ("odd", ODD)):
    ds = gdal.Open(path)
    own = ds.GetGeoTransform()
    oc = int((x - own[0]) / own[1])
    orr = int((y - own[3]) / own[5])
    direct = ds.GetRasterBand(1).ReadAsArray(oc, orr, 1, 1)[0][0]
    check("%s: the pixel at row %d column %d is the one over that ground"
          % (name, probe_r, probe_c),
          float(arrays[name][0][probe_r][probe_c]) == float(direct),
          (arrays[name][0][probe_r][probe_c], direct))
    ds = None

print()
print("a frame that hangs over the edge of a coarser raster")
edge = Rect(400000.0 + 195 * 0.20, 4100000.0 - 200 * 0.20,
            400000.0 + 205 * 0.20, 4100000.0 - 190 * 0.20)
c, r, ew, eh = snap(COARSE_GT, (200, 200), edge)
check("clipped, it stops at the raster", (ew, eh) == (5, 10), (ew, eh))
c, r, ew, eh = snap(COARSE_GT, (200, 200), edge, clip=False)
check("unclipped, it keeps its ten by ten", (ew, eh) == (10, 10), (ew, eh))
ds = gdal.Open(COARSE)
array, nodata, resampled = read_on_grid(ds, [1], window_transform(COARSE_GT, c, r),
                                        ew, eh)
check("and the half outside comes back at full size",
      array.shape == (1, 10, 10), array.shape)
ds = None

print()
print("a raster in degrees beside one in metres")
DEG = os.path.join(FOLDER, "degrees.tif")
# roughly the same ground, in EPSG:4326, at about half a metre
DEG_GT = (12.5, 0.0000045, 0.0, 37.5, 0.0, -0.0000045)
make(DEG, DEG_GT, 400, 400, 3, epsg=4326)
ds = gdal.Open(DEG)
check("it is not on the metric grid", not aligned(FINE_GT, ds.GetGeoTransform()))
deg_rect = Rect(12.5001, 37.4991, 12.5003, 37.4993)
c, r, dw, dh = snap(DEG_GT, (400, 400), deg_rect)
check("a window in degrees is still a whole number of its own pixels",
      dw > 0 and dh > 0, (dw, dh))
array, nodata, resampled = read_on_grid(ds, [1, 2, 3],
                                        window_transform(DEG_GT, c, r), dw, dh)
check("and it reads without resampling, being on its own grid",
      not resampled and array.shape == (3, dh, dw), (resampled, array.shape))
ds = None

print()
print("the subtraction that misses a pixel edge by a billionth")
# the case that turned a frame of 200 into a cutout of 201 before on_edge
for res, size in ((0.05, 200), (0.20, 50), (0.07, 143)):
    gt0 = (400000.0, res, 0.0, 4100000.0, 0.0, -res)
    x0 = 400000.0 + 3000 * res
    y1 = 4100000.0 - 2000 * res
    r = Rect(x0, y1 - size * res, x0 + size * res, y1)
    c, rr, ww, hh = snap(gt0, (10000, 10000), r)
    check("at %.2f m a frame of %d pixels stays %d" % (res, size, size),
          (ww, hh) == (size, size), (ww, hh))

def read(ds, bands, gt, w, h, **how):
    """read_on_grid with a role and a system. The build before these took
    neither; it is then asked without them, so what it does instead shows
    up as a failed check rather than as a traceback."""
    try:
        return read_on_grid(ds, bands, gt, w, h, **how)
    except TypeError as err:
        print("      [read_on_grid takes no %s: %s]" % (sorted(how), err))
        return read_on_grid(ds, bands, gt, w, h)


def plane_dem(path):
    """A surface z = 100 + 0.5 x + 0.25 y, in metres from the corner, at the
    centre of every pixel of a 50 cm grid: what interpolation must give back
    exactly, and what nearest neighbour turns into steps."""
    r, c = np.indices((40, 40))
    z = (100 + 0.5 * (c + 0.5) * 0.5 + 0.25 * (r + 0.5) * 0.5)
    ds = gdal.GetDriverByName("GTiff").Create(path, 40, 40, 1,
                                              gdal.GDT_Float32)
    ds.SetGeoTransform((400000.0, 0.5, 0.0, 4100000.0, 0.0, -0.5))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32633)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(z.astype(np.float32))
    ds = None
    return path


print()
print("an image onto a larger pixel is averaged, not picked")
# Stripes of 10 cm, two columns of 20 and two of 220 at 5 cm, read onto
# 25 cm. By nearest neighbour every 25 cm pixel took one 5 cm column and the
# picture came out as stripes of 20 and 220 that are not on the ground
# (aliasing); the ground under each pixel is a mixture.
STRIPES = os.path.join(FOLDER, "stripes.tif")
stripe = np.where((np.arange(400) // 2) % 2 == 0, 20, 220).astype(np.uint8)
make(STRIPES, FINE_GT, 400, 400, 1, fill=np.tile(stripe, (400, 1)))
quarter = (400000.0, 0.25, 0.0, 4100000.0, 0.0, -0.25)
ds = gdal.Open(STRIPES)
array, nodata, how = read(ds, [1], quarter, 40, 40, role="image")
ds = None
footprint = np.tile(stripe, (400, 1))[:200, :200].reshape(
    40, 5, 40, 5).mean(axis=(1, 3))
check("each pixel is the mean of the ground under it",
      np.abs(array[0] - footprint).max() < 0.01,
      (sorted(np.unique(array[0]).tolist())[:6], how))
check("and the manifest is told it was averaged", how == "average", how)

print()
print("an image onto a smaller pixel is interpolated, not stepped")
DEM = plane_dem(os.path.join(FOLDER, "dem.tif"))
ds = gdal.Open(DEM)
inner = (400001.0, 0.05, 0.0, 4099999.0, 0.0, -0.05)
array, nodata, how = read(ds, [1], inner, 360, 360, role="image")
ds = None
r, c = np.indices((360, 360))
x = 1.0 + (c + 0.5) * 0.05
y = 1.0 + (r + 0.5) * 0.05
truth = 100 + 0.5 * x + 0.25 * y
check("a surface read onto 5 cm keeps its slope, no steps of 50 cm",
      np.abs(array[0] - truth).max() < 1e-3,
      (float(np.abs(array[0] - truth).max()), how))
check("by bilinear interpolation", how == "bilinear", how)

print()
print("classes onto a larger pixel take the class most of it holds")
# A map of 25 cm read onto 10 m. In every 10 m block the class around is 2 or
# 4 and a patch of 6 by 6 at its centre is 1 or 3: nearest neighbour took the
# patch at the centre for the whole block, 0 labels of 16 right.
blocks = (np.indices((160, 160))[1] // 40) % 2
around = np.where(blocks == 0, 2, 4)
patch = np.where(blocks == 0, 1, 3)
inside = np.indices((160, 160)) % 40
centre = (np.abs(inside[0] - 19.5) < 3) & (np.abs(inside[1] - 19.5) < 3)
MAJORITY = os.path.join(FOLDER, "majority.tif")
make(MAJORITY, (400000.0, 0.25, 0.0, 4100000.0, 0.0, -0.25), 160, 160, 1,
     fill=np.where(centre, patch, around).astype(np.uint8))
ten = (400000.0, 10.0, 0.0, 4100000.0, 0.0, -10.0)
ds = gdal.Open(MAJORITY)
array, nodata, how = read(ds, [1], ten, 4, 4, role="classes")
ds = None
want = np.where((np.arange(4) % 2) == 0, 2, 4)[None, :].repeat(4, 0)
check("every 10 m pixel has the class of most of its ground",
      np.array_equal(array[0], want), (array[0].tolist(), how))
check("by mode, which only ever gives a class the map holds",
      how == "mode", how)

print()
print("each band keeps its own nodata when it is resampled")
TWO = os.path.join(FOLDER, "two_nodata.tif")
ds = gdal.GetDriverByName("GTiff").Create(TWO, 100, 100, 2, gdal.GDT_Float32)
ds.SetGeoTransform(FINE_GT)
ds.SetProjection(gdal.Open(FINE).GetProjection())
rng = np.random.default_rng(3)
one = rng.uniform(10, 50, (100, 100)).astype(np.float32)
two = rng.uniform(100, 200, (100, 100)).astype(np.float32)
two[:, :50] = 255
ds.GetRasterBand(1).WriteArray(one)
ds.GetRasterBand(1).SetNoDataValue(-9999)
ds.GetRasterBand(2).WriteArray(two)
ds.GetRasterBand(2).SetNoDataValue(255)
ds = None
ds = gdal.Open(TWO)
array, nodata, how = read(ds, [1, 2], quarter, 20, 20, role="image")
ds = None
right = two[:, 50:].reshape(20, 5, 10, 5).mean(axis=(1, 3))
check("band 2 is its nodata where it has no data",
      (array[1][:, :10] == 255).all(), array[1][:3, :12].tolist())
check("and the mean of its own data elsewhere, its nodata left out",
      np.abs(array[1][:, 10:] - right).max() < 0.01,
      float(np.abs(array[1][:, 10:] - right).max()))

print()
print("past the edge of a resampled image with no nodata: NaN, not black")
# The 7 cm image ends at 400041.93. A window of the 5 cm grid reaching past
# it is read by Warp, which used to fill the outside with zeros: black
# pixels that cannot be told from the ground.
edge_gt = (400040.0, 0.05, 0.0, 4099990.0, 0.0, -0.05)
ds = gdal.Open(ODD)
array, nodata, how = read(ds, [1, 2, 3], edge_gt, 100, 20, role="image")
ds = None
xs = edge_gt[0] + (np.arange(100) + 0.5) * 0.05
past = xs > ODD_GT[0] + 600 * 0.07 + 0.07
within = xs < ODD_GT[0] + 600 * 0.07 - 0.07
check("the part past the edge comes back as NaN in every band",
      np.isnan(array[:, :, past]).all(),
      np.unique(array[:, :, past])[:4].tolist())
check("and the part over the image does not", np.isfinite(
    array[:, :, within]).all())

print()
print("a raster stored bottom row first is read exactly")
NORTH_DOWN = os.path.join(FOLDER, "north_down.tif")
ND_GT = (400000.0, 0.05, 0.0, 4099990.0, 0.0, 0.05)
stored = (np.indices((200, 200)).sum(0) % 251).astype(np.uint8)
make(NORTH_DOWN, ND_GT, 200, 200, 1, fill=stored)
north = g.get("north_up")
check("north_up describes it from the top row",
      north is not None
      and tuple(north(ND_GT, 200)) == (400000.0, 0.05, 0.0, 4100000.0, 0.0,
                                       -0.05),
      north and north(ND_GT, 200))
PICTURE = os.path.join(FOLDER, "picture.tif")
gdal.GetDriverByName("GTiff").Create(PICTURE, 20, 10, 1, gdal.GDT_Byte)
north_of = g.get("north_up_of")
ds = gdal.Open(PICTURE)
# GDAL answers (0, 1, 0, 0, 0, 1) for it, rows going up; QGIS draws it at
# y = -row, and that is the grid a cutout of it is taken on
check("but a file with no geotransform at all is on the grid QGIS draws it "
      "on, y = -row, not turned over",
      north_of is not None
      and tuple(north_of(ds)) == (0.0, 1.0, 0.0, 0.0, 0.0, -1.0),
      north_of and north_of(ds))
ds = None
window = (400000.0 + 20 * 0.05, 0.05, 0.0, 4100000.0 - 30 * 0.05, 0.0, -0.05)
ds = gdal.Open(NORTH_DOWN)
array, nodata, how = read(ds, [1], window, 50, 40, role="image")
ds = None
check("its pixels come back as they are, turned the right way up",
      np.array_equal(array[0], stored[::-1][30:70, 20:70]),
      array[0][:2, :4].tolist())
check("with no resampling", not how, how)

print()
print("a layer in another system is reprojected onto the grid")
# The map of classes, warped into EPSG:4326 and read back onto the 5 cm UTM
# grid of the first layer. It used to be left out of every cutout.
IN_DEGREES = os.path.join(FOLDER, "classes_4326.tif")
gdal.Warp(IN_DEGREES, CLASSES, dstSRS="EPSG:4326", resampleAlg="near")
utm = gdal.Open(FINE).GetProjection()
window = (400008.0, 0.05, 0.0, 4099988.0, 0.0, -0.05)
ds = gdal.Open(IN_DEGREES)
array, nodata, how = read(ds, [1], window, 200, 200, role="classes",
                          wkt=utm)
ds = None
truth = codes[240:440, 160:360]
agree = float((array[0] == truth).mean())
check("it lands on the same ground: its classes agree with the map",
      agree > 0.97, agree)
check("with no code it does not hold",
      set(np.unique(array[0]).tolist()) <= {0.0, 1.0, 3.0, 7.0},
      np.unique(array[0])[:8].tolist())
check("and it says it was resampled", bool(how), how)

print()
print("what is written out is on the grid it says it is")
out = os.path.join(FOLDER, "cut_fine.tif")
write_tif(out, (arrays["fine"]).astype(np.uint8), gt,
          gdal.Open(FINE).GetProjection())
ds = gdal.Open(out)
check("the file carries the window transform",
      [round(v, 9) for v in ds.GetGeoTransform()] == [round(v, 9) for v in gt],
      ds.GetGeoTransform())
check("and the size it was read at", (ds.RasterXSize, ds.RasterYSize) == (w, h),
      (ds.RasterXSize, ds.RasterYSize))
ds = None

print()
print("FAILED: %d" % len(fails) if fails else "all of them pass")
for f in fails:
    print("   " + f)
# Removed at the end, not left behind. This folder used to be a fixed one
# under /tmp, which on Windows is a tmp folder at the root of the drive,
# and every run left its files there. The two rasters still held open above
# are let go first, or Windows refuses to delete them.
first = coarse_first = None
shutil.rmtree(FOLDER, ignore_errors=True)
sys.exit(1 if fails else 0)
