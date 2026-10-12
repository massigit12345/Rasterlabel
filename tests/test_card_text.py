"""The dataset card as text: the rules, the STAC fields, the Markdown.

The counts of a card come from burning the readings on the campaign grid,
which needs GDAL and has a suite of its own. What is checked here is the
part after the counting, handed the numbers of fixture A:
ANNA and BRUNO in pass 1 on one 10 x 10 frame,

    ANNA, pass 1        class 1: 60  class 2: 40
    BRUNO, pass 1       class 1: 50  class 2: 40
    all readings        class 1: 52  class 2: 48   (BRUNO drawn last wins)
    consensus of pass 1 class 1: 50  class 2: 32   82 px agreed by 2 of 2,
                        18 without a majority, 8 of them painted by both
                        differently and 10 by one only

and of fixture D, a corrected 4 x 4 map. The class table must read exactly
in its fixed layout, the STAC overviews must carry those counts and no
others, a report fed into the card is marked "may be stale" when what it
was made from has changed, and writing the same card twice gives the same
files but for the date.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import io
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purekit

rl = purekit.load("reports", "card")
t = purekit.Checks()

classes = [{"code": 1, "name": "class 1", "colour": "#d95f02"},
           {"code": 2, "name": "class 2", "colour": "#1b9e77"},
           {"code": 3, "name": "old", "colour": "#000000", "retired": True}]
data = {"id": "c0ffee123456", "name": "aragona_2025", "classes": classes}
consensus = {"mode": "consensus", "label": "consensus of pass 1: ANNA, BRUNO",
             "tag": "consensus_p1", "readings": [["ANNA", 1], ["BRUNO", 1]],
             "counts": {1: 50, 2: 32}, "labelled_px": 82,
             "votes_histogram": {0: 18, 2: 82},
             "labelled_histogram": {1: 10, 2: 90}, "no_majority_px": 18,
             "all_painted_disagree_px": 8}
products = [
    {"mode": "one", "label": "ANNA, pass 1", "tag": "ANNA_p1",
     "readings": [["ANNA", 1]], "counts": {1: 60, 2: 40}, "labelled_px": 100},
    {"mode": "one", "label": "BRUNO, pass 1", "tag": "BRUNO_p1",
     "readings": [["BRUNO", 1]], "counts": {1: 50, 2: 40}, "labelled_px": 90},
    {"mode": "all", "label": "all readings together", "tag": "all",
     "readings": [["ANNA", 1], ["BRUNO", 1]], "counts": {1: 52, 2: 48},
     "labelled_px": 100},
    consensus]


def card_a(written="2026-10-08T20:00:00"):
    return {"card_format": 1, "kind": "campaign", "written": written,
            "software": {"name": "RasterLabel", "version": "1.1",
                         "build": rl.BUILD},
            "campaign": {"name": "aragona_2025", "id": data["id"]},
            "grid": {"crs": "EPSG:32633", "crs_label": "EPSG:32633",
                     "origin": [500000.0, 4140010.0],
                     "pixel_crs": [1.0, 1.0], "pixel_m": [1.0, 1.0]},
            "rules": rl.card_rules(points_in_mask=False,
                                   all_rule="the last drawn wins"),
            "classes": classes, "products": products,
            "readings": [{"operator": "ANNA", "pass": 1,
                          "marks": {"polygons": 2, "points": 1},
                          "frames_complete": 1, "frames_touched": 1},
                         {"operator": "BRUNO", "pass": 1,
                          "marks": {"polygons": 2}, "frames_complete": 0,
                          "frames_touched": 1}],
            "frames": {"count": 1, "closed_stored": 1,
                       "closed_recomputed": 1, "mismatches": []},
            "stac": {"describes": consensus["label"]},
            "limits": rl.card_limits("campaign")}


print("the rules as sentences")
rules = rl.card_rules()
t.ok("pixel rule centre", rules["pixel_rule"] == "centre")
t.ok("the consensus sentence says n//2+1", "n//2+1" in rules["consensus"])
t.ok("the closed sentence says 99.5%", "99.5%" in rules["closed"],
     rules["closed"])
t.ok("unlabelled 0, codes 1-254, 255 reserved",
     (rules["unlabelled_value"], rules["class_codes"],
      rules["reserved_value"]) == (0, "1-254", 255))

print()
print("the STAC label fields of the consensus")
stac = rl.card_stac_label_fields(consensus, classes, data,
                                 reading_rule="strict majority")
t.ok("label:overviews carry the counts of the consensus",
     stac["label:overviews"][0]["counts"] == [
         {"name": "class 1", "count": 50}, {"name": "class 2", "count": 32}],
     stac["label:overviews"])
t.ok("label:classes the codes in use, the retired one left out",
     stac["label:classes"] == [{"name": None, "classes": [1, 2]}])
t.ok("label:type raster, methods manual, task segmentation",
     stac["label:type"] == "raster" and stac["label:methods"] == ["manual"]
     and stac["label:tasks"] == ["segmentation"])
t.ok("the description names the campaign and the pixel rule",
     "aragona_2025" in stac["label:description"]
     and "pixel centre" in stac["label:description"])
t.ok("and how the counts were made", stac["rasterlabel:pixel_rule"]
     == "centre" and stac["rasterlabel:campaign_id"] == data["id"]
     and stac["rasterlabel:version"] == "1.1"
     and stac["rasterlabel:reading_mode"] == "consensus")
t.ok("a class of the legend with no pixel is there with 0",
     rl.card_stac_label_fields({"counts": {1: 7}}, classes, data)
     ["label:overviews"][0]["counts"][1] == {"name": "class 2", "count": 0})

print()
print("the GeoTIFF tags")
tags = rl.card_provenance_metadata(data, "/x/aragona_2025_card.json")
t.ok("build, campaign id, pixel rule, unlabelled, card name",
     tags == {"RASTERLABEL_BUILD": rl.BUILD,
              "RASTERLABEL_CAMPAIGN_ID": data["id"],
              "RASTERLABEL_PIXEL_RULE": rl.PIXEL_RULE_TEXT,
              "RASTERLABEL_UNLABELLED": "0",
              "RASTERLABEL_CARD": "aragona_2025_card.json"}, tags)
t.ok("the pixel rule starts with centre",
     tags["RASTERLABEL_PIXEL_RULE"].startswith("centre"))
t.ok("no card, no card tag",
     "RASTERLABEL_CARD" not in rl.card_provenance_metadata(data))

print()
print("the Markdown")
md = rl.card_render_markdown(card_a())
lines = md.split("\n")
t.ok("the title", lines[0] == "# Dataset card: aragona_2025")
t.ok("the build line", lines[2] == "RasterLabel 1.1, build %s, written "
     "2026-10-08T20:00:00" % rl.BUILD, lines[2])
head = "| code | class | ANNA p1 | BRUNO p1 | all | consensus p1 | " \
    "share (consensus p1) |"
t.ok("the class table, as the card prints it", head in lines, [
    l for l in lines if l.startswith("| code")])
t.ok("class 1: 60 50 52 50 61.0%",
     "| 1 | class 1 | 60 | 50 | 52 | 50 | 61.0% |" in lines)
t.ok("class 2: 40 40 48 32 39.0%",
     "| 2 | class 2 | 40 | 40 | 48 | 32 | 39.0% |" in lines)
line = [l for l in lines if l.startswith("consensus p1:")]
t.ok("the consensus line", line == [
    "consensus p1: 82 px agreed by 2 of 2, 18 px without a majority (8 "
    "painted by both differently, 10 by one only)"], line)
t.ok("the readings table", "| ANNA | 1 | 2 | 0 | 1 | 0 | 1 | 1 |" in lines)
t.ok("the frames", "1 frame; 1 closed as stored, 1 as recomputed now."
     in lines)
t.ok("a yes or no for a rule that is one", "- points in mask: no" in lines)
t.ok("what it does not say, operator names among it",
     "- operator names are personal data" in lines)
t.ok("kappa only as an agreement statistic", "agreement statistic" in md)
t.ok("the lines end with \\n", md.endswith("\n") and "\r" not in md)

empty = dict(card_a(), products=[], readings=[])
t.ok("an empty campaign: nothing drawn yet",
     "Nothing drawn yet" in rl.card_render_markdown(empty))
wide = dict(card_a())
wide["products"] = [dict(products[0], tag="R%d_p1" % i,
                         label="R%d, pass 1" % i) for i in range(5)] \
    + products[2:]
mdw = rl.card_render_markdown(wide)
t.ok("five readings: the main table keeps all, consensus and share",
     "| code | class | all | consensus p1 | share (consensus p1) |" in mdw)
t.ok("and a second table lists each reading",
     "| code | class | R0 p1 | R1 p1 | R2 p1 | R3 p1 | R4 p1 |" in mdw)
t.ok("the described product by default is the consensus",
     rl.card_described(dict(card_a(), stac={}))["mode"] == "consensus")
one = dict(card_a(), products=[products[0]], stac={})
t.ok("with one reading it is that reading",
     rl.card_described(one)["tag"] == "ANNA_p1")

print()
print("a correction card, fixture D")
corr = {"kind": "correction", "written": "2026-10-08",
        "software": {"name": "RasterLabel", "version": "1.1", "build": "x"},
        "correction": {"name": "map_corr", "id": "beef", "source": "map.tif"},
        "classes": classes[:2],
        "pixels": {"before": {1: 8, 2: 8}, "after": {1: 11, 2: 5},
                   "changed_px": 3, "changed_share": 0.1875,
                   "changed_pairs_px": [{"from": 2, "to": 1, "px": 3,
                                         "m2": 3.0}]},
        "operations": {"count": 2, "by_operator": {"MASSI": 2},
                       "changed_m2_logged": 3.0, "changed_m2_measured": 3.0,
                       "swept_m2": 7.0, "swept_over_changed": 2.33},
        "rules": {"pixel_rule": "centre"}}
mdc = rl.card_render_markdown(corr)
t.ok("before, after and the change per class",
     "| 1 | class 1 | 8 | 11 | +3 |" in mdc
     and "| 2 | class 2 | 8 | 5 | -3 |" in mdc, mdc)
t.ok("the changed share", "3 px changed by hand, 18.8% of the map." in mdc)
t.ok("from what into what", "- class 2 -> class 1: 3 px" in mdc)
t.ok("the operations", "2 operations; MASSI 2." in mdc)
nosrc = dict(corr, pixels=dict(corr["pixels"], before=None,
                               before_reason="the source map is not there"))
mdn = rl.card_render_markdown(nosrc)
t.ok("no source: before is empty and the reason is given",
     "| 1 | class 1 |  | 11 |  |" in mdn
     and "the source map is not there" in mdn)

print()
print("feeds and writing")
root = tempfile.mkdtemp(prefix="rl_card_")
try:
    package = os.path.join(root, "annotation.gpkg")
    with open(package, "wb") as fh:
        fh.write(b"v1")
    tmp, final = rl.report_folder(root, "agreement", "ANNA_p1_vs_BRUNO_p1")
    summary = rl.report_header("agreement", {"kind": "campaign",
                                             "id": data["id"]})
    summary["inputs"] = rl.report_inputs([package])
    summary["headline"] = {"A": "ANNA, pass 1", "B": "BRUNO, pass 1",
                           "overall": 0.8, "kappa": 0.615384615,
                           "overall_ci": [0.7, 0.9], "secret": 1}
    rl.report_json(os.path.join(tmp, "summary.json"), summary)
    rl.report_finish(tmp, final)
    feeds = rl.card_feeds(root, "campaign", data["id"],
                          rl.report_inputs([package]))
    t.ok("the agreement report feeds the card", feeds["agreement"] is not None
         and feeds["time"] is None)
    t.ok("with exactly the headline keys", sorted(
        feeds["agreement"]["headline"]) == sorted(
        rl.REPORT_HEADLINES["agreement"]))
    t.ok("not stale while the package is the same",
         feeds["agreement"]["stale"] is False)
    time.sleep(0.05)
    with open(package, "wb") as fh:
        fh.write(b"v2")
    feeds = rl.card_feeds(root, "campaign", data["id"],
                          rl.report_inputs([package]))
    t.ok("stale once the package changed", feeds["agreement"]["stale"])
    mdf = rl.card_render_markdown(dict(card_a(), agreement=feeds["agreement"]))
    t.ok("and the Markdown says may be stale", "may be stale" in mdf)
    t.ok("kappa is labelled an agreement statistic",
         "- kappa (agreement statistic): 0.6154" in mdf, mdf)
    # no bootstrap (fewer than five frames): the interval entries are None
    bare = dict(feeds["agreement"], headline={
        "overall": 0.8, "overall_ci": [None, None],
        "per_class_iou": {"bare ground": [0.9075, None, None],
                          "built-up": [0.6504, 0.5, 0.8],
                          "water": [None, None, None]}})
    mdb = rl.card_render_markdown(dict(card_a(), agreement=bare))
    t.ok("an empty interval leaves no stray commas or semicolons",
         "- per class iou: bare ground 0.9075; built-up 0.6504 (0.5 to 0.8)"
         in mdb.splitlines(), [l for l in mdb.splitlines() if "iou" in l])
    t.ok("and an interval with nothing in it has no line at all",
         "overall ci" not in mdb, mdb)
    t.ok("one that is there reads low to high",
         "- overall ci: 0.7 to 0.9" in mdf, mdf)
    sha = "ab" * 32
    mds = rl.card_render_markdown(dict(card_a(), exports=[
        {"path": "mask.tif", "role": "mask", "sha256": sha,
         "verified": True}]))
    t.ok("the Files table gives the whole SHA-256, not its first 12 letters",
         "| mask.tif | mask | %s | yes |" % sha in mds.splitlines(), mds)
    t.ok("another campaign's report does not feed it",
         rl.card_feeds(root, "campaign", "other", [])["agreement"] is None)

    out = os.path.join(root, "export")
    os.makedirs(out)
    md1, js1 = rl.card_write(card_a("2026-10-08T20:00:00"), out,
                             "aragona_2025")
    first_md = io.open(md1, encoding="utf-8").read()
    first_js = json.loads(io.open(js1, encoding="utf-8").read())
    t.ok("written as <stem>_card.md and <stem>_card.json",
         os.path.basename(md1) == "aragona_2025_card.md"
         and os.path.basename(js1) == "aragona_2025_card.json")
    md2, js2 = rl.card_write(card_a("2026-10-09T08:00:00"), out,
                             "aragona_2025")
    second_md = io.open(md2, encoding="utf-8").read()
    second_js = json.loads(io.open(js2, encoding="utf-8").read())
    first_js.pop("written")
    second_js.pop("written")
    t.ok("written twice, the JSON is the same but for the date",
         first_js == second_js)
    a_lines = first_md.split("\n")
    b_lines = second_md.split("\n")
    t.ok("and so is the Markdown, but for the date line",
         [i for i, (x, y) in enumerate(zip(a_lines, b_lines)) if x != y] == [2]
         and len(a_lines) == len(b_lines))
    t.ok("card_format 1 in the JSON", second_js["card_format"] == 1)
    t.ok("no .partial left", not [f for f in os.listdir(out)
                                  if f.endswith(".partial")])
finally:
    shutil.rmtree(root, ignore_errors=True)

t.done()
