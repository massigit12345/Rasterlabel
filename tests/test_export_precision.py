"""KML and CSV give back the polygons the campaign holds, not fifteen digits
of them.

Found in a real campaign: of twenty-three polygons, two came out of the KML
and the CSV invalid, "Ring Self-intersection" and "Self-intersection", while
the GeoPackage they came from and the shapefile, the GeoJSON and the
GeoPackage written beside them were valid. Each of the two held a pair of
vertices left by the cut against its neighbours a hundredth of a nanometre
apart or less: two different doubles, and a valid ring. The KML and CSV
writers of GDAL write a coordinate as text with fifteen significant digits,
which on a longitude of 13 degrees is a step of 1e-13, and both vertices of
the pair became the same fifteen digits: the ring went back on itself. The
same rounding made eight pairs of neighbours overlap, by slivers ten
nanometres wide.

The polygons here are built the same way: two squares that share an edge
exactly, near where the campaign was, and in the lower one a notch whose two
corners on that edge are three doubles apart. Valid as they are; written as
GDAL writes them by default, the notch closes into a spike. The suite shows
that first, with GDAL alone, and then exports them in every format the dialog
offers and reads them back: every polygon valid, the two squares still only
touching, and in the CSV and the KML the very same doubles that are in the
package.

Twice: once the way this GDAL goes, and once as GDAL 3.8 goes inside QGIS
3.36, which reads how many digits to write once per process, before the
plugin can ask, and writes fifteen whatever it is asked: there the file is
written and its coordinates are then written again, exactly. And last the
net under both: a polygon valid in the package that comes out invalid is
said, and one that was invalid already is not.

The code under test is lifted out of rasterlabel.py as written."""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

from decimal import Decimal
import ast, math, os, re, shutil, sys, tempfile

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()
gdal.PushErrorHandler("CPLQuietErrorHandler")

SRC = os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)
WANTED = {"FORMATS", "TEXT_DRIVERS", "FULL_PRECISION", "WRITTEN_WHOLE", "exact_text",
          "NUMBER", "GEOMETRY_TEXT", "COORDINATES", "full_precision",
          "coordinates_exact", "runs_of", "renumbered", "rewrite_coordinates",
          "invalid_polygons", "write_vectors", "PLACEHOLDER_SRS",
          "tables_have_system", "feature_counts", "remove_output",
          "defuse_csv", "csv_text", "_FORMULA_START", "_PLAIN_NUMBER",
          "long_path"}
pieces, found = [], set()
for node in tree.body:
    name = getattr(node, "name", None)
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        name = node.targets[0].id
    if name in WANTED:
        found.add(name)
        pieces.append("".join(lines[node.lineno - 1:node.end_lineno]))
assert found == WANTED, sorted(WANTED - found)

LOGGED = []
g = {"os": os, "re": re, "shutil": shutil, "tempfile": tempfile,
     "Decimal": Decimal, "csv": __import__("csv"), "io": __import__("io"),
     "sys": sys,
     "gdal": gdal, "ogr": ogr,
     "log": lambda m, loud=False: LOGGED.append(m),
     "release_file": lambda p: 0}
exec("\n".join(pieces), g)
FORMATS = g["FORMATS"]
write_vectors = g["write_vectors"]

fails = []


def check(name, condition, detail=""):
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))
    if not condition:
        fails.append(name)


FOLDER = tempfile.mkdtemp(prefix="rl_export_precision_")

# ------------------------------------------------------------------ fixture
# Near where the campaign was: longitude 13.6, where a double is 1.8e-15
# apart from the next and fifteen digits are 1e-13 apart.
X0, X1 = 13.6003200000000, 13.6003300000000
Y0, Y1, Y2 = 37.3758000000000, 37.3758100000000, 37.3758200000000
XA = 13.6003277302064            # a corner of the notch, on the shared edge
XB = math.nextafter(XA, 1e3)     # the middle of the notch, one double on
XA2 = math.nextafter(XB, 1e3)    # its other corner, two doubles on
YB = 37.3758060000000            # how deep the notch goes

LOWER = [(X0, Y0), (X1, Y0), (X1, Y1), (XA2, Y1), (XB, YB), (XA, Y1),
         (X0, Y1), (X0, Y0)]
UPPER = [(X0, Y1), (XA, Y1), (XA2, Y1), (X1, Y1), (X1, Y2), (X0, Y2),
         (X0, Y1)]
# A bow tie, invalid in the package itself: nothing an export should mend
# or complain about.
BOW = [(X0, Y2), (X1, Y2 + 1e-5), (X1, Y2), (X0, Y2 + 1e-5), (X0, Y2)]


