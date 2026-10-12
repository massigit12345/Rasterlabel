"""Round trip with a real GDAL: build a small campaign package, write it out
in every format the dialog offers, then read each one back and check that the
rows, the fields and the geometry survived.

The code under test is lifted out of rasterlabel.py as written, so this fails
if the file changes, not if a copy of it does."""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

from decimal import Decimal
import ast, os, re, shutil, sys, tempfile

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

SRC = os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)
# write_vectors and what it calls: the digits it asks GDAL for, and what it
# does when they are not given (test_export_precision is about those).
WANTED = {"FORMATS", "count_rows", "write_vectors", "TEXT_DRIVERS",
          "FULL_PRECISION", "WRITTEN_WHOLE", "exact_text", "NUMBER", "GEOMETRY_TEXT",
          "COORDINATES", "full_precision", "coordinates_exact", "runs_of", "renumbered",
          "rewrite_coordinates", "invalid_polygons", "PLACEHOLDER_SRS",
          "tables_have_system", "feature_counts", "remove_output",
          "defuse_csv", "csv_text", "_FORMULA_START", "_PLAIN_NUMBER",
          "long_path"}
# What write_vectors calls since it was taught a campaign with no system and
# to count what it wrote. A build from before has none of them and does not
# call them: this suite then says what it gets wrong instead of stopping.
LATER = {"PLACEHOLDER_SRS", "tables_have_system", "feature_counts",
         "remove_output", "defuse_csv", "csv_text", "_FORMULA_START",
         "_PLAIN_NUMBER", "long_path"}
pieces, found = [], set()
for node in tree.body:
    name = getattr(node, "name", None)
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        name = node.targets[0].id
    if name in WANTED:
        found.add(name)
        pieces.append("".join(lines[node.lineno - 1:node.end_lineno]))
assert WANTED - found <= LATER, sorted(WANTED - found)

g = {"os": os, "re": re, "shutil": shutil, "tempfile": tempfile,
     "Decimal": Decimal, "csv": __import__("csv"), "io": __import__("io"),
     "sys": sys,
     "gdal": gdal, "ogr": ogr,
     "log": lambda m, loud=False: print("      [log]", m),
     "release_file": lambda p: 0}
exec("\n".join(pieces), g)
FORMATS = g["FORMATS"]
write_vectors = g["write_vectors"]
count_rows = g["count_rows"]

FOLDER = tempfile.mkdtemp(prefix="rl_export_")
PACKAGE = os.path.join(FOLDER, "annotation.gpkg")

TABLES = [("tiles", ogr.wkbPolygon,
           [("tile_id", ogr.OFTString), ("side_m", ogr.OFTReal),
            ("note", ogr.OFTString), ("created", ogr.OFTString),
            ("closed", ogr.OFTInteger)]),
          ("polygons", ogr.wkbMultiPolygon,
           [("class_name", ogr.OFTString), ("class_code", ogr.OFTInteger),
            ("tile_id", ogr.OFTString), ("pass_no", ogr.OFTInteger),
            ("operator", ogr.OFTString), ("created", ogr.OFTString)]),
          ("points", ogr.wkbPoint,
           [("class_name", ogr.OFTString), ("class_code", ogr.OFTInteger),
            ("tile_id", ogr.OFTString), ("operator", ogr.OFTString),
            ("conf", ogr.OFTString), ("created", ogr.OFTString)]),
          ("boxes", ogr.wkbPolygon,
           [("class_name", ogr.OFTString), ("class_code", ogr.OFTInteger),
            ("tile_id", ogr.OFTString), ("operator", ogr.OFTString),
            ("width_m", ogr.OFTReal), ("height_m", ogr.OFTReal),
            ("created", ogr.OFTString)])]

srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)


def square(x, y, side):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for dx, dy in ((0, 0), (side, 0), (side, side), (0, side), (0, 0)):
        ring.AddPoint_2D(x + dx, y + dy)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly


