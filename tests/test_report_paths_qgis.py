"""What QGIS opens on Windows past 260 characters, asked of QGIS itself.

tests/test_report_paths.py holds the rule that refuses a report whose
GeoPackage QGIS could not open. The rule rests on facts that only a QGIS can
state, and they are asked here, of whichever QGIS runs the suite (the run of
2026 was made on 3.36, 3.44 and 4.2, and the three said the same):

- a GeoPackage on 300 characters of path is written by GDAL (through the
  \\\\?\\ form of the path, long_path) and QGIS says the layer is not valid,
  with the plain path and with the \\\\?\\ one alike;
- a GeoPackage on the longest path the rule lets be, 248 characters, opens,
  holds its feature and can be edited and saved: QGIS 3.36 edits through a
  -journal file beside the GeoPackage, eight characters more than its path,
  and a path that left no room for it (252) loaded and could not be changed;
- a GeoTIFF on 300 characters opens, and so does a GeoJSON, which is why the
  rule holds only a SQLite file to a length: refusing a map of pairs for the
  length of its path would refuse a report that loads.

If a QGIS one day opens the GeoPackage, the first of these fails, and the
rule can go. Windows only: the limit is the one of its path names. Elsewhere
the suite says so and ends clean.

Needs QGIS; tests/run.py skips it where QGIS is missing and, with
RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qgiskit as K  # noqa: E402
from osgeo import gdal, ogr, osr  # noqa: E402
from qgis.core import QgsRasterLayer, QgsVectorLayer  # noqa: E402

g, check = K.g, K.check

if os.name != "nt":
    print("the limit is Windows's: nothing to ask on this machine")
    K.finish()

PREFIX = "\\\\?\\"
root = tempfile.mkdtemp(prefix="rl_paths_")


def made(path):
    """A folder at any depth, one level at a time: os.makedirs cannot walk a
    path in the \\\\?\\ form."""
    todo, cur = [], path
    while not os.path.isdir(PREFIX + cur):
        todo.append(cur)
        cur = os.path.dirname(cur)
    for p in reversed(todo):
        os.mkdir(PREFIX + p)
    return path


def folder_for(n, name):
    """A folder under root whose path with this file in it is n long."""
    k = n - len(root) - 1 - len(name) - 1
    return made(os.path.join(root, "d" * k))


UTM = osr.SpatialReference()
UTM.ImportFromEPSG(32633)


def geopackage(path):
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(PREFIX + path)
    lyr = ds.CreateLayer("frames", UTM, ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn("n", ogr.OFTInteger))
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt("POLYGON((0 0,1 0,1 1,0 0))"))
    lyr.CreateFeature(f)
    ds = None


def edits(path, layer):
    """Start editing, change a value and save, as a field calculation does."""
    v = QgsVectorLayer("%s|layername=%s" % (path, layer), "x", "ogr")
    if not (v.isValid() and v.startEditing()):
        return False
    first = next(v.getFeatures())
    ok = v.changeAttributeValue(first.id(), v.fields().indexOf("n"), 7)
    return bool(ok and v.commitChanges())


def loads(path, layer):
    v = QgsVectorLayer("%s|layername=%s" % (path, layer), "x", "ogr")
    return v.isValid() and v.featureCount() == 1


try:
    long_gpkg = os.path.join(folder_for(300, "frames.gpkg"), "frames.gpkg")
    geopackage(long_gpkg)
    print("on %d characters" % len(long_gpkg))
    check("the GeoPackage was written", os.path.exists(PREFIX + long_gpkg))
    check("QGIS cannot open it by its path",
          not loads(long_gpkg, "frames"))
    check("nor by the \\\\?\\ form of it",
          not loads(PREFIX + long_gpkg, "frames"))

    room = g["WINDOWS_PATH_MAX"] - g["SQLITE_SIDE_FILES"] \
        - g["REPORT_RENUMBER"]
    near_gpkg = os.path.join(folder_for(room, "frames.gpkg"), "frames.gpkg")
    geopackage(near_gpkg)
    print("on %d characters" % len(near_gpkg))
    check("the longest path the rule lets be is %d" % room,
          len(near_gpkg) == room, len(near_gpkg))
    check("QGIS opens it and reads its feature", loads(near_gpkg, "frames"))
    check("and edits it and saves, which takes a -journal beside it",
          edits(near_gpkg, "frames"))

    long_tif = os.path.join(folder_for(300, "pairs.tif"), "pairs.tif")
    ds = gdal.GetDriverByName("GTiff").Create(PREFIX + long_tif, 4, 4, 1,
                                              gdal.GDT_Byte)
    ds.SetGeoTransform((0, 1, 0, 4, 0, -1))
    ds.SetProjection(UTM.ExportToWkt())
    ds.GetRasterBand(1).Fill(1)
    ds = None
    print("on %d characters" % len(long_tif))
    check("a GeoTIFF opens in QGIS", QgsRasterLayer(long_tif, "x").isValid())

    long_json = os.path.join(folder_for(300, "places.geojson"),
                             "places.geojson")
    ds = ogr.GetDriverByName("GeoJSON").CreateDataSource(PREFIX + long_json)
    lyr = ds.CreateLayer("places", UTM, ogr.wkbPolygon)
    f = ogr.Feature(lyr.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt("POLYGON((0 0,1 0,1 1,0 0))"))
    lyr.CreateFeature(f)
    ds = None
    print("on %d characters" % len(long_json))
    check("a GeoJSON opens in QGIS",
          QgsVectorLayer(long_json, "x", "ogr").isValid())
finally:
    for top in os.listdir(root):
        shutil.rmtree(PREFIX + os.path.join(root, top), ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)

K.finish()
