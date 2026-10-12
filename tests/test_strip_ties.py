"""A mask written in strips is the mask one pass would write, ties included.

A pixel whose centre lies exactly on the edge of a polygon is a tie, and
which side takes it is a matter of the last digit of a coordinate. The
strips of Whole used to be burned on a grid moved down by their first row,
which moved the rounding with it: the same polygon painted a pixel at one
strip height and not at another. Now every strip is burned from the shapes
in the pixels of the whole raster, shifted by whole rows, which is exact,
so the strip height cannot change a single pixel.

The shapes here all have their edges on pixel centres, the worst case, in a
grid whose pixel (0.05) is not a number a computer holds exactly.

The program is the built file, run as it is shipped; QGIS is faked, see
correctkit.py."""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                                 # noqa: E402
from osgeo import gdal, ogr, osr                                   # noqa: E402
import correctkit as K                                             # noqa: E402

gdal.UseExceptions()
g, check = K.g, K.check
Stencil = g["Stencil"]

tmp = tempfile.mkdtemp(prefix="strip_ties_")
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)
WKT = srs.ExportToWkt()


def package(path, gt, w, h, edges_on_centres, seed=3):
    """A GeoPackage of 120 rectangles, as many as there are classes 1 to 3.
    With edges_on_centres every edge lies on the centre of a pixel row or
    column; without, a quarter of a pixel off it."""
    rng = np.random.default_rng(seed)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    layer = ds.CreateLayer("polygons", srs, ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn("class_code", ogr.OFTInteger))
    shift = 0.5 if edges_on_centres else 0.25
    for i in range(120):
        c0 = int(rng.integers(0, w - 20))
        r0 = int(rng.integers(0, h - 40))
        c1 = c0 + int(rng.integers(3, 20))
        r1 = r0 + int(rng.integers(3, 40))
        corners = []
        for c, r in ((c0, r0), (c1, r0), (c1, r1), (c0, r1), (c0, r0)):
            col, row = c + shift, r + shift
            corners.append((gt[0] + col * gt[1] + row * gt[2],
                            gt[3] + col * gt[4] + row * gt[5]))
        f = ogr.Feature(layer.GetLayerDefn())
        f.SetGeometry(ogr.CreateGeometryFromWkt("POLYGON((%s))" % ",".join(
            "%r %r" % p for p in corners)))
        f.SetField("class_code", 1 + i % 3)
        layer.CreateFeature(f)
        f = None
    ds = None


def strips(stencil, gt, w, h, height, whole=True):
    """The window of the whole raster, put together from strips. None from a
    build whose burn_into does not take the whole raster yet."""
    try:
        return pieces(stencil, gt, w, h, height, whole)
    except TypeError:
        return None


def pieces(stencil, gt, w, h, height, whole):
    out, row = [], 0
    while row < h:
        take_ = min(height, h - row)
        strip = (gt[0] + row * gt[2], gt[1], gt[2],
                 gt[3] + row * gt[5], gt[4], gt[5])
        extra = {"whole": tuple(gt), "row": row} if whole else {}
        out.append(stencil.burn_into(strip, w, take_, WKT, **extra))
        row += take_
    return np.vstack(out)


GRIDS = {"north up, 5 cm": (400000.0, 0.05, 0.0, 4100000.0, 0.0, -0.05),
         "rotated": (400000.0, 0.0499, 0.004, 4100000.0, 0.004, -0.0499),
         "pixels of 7 mm": (400123.456, 0.007, 0.0, 4100321.987, 0.0, -0.007)}
W, H = 300, 500

for label, gt in GRIDS.items():
    print()
    print(label + ", every edge on a pixel centre")
    path = os.path.join(tmp, label.split(",")[0].replace(" ", "_") + ".gpkg")
    package(path, gt, W, H, True)
    st = Stencil(path, "polygons", "class_code", WKT)
    check("the stencil holds the 120 rectangles", st.ok and st.count == 120,
          (st.ok, st.count))
    one = strips(st, gt, W, H, H)
    if one is None:
        one = st.burn_into(gt, W, H, WKT)
    check("one pass paints something", int((one > 0).sum()) > 5000,
          int((one > 0).sum()))
    for height in (1, 7, 64, 333):
        got = strips(st, gt, W, H, height)
        check("strips of %d rows paint the pixels one pass paints" % height,
              got is not None and np.array_equal(got, one),
              None if got is None else int((got != one).sum()))
    # for the record: the grid moved down strip by strip, which is what was
    # done, does not hold on this fixture. Said, not asserted: it is the last
    # digit of a coordinate, and GDAL may one day round it the same way.
    moved = pieces(st, gt, W, H, 7, False)
    print("      (moving the grid strip by strip paints %d pixels other than "
          "one pass does)" % int((moved != st.burn_into(gt, W, H, WKT)).sum()))
    st.close()

