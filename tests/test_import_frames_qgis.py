"""Import frames with the sampling design, in a real QGIS.

The panel driven as a person drives it, the windows answered from here:

- a tiled campaign on a map of two classes (1 on the left half, 2 on the
  right), and an AcATaMa sample layer of twelve points with an id alone:
  the window guesses id for the sample id, the stratum is read from the
  map, and Import adds twelve frames, each with its sample id and its
  stratum (1 or 2, as the map says under it), no two of them overlapping;
  design_log.csv has twelve rows, the manifest one design whose counts say
  twelve added, and the box says so;
- the list of frames says the design of each in its tooltip, and the line
  under it the design of the frame in hand;
- the same file again: nothing would be added, Import is grey, and an
  import pressed all the same writes nothing;
- a frame of the design moved and another deleted: the delete question
  names the sample, and each writes its row; Check then says how many
  frames carry the design and gives one note;
- a second campaign: a draw half over a frame accepted before it and one
  off the map are refused and said (frame_clash and the raster's extent,
  through QGIS), and polygons keep their own side on the grid.

Needs QGIS; tests/run.py skips it where QGIS is missing and, with
RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qgiskit as K  # noqa: E402
import numpy as np  # noqa: E402
from osgeo import gdal, ogr  # noqa: E402
from qgis.PyQt.QtCore import Qt  # noqa: E402

g, check = K.g, K.check


def two_classes(path, nx=80, ny=60):
    """1 on the left half, 2 on the right, 1 m pixels, in UTM 33N."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    a = np.ones((ny, nx), np.uint8)
    a[:, nx // 2:] = 2
    ds = gdal.GetDriverByName("GTiff").Create(path, nx, ny, 1, gdal.GDT_Byte)
    ds.SetGeoTransform([K.X0, 1.0, 0, K.Y0, 0, -1.0])
    ds.SetProjection(K.UTM.ExportToWkt())
    ds.GetRasterBand(1).WriteArray(a)
    ds = None
    return path


def sample_file(path, features, kind=ogr.wkbPoint, fields=(("id",
                                                              ogr.OFTInteger),)):
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    lyr = ds.CreateLayer("sample", K.UTM, kind)
    for name, ftype in fields:
        lyr.CreateField(ogr.FieldDefn(name, ftype))
    for wkt, values in features:
        f = ogr.Feature(lyr.GetLayerDefn())
        for k, v in values.items():
            f.SetField(k, v)
        f.SetGeometry(ogr.CreateGeometryFromWkt(wkt))
        lyr.CreateFeature(f)
    ds = None
    return path


def tiles(package):
    con = sqlite3.connect(package)
    try:
        return [dict(zip(("tile_id", "sample_id", "stratum", "incl_prob",
                          "weight", "design", "note"), r))
                for r in con.execute(
                    "select tile_id, sample_id, stratum, incl_prob, weight, "
                    "design, note from tiles order by tile_id")]
    finally:
        con.close()


def log_rows(folder):
    path = os.path.join(folder, "design_log.csv")
    if not os.path.exists(path):
        return []
    with io.open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def manifest(folder):
    with io.open(os.path.join(folder, "campaign.json"), encoding="utf-8") as fh:
        return json.load(fh)


def choose_file(path):
    dialog = g["QFileDialog"]
    dialog.getOpenFileName = staticmethod(lambda *a, **k: (path, ""))


SEEN = {}


def answer(stratum_from=None, own=None, press=True):
    def setup(d):
        SEEN.clear()
        SEEN["mapping"] = {f: b.currentText() for f, b in d.combos.items()}
        SEEN["what"] = d.source_what.text()
        if stratum_from:
            box = d.combos["stratum"]
            i = box.findText("from raster: %s" % stratum_from)
            SEEN["raster_offered"] = i >= 0
            box.setCurrentIndex(i)
        if own is not None:
            (d.own_side if own else d.settings_side).setChecked(True)
        d.refresh()
        SEEN["preview"] = d.preview.text()
        SEEN["go"] = (d.go.text(), d.go.isEnabled(), d.go.toolTip())
        SEEN["own_enabled"] = d.own_side.isEnabled()
        return 1 if press else 0
    K.ANSWERS["ImportFrames"] = setup


root = tempfile.mkdtemp(prefix="rl_import_frames_")
try:
    data = os.path.join(root, "data")
    map_path = two_classes(os.path.join(data, "map_2024.tif"))
    classes = K.layer_of(map_path)
    panel = K.new_panel()
    camp = os.path.join(root, "camp")
    K.new_campaign(panel, camp, classes, tiled=True, name="design campaign")
    section = K.annotate(panel)
    section.tile_side.setValue(8.0)
    before = manifest(camp)
    check("opening writes no design_log.csv and no designs in the manifest",
          not os.path.exists(os.path.join(camp, "design_log.csv"))
          and "designs" not in before)

    print("an AcATaMa sample: twelve points, id alone")
    points = []
    for j in range(3):
        for i in range(4):
            points.append(("POINT(%r %r)" % (K.X0 + 10.0 + 20.0 * i,
                                              K.Y0 - 10.0 - 20.0 * j),
                           {"id": len(points) + 1}))
    acatama = sample_file(os.path.join(data, "draws_2024.gpkg"), points)
    choose_file(acatama)
    answer(stratum_from="map_2024.tif")
    section.import_tiles()
    check("the window guessed id for the sample id, nothing else",
          SEEN.get("mapping", {}).get("sample_id") == "id"
          and SEEN["mapping"]["incl_prob"] == "(none)", SEEN.get("mapping"))
    check("it said what the file is", SEEN.get("what", "").startswith(
        "12 points, EPSG:32633"), SEEN.get("what"))
    check("the map is offered for the stratum", SEEN.get("raster_offered"))
    check("points: the own side is grey", SEEN.get("own_enabled") is False)
    check("it said what would happen: 12 added from points",
          SEEN.get("preview", "").startswith(
              "12 added: 0 moved onto the grid, 0 resized, 12 from points"),
          SEEN.get("preview"))
    check("and the key read Import 12", SEEN.get("go", ("",))[0]
          == "Import 12", SEEN.get("go"))
    package = os.path.join(camp, "annotation.gpkg")
    rows = tiles(package)
    check("12 frames", len(rows) == 12, len(rows))
    check("each with its sample id", sorted(int(r["sample_id"]) for r in rows)
          == list(range(1, 13)), [r["sample_id"] for r in rows])
    check("the stratum read from the map: 1 on the left, 2 on the right",
          {r["stratum"] for r in rows} == {"1", "2"}
          and all(r["stratum"] == ("1" if (int(r["sample_id"]) - 1) % 4 < 2
                                   else "2") for r in rows),
          [(r["sample_id"], r["stratum"]) for r in rows])
    check("no probability and no weight invented",
          all(r["incl_prob"] is None and r["weight"] is None for r in rows))
    check('the note says the sample: "sample 1"',
          [r["note"] for r in rows if r["sample_id"] == "1"] == ["sample 1"])
    check("no two frames overlap",
          K.overlapping_pairs(section.tile_layer) == 0)
    logged = log_rows(camp)
    check("design_log.csv: 12 rows, all added, from points",
          len(logged) == 12 and all(r["outcome"] == "added"
                                    and r["reason"] == "from_point"
                                    for r in logged), len(logged))
    check("in the campaign's system, with the operator",
          logged and logged[0]["crs"] == "EPSG:32633"
          and logged[0]["operator"] == "ANNA"
          and logged[0]["source_file"] == "draws_2024.gpkg", logged[:1])
    data_now = manifest(camp)
    designs = data_now.get("designs") or []
    check("the manifest: one design, 12 added",
          len(designs) == 1 and designs[0]["counts"]["added"] == 12,
          designs)
    check("the mapping as chosen: id, and the stratum from the map",
          designs and designs[0]["mapping"]["sample_id"] == "id"
          and designs[0]["mapping"]["stratum"] == "raster:map_2024.tif"
          and designs[0]["log"] == "design_log.csv"
          and designs[0]["id"] == logged[0]["import_id"], designs[:1])
    info = [t for k, t in K.BOXES if k == "information"]
    check("the box: 12 frames added, design_log.csv lists all 12",
          info and info[-1].startswith("12 frames added, 0 already there, "
                                       "0 refused.")
          and "lists all 12 features of draws_2024.gpkg" in info[-1],
          info[-1:])

    print()
    print("the list of frames says the design")
    tip = section.tiles.itemData(0, Qt.ItemDataRole.ToolTipRole)
    check("in the tooltip of each frame", tip and tip.startswith("sample "),
          tip)
    section.select_tile("t001")
    check("and under the list, for the frame in hand",
          section.design_line.isVisibleTo(section)
          and section.design_line.text() == "sample 1 · stratum 1",
          section.design_line.text())

    print()
    print("the same file again")
    answer(stratum_from="map_2024.tif")
    section.import_tiles()
    check("nothing would be added: Import is grey and says why",
          SEEN.get("go", ("", True, ""))[1] is False
          and "nothing in this file would become a new frame"
          in SEEN["go"][2] and "12 already there" in SEEN.get("preview", ""),
          SEEN.get("go"))
    check("pressed all the same, it writes nothing",
          len(log_rows(camp)) == 12
          and len(manifest(camp).get("designs") or []) == 1
          and len(tiles(package)) == 12)

    print()
    print("a frame of the design moved, another deleted")
    moving = [f for f in section.all_tiles() if f["tile_id"] == "t002"][0]
    section.move_tile(moving, 2.0, 0.0)
    moved = [r for r in log_rows(camp) if r["event"] == "move"]
    check("the move is written: t002, 2 px", len(moved) == 1
          and moved[0]["tile_id"] == "t002" and moved[0]["shift_px"] == "2"
          and moved[0]["sample_id"] == "2", moved)
    section.select_tile("t003")
    K.CLICK.append("Delete tile")
    section.delete_tile()
    check("the question names the sample", K.ASKED and
          "This frame is sample 3 of the imported design" in K.ASKED[-1],
          K.ASKED[-1:])
    gone = [r for r in log_rows(camp) if r["event"] == "delete"]
    check("the delete is written: one row, t003, no frame after",
          len(gone) == 1 and gone[0]["tile_id"] == "t003"
          and gone[0]["frame_xmin"] == "" and gone[0]["outcome"] == "deleted",
          gone)
    found = g["design_findings"](panel.campaign)
    levels = [f.level for f in found]
    check("Check: 11 frames carry a sample of 1 imported design",
          found and found[0].what == "11 frames carry a sample of 1 imported "
          "design", [f.what for f in found])
    check("and one note, the frames moved and deleted after the import",
          levels.count("note") == 1
          and "1 moved and 1 deleted" in found[-1].what,
          [(f.level, f.what) for f in found])
    text, bad, notes = g["report"](panel.campaign, None,
                                   more=panel.more_checks())
    check("in the report Check shows", "frames of an imported design were "
          "1 moved and 1 deleted after the import" in text)
    panel.close_module()
    panel.close_campaign()

    print()
    print("a second campaign: refusals through QGIS, and polygons")
    camp2 = os.path.join(root, "camp2")
    K.new_campaign(panel, camp2, classes, tiled=True, name="second")
    section = K.annotate(panel)
    section.tile_side.setValue(8.0)
    three = sample_file(os.path.join(data, "three.gpkg"), [
        ("POINT(%r %r)" % (K.X0 + 10.0, K.Y0 - 10.0), {"id": 1}),
        ("POINT(%r %r)" % (K.X0 + 12.0, K.Y0 - 10.0), {"id": 2}),
        ("POINT(%r %r)" % (K.X0 + 500.0, K.Y0 - 10.0), {"id": 3})])
    choose_file(three)
    answer()
    section.import_tiles()
    check("1 added, 1 refused over it, 1 off the map",
          "1 added" in SEEN.get("preview", "")
          and "1 refused: overlap with t001" in SEEN["preview"]
          and "1 refused: outside the raster" in SEEN["preview"],
          SEEN.get("preview"))
    logged = log_rows(camp2)
    check("all three in the log, the refusals with their reasons",
          [(r["outcome"], r["reason"].split(";")[0], r["other_tile"])
           for r in logged] == [("added", "from_point", ""),
                                ("refused", "overlap", "t001"),
                                ("refused", "outside_raster", "")], logged)
    found = g["design_findings"](panel.campaign)
    check("Check: 2 draws never became frames",
          any(f.level == "note" and f.what.startswith(
              "2 draws of three.gpkg never became frames")
              for f in found), [f.what for f in found])
    sq = "POLYGON((%r %r,%r %r,%r %r,%r %r,%r %r))"

    def square(x, y, s):
        return sq % (x, y, x + s, y, x + s, y + s, x, y + s, x, y)

    polys = sample_file(os.path.join(data, "plots.gpkg"), [
        (square(K.X0 + 40.0, K.Y0 - 30.0, 7.0), {"plot_id": "P1"}),
        (square(K.X0 + 60.3, K.Y0 - 30.0, 7.0), {"plot_id": "P2"})],
        kind=ogr.wkbPolygon, fields=(("plot_id", ogr.OFTString),))
    choose_file(polys)
    answer(own=True)
    section.import_tiles()
    check("polygons square on the grid: each keeps its own side",
          SEEN.get("own_enabled") is True and SEEN.get("preview", "")
          .startswith("2 added: 1 moved onto the grid, 0 resized"),
          SEEN.get("preview"))
    rows = tiles(os.path.join(camp2, "annotation.gpkg"))
    px_m = section.geometry.pixel_m[0]
    check("P1 and P2 are frames of 7 px, their side on the ground as "
          "create_tile writes it",
          [r["sample_id"] for r in rows if r["sample_id"]] == ["1", "P1",
                                                               "P2"]
          and [round(f["side_m"] / px_m, 9) for f in section.all_tiles()
               if f["sample_id"] in ("P1", "P2")] == [7.0, 7.0],
          [(f["tile_id"], f["sample_id"], f["side_m"])
           for f in section.all_tiles()])
    check("still no two frames overlap",
          K.overlapping_pairs(section.tile_layer) == 0)
    check("the manifest of the second campaign has its two designs",
          len(manifest(camp2).get("designs") or []) == 2)
    print()
    print("tiles written by an earlier build from a REAL column")
    # R and pandas write every id as a double, and an earlier build kept the
    # text of the double: 12.0. The same file imported again writes 12, and
    # must find the frames it put there, not put a second set over them.
    panel.close_module()
    panel.close_campaign()
    camp3 = os.path.join(root, "camp3")
    K.new_campaign(panel, camp3, classes, tiled=True, name="third")
    section = K.annotate(panel)
    section.tile_side.setValue(8.0)
    real = sample_file(os.path.join(data, "real_ids.gpkg"), [
        ("POINT(%r %r)" % (K.X0 + 10.0, K.Y0 - 10.0), {"id": 12.0}),
        ("POINT(%r %r)" % (K.X0 + 30.0, K.Y0 - 10.0), {"id": 13.0})],
        fields=(("id", ogr.OFTReal),))
    choose_file(real)
    answer()
    section.import_tiles()
    package3 = os.path.join(camp3, "annotation.gpkg")
    check("a REAL column is written as 12 and 13, not 12.0 and 13.0",
          sorted(r["sample_id"] for r in tiles(package3)) == ["12", "13"],
          tiles(package3))
    lyr = section.tile_layer
    if not lyr.isEditable():
        lyr.startEditing()
    at = lyr.fields().indexOf("sample_id")
    for f in lyr.getFeatures():
        lyr.changeAttributeValue(f.id(), at, f["sample_id"] + ".0")
    check("(the frames as the earlier build wrote them)",
          lyr.commitChanges(), lyr.commitErrors())
    lyr.startEditing()
    check("they hold 12.0 and 13.0 now",
          sorted(r["sample_id"] for r in tiles(package3)) == ["12.0", "13.0"],
          tiles(package3))
    made = len(log_rows(camp3))
    answer()
    section.import_tiles()
    check("the same file again: both are already there, nothing would be "
          "added and Import is grey",
          "2 already there" in SEEN.get("preview", "")
          and SEEN.get("go", ("", True, ""))[1] is False, SEEN)
    check("pressed all the same, no frame is added or written over",
          len(tiles(package3)) == 2 and len(log_rows(camp3)) == made
          and sorted(r["sample_id"] for r in tiles(package3))
          == ["12.0", "13.0"], tiles(package3))
    check("and the manifest has the one design",
          len(manifest(camp3).get("designs") or []) == 1)

    check("nobody was asked anything unexpected", not K.UNEXPECTED,
          K.UNEXPECTED)
    K.close_panel(panel)
finally:
    shutil.rmtree(root, ignore_errors=True)
K.finish()