def multipolygon(ring_points):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in ring_points:
        ring.AddPoint_2D(x, y)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    multi = ogr.Geometry(ogr.wkbMultiPolygon)
    multi.AddGeometry(poly)
    return multi


def package(path, shapes):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    layer = ds.CreateLayer("polygons", srs, ogr.wkbMultiPolygon,
                           ["GEOMETRY_NAME=geom"])
    for field, kind in (("class_name", ogr.OFTString),
                        ("tile_id", ogr.OFTString)):
        layer.CreateField(ogr.FieldDefn(field, kind))
    points = ds.CreateLayer("points", srs, ogr.wkbPoint,
                            ["GEOMETRY_NAME=geom"])
    points.CreateField(ogr.FieldDefn("tile_id", ogr.OFTString))
    for name, ring in shapes:
        f = ogr.Feature(layer.GetLayerDefn())
        f.SetField("class_name", name)
        f.SetField("tile_id", "t_001")
        f.SetGeometry(multipolygon(ring))
        layer.CreateFeature(f)
    # a point, so the KML holds coordinates of more than one kind
    f = ogr.Feature(points.GetLayerDefn())
    f.SetField("tile_id", "t_001")
    p = ogr.Geometry(ogr.wkbPoint)
    p.AddPoint_2D(XB, (Y1 + Y2) / 2)
    f.SetGeometry(p)
    points.CreateFeature(f)
    layer = points = ds = None


def polygons_in(path):
    """The polygons of a file, by class, in the order they are in."""
    out = []
    ds = ogr.Open(path)
    for i in range(ds.GetLayerCount()):
        layer = ds.GetLayerByIndex(i)
        if ds.GetLayerCount() > 1 and "polygons" not in layer.GetName():
            continue
        for f in layer:
            out.append((f.GetField("class_name"),
                        f.GetGeometryRef().Clone()))
    ds = None
    return out


def vertices(geom):
    pts = []
    def walk(h):
        if h.GetGeometryCount():
            for i in range(h.GetGeometryCount()):
                walk(h.GetGeometryRef(i))
        else:
            pts.extend(h.GetPoint_2D(k) for k in range(h.GetPointCount()))
    walk(geom)
    return pts


PACKAGE = os.path.join(FOLDER, "annotation.gpkg")
package(PACKAGE, [("crust", LOWER), ("water", UPPER)])
KEPT = {name: vertices(geom) for name, geom in polygons_in(PACKAGE)}

print("the two squares, in the package")
inside = polygons_in(PACKAGE)
check("both are valid there", all(geom.IsValid() for _, geom in inside),
      [(n, geom.IsValid()) for n, geom in inside])
check("and only touch: they share an edge and no area",
      inside[0][1].Intersection(inside[1][1]).GetArea() == 0)
check("the notch's two corners are two different doubles",
      XA != XA2 and abs(XA2 - XA) < 1e-14, XA2 - XA)
check("and fifteen digits make them one",
      "%.15g" % XA == "%.15g" % XA2, ("%.15g" % XA, "%.15g" % XA2))

# ------------------------------------------------- what GDAL does by itself
# First, before anything here asks GDAL for more digits: GDAL 3.8 decides
# its digits once, the first time it writes WKT, and this is the first time.
print()
print("written the way GDAL writes them when nothing is asked")
for driver, extension, extra in (
        ("CSV", ".csv", ["GEOMETRY=AS_WKT", "CREATE_CSVT=YES"]),
        ("KML", ".kml", [])):
    target = os.path.join(FOLDER, "plain" + extension)
    out = gdal.VectorTranslate(target, PACKAGE, options=gdal.VectorTranslateOptions(
        format=driver, layers=["polygons"], layerCreationOptions=extra))
    out = None
    back = polygons_in(target)
    check("%s: the notched square comes out invalid (the defect)" % driver,
          not dict(back)["crust"].IsValid())
    check("%s: because the notch's two corners became one vertex" % driver,
          len(set(vertices(dict(back)["crust"])))
          == len(set(KEPT["crust"])) - 1)

# ------------------------------------------------------------ every format


