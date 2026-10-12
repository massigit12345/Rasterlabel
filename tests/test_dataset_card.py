"""The dataset card, counted for real: a campaign and a correction.

Real GDAL, real GeoPackages and GeoTIFFs, QGIS faked (correctkit with
RL_KIT_REAL_GDAL), the code read from the built single file. The fixtures
are small enough to be worked out by hand:

- A, a campaign on a 10 x 10 grid of 1 m pixels in UTM 33 N, one frame over
  all of it. ANNA in pass 1 drew class 1 on x 0-6 and class 2 on x 6-10;
  BRUNO in pass 1 class 1 on x 0-5 and class 2 on x 5-10, y 2-10; ANNA also
  dropped a point of class 2, 3 px across. By hand: ANNA 60 / 40, BRUNO
  50 / 40, every reading together (BRUNO drawn last wins) 52 / 48, and the
  consensus of pass 1 50 / 32, with 82 px agreed by 2 of 2 and 18 without a
  majority, 8 of them painted by both differently (x 5-6, y 2-10). ANNA
  closed the frame, BRUNO covered 90 % of it. The point is 9 px of
  footprint and changes no count, since points are not in the mask.
- B, the pixel centre: CARLO's polygon x 0-2.4 holds 2 pixels in its row,
  not 3. ALL_TOUCHED would add the third.
- D, a corrected 4 x 4 map, classes 1 above and 2 below; row 2, columns 0-2
  changed from 2 to 1 by MASSI in two strokes.

Also: the reports a card copies (agreement, time, model vs corrected) and
when they are marked as possibly stale; the same card twice is the same
bytes but for the date; an empty campaign, one with no coordinate system,
one whose reference raster has moved, a reading with no operator; a map in
16 bits with a code of 300; the files written beside the card and whether
their counts are the card's; the STAC fields and Item held against the
published label and projection schemas; and the Measure entries in both
blocks, the card written from them into reports/card/<stamp>/ with nothing
in the campaign or the correction changed.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import time

os.environ["RL_KIT_REAL_GDAL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fixtures"))
sys.path.insert(0, os.path.join(HERE, "fixtures", "stac"))
import correctkit as K                                             # noqa: E402
import impact as F                                                 # noqa: E402
import minischema                                                  # noqa: E402
import numpy as np                                                 # noqa: E402
from osgeo import gdal, ogr                                        # noqa: E402

g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_dataset_card_")
GRID = F.GRID_CARD
OX, OY = 500000.0, 4140000.0           # local x, y are metres from here
CLASSES = [{"code": 1, "name": "class 1", "colour": "#d95f02"},
           {"code": 2, "name": "class 2", "colour": "#1b9e77"}]
ANNA, BRUNO, CARLO = ("ANNA", 1), ("BRUNO", 1), ("CARLO", 1)
CONSENSUS = "consensus of pass 1: ANNA, BRUNO"


def box(x0, y0, x1, y1):
    return (OX + x0, OY + y0, OX + x1, OY + y1)


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def manifest(folder):
    with io.open(os.path.join(folder, "campaign.json"),
                 encoding="utf-8") as fh:
        return json.load(fh)


def make(name, marks, frames=None, classes=CLASSES, reference=True):
    folder = os.path.join(root, name)
    frames = [("F1", box(0, 0, 10, 10), True)] if frames is None else frames
    package = F.make_campaign(folder, GRID, frames, marks, classes=classes,
                              name=name, campaign_id=(name * 12)[:12])
    if reference:
        F._tif(os.path.join(folder, "ortho.tif"), GRID,
               np.zeros((10, 10), np.uint8))
    return folder, package, manifest(folder)


def set_point_size(package, n):
    ds = ogr.Open(package, 1)
    lyr = ds.GetLayerByName("points")
    for f in lyr:
        f.SetField("size_px", n)
        lyr.SetFeature(f)
    lyr = None
    ds = None


def by_label(card):
    return {p["label"]: p for p in card["products"]}


def ints(d):
    return {int(k): v for k, v in (d or {}).items()}


# ------------------------------------------------------------ fixture A
MARKS_A = [("polygons", ANNA, 1, box(0, 0, 6, 10)),
           ("polygons", ANNA, 2, box(6, 0, 10, 10)),
           ("polygons", BRUNO, 1, box(0, 0, 5, 10)),
           ("polygons", BRUNO, 2, box(5, 2, 10, 10)),
           ("points", ANNA, 2, box(7, 5, 8, 6))]
folder_a, package_a, data_a = make("aragona", MARKS_A)
set_point_size(package_a, 3)
before_sha = sha(package_a)
before_mtime = os.path.getmtime(package_a)
before_manifest = sha(os.path.join(folder_a, "campaign.json"))
ticks = []
card = g["card_gather_campaign"](
    data_a, folder_a, package_a,
    progress=lambda text, done, total: ticks.append((text, done, total)))
P = by_label(card)

print("fixture A: the readings")
rows = {(r["operator"], r["pass"]): r for r in card["readings"]}
check("two readings, in the order of reading_choices",
      [(r["operator"], r["pass"]) for r in card["readings"]]
      == [ANNA, BRUNO], card["readings"])
check("ANNA: 2 polygons and 1 point",
      rows[ANNA]["marks"] == {"polygons": 2, "lines": 0, "points": 1,
                              "boxes": 0}, rows[ANNA]["marks"])
check("BRUNO: 2 polygons", rows[BRUNO]["marks"]["polygons"] == 2
      and sum(rows[BRUNO]["marks"].values()) == 2, rows[BRUNO]["marks"])
counted = g["readings_in"](package_a)
check("the row totals are what readings_in finds",
      {r: sum(rows[r]["marks"].values()) for r in rows} == counted, counted)
check("ANNA's point stands for 9 px", rows[ANNA]["points_footprint_px"] == 9,
      rows[ANNA]["points_footprint_px"])
check("operators and passes", card["operators"] == ["ANNA", "BRUNO"]
      and card["passes"] == [1])
check("the tags are the file names' tags",
      [r["tag"] for r in card["readings"]] == ["ANNA_p1", "BRUNO_p1"])

print()
print("fixture A: the products, by hand")
check("the products are what Export and Whole raster offer",
      sorted(P) == sorted(["all readings together", "ANNA, pass 1",
                           "BRUNO, pass 1", CONSENSUS]), sorted(P))
check("ANNA, pass 1: 60 and 40", ints(P["ANNA, pass 1"]["counts"])
      == {1: 60, 2: 40}, P["ANNA, pass 1"]["counts"])
check("labelled 100, 60 m2 and 40 m2",
      P["ANNA, pass 1"]["labelled_px"] == 100
      and ints(P["ANNA, pass 1"]["m2"]) == {1: 60.0, 2: 40.0},
      P["ANNA, pass 1"]["m2"])
check("BRUNO, pass 1: 50 and 40, labelled 90",
      ints(P["BRUNO, pass 1"]["counts"]) == {1: 50, 2: 40}
      and P["BRUNO, pass 1"]["labelled_px"] == 90, P["BRUNO, pass 1"])
check("every reading together, BRUNO drawn last: 52 and 48",
      ints(P["all readings together"]["counts"]) == {1: 52, 2: 48},
      P["all readings together"]["counts"])
c = P[CONSENSUS]
check("the consensus of pass 1: 50 and 32", ints(c["counts"])
      == {1: 50, 2: 32}, c["counts"])
check("votes: 82 px by 2 of 2, 18 by none", ints(c["votes_histogram"])
      == {0: 18, 2: 82}, c["votes_histogram"])
check("painted by one reading 10 px, by both 90",
      ints(c["labelled_histogram"]) == {1: 10, 2: 90},
      c["labelled_histogram"])
check("18 px without a majority, 8 painted by both differently",
      c["no_majority_px"] == 18 and c["all_painted_disagree_px"] == 8,
      (c["no_majority_px"], c["all_painted_disagree_px"]))
check("shares 50/82 and 32/82",
      abs(ints(c["share"])[1] - 50 / 82.0) < 1e-6
      and abs(ints(c["share"])[2] - 32 / 82.0) < 1e-6, c["share"])
check("the window is the whole grid", c["window_px"] == [0, 0, 10, 10],
      c["window_px"])
check("the points change no count (points_in_mask off)",
      card["rules"]["points_in_mask"] is False
      and ints(P["ANNA, pass 1"]["counts"]) == {1: 60, 2: 40})

print()
print("fixture A: the frames")
fr = card["frames"]
check("one frame, closed as stored and as recomputed",
      fr["count"] == 1 and fr["closed_stored"] == 1
      and fr["closed_recomputed"] == 1 and fr["mismatches"] == [], fr)
one = fr["per_frame"][0]
check("ANNA covers all of it, BRUNO 90 %",
      one["readings"]["ANNA, pass 1"]["share_area"] == 1.0
      and abs(one["readings"]["BRUNO, pass 1"]["share_area"] - 0.9) < 1e-9,
      one["readings"])
check("100 px in the frame; ANNA painted 100, BRUNO 90",
      one["frame_px"] == 100
      and one["readings"]["ANNA, pass 1"]["painted_px"] == 100
      and one["readings"]["BRUNO, pass 1"]["painted_px"] == 90, one)
check("and per class in the frame",
      ints(one["readings"]["BRUNO, pass 1"]["counts"]) == {1: 50, 2: 40})
check("ANNA completes it, BRUNO only touches it",
      (rows[ANNA]["frames_complete"], rows[ANNA]["frames_touched"],
       rows[BRUNO]["frames_complete"], rows[BRUNO]["frames_touched"])
      == (1, 1, 0, 1))

print()
print("fixture A: the rules, the build, the grid, the package")
rules = card["rules"]
check("pixel rule centre", rules["pixel_rule"] == "centre")
check("the consensus sentence says n//2+1", "n//2+1" in rules["consensus"])
check("the closed sentence says 99.5%", "99.5%" in rules["closed"])
check("every reading together: the last drawn wins",
      "drawn last wins" in rules["all_readings"], rules["all_readings"])
check("version 1.1 and the build of the bundle",
      card["software"]["version"] == "1.1"
      and card["software"]["build"] == g["BUILD"], card["software"])
check("card_format 1, kind campaign",
      card["card_format"] == 1 and card["kind"] == "campaign")
grid = card["grid"]
check("the grid: EPSG:32633, origin, 1 m, 10 x 10",
      grid["crs"] == "EPSG:32633" and grid["origin"] == [500000.0, 4140010.0]
      and grid["pixel_crs"] == [1.0, 1.0] and grid["size_px"] == [10, 10]
      and grid["reference_present"] is True
      and grid["aligned_with_reference"] is True, grid)
check("its name", "UTM zone 33N" in grid["crs_label"]
      and "EPSG:32633" in grid["crs_label"], grid["crs_label"])
check("the package's SHA-256 and size",
      card["campaign"]["package_sha256"] == before_sha
      and card["campaign"]["package_bytes"] == os.path.getsize(package_a))
check("no folder of the machine in the card",
      card["campaign"]["folder"] == "aragona"
      and card["campaign"]["package"] == "annotation.gpkg"
      and grid["reference_raster"] == "ortho.tif")
check("the package is only read", sha(package_a) == before_sha
      and os.path.getmtime(package_a) == before_mtime)
check("and the manifest too",
      sha(os.path.join(folder_a, "campaign.json")) == before_manifest)
check("progress was told, with the reading in the words",
      any(t[0].startswith("ANNA, pass 1 (") for t in ticks)
      and ticks[-1][1] == ticks[-1][2], ticks[:3])
check("the legend holds every code drawn",
      card["codes_not_in_legend"] == [] and card["retired_with_marks"] == [])

print()
print("fixture A: strips of 3 rows give the same counts")
kept_rows = g["STRIP_ROWS"]
g["STRIP_ROWS"] = 3
try:
    again = g["card_gather_campaign"](data_a, folder_a, package_a)
finally:
    g["STRIP_ROWS"] = kept_rows
check("every product the same, burned in four strips",
      [p["counts"] for p in again["products"]]
      == [p["counts"] for p in card["products"]]
      and [p.get("votes_histogram") for p in again["products"]]
      == [p.get("votes_histogram") for p in card["products"]])

print()
print("fixture A: the STAC label fields")
stac = card["stac"]
props = stac["properties"]
check("they describe the consensus", stac["describes"] == CONSENSUS,
      stac["describes"])
check("label:overviews carry its counts",
      props["label:overviews"][0]["counts"]
      == [{"name": "class 1", "count": 50}, {"name": "class 2", "count": 32}],
      props["label:overviews"])
check("label:classes", props["label:classes"]
      == [{"name": None, "classes": [1, 2]}])
check("label:type raster, methods manual",
      props["label:type"] == "raster" and props["label:methods"] == ["manual"])
check("and the rasterlabel fields",
      props["rasterlabel:reading_mode"] == "consensus"
      and props["rasterlabel:readings"] == [["ANNA", 1], ["BRUNO", 1]]
      and "strict majority" in props["rasterlabel:reading_rule"]
      and props["rasterlabel:campaign_id"] == data_a["id"])
named = g["card_gather_campaign"](data_a, folder_a, package_a,
                                  describe={"mode": "one",
                                            "readings": [ANNA]})
check("describe names another product: ANNA's",
      named["stac"]["describes"] == "ANNA, pass 1"
      and named["stac"]["properties"]["label:overviews"][0]["counts"]
      == [{"name": "class 1", "count": 60}, {"name": "class 2", "count": 40}])

print()
print("the STAC Item beside a mask, against the published schemas")
print("  (read with %s)" % minischema.reader())
mask = os.path.join(root, "whole", "aragona_ortho_consensus_p1_mask.tif")
os.makedirs(os.path.dirname(mask))
gt = (500000.0, 1.0, 0.0, 4140010.0, 0.0, -1.0)
wkt = g["card_srs"]("EPSG:32633").ExportToWkt()
item = g["card_stac_item_for_mask"](card, mask, gt, 10, 10, wkt,
                                    votes_path=mask.replace("_mask",
                                                            "_votes"),
                                    card_name="aragona_card.json")
label_errors = minischema.validate(item, "label")
proj_errors = minischema.validate(item, "projection")
check("the Item holds against label v1.0.1", not label_errors, label_errors)
check("and against projection v1.1.0", not proj_errors, proj_errors)
ring = item["geometry"]["coordinates"][0]
check("the footprint is a closed ring running counter-clockwise, as GeoJSON "
      "(RFC 7946) asks of an exterior ring",
      len(ring) == 5 and ring[0] == ring[-1] and sum(
          a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:])) > 0,
      ring)
check("in longitude and latitude, near 15 E 37.4 N",
      14.9 < item["bbox"][0] < 15.1 and 37.3 < item["bbox"][1] < 37.5,
      item["bbox"])
check("proj:epsg 32633, shape 10 x 10",
      item["properties"]["proj:epsg"] == 32633
      and item["properties"]["proj:shape"] == [10, 10])
check("the mask is the labels asset, the votes metadata",
      item["assets"]["labels"]["roles"] == ["labels", "labels-raster"]
      and item["assets"]["labels"]["href"] == "./" + os.path.basename(mask)
      and item["assets"]["votes"]["roles"] == ["metadata"])
check("its counts are the card's",
      item["properties"]["label:overviews"] == props["label:overviews"])
check("label:overviews property_key is a string, as the schema wants",
      props["label:overviews"][0]["property_key"] == "class_code")
for what, change in (
        ("a null property_key", lambda p: p["label:overviews"][0].update(
            property_key=None)),
        ("a raster class with a name", lambda p: p["label:classes"][0]
         .update(name="classes")),
        ("an unknown label: field", lambda p: p.update({"label:count": 1})),
        ("a count that is not whole", lambda p: p["label:overviews"][0]
         ["counts"][0].update(count=1.5))):
    broken = json.loads(json.dumps(item))
    change(broken["properties"])
    check("the schema reader has teeth: %s is refused" % what,
          minischema.validate(broken, "label"))
broken = json.loads(json.dumps(item))
broken["properties"]["proj:shape"] = [10]
check("and so is a proj:shape of one number",
      minischema.validate(broken, "projection"))
written = g["card_write_mask_item"](card, mask, gt, 10, 10, wkt)
check("written beside the mask as <mask stem>.stac.json",
      written == os.path.join(os.path.dirname(mask),
                              "aragona_ortho_consensus_p1_mask.stac.json")
      and os.path.isfile(written))
check("the item's datetime is the card's moment",
      item["properties"]["datetime"].endswith("Z"))

print()
print("the files written beside the card")
consensus_mask = np.zeros((10, 10), np.uint8)
consensus_mask[:, 0:5] = 1                 # x 0-5, every row
consensus_mask[0:8, 6:10] = 2              # x 6-10, y 2-10: rows 0-7
F._tif(mask, GRID, consensus_mask)
votes = mask.replace("_mask", "_votes")
F._tif(votes, GRID, np.zeros((10, 10), np.uint8))
choice = {"mode": "consensus", "readings": [ANNA, BRUNO],
          "tag": "consensus_p1", "label": CONSENSUS}
exports = [{"path": mask, "role": "mask", "reading": choice, "scale": 1},
           {"path": votes, "role": "votes", "reading": choice, "scale": 1}]
withfiles = g["card_gather_campaign"](data_a, folder_a, package_a,
                                      exports=exports, describe=choice,
                                      where=os.path.dirname(mask))
e = withfiles["exports"]
check("each file with its role, SHA-256 and size, relative to the card",
      [x["role"] for x in e] == ["mask", "votes"]
      and e[0]["path"] == os.path.basename(mask)
      and e[0]["sha256"] == sha(mask)
      and e[0]["bytes"] == os.path.getsize(mask), e)
check("the mask holds the consensus counts: verified",
      e[0]["verified"] is True and ints(e[0]["counts_in_file"])
      == {1: 50, 2: 32}, e[0])
check("the votes are not a mask and are not verified",
      e[1]["verified"] is None)
tally = np.zeros(256, np.int64)
tally[1], tally[2] = 50, 32
by_tally = g["card_gather_campaign"](
    data_a, folder_a, package_a, where=os.path.dirname(mask),
    exports=[dict(exports[0], counts=tally)])
check("the tally paint_whole keeps is taken when given",
      by_tally["exports"][0]["verified"] is True)
wrong = consensus_mask.copy()
wrong[9, 9] = 1
F._tif(mask, GRID, wrong)
bad = g["card_gather_campaign"](data_a, folder_a, package_a,
                                exports=exports[:1])["exports"][0]
check("one pixel off: not verified, and the reason says which class",
      bad["verified"] is False and "1: 51 in the file, 50 counted"
      in bad["verified_reason"], bad)
F._tif(mask, GRID, consensus_mask)
coarse = g["card_gather_campaign"](
    data_a, folder_a, package_a,
    exports=[dict(exports[0], scale=2)])["exports"][0]
check("at scale 1:2: not verified, saying 1:2",
      coarse["verified"] is False and "1:2" in coarse["verified_reason"],
      coarse)
half = os.path.join(root, "whole", "left_half_mask.tif")
F._tif(half, dict(GRID, size=(5, 10)), consensus_mask[:, :5].copy())
left = g["card_gather_campaign"](
    data_a, folder_a, package_a,
    exports=[{"path": half, "role": "mask", "reading": choice,
              "scale": 1}])["exports"][0]
check("a mask of the left half: burned again over its extent, verified",
      left["verified"] is True and ints(left["counts_in_file"]) == {1: 50},
      left)
shifted = os.path.join(root, "whole", "shifted_mask.tif")
F._tif(shifted, dict(GRID, origin=(500000.5, 4140010.0)), consensus_mask)
off = g["card_gather_campaign"](
    data_a, folder_a, package_a,
    exports=[{"path": shifted, "role": "mask", "reading": choice,
              "scale": 1}])["exports"][0]
check("a mask half a pixel off the grid: not verified",
      off["verified"] is False and "another grid" in off["verified_reason"],
      off)

print()
print("the Markdown and the JSON")
out_a = os.path.join(root, "out_a")
os.makedirs(out_a)
md_path, js_path = g["card_write"](withfiles, out_a, "aragona")
md = io.open(md_path, encoding="utf-8").read()
lines = md.split("\n")
check("the class table, as the card prints it",
      "| code | class | ANNA p1 | BRUNO p1 | all | consensus p1 | "
      "share (consensus p1) |" in lines
      and "| 1 | class 1 | 60 | 50 | 52 | 50 | 61.0% |" in lines
      and "| 2 | class 2 | 40 | 40 | 48 | 32 | 39.0% |" in lines,
      [l for l in lines if l.startswith("|")][:4])
check("and the consensus line under it",
      "consensus p1: 82 px agreed by 2 of 2, 18 px without a majority (8 "
      "painted by both differently, 10 by one only)" in lines)
check("the files with their SHA-256",
      "| %s | mask | %s | yes |" % (os.path.basename(mask),
                                    sha(mask)) in lines
      and "| annotation.gpkg | package | %s |  |" % before_sha in lines,
      [l for l in lines if "mask" in l or "gpkg" in l])
check("the frames and the readings",
      "1 frame; 1 closed as stored, 1 as recomputed now." in lines
      and "| ANNA | 1 | 2 | 0 | 1 | 0 | 1 | 1 |" in lines)
check("what it does not say", "## What this card does not say" in lines
      and "- operator names are personal data" in lines
      and "- 0 inside a window is not counted as unlabelled ground" in lines)
check("the points are said to be outside the counts",
      any("points are not in these pixel counts" in l for l in lines))
js = json.load(io.open(js_path, encoding="utf-8"))
check("the JSON has the keys of card_format 1",
      {"card_format", "kind", "written", "software", "campaign", "grid",
       "rules", "classes", "codes_not_in_legend", "retired_with_marks",
       "readings", "operators", "passes", "frames", "products", "exports",
       "stac", "agreement", "time", "limits"} <= set(js), sorted(js))
check("UTF-8, LF, nothing left half written",
      b"\r" not in open(md_path, "rb").read()
      and b"\r" not in open(js_path, "rb").read()
      and not [f for f in os.listdir(out_a) if f.endswith(".partial")])

print()
print("the same card twice: the same bytes but for the date")
out_1, out_2 = os.path.join(root, "det_1"), os.path.join(root, "det_2")
os.makedirs(out_1)
os.makedirs(out_2)
c1 = g["card_gather_campaign"](data_a, folder_a, package_a)
c1["written"] = "2026-10-08T20:00:00"
m1, j1 = g["card_write"](c1, out_1, "aragona")
time.sleep(1.1)
c2 = g["card_gather_campaign"](data_a, folder_a, package_a)
m2, j2 = g["card_write"](c2, out_2, "aragona")
a_js = json.load(io.open(j1, encoding="utf-8"))
b_js = json.load(io.open(j2, encoding="utf-8"))
check("the dates differ", a_js["written"] != b_js["written"])
a_js.pop("written")
b_js.pop("written")
check("the JSON is the same once the date is taken out", a_js == b_js)
a_lines = io.open(m1, encoding="utf-8").read().split("\n")
b_lines = io.open(m2, encoding="utf-8").read().split("\n")
check("the Markdown differs on the date line alone",
      len(a_lines) == len(b_lines)
      and [i for i, (x, y) in enumerate(zip(a_lines, b_lines)) if x != y]
      == [2])
raw_1 = open(j1, "rb").read().replace(
    b'"written": "2026-10-08T20:00:00"', b'"written": "W"')
raw_2 = open(j2, "rb").read().replace(
    ('"written": "%s"' % c2["written"]).encode(), b'"written": "W"')
check("byte for byte, once the date is the same", raw_1 == raw_2)

print()
print("fixture B: by pixel centre")
folder_b, package_b, data_b = make(
    "centre", [("polygons", CARLO, 1, box(0, 9, 2.4, 10))])
card_b = g["card_gather_campaign"](data_b, folder_b, package_b)
pb = by_label(card_b)["CARLO, pass 1"]
check("x 0-2.4 holds 2 pixels, not 3", ints(pb["counts"]) == {1: 2},
      pb["counts"])
check("one reading: no consensus, and the STAC fields describe it",
      [p["mode"] for p in card_b["products"]] == ["all", "one"]
      and card_b["stac"]["describes"] == "CARLO, pass 1")

print()
print("feeds: the reports the card copies")
summary_a = g["report_header"]("agreement", {"kind": "campaign",
                                             "id": data_a["id"],
                                             "name": "aragona"})
summary_a["headline"] = {"A": "ANNA, pass 1", "B": "BRUNO, pass 1",
                         "kind": "inter", "frames_used": 1, "overall": 0.8,
                         "kappa": 0.6154, "quantity": 0.1, "allocation": 0.1,
                         "mean_iou": 0.66, "per_class_iou": {
                             "class 1": [0.8, None, None]}}
feed_dir = os.path.join(folder_a, "reports", "agreement", "x")
os.makedirs(feed_dir)
feed_path = os.path.join(feed_dir, "summary.json")
g["report_json"](feed_path, summary_a)
old = before_mtime - 3600
os.utime(feed_path, (old, old))
fed = g["card_gather_campaign"](data_a, folder_a, package_a)
check("the agreement report is copied", fed["agreement"] is not None
      and fed["agreement"]["headline"]["overall"] == 0.8, fed["agreement"])
check("from its source path",
      fed["agreement"]["source"] == "reports/agreement/x/summary.json",
      fed["agreement"]["source"])
check("older than the package, with no inputs recorded: may be stale",
      fed["agreement"]["stale"] is True, fed["agreement"])
md_fed = g["card_render_markdown"](fed)
check("and the Markdown says so", "may be stale" in md_fed
      and "## Agreement" in md_fed)
check("kappa only as an agreement statistic",
      "- kappa (agreement statistic): 0.6154" in md_fed)
check("the information box says so too",
      g["card_stale_lines"](fed) == [
          "The agreement report is older than the last change to the "
          "campaign: its numbers are marked as such."])
summary_a["inputs"] = g["report_inputs"]([package_a])
g["report_json"](feed_path, summary_a)
os.utime(feed_path, (old, old))
fresh = g["card_gather_campaign"](data_a, folder_a, package_a)
check("with the package's SHA-256 recorded and the same: not stale",
      fresh["agreement"]["stale"] is False, fresh["agreement"])
summary_a["inputs"][0]["sha256"] = "0" * 64
g["report_json"](feed_path, summary_a)
moved = g["card_gather_campaign"](data_a, folder_a, package_a)
check("with another SHA-256 recorded: stale", moved["agreement"]["stale"]
      and "changed" in moved["agreement"]["stale_reason"], moved["agreement"])
summary_a["owner"]["id"] = "somebodyelse"
g["report_json"](feed_path, summary_a)
other = g["card_gather_campaign"](data_a, folder_a, package_a)
check("made of another campaign: not copied", other["agreement"] is None)
check("and a note in the limits says why",
      any("another campaign" in l and "somebodyelse" in l
          for l in other["limits"]), other["limits"])
shutil.rmtree(os.path.join(folder_a, "reports"))
tdir = os.path.join(folder_a, "reports", "time", "20261008-1945")
os.makedirs(tdir)
summary_t = g["report_header"]("time", {"kind": "campaign",
                                        "id": data_a["id"]})
summary_t["headline"] = {"idle_s": 60, "active_h": 1.5,
                         "min_per_ha_scratch": 12.0}
summary_t["inputs"] = g["report_inputs"]([package_a])
g["report_json"](os.path.join(tdir, "time_summary.json"), summary_t)
timed = g["card_gather_campaign"](data_a, folder_a, package_a)
check("the time report, from time_summary.json",
      timed["time"] is not None and timed["time"]["headline"]["active_h"]
      == 1.5 and timed["time"]["source"].endswith("time_summary.json")
      and timed["time"]["stale"] is False, timed["time"])
check("with the keys fixed for it",
      sorted(timed["time"]["headline"]) == sorted(
          g["REPORT_HEADLINES"]["time"]))
shutil.rmtree(os.path.join(folder_a, "reports"))
check("with no reports at all, nothing is copied",
      g["card_gather_campaign"](data_a, folder_a, package_a)["agreement"]
      is None)

print()
print("edges")
folder_e, package_e, data_e = make("empty", [])
card_e = g["card_gather_campaign"](data_e, folder_e, package_e)
check("an empty package: no product", card_e["products"] == []
      and card_e["readings"] == [], card_e["products"])
md_e = g["card_render_markdown"](card_e)
check("and the Markdown says nothing drawn yet",
      "Nothing drawn yet" in md_e and "nothing drawn yet" in md_e)
check("its STAC fragment is there all the same, with zeros",
      card_e["stac"]["properties"]["label:overviews"][0]["counts"]
      == [{"name": "class 1", "count": 0}, {"name": "class 2", "count": 0}])
nocrs = json.loads(json.dumps(data_a))
nocrs["grid"]["crs"] = ""
card_n = g["card_gather_campaign"](nocrs, folder_a, package_a)
check("no coordinate system: crs is empty", card_n["grid"]["crs"] == ""
      and card_n["grid"]["crs_label"] == "")
check("the counts are the same", [p["counts"] for p in card_n["products"]]
      == [p["counts"] for p in card["products"]])
check("the STAC fragment is kept", card_n["stac"]["properties"] is not None)
photo = os.path.join(root, "photo", "photo_mask.tif")
os.makedirs(os.path.dirname(photo))
check("and no STAC Item is written",
      g["card_write_mask_item"](card_n, photo, gt, 10, 10, "") is None
      and not os.listdir(os.path.dirname(photo)))
check("the limits say so", any("no coordinate system" in l
                               for l in card_n["limits"]))
gone = json.loads(json.dumps(data_a))
gone["grid"]["reference_raster"] = os.path.join(root, "moved", "ortho.tif")
card_g = g["card_gather_campaign"](gone, folder_a, package_a)
check("the reference raster moved: size unknown",
      card_g["grid"]["size_px"] is None
      and card_g["grid"]["reference_present"] is False)
check("the windows are not clipped, and the counts are the same",
      [p["counts"] for p in card_g["products"]]
      == [p["counts"] for p in card["products"]])
check("and the card says it", any("is not there" in l
                                  for l in card_g["limits"]))
# a reference raster stored bottom row first: the same pixels on the same
# ground as the one above (its bottom edge is the grid's, 10 m below the top)
down = os.path.join(root, "north_down.tif")
ds_down = gdal.GetDriverByName("GTiff").Create(down, 10, 10, 1, gdal.GDT_Byte)
ds_down.SetGeoTransform((OX, 1.0, 0.0, OY, 0.0, 1.0))
ds_down.SetProjection(F._srs(GRID).ExportToWkt())
ds_down = None
flipped = json.loads(json.dumps(data_a))
flipped["grid"]["reference_raster"] = down
card_f = g["card_gather_campaign"](flipped, folder_a, package_a)
check("a reference raster stored bottom row first is on the grid of the "
      "campaign, and gives its size",
      card_f["grid"]["aligned_with_reference"] is True
      and card_f["grid"]["size_px"] == [10, 10], card_f["grid"])
check("the card does not say it is on another grid",
      not any("not on the grid" in l for l in card_f["limits"]),
      card_f["limits"])
check("and the counts are the same",
      [p["counts"] for p in card_f["products"]]
      == [p["counts"] for p in card["products"]],
      ([p["counts"] for p in card_f["products"]],
       [p["counts"] for p in card["products"]]))
folder_u, package_u, data_u = make(
    "unnamed", [("polygons", (None, None), 1, box(0, 0, 3, 3))])
card_u = g["card_gather_campaign"](data_u, folder_u, package_u)
check("a mark with no operator and no pass: UNNAMED, pass 1",
      [r["label"] for r in card_u["readings"]] == ["UNNAMED, pass 1"]
      and "UNNAMED, pass 1" in by_label(card_u), card_u["readings"])
folder_w, package_w, data_w = make(
    "past254", [("polygons", ANNA, 300, box(0, 0, 2, 2))])
card_w = g["card_gather_campaign"](data_w, folder_w, package_w)
check("a code past 254 (a manifest edited by hand): counted, and said",
      ints(by_label(card_w)["ANNA, pass 1"]["counts"]) == {300: 4}
      and card_w["codes_not_in_legend"] == [300]
      and any("past 254" in l for l in card_w["limits"]),
      (by_label(card_w)["ANNA, pass 1"]["counts"], card_w["limits"]))

print()
print("fixture D: a correction")
src = np.array([[1] * 4, [1] * 4, [2] * 4, [2] * 4], np.uint8)
cpy = src.copy()
cpy[2, 0:3] = 1
chg = np.zeros((4, 4), np.uint8)
chg[2, 0:3] = 1
ops = [{"n": 1, "when": "2026-10-08T10:00:00", "operator": "MASSI",
        "into": "class 1", "only": "class 2", "pixels": 2,
        "swept_m2": "4.000", "changed_m2": "2.000", "x": 0, "y": 0,
        "col": 0, "row": 2, "width": 2, "height": 1},
       {"n": 2, "when": "2026-10-08T10:01:00", "operator": "MASSI",
        "into": "class 1", "only": "class 2", "pixels": 1,
        "swept_m2": "3.000", "changed_m2": "1.000", "x": 0, "y": 0,
        "col": 2, "row": 2, "width": 1, "height": 1}]
folder_d = os.path.join(root, "correction_d")
paths = F.make_correction(folder_d, src, cpy, chg, ops)
book = {"program": "RasterLabel", "kind": "correction", "format": 1,
        "id": "beefbeefbeef", "name": "model_corr",
        "created": "2026-10-08T09:00:00", "operator": "MASSI",
        "operators": ["MASSI"], "source": paths["source"], "band": 1,
        "working_copy": os.path.basename(paths["copy"]),
        "changes": os.path.basename(paths["changes"]),
        "grid": {"crs": "EPSG:32633", "origin": [500000.0, 4140010.0],
                 "pixel_crs": [1.0, 1.0], "pixel_m": [1.0, 1.0],
                 "size": [4, 4]},
        "nodata": None, "classes": CLASSES, "operations": 2,
        "changed_m2": 3.0, "swept_m2": 7.0, "pairs": {}}
with io.open(os.path.join(folder_d, "correction.json"), "w",
             encoding="utf-8") as fh:
    json.dump(book, fh)
copy_sha = sha(paths["copy"])
card_d = g["card_gather_correction"](book, folder_d)
px = card_d["pixels"]
check("before 8 and 8", ints(px["before"]) == {1: 8, 2: 8}, px["before"])
check("after 11 and 5", ints(px["after"]) == {1: 11, 2: 5}, px["after"])
check("the change +3 and -3", ints(px["delta"]) == {1: 3, 2: -3})
check("3 px changed, 18.75 % of the map",
      px["changed_px"] == 3 and px["changed_share"] == 0.1875, px)
check("all of them from class 2 into class 1",
      px["changed_pairs_px"] == [{"from": 2, "to": 1, "px": 3, "m2": 3.0}],
      px["changed_pairs_px"])
op = card_d["operations"]
check("2 operations, both MASSI's", op["count"] == 2
      and op["by_operator"] == {"MASSI": 2}, op)
check("logged 3 m2 changed, measured 3 m2",
      op["changed_m2_logged"] == 3.0 and op["changed_m2_measured"] == 3.0)
check("7 m2 swept, 2.33 times what changed", op["swept_m2"] == 7.0
      and abs(op["swept_over_changed"] - 7 / 3.0) < 0.001, op)
check("the pairs of the log", op["pairs_logged"]
      == {"class 2 -> class 1": [2, 3.0]}, op["pairs_logged"])
check("first and last stroke", op["first"] == "2026-10-08T10:00:00"
      and op["last"] == "2026-10-08T10:01:00")
check("the bands of the map", card_d["correction"]["bands"][0]["type"]
      == "Byte" and card_d["correction"]["bands"][0]["band"] == 1)
check("the working copy's SHA-256", card_d["correction"]
      ["working_copy_sha256"] == copy_sha)
check("STAC: methods automated and manual, overviews the after counts",
      card_d["stac"]["properties"]["label:methods"] == ["automated", "manual"]
      and card_d["stac"]["properties"]["label:overviews"][0]["counts"]
      == [{"name": "class 1", "count": 11}, {"name": "class 2", "count": 5}])
check("the correction's STAC fields hold against label v1.0.1",
      not minischema.validate(
          {"type": "Feature", "stac_extensions": [g["LABEL_EXT"]],
           "properties": dict(card_d["stac"]["properties"],
                              datetime="2026-10-08T20:00:00Z"),
           "links": [], "assets": {}}, "label"))
md_d = g["card_render_markdown"](card_d)
check("the Markdown: before, after, change",
      "| 1 | class 1 | 8 | 11 | +3 |" in md_d
      and "| 2 | class 2 | 8 | 5 | -3 |" in md_d)
check("and the bands of the map", "## Bands of the map" in md_d)
check("the copy is only read", sha(paths["copy"]) == copy_sha)
logged = dict(book, changed_m2=5.0)
with io.open(paths["operations"], "a", encoding="utf-8") as fh:
    fh.write("3,2026-10-08T10:02:00,MASSI,class 1,class 2,2,2.000,2.000,"
             "0,0,0,3,2,1\n")
card_l = g["card_gather_correction"](logged, folder_d)
check("an undone stroke: the log and the record of changes differ, said",
      card_l["operations"]["changed_m2_logged"] == 5.0
      and any("undone strokes are not subtracted" in l
              for l in card_l["limits"]), card_l["limits"])
os.remove(paths["source"])
card_s = g["card_gather_correction"](book, folder_d)
check("the source deleted: before is null and the reason names it",
      card_s["pixels"]["before"] is None
      and "source" in card_s["pixels"]["before_reason"],
      card_s["pixels"]["before_reason"])
check("after unchanged", ints(card_s["pixels"]["after"]) == {1: 11, 2: 5})

folder_16 = os.path.join(root, "correction_16")
os.makedirs(folder_16)
wide = np.array([[1, 1, 300, 300], [1, 1, 300, 300], [2, 2, 2, 2],
                 [65535, 65535, 2, 2]], np.uint16)
ds = gdal.GetDriverByName("GTiff").Create(
    os.path.join(folder_16, "wide_corrected.tif"), 4, 4, 1, gdal.GDT_UInt16)
ds.SetGeoTransform((500000.0, 1.0, 0.0, 4140010.0, 0.0, -1.0))
ds.GetRasterBand(1).SetNoDataValue(65535)
ds.GetRasterBand(1).WriteArray(wide)
ds = None
book16 = dict(book, working_copy="wide_corrected.tif", changes="",
              source="", nodata=65535)
card_16 = g["card_gather_correction"](book16, folder_16)
check("16 bits: the code 300 is counted, the nodata 65535 is not",
      ints(card_16["pixels"]["after"]) == {1: 4, 2: 6, 300: 4},
      card_16["pixels"]["after"])
check("and no note about codes past 254: they are the map's own",
      not any("254" in l for l in card_16["limits"]), card_16["limits"])
check("the STAC fields name 300 with its count",
      {"name": "code 300", "count": 4} in card_16["stac"]["properties"]
      ["label:overviews"][0]["counts"])

mdir = os.path.join(folder_d, "reports", "model_vs_corrected",
                    "swept_20261008-2015")
os.makedirs(mdir)
summary_m = g["report_header"]("model_vs_corrected",
                               {"kind": "correction", "id": book["id"]})
summary_m["headline"] = {"scope": "swept", "pixels": 3, "oa": 0.778}
summary_m["inputs"] = g["report_inputs"]([paths["copy"]])
g["report_json"](os.path.join(mdir, "summary.json"), summary_m)
card_m = g["card_gather_correction"](book, folder_d)
check("the model vs corrected report is copied into the correction's card",
      card_m["model_vs_corrected"] is not None
      and card_m["model_vs_corrected"]["headline"]["oa"] == 0.778
      and card_m["model_vs_corrected"]["stale"] is False,
      card_m["model_vs_corrected"])
check("and has its section in the Markdown",
      "## Model vs corrected" in g["card_render_markdown"](card_m))
check("with no uncertainty or time report, none is copied",
      card_m["uncertainty"] is None and card_m["time"] is None)

print()
print("Measure ▸ Dataset card… in both blocks")
panel = g["Panel"]()
panel.update_enabled()


def entries(menu):
    menu.aboutToShow.emit()
    return [None if a.isSeparator() else (a.text(), a.isEnabled(),
                                          a.toolTip())
            for a in menu.actions()]


check("with nothing open, the card cannot be written",
      g["card_enabled_campaign"](panel) == (False, "Open a campaign first.")
      and g["card_enabled_correction"](panel)
      == (False, "Open a correction first."))
folder_ui, package_ui, data_ui = make("menu", MARKS_A)
camp = g["Campaign"](folder_ui)
camp.data = manifest(folder_ui)
panel.campaign = camp
panel._reading = {"campaign": camp.data["id"], "operator": "ANNA",
                  "pass": 1, "blind": True, "by_operator": False}
panel.update_enabled()
said = entries(panel.b_measure.menu())
by = {s[0]: s for s in said if s}
check("the campaign's menu holds Dataset card…, last, after a separator",
      said and said[-1] is not None and said[-1][0] == "Dataset card…"
      and said[-2] is None, said)
check("and it can be pressed", by["Dataset card…"][1], by.get("Dataset card…"))
check("the key's tooltip names it", "dataset card"
      in panel.b_measure.toolTip(), panel.b_measure.toolTip())
ui_manifest = sha(os.path.join(folder_ui, "campaign.json"))
ui_package = sha(package_ui)
K.BOXES[:] = []
done = g["card_start_campaign"](panel)
check("written into reports/card/<stamp>/",
      done is not None and os.path.dirname(done["folder"])
      == os.path.join(folder_ui, "reports", "card"), done and done["folder"])
check("as <stem>_card.md and <stem>_card.json",
      done is not None and sorted(os.listdir(done["folder"]))
      == ["menu_card.json", "menu_card.md"])
check("nothing left ending in .tmp", not [
    n for n in os.listdir(os.path.join(folder_ui, "reports", "card"))
    if n.endswith(".tmp")])
check("one information box, saying where and what it holds",
      [b[0] for b in K.BOXES] == ["information"]
      and K.BOXES[0][1].startswith("Dataset card written in ")
      and "menu_card.md and .json" in K.BOXES[0][1]
      and "2 readings, 1 consensus, 1 frame (1 closed)" in K.BOXES[0][1]
      and "Pixel counts on the campaign grid, by pixel centre."
      in K.BOXES[0][1], K.BOXES)
check("the manifest is neither written nor told",
      sha(os.path.join(folder_ui, "campaign.json")) == ui_manifest)
check("the package is only read", sha(package_ui) == ui_package)
panel._reading["by_operator"] = True
K.BOXES[:] = []
refused = g["card_start_campaign"](panel)
check("a reader kept from BRUNO's work is refused, with the card's words",
      refused is None and K.BOXES and K.BOXES[0][0] == "warning"
      and "The card would show it" in K.BOXES[0][1]
      and K.BOXES[0][1].endswith("then write the card."), K.BOXES)
check("and nothing more is written", len(os.listdir(
    os.path.join(folder_ui, "reports", "card"))) == 1)
panel._reading["by_operator"] = False

corr = g["CorrectionCampaign"](folder_d)
corr.data = json.loads(json.dumps(book))
corr.data["source"] = ""
panel.correction = corr
panel.update_enabled()
said = entries(panel.c_measure.menu())
check("the correction's menu holds Dataset card…, last, after a separator",
      said and said[-1] is not None and said[-1][0] == "Dataset card…"
      and said[-1][1] and said[-2] is None, said)
before_book = sha(os.path.join(folder_d, "correction.json"))
K.BOXES[:] = []
done_c = g["card_start_correction"](panel)
check("the correction's card in its reports/card/<stamp>/",
      done_c is not None and os.path.dirname(done_c["folder"])
      == os.path.join(folder_d, "reports", "card")
      and sorted(os.listdir(done_c["folder"]))
      == ["model_corr_card.json", "model_corr_card.md"], done_c)
check("and its box", K.BOXES and K.BOXES[0][0] == "information"
      and "3 px changed by hand (18.8% of the map), 3 operations"
      in K.BOXES[0][1], K.BOXES)
check("the correction's manifest is not touched",
      sha(os.path.join(folder_d, "correction.json")) == before_book)
corr.data["working_copy"] = "not_there.tif"
check("grey when the working copy is not there, saying why",
      g["card_enabled_correction"](panel)[0] is False
      and "not_there.tif" in g["card_enabled_correction"](panel)[1])

shutil.rmtree(root, ignore_errors=True)
sys.exit(K.finish())
