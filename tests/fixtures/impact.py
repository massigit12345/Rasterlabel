"""The campaigns and corrections the measuring suites are tried on.

Every measuring feature (agreement, time, the card, model vs corrected, the
ignore value) is checked on a campaign small enough to be worked out by
hand, and several of them on the same one, so the hand values are written
once, here, and not recomputed per suite. Real GDAL and real GeoPackages:
these are the fixtures of the suites in NEEDS_GDAL.

- make_campaign(folder, grid, frames, marks): a campaign folder, with
  campaign.json and annotation.gpkg in the schema the program writes (the
  TABLES of the built file, read out of it, so a column added there is a
  column here). grid is GRID_CARD or GRID_AGREEMENT or one like them;
  frames are (tile_id, bbox, closed); marks are (table, reading, class
  code, bbox), with a tile_id as a fifth item when it is not the frame the
  centre of the box falls in.
- make_shared_campaign(folder): the one two-reader campaign of the plan.
  ANNA p1 and BRUNO p1 both read frame t001 whole, with the border between
  class 1 and class 2 in a different column; BRUNO left t002 at 81 %; t003
  was touched by ANNA only. SHARED_VALUES holds what it is known to give.
- make_correction(folder, source_array, copy_array, changes, operations_rows):
  the files of a correction on the card grid: the map as it came, the
  working copy, the record of changes and operations.csv.
- write_journal(path, rows): a journal.csv, columns in JOURNAL_COLUMNS
  order, empty where a row says nothing.

bbox is (xmin, ymin, xmax, ymax) in the grid's system; px_box turns pixel
columns and rows of a grid into one.
"""
import ast
import csv
import io
import json
import os

from osgeo import gdal, ogr, osr

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(TESTS)
SRC = os.environ.get("RL_SRC") or os.path.join(ROOT, "dist", "rasterlabel.py")

# The grid of card fixture A: 1 m pixels, 10 x 10, UTM 33 N.
GRID_CARD = {"epsg": 32633, "origin": (500000.0, 4140010.0), "pixel": 1.0,
             "size": (10, 10)}
# The grid of agreement fixture B: the same corner, 0.05 m pixels, wide
# enough for three frames of 10 x 10 pixels side by side.
GRID_AGREEMENT = {"epsg": 32633, "origin": (500000.0, 4140010.0),
                  "pixel": 0.05, "size": (30, 10)}

CLASSES = [{"code": 1, "name": "crater", "colour": "#2a78d6"},
           {"code": 2, "name": "mud flow", "colour": "#eb6834"}]

ANNA = ("ANNA", 1)
BRUNO = ("BRUNO", 1)


def _lifted(names):
    """Top-level assignments of the built file, run with ogr in hand."""
    source = io.open(SRC, encoding="utf-8").read()
    lines = source.splitlines(True)
    space = {"ogr": ogr}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0],
                                                       ast.Name) \
                and node.targets[0].id in names:
            exec("".join(lines[node.lineno - 1:node.end_lineno]), space)
    return space


def tables():
    """TABLES and JOURNAL_COLUMNS as the built file has them."""
    space = _lifted({"DESIGN_TILE_COLUMNS", "TABLES", "JOURNAL_COLUMNS"})
    return space["TABLES"], space["JOURNAL_COLUMNS"]


def px_box(grid, c0, r0, c1, r1):
    """Pixel columns c0..c1 and rows r0..r1 (end not included) as a bbox."""
    ox, oy = grid["origin"]
    p = grid["pixel"]
    return (ox + c0 * p, oy - r1 * p, ox + c1 * p, oy - r0 * p)


def _ring(bbox):
    xmin, ymin, xmax, ymax = bbox
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in ((xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax),
                 (xmin, ymin)):
        ring.AddPoint_2D(x, y)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return poly


