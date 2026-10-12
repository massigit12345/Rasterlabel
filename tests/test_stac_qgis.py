"""What a STAC item says of a place, against the real QGIS classes.

The footprint of a cutout and the fields of the projection extension are
made with QGIS's own coordinate systems and transforms, which no fake
stands in for:

  proj:wkt2 holds WKT2. A system with no EPSG code went into the item as
  the WKT1 QGIS hands out, which a reader of the field takes for what it
  says it is; it is WKT2 now, or the field is left out when it cannot be
  made;
  the footprint is a closed ring that runs counter-clockwise, the exterior
  ring of a GeoJSON polygon (RFC 7946), in a system north of the equator
  and in one south of it, and in degrees.

Needs QGIS itself, its Python and its classes, and GDAL, which comes with
it. tests/run.py skips it where QGIS is missing and, with RL_REQUIRE_QGIS=1,
fails it instead.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.environ.get("RL_ROOT") or os.path.dirname(_HERE)
SRC = os.environ.get("RL_SRC", os.path.join(_ROOT, "dist", "rasterlabel.py"))
sys.path.insert(0, os.path.join(_HERE, "fixtures", "stac"))

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail != "" and not cond else ""))
    if not cond:
        fails.append(name)


def finish():
    print()
    print("FAILED: %d" % len(fails) if fails else "all pass")
    for f in fails:
        print("   " + f)
    sys.stdout.flush()
    # os._exit: the QGIS application object is not torn down, and a teardown
    # that crashes would turn a passing run into a failed one.
    os._exit(1 if fails else 0)


try:
    from qgis.core import Qgis, QgsApplication
    from osgeo import gdal, osr
    import minischema
except ImportError as e:
    print("QGIS is not importable here: %s" % e)
    sys.exit(1)

gdal.UseExceptions()
app = QgsApplication([], False)
app.initQgis()
print("QGIS %s, GDAL %s" % (Qgis.QGIS_VERSION, gdal.__version__))

code = open(SRC, encoding="utf-8").read().replace("\nstart()\n", "\n")
g = {"__name__": "rasterlabel", "__file__": SRC}
exec(compile(code, SRC, "exec"), g)


def area(ring):
    """The signed area of a closed ring: positive counter-clockwise."""
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:])) / 2


def wkt_of(text):
    srs = osr.SpatialReference()
    if text.startswith("EPSG:"):
        srs.ImportFromEPSG(int(text[5:]))
    else:
        srs.ImportFromProj4(text)
    return srs.ExportToWkt()


print("the footprint")
BOX = (500010.0, 4099970.0, 500030.0, 4099990.0)
for words, text, box in (
        ("UTM 33N, north of the equator", "EPSG:32633", BOX),
        ("UTM 33S, south of it", "EPSG:32733",
         (500010.0, 6000000.0, 500030.0, 6000020.0)),
        ("degrees", "EPSG:4326", (13.5, 37.3, 13.6, 37.4)),
        ("a system of its own", "+proj=tmerc +lat_0=0 +lon_0=13.37 +k=0.9996 "
                                "+x_0=123456 +y_0=7 +datum=WGS84 +units=m",
         (123500.0, 4100000.0, 123520.0, 4100020.0))):
    shape, bbox = g["lonlat_footprint"](box, wkt_of(text))
    ring = (shape or {"coordinates": [[]]})["coordinates"][0]
    check("%s: a closed ring of five points" % words,
          len(ring) == 5 and ring[0] == ring[-1], ring)
    check("%s: running counter-clockwise" % words, area(ring) > 0, ring)
    check("%s: and the bbox is the ring's" % words, bbox == [
        min(p[0] for p in ring), min(p[1] for p in ring),
        max(p[0] for p in ring), max(p[1] for p in ring)], bbox)
check("with no system there is no footprint",
      g["lonlat_footprint"](BOX, "") == (None, None))

print()
print("the projection fields")
GT = (500010.0, 0.5, 0.0, 4099990.0, 0.0, -0.5)
fields = g["projection_of"](GT, 40, 40, wkt_of("EPSG:32633"), BOX)
check("a system with a code gives proj:epsg and no wkt2",
      fields["proj:epsg"] == 32633 and "proj:wkt2" not in fields, fields)
custom = wkt_of("+proj=tmerc +lat_0=0 +lon_0=13.37 +k=0.9996 +x_0=123456 "
                "+y_0=7 +datum=WGS84 +units=m")
fields = g["projection_of"](GT, 40, 40, custom, BOX)
check("one without gives no epsg", fields["proj:epsg"] is None, fields)
text = fields.get("proj:wkt2", "")
check("and WKT2: a PROJCRS, not the PROJCS of WKT1",
      text.startswith("PROJCRS[") and "PROJCS[" not in text, text[:60])
back = osr.SpatialReference()
check("which GDAL reads back as the same system",
      bool(text) and back.ImportFromWkt(text) == 0
      and bool(back.IsSame(osr.SpatialReference(wkt=custom))), text[:60])
errors = minischema.validate(
    {"type": "Feature", "stac_extensions": [g["PROJ_EXT"]], "assets": {},
     "properties": dict(fields, datetime="2025-01-01T00:00:00Z")},
    "projection")
check("the item holds against the projection extension, v1.1.0",
      not errors, errors)
fields = g["projection_of"](GT, 40, 40, "not a system at all", BOX)
check("a text that is no system at all is not passed off as WKT2",
      "proj:wkt2" not in fields, fields)
check("the shape is rows first, the transform the affine, the bbox the box",
      fields["proj:shape"] == [40, 40]
      and fields["proj:transform"] == [0.5, 0.0, 500010.0, 0.0, -0.5,
                                       4099990.0, 0.0, 0.0, 1.0]
      and fields["proj:bbox"] == list(BOX), fields)

finish()