driver = ogr.GetDriverByName("GPKG")
ds = driver.CreateDataSource(PACKAGE)
COUNTS = {"tiles": 2, "polygons": 5, "points": 4, "boxes": 3}
for name, kind, fields in TABLES:
    layer = ds.CreateLayer(name, srs, kind, ["GEOMETRY_NAME=geom"])
    for field, ftype in fields:
        d = ogr.FieldDefn(field, ftype)
        if ftype == ogr.OFTString:
            d.SetWidth(80)
        layer.CreateField(d)
    for i in range(COUNTS[name]):
        f = ogr.Feature(layer.GetLayerDefn())
        x, y = 400000.0 + i * 10, 4100000.0 - i * 10
        if kind == ogr.wkbPoint:
            geom = ogr.Geometry(ogr.wkbPoint)
            geom.AddPoint_2D(x + 1, y - 1)
        elif kind == ogr.wkbMultiPolygon:
            geom = ogr.Geometry(ogr.wkbMultiPolygon)
            geom.AddGeometry(square(x, y - 5, 4))
        else:
            geom = square(x, y - 8, 8)
        f.SetGeometry(geom)
        # the first of each table belongs to frame t_001, the rest to t_002
        f.SetField("tile_id", "t_001" if i == 0 else "t_002")
        if "class_name" in [a for a, _ in fields]:
            f.SetField("class_name", "crust" if i % 2 else "water")
            f.SetField("class_code", 1 if i % 2 else 3)
        layer.CreateFeature(f)
        f = None
    layer = None
ds = None

fails = []


def check(name, condition, detail=""):
    print(("  ok   " if condition else "  FAIL ") + name +
          (("  " + str(detail)) if detail and not condition else ""))
    if not condition:
        fails.append(name)


print("the package that was built")
for name in COUNTS:
    check("%s has %d rows" % (name, COUNTS[name]),
          count_rows(PACKAGE, name) == COUNTS[name],
          count_rows(PACKAGE, name))
check("a table that is not there counts zero",
      count_rows(PACKAGE, "nothing") == 0)
check("a package that is not there counts zero",
      count_rows(os.path.join(FOLDER, "nowhere.gpkg"), "tiles") == 0)

ALL = list(COUNTS)


def rows_in(path, layer_name=None):
    ds = ogr.Open(path)
    if ds is None:
        return None
    layer = ds.GetLayerByName(layer_name) if layer_name else ds.GetLayer(0)
    return None if layer is None else int(layer.GetFeatureCount())


for label, driver_name, extension, one_file, forced in FORMATS:
    print()
    print(label)
    out = os.path.join(FOLDER, driver_name.replace(" ", "_"))
    recipe = {"tables": ALL, "driver": driver_name, "extension": extension,
              "one_file": one_file, "crs": forced, "tile_id": None,
              "folder": out}
    written, failed, notes = write_vectors(PACKAGE, recipe, "aragona_2025")
    check("nothing failed", not failed, failed)
    check("and nothing came back different", not notes, notes)
    check("files were written", bool(written), written)
    if one_file:
        check("one file only", len(written) == 1, written)
        for name in ALL:
            got = rows_in(written[0], name)
            check("%s came back with %d rows" % (name, COUNTS[name]),
                  got == COUNTS[name], got)
    else:
        check("one file per table", len(written) == len(ALL), written)
        for path in written:
            table = os.path.basename(path).split("_")[-1].split(".")[0]
            got = rows_in(path)
            check("%s came back with %d rows" % (table, COUNTS[table]),
                  got == COUNTS[table], got)

    # the projection, where the format pins one down
    sample = written[0] if written else None
    if sample and driver_name in ("GeoJSON", "KML"):
        ds = ogr.Open(sample)
        layer = ds.GetLayer(0)
        ref = layer.GetSpatialRef()
        code = ref.GetAuthorityCode(None) if ref is not None else None
        check("written in degrees", code in ("4326", None), code)
        f = layer.GetNextFeature()
        geom = f.GetGeometryRef()
        x, y = geom.Centroid().GetX(), geom.Centroid().GetY()
        check("and the coordinates really are degrees",
              -180 <= x <= 180 and -90 <= y <= 90, (x, y))
        ds = None

print()
print("a class that is a formula is not one in the CSV")
# Excel and LibreOffice run a cell that begins with = + - or @. GDAL writes
# what the package holds, so the file is made safe after it.
import csv as _csv
formula_pkg = os.path.join(FOLDER, "formula.gpkg")
fds = ogr.GetDriverByName("GPKG").CreateDataSource(formula_pkg)
flayer = fds.CreateLayer("polygons", srs, ogr.wkbMultiPolygon,
                         ["GEOMETRY_NAME=geom"])