def _srs(grid):
    s = osr.SpatialReference()
    s.ImportFromEPSG(int(grid["epsg"]))
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def _inside(bbox, frame_bbox):
    cx, cy = (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0
    return frame_bbox[0] <= cx <= frame_bbox[2] \
        and frame_bbox[1] <= cy <= frame_bbox[3]


def make_campaign(folder, grid, frames, marks, classes=None, name="impact",
                  campaign_id="0123456789ab", schema=None):
    """A campaign folder; returns the path of its GeoPackage."""
    os.makedirs(folder, exist_ok=True)
    schema = schema or tables()[0]
    package = os.path.join(folder, "annotation.gpkg")
    srs = _srs(grid)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(package)
    layers = {}
    for table, kind, fields in schema:
        lyr = ds.CreateLayer(table, srs, kind, ["GEOMETRY_NAME=geom"])
        for fname, ftype in fields:
            d = ogr.FieldDefn(fname, ftype)
            if ftype == ogr.OFTString:
                d.SetWidth(80)
            lyr.CreateField(d)
        layers[table] = lyr
    p = grid["pixel"]
    for tile_id, bbox, closed in frames:
        lyr = layers["tiles"]
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("tile_id", tile_id)
        f.SetField("side_m", round(bbox[2] - bbox[0], 6))
        f.SetField("note", "")
        f.SetField("created", "2026-10-01T09:00:00")
        f.SetField("closed", 1 if closed else 0)
        f.SetGeometry(_ring(bbox))
        lyr.CreateFeature(f)
    by_code = {c["code"]: c["name"] for c in (classes or CLASSES)}
    for n, mark in enumerate(marks):
        table, reading, code, bbox = mark[:4]
        tile_id = mark[4] if len(mark) > 4 else next(
            (t for t, fb, _ in frames if _inside(bbox, fb)), None)
        lyr = layers[table]
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("class_name", by_code.get(code, "code %d" % code))
        f.SetField("class_code", int(code))
        if tile_id is not None:
            f.SetField("tile_id", tile_id)
        if reading[0] is not None:
            f.SetField("operator", reading[0])
        if reading[1] is not None:
            f.SetField("pass_no", int(reading[1]))
        f.SetField("created", "2026-10-01T10:%02d:00" % (n % 60))
        geom = _ring(bbox)
        if table == "polygons":
            multi = ogr.Geometry(ogr.wkbMultiPolygon)
            multi.AddGeometry(geom)
            geom = multi
        elif table == "points":
            c = geom.Centroid()
            geom = ogr.Geometry(ogr.wkbPoint)
            geom.AddPoint_2D(c.GetX(), c.GetY())
            f.SetField("size_px", 1)
        f.SetGeometry(geom)
        lyr.CreateFeature(f)
    layers = None
    ds = None
    data = {
        "program": "RasterLabel", "version": "1.1", "id": campaign_id,
        "name": name, "created": "2026-10-01T09:00:00",
        "operator": "ANNA", "operators": ["ANNA", "BRUNO"],
        "with_tiles": True, "classes": classes or CLASSES,
        "grid": {"reference_raster": os.path.join(folder, "ortho.tif"),
                 "crs": "EPSG:%d" % grid["epsg"],
                 "origin": list(grid["origin"]),
                 "pixel_crs": [p, p], "pixel_m": [p, p]},
        "layers": [], "tiles": [], "cutouts": [], "corrections": [],
        "journal": {"on": True, "file": "journal.csv", "version": 1,
                    "since": "2026-10-01T07:00:00Z"},
        "reports": []}
    with io.open(os.path.join(folder, "campaign.json"), "w",
                 encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return package


# The shared two-reader campaign, frames of 10 x 10 pixels at 0.05 m.
SHARED_FRAMES = [("t001", px_box(GRID_AGREEMENT, 0, 0, 10, 10), True),
                 ("t002", px_box(GRID_AGREEMENT, 10, 0, 20, 10), False),
                 ("t003", px_box(GRID_AGREEMENT, 20, 0, 30, 10), False)]
SHARED_MARKS = [
    # t001: ANNA class 1 in columns 0-5, class 2 in 6-9; BRUNO 0-3 and 4-9
    ("polygons", ANNA, 1, px_box(GRID_AGREEMENT, 0, 0, 6, 10)),
    ("polygons", ANNA, 2, px_box(GRID_AGREEMENT, 6, 0, 10, 10)),
    ("polygons", BRUNO, 1, px_box(GRID_AGREEMENT, 0, 0, 4, 10)),
    ("polygons", BRUNO, 2, px_box(GRID_AGREEMENT, 4, 0, 10, 10)),
    # t002: ANNA all of it, BRUNO 9 x 9 of the 10 x 10, 81 %
    ("polygons", ANNA, 1, px_box(GRID_AGREEMENT, 10, 0, 20, 10)),
    ("polygons", BRUNO, 1, px_box(GRID_AGREEMENT, 10, 0, 19, 9)),
    # t003: ANNA only, half of it
    ("polygons", ANNA, 2, px_box(GRID_AGREEMENT, 20, 0, 25, 10)),
]
SHARED_VALUES = {
    "shares": {"t001": {ANNA: 1.0, BRUNO: 1.0},
               "t002": {ANNA: 1.0, BRUNO: 0.81},
               "t003": {ANNA: 0.5}},
    "closed": {"t001": {ANNA, BRUNO}, "t002": {ANNA}, "t003": set()},
    # agreement on t001, pixels: rows ANNA, columns BRUNO, classes 1 and 2
    "t001_matrix": [[40, 20], [0, 40]],
    "t001_po": 0.8, "t001_pe": 0.48, "t001_kappa": 0.32 / 0.52,
    "t001_iou": [2 / 3, 2 / 3], "t001_dice": [0.8, 0.8],
    "t001_quantity": 0.2, "t001_allocation": 0.0,
    "pixel_m2": 0.0025,
}


def make_shared_campaign(folder):
    return make_campaign(folder, GRID_AGREEMENT, SHARED_FRAMES, SHARED_MARKS)


def _tif(path, grid, array, nodata=None):
    h, w = array.shape
    ds = gdal.GetDriverByName("GTiff").Create(path, w, h, 1, gdal.GDT_Byte)
    ox, oy = grid["origin"]
    p = grid["pixel"]
    ds.SetGeoTransform((ox, p, 0.0, oy, 0.0, -p))
    ds.SetProjection(_srs(grid).ExportToWkt())
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    band.WriteArray(array)
    band = None
    ds = None
    return path


def make_correction(folder, source_array, copy_array, changes=None,
                    operations_rows=(), grid=GRID_CARD, nodata=0,
                    stem="model"):
    """The files of a correction on the grid; returns their paths.

    changes is the 0/1 record of changed pixels; left out, it is where the
    copy differs from the source. operations_rows are dicts, written in the
    order of the keys of the first one."""
    import numpy as np
    os.makedirs(folder, exist_ok=True)
    src = np.asarray(source_array, dtype=np.uint8)
    cpy = np.asarray(copy_array, dtype=np.uint8)
    chg = (src != cpy).astype(np.uint8) if changes is None \
        else np.asarray(changes, dtype=np.uint8)
    paths = {"source": _tif(os.path.join(folder, stem + ".tif"), grid, src,
                            nodata),
             "copy": _tif(os.path.join(folder, stem + "_corrected.tif"),
                          grid, cpy, nodata),
             "changes": _tif(os.path.join(folder,
                                          stem + "_corrected_changes.tif"),
                             grid, chg)}
    rows = list(operations_rows)
    paths["operations"] = os.path.join(folder, "operations.csv")
    with io.open(paths["operations"], "w", encoding="utf-8",
                 newline="") as fh:
        if rows:
            out = csv.DictWriter(fh, fieldnames=list(rows[0]),
                                 lineterminator="\n")
            out.writeheader()
            for r in rows:
                out.writerow(r)
    return paths


def write_journal(path, rows):
    """A journal.csv: a header of JOURNAL_COLUMNS, then one line a row."""
    columns = tables()[1]
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        out = csv.writer(fh, lineterminator="\n")
        out.writerow(columns)
        for r in rows:
            out.writerow(["" if r.get(c) is None else r.get(c)
                          for c in columns])
    return path
