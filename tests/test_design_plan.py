"""Import frames with the sampling design: what becomes of every unit.

design_plan decides, for every unit of a file, whether it becomes a frame,
fills in the design of a frame already there, is already there, or is
refused and why; one decision per unit, never fewer. This suite runs it on
small fixtures of sampling files, with no QGIS and no GDAL, and
with shapely saying independently which frames overlap.

The grid: origin (500000, 4200000), pixels of 0.5 m, a raster of 1000 x
1000 px (x 500000..500500, y 4199500..4200000); a frame of 10 m in
Settings, 20 px; an empty campaign.

- S1..S9 in fid order, Settings side: five added (t001..t005, no gap), one
  duplicate, one overlap, one outside the raster, one with no geometry;
  the frames, the reasons, the side and the shift of each;
- the same units on their own side: an odd side stays where it is, where
  Python's round would have moved it;
- frames there already: completed, already there, a duplicate of another
  draw; the same file twice adds nothing the second time;
- the column names of spsurvey, sampling::strata and AcATaMa;
- the words the window and the box say, design_log.csv written twice with
  its header once, and a moved or deleted frame of the design logged;
- Check on a campaign with a design;
- 200 random units: as many decisions, and no two frames added that share
  ground.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import io
import json
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purekit

rl = purekit.load("design")
t = purekit.Checks()

try:
    from shapely.geometry import box as shape_box
except ImportError:
    print("shapely is missing: pip install shapely")
    sys.exit(1)

O, P = (500000.0, 4200000.0), (0.5, 0.5)
EXTENT = (500000.0, 4199500.0, 500500.0, 4200000.0)
SIDE = rl.design_settings_side(10.0, 0.5)
TINY = rl.DESIGN_OVERLAP_PX2 * P[0] * P[1]


def shapely_clash(existing):
    """The clash the plugin asks of QGIS, asked of shapely here."""
    def clash(bbox, accepted):
        mine = shape_box(*bbox)
        out = []
        for e in list(existing) + list(accepted):
            if e.get("bbox") is None:
                continue
            if mine.intersection(shape_box(*e["bbox"])).area > TINY:
                out.append(str(e["tile_id"]))
        return sorted(out)
    return clash


def unit(fid, kind, bbox, **attrs):
    return {"fid": fid, "kind": kind, "bbox": bbox, "transform_ok": True,
            "attrs": attrs, "parts": 1}


def pt(x, y):
    return (x, y, x, y)


MAP = {"sample_id": "sid", "stratum": None, "incl_prob": "ip",
       "weight": "w", "design": None}
ROWS = [
    unit(1, "polygon", (500010, 4199980, 500020, 4199990), sid="A1",
         ip="0.05", w="20"),
    unit(2, "polygon", (500030.2, 4199980.2, 500040.2, 4199990.2), ip=1.5),
    unit(3, "polygon", (500060, 4199980, 500067, 4199987), w=-3),
    unit(4, "polygon", (500010, 4199980, 500020, 4199990), sid="A9"),
    unit(5, "polygon", (500015, 4199980, 500025, 4199990)),
    unit(6, "polygon", (500020, 4199980, 500030, 4199990), ip="0,05"),
    unit(7, "point", pt(500100.3, 4199950.1), ip="abc"),
    unit(8, "point", pt(501000, 4199900)),
    unit(9, "none", None),
]


def plan(rows, existing=(), own=False, **kw):
    existing = list(existing)
    return rl.design_plan(rows, existing, clash=shapely_clash(existing),
                          inside=rl.design_inside_box(EXTENT),
                          settings_side_px=SIDE, own_side=own, origin=O,
                          pixel=P, mapping=kw.pop("mapping", MAP), **kw)


def frame_of(d):
    return tuple(round(v, 6) for v in d["frame"])


print("S1..S9, the side in Settings (20 px)")
D = plan(ROWS)
by = {d["fid"]: d for d in D}
t.ok("nine decisions for nine units", len(D) == 9, len(D))
s1 = by[1]
t.ok("S1 added as t001, the frame identical, no reason",
     (s1["outcome"], s1["tile_id"], s1["reason"]) == ("added", "t001", "")
     and frame_of(s1) == (500010, 4199980, 500020, 4199990), s1)
t.ok("S1: no shift, ip 0.05 and w 20 carried",
     s1["shift_px"] == 0 and s1["values"]["incl_prob"] == 0.05
     and s1["values"]["weight"] == 20.0)
s2 = by[2]
t.ok("S2 added as t002 at (500030, 4199980, 500040, 4199990)",
     s2["outcome"] == "added" and s2["tile_id"] == "t002"
     and frame_of(s2) == (500030, 4199980, 500040, 4199990), s2)
t.ok('S2: "snapped;bad_value:incl_prob", shift 0.4, ip empty, its text kept',
     s2["reason"] == "snapped;bad_value:incl_prob"
     and s2["shift_px"] == 0.4 and s2["values"]["incl_prob"] is None
     and s2["raw"]["incl_prob"] == "1.5", (s2["reason"], s2["shift_px"]))
s3 = by[3]
t.ok("S3 added as t003 at (500058.5, 4199978.5, 500068.5, 4199988.5)",
     s3["tile_id"] == "t003"
     and frame_of(s3) == (500058.5, 4199978.5, 500068.5, 4199988.5), s3)
t.ok('S3: "resized;bad_value:weight", 14 px to 20 px',
     s3["reason"] == "resized;bad_value:weight"
     and s3["src_side_px"] == 14 and s3["frame_side_px"] == 20, s3["reason"])
t.ok("S4, S1's square under another sample: a duplicate of t001",
     (by[4]["outcome"], by[4]["reason"], by[4]["other_tile"])
     == ("refused", "duplicate", "t001"), by[4])
t.ok("S5, half over S1: overlap with t001",
     (by[5]["outcome"], by[5]["reason"], by[5]["other_tile"])
     == ("refused", "overlap", "t001"), by[5])
t.ok("S6 touches t001 and t002 and shares no ground: added as t004",
     (by[6]["outcome"], by[6]["tile_id"]) == ("added", "t004")
     and by[6]["values"]["incl_prob"] == 0.05, by[6])
s7 = by[7]
t.ok("S7, a point: t005 at (500095.5, 4199945, 500105.5, 4199955)",
     s7["tile_id"] == "t005"
     and frame_of(s7) == (500095.5, 4199945, 500105.5, 4199955), s7)
t.ok('S7: "from_point;bad_value:incl_prob"',
     s7["reason"] == "from_point;bad_value:incl_prob", s7["reason"])
t.ok("S8, off the raster: refused, outside_raster",
     (by[8]["outcome"], by[8]["reasons"][0]) == ("refused",
                                                 "outside_raster"), by[8])
t.ok("S9, no geometry: refused, no_geometry",
     (by[9]["outcome"], by[9]["reason"]) == ("refused", "no_geometry"))
counts = rl.design_summary(D)
t.ok("added 5; refused: duplicate 1, overlap 1, outside 1, no geometry 1",
     (counts["added"], counts["duplicate"], counts["overlap"],
      counts["outside_raster"], counts["no_geometry"]) == (5, 1, 1, 1, 1),
     counts)
t.ok("every unit counted once", sum(counts.values()) == 9, counts)
t.ok("t001..t005, no gap", [d["tile_id"] for d in D
                            if d["outcome"] == "added"]
     == ["t001", "t002", "t003", "t004", "t005"])
shuffled = list(reversed(ROWS))
t.ok("the order is the file's fid, whatever order the rows come in",
     [d["fid"] for d in plan(shuffled)] == list(range(1, 10)))
t.ok("the same rows give the same decisions",
     [(d["outcome"], d["tile_id"], d["reason"]) for d in plan(ROWS)]
     == [(d["outcome"], d["tile_id"], d["reason"]) for d in D])

print()
print("their own side")
own = plan([ROWS[2]], own=True)[0]
t.ok("S3 on its own side, 14 px: the frame is the source, nothing said of "
     "its shape (only of its weight)",
     own["frame_side_px"] == 14 and own["shift_px"] == 0
     and frame_of(own) == (500060, 4199980, 500067, 4199987)
     and own["reason"] == "bad_value:weight", own)
s10 = plan([unit(10, "polygon", (500005.5, 4199900, 500008.0, 4199902.5))],
           own=True)[0]
t.ok("S10, 5 px, an odd side: identical, col 11, no reason",
     frame_of(s10) == (500005.5, 4199900, 500008.0, 4199902.5)
     and s10["col"] == 11 and s10["reason"] == "", s10)
old_col = int(round((500006.75 - O[0]) / P[0])) - 5 // 2
t.ok("where snapped_square's round would have put it at col 12, half a "
     "pixel off", old_col == 12 and s10["col"] != old_col)
flat = plan([unit(11, "polygon", (500200, 4199800, 500210, 4199807))],
            own=True)[0]
t.ok("a 10 x 7 m polygon: side 20, resized",
     flat["frame_side_px"] == 20 and flat["reason"] == "resized", flat)
t.ok("a point always takes the Settings side",
     plan([ROWS[6]], own=True)[0]["frame_side_px"] == 20)
line = plan([unit(12, "line", (500300, 4199700, 500305, 4199702))])[0]
t.ok("a line too, flagged from_line",
     line["frame_side_px"] == 20 and line["reason"] == "from_line", line)
multi = dict(unit(13, "polygon", (500400, 4199600, 500410, 4199610)),
             parts=2)
t.ok("a shape of two parts is flagged multipart",
     plan([multi])[0]["reason"] == "multipart")
edge = plan([unit(14, "point", pt(500499, 4199600))])[0]
t.ok("a frame across the raster's edge is added, partly outside",
     edge["outcome"] == "added"
     and "partly_outside_raster" in edge["reasons"], edge)
moved = plan([dict(unit(15, "polygon", (1, 2, 3, 4)), transform_ok=False)])
t.ok("one that could not be brought into the campaign's system: refused",
     moved[0]["reason"] == "transform_failed")
nogrid = rl.design_plan([ROWS[0]], [], settings_side_px=20, origin=O,
                        pixel=(0.0, 0.0))
t.ok("a campaign with no grid refuses, and says so",
     nogrid[0]["reason"] == "no_grid")

print()
print("frames there already")
t001 = {"tile_id": "t001", "bbox": (500010, 4199980, 500020, 4199990),
        "design": dict.fromkeys(rl.DESIGN_FIELDS)}
d = plan([ROWS[0]], [t001])[0]
t.ok("t001 with no design + S1 (A1): completed, t001",
     (d["outcome"], d["tile_id"], d["other_tile"])
     == ("completed", "t001", "t001")
     and d["values"]["sample_id"] == "A1", d)
with_a1 = dict(t001, design=dict(t001["design"], sample_id="A1"))
d = plan([ROWS[0]], [with_a1])[0]
t.ok("t001 with A1 + S1 (A1): already there",
     (d["outcome"], d["tile_id"]) == ("already_there", "t001"), d)
b7 = dict(ROWS[0], attrs=dict(ROWS[0]["attrs"], sid="B7"))
d = plan([b7], [with_a1])[0]
t.ok("t001 with A1 + S1 as B7: refused, duplicate of t001",
     (d["outcome"], d["reason"], d["other_tile"])
     == ("refused", "duplicate", "t001"), d)
t.ok("a new frame is numbered after the highest there",
     plan([ROWS[1]], [dict(with_a1, tile_id="t041")])[0]["tile_id"]
     == "t042")


def as_existing(decisions):
    return [{"tile_id": d["tile_id"], "bbox": d["frame"],
             "design": d["values"]} for d in decisions
            if d["outcome"] == "added"]


again = plan(ROWS, as_existing(D))
c2 = rl.design_summary(again)
t.ok("the same file twice: nothing added the second time",
     c2["added"] == 0 and c2["completed"] == 0, c2)
t.ok("the five frames are already there, the four refusals stay refusals",
     c2["already_there"] == 5 and (c2["duplicate"], c2["overlap"],
                                   c2["outside_raster"],
                                   c2["no_geometry"]) == (1, 1, 1, 1), c2)
t.ok("and nothing of the second run lies over a frame",
     not [x for x in again if x["outcome"] == "added"])
twice = plan([ROWS[0], dict(ROWS[0], fid=20)])
t.ok("one square twice in one file: the second is a duplicate of the "
     "first's new frame", twice[1]["reason"].startswith("duplicate")
     and twice[1]["other_tile"] == "t001", twice[1])
t.ok("and both are flagged as the same sample id",
     all("duplicate_sample_id" in x["reasons"] for x in twice))

# Tiles written by an earlier build from a REAL column hold the id and the
# stratum as 12.0 and 2.0; the same file imported again now writes 12 and 2.
# Both spellings are one draw: the second import adds, completes and refuses
# nothing, and a different id is still a different draw.
REAL = {"sample_id": "sid", "stratum": "st", "incl_prob": "ip",
        "weight": "w", "design": None}
real_row = unit(1, "polygon", (500010, 4199980, 500020, 4199990),
                sid=12.0, st=2.0, ip=0.05, w=20.0)
spelt_old = dict(dict.fromkeys(rl.DESIGN_FIELDS), sample_id="12.0",
                 stratum="2.0", incl_prob=0.05, weight=20.0)
old_tile = {"tile_id": "t007", "bbox": (500010, 4199980, 500020, 4199990),
            "design": spelt_old}
d = plan([real_row], [old_tile], mapping=REAL)[0]
t.ok("a tile written with 12.0 and 2.0 and the same file now read as 12 and "
     "2: already there, no new frame",
     (d["outcome"], d["tile_id"], d["values"]["sample_id"],
      d["values"]["stratum"]) == ("already_there", "t007", "12", "2"), d)
d = plan([dict(real_row, attrs=dict(real_row["attrs"], sid=13.0))],
         [old_tile], mapping=REAL)[0]
t.ok("another id on the same ground is still another draw: refused",
     (d["outcome"], d["reason"]) == ("refused", "duplicate"), d)
only_stratum = {"sample_id": None, "stratum": "st", "incl_prob": None,
                "weight": None, "design": None}
old_stratum = {"tile_id": "t007", "bbox": old_tile["bbox"],
               "design": dict(dict.fromkeys(rl.DESIGN_FIELDS),
                              stratum="2.0")}
d = plan([real_row], [old_stratum], mapping=only_stratum)[0]
t.ok("with no id in the file, a stratum of 2.0 there and 2 now is the same "
     "draw too", d["outcome"] == "already_there", d)
d = plan([dict(real_row, attrs={"st": 3.0})], [old_stratum],
         mapping=only_stratum)[0]
t.ok("and a stratum 3 over a stratum of 2.0 is not",
     (d["outcome"], d["reason"]) == ("refused", "duplicate"), d)
both = plan([real_row, dict(real_row, fid=2, attrs=dict(real_row["attrs"],
                                                       sid=12.5))],
            [old_tile], mapping=REAL)
t.ok("12.5 is not 12.0: only the first is already there",
     [x["outcome"] for x in both] == ["already_there", "refused"], both)

print()
print("the stratum from a raster, the design typed")
read = []


def stratum_at(x, y):
    read.append((x, y))
    return 2 if x > 500050 else 1


pts = [unit(i, "point", pt(500020 + 40 * i, 4199900)) for i in range(4)]
got = rl.design_plan(pts, [], settings_side_px=SIDE, origin=O, pixel=P,
                     mapping={"sample_id": None, "stratum": "ignored"},
                     stratum_of=stratum_at, design_typed="AcATaMa, n=4")
t.ok("read at the middle of each frame",
     len(read) == 4 and read[0] == (500020.0, 4199900.0), read[:2])
t.ok("1 on the left, 2 on the right, as text",
     [g["values"]["stratum"] for g in got] == ["1", "2", "2", "2"],
     [g["values"]["stratum"] for g in got])
t.ok("the design typed goes on every frame",
     {g["values"]["design"] for g in got} == {"AcATaMa, n=4"})

print()
print("which column is which")
t.ok("spsurvey grts", rl.design_guess_mapping(
    ["siteID", "siteuse", "replsite", "lon_WGS84", "lat_WGS84", "stratum",
     "wgt", "ip", "caty"]) == {"sample_id": "siteID", "stratum": "stratum",
                               "incl_prob": "ip", "weight": "wgt",
                               "design": None})
t.ok("AcATaMa: id, never fid",
     rl.design_guess_mapping(["fid", "id"])["sample_id"] == "id")
m = rl.design_guess_mapping(["ID_unit", "Prob", "Stratum"])
t.ok("sampling::strata", (m["sample_id"], m["incl_prob"], m["stratum"])
     == ("ID_unit", "Prob", "Stratum"), m)
t.ok('"0.05", "0,05", 1: kept; "1,000.5" and 0: refused; "": empty',
     rl.design_parse_prob("0.05")[0] == 0.05
     and rl.design_parse_prob("0,05")[0] == 0.05
     and rl.design_parse_prob(1) == (1.0, None)
     and rl.design_parse_prob("1,000.5")[1] == "bad_value:incl_prob"
     and rl.design_parse_prob(0)[1] == "bad_value:incl_prob"
     and rl.design_parse_prob("") == (None, None))

print()
print("the words")
lines = rl.design_preview(D)
t.ok("the first line: 5 added and how",
     lines[0] == "5 added: 1 moved onto the grid, 1 resized, 1 from points",
     lines[0])
t.ok("each refusal with the frames it is about",
     "1 refused: a duplicate of t001" in lines
     and "1 refused: overlap with t001" in lines
     and "1 refused: outside the raster" in lines
     and "1 refused: no geometry" in lines, lines)
t.ok("and the values left empty",
     any(l.startswith("values left empty") and "incl prob 2" in l
         and "weight 1" in l for l in lines), lines)
t.ok("Import 5: the added and the completed",
     rl.design_import_count(D) == 5)
done = rl.design_done_text(D, "draws_2024.gpkg")
t.ok("the box after: counts, and design_log.csv lists all 9",
     done.startswith("5 frames added, 0 already there, 4 refused "
                     "(duplicate 1, overlap 1, outside raster 1, "
                     "no geometry 1). design_log.csv")
     and "all 9 features of draws_2024.gpkg, one row each" in done, done)
t.ok('one reason alone: "(overlap)"', rl.design_refused_text(
    {"overlap": 2}) == "overlap")
t.ok("the line under the list of frames",
     rl.design_tile_line({"sample_id": "S017", "stratum": "3",
                          "weight": 20.0}) == "sample S017 · stratum 3 · w 20")
t.ok("nothing for a frame without a design",
     rl.design_tile_line(dict.fromkeys(rl.DESIGN_FIELDS)) == "")

print()
print("design_log.csv")
root = tempfile.mkdtemp(prefix="rl_design_plan_")
try:
    path = rl.design_log_path(root)
    rows = rl.design_log_rows(D, "ab12cd34", "2026-10-09T12:00:00", "ANNA",
                              "draws_2024.gpkg", "EPSG:32633")
    t.ok("one row per unit", len(rows) == 9)
    t.ok("append once", rl.design_append_log(path, rows))
    t.ok("append twice", rl.design_append_log(path, rows))
    back = list(csv.reader(io.open(path, encoding="utf-8", newline="")))
    t.ok("the header once, then 18 rows, in LOG_COLUMNS order",
         back[0] == list(rl.DESIGN_LOG_COLUMNS) and len(back) == 19,
         len(back))
    named = [dict(zip(back[0], r)) for r in back[1:10]]
    t.ok("S2's row: snapped, its raw 1.5, the frame to the last digit",
         named[1]["reason"] == "snapped;bad_value:incl_prob"
         and named[1]["incl_prob_raw"] == "1.5"
         and named[1]["frame_xmin"] == "%.17g" % 500030.0
         and named[1]["shift_px"] == "0.4", named[1])
    t.ok("S9's row: refused, no geometry, no frame",
         named[8]["outcome"] == "refused"
         and named[8]["reason"] == "no_geometry"
         and named[8]["frame_xmin"] == "", named[8])
    t.ok("S4's row names the other frame",
         named[3]["other_tile"] == "t001" and named[3]["sample_id"] == "A9")
    gone = rl.design_not_written(D, "the package is locked; by OneDrive")
    t.ok("a commit that failed: every unit not_written, the reason without "
         "a stray ;", all(g["outcome"] == "not_written"
                          and g["reason"] == "commit failed: the package is "
                          "locked, by OneDrive" for g in gone)
         and len(gone) == 9)
    t.ok("and counted as such", rl.design_summary(gone)["not_written"] == 9)

    print()
    print("a frame of the design moved or deleted")

    class Crs(object):
        def authid(self):
            return "EPSG:32633"

    class Grid(object):
        pixel_crs = (0.5, 0.5)
        crs = Crs()

    class Section(object):
        geometry = Grid()

        def __init__(self, folder):
            self.campaign = type("C", (), {"folder": folder})()

        def operator_name(self):
            return " anna "

    class Feature(dict):
        def __getitem__(self, k):
            return dict.__getitem__(self, k)

    sec = Section(root)
    designed = Feature(tile_id="t001", sample_id="A1", stratum=None,
                       incl_prob=0.05, weight=20.0, design=None)
    plain = Feature(tile_id="t009", sample_id=None, stratum=None,
                    incl_prob=None, weight=None, design=None)
    before = (500010.0, 4199980.0, 500020.0, 4199990.0)
    after = (500011.0, 4199980.0, 500021.0, 4199990.0)
    t.ok("a move of a frame of the design is written",
         rl.design_frame_event(sec, "move", "t001", before, after, designed))
    t.ok("a delete too",
         rl.design_frame_event(sec, "delete", "t001", after, None, designed))
    t.ok("a frame placed by hand writes nothing",
         rl.design_frame_event(sec, "delete", "t009", before, None, plain)
         is None)
    t.ok("nor does a new or an imported frame",
         rl.design_frame_event(sec, "import", "t001", None, after, designed)
         is None and rl.design_frame_event(sec, "new", "t001", None, after,
                                           designed) is None)
    t.ok("a feature with no such columns writes nothing",
         rl.design_frame_event(sec, "move", "t009", before, after,
                               Feature(tile_id="t009")) is None)
    log_rows = rl.design_read_log(path)
    mv, dl = log_rows[-2], log_rows[-1]
    t.ok("20 rows now", len(log_rows) == 20, len(log_rows))
    t.ok("the move: the old frame in src, the new in frame, 2 px",
         mv["event"] == "move" and mv["outcome"] == "moved"
         and float(mv["src_xmin"]) == 500010.0
         and float(mv["frame_xmin"]) == 500011.0
         and mv["shift_px"] == "2" and mv["sample_id"] == "A1"
         and mv["incl_prob_raw"] == "0.05" and mv["weight_raw"] == "20",
         mv)
    t.ok("the delete: the old frame, no new one",
         dl["event"] == "delete" and dl["outcome"] == "deleted"
         and float(dl["src_xmin"]) == 500011.0 and dl["frame_xmin"] == "",
         dl)
    t.ok("with the system", mv["crs"] == "EPSG:32633")

    print()
    print("Check")

    class Finding(object):
        def __init__(self, level, what, detail=""):
            self.level, self.what, self.detail = level, what, detail

    rl.design_findings.__globals__["Finding"] = Finding
    frames = {"t001": {"sample_id": "A1", "incl_prob": 0.05, "weight": 20.0},
              "t004": {"sample_id": None, "incl_prob": 0.05, "weight": 10.0}}
    rl.design_findings.__globals__["frame_design"] = lambda p: dict(frames)
    pkg = os.path.join(root, "annotation.gpkg")
    open(pkg, "wb").close()
    owner = type("O", (), {"folder": root, "package_path": pkg,
                           "data": {"designs": [rl.design_manifest_entry(
                               "ab12cd34", "now", "ANNA", "/x/draws.gpkg",
                               "EPSG:32633", MAP, "", False, 20,
                               counts)]}})()
    found = rl.design_findings(owner)
    words = [(f.level, f.what) for f in found]
    t.ok("ok: 2 frames carry a sample of 1 imported design",
         ("ok", "2 frames carry a sample of 1 imported design") in words,
         words)
    t.ok("note: the 4 draws that never became frames",
         any(lv == "note" and w.startswith("4 draws of draws.gpkg never "
                                           "became frames")
             for lv, w in words), words)
    t.ok("note: moved and deleted after the import",
         ("note", "frames of an imported design were 1 moved and 1 deleted "
          "after the import") in words, words)
    t.ok("note: a weight that is not 1/p, on t004 alone, as a fact",
         any(lv == "note" and "on 1 frame the weight" in w
             for lv, w in words)
         and any("t004" in f.detail and "nothing was changed" in f.detail
                 for f in found), words)
    empty = type("O", (), {"folder": tempfile.mkdtemp(dir=root),
                           "package_path": "", "data": {}})()
    rl.design_findings.__globals__["frame_design"] = lambda p: {}
    t.ok("nothing at all for a campaign that never had a design",
         rl.design_findings(empty) == [])
    entry = owner.data["designs"][0]
    t.ok("the manifest entry: side, order, counts, log",
         entry["side"] == "settings" and entry["side_px"] == 20
         and entry["order"].startswith("source fid ascending")
         and entry["counts"]["added"] == 5
         and entry["log"] == "design_log.csv"
         and json.loads(json.dumps(entry)) == entry)
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("200 random units")
rnd = random.Random(20261009)
rows = []
for i in range(200):
    kind = rnd.choice(["point", "polygon", "polygon", "line", "none"])
    x = rnd.uniform(499990, 500510)
    y = rnd.uniform(4199490, 4200010)
    if kind == "none":
        bbox = None
    elif kind == "point":
        bbox = pt(x, y)
    else:
        s = rnd.uniform(2, 30)
        bbox = (x, y, x + s * rnd.uniform(0.6, 1.4), y + s)
    rows.append(dict(unit(i, kind, bbox, sid="R%d" % rnd.randint(0, 150)),
                     transform_ok=rnd.random() > 0.03))
for own_side in (False, True):
    got = plan(rows, own=own_side)
    added = [shape_box(*d["frame"]) for d in got if d["outcome"] == "added"]
    worst = 0.0
    for i in range(len(added)):
        for j in range(i + 1, len(added)):
            worst = max(worst, added[i].intersection(added[j]).area)
    side = "own side" if own_side else "Settings side"
    t.ok("%s: as many decisions as units" % side, len(got) == len(rows))
    t.ok("%s: every one counted once" % side,
         sum(rl.design_summary(got).values()) == len(rows))
    t.ok("%s: no two frames added share ground (%d added)"
         % (side, len(added)), worst <= TINY, worst)
    t.ok("%s: the default clash, on boxes, decides as shapely does" % side,
         [x["outcome"] for x in rl.design_plan(
             rows, [], inside=rl.design_inside_box(EXTENT),
             settings_side_px=SIDE, own_side=own_side, origin=O, pixel=P,
             mapping=MAP)] == [x["outcome"] for x in got])

t.done()