def export_all(label):
    for _, driver, extension, one_file, forced in FORMATS:
        out = os.path.join(FOLDER, label, driver.replace(" ", "_"))
        recipe = {"tables": ["polygons", "points"], "driver": driver,
                  "extension": extension, "one_file": one_file,
                  "crs": forced, "tile_id": None, "folder": out}
        written, failed, notes = write_vectors(PACKAGE, recipe, "camp")
        check("%s: written, nothing failed, nothing to say" % driver,
              written and not failed and not notes, (written, failed, notes))
        path = [p for p in written if one_file or "polygons" in p][0]
        back = polygons_in(path)
        check("%s: both squares valid" % driver,
              len(back) == 2 and all(geom.IsValid() for _, geom in back),
              [(n, geom.IsValid()) for n, geom in back])
        if len(back) == 2:
            area = back[0][1].Intersection(back[1][1]).GetArea()
            check("%s: and still only touching" % driver, area == 0, area)
        if driver in ("CSV", "KML", "GPKG", "GeoJSON"):
            same = all(vertices(geom) == KEPT[name] for name, geom in back)
            check("%s: the very same doubles as in the package" % driver,
                  same)
        if driver in ("CSV", "KML"):
            text = open(path, encoding="utf-8").read()
            check("%s: the corner written in full, the other one beside it"
                  % driver, repr(XA) in text and repr(XA2) in text)


print()
print("exported, the way this GDAL (%s) goes" % gdal.__version__)
with g["full_precision"]():
    asked = g["coordinates_exact"]()
print("  (here GDAL %s the digits it is asked for)"
      % ("writes" if asked else "does not write"))
export_all("as_it_goes")

print()
print("exported again, into the same folders, over the first export")
# Over an old KML GDAL used to hand the file to LIBKML, which rewrote it in
# its own layout, with an altitude on every vertex and fifteen digits.
export_all("as_it_goes")

print()
print("exported as on GDAL 3.8 inside QGIS 3.36: fifteen digits, asked or not")
# Asked for fifteen digits and told they are not enough: what a GDAL that
# has decided its digits already does, whatever this GDAL would do.
g["FULL_PRECISION"] = {"OGR_WKT_PRECISION": "15", "OGR_WKT_ROUND": "YES"}
g["coordinates_exact"] = lambda: False
del LOGGED[:]
export_all("fifteen_digits")
check("the log says the coordinates were given back in full",
      any("given them back in full" in m for m in LOGGED), LOGGED)
check("and no file was left with fifteen digits",
      not any("left as GDAL wrote them" in m for m in LOGGED), LOGGED)
del LOGGED[:]
export_all("fifteen_digits")
check("and again over it: still given back in full, nothing left as it was",
      not any("left as GDAL wrote them" in m for m in LOGGED), LOGGED)

print()
print("the text is only renumbered where it is the text expected")
check("the same numbers, written in full",
      g["renumbered"]("1.5 2.25,3", [1.5, 2.25, 3.0]) == "1.5 2.25,3.0")
check("one number too many or too few is refused",
      g["renumbered"]("1 2 3", [1.0, 2.0]) is None)
check("and so is a number that is not the value it stands for",
      g["renumbered"]("1 2", [1.0, 2.5]) is None)
check("a coordinate near zero is written in plain decimals, exactly",
      g["exact_text"](1e-05) == "0.00001"
      and float(g["exact_text"](-3.2e-07)) == -3.2e-07)
ROWS = ('WKT,class_name,note\r\n'
        '"POLYGON ((1 2,3 4,1 2))",a,"he wrote ""POLYGON ((5 6,7 8))"""\r\n'
        '"POINT (9 10)",b,"two\r\n""POINT (11 12)"" lines"\r\n'
        ',c,no geometry\r\n')
check("in a CSV only the geometry of each row is taken for one, not a "
      "polygon quoted in a note",
      [m.group(1) for m in g["GEOMETRY_TEXT"].finditer(ROWS)]
      == ["POLYGON ((1 2,3 4,1 2))", "POINT (9 10)"],
      [m.group(1) for m in g["GEOMETRY_TEXT"].finditer(ROWS)])

# ------------------------------------------------------------- the net
print()
print("what is read back is said")
PACKAGE = os.path.join(FOLDER, "with_a_bow_tie.gpkg")
package(PACKAGE, [("crust", LOWER), ("water", UPPER), ("bow", BOW)])
recipe = {"tables": ["polygons"], "driver": "CSV", "extension": ".csv",
          "one_file": False, "crs": None, "tile_id": None,
          "folder": os.path.join(FOLDER, "net")}
written, failed, notes = write_vectors(PACKAGE, recipe, "camp")
check("a polygon invalid in the package already is no news", not notes, notes)
# and if the coordinates could not be written again, the notch would come
# out closed: that is said, by file and by table
g["rewrite_coordinates"] = lambda *a: False
written, failed, notes = write_vectors(PACKAGE, recipe, "camp")
check("a polygon valid in the package and invalid in the file is said",
      notes == ["camp_polygons.csv: 1 polygon of polygons came out invalid"],
      notes)

print()
print("FAILED: %d" % len(fails) if fails else "all of them pass")
for f in fails:
    print("   " + f)
shutil.rmtree(FOLDER, ignore_errors=True)
sys.exit(1 if fails else 0)
