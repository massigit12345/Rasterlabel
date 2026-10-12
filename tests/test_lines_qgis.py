"""The strip a line claims, with the real geometry classes and the real burn.

test_lines.py runs strip() against a stand-in for the geometry. What a stand-in
cannot say is what GDAL does with the polygon that comes out: a pixel is burned
when its centre is inside, and the strip is made of whole pixels so that it
burns to exactly the pixels it counted, in one piece, at every angle and at
every width. A strip that burned a pixel more or less than it said, or came
back in several parts, would put a different mask on disk from the one on the
screen.

The width itself is measured in test_lines.py. Here: the count of the strip is
the count of the burned mask, it is one polygon, and it is as wide at a slant
as along a row, for the widths 2 and up (a width of 1 is the thinnest unbroken
chain, and says so).

Needs QGIS and GDAL; tests/run.py skips it where QGIS is missing and, with
RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgiskit as K  # noqa: E402
import numpy as np  # noqa: E402
from osgeo import gdal, ogr  # noqa: E402
from qgis.core import QgsPointXY  # noqa: E402

gdal.UseExceptions()
print("QGIS %s" % K.QGIS_VERSION)
g = K.g
fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail != "" and not cond else ""))
    if not cond:
        fails.append(name)


PX = 0.05
OX, OY = 4000000.0, 4100000.0
SIZE = 150
geometry = object.__new__(g["Geometry"])
geometry.pixel_crs = (PX, PX)
geometry.origin = (OX, OY)


def burn(polygon):
    """The mask GDAL burns from the polygon, pixel centre rule."""
    ds = gdal.GetDriverByName("MEM").Create("", SIZE, SIZE, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((OX, PX, 0, OY, 0, -PX))
    mem = g["Stencil"].in_memory("strip")
    layer = mem.CreateLayer("strip", None, ogr.wkbPolygon)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(ogr.CreateGeometryFromWkb(bytes(polygon.asWkb())))
    layer.CreateFeature(feature)
    gdal.RasterizeLayer(ds, [1], layer, burn_values=[1])
    return ds.ReadAsArray().astype(bool)


def trace(points):
    return [QgsPointXY(OX + c * PX, OY - r * PX) for c, r in points]


print("the strip burns to the pixels it counted")
for n in (1, 2, 3, 5):
    for angle in (0, 15, 30, 45, 60, 90, 135):
        a = (60.3, 20.7)
        b = (a[0] + 70 * math.cos(math.radians(angle)),
             a[1] + 70 * math.sin(math.radians(angle)))
        band, covered = geometry.strip(trace([a, b]), n)
        mask = burn(band)
        parts = band.constGet().partCount() if band.isMultipart() else 1
        check("%d px at %d degrees: %d counted, %d burned, one piece"
              % (n, angle, covered, int(mask.sum())),
              covered == int(mask.sum()) and parts == 1,
              (covered, int(mask.sum()), parts))

print()
print("a polyline with a sharp turn burns to what it counted")
for n in (1, 3, 5):
    pts = [(10.5, 10.5), (60.5, 10.5), (15.0, 26.0)]
    band, covered = geometry.strip(trace(pts), n)
    mask = burn(band)
    parts = band.constGet().partCount() if band.isMultipart() else 1
    check("%d px: counted %d, burned %d, one piece" % (n, covered, int(mask.sum())),
          covered == int(mask.sum()) and parts == 1, (covered, int(mask.sum()), parts))

print()
print("a freehand trace burns to what it counted, in one piece")
# many short stretches off the line by a fraction of a pixel, with a point
# repeated, the way the mouse gives them
rnd = np.random.RandomState(11)
for n in (1, 2, 3, 5):
    for angle in (0, 20, 45, 90):
        th = math.radians(angle)
        pts = []
        for i in range(0, 90, 2):
            j = rnd.uniform(-0.3, 0.3)
            pts.append((20.0 + i * math.cos(th) - j * math.sin(th),
                        20.0 + i * math.sin(th) + j * math.cos(th)))
        pts.insert(10, pts[10])
        band, covered = geometry.strip(trace(pts), n)
        mask = burn(band)
        parts = band.constGet().partCount() if band.isMultipart() else 1
        check("%d px at %d degrees: counted %d, burned %d, one piece"
              % (n, angle, covered, int(mask.sum())),
              covered == int(mask.sum()) and parts == 1,
              (covered, int(mask.sum()), parts))

print()
print("the width is the same at a slant")
for n in (3, 5):
    wide = {}
    for angle in (0, 30, 45, 60, 90):
        got = []
        for start in ((60.3, 20.7), (60.7, 20.2), (60.5, 20.5), (60.1, 20.9)):
            b = (start[0] + 60 * math.cos(math.radians(angle)),
                 start[1] + 60 * math.sin(math.radians(angle)))
            band, covered = geometry.strip(trace([start, b]), n)
            got.append(covered / (60.0 + n))
        wide[angle] = sum(got) / len(got)
    check("%d px: along a row %.2f, at 45 degrees %.2f, at 60 degrees %.2f"
          % (n, wide[0], wide[45], wide[60]),
          all(abs(w - n) <= 0.06 * n for w in wide.values()), wide)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
