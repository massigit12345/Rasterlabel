"""The mask of Whole comes with its legend.

A mask was written with the class codes and a band called class_code, and
nothing else: opened in QGIS it was grey, and whoever received it could not
tell a 3 from a 4. Now a GeoTIFF mask carries the classes of the campaign as
its colour table and category names, any mask has a .qml beside it, and a
.qml already there is followed instead of overwritten, so what was set on it
by hand stays. The codes in the pixels are exactly what they were.

Real files, read and written by GDAL; QGIS is faked, see correctkit.py. The
suite that opens the mask in a real QGIS is test_whole_export_qgis.

Needs the GDAL Python bindings.
"""
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

root = tempfile.mkdtemp(prefix="rl_whole_legend_")
W, H = 120, 80
OX, OY, PX = 500000.0, 4100000.0, 0.5
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)

CLASSES = [{"code": 1, "name": "crust", "colour": "#b0651f"},
           {"code": 2, "name": "water", "colour": "#2f6f9f"},
           {"code": 3, "name": "salt", "colour": "#e8e2d5"}]

raster = os.path.join(root, "ortho.tif")
ds = gdal.GetDriverByName("GTiff").Create(raster, W, H, 3, gdal.GDT_Byte)
ds.SetGeoTransform((OX, PX, 0.0, OY, 0.0, -PX))
ds.SetProjection(srs.ExportToWkt())
for b in range(3):
    ds.GetRasterBand(b + 1).WriteArray(np.full((H, W), 90 + 30 * b, np.uint8))
ds = None

package = os.path.join(root, "annotation.gpkg")
ds = ogr.GetDriverByName("GPKG").CreateDataSource(package)
layer = ds.CreateLayer("polygons", srs, ogr.wkbMultiPolygon,
                       ["GEOMETRY_NAME=geom"])
layer.CreateField(ogr.FieldDefn("class_code", ogr.OFTInteger))
for code, (c0, r0) in ((1, (5, 5)), (2, (40, 5)), (3, (70, 30))):
    x0, y0 = OX + c0 * PX, OY - r0 * PX
    x1, y1 = x0 + 20 * PX, y0 - 20 * PX
    f = ogr.Feature(layer.GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt(
        "MULTIPOLYGON(((%r %r,%r %r,%r %r,%r %r,%r %r)))"
        % (x0, y0, x1, y0, x1, y1, x0, y1, x0, y0)))
    f.SetField("class_code", code)
    layer.CreateFeature(f)
    f = None
layer = ds = None


def run(name, driver="GTiff", extension=".tif", classes=None, **extra):
    """paint_whole for a mask alone; returns (path, recipe)."""
    src = gdal.Open(raster)
    path = os.path.join(root, name + extension)
    recipe = {"ds": src, "scale": 1, "rgb": [1, 2, 3],
              "limits": [(0.0, 255.0)] * 3, "alpha": 45,
              "colours": {1: (176, 101, 31), 2: (47, 111, 159),
                          3: (232, 226, 213)},
              "outputs": [("mask", path, driver)], "package": package,
              "want_lines": False, "want_points": False,
              "want_boxes": False, "points_in_mask": False, "dot_px": 1}
    if classes is not None:
        recipe["classes"] = classes
    recipe.update(extra)
    g["paint_whole"](recipe)
    src = None
    return path, recipe


def pixels(path):
    f = gdal.Open(path)
    out = f.GetRasterBand(1).ReadAsArray()
    f = None
    return out


def qml(path):
    return os.path.splitext(path)[0] + ".qml"


print("a GeoTIFF mask")
bare, _ = run("bare")
dressed, recipe = run("dressed", classes=CLASSES)
f = gdal.Open(bare)
check("without classes there is no .qml and no colour table, as before",
      not os.path.exists(qml(bare))
      and f.GetRasterBand(1).GetColorTable() is None)
f = None
check("the codes are exactly the ones the bare mask holds",
      np.array_equal(pixels(dressed), pixels(bare)))
check("and they are the three classes", sorted(
    int(v) for v in np.unique(pixels(dressed))) == [0, 1, 2, 3])
f = gdal.Open(dressed)
band = f.GetRasterBand(1)
table = band.GetColorTable()
check("a colour table is inside the file", table is not None)
if table is not None:
    check("with the colour of every class",
          table.GetColorEntry(1)[:3] == (176, 101, 31)
          and table.GetColorEntry(2)[:3] == (47, 111, 159)
          and table.GetColorEntry(3)[:3] == (232, 226, 213),
          [table.GetColorEntry(i) for i in range(4)])
    check("and no class colour for the value that is none",
          table.GetColorEntry(0)[:3] not in [
              table.GetColorEntry(i)[:3] for i in (1, 2, 3)],
          table.GetColorEntry(0))
