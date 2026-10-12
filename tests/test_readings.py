"""Two operators, two passes, one frame: what goes out, and what is closed.

The campaign every claim here is tried on is small and drawn so that the
readings disagree in known places. ANNA and BRUNO both read the frame in
pass 1, each one all of it, with the border between their two classes in a
different place; in pass 2 each read only half of it. Painted one on top of
the other, the last drawn wins and the mask is neither reading, which is what
the Whole raster and Export always wrote. So each reading can go out on its
own, and the readings can vote.

Real GDAL, a real GeoPackage, the code lifted out of rasterlabel.py as
written. Also here: the class codes a byte cannot hold (a mask is widened
only for a code that is really past 254), and the closed column measured
reading by reading in measure_tile.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from decimal import Decimal

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

SRC = os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)

fails = []


def check(name, cond, detail=""):
    cond = bool(cond)
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if not cond else ""))
    if not cond:
        fails.append(name)


def method(name, inside):
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    first = min([sub.lineno] +
                                [d.lineno for d in sub.decorator_list])
                    t = "".join(lines[first - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s.%s not found" % (inside, name))


# Everything the exports and the whole raster call, as written.
WANTED = {
    # the readings
    "MAX_CLASS_CODE", "IGNORE_CODE", "OPERATOR_BLANK", "VERSION",
    "CLOSED_SHARE",
    "READING_TABLES", "operator_word", "pass_number", "reading_label",
    "readings_in", "reading_choices", "majority", "reading_rule",
    "reading_metadata", "no_room_for_class", "tidy", "now", "long_path",
    # who votes where in a consensus
    "consensus_voters", "voters_in", "frames_by_readings_text",
    "reading_shares", "_package_read", "_field_of", "_sql_list",
    "_clipped", "_area_of_union",
    # the whole raster
    "Stencil", "ConsensusCover", "open_for_write", "landed", "finish_write",
    "paint_whole", "mask_type", "vote", "class_band_type", "is_class_code",
    "class_array", "put_raster", "write_tif", "pixel_grid", "pixel_holding",
    "put_picture", "scratch_of",
    "drop_scratch",
    # what the mask holds where nobody painted (test_ignore_index)
    "unlabelled_metadata", "unlabelled_rule", "ignore_refusal",
    "settle_unlabelled", "_tally_add",
    # the vector export
    "FORMATS", "count_rows", "write_vectors", "TEXT_DRIVERS",
    "FULL_PRECISION", "WRITTEN_WHOLE", "exact_text", "NUMBER",
    "GEOMETRY_TEXT", "COORDINATES", "full_precision", "coordinates_exact",
    "runs_of", "renumbered", "rewrite_coordinates", "invalid_polygons",
    "write_reading", "narrowed_package", "polygonal", "solid",
    "consensus_polygons", "PLACEHOLDER_SRS", "tables_have_system",
    "feature_counts", "remove_output"}
pieces, found = [], set()
for node in tree.body:
    name = getattr(node, "name", None)
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        name = node.targets[0].id
    if name in WANTED and name not in found:
        found.add(name)
        pieces.append("".join(lines[node.lineno - 1:node.end_lineno]))
assert found == WANTED, sorted(WANTED - found)
said = []
g = {"os": os, "re": re, "shutil": shutil, "tempfile": tempfile,
     "Decimal": Decimal, "math": math, "datetime": datetime, "np": np,
     "gdal": gdal, "ogr": ogr, "osr": osr, "IOError": IOError,
     "STRIP_ROWS": 16,
     "log": lambda m, loud=False: said.append(str(m)),
     "release_file": lambda p: 0}
exec("\n".join(pieces), g)

# ------------------------------------------------------------- the campaign
W = H = 100
PX = 1.0
OX, OY = 1000.0, 2000.0
FOLDER = tempfile.mkdtemp(prefix="rl_readings_")
PACKAGE = os.path.join(FOLDER, "annotation.gpkg")
RASTER = os.path.join(FOLDER, "ortho.tif")

TABLES = [("tiles", ogr.wkbPolygon,
           [("tile_id", ogr.OFTString), ("side_m", ogr.OFTReal),
            ("note", ogr.OFTString), ("created", ogr.OFTString),
            ("closed", ogr.OFTInteger)]),
          ("polygons", ogr.wkbMultiPolygon,
           [("class_name", ogr.OFTString), ("class_code", ogr.OFTInteger),
            ("tile_id", ogr.OFTString), ("pass_no", ogr.OFTInteger),
            ("operator", ogr.OFTString), ("created", ogr.OFTString)]),
          ("lines", ogr.wkbMultiLineString,
           [("class_name", ogr.OFTString), ("class_code", ogr.OFTInteger),
            ("tile_id", ogr.OFTString), ("pass_no", ogr.OFTInteger),
            ("operator", ogr.OFTString), ("width_px", ogr.OFTInteger),
            ("width_m", ogr.OFTReal), ("length_m", ogr.OFTReal),
            ("mode", ogr.OFTString), ("created", ogr.OFTString)]),
          ("points", ogr.wkbPoint,
           [("class_name", ogr.OFTString), ("class_code", ogr.OFTInteger),
            ("tile_id", ogr.OFTString), ("pass_no", ogr.OFTInteger),
            ("operator", ogr.OFTString), ("size_px", ogr.OFTInteger),
            ("conf", ogr.OFTString), ("created", ogr.OFTString)]),
          ("boxes", ogr.wkbPolygon,
           [("class_name", ogr.OFTString), ("class_code", ogr.OFTInteger),
            ("tile_id", ogr.OFTString), ("pass_no", ogr.OFTInteger),
            ("operator", ogr.OFTString), ("width_m", ogr.OFTReal),
            ("height_m", ogr.OFTReal), ("created", ogr.OFTString)])]
NAMES = {1: "mud", 2: "crust", 3: "rill", 4: "vent", 5: "pool", 6: "cone",
         300: "far"}


def columns(c0, c1):
    """The pixel columns c0 to c1 - 1, the whole height of the frame."""
    x0, x1 = OX + c0 * PX, OX + c1 * PX
    return "MULTIPOLYGON(((%f %f,%f %f,%f %f,%f %f,%f %f)))" % (
        x0, OY, x1, OY, x1, OY - H * PX, x0, OY - H * PX, x0, OY)


# (table, wkt, code, operator, pass_no): in this order, which is the order
# they were drawn in. Names are written the way people type them: the same
# person in two cases, a pass left empty.
MARKS = [
    ("polygons", columns(0, 60), 1, "Anna", 1),
    ("polygons", columns(60, 100), 2, "ANNA ", 1),
    ("polygons", columns(0, 40), 1, "bruno", None),
    ("polygons", columns(40, 100), 2, "BRUNO", 1),
    ("polygons", columns(0, 50), 1, "ANNA", 2),
    ("polygons", columns(50, 100), 2, "BRUNO", 2),
    ("lines", "MULTILINESTRING((%f %f,%f %f))" % (
        OX + 5, OY - 30.5, OX + 95, OY - 30.5), 3, "ANNA", 1),
    ("points", "POINT(%f %f)" % (OX + 10.5, OY - 10.5), 4, "ANNA", 1),
    ("points", "POINT(%f %f)" % (OX + 80.5, OY - 80.5), 5, "BRUNO", 1),
    ("boxes", "POLYGON((%f %f,%f %f,%f %f,%f %f,%f %f))" % (
        OX + 20, OY - 20, OX + 30, OY - 20, OX + 30, OY - 30, OX + 20,
        OY - 30, OX + 20, OY - 20), 6, "BRUNO", 2),
]


def make_package(path, marks):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32633)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    layers = {}
    for name, kind, fields in TABLES:
        lyr = ds.CreateLayer(name, srs, kind, ["GEOMETRY_NAME=geom"])
        for field, ftype in fields:
            lyr.CreateField(ogr.FieldDefn(field, ftype))
        layers[name] = lyr
    f = ogr.Feature(layers["tiles"].GetLayerDefn())
    f.SetGeometry(ogr.CreateGeometryFromWkt(
        "POLYGON((%f %f,%f %f,%f %f,%f %f,%f %f))" % (
            OX, OY, OX + W, OY, OX + W, OY - H, OX, OY - H, OX, OY)))
    f.SetField("tile_id", "t001")
    f.SetField("closed", 0)
    layers["tiles"].CreateFeature(f)
    for table, wkt, code, who, p in marks:
        lyr = layers[table]
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
        f.SetField("class_code", code)
        f.SetField("class_name", NAMES[code])
        f.SetField("tile_id", "t001")
        f.SetField("operator", who)
        if p is not None:
            f.SetField("pass_no", p)
        if table == "points":
            f.SetField("size_px", 1)
        lyr.CreateFeature(f)
        f = None
    ds = None


def make_raster(path):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32633)
    ds = gdal.GetDriverByName("GTiff").Create(path, W, H, 3, gdal.GDT_Byte)
    for i in range(3):
        ds.GetRasterBand(i + 1).Fill(100 + 20 * i)
    ds.SetGeoTransform((OX, PX, 0, OY, 0, -PX))
    ds.SetProjection(srs.ExportToWkt())
    ds = None


make_package(PACKAGE, MARKS)
make_raster(RASTER)
ANNA1, BRUNO1, ANNA2, BRUNO2 = (("ANNA", 1), ("BRUNO", 1), ("ANNA", 2),
                                ("BRUNO", 2))

try:
    # --------------------------------------------------------- the readings
    print("the readings of the package")
    counts = g["readings_in"](PACKAGE)
    check("four readings, however the names and the passes were typed",
          sorted(counts) == sorted([ANNA1, BRUNO1, ANNA2, BRUNO2]),
          sorted(counts))
    check("each with the marks it holds, from every table",
          counts[ANNA1] == 4 and counts[BRUNO1] == 3 and counts[BRUNO2] == 2,
          counts)
    choices = g["reading_choices"](counts)
    by_tag = {c["tag"]: c for c in choices}
    check("all together first, as both windows always did",
          choices[0]["mode"] == "all" and choices[0]["tag"] == "", choices[0])
    check("then each reading on its own",
          [c["label"] for c in choices if c["mode"] == "one"]
          == ["ANNA, pass 1", "BRUNO, pass 1", "ANNA, pass 2",
              "BRUNO, pass 2"],
          [c["label"] for c in choices])
    check("a consensus for each pass read by two operators, and of all four",
          {"consensus_p1", "consensus_p2", "consensus_all"} <= set(by_tag),
          sorted(by_tag))
    check("a strict majority: both of two, two of three, three of four",
          (g["majority"](2), g["majority"](3), g["majority"](4)) == (2, 2, 3))

    # ----------------------------------------------------- the whole raster
    COLOURS = {c: (200, 10 * c, 0) for c in NAMES}

    def whole(choice, kinds=("mask",), points_in=False, package=PACKAGE,
              tag="x"):
        outputs = []
        for k in kinds:
            outputs.append((k, os.path.join(FOLDER, "%s_%s.tif" % (tag, k)),
                            "GTiff"))
        src = gdal.Open(RASTER)
        recipe = {"ds": src, "scale": 1, "rgb": [1, 2, 3],
                  "limits": [(0.0, 255.0)] * 3, "alpha": 45,
                  "colours": COLOURS, "outputs": outputs,
                  "package": package, "want_lines": True,
                  "want_points": True, "want_boxes": True,
                  "points_in_mask": points_in, "dot_px": 1,
                  "reading": choice}
        g["paint_whole"](recipe)
        src = None
        out = {}
        for k, path, _ in outputs:
            ds = gdal.Open(path)
            out[k] = (ds.ReadAsArray(), ds.GetMetadata(),
                      ds.GetRasterBand(1).DataType,
                      [ds.GetRasterBand(b + 1).GetDescription()
                       for b in range(ds.RasterCount)])
            ds = None
        return out

    print()
    print("the whole raster, every reading together: the last drawn wins")
    m, tags, kind, _ = whole(choices[0], tag="all")["mask"]
    check("the mask is pass 2 painted over pass 1, neither reading",
          int((m == 1).sum()) == 5000 and int((m == 2).sum()) == 5000,
          (int((m == 1).sum()), int((m == 2).sum())))
    check("and it says so inside the file",
          tags.get("RASTERLABEL_READING_MODE") == "all"
          and "drawn last wins" in tags.get("RASTERLABEL_READING_RULE", ""),
          tags)
    check("in one byte", kind == gdal.GDT_Byte, kind)

    print()
    print("one reading")
    out = whole(by_tag["ANNA_p1"], kinds=("mask", "painted"), tag="anna1")
    m, tags, _, names = out["mask"]
    check("ANNA's pass 1 alone: her border at column 60",
          int((m[:, :60] == 1).sum()) == 6000
          and int((m[:, 60:] == 2).sum()) == 4000, np.unique(m))
    check("named in the file", tags.get("RASTERLABEL_READINGS")
          == "ANNA, pass 1" and tags.get("RASTERLABEL_READING_MODE") == "one",
          tags)
    check("and the band says what it holds", names == ["class_code"], names)
    painted = out["painted"][0]
    bruno_dot = painted[:, 80, 80]
    check("BRUNO's point is not painted on ANNA's image",
          tuple(int(v) for v in bruno_dot) != COLOURS[5],
          tuple(int(v) for v in bruno_dot))
    anna_dot = painted[:, 10, 10]
    check("ANNA's is", tuple(int(v) for v in anna_dot) == COLOURS[4],
          tuple(int(v) for v in anna_dot))
    m = whole(by_tag["BRUNO_p1"], tag="bruno1")["mask"][0]
    check("BRUNO's pass 1 alone, his pass left empty in the file: column 40",
          int((m[:, :40] == 1).sum()) == 4000
          and int((m[:, 40:] == 2).sum()) == 6000, np.unique(m))
    m = whole(by_tag["ANNA_p1"], points_in=True, tag="anna1p")["mask"][0]
    check("points in the mask are the reading's own points",
          int(m[10, 10]) == 4 and int(m[80, 80]) == 2, (m[10, 10], m[80, 80]))

    print()
    print("the consensus of pass 1")
    out = whole(by_tag["consensus_p1"], kinds=("mask", "votes"), tag="c1")
    m, tags, _, _ = out["mask"]
    v, vtags, vkind, vnames = out["votes"]
    check("the class both gave: mud left of 40, crust right of 60",
          int((m[:, :40] == 1).sum()) == 4000
          and int((m[:, 60:] == 2).sum()) == 4000, np.unique(m))
    check("and nothing where they disagree, columns 40 to 59",
          int((m[:, 40:60] == 0).sum()) == 2000, int((m[:, 40:60] != 0).sum()))
    check("the votes: two where they agree, none where they do not",
          v.shape == (2, H, W) and (v[0][:, :40] == 2).all()
          and (v[0][:, 40:60] == 0).all(), np.unique(v[0]))
    check("and both painted every pixel", (v[1] == 2).all(), np.unique(v[1]))
    check("the votes say what their bands are",
          vnames == ["votes", "readings_labelled"], vnames)
    check("the rule is written into the mask",
          tags.get("RASTERLABEL_READING_MODE") == "consensus"
          and "at least 2" in tags.get("RASTERLABEL_READING_RULE", "")
          and tags.get("RASTERLABEL_READINGS") == "ANNA, pass 1; BRUNO, pass 1",
          tags)

    print()
    print("the consensus of all four readings: three of four")
    out = whole(by_tag["consensus_all"], kinds=("mask", "votes"), tag="call")
    m = out["mask"][0]
    v = out["votes"][0]
    check("mud where three gave it, columns 0 to 39",
          int((m[:, :40] == 1).sum()) == 4000 and (v[0][:, :40] == 3).all(),
          (int((m[:, :40] == 1).sum()), np.unique(v[0][:, :40])))
    check("crust where three gave it, columns 60 to 99",
          int((m[:, 60:] == 2).sum()) == 4000, int((m[:, 60:] == 2).sum()))
    check("nothing where only two of four agree, 40 to 59",
          (m[:, 40:60] == 0).all(), np.unique(m[:, 40:60]))
    check("three readings painted every pixel", (v[1] == 3).all(),
          np.unique(v[1]))

    # ------------------------------------------------------- the export
    def export(choice, driver="GPKG", extension=".gpkg", one_file=True,
               tables=("tiles", "polygons", "lines", "points", "boxes"),
               tag="x"):
        folder = os.path.join(FOLDER, "export_" + tag)
        recipe = {"tables": list(tables), "driver": driver,
                  "extension": extension, "one_file": one_file, "crs": None,
                  "tile_id": None, "folder": folder, "reading": choice}
        written, failed, notes = g["write_vectors"](PACKAGE, recipe, "camp")
        return written, failed, notes, folder

    def rows(path, table):
        ds = ogr.Open(path)
        lyr = ds.GetLayerByName(table)
        out = []
        for f in lyr:
            item = {k: f.GetField(k) for k in
                    (lyr.GetLayerDefn().GetFieldDefn(i).GetName()
                     for i in range(lyr.GetLayerDefn().GetFieldCount()))}
            item["geom"] = f.GetGeometryRef().Clone()
            out.append(item)
        ds = None
        return out

    print()
    print("the export, every reading together, is what it always was")
    written, failed, _, _ = export(choices[0], tag="all")
    check("one file, nothing failed", len(written) == 1 and not failed,
          (written, failed))
    check("every polygon of every reading",
          len(rows(written[0], "polygons")) == 6)

    print()
    print("the export of one reading")
    written, failed, notes, _ = export(by_tag["BRUNO_p1"], tag="bruno")
    check("written", len(written) == 1 and not failed, (written, failed))
    polys = rows(written[0], "polygons")
    check("BRUNO's two polygons of pass 1 and nothing else",
          len(polys) == 2 and {p["operator"].strip().upper()
                               for p in polys} == {"BRUNO"}, polys)
    check("his point, not ANNA's", [p["class_code"] for p in
                                    rows(written[0], "points")] == [5])
    check("no line and no box: they are not his in pass 1",
          not rows(written[0], "lines") and not rows(written[0], "boxes"))
    check("the frame goes out, it is nobody's",
          len(rows(written[0], "tiles")) == 1)
    written, failed, _, _ = export(by_tag["ANNA_p2"], driver="ESRI Shapefile",
                                   extension=".shp", one_file=False,
                                   tables=("polygons",), tag="shp")
    check("a format of one table a file too",
          len(written) == 1 and len(rows(written[0], "camp_polygons")) == 1,
          (written, failed))

    print()
    print("the export of a consensus")
    written, failed, notes, _ = export(by_tag["consensus_p1"], tag="c1")
    polys = rows(written[0], "polygons")
    area = {}
    for p in polys:
        area[p["class_code"]] = area.get(p["class_code"], 0.0) \
            + p["geom"].GetArea()
    check("the ground both gave mud and the ground both gave crust",
          abs(area.get(1, 0) - 4000) < 1e-6 and abs(area.get(2, 0) - 4000)
          < 1e-6, area)
    check("each one says it is a consensus, of pass 1, and by how much",
          all(p["operator"] == "CONSENSUS" and p["pass_no"] == 1
              and p["votes"] == 2 and p["readings"] == 2 for p in polys),
          [(p["operator"], p["pass_no"], p["votes"], p["readings"])
           for p in polys])
    check("named as their class", {p["class_name"] for p in polys}
          == {"mud", "crust"})
    check("the points of both readings go out, each with its reading",
          sorted(p["class_code"] for p in rows(written[0], "points"))
          == [4, 5])
    check("a valid polygon in, a valid polygon out", not notes, notes)

    # the vector consensus burned is the raster consensus
    burned = gdal.GetDriverByName("MEM").Create("", W, H, 1, gdal.GDT_Byte)
    burned.SetGeoTransform((OX, PX, 0, OY, 0, -PX))
    vds = ogr.Open(written[0])
    gdal.RasterizeLayer(burned, [1], vds.GetLayerByName("polygons"),
                        options=["ATTRIBUTE=class_code"])
    vds = None
    raster_c1 = whole(by_tag["consensus_p1"], tag="c1b")["mask"][0]
    check("burned, it is the consensus mask pixel for pixel",
          (burned.ReadAsArray() == raster_c1).all(),
          int((burned.ReadAsArray() != raster_c1).sum()))
    burned = None

    written, failed, _, _ = export(by_tag["consensus_all"], tag="call")
    polys = rows(written[0], "polygons")
    check("of four: three votes, of four readings, and no pass of its own",
          polys and all(p["votes"] == 3 and p["readings"] == 4
                        and p["pass_no"] is None for p in polys),
          [(p["votes"], p["readings"], p["pass_no"]) for p in polys])
    check("over the same ground as the raster",
          abs(sum(p["geom"].GetArea() for p in polys) - 8000) < 1e-6,
          sum(p["geom"].GetArea() for p in polys))

    print()
    print("the boxes go out with their reading")
    # Objects now stamps a box with the reading that drew it, so the box of
    # BRUNO's second pass is his, in pass 2, wherever the readings are split.
    def box_readings(choice, tag):
        written, failed, _, _ = export(choice, tag=tag)
        return sorted((b["operator"], b["pass_no"])
                      for b in rows(written[0], "boxes"))
    check("in BRUNO's second pass, his box",
          box_readings(by_tag["BRUNO_p2"], "bx_b2") == [("BRUNO", 2)],
          box_readings(by_tag["BRUNO_p2"], "bx_b2"))
    check("in ANNA's second pass, none",
          box_readings(by_tag["ANNA_p2"], "bx_a2") == [])
    check("in the consensus of pass 2, his box, as it was drawn",
          box_readings(by_tag["consensus_p2"], "bx_c2") == [("BRUNO", 2)],
          box_readings(by_tag["consensus_p2"], "bx_c2"))
    check("in the consensus of pass 1, none",
          box_readings(by_tag["consensus_p1"], "bx_c1") == [])
    check("in the consensus of every reading, his box",
          box_readings(by_tag["consensus_all"], "bx_ca") == [("BRUNO", 2)])

    # --------------------------------------------------- class codes
    print()
    print("class codes and the byte of the mask")
    mask_type = g["mask_type"]
    check("1 to 254 is one byte", mask_type(254) == gdal.GDT_Byte)
    check("255 is kept for ignore, so a class 255 is not written as one",
          mask_type(255) == gdal.GDT_UInt16 and g["IGNORE_CODE"] == 255)
    check("past a byte, two", mask_type(300) == gdal.GDT_UInt16)
    check("the ceiling is said in the words the user is refused with",
          "254" in g["no_room_for_class"]()
          and "255" in g["no_room_for_class"]())
    wide = os.path.join(FOLDER, "wide.gpkg")
    make_package(wide, MARKS[:1] + [("polygons", columns(60, 100), 300,
                                      "ANNA", 1)])
    m, _, kind, _ = whole(by_tag["ANNA_p1"], package=wide, tag="wide")["mask"]
    check("a campaign that holds class 300 gets a 16 bit mask",
          kind == gdal.GDT_UInt16, gdal.GetDataTypeName(kind))
    check("with 300 in it, not 44", int((m == 300).sum()) == 4000
          and int((m == 44).sum()) == 0, np.unique(m))
    check("and the classes under 255 untouched", int((m == 1).sum()) == 6000)

    def band_of(values, dtype, nodata=None):
        path = os.path.join(FOLDER, "cls_%d.tif" % len(os.listdir(FOLDER)))
        ds = gdal.GetDriverByName("GTiff").Create(path, 4, 1, 1, dtype)
        ds.GetRasterBand(1).WriteArray(np.array([values]))
        if nodata is not None:
            ds.GetRasterBand(1).SetNoDataValue(nodata)
        ds = None
        return gdal.Open(path)

    cbt = g["class_band_type"]
    check("a map of bytes is cut in bytes",
          cbt(band_of([0, 1, 255, 3], gdal.GDT_Byte), 1) == gdal.GDT_Byte)
    check("a 16 bit map whose classes fit in a byte is cut in bytes",
          cbt(band_of([0, 1, 200, 3], gdal.GDT_UInt16), 1) == gdal.GDT_Byte)
    check("one with a class 300 in 16 bits, not wrapped",
          cbt(band_of([0, 1, 300, 3], gdal.GDT_UInt16), 1) == gdal.GDT_UInt16)
    check("its nodata counts, since a window past the edge holds it",
          cbt(band_of([0, 1, 2, 3], gdal.GDT_UInt16, 65535), 1)
          == gdal.GDT_UInt16)
    check("negative codes keep their sign",
          cbt(band_of([-5, 1, 2, 3], gdal.GDT_Int16), 1) == gdal.GDT_Int16)
    for driver, ext in (("GTiff", ".tif"), ("PNG", ".png")):
        path = os.path.join(FOLDER, "codes" + ext)
        codes = np.array([[[0, 1, 300, 254]]], g["class_array"](
            gdal.GDT_UInt16))
        g["put_raster"](driver, path, codes, (OX, PX, 0, OY, 0, -PX), "",
                        dtype=gdal.GDT_UInt16)
        back = gdal.Open(path).ReadAsArray()
        check("a cutout of classes past a byte, as %s, reads back the same"
              % driver, back.tolist() == [[0, 1, 300, 254]], back.tolist())

    # ------------------------------------------- the readings, into a cutout
    print()
    print("a cutout of a consensus mask carries which readings it holds")
    exec(method("readings_of", "CutoutsSection"), g)
    readings_of = getattr(g["readings_of"], "__func__", g["readings_of"])
    ds = gdal.Open(os.path.join(FOLDER, "c1_mask.tif"))
    got = readings_of(ds)
    ds = None
    check("it is read off the mask", got and got[
        "RASTERLABEL_READING_MODE"] == "consensus", got)
    ds = gdal.Open(RASTER)
    plain = readings_of(ds)
    ds = None
    check("and a map made elsewhere claims nothing", plain is None, plain)
    ws = method("write_stac", "CutoutsSection")
    check("the STAC item says it", '"rasterlabel:readings"' in ws)
    cc = method("cut_classes", "CutoutsSection")
    check("the classes of a cutout are cut in the type the map needs",
          "self.class_type(s)" in cc and ".astype(class_array(held))" in cc
          and "nan=0.0).astype(np.uint8)" not in cc)

    # --------------------------------------------------- closed, by reading
    print()
    print("a frame is closed by one reading, never by two added together")

    class Geom(object):
        def __init__(self, g_): self.g = g_
        @staticmethod
        def unaryUnion(pieces):
            out = pieces[0].g.Clone()
            for p in pieces[1:]:
                out = out.Union(p.g)
            return Geom(out)
        def intersection(self, other): return Geom(self.g.Intersection(other.g))
        def isEmpty(self): return self.g.IsEmpty()
        def area(self): return self.g.GetArea()
        def boundingBox(self):
            x0, x1, y0, y1 = self.g.GetEnvelope()
            return Box(x0, y0, x1, y1)

    class Box(object):
        def __init__(self, *v): self.v = v
        def xMinimum(self): return self.v[0]
        def yMinimum(self): return self.v[1]
        def xMaximum(self): return self.v[2]
        def width(self): return self.v[2] - self.v[0]

    class Point(object):
        def __init__(self, x, y): self._x, self._y = x, y
        def x(self): return self._x
        def y(self): return self._y

    class Feature(dict):
        def __init__(self, geom, **kw):
            dict.__init__(self, kw)
            self.g = geom
        def geometry(self): return self.g
        def hasGeometry(self): return self.g is not None
        def id(self): return 1

    class Field(object):
        def __init__(self, n): self.n = n
        def name(self): return self.n

    class Fields(list):
        def indexOf(self, n):
            return [f.name() for f in self].index(n)

    class Layer(object):
        def __init__(self, features=()):
            self.features = list(features)
            self.written = {}
        def fields(self): return Fields([Field("tile_id"), Field("side_m"),
                                         Field("closed")])
        def getFeatures(self): return iter(self.features)
        def isEditable(self): return True
        def startEditing(self): pass
        def changeAttributeValue(self, fid, index, value):
            self.written[self.fields()[index].name()] = value

    class Ruler(object):
        def measureLine(self, a, b): return math.hypot(b.x() - a.x(),
                                                       b.y() - a.y())

    class Measures(object):
        measure = Ruler()
        def area(self, x): return x.area()

    class AnnotationSection(object):
        OPERATOR_BLANK = g["OPERATOR_BLANK"]

    mns = {"QgsGeometry": Geom, "QgsPointXY": Point,
           "AnnotationSection": AnnotationSection,
           "CLOSED_SHARE": g["CLOSED_SHARE"]}
    for name in ("measure_tile", "operator_of", "pass_of"):
        exec(method(name, "AnnotationSection"), mns)

    class Section(object):
        operator_of = mns["operator_of"]
        pass_of = mns["pass_of"]

        def __init__(self, polygons):
            self.tile_layer = Layer()
            self.polygons = Layer(polygons)
            self.geometry = Measures()

    def closed(*marks):
        s = Section([Feature(Geom(ogr.CreateGeometryFromWkt(wkt)),
                             tile_id="t001", operator=who, pass_no=p)
                     for wkt, who, p in marks])
        frame = ogr.CreateGeometryFromWkt(columns(0, 100))
        mns["measure_tile"](s, Feature(Geom(frame), tile_id="t001"))
        return s.tile_layer.written.get("closed")

    check("ANNA sixty per cent and BRUNO sixty per cent, the rest of it: "
          "open", closed((columns(0, 60), "ANNA", 1),
                         (columns(40, 100), "BRUNO", 1)) == 0)
    check("ANNA all of it: closed",
          closed((columns(0, 60), "Anna", 1), (columns(60, 100), "ANNA", 1),
                 (columns(40, 100), "BRUNO", 1)) == 1)
    check("the same person in two cases and a pass left empty is one reading",
          closed((columns(0, 60), "anna", None),
                 (columns(60, 100), "ANNA ", 1)) == 1)
    check("one person in two passes is two readings",
          closed((columns(0, 60), "ANNA", 1),
                 (columns(60, 100), "ANNA", 2)) == 0)

    # With "one operator at a time" off, the brush and Fill Gap see every
    # operator of the pass and the coverage only the reading in hand. Where
    # the others painted the rest, the yellow line said "press Fill Gap",
    # and Fill Gap answered "no holes".
    print()
    print("the yellow line, when the rest of the frame is somebody else's")

    class Box_(object):
        def __init__(self, on): self.on = on
        def isChecked(self): return self.on

    class Step(object):
        text = ""
        def setText(self, t): Step.text = t

    class Panel(object):
        tiled = True
        class_name = "mud"
        others_fill_frame = None
        suggest = None
        operator_of = mns["operator_of"]

        def __init__(self, ticked, marks):
            self.by_operator = Box_(ticked)
            self.step = Step()
            self.geometry = Measures()
            self.scope = [Feature(Geom(ogr.CreateGeometryFromWkt(wkt)),
                                  operator=who) for wkt, who in marks]
        def tile_ids(self): return ["t001"]
        def current_tile_id(self): return "t001"
        def tile_geometry(self):
            return Geom(ogr.CreateGeometryFromWkt(columns(0, 100)))
        def operator_name(self): return "ANNA"
        def scope_polygons(self): return self.scope

    sns = {"QgsGeometry": Geom}
    for name in ("others_fill_frame", "suggest"):
        exec(method(name, "AnnotationSection"), sns)
    Panel.others_fill_frame = sns["others_fill_frame"]
    Panel.suggest = sns["suggest"]
    shared = [(columns(0, 60), "ANNA"), (columns(60, 100), "BRUNO")]
    p = Panel(False, shared)
    p.suggest(60.0, 1)
    check("box off, BRUNO painted the rest: it says so, and what to tick",
          "BRUNO's work" in Step.text
          and "one operator at a time" in Step.text
          and "Fill Gap</b> and finish" not in Step.text, Step.text)
    p = Panel(False, [(columns(0, 60), "ANNA"), (columns(60, 80), "BRUNO")])
    p.suggest(60.0, 1)
    check("with a gap left, Fill Gap has something to fill and is named",
          "Fill Gap" in Step.text and "BRUNO" not in Step.text, Step.text)
    p = Panel(True, shared[:1])
    p.suggest(60.0, 1)
    check("with the box ticked the others are not in the way",
          "BRUNO" not in Step.text and "Fill Gap" in Step.text, Step.text)

    # ------------------------------------------------- names in file names
    print()
    print("two readings never share a file name")
    tags = [c["tag"] for c in g["reading_choices"](
        {("ANNA B", 1): 1, ("ANNA_B", 1): 1, ("CONSENSUS", 1): 1})]
    check("names that tidy alike, or differ only in case from a consensus, "
          "get a number", len({t.lower() for t in tags}) == len(tags), tags)
    check("and the first of them keeps the plain name",
          "ANNA_B_p1" in tags and "ANNA_B_p1_2" in tags, tags)

    old = os.path.join(FOLDER, "old.gpkg")
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(old)
    lyr = ds.CreateLayer("polygons", None, ogr.wkbMultiPolygon)
    lyr.CreateField(ogr.FieldDefn("class_code", ogr.OFTInteger))
    for _ in range(3):
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetGeometry(ogr.CreateGeometryFromWkt(columns(0, 10)))
        lyr.CreateFeature(f)
    lyr = ds = None
    check("a package from before the operator and the pass: one reading",
          g["readings_in"](old) == {("UNNAMED", 1): 3},
          g["readings_in"](old))
    check("counted by SQLite every time, never walked feature by feature",
          not [m for m in said if "by SQL" in m],
          [m for m in said if "by SQL" in m])

    # ------------------------------------------- what the window says
    print()
    print("the line under the list of readings")
    dns = {"majority": g["majority"]}
    for name in ("_listed", "reading_note"):
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                exec("".join(lines[node.lineno - 1:node.end_lineno]), dns)
    note = dns["reading_note"]
    check("a consensus of two is the class both gave",
          "both readings" in note(by_tag["consensus_p1"], True)
          and "at least 2 of the 2" not in note(by_tag["consensus_p1"], True),
          note(by_tag["consensus_p1"], True))
    check("of four, three of them",
          "at least 3 of the 4 readings" in note(by_tag["consensus_all"],
                                                  False))
    said_all = note(choices[0], True)
    check("all together names every pass two operators share",
          "ANNA and BRUNO read pass 1" in said_all
          and "ANNA and BRUNO, pass 2" in said_all, said_all)

    print()
    print("a map of classes a PNG cannot hold goes out as GeoTIFF")
    path = os.path.join(FOLDER, "signed.png")
    gdal.PushErrorHandler("CPLQuietErrorHandler")
    try:
        g["put_raster"]("PNG", path, np.array([[[-1, 300]]], np.int16),
                        (OX, PX, 0, OY, 0, -PX), "", dtype=gdal.GDT_Int16)
        clamped = gdal.Open(path).ReadAsArray().tolist()
    finally:
        gdal.PopErrorHandler()
    check("(GDAL writes 16 signed bits into a PNG as bytes, clamped)",
          clamped != [[-1, 300]], clamped)
    cl = method("cut_layers", "CutoutsSection")
    check("so Cutouts sends such a map to GeoTIFF",
          'driver == "PNG"' in cl and "self.class_type(s) not in" in cl
          and 'shape_of("GTiff", s["role"])' in cl)
finally:
    shutil.rmtree(FOLDER, ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