for field, ftype in (("class_name", ogr.OFTString), ("class_code", ogr.OFTInteger),
                     ("depth", ogr.OFTReal), ("operator", ogr.OFTString),
                     ("tile_id", ogr.OFTString)):
    flayer.CreateField(ogr.FieldDefn(field, ftype))
for name, depth in (('=HYPERLINK("http://example.org","x")', -2.5),
                    ("-water", 3.0), ("@anna", 0.0), ("plain", -1.0)):
    f = ogr.Feature(flayer.GetLayerDefn())
    geom = ogr.Geometry(ogr.wkbMultiPolygon)
    geom.AddGeometry(square(400000.0, 4100000.0, 4))
    f.SetGeometry(geom)
    f.SetField("class_name", name)
    f.SetField("class_code", -1 if name == "plain" else 1)
    f.SetField("depth", depth)
    f.SetField("operator", "+ANNA" if name == "@anna" else "ANNA")
    f.SetField("tile_id", "t_001")
    flayer.CreateFeature(f)
    f = None
flayer = fds = None
csv_label = [fmt for fmt in FORMATS if fmt[1] == "CSV"][0]
out = os.path.join(FOLDER, "formula_csv")
written, failed, notes = write_vectors(
    formula_pkg, {"tables": ["polygons"], "driver": "CSV",
                  "extension": csv_label[2], "one_file": csv_label[3],
                  "crs": csv_label[4], "tile_id": None, "folder": out},
    "formulas")
check("the CSV is written", len(written) == 1 and not failed, (written, failed))
if written:
    path = written[0]
    if os.path.isdir(path):
        path = os.path.join(path, "polygons.csv")
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(_csv.DictReader(fh))
    check("every row is there", len(rows) == 4, len(rows))
    names = [r["class_name"] for r in rows]
    check("the formula has a quote in front and its text after it",
          names[0] == "'=HYPERLINK(\"http://example.org\",\"x\")", names[0])
    check("so has a class that begins with a minus", names[1] == "'-water",
          names[1])
    check("and an operator that begins with a plus",
          rows[2]["operator"] == "'+ANNA", rows[2]["operator"])
    check("an ordinary name is as it was", names[3] == "plain")
    check("a negative number is still a number",
          [r["class_code"] for r in rows][3] == "-1"
          and rows[0]["depth"] in ("-2.5", "-2.50"), rows[0]["depth"])
    wkt = list(rows[0].values())[0]
    check("and the geometry, the first column, is untouched",
          wkt.startswith(("MULTIPOLYGON", "POLYGON")), wkt[:30])

print()
print("the class of a polygon survives the trip")
shape_dir = os.path.join(FOLDER, "ESRI_Shapefile")
ds = ogr.Open(os.path.join(shape_dir, "aragona_2025_polygons.shp"))
layer = ds.GetLayer(0)
names = sorted(f.GetField("class_name") for f in layer)
check("the five polygons kept their classes",
      names == ["crust", "crust", "water", "water", "water"], names)
fields = [layer.GetLayerDefn().GetFieldDefn(i).GetName()
          for i in range(layer.GetLayerDefn().GetFieldCount())]
check("no field name was truncated by the shapefile",
      all(len(n) <= 10 for n in fields) and "class_name" in fields, fields)
ds = None

print()
print("a class named outside Latin-1 keeps its name in a shapefile")
# The table of a shapefile is written in ISO-8859-1 unless told otherwise,
# and GDAL turned a Chinese, Greek or Cyrillic name into question marks.
NAMES = ["Água é", "林", "Ελιά",
         "вода"]
wide_pkg = os.path.join(FOLDER, "wide_names.gpkg")
wds = ogr.GetDriverByName("GPKG").CreateDataSource(wide_pkg)
wlayer = wds.CreateLayer("polygons", srs, ogr.wkbMultiPolygon,
                         ["GEOMETRY_NAME=geom"])
for field, ftype in (("class_name", ogr.OFTString),
                     ("class_code", ogr.OFTInteger),
                     ("tile_id", ogr.OFTString)):
    wlayer.CreateField(ogr.FieldDefn(field, ftype))
for i, name in enumerate(NAMES):
    f = ogr.Feature(wlayer.GetLayerDefn())
    geom = ogr.Geometry(ogr.wkbMultiPolygon)
    geom.AddGeometry(square(400000.0 + i * 10, 4100000.0, 4))
    f.SetGeometry(geom)
    f.SetField("class_name", name)
    f.SetField("class_code", i + 1)
    f.SetField("tile_id", "t_001")
    wlayer.CreateFeature(f)
    f = None
