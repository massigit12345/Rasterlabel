"""The sampling design in a real GeoPackage, with real GDAL.

- An older package, whose tiles table has the five columns of 1.1 and two
  frames, gets the five design columns when the campaign is opened
  (prepare_package), and nothing else: the two frames come back as they
  were, with an empty design.
- The files a sample comes in, written by ogr with the column names their
  makers give: spsurvey's grts written with sf::st_write (siteID, stratum,
  wgt, ip, in a GeoJSON), sampling::strata (ID_unit, Stratum, Prob, in a
  shapefile) and an AcATaMa sample layer (id alone, points in a
  GeoPackage). The columns are guessed from them, the units planned on the
  grid, the frames written through ogr into the tiles table, and read back
  with frame_design: the probability and the weight as REAL, the sample
  id and the stratum as TEXT, the values as given.
- design_log.csv has a row for every feature of each file.

The code is lifted out of the built file, as written. Needs GDAL; tests/
run.py skips it where the bindings are missing and, with
RL_REQUIRE_GDAL=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import csv
import io
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import purekit  # noqa: E402

ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
SRC = os.environ.get("RL_SRC") or os.path.join(ROOT, "dist", "rasterlabel.py")
source = io.open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)

fails = []


def check(name, cond, detail=""):
    cond = bool(cond)
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if not cond else ""))
    if not cond:
        fails.append(name)


WANTED = {"DESIGN_FIELDS", "DESIGN_TILE_COLUMNS", "TABLES", "Campaign",
          "frame_design", "_package_read", "_field_of", "now", "tidy",
          "long_path"}
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
SRS = osr.SpatialReference()
SRS.ImportFromEPSG(32633)
SRS.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
g = {"os": os, "re": re, "json": json, "gdal": gdal, "ogr": ogr,
     "osr": osr, "datetime": datetime, "timezone": timezone,
     "log": lambda m, loud=False: said.append(str(m)),
     "spatial_reference": lambda crs: SRS}
exec("\n".join(pieces), g)
rl = purekit.load("design")

O, P = (500000.0, 4200000.0), (0.5, 0.5)
EXTENT = (500000.0, 4199500.0, 500500.0, 4200000.0)
OLD_TILES = ("tile_id", "side_m", "note", "created", "closed")


def old_package(path):
    """A package as 1.1 wrote it before the design: every table, the tiles
    without the five design columns, two frames."""
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    for table, kind, fields in g["TABLES"]:
        lyr = ds.CreateLayer(table, SRS, kind, ["GEOMETRY_NAME=geom"])
        for fname, ftype in fields:
            if table == "tiles" and fname not in OLD_TILES:
                continue
            d = ogr.FieldDefn(fname, ftype)
            if ftype == ogr.OFTString:
                d.SetWidth(80)
            lyr.CreateField(d)
        if table == "tiles":
            for i, (x, y) in enumerate(((500010, 4199980),
                                        (500030, 4199980))):
                f = ogr.Feature(lyr.GetLayerDefn())
                f.SetField("tile_id", "t%03d" % (i + 1))
                f.SetField("side_m", 10.0)
                f.SetField("note", "by hand")
                f.SetField("created", "2026-10-01T10:00:00")
                f.SetField("closed", 0)
                f.SetGeometry(ogr.CreateGeometryFromWkt(
                    "POLYGON((%f %f,%f %f,%f %f,%f %f,%f %f))"
                    % (x, y, x + 10, y, x + 10, y + 10, x, y + 10, x, y)))
                lyr.CreateFeature(f)
    ds = None


def tiles_rows(path):
    ds = ogr.Open(path, 0)
    lyr = ds.GetLayerByName("tiles")
    defn = lyr.GetLayerDefn()
    names = [defn.GetFieldDefn(i).GetName()
             for i in range(defn.GetFieldCount())]
    kinds = {defn.GetFieldDefn(i).GetName():
             defn.GetFieldDefn(i).GetTypeName()
             for i in range(defn.GetFieldCount())}
    rows = []
    for f in lyr:
        rows.append({n: (f.GetField(n) if f.IsFieldSetAndNotNull(n)
                         else None) for n in names})
        rows[-1]["_bbox"] = f.GetGeometryRef().GetEnvelope()
    ds = None
    return rows, kinds


def write_source(path, driver, fields, features, kind):
    """A sample file as its maker writes it: fields [(name, ogr type)],
    features [(wkt or None, {name: value})]."""
    drv = ogr.GetDriverByName(driver)
    if os.path.exists(path):
        drv.DeleteDataSource(path)
    ds = drv.CreateDataSource(path)
    lyr = ds.CreateLayer("sample", SRS, kind)
    for name, ftype in fields:
        lyr.CreateField(ogr.FieldDefn(name, ftype))
    for wkt, values in features:
        f = ogr.Feature(lyr.GetLayerDefn())
        for k, v in values.items():
            f.SetField(k, v)
        if wkt:
            f.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
        lyr.CreateFeature(f)
    ds = None


def read_units(path):
    """The units of a file as the import reads them: fid, kind, bounding
    box, columns, parts. What import_read_rows does with QGIS, with ogr."""
    ds = ogr.Open(path, 0)
    lyr = ds.GetLayer(0)
    defn = lyr.GetLayerDefn()
    names = [defn.GetFieldDefn(i).GetName()
             for i in range(defn.GetFieldCount())]
    rows = []
    for f in lyr:
        geom = f.GetGeometryRef()
        kind, bbox, parts = "none", None, 1
        if geom is not None and not geom.IsEmpty():
            flat = ogr.GT_Flatten(geom.GetGeometryType())
            kind = {ogr.wkbPoint: "point", ogr.wkbMultiPoint: "point",
                    ogr.wkbLineString: "line",
                    ogr.wkbMultiLineString: "line",
                    ogr.wkbPolygon: "polygon",
                    ogr.wkbMultiPolygon: "polygon"}.get(flat, "none")
            x0, x1, y0, y1 = geom.GetEnvelope()
            bbox = (x0, y0, x1, y1)
            if flat in (ogr.wkbMultiPolygon, ogr.wkbMultiPoint,
                        ogr.wkbMultiLineString):
                parts = geom.GetGeometryCount()
        rows.append({"fid": f.GetFID(), "kind": kind, "bbox": bbox,
                     "transform_ok": True, "parts": parts,
                     "attrs": {n: (f.GetField(n) if f.IsFieldSetAndNotNull(n)
                                   else None) for n in names}})
    ds = None
    return rows, names


def existing_of(path):
    rows, _ = tiles_rows(path)
    out = []
    for r in rows:
        x0, x1, y0, y1 = r["_bbox"]
        out.append({"tile_id": r["tile_id"], "bbox": (x0, y0, x1, y1),
                    "design": {f: r.get(f) for f in rl.DESIGN_FIELDS}})
    return out


def write_frames(path, decisions):
    """The frames a plan adds, written into the tiles table through ogr:
    what import_tiles writes through QGIS."""
    ds = ogr.Open(path, 1)
    lyr = ds.GetLayerByName("tiles")
    for d in decisions:
        if d["outcome"] != "added":
            continue
        x0, y0, x1, y1 = d["frame"]
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("tile_id", d["tile_id"])
        f.SetField("side_m", d["frame_side_px"] * P[0])
        v = d["values"]
        f.SetField("note", "sample %s" % v["sample_id"] if v["sample_id"]
                   else "imported")
        f.SetField("closed", 0)
        for field in rl.DESIGN_FIELDS:
            if v.get(field) is not None:
                f.SetField(field, v[field])
        f.SetGeometry(ogr.CreateGeometryFromWkt(
            "POLYGON((%r %r,%r %r,%r %r,%r %r,%r %r))"
            % (x0, y0, x1, y0, x1, y1, x0, y1, x0, y0)))
        lyr.CreateFeature(f)
    ds = None


root = tempfile.mkdtemp(prefix="rl_design_package_")
try:
    print("an older package gets the five columns, and nothing else")
    camp = os.path.join(root, "camp")
    os.makedirs(camp)
    package = os.path.join(camp, "annotation.gpkg")
    old_package(package)
    before, _ = tiles_rows(package)
    added = g["Campaign"](camp).prepare_package(None)
    check("prepare_package adds tiles.sample_id, stratum, incl_prob, weight "
          "and design", added == ["tiles.sample_id", "tiles.stratum",
                                  "tiles.incl_prob", "tiles.weight",
                                  "tiles.design"], added)
    after, kinds = tiles_rows(package)
    check("the two frames come back as they were",
          [{k: r[k] for k in OLD_TILES} for r in after]
          == [{k: r[k] for k in OLD_TILES} for r in before], after)
    check("with every design field empty", all(
        r[f] is None for r in after for f in rl.DESIGN_FIELDS))
    check("incl_prob and weight are REAL, the others TEXT",
          (kinds["incl_prob"], kinds["weight"], kinds["sample_id"],
           kinds["stratum"], kinds["design"])
          == ("Real", "Real", "String", "String", "String"), kinds)
    check("a second open adds nothing", g["Campaign"](camp).prepare_package(
        None) == [])
    check("frame_design lists no frame placed by hand",
          g["frame_design"](package) == {})

    print()
    print("spsurvey's grts, written with sf::st_write as GeoJSON")
    sps = os.path.join(root, "grts.geojson")
    sq = "POLYGON((%r %r,%r %r,%r %r,%r %r,%r %r))"

    def square(x, y, s=10.0):
        return sq % (x, y, x + s, y, x + s, y + s, x, y + s, x, y)

    write_source(sps, "GeoJSON",
                 [("siteID", ogr.OFTString), ("siteuse", ogr.OFTString),
                  ("replsite", ogr.OFTString), ("stratum", ogr.OFTString),
                  ("wgt", ogr.OFTReal), ("ip", ogr.OFTReal)],
                 [(square(500100, 4199900), {"siteID": "Site-01",
                                             "siteuse": "Base",
                                             "stratum": "forest",
                                             "wgt": 20.0, "ip": 0.05}),
                  (square(500120.2, 4199900.2), {"siteID": "Site-02",
                                                 "siteuse": "Base",
                                                 "stratum": "crop",
                                                 "wgt": 12.5, "ip": 0.08}),
                  (square(500105, 4199900), {"siteID": "Site-03",
                                             "siteuse": "Over",
                                             "stratum": "forest",
                                             "wgt": 20.0, "ip": 0.05}),
                  (None, {"siteID": "Site-04", "stratum": "crop",
                          "wgt": 12.5, "ip": 0.08})],
                 ogr.wkbPolygon)
    units, names = read_units(sps)
    mapping = rl.design_guess_mapping(names)
    check("guessed: siteID, stratum, ip, wgt",
          mapping == {"sample_id": "siteID", "stratum": "stratum",
                      "incl_prob": "ip", "weight": "wgt", "design": None},
          mapping)
    decisions = rl.design_plan(units, existing_of(package),
                               inside=rl.design_inside_box(EXTENT),
                               settings_side_px=20, own_side=True, origin=O,
                               pixel=P, mapping=mapping,
                               design_typed="GRTS, spsurvey 5")
    counts = rl.design_summary(decisions)
    check("2 added, 1 overlap, 1 with no geometry",
          (counts["added"], counts["overlap"], counts["no_geometry"])
          == (2, 1, 1), counts)
    check("numbered after the frames there: t003, t004",
          [d["tile_id"] for d in decisions if d["outcome"] == "added"]
          == ["t003", "t004"])
    write_frames(package, decisions)
    design = g["frame_design"](package)
    check("frame_design reads both back", sorted(design) == ["t003", "t004"],
          sorted(design))
    t3 = design.get("t003", {})
    check("the probability and the weight as numbers, as given",
          isinstance(t3.get("incl_prob"), float)
          and t3.get("incl_prob") == 0.05 and t3.get("weight") == 20.0, t3)
    check("the sample id and the stratum as text",
          t3.get("sample_id") == "Site-01" and t3.get("stratum") == "forest",
          t3)
    check("the design typed", t3.get("design") == "GRTS, spsurvey 5")
    t4 = design.get("t004", {})
    check("Site-02 on the grid, 0.2 m off: moved onto it",
          t4.get("sample_id") == "Site-02"
          and "snapped" in [d for d in decisions if d["tile_id"] == "t004"][
              0]["reasons"], t4)
    rows, _ = tiles_rows(package)
    check("the note says the sample",
          [r["note"] for r in rows if r["tile_id"] == "t003"]
          == ["sample Site-01"])
    log_path = rl.design_log_path(camp)
    rl.design_append_log(log_path, rl.design_log_rows(
        decisions, "aa11bb22", "2026-10-09T12:00:00", "ANNA",
        rl.design_source_name(sps), "EPSG:32633"))
    again = rl.design_plan(units, existing_of(package),
                           inside=rl.design_inside_box(EXTENT),
                           settings_side_px=20, own_side=True, origin=O,
                           pixel=P, mapping=mapping,
                           design_typed="GRTS, spsurvey 5")
    c2 = rl.design_summary(again)
    check("the same file again: 2 already there, nothing added",
          c2["added"] == 0 and c2["already_there"] == 2, c2)

    print()
    print("sampling::strata, written as a shapefile")
    shp = os.path.join(root, "strata.shp")
    write_source(shp, "ESRI Shapefile",
                 [("ID_unit", ogr.OFTInteger), ("Stratum", ogr.OFTInteger),
                  ("Prob", ogr.OFTReal)],
                 [("POINT(%r %r)" % (500300 + 20 * i, 4199700),
                   {"ID_unit": 17 + i, "Stratum": 1 + i % 2,
                    "Prob": 0.025}) for i in range(3)],
                 ogr.wkbPoint)
    units, names = read_units(shp)
    mapping = rl.design_guess_mapping(names)
    check("guessed: ID_unit, Stratum, Prob",
          (mapping["sample_id"], mapping["stratum"], mapping["incl_prob"])
          == ("ID_unit", "Stratum", "Prob"), mapping)
    decisions_shp = rl.design_plan(units, existing_of(package),
                                   inside=rl.design_inside_box(EXTENT),
                                   settings_side_px=20, origin=O, pixel=P,
                                   mapping=mapping)
    write_frames(package, decisions_shp)
    design = g["frame_design"](package)
    t5 = design.get("t005", {})
    check("points: 3 frames of the Settings side, from points",
          rl.design_summary(decisions_shp)["added"] == 3
          and all("from_point" in d["reasons"] for d in decisions_shp))
    check("an integer id and stratum carried as text, the probability as "
          "a number", t5.get("sample_id") == "17" and t5.get("stratum")
          == "1" and t5.get("incl_prob") == 0.025, t5)
    check("no weight is worked out from the probability",
          t5.get("weight") is None)
    rl.design_append_log(log_path, rl.design_log_rows(
        decisions_shp, "cc33dd44", "2026-10-09T12:05:00", "ANNA",
        rl.design_source_name(shp), "EPSG:32633"))

    print()
    print("an AcATaMa sample layer: points, id alone")
    aca = os.path.join(root, "acatama.gpkg")
    write_source(aca, "GPKG", [("id", ogr.OFTInteger)],
                 [("POINT(%r %r)" % (500300 + 20 * i, 4199600),
                   {"id": i + 1}) for i in range(4)],
                 ogr.wkbPoint)
    units, names = read_units(aca)
    mapping = rl.design_guess_mapping(names)
    check("guessed: id, and nothing else",
          mapping == {"sample_id": "id", "stratum": None, "incl_prob": None,
                      "weight": None, "design": None}, mapping)
    check("fid is never offered as the sample id", "fid" not in [
        n.lower() for n in names] or mapping["sample_id"] != "fid")
    decisions_aca = rl.design_plan(units, existing_of(package),
                                   inside=rl.design_inside_box(EXTENT),
                                   settings_side_px=20, origin=O, pixel=P,
                                   mapping=mapping,
                                   stratum_of=lambda x, y: 1 if x < 500330
                                   else 2)
    check("the stratum read from the map at each frame",
          [d["values"]["stratum"] for d in decisions_aca]
          == ["1", "1", "2", "2"],
          [d["values"]["stratum"] for d in decisions_aca])
    check("incl_prob and weight left empty, and said nowhere as a fault",
          all(d["values"]["incl_prob"] is None
              and d["values"]["weight"] is None
              and not any(r.startswith("bad_value") for r in d["reasons"])
              for d in decisions_aca))
    rl.design_append_log(log_path, rl.design_log_rows(
        decisions_aca, "ee55ff66", "2026-10-09T12:10:00", "ANNA",
        rl.design_source_name(aca), "EPSG:32633"))

    print()
    print("design_log.csv")
    back = list(csv.DictReader(io.open(log_path, encoding="utf-8",
                                       newline="")))
    check("a row for every feature of the three files: 4 + 3 + 4",
          len(back) == 11, len(back))
    check("each file under its own import",
          [r["import_id"] for r in back].count("aa11bb22") == 4
          and [r["source_file"] for r in back].count("strata.shp") == 3)
    nogeom = [r for r in back if r["sample_id"] == "Site-04"]
    check("the unit with no geometry is there, refused, with its sample id",
          nogeom and nogeom[0]["outcome"] == "refused"
          and nogeom[0]["reason"] == "no_geometry", nogeom)
    raw = io.open(log_path, "rb").read()
    check("UTF-8 without a BOM, \\n line ends",
          not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw)
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