print()
print("edges off the centres: the same as GDAL's own pass over the raster")
# Off the ties nothing is a matter of the last digit, and the shapes in the
# pixels of the raster must give what GDAL gives for them in map coordinates.
for label, gt in GRIDS.items():
    path = os.path.join(tmp, "clear_" + label.split(",")[0].replace(" ", "_")
                        + ".gpkg")
    package(path, gt, W, H, False, seed=5)
    st = Stencil(path, "polygons", "class_code", WKT)
    ours = strips(st, gt, W, H, 64)
    theirs = st.burn_into(gt, W, H, WKT)
    check("%s: %d pixels painted, none different from GDAL's"
          % (label, int((theirs > 0).sum())),
          np.array_equal(ours, theirs) and (theirs > 0).any(),
          int((ours != theirs).sum()))
    # the shifted window of a big raster too: a piece taken from the middle
    c0, r0, ww, hh = 37, 123, 111, 201
    piece_gt = (gt[0] + c0 * gt[1] + r0 * gt[2], gt[1], gt[2],
                gt[3] + c0 * gt[4] + r0 * gt[5], gt[4], gt[5])
    piece = st.burn_into(piece_gt, ww, hh, WKT, whole=tuple(gt), col=c0,
                         row=r0)
    check("%s: and a piece from the middle is that piece of it" % label,
          np.array_equal(piece, theirs[r0:r0 + hh, c0:c0 + ww]),
          int((piece != theirs[r0:r0 + hh, c0:c0 + ww]).sum()))
    st.close()

print()
print("burning from the pixels of the raster says nothing to the console")
# GDAL 3.8 (QGIS 3.36) warned "Failed to fetch spatial reference on layer"
# at every strip when the shapes in pixels had no system and the raster
# they were burned into had none either. A warning at every strip of a large
# raster is thousands of lines in the log.
said = []


def listen(kind, number, message):
    said.append((kind, message))


gt = GRIDS["north up, 5 cm"]
path = os.path.join(tmp, "north_up.gpkg")
st = Stencil(path, "polygons", "class_code", WKT)
gdal.PushErrorHandler(listen)
try:
    for row in range(0, H, 64):
        st.burn_into(gt, W, min(64, H - row), WKT, whole=tuple(gt), row=row)
finally:
    gdal.PopErrorHandler()
check("no warning or error over %d strips" % len(range(0, H, 64)),
      not said, said[:2])
st.close()

print()
print("a grid with no inverse falls back to the grid of the window")
flat = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
gt = GRIDS["north up, 5 cm"]
path = os.path.join(tmp, "north_up.gpkg")
st = Stencil(path, "polygons", "class_code", WKT)
try:
    got = st.burn_into(gt, W, 10, WKT, whole=flat, row=0)
except TypeError:
    got = None
check("it burns the window as it always did, and does not raise",
      got is not None and np.array_equal(got, st.burn_into(gt, W, 10, WKT)))
st.close()

print()
print("Whole, strip by strip, and the card that counts it again")
# the same rectangles as a mask, written by paint_whole with strips of
# several heights; the card recounts the pixels with the same stencils
gt = GRIDS["north up, 5 cm"]
raster = os.path.join(tmp, "ortho.tif")
ds = gdal.GetDriverByName("GTiff").Create(raster, W, H, 3, gdal.GDT_Byte)
ds.SetGeoTransform(gt)
ds.SetProjection(WKT)
for b in range(3):
    ds.GetRasterBand(b + 1).WriteArray(np.full((H, W), 100 + b, np.uint8))
ds = None
package_path = os.path.join(tmp, "north_up.gpkg")


def mask_with(strip_rows):
    g["STRIP_ROWS"] = strip_rows
    src = gdal.Open(raster)
    path = os.path.join(tmp, "mask_%d.tif" % strip_rows)
    g["paint_whole"]({
        "ds": src, "scale": 1, "rgb": [1, 2, 3], "limits": [(0.0, 255.0)] * 3,
        "alpha": 45, "colours": {1: (1, 1, 1), 2: (2, 2, 2), 3: (3, 3, 3)},
        "outputs": [("mask", path, "GTiff")], "package": package_path,
        "want_lines": False, "want_points": False, "want_boxes": False,
        "points_in_mask": False, "dot_px": 1})
    src = None
    f = gdal.Open(path)
    out = f.GetRasterBand(1).ReadAsArray()
    f = None
    return out


one_pass = mask_with(100000)
check("one pass paints the rectangles", int((one_pass > 0).sum()) > 5000)
for rows in (1, 7, 64, 333):
    got = mask_with(rows)
    check("strips of %d rows write the mask one pass writes" % rows,
          np.array_equal(got, one_pass), int((got != one_pass).sum()))
g["STRIP_ROWS"] = 64
counted = g["card_burn"](package_path, {"mode": "all"}, gt, (0, 0, W, H),
                         WKT)["counts"]
written = {int(v): int((one_pass == v).sum()) for v in np.unique(one_pass)}
check("and the card counts, tie pixels included, what the mask holds",
      {k: v for k, v in counted.items() if v} == written,
      (counted, written))
window = g["card_burn"](package_path, {"mode": "all"}, gt,
                        (37, 123, 111, 201), WKT)["counts"]
piece = one_pass[123:123 + 201, 37:37 + 111]
check("for a window in the middle of the raster too",
      {k: v for k, v in window.items() if v}
      == {int(v): int((piece == v).sum()) for v in np.unique(piece)}, window)

shutil.rmtree(tmp, ignore_errors=True)
sys.exit(K.finish())