wlayer = wds = None
shp_label = [fmt for fmt in FORMATS if fmt[1] == "ESRI Shapefile"][0]
out = os.path.join(FOLDER, "wide_shapefile")
written, failed, notes = write_vectors(
    wide_pkg, {"tables": ["polygons"], "driver": "ESRI Shapefile",
               "extension": shp_label[2], "one_file": shp_label[3],
               "crs": shp_label[4], "tile_id": None, "folder": out},
    "wide")
check("the shapefile is written", len(written) == 1 and not failed,
      (written, failed))
if written:
    shp = written[0]
    sds = ogr.Open(shp)
    got = sorted(f.GetField("class_name") for f in sds.GetLayer(0))
    sds = None
    check("every name is read back as it was", got == sorted(NAMES), got)
    check("and a .cpg says the table is UTF-8",
          os.path.exists(os.path.splitext(shp)[0] + ".cpg")
          and "UTF-8" in open(os.path.splitext(shp)[0] + ".cpg").read().upper())

print()
print("the geometry is written out as text in the csv")
csv_path = os.path.join(FOLDER, "CSV", "aragona_2025_points.csv")
head, first = open(csv_path).readlines()[:2]
check("the geometry is the first column", head.startswith("geom"), head.strip())
check("and it holds WKT", first.startswith('"POINT ('), first.strip())
check("the class is beside it", "class_name" in head, head.strip())
check("a csvt says which column is the geometry",
      open(csv_path[:-4] + ".csvt").read().startswith("WKT"))

print()
print("narrowing down to one frame")
out = os.path.join(FOLDER, "one_frame")
recipe = {"tables": ALL, "driver": "GPKG", "extension": ".gpkg",
          "one_file": True, "crs": None, "tile_id": "t_001", "folder": out}
written, failed, notes = write_vectors(PACKAGE, recipe, "aragona_2025")
check("it was written", bool(written) and not failed, (written, failed))
for name in ALL:
    check("%s kept only the one row of that frame" % name,
          rows_in(written[0], name) == 1, rows_in(written[0], name))

print()
print("exported again into the same folder, narrowed to one frame")
# Overwrite was asked for and GDAL did not do it for a CSV or a GeoJSON: it
# opened the first export, could not take its table out, and gave it back
# as it was, so the second export kept every row of the first and the
# window said it was written.
for label, driver_name, extension, one_file, forced in FORMATS:
    out = os.path.join(FOLDER, driver_name.replace(" ", "_"))
    recipe = {"tables": ALL, "driver": driver_name, "extension": extension,
              "one_file": one_file, "crs": forced, "tile_id": "t_001",
              "folder": out}
    written, failed, notes = write_vectors(PACKAGE, recipe, "aragona_2025")
    check("%s: written again, nothing failed" % driver_name,
          len(written) == (1 if one_file else len(ALL)) and not failed,
          (written, failed))
    for path in written:
        for name in ALL if one_file else [None]:
            got = rows_in(path, name)
            check("%s: %s holds only the frame's one row now"
                  % (driver_name, name or os.path.basename(path)), got == 1,
                  got)

print()
print("a folder that does not exist yet")
out = os.path.join(FOLDER, "deep", "deeper")
recipe = {"tables": ["points"], "driver": "GeoJSON", "extension": ".geojson",
          "one_file": False, "crs": "EPSG:4326", "tile_id": None,
          "folder": out}
written, failed, notes = write_vectors(PACKAGE, recipe, "aragona_2025")
check("is made on the way", bool(written) and os.path.exists(written[0]),
      (written, failed))

print()
print("a table that the format cannot hold")
recipe = {"tables": ["nothing_here"], "driver": "GPKG", "extension": ".gpkg",
          "one_file": False, "crs": None, "tile_id": None,
          "folder": os.path.join(FOLDER, "missing")}
written, failed, notes = write_vectors(PACKAGE, recipe, "aragona_2025")
check("is reported, not crashed through", failed == ["nothing_here"],
      (written, failed))

