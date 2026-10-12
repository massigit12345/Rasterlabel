"""The orthomosaic in WGS 84 bound to itself, through real PROJ.

test_units_not_labels.py runs the decision against a bench that is told what
PROJ would say. This one asks PROJ. The system is the one the GeoTIFF keys of
the orthomosaic declare (WGS 84, a TOWGS84 of seven zeros), read the way GDAL
reads it, which is as a BOUNDCRS; QGIS 3.36 then answers authid() "" and
isGeographic() False for it, and the bench says the same. Everything else is
real: PROJ identifies the system, PROJ moves the points into the UTM zone the
geometry picks, and the round brush stroke is measured on a plane centred on
it, so the half metre checked is half a metre on the ground.

What has to hold: the campaign made with that raster by the build with the
defect (manifest crs "", layers in the bound system) draws in EPSG:4326 and
measures in EPSG:32633, and one click of the round brush at 0.5 m covers
0.78 m2 and is a metre across. The defect made it a degree across.

Needs the GDAL bindings and shapely; not QGIS.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import math
import os as _os
import sys

from osgeo import osr

osr.UseExceptions()

try:
    from shapely import affinity
    from shapely.geometry import Point as SPoint, box
    from shapely.ops import transform as reproject
except ImportError:
    print("shapely is missing")
    sys.exit(1)

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")
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
    for node in tree.body:
        if getattr(node, "name", None) == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return "".join(lines[node.lineno - 1:node.end_lineno])
    return None


# What gdalsrsinfo -o wkt1 prints for the orthomosaic.
DECLARED = ('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,'
            '298.257223563,AUTHORITY["EPSG","7030"]],TOWGS84[0,0,0,0,0,0,0],'
            'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG",'
            '"8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG",'
            '"9122"]],AXIS["Latitude",NORTH],AXIS["Longitude",EAST],'
            'AUTHORITY["EPSG","4326"]]')
LON0, LAT0 = 13.597839205127535, 37.377095687404655
PIX_DEG = (5.645130000000217e-07, 4.5051299999999503e-07)
PIX_M = (0.049999965267167275, 0.05000004866281121)
DEGREES, METRES = "degrees", "metres"


def srs_of(text):
    s = osr.SpatialReference()
    if text.upper().startswith("EPSG:"):
        s.ImportFromEPSG(int(text[5:]))
    else:
        s.ImportFromWkt(text)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


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
    """QgsCoordinateReferenceSystem over a real osr system. authid() and
    isGeographic() answer as QGIS 3.36 does for a BOUNDCRS, nothing and False;
    the units are PROJ's own."""
    WKT_PREFERRED = "wkt2"

    def __init__(self, text=""):
        try:
            self.srs = srs_of(text) if text else None
        except Exception:
            self.srs = None
    @classmethod
    def fromWkt(cls, wkt): return cls(wkt)
    def isValid(self): return self.srs is not None
    def wkt2(self): return self.srs.ExportToWkt(["FORMAT=WKT2_2019"]) if self.srs else ""
    def bound(self): return self.wkt2().startswith("BOUNDCRS")
    def authid(self):
        if self.srs is None or self.bound():
            return ""
        name, code = self.srs.GetAuthorityName(None), self.srs.GetAuthorityCode(None)
        return "%s:%s" % (name, code) if name and code else ""
    def isGeographic(self):
        return bool(self.srs is not None and not self.bound() and self.srs.IsGeographic())
    def mapUnits(self):
        if self.srs is None:
            return "unknown"
        if self.srs.IsGeographic():
            return DEGREES
        return METRES if self.srs.GetLinearUnits() == 1.0 else "other"
    def description(self): return self.srs.GetName() if self.srs else ""
    def toWkt(self, variant=None): return self.wkt2()
    def bounds(self): return Rect(-180, -90, 180, 90)
    def __eq__(self, o):
        return isinstance(o, Crs) and (self.authid(), self.wkt2()) == (o.authid(), o.wkt2())
    def __ne__(self, o): return not self.__eq__(o)
    __hash__ = None


class Transform(object):
    """QgsCoordinateTransform, done by PROJ."""
    def __init__(self, a, b, ctx=None):
        self.ct = None
        if a.isValid() and b.isValid():
            self.ct = osr.CoordinateTransformation(a.srs, b.srs)
    def xy(self, x, y):
        if self.ct is None:
            return x, y
        p = self.ct.TransformPoint(x, y)
        return p[0], p[1]
    def transform(self, p): return Pt(*self.xy(p.x(), p.y()))


class QT(object):
    def __init__(self, m11, m12, m21, m22, dx, dy):
        self.m = (m11, m12, m21, m22, dx, dy)


class G(object):
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


def on_the_ground(crs, g, at):
    """g moved onto a plane centred on the point, where a metre is a metre in
    every direction: azimuthal equidistant, from PROJ."""
    here = Crs("")
    here.srs = osr.SpatialReference()
    here.srs.ImportFromProj4("+proj=aeqd +lat_0=%.12f +lon_0=%.12f +datum=WGS84 "
                             "+units=m +no_defs" % (at.y(), at.x()))
    here.srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    t = Transform(crs, here)
    return reproject(lambda x, y, z=None: t.xy(x, y), g.s)


