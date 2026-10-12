"""Degrees or metres is decided by the units of the coordinate system, never by
its kind or by whether it has an EPSG code.

What went wrong. An orthomosaic in WGS 84 declares, in its GeoTIFF keys, a
TOWGS84 of seven zeros. GDAL hands that over as a BOUNDCRS: WGS 84 bound to
WGS 84 by a transformation that does nothing. QGIS 3.36 gives such a system no
authid and answers isGeographic() False for it, because a bound system is not
a geographic one by type. Its coordinates are degrees all the same.

  * The manifest kept authid(), so it said "crs": "" about a perfectly good
    system, which is what a photograph with no system writes.
  * Geometry took "not geographic" for "metres": the round brush of half a
    metre was buffered by half a DEGREE, the preview circle covered the whole
    screen and one click filled the frame.
  * The log said "drawing in ?, measuring in ?".

The functions are taken out of the shipped file as written and run against
fakes that behave the way QGIS 3.36 does with that raster: the bound system
has no authid, isGeographic() False and mapUnits() degrees. Geometry is the
real class. Coordinates go through a local plane that is exact enough for a
circle of half a metre; test_boundcrs_gdal.py does the same through PROJ.

No QGIS needed, and no GDAL: shapely does the geometry.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import math
import os as _os
import sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

try:
    from shapely import affinity
    from shapely.geometry import Point as SPoint, box
    from shapely.ops import transform as reproject
except ImportError:
    print("shapely is missing: pip install shapely")
    sys.exit(1)

SRC = _os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail != "" and not cond else ""))
    if not cond:
        fails.append(name)


def take(name):
    """A top-level function or class of the shipped file, or None when this
    build has none of that name (the build before the fix lacks the helpers,
    and the checks that need them then fail instead of crashing the suite)."""
    for node in tree.body:
        if getattr(node, "name", None) == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return "".join(lines[node.lineno - 1:node.end_lineno])
    return None


# ------------------------------------------------------------------ the site
# The orthomosaic: Aragona, Sicily, a pixel of five centimetres.
LON0, LAT0 = 13.597839205127535, 37.377095687404655
PIX_DEG = (5.645130000000217e-07, 4.5051299999999503e-07)
PIX_M = (0.049999965267167275, 0.05000004866281121)
M_PER_DEG = (PIX_M[0] / PIX_DEG[0], PIX_M[1] / PIX_DEG[1])


# ------------------------------------------------------------------ the fakes
DEGREES, METRES, FEET = "degrees", "metres", "feet"
BOUND_WKT = ('BOUNDCRS[SOURCECRS[GEOGCRS["WGS 84",DATUM["World Geodetic '
             'System 1984",ELLIPSOID["WGS 84",6378137,298.257223563]],'
             'CS[ellipsoidal,2],ID["EPSG",4326]]],TARGETCRS[GEOGCRS["WGS 84"'
             ']],ABRIDGEDTRANSFORMATION["Transformation from WGS 84 to WGS84"'
             ',METHOD["Position Vector transformation (geog2D domain)"]]]')
SHIFTED_WKT = BOUND_WKT.replace("WGS 84 to WGS84", "a datum shifted by 100 m")
# What QGIS reads back from a GeoPackage table made with no system (srs_id 0):
# GDAL's sphere in degrees with an unknown datum. The tables of the campaign
# the defect was found on are in it, and so are those of every photograph.
UNDEFINED_WKT = ('GEOGCS["Undefined geographic SRS",DATUM["unknown",SPHEROID['
                 '"unknown",6378137,298.257223563]],PRIMEM["Greenwich",0],'
                 'UNIT["degree",0.0174532925199433]]')
# what each system is: authid, units, isGeographic() as QGIS 3.36 answers it,
# and the plane it is laid on (deg: lon/lat, shifted: lon/lat moved, utm)
KINDS = {
    "EPSG:4326": ("EPSG:4326", DEGREES, True, "deg", "WGS 84"),
    "EPSG:32633": ("EPSG:32633", METRES, False, "utm", "WGS 84 / UTM zone 33N"),
    "EPSG:2227": ("EPSG:2227", FEET, False, "feet", "California zone 3 (ftUS)"),
    BOUND_WKT: ("", DEGREES, False, "deg", "WGS 84"),
    SHIFTED_WKT: ("", DEGREES, False, "shifted", "WGS 84"),
    UNDEFINED_WKT: ("", DEGREES, False, "deg", "Undefined geographic SRS"),
}


class Pt(object):
    def __init__(self, x, y): self._x, self._y = float(x), float(y)
    def x(self): return self._x
    def y(self): return self._y


class Rect(object):
    def __init__(self, a, b, c, d):
        self.v = [min(a, c), min(b, d), max(a, c), max(b, d)]
    def xMinimum(self): return self.v[0]
    def yMinimum(self): return self.v[1]
    def xMaximum(self): return self.v[2]
    def yMaximum(self): return self.v[3]
    def width(self): return self.v[2] - self.v[0]
    def height(self): return self.v[3] - self.v[1]
    def center(self): return Pt((self.v[0] + self.v[2]) / 2, (self.v[1] + self.v[3]) / 2)


class Crs(object):
    """QgsCoordinateReferenceSystem as QGIS 3.36 answers about these systems."""
    WKT_PREFERRED = "wkt2"

    def __init__(self, text=""):
        self.text = text if text in KINDS else ""
    @classmethod
    def fromWkt(cls, wkt):
        return cls(wkt)
    def createFromWkt(self, wkt):
        self.text = wkt if wkt in KINDS else ""
        return bool(self.text)
    def isValid(self): return bool(self.text)
    def authid(self): return KINDS[self.text][0] if self.text else ""
    def mapUnits(self): return KINDS[self.text][1] if self.text else "unknown"
    def isGeographic(self): return KINDS[self.text][2] if self.text else False
    def plane(self): return KINDS[self.text][3] if self.text else None
    def description(self): return KINDS[self.text][4] if self.text else ""
    def toWkt(self, variant=None):
        return self.text if "[" in self.text else 'WKT_OF[%s]' % self.text
    def bounds(self): return Rect(-180, -90, 180, 90)
    def __eq__(self, o): return isinstance(o, Crs) and o.text == self.text
    def __ne__(self, o): return not self.__eq__(o)
    __hash__ = None


def to_lonlat(plane, x, y):
    if plane == "deg":
        return x, y
    if plane == "shifted":
        return x + 0.001, y           # a hundred metres or so east
    if plane == "utm":
        return (15.0 + (x - 500000.0) / M_PER_DEG[0], y / M_PER_DEG[1])
    if plane == "feet":
        return to_lonlat("utm", x * 0.3048006, y * 0.3048006)
    raise ValueError(plane)


def from_lonlat(plane, lon, lat):
    if plane == "deg":
        return lon, lat
    if plane == "shifted":
        return lon - 0.001, lat
    if plane == "utm":
        return (500000.0 + (lon - 15.0) * M_PER_DEG[0], lat * M_PER_DEG[1])
    if plane == "feet":
        x, y = from_lonlat("utm", lon, lat)
        return x / 0.3048006, y / 0.3048006
    raise ValueError(plane)


class Transform(object):
    """QgsCoordinateTransform between the planes above. An invalid system on
    either side leaves the coordinates alone, as QGIS does."""
    def __init__(self, a, b, ctx=None):
        self.a, self.b = a.plane(), b.plane()
    def xy(self, x, y):
        if self.a is None or self.b is None or self.a == self.b:
            return x, y
        return from_lonlat(self.b, *to_lonlat(self.a, x, y))
    def transform(self, p):
        return Pt(*self.xy(p.x(), p.y()))


class QT(object):
    """QTransform(m11, m12, m21, m22, dx, dy)."""
    def __init__(self, m11, m12, m21, m22, dx, dy):
        self.m = (m11, m12, m21, m22, dx, dy)


class G(object):
    """QgsGeometry, done by shapely."""
    def __init__(self, other=None):
        self.s = other.s if isinstance(other, G) else other
    @staticmethod
    def fromPointXY(p): return G(SPoint(p.x(), p.y()))
    @staticmethod
    def fromRect(r): return G(box(r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()))
    def transform(self, t):
        if isinstance(t, QT):
            m11, m12, m21, m22, dx, dy = t.m
            self.s = affinity.affine_transform(self.s, [m11, m21, m12, m22, dx, dy])
        else:
            self.s = reproject(lambda x, y, z=None: t.xy(x, y), self.s)
        return 0
    def buffer(self, d, segments): return G(self.s.buffer(d, segments))
    def asPoint(self): return Pt(self.s.x, self.s.y)
    def isEmpty(self): return self.s is None or self.s.is_empty
    def area(self): return self.s.area
    def boundingBox(self): return Rect(*self.s.bounds)


class Measure(object):
    """QgsDistanceArea on the ellipsoid: through the UTM plane, which near the
    site is as good as the ellipsoid for half a metre."""
    def setSourceCrs(self, crs, ctx): self.crs = crs
    def setEllipsoid(self, name): pass
    def measureArea(self, g):
        if self.crs.plane() is None:
            return g.area()
        t = Transform(self.crs, Crs("EPSG:32633"))
        return reproject(lambda x, y, z=None: t.xy(x, y), g.s).area


class Match(object):
    def __init__(self, code): self.code = code
    def GetAuthorityName(self, key): return "EPSG"
    def GetAuthorityCode(self, key): return self.code


class SpatialReference(object):
    """osr, as PROJ identifies these: either BOUNDCRS is EPSG:4326 at 100."""
    def ImportFromWkt(self, wkt): self.wkt = wkt; return 0
    def FindMatches(self):
        return [(Match("4326"), 100)] if self.wkt.startswith("BOUNDCRS") else []


class Project(object):
    @staticmethod
    def instance(): return Project()
    def transformContext(self): return None


LOG = []
osr = type("osr", (), {"SpatialReference": SpatialReference})
ns = {"QgsCoordinateReferenceSystem": Crs, "QgsCoordinateTransform": Transform,
      "QgsDistanceArea": Measure, "QgsGeometry": G, "QgsRectangle": Rect,
      "QgsPointXY": Pt, "QgsProject": Project, "QTransform": QT, "osr": osr,
      "Qgis": type("Qgis", (), {}), "UNIT_DEGREES": DEGREES,
      "UNIT_METRES": METRES, "GEOM_POLYGON": "polygon", "math": math,
      "log": lambda text, **k: LOG.append(text),
      "project_ellipsoid": lambda: "WGS84"}
exec(take("MIN_AREA_PX"), ns)
HELPERS = ("crs_units", "in_degrees", "in_metres", "crs_wkt", "crs_from_text",
           "crs_to_text", "_NAMED_CRS", "named_crs", "same_ground", "crs_label",
           "PLACEHOLDER_SRS", "placeholder_crs", "ellipsoid_for")
missing = [h for h in HELPERS if take(h) is None]
for h in HELPERS:
    if take(h) is not None:
        exec(take(h), ns)
exec(take("Geometry"), ns)
Geometry = ns["Geometry"]


class Campaign(object):
    def __init__(self, crs, origin=(LON0, LAT0), pixel_crs=PIX_DEG, pixel_m=PIX_M):
        self.data = {"grid": {"crs": crs, "origin": list(origin),
                              "pixel_crs": list(pixel_crs),
                              "pixel_m": list(pixel_m)}}


BOUND = Crs(BOUND_WKT)
CLICK = Pt(LON0 + 0.0002, LAT0 - 0.0001)
WANT_AREA = 0.5 ** 2 * 24 * math.sin(2 * math.pi / 48)   # 48 sides, 12 a quarter


def stroke(geo, metres=0.5):
    """What the round brush does with a single click."""
    return geo.buffer(G.fromPointXY(CLICK), metres, 12)


def size_in_metres(g):
    b = g.boundingBox()
    return b.width() * M_PER_DEG[0], b.height() * M_PER_DEG[1]


# ---------------------------------------------------------------- the checks
print("the bench is what QGIS 3.36 says about the orthomosaic")
check("the bound WGS 84 has no authid", BOUND.authid() == "")
check("isGeographic() says False for it", BOUND.isGeographic() is False)
check("and its units are degrees", BOUND.mapUnits() == DEGREES)

print()
print("the decision is taken on the units")
check("this build has the helpers that decide by units", not missing, missing)
if not missing:
    check("in_degrees(): the bound WGS 84 counts in degrees",
          ns["in_degrees"](BOUND) is True)
    check("in_metres(): and not in metres", ns["in_metres"](BOUND) is False)
    check("UTM 33N counts in metres", ns["in_metres"](Crs("EPSG:32633")))
    check("a system in feet is neither", not ns["in_metres"](Crs("EPSG:2227"))
          and not ns["in_degrees"](Crs("EPSG:2227")))
    check("no system is neither", not ns["in_metres"](Crs(""))
          and not ns["in_degrees"](Crs("")))
    check("named_crs(): the bound WGS 84 is EPSG:4326 under its own name",
          ns["named_crs"](BOUND, (LON0, LAT0)).authid() == "EPSG:4326")
    check("but a WGS 84 bound by a real shift is NOT called EPSG:4326",
          ns["named_crs"](Crs(SHIFTED_WKT), (LON0, LAT0)).authid() == "")
    check("crs_label() writes EPSG:4326, not ? or nothing",
          ns["crs_label"](BOUND) == "EPSG:4326", ns["crs_label"](BOUND))
    check("and a nameless system by its description",
          "WGS 84" in ns["crs_label"](Crs(SHIFTED_WKT)))

print()
print("the manifest keeps a system it can read back")
if not missing:
    text = ns["crs_to_text"](ns["named_crs"](BOUND, (LON0, LAT0)))
    check("a new campaign on the orthomosaic writes EPSG:4326", text == "EPSG:4326",
          text)
    text = ns["crs_to_text"](Crs(SHIFTED_WKT))
    check("a system with no code is written as its WKT, not as \"\"",
          text == SHIFTED_WKT, text[:40])
    back = ns["crs_from_text"](text)
    check("and the WKT reads back as the same system",
          back.isValid() and back == Crs(SHIFTED_WKT))
    check("an EPSG code reads back", ns["crs_from_text"]("EPSG:32633").authid()
          == "EPSG:32633")
    check("\"\" still reads as no system, for a photograph",
          not ns["crs_from_text"]("").isValid())
    check("so does a manifest with no crs at all",
          not ns["crs_from_text"](None).isValid())
else:
    check("the manifest helpers exist", False, missing)

print()
print("a campaign made by the build with the defect: crs \"\", layers bound")
del LOG[:]
geo = Geometry(Campaign(""), BOUND)
check("draws in EPSG:4326", geo.crs.authid() == "EPSG:4326", geo.crs.authid())
check("measures in UTM 33N", geo.metric is not None
      and geo.metric.authid() == "EPSG:32633",
      geo.metric.authid() if geo.metric is not None else None)
g = stroke(geo)
w, h = size_in_metres(g)
check("the round brush of 0.5 m is one metre across",
      abs(w - 1.0) < 0.01 and abs(h - 1.0) < 0.01, (round(w, 4), round(h, 4)))
check("in degrees, which is the campaign unit, it is a millionth of a degree "
      "and some, not a whole one", g.boundingBox().width() < 1e-4,
      g.boundingBox().width())
area = geo.area(g)
check("one click covers %.3f m2, a circle of half a metre" % WANT_AREA,
      abs(area - WANT_AREA) < 0.01 * WANT_AREA, area)
sq = geo.square(CLICK, 10.0)
w, h = size_in_metres(sq)
check("a frame of 10 m is 10 m a side", abs(w - 10) < 0.05 and abs(h - 10) < 0.05,
      (w, h))
check("and the log names both systems",
      not any("?" in x for x in LOG), LOG)

print()
print("the campaign the defect was found on: crs \"\", tables with no system")
del LOG[:]
geo = Geometry(Campaign(""), Crs(UNDEFINED_WKT))
check("the GeoPackage's stand-in for no system does not win",
      not geo.crs.isValid(), geo.crs.text[:30])
g = stroke(geo)
w, h = size_in_metres(g)
check("the round brush of 0.5 m is still one metre across, by the pixel ratio",
      abs(w - 1.0) < 0.01 and abs(h - 1.0) < 0.01, (round(w, 4), round(h, 4)))
check("and it is said that the tables carry no system",
      any("no coordinate system of their own" in x for x in LOG), LOG)
geo = Geometry(Campaign("EPSG:4326"), Crs(UNDEFINED_WKT))
check("once the manifest names EPSG:4326, that is what it draws in",
      geo.crs.authid() == "EPSG:4326", geo.crs.text[:30])
check("and it measures in UTM 33N", geo.metric is not None
      and geo.metric.authid() == "EPSG:32633")
check("and one click covers %.3f m2" % WANT_AREA,
      abs(geo.area(stroke(geo)) - WANT_AREA) < 0.01 * WANT_AREA,
      geo.area(stroke(geo)))

print()
print("a campaign made by this build: crs EPSG:4326, layers EPSG:4326")
geo = Geometry(Campaign("EPSG:4326"), Crs("EPSG:4326"))
check("measures in UTM 33N", geo.metric is not None
      and geo.metric.authid() == "EPSG:32633")
check("one click is still %.3f m2" % WANT_AREA,
      abs(geo.area(stroke(geo)) - WANT_AREA) < 0.01 * WANT_AREA,
      geo.area(stroke(geo)))

print()
print("a campaign whose manifest holds a WKT")
geo = Geometry(Campaign(SHIFTED_WKT), None)
check("the WKT is read as a system", geo.crs.isValid(), geo.crs.text[:30])
check("in degrees, so measured in UTM", geo.metric is not None
      and geo.metric.authid() == "EPSG:32633")
check("and one click is %.3f m2" % WANT_AREA,
      abs(geo.area(stroke(geo)) - WANT_AREA) < 0.02 * WANT_AREA,
      geo.area(stroke(geo)))

print()
print("a campaign in feet")
FEET_ORIGIN = from_lonlat("feet", LON0, LAT0)
geo = Geometry(Campaign("EPSG:2227", origin=FEET_ORIGIN,
                        pixel_crs=(0.05 / 0.3048006,) * 2, pixel_m=(0.05, 0.05)),
               None)
check("feet are not metres: the site is placed in UTM 33N",
      geo.metric is not None and geo.metric.authid() == "EPSG:32633",
      geo.metric.authid() if geo.metric is not None else None)

print()
print("the safety net: no metric system can be found")
del LOG[:]
far = Campaign("EPSG:4326", origin=(500.0, 4000.0))      # not on the Earth
geo = Geometry(far, None)
check("no metric system is made up", geo.metric is None,
      geo.metric.authid() if geo.metric is not None else None)
CLICK_FAR = Pt(500.0002, 3999.9999)
g = geo.buffer(G.fromPointXY(CLICK_FAR), 0.5, 12)
b = g.boundingBox()
check("the brush is turned into campaign units with the pixel ratio: x",
      abs(b.width() - 1.0 * PIX_DEG[0] / PIX_M[0]) < 1e-3 * b.width(), b.width())
check("and y, separately", abs(b.height() - 1.0 * PIX_DEG[1] / PIX_M[1])
      < 1e-3 * b.height(), b.height())
check("which is about a metre across on the ground",
      abs(b.width() * M_PER_DEG[0] - 1.0) < 0.01, b.width() * M_PER_DEG[0])
check("never half a campaign unit, which in degrees is fifty kilometres",
      b.width() < 1e-3, b.width())
sq = geo.square(CLICK_FAR, 10.0).boundingBox()
check("square(): 10 m in campaign units by the same ratio",
      abs(sq.width() * M_PER_DEG[0] - 10) < 0.01
      and abs(sq.height() * M_PER_DEG[1] - 10) < 0.01,
      (sq.width() * M_PER_DEG[0], sq.height() * M_PER_DEG[1]))
said = [x for x in LOG if "pixel size" in x]
check("and it is said once in the log", len(said) == 1, LOG)
geo.buffer(G.fromPointXY(CLICK_FAR), 0.5, 12)
geo.square(CLICK_FAR, 3.0)
check("only once, however many strokes follow",
      len([x for x in LOG if "pixel size" in x]) == 1, LOG)

print()
print("a picture with no coordinate system, as before")
del LOG[:]
pic = Campaign("", origin=(0.0, 0.0), pixel_crs=(1.0, 1.0), pixel_m=(1.0, 1.0))
geo = Geometry(pic, None)
g = geo.buffer(G.fromPointXY(Pt(100.0, -50.0)), 5.0, 12).boundingBox()
check("a radius of 5 is 5 pixels, as it always was",
      abs(g.width() - 10.0) < 1e-9, g.width())
check("and nothing is said about a missing metric system: there is no system",
      not [x for x in LOG if "pixel size" in x], LOG)
geo = Geometry(pic, Crs(UNDEFINED_WKT))
g = geo.buffer(G.fromPointXY(Pt(100.0, -50.0)), 5.0, 12).boundingBox()
check("its tables, in the GeoPackage's stand-in, do not turn pixels into degrees",
      abs(g.width() - 10.0) < 1e-9 and geo.metric is None, g.width())

print()
if fails:
    print("%d FAILED" % len(fails))
    sys.exit(1)
print("all passed")