print()
print("a campaign with no coordinate system")
# A picture, or a world file with no system: the coordinates are pixels, or
# units nobody named. GeoJSON and KML were reprojected to degrees all the
# same: GDAL 3.13 wrote them with no feature at all, GDAL 3.8 with pixels
# labelled as degrees, and both were said written.
NOSYS = os.path.join(FOLDER, "picture.gpkg")
ds = driver.CreateDataSource(NOSYS)
for name, kind, fields in TABLES:
    layer = ds.CreateLayer(name, None, kind, ["GEOMETRY_NAME=geom"])
    for field, ftype in fields:
        layer.CreateField(ogr.FieldDefn(field, ftype))
    for i in range(COUNTS[name]):
        f = ogr.Feature(layer.GetLayerDefn())
        x, y = 40.0 + i * 30, -40.0 - i * 30          # pixels, y = -row
        if kind == ogr.wkbPoint:
            geom = ogr.Geometry(ogr.wkbPoint)
            geom.AddPoint_2D(x + 1, y - 1)
        elif kind == ogr.wkbMultiPolygon:
            geom = ogr.Geometry(ogr.wkbMultiPolygon)
            geom.AddGeometry(square(x, y - 5, 4))
        else:
            geom = square(x, y - 8, 8)
        f.SetGeometry(geom)
        f.SetField("tile_id", "t_001")
        layer.CreateFeature(f)
        f = None
    layer = None
ds = None


def centre_of(path, layer_name=None):
    """The centre of the first shape of a table, and whether the file calls
    its coordinates degrees; None for a table with no shape in it."""
    ds = ogr.Open(path)
    layer = ds.GetLayerByName(layer_name) if layer_name else ds.GetLayer(0)
    ref = layer.GetSpatialRef()
    # the stand-in a GeoPackage gives a table with no system is no claim
    degrees = ref is not None and bool(ref.IsGeographic()) \
        and (ref.GetName() or "") not in ("Undefined geographic SRS",
                                          "Undefined Cartesian SRS")
    if path.endswith(".geojson"):
        # GDAL reads every GeoJSON as WGS 84, which is what the format says
        # a file with no "crs" member is in; the claim is the member itself
        with open(path, encoding="utf-8") as fh:
            degrees = '"crs"' in fh.read()
    f = layer.GetNextFeature()
    out = None
    if f is not None and f.GetGeometryRef() is not None:
        c = f.GetGeometryRef().Centroid()
        out = (c.GetX(), c.GetY(), degrees)
    ds = None
    return out


for label, driver_name, extension, one_file, forced in FORMATS:
    out = os.path.join(FOLDER, "nosys_" + driver_name.replace(" ", "_"))
    # degrees asked for wherever they can be: forced, or the box ticked
    recipe = {"tables": ALL, "driver": driver_name, "extension": extension,
              "one_file": one_file, "crs": "EPSG:4326", "tile_id": None,
              "folder": out, "system": False}
    written, failed, notes = write_vectors(NOSYS, recipe, "photo")
    if driver_name == "KML":
        check("KML, which holds degrees only, is refused",
              not written and sorted(failed) == sorted(ALL),
              (written, failed))
        check("and the note says why",
              any("KML" in n and "coordinate system" in n for n in notes),
              notes)
        check("and no file is left to look like an export",
              not os.path.isdir(out) or not os.listdir(out),
              os.listdir(out) if os.path.isdir(out) else None)
        continue
    check("%s: every table written" % driver_name,
          not failed and len(written) == (1 if one_file else len(ALL)),
          (written, failed))
    for name in ALL:
        path = written[0] if one_file else os.path.join(
            out, "photo_%s%s" % (name, extension))
        got = rows_in(path, name if one_file else None) \
            if os.path.exists(path) else None
        check("%s: %s holds its %d rows" % (driver_name, name, COUNTS[name]),
              got == COUNTS[name], got)
    path = written[0] if written else None
    if path:
        where = centre_of(path, "points" if one_file else None)
        check("%s: in the pixels they were drawn in, not in degrees"
              % driver_name,
              where is not None and where[0] > 30 and where[1] < -30, where)
        check("%s: and nothing in the file calls them degrees" % driver_name,
              where is not None and not where[2], where)
    check("%s: and the window is told the coordinates are not degrees"
          % driver_name,
          any("no coordinate system" in n for n in notes), notes)

# The dialog of an earlier build sends no "system": the tables say it then.
out = os.path.join(FOLDER, "nosys_older_dialog")
recipe = {"tables": ["polygons"], "driver": "GeoJSON",
          "extension": ".geojson", "one_file": False, "crs": "EPSG:4326",
          "tile_id": None, "folder": out}