names = band.GetCategoryNames()
check("the category names, by code", names is not None
      and list(names)[1:4] == ["crust", "water", "salt"], names)
check("the band is still called class_code",
      band.GetDescription() == "class_code", band.GetDescription())
check("and says it is a palette", band.GetColorInterpretation()
      == gdal.GCI_PaletteIndex)
check("no nodata where none was asked", band.GetNoDataValue() is None,
      band.GetNoDataValue())
check("the readings are still said inside the file",
      "RASTERLABEL_READING_MODE" in (f.GetMetadata() or {}),
      f.GetMetadata())
f = band = table = None
text = open(qml(dressed), encoding="utf-8").read() \
    if os.path.exists(qml(dressed)) else ""
check("a .qml of the same name beside it", bool(text))
check("which is a paletted style of band 1",
      'type="paletted"' in text and 'band="1"' in text, text[:300])
check("with every class: code, colour and name",
      all(('value="%d"' % c["code"]) in text and c["name"] in text
          and c["colour"] in text for c in CLASSES), text)
check("the .qml is handed back, for the box that names the files",
      recipe.get("sidecars") == [qml(dressed)], recipe.get("sidecars"))
# a GeoTIFF keeps category names in the .aux.xml beside it, as it does for
# the corrected map of Correct
check("the category names are in the .aux.xml beside it",
      "<Category>crust</Category>" in open(
          dressed + ".aux.xml", encoding="utf-8").read())

print()
print("with an ignore value where nobody painted")
bare255, _ = run("bare255", unlabelled="ignore", ignore=255)
dress255, _ = run("dress255", classes=CLASSES, unlabelled="ignore",
                  ignore=255)
check("the codes, 255 included, are exactly the same",
      np.array_equal(pixels(dress255), pixels(bare255))
      and 255 in np.unique(pixels(dress255)))
f = gdal.Open(dress255)
band = f.GetRasterBand(1)
check("the nodata is still 255", band.GetNoDataValue() == 255,
      band.GetNoDataValue())
check("and the colour table is there", band.GetColorTable() is not None)
check("with 255 not among the classes of the .qml",
      'value="255"' not in open(qml(dress255), encoding="utf-8").read())
f = band = None

print()
print("a mask of sixteen bits, which a GeoTIFF gives no table for")
wide, _ = run("wide", classes=CLASSES, unlabelled="ignore", ignore=-9999)
bare_wide, _ = run("bare_wide", unlabelled="ignore", ignore=-9999)
check("the codes are the same", np.array_equal(pixels(wide),
                                               pixels(bare_wide)))
check("its .qml is there", os.path.exists(qml(wide)))
f = gdal.Open(wide)
check("and no colour table, which a GeoTIFF of that type cannot hold",
      f.GetRasterBand(1).GetColorTable() is None)
f = None
check("its category names are in the .aux.xml",
      "<Category>salt</Category>" in open(
          wide + ".aux.xml", encoding="utf-8").read())

print()
print("a PNG mask")
png, _ = run("png", driver="PNG", extension=".png", classes=CLASSES)
bare_png, _ = run("bare_png", driver="PNG", extension=".png")
check("the codes are the same", np.array_equal(pixels(png),
                                               pixels(bare_png)))
check("it has its .qml", os.path.exists(qml(png)))
# a PNG already has an .aux.xml for its georeferencing; what GDAL would add
# to it for the names is the file nobody asked for
check("and the names are not added to the .aux.xml of the PNG",
      not os.path.exists(png + ".aux.xml")
      or "<Category>" not in open(png + ".aux.xml",
                                  encoding="utf-8").read())

print()
print("a .qml that is already there is followed")
again = os.path.join(root, "again.tif")
with open(qml(again), "w", encoding="utf-8") as out:
    out.write(g["style_text"](
        1, [{"code": 9, "name": "old", "colour": "#000000"}]).replace(
            'opacity="1"', 'opacity="0.55"'))
run("again", classes=CLASSES)
text = open(qml(again), encoding="utf-8").read()
check("the classes are those of the campaign now",
      "crust" in text and 'value="9"' not in text, text)
check("the opacity somebody set stays", 'opacity="0.55"' in text, text)

print()
print("no legend, no trouble")
check("a campaign with no classes writes none",
      not os.path.exists(qml(run("none", classes=[])[0])))

shutil.rmtree(root, ignore_errors=True)
sys.exit(K.finish())
