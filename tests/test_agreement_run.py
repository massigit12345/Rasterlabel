"""Compare two readings, for real: the frames, the maps, the tables.

The shared two-reader campaign of tests/fixtures/impact.py, a real
GeoPackage burned with real GDAL: ANNA and BRUNO read frame t001 whole with
the border between class 1 and class 2 two columns apart, BRUNO left t002
at 81 %, and t003 was touched by ANNA alone. Its hand values: N11 = 40,
N12 = 20, N22 = 40, Po 0.8, Pe 0.48, kappa 0.32 / 0.52, IoU 2/3 for both
classes, F1 (Dice) 0.8, quantity 0.2 and allocation 0.

What is checked:

- the plan: under "closed by both", t001 is compared, t002 is left out as
  "B 81.0 %" and t003 as "only A"; under "touched by both" t002 is in;
  two operators in one pass are "inter", one operator in two passes
  "intra";
- the report folder, reports/agreement/ANNA_p1_vs_BRUNO_p1_<stamp>, with
  nothing ending in .tmp left; a second run makes a second folder and
  leaves the first as it was; a run cancelled after its first frame
  leaves nothing at all;
- the numbers, pooled, against the hand values;
- the disagreement map: 20 pixels of code 2 in columns 4 and 5, 80 of
  code 1, on the campaign's own grid with no offset, its colours inside,
  its .qml beside it;
- the map of pairs: 1 + i*K + j over the codes [0, 1, 2], so (1, 2) is 6,
  and each pair read back is the class of each reading's own Whole raster
  mask ("one reading", scale 1) at that pixel;
- the GeoPackage: one polygon of disagreement, class 1 against 2, 20
  pixels, 0.05 m²; the frames with their numbers;
- the tables and summary.json: Q + A = 1 - Po, the frames used and left
  out are every frame either reading touched, version 1.1, the headline;
- a campaign with no frames is one region, with no interval and saying
  why; a code past the legend (300, an old campaign edited by hand) gets
  its pairs all the same and a name that says so; the points count only
  when asked;
- the GeoPackage of the campaign is only read.

Real GDAL, QGIS faked (correctkit with RL_KIT_REAL_GDAL).
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import io
import json
import os
import shutil
import sys
import tempfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import correctkit as K                                             # noqa: E402
import impact as F                                                 # noqa: E402
import numpy as np                                                 # noqa: E402
from osgeo import gdal, ogr                                        # noqa: E402

g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_agreement_run_")
ANNA, BRUNO = F.ANNA, F.BRUNO


def campaign(name, frames=None, marks=None, classes=None, tiled=True):
    folder = os.path.join(root, name)
    package = F.make_campaign(folder, F.GRID_AGREEMENT,
                              F.SHARED_FRAMES if frames is None else frames,
                              F.SHARED_MARKS if marks is None else marks,
                              classes=classes, name=name)
    path = os.path.join(folder, "campaign.json")
    with io.open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not tiled:
        data["with_tiles"] = False
        with io.open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    return folder, package, data


def run(folder, package, data, a=ANNA, b=BRUNO, rule="closed", points=False,
        n_boot=200, cancelled=None):
    plan = g["cmp_plan"](data, package, a, b, rule, points)
    return g["cmp_compare"]({"data": data, "folder": folder,
                             "package": package, "plan": plan,
                             "n_boot": n_boot, "seed": 1},
                            None, cancelled)


def band(path):
    ds = gdal.Open(path)
    out = ds.GetRasterBand(1).ReadAsArray(), ds.GetGeoTransform(), ds
    return out


def rows(path):
    with io.open(path, encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def reports_in(folder):
    base = os.path.join(folder, "reports", "agreement")
    return sorted(os.listdir(base)) if os.path.isdir(base) else []


print("the names of the maps")
# Made by report_artifact_name, which no longer cuts a name at 48 letters:
# the names Compare and Model vs corrected gave before are kept letter for
# letter, and two long readings no longer give two maps one name.
check("Compare's maps keep their names",
      g["cmp_files"]("aragona_2025", "ANNA_p1_vs_BRUNO_p1") == {
          "disagreement":
              "aragona_2025_agreement_ANNA_p1_vs_BRUNO_p1_disagreement.tif",
          "pairs": "aragona_2025_agreement_ANNA_p1_vs_BRUNO_p1_pairs.tif",
          "vectors": "aragona_2025_agreement_ANNA_p1_vs_BRUNO_p1.gpkg"},
      g["cmp_files"]("aragona_2025", "ANNA_p1_vs_BRUNO_p1"))
_long = g["cmp_files"]("aragona_2025_survey",
                       "FIRST_LONG_OPERATOR_p1_vs_SECOND_LONG_OPERATOR_p2")
check("two long readings: two names, each with its part",
      _long["disagreement"].endswith("_OPERATOR_p2_disagreement.tif")
      and _long["pairs"].endswith("_OPERATOR_p2_pairs.tif"), _long)
check("the map of Model vs corrected keeps its name",
      g["mvc_files"]("land cover.v2_corrected", "swept")
      == {"pairs": "land cover.v2_corrected_mvc_swept_pairs.tif"})

folder, package, data = campaign("shared")
before = (os.path.getsize(package), os.path.getmtime(package))

print("which frames")
plan = g["cmp_plan"](data, package, ANNA, BRUNO, "closed")
reasons = {x["tile_id"]: x["reason"] for x in plan["left_out"]}
check("closed by both: t001 is compared", plan["used"] == ["t001"],
      plan["used"])
check("t002 is left out with BRUNO's share", reasons.get("t002") ==
      "B 81.0 %", reasons)
check("t003, touched by ANNA alone, is left out as only A",
      reasons.get("t003") == "only A", reasons)
check("two operators in one pass: inter-observer", plan["kind"] == "inter")
check("BRUNO is unfinished on t002, ANNA on t003",
      [t for t, _ in plan["unfinished"]["B"]] == ["t002"]
      and [t for t, _ in plan["unfinished"]["A"]] == ["t003"],
      plan["unfinished"])
check("the counts the window shows", plan["counts"] ==
      {"closed": 1, "touched": 2}, plan["counts"])
check("the codes are unlabelled and the legend", plan["codes"] == [0, 1, 2],
      plan["codes"])
touched = g["cmp_plan"](data, package, ANNA, BRUNO, "touched")
check("touched by both: t002 is in too", touched["used"] == ["t001", "t002"],
      touched["used"])
same = g["cmp_plan"](data, package, ANNA, ANNA, "closed")
check("a reading against itself is refused", bool(same["refusal"]),
      same["refusal"])
check("the left-out line of the window",
      g["cmp_left_out_words"](plan) == "t002 (B 81.0 %), t003 (only A)",
      g["cmp_left_out_words"](plan))

print()
print("the report")
res = run(folder, package, data)
out = res["folder"]
check("in reports/agreement/ANNA_p1_vs_BRUNO_p1_<stamp>",
      os.path.dirname(out) == os.path.join(folder, "reports", "agreement")
      and os.path.basename(out).startswith("ANNA_p1_vs_BRUNO_p1_"), out)
check("and nothing ending in .tmp is left",
      not [n for n in reports_in(folder) if n.endswith(".tmp")],
      reports_in(folder))
o = res["summary"]["pooled"]["overall"]
check("overall agreement 0.8", abs(o["po"] - 0.8) < 1e-12, o["po"])
check("expected 0.48", abs(o["pe"] - 0.48) < 1e-12, o["pe"])
check("kappa 0.6154", abs(o["kappa"] - 0.32 / 0.52) < 1e-12, o["kappa"])
check("quantity 0.2, allocation 0", abs(o["quantity"] - 0.2) < 1e-12
      and abs(o["allocation"]) < 1e-12, (o["quantity"], o["allocation"]))
pc = {c["code"]: c for c in res["summary"]["pooled"]["per_class"]}
check("IoU 2/3 for both classes", all(abs(pc[c]["iou"] - 2 / 3.0) < 1e-12
                                      for c in (1, 2)))
check("F1 (Dice) 0.8 for both", all(abs(pc[c]["f1"] - 0.8) < 1e-12
                                    for c in (1, 2)))
check("seen from A: class 1 2/3, class 2 1; from B: 1 and 2/3",
      abs(pc[1]["rate_A"] - 40 / 60.0) < 1e-12 and pc[2]["rate_A"] == 1.0
      and pc[1]["rate_B"] == 1.0 and abs(pc[2]["rate_B"] - 40 / 60.0) < 1e-12)
check("one frame: no interval, and it says so",
      res["summary"]["bootstrap"]["ci"] is None
      and "fewer than 5 frames" in res["summary"]["bootstrap"]["reason"],
      res["summary"]["bootstrap"])

files = res["files"]
dis, gt, ds = band(os.path.join(out, files["disagreement"]))
check("the disagreement map is named for the campaign and the readings",
      files["disagreement"] == "shared_agreement_ANNA_p1_vs_BRUNO_p1_"
      "disagreement.tif", files)
check("20 pixels of disagreement, in columns 4 and 5",
      int((dis == 2).sum()) == 20 and bool((dis[:, 4:6] == 2).all()),
      np.argwhere(dis == 2)[:3])
check("and 80 of agreement", int((dis == 1).sum()) == 80)
check("on the campaign's grid, with no offset",
      tuple(gt) == (500000.0, 0.05, 0.0, 4140010.0, 0.0, -0.05), gt)
b1 = ds.GetRasterBand(1)
check("a byte, nodata 0, with its colours and names inside",
      b1.DataType == gdal.GDT_Byte and b1.GetNoDataValue() == 0
      and b1.GetColorTable() is not None
      and (b1.GetCategoryNames() or [""] * 3)[2] == "disagree")
meta = ds.GetMetadata()
check("and what it is, in its metadata",
      meta.get("RASTERLABEL_AGREEMENT_A") == "ANNA, pass 1"
      and meta.get("RASTERLABEL_AGREEMENT_KIND") == "inter"
      and meta.get("RASTERLABEL_FRAMES_RULE") == "closed"
      and meta.get("RASTERLABEL_VERSION") == "1.1", meta)
b1 = ds = None
check("with its .qml beside it", os.path.isfile(os.path.join(
    out, files["disagreement"][:-4] + ".qml")))
pairs, pgt, ds = band(os.path.join(out, files["pairs"]))
ds = None
check("the map of pairs: (1, 2) is 1 + 1*3 + 2 = 6, where they differ",
      bool((pairs[:, 4:6] == 6).all()) and int((pairs == 6).sum()) == 20)
check("(1, 1) is 5 and (2, 2) is 9", bool((pairs[:, :4] == 5).all())
      and bool((pairs[:, 6:] == 9).all()))
check("on the same grid", tuple(pgt) == tuple(gt))
check("and read back with cm_pair_of", g["cm_pair_of"](6, [0, 1, 2])
      == (1, 2))

print()
print("the very masks Whole raster writes")
ref = os.path.join(folder, "ortho.tif")
F._tif(ref, F.GRID_AGREEMENT, np.zeros((10, 30), np.uint8))
masks = {}
for r in (ANNA, BRUNO):
    path = os.path.join(root, "whole_%s.tif" % r[0])
    src = gdal.Open(ref)
    g["paint_whole"]({"ds": src, "scale": 1, "rgb": [1, 1, 1],
                      "limits": [(0, 1)] * 3, "alpha": 45, "colours": {},
                      "layer": None, "want_lines": False,
                      "want_points": False, "want_boxes": False,
                      "points_in_mask": False,
                      "outputs": [("mask", path, "GTiff")],
                      "package": package,
                      "reading": {"mode": "one", "readings": [r]}})
    src = None
    masks[r] = band(path)[0][:, :10]
decoded = np.vectorize(lambda v: g["cm_pair_of"](v, [0, 1, 2]) or (0, 0),
                       otypes=[object])(pairs)
a_back = np.array([[p[0] for p in row] for row in decoded])
b_back = np.array([[p[1] for p in row] for row in decoded])
check("A is ANNA's own mask, pixel for pixel",
      bool((a_back == masks[ANNA]).all()))
check("B is BRUNO's own mask, pixel for pixel",
      bool((b_back == masks[BRUNO]).all()))

print()
print("the GeoPackage")
vec = ogr.Open(os.path.join(out, files["vectors"]))
lyr = vec.GetLayerByName("disagreement")
feats = list(lyr)
check("one place of disagreement", len(feats) == 1, len(feats))
if feats:
    f = feats[0]
    check("class 1 of A against class 2 of B",
          f.GetField("kind") == "disagree" and f.GetField("code_A") == 1
          and f.GetField("code_B") == 2 and f.GetField("name_A") == "crater"
          and f.GetField("name_B") == "mud flow")
    check("20 pixels, 0.05 m²", f.GetField("pixels") == 20
          and abs(f.GetField("area_m2") - 0.05) < 1e-9,
          (f.GetField("pixels"), f.GetField("area_m2")))
frames = {f.GetField("tile_id"): f for f in vec.GetLayerByName("frames")}
check("the frames, used and left out", sorted(frames) ==
      ["t001", "t002", "t003"], sorted(frames))
check("t001 with its agreement", frames["t001"].GetField("used") == 1
      and abs(frames["t001"].GetField("overall") - 0.8) < 1e-9)
check("t002 left out, saying why", frames["t002"].GetField("used") == 0
      and frames["t002"].GetField("reason") == "B 81.0 %")
frames = feats = f = lyr = vec = None
check("each layer with its style beside it, once QGIS writes it: named",
      "shared_agreement_ANNA_p1_vs_BRUNO_p1_frames.qml"
      in res["written"], res["written"])

print()
print("the tables")
head = rows(os.path.join(out, "confusion.csv"))
check("confusion.csv: A \\ B, unlabelled first, codes and names",
      head[0] == ["A \\ B", "0 unlabelled", "1 crater", "2 mud flow"],
      head[0])
check("and the counts", head[1:4] == [["0 unlabelled", "0", "0", "0"],
                                      ["1 crater", "0", "40", "20"],
                                      ["2 mud flow", "0", "0", "40"]],
      head[1:4])
check("then the same in m²", any(r and r[0] == "A \\ B (m²)" for r in head))
long_rows = rows(os.path.join(out, "confusion_by_frame.csv"))
check("confusion_by_frame.csv, long, with the pooled one as ALL",
      long_rows[0] == ["tile_id", "code_A", "name_A", "code_B", "name_B",
                       "pixels", "area_m2"]
      and ["ALL", "1", "crater", "2", "mud flow", "20", "0.05"]
      in long_rows, long_rows[:4])
per_class = rows(os.path.join(out, "per_class.csv"))
check("per_class.csv names F1 f1 and the rates by reading",
      "f1" in per_class[0] and "agree_from_A" in per_class[0]
      and "dice" not in per_class[0], per_class[0])
per_frame = rows(os.path.join(out, "per_frame.csv"))
by = {r[0]: dict(zip(per_frame[0], r)) for r in per_frame[1:]}
check("per_frame.csv: every frame, with why it is left out",
      sorted(by) == ["t001", "t002", "t003"]
      and by["t003"]["reason"] == "only A" and by["t001"]["used"] == "1",
      by.keys())
pair_rows = rows(os.path.join(out, "pairs.csv"))
check("pairs.csv: the legend of the map of pairs, with the pixels",
      pair_rows[0][:6] == ["value", "a_code", "a_name", "b_code", "b_name",
                           "pixels"]
      and ["6", "1", "crater", "2", "mud flow", "20"] ==
      [x for x in pair_rows if x[0] == "6"][0][:6], pair_rows)
with io.open(os.path.join(out, "summary.json"), encoding="utf-8") as fh:
    summary = json.load(fh)
p = summary["pooled"]
check("summary.json: Q + A = 1 - Po", abs(p["quantity"] + p["allocation"]
                                          - (1 - p["overall"])) < 1e-12)
check("the frames used and left out are every frame either one touched",
      sorted(summary["frames"]["used"] + [x["tile_id"] for x in
                                          summary["frames"]["left_out"]])
      == ["t001", "t002", "t003"], summary["frames"])
check("version 1.1, kind agreement, the campaign as owner",
      summary["version"] == "1.1"
      and summary["rasterlabel:report"] == "agreement"
      and summary["owner"]["id"] == data["id"], summary["owner"])
check("the headline keys of the card", sorted(summary["headline"]) ==
      sorted(g["REPORT_HEADLINES"]["agreement"]), sorted(summary["headline"]))
check("kappa said to be agreement, not accuracy",
      any("not a measure of accuracy" in n for n in summary["notes"]))
check("the seed and the resamples are written down",
      summary["parameters"]["seed"] == 1
      and summary["parameters"]["resamples"] == 200)
# the styles of the two vector layers are written by QGIS, on its main
# thread, once the report is in place (ui_compare.compare_vector_styles)
missing = [n for n in summary["files"]
           if not os.path.exists(os.path.join(out, n))]
check("every file it lists is in the folder, the vector styles aside",
      sorted(missing) == ["shared_agreement_ANNA_p1_vs_BRUNO_p1_frames.qml",
                          "shared_agreement_ANNA_p1_vs_BRUNO_p1_polygons.qml"],
      missing)

print()
print("run again, cancelled, and read only")
first = reports_in(folder)
again = run(folder, package, data)
check("a second run is a second folder", again["folder"] != out
      and len(reports_in(folder)) == len(first) + 1, reports_in(folder))
check("and the first is left as it was",
      os.path.isfile(os.path.join(out, "summary.json")))
seen = []


def stop():
    seen.append(1)
    return True


try:
    run(folder, package, data, rule="touched", cancelled=stop)
    stopped = False
except g["CmpCancelled"]:
    stopped = True
check("Cancel after the first frame stops the run", stopped and
      len(seen) == 1, seen)
check("and leaves nothing behind it", reports_in(folder) ==
      sorted(first + [os.path.basename(again["folder"])]),
      reports_in(folder))
check("the campaign's GeoPackage is only read",
      (os.path.getsize(package), os.path.getmtime(package)) == before)

print()
print("one operator, two passes, and the points")
f2, p2, d2 = campaign("intra", marks=F.SHARED_MARKS[:2] + [
    ("polygons", ("ANNA", 2), 1, F.px_box(F.GRID_AGREEMENT, 0, 0, 4, 10)),
    ("polygons", ("ANNA", 2), 2, F.px_box(F.GRID_AGREEMENT, 4, 0, 10, 10)),
    ("points", ("ANNA", 2), 1, F.px_box(F.GRID_AGREEMENT, 5, 5, 6, 6))])
plan2 = g["cmp_plan"](d2, p2, ANNA, ("ANNA", 2), "closed")
check("ANNA p1 against ANNA p2 is intra-observer", plan2["kind"] == "intra")
r2 = run(f2, p2, d2, ANNA, ("ANNA", 2))
dis2 = band(os.path.join(r2["folder"], r2["files"]["disagreement"]))[0]
check("without the points, 20 pixels differ", int((dis2 == 2).sum()) == 20)
r3 = run(f2, p2, d2, ANNA, ("ANNA", 2), points=True)
dis3 = band(os.path.join(r3["folder"], r3["files"]["disagreement"]))[0]
check("with them, the point's pixel agrees: 19",
      int((dis3 == 2).sum()) == 19 and dis3[5, 5] == 1,
      int((dis3 == 2).sum()))

print()
print("no frames, and a code past the legend")
f4, p4, d4 = campaign("whole", frames=[], marks=[
    m[:4] + ("",) for m in F.SHARED_MARKS[:4]], tiled=False)
r4 = run(f4, p4, d4)
check("a campaign with no frames is one region",
      r4["ids"] == ["(whole)"], r4["ids"])
check("compared the same", abs(r4["summary"]["pooled"]["overall"]["po"]
                               - 0.8) < 1e-12)
check("no interval, and the report says why",
      r4["summary"]["bootstrap"]["ci"] is None
      and any("not a sample of frames" in n for n in r4["notes"]),
      r4["notes"])
f5, p5, d5 = campaign("legacy", marks=[
    ("polygons", ANNA, 300, F.px_box(F.GRID_AGREEMENT, 0, 0, 6, 10)),
    ("polygons", ANNA, 2, F.px_box(F.GRID_AGREEMENT, 6, 0, 10, 10)),
    ("polygons", BRUNO, 1, F.px_box(F.GRID_AGREEMENT, 0, 0, 4, 10)),
    ("polygons", BRUNO, 2, F.px_box(F.GRID_AGREEMENT, 4, 0, 10, 10))],
    frames=F.SHARED_FRAMES[:1])
r5 = run(f5, p5, d5)
check("a code past the legend is a code of its own",
      r5["codes"] == [0, 1, 2, 300], r5["codes"])
pairs5 = band(os.path.join(r5["folder"], r5["files"]["pairs"]))[0]
check("its pairs are written all the same: (300, 2) is 1 + 3*4 + 2 = 15",
      bool((pairs5[:, 4:6] == 15).all()), np.unique(pairs5))
with io.open(os.path.join(r5["folder"], "per_class.csv"),
             encoding="utf-8") as fh:
    check("and named as not in the legend",
          "code 300 (not in the legend)" in fh.read())

shutil.rmtree(root, ignore_errors=True)
sys.exit(K.finish())