written, failed, notes = write_vectors(NOSYS, recipe, "photo")
check("the tables' own lack of a system is enough to tell",
      len(written) == 1 and rows_in(written[0]) == COUNTS["polygons"],
      (written, failed, notes))

# What the window sends now for a GeoJSON with no system: no degrees asked.
# The file is still read as degrees by whoever opens it, so it is said.
recipe = dict(recipe, crs=None, system=False,
              folder=os.path.join(FOLDER, "nosys_from_window"))
written, failed, notes = write_vectors(NOSYS, recipe, "photo")
check("a GeoJSON with no system is written, and said not to be in degrees",
      len(written) == 1 and any("no coordinate system" in n for n in notes),
      (written, notes))

print()
print("what GDAL could not write is not said written")
# GDAL is told to skip what it cannot write, so a feature it could not
# reproject comes out without its geometry and a table it could not write
# comes out empty; both used to be counted as written.
FAR = os.path.join(FOLDER, "far.gpkg")
ds = driver.CreateDataSource(FAR)
for name, far in (("polygons", [False, True, False]), ("boxes", [True, True])):
    layer = ds.CreateLayer(name, srs, ogr.wkbPolygon, ["GEOMETRY_NAME=geom"])
    layer.CreateField(ogr.FieldDefn("class_code", ogr.OFTInteger))
    for i, out_there in enumerate(far):
        f = ogr.Feature(layer.GetLayerDefn())
        x = 1e39 if out_there else 400000.0 + i * 10
        f.SetGeometry(square(x, 4100000.0, 8))
        f.SetField("class_code", 1)
        layer.CreateFeature(f)
        f = None
    layer = None
ds = None
out = os.path.join(FOLDER, "far")
recipe = {"tables": ["polygons", "boxes"], "driver": "GeoJSON",
          "extension": ".geojson", "one_file": False, "crs": "EPSG:4326",
          "tile_id": None, "folder": out}
written, failed, notes = write_vectors(FAR, recipe, "far")
check("the table that lost one of its three shapes is still written",
      [os.path.basename(p) for p in written] == ["far_polygons.geojson"],
      written)
check("and the loss is said",
      any("2 of the 3" in n and "polygons" in n for n in notes), notes)
check("the table that lost all of them is a failure", failed == ["boxes"],
      failed)
check("and its empty file is taken away",
      not os.path.exists(os.path.join(out, "far_boxes.geojson")),
      os.listdir(out))

print()
print("a folder near the limit of 260 characters")
# A path past MAX_PATH is reached on Windows only through the \?\ prefix,
# and the export asked Python for the folder, the file and its removal with
# the plain path: the folder could not be made, or the old file not seen, and
# the window blamed the format. Elsewhere a long path is just a path, and
# this checks the same thing for the same reason.
long_top = os.path.join(FOLDER, "a_folder_with_a_long_name")
long_dir = long_top
while len(long_dir) < 236:
    long_dir = os.path.join(long_dir, "a_folder_with_a_long_name_%02d"
                            % len(long_dir))
long_dir = long_dir[:236].rstrip(os.sep + "_")
for label, driver_name, extension, one_file, forced in FORMATS:
    if driver_name not in ("GPKG", "GeoJSON"):
        continue
    for again in (0, 1):
        recipe = {"tables": ["points"], "driver": driver_name,
                  "extension": extension, "one_file": one_file,
                  "crs": forced, "tile_id": None, "folder": long_dir}
        written, failed, notes = write_vectors(PACKAGE, recipe,
                                               "aragona_2025_long_name")
        target = (written or [""])[0]
        check("%s near 260 characters (%s): written, nothing failed"
              % (driver_name, "again" if again else "first"),
              len(written) == 1 and not failed and len(target) > 255,
              (len(target), failed))
        check("%s near 260 characters (%s): the file is there"
              % (driver_name, "again" if again else "first"),
              bool(target) and os.path.exists(g["long_path"](target)))
shutil.rmtree(g["long_path"](long_top), ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all of them pass")
for f in fails:
    print("   " + f)
# Removed at the end, not left behind. This folder used to be a fixed one
# under /tmp, which on Windows is a tmp folder at the root of the drive,
# and every run left its files there.
shutil.rmtree(FOLDER, ignore_errors=True)
sys.exit(1 if fails else 0)