class Measure(object):
    def setSourceCrs(self, crs, ctx): self.crs = crs
    def setEllipsoid(self, name): pass
    def measureArea(self, g):
        c = g.s.centroid
        return on_the_ground(self.crs, g, Pt(c.x, c.y)).area


class Project(object):
    @staticmethod
    def instance(): return Project()
    def transformContext(self): return None


LOG = []
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
for h in HELPERS:
    if take(h) is not None:
        exec(take(h), ns)
exec(take("Geometry"), ns)
Geometry = ns["Geometry"]


class Campaign(object):
    def __init__(self, crs):
        self.data = {"grid": {"crs": crs, "origin": [LON0, LAT0],
                              "pixel_crs": list(PIX_DEG), "pixel_m": list(PIX_M)}}


BOUND = Crs(DECLARED)
CLICK = Pt(LON0 + 0.002, LAT0 - 0.0014)
WANT_AREA = 0.5 ** 2 * 24 * math.sin(2 * math.pi / 48)

print("what PROJ makes of the system the orthomosaic declares")
check("GDAL reads it as a BOUNDCRS", BOUND.bound(), BOUND.wkt2()[:30])
check("its units are degrees", BOUND.mapUnits() == DEGREES)
matches = [(m.GetAuthorityName(None), m.GetAuthorityCode(None), c)
           for m, c in osr.SpatialReference(BOUND.wkt2()).FindMatches()]
check("PROJ identifies it as EPSG:4326, certain of it", ("EPSG", "4326", 100) in matches,
      matches[:3])
moved = Transform(BOUND, Crs("EPSG:4326")).transform(CLICK)
check("and moving a point from it to EPSG:4326 leaves the point where it was",
      abs(moved.x() - CLICK.x()) < 1e-12 and abs(moved.y() - CLICK.y()) < 1e-12,
      (moved.x() - CLICK.x(), moved.y() - CLICK.y()))

print()
print("the helpers, against PROJ")
if take("named_crs") is None:
    check("this build has named_crs()", False)
else:
    named = ns["named_crs"](BOUND, (LON0, LAT0))
    check("named_crs() names it EPSG:4326", named.authid() == "EPSG:4326",
          named.authid())
    text = ns["crs_to_text"](named)
    check("which is what a new campaign writes in its manifest", text == "EPSG:4326",
          text)
    shifted = Crs(BOUND.wkt2().replace('PARAMETER["X-axis translation",0,',
                                       'PARAMETER["X-axis translation",100,'))
    check("a WGS 84 bound by a real shift keeps no name it does not have",
          ns["named_crs"](shifted, (LON0, LAT0)).authid() == "",
          ns["named_crs"](shifted, (LON0, LAT0)).authid())
    kept = ns["crs_to_text"](shifted)
    check("and goes into the manifest as its WKT, which reads back",
          kept.startswith("BOUNDCRS") and ns["crs_from_text"](kept).isValid(),
          kept[:30])

print()
print("the campaign made by the build with the defect: crs \"\", layers bound")
geo = Geometry(Campaign(""), BOUND)
check("draws in EPSG:4326", geo.crs.authid() == "EPSG:4326", geo.crs.authid())
check("measures in EPSG:32633, the UTM zone of Sicily",
      geo.metric is not None and geo.metric.authid() == "EPSG:32633",
      geo.metric.authid() if geo.metric is not None else None)
stroke = geo.buffer(G.fromPointXY(CLICK), 0.5, 12)
flat = on_the_ground(geo.crs, stroke, CLICK)
x0, y0, x1, y1 = flat.bounds
check("one click of the round brush at 0.5 m is a metre across, on the ground",
      abs((x1 - x0) - 1.0) < 0.005 and abs((y1 - y0) - 1.0) < 0.005,
      (round(x1 - x0, 4), round(y1 - y0, 4)))
check("and covers %.3f m2" % WANT_AREA, abs(flat.area - WANT_AREA) < 0.005 * WANT_AREA,
      flat.area)
check("which the campaign measures as such", abs(geo.area(stroke) - WANT_AREA)
      < 0.005 * WANT_AREA, geo.area(stroke))
b = stroke.boundingBox()
check("in campaign units, a hundred thousandth of a degree and not a whole one",
      b.width() < 2e-5 and b.height() < 2e-5, (b.width(), b.height()))

print()
print("the campaign made by this build: crs EPSG:4326")
geo = Geometry(Campaign("EPSG:4326"), Crs("EPSG:4326"))
stroke = geo.buffer(G.fromPointXY(CLICK), 0.5, 12)
check("measures in EPSG:32633", geo.metric is not None
      and geo.metric.authid() == "EPSG:32633")
check("and one click covers %.3f m2" % WANT_AREA,
      abs(on_the_ground(geo.crs, stroke, CLICK).area - WANT_AREA) < 0.005 * WANT_AREA,
      on_the_ground(geo.crs, stroke, CLICK).area)

print()
if fails:
    print("%d FAILED" % len(fails))
    sys.exit(1)
print("all passed")
