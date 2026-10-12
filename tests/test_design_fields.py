"""The sampling design of an imported frame: its columns, its values, its log.

design.py carries five things of every sampled unit into the tiles table,
exactly as given: sample_id, stratum, incl_prob, weight and design. This
suite checks the part that needs no QGIS, against small fixtures of
sampling files:

- which source column is which, for spsurvey (siteID, stratum, wgt, ip),
  sampling::strata (ID_unit, Stratum, Prob) and AcATaMa (id), never fid;
- how a value is read: "0.05" and "0,05" are 0.05, "1,000.5" is refused
  because the comma cannot be told apart, 0 is not a probability, an empty
  cell is simply empty, and nothing is ever derived from anything else;
- where a frame lands on the grid (origin (500000, 4200000), 0.5 m pixels):
  the corner rounded half up from the edges, so an odd-sided square already
  on the grid stays where it is, where Python's round would move half of
  them a pixel;
- the rows of design_log.csv, appended with the header once.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purekit

rl = purekit.load("design")
t = purekit.Checks()

print("design.py is plain Python")
plain, sibling = purekit.imports_of("design")
t.ok("no QGIS, Qt or GDAL", not [m for m in plain if m in (
    "qgis", "osgeo", "PyQt5", "PyQt6")], plain)
t.ok("from the program only constants and naming",
     set(sibling) <= {"constants", "naming"}, sibling)

print()
print("which column is which")
spsurvey = ["siteID", "siteuse", "replsite", "lon_WGS84", "lat_WGS84",
            "stratum", "wgt", "ip", "caty"]
t.ok("spsurvey grts", rl.design_guess_mapping(spsurvey) == {
    "sample_id": "siteID", "stratum": "stratum", "incl_prob": "ip",
    "weight": "wgt", "design": None}, rl.design_guess_mapping(spsurvey))
t.ok("AcATaMa: id, never fid",
     rl.design_guess_mapping(["fid", "id"])["sample_id"] == "id")
t.ok("fid alone is not a sample id",
     rl.design_guess_mapping(["fid"])["sample_id"] is None)
strata = rl.design_guess_mapping(["ID_unit", "Prob", "Stratum"])
t.ok("sampling::strata", (strata["sample_id"], strata["incl_prob"],
                          strata["stratum"]) == ("ID_unit", "Prob", "Stratum"))
t.ok("the first alias present wins",
     rl.design_guess_mapping(["id", "sample_id"])["sample_id"] == "sample_id")

print()
print("reading the values")
t.ok('"0.05" is 0.05', rl.design_parse_prob("0.05") == (0.05, None))
t.ok('"0,05" is 0.05', rl.design_parse_prob("0,05") == (0.05, None))
t.ok('"1,000.5" is refused', rl.design_parse_prob("1,000.5")
     == (None, "bad_value:incl_prob"))
t.ok("0 is not a probability", rl.design_parse_prob(0)
     == (None, "bad_value:incl_prob"))
t.ok("1 is", rl.design_parse_prob(1) == (1.0, None))
t.ok("1.5 is not", rl.design_parse_prob("1.5")[1] == "bad_value:incl_prob")
t.ok('"" is empty, with no flag', rl.design_parse_prob("") == (None, None))
t.ok("None is empty, with no flag", rl.design_parse_prob(None)
     == (None, None))
t.ok('"abc" is refused', rl.design_parse_prob("abc")[1]
     == "bad_value:incl_prob")
t.ok("nan is refused", rl.design_parse_prob(float("nan"))[1]
     == "bad_value:incl_prob")
t.ok("a weight of 20", rl.design_parse_weight("20") == (20.0, None))
t.ok("a weight of -3 is refused", rl.design_parse_weight(-3)
     == (None, "bad_value:weight"))
t.ok("a weight of 0 is refused", rl.design_parse_weight("0")[1]
     == "bad_value:weight")
t.ok("a boolean is not a number", rl.design_parse_weight(True)[1]
     == "bad_value:weight")
values, raw, flags, full = rl.design_values(
    {"siteID": " A1 ", "ip": "1.5", "wgt": "20", "stratum": 3},
    rl.design_guess_mapping(spsurvey), design_typed="stratified random, n=120")
t.ok("a unit's design: trimmed id, stratum as text, weight kept",
     values["sample_id"] == "A1" and values["stratum"] == "3"
     and values["weight"] == 20.0)
t.ok("the bad probability is left empty and flagged, its text kept",
     values["incl_prob"] is None and flags == ["bad_value:incl_prob"]
     and raw["incl_prob"] == "1.5")
t.ok("weight is not derived from the probability, nor the reverse",
     values["incl_prob"] is None and values["weight"] == 20.0)
t.ok("the typed design", values["design"] == "stratified random, n=120"
     and full == "stratified random, n=120")
long_design = "x" * 120
v2, _, f2, full2 = rl.design_values({}, {}, design_typed=long_design)
t.ok("a design past 80 characters is cut in the column, kept whole in the "
     "manifest", len(v2["design"]) == 80 and full2 == long_design)
v3, _, f3, _ = rl.design_values({"id": "s" * 90}, {"sample_id": "id"})
t.ok("a sample id past 80 characters is cut, and says so",
     len(v3["sample_id"]) == 80 and f3 == ["truncated:sample_id"])
v4, _, _, _ = rl.design_values({}, {"stratum": None}, stratum_value=2)
t.ok("a stratum read from a raster", v4["stratum"] == "2")
v5, shown5, _, _ = rl.design_values(
    {"id": 12.0, "st": 2.0, "ip": 0.25, "w": 4.0},
    {"sample_id": "id", "stratum": "st", "incl_prob": "ip", "weight": "w"})
t.ok("an id and a stratum a REAL column holds whole are 12 and 2, not 12.0 "
     "and 2.0, which would no longer match the design they are joined to",
     v5["sample_id"] == "12" and v5["stratum"] == "2"
     and shown5["sample_id"] == "12" and shown5["stratum"] == "2",
     (v5, shown5))
t.ok("and the numbers keep the digits they came with",
     v5["incl_prob"] == 0.25 and v5["weight"] == 4.0
     and shown5["weight"] == "4.0", (v5, shown5))
v6, _, _, _ = rl.design_values({"id": 12.5, "st": -3.0},
                               {"sample_id": "id", "stratum": "st"})
t.ok("a true decimal keeps its digits, a negative whole number is whole",
     v6["sample_id"] == "12.5" and v6["stratum"] == "-3", v6)
v7, _, _, _ = rl.design_values({"id": float("nan"), "st": True},
                               {"sample_id": "id", "stratum": "st"})
t.ok("a NaN and a boolean are written as they always were",
     v7["sample_id"] == "nan" and v7["stratum"] == "True", v7)
old = {"sample_id": "12.0", "stratum": "2.0"}
t.ok("a tile written from a REAL column (12.0, 2.0) is the same draw as the "
     "re-import of the file (12, 2)",
     rl.design_same_unit(old, v5) and rl.design_same_unit(v5, old))
t.ok("and so without a sample id",
     rl.design_same_unit({"stratum": "2.0"}, {"stratum": "2"}))
t.ok("12.5 is not 12, nor 12.05 12, nor 120 12",
     not rl.design_same_unit({"sample_id": "12.5"}, {"sample_id": "12"})
     and not rl.design_same_unit({"sample_id": "12.05"}, {"sample_id": "12"})
     and not rl.design_same_unit({"sample_id": "120"}, {"sample_id": "12"})
     and not rl.design_same_unit({"stratum": "3"}, {"stratum": "2.0"}))
t.ok("no design at all", not rl.design_has_design(
    rl.design_values({}, {})[0]))

print()
print("on the grid: origin (500000, 4200000), pixels of 0.5 m")
O, P = (500000.0, 4200000.0), (0.5, 0.5)
side = rl.design_settings_side(10.0, 0.5)
t.ok("the Settings side, 10 m, is 20 px", side == 20)
sq = rl.design_grid_square(500015.0, 4199985.0, 20, O, P)
t.ok("S1: a square already on the grid stays",
     sq[:4] == (500010.0, 4199980.0, 500020.0, 4199990.0), sq)
sq = rl.design_grid_square(500035.2, 4199985.2, 20, O, P)
# col = floor(70.4 - 10 + 0.5) = 60
t.ok("S2: col 60, so (500030, 4199980, 500040, 4199990)",
     sq == (500030.0, 4199980.0, 500040.0, 4199990.0, 60, 20), sq)
t.near("and moved 0.4 px", rl.design_shift_px(
    (500030.2, 4199980.2, 500040.2, 4199990.2), sq[:4], P), 0.4, 1e-6)
sq = rl.design_grid_square(500063.5, 4199983.5, 20, O, P)
# a 14 px source, Settings side: col = floor(127 - 10 + 0.5) = 117,
# row = floor(33 - 10 + 0.5) = 23
t.ok("S3: col 117, row 23", sq == (500058.5, 4199978.5, 500068.5,
                                   4199988.5, 117, 23), sq)
sq = rl.design_grid_square(500100.3, 4199950.1, 20, O, P)
# col = floor(200.6 - 10 + 0.5) = 191, row = floor(99.8 - 10 + 0.5) = 90
t.ok("S7, a point: col 191, row 90", sq == (500095.5, 4199945.0, 500105.5,
                                           4199955.0, 191, 90), sq)
side, resized = rl.design_own_side(14.0, 14.0)
t.ok("own side of a 14 px square: 14, not resized", (side, resized)
     == (14, False))
sq = rl.design_grid_square(500063.5, 4199983.5, 14, O, P)
t.ok("S3 on its own side equals the source",
     sq[:4] == (500060.0, 4199980.0, 500067.0, 4199987.0)
     and sq[4:] == (120, 26), sq)
sq = rl.design_grid_square(500006.75, 4199901.25, 5, O, P)
# a 5 px square, odd: col = floor(13.5 - 2.5 + 0.5) = 11
t.ok("S10, odd side: stays at col 11 (xmin 500005.5, ymax 4199902.5)",
     sq[0] == 500005.5 and sq[3] == 4199902.5 and sq[4] == 11, sq)
rounded = int(round((500006.75 - O[0]) / P[0])) - 5 // 2
t.ok("where the round-half-to-even rule would have put it at col 12",
     rounded == 12)
t.ok("a 10 x 7 m polygon: side 20, resized",
     rl.design_own_side(20.0, 14.0) == (20, True))
t.ok("square within a pixel: not resized",
     rl.design_own_side(20.0, 19.2) == (20, False))
t.ok("every edge is the origin plus whole pixels", all(
    abs(((v - O[0]) / 0.5) - round((v - O[0]) / 0.5)) < 1e-9
    for v in rl.design_grid_square(500123.4567, 4199876.5, 7, O, P)[:4:2]))

print()
print("counting the outcomes")
decisions = [{"outcome": "added"}] * 5 + [
    {"outcome": "refused", "reason": "duplicate"},
    {"outcome": "refused", "reason": "overlap"},
    {"outcome": "refused", "reason": "from_point;outside_raster"},
    {"outcome": "refused", "reason": "no_geometry"},
    {"outcome": "already_there"}]
counts = rl.design_summary(decisions)
t.ok("added 5, duplicate 1, overlap 1, outside 1, no geometry 1, there 1",
     (counts["added"], counts["duplicate"], counts["overlap"],
      counts["outside_raster"], counts["no_geometry"],
      counts["already_there"]) == (5, 1, 1, 1, 1, 1), counts)
t.ok("every unit counted once", sum(counts.values()) == len(decisions))

print()
print("design_log.csv")
root = tempfile.mkdtemp(prefix="rl_design_")
try:
    path = os.path.join(root, rl.DESIGN_LOG)
    rows = [rl.design_log_row(import_id="ab12cd34", event="import",
                              source_file="draws.gpkg", source_fid=i,
                              sample_id="A%d" % i, outcome="added",
                              reason=["snapped", "bad_value:incl_prob"],
                              tile_id="t%03d" % i,
                              src=(500030.2, 4199980.2, 500040.2,
                                   4199990.2),
                              frame=(500030.0, 4199980.0, 500040.0,
                                     4199990.0),
                              src_side_px=20, frame_side_px=20,
                              shift_px=0.4, crs="EPSG:32633")
            for i in range(9)]
    t.ok("append once", rl.design_append_log(path, rows))
    t.ok("append twice", rl.design_append_log(path, rows))
    back = list(csv.reader(io.open(path, encoding="utf-8", newline="")))
    t.ok("the header appears once, then 18 rows",
         back[0] == list(rl.DESIGN_LOG_COLUMNS) and len(back) == 19)
    t.ok("the columns", len(back[1]) == len(rl.DESIGN_LOG_COLUMNS) == 27)
    named = dict(zip(back[0], back[1]))
    t.ok("reasons joined with ;", named["reason"]
         == "snapped;bad_value:incl_prob")
    t.ok("coordinates with every digit a double has",
         named["src_xmin"] == "%.17g" % 500030.2
         and float(named["src_xmin"]) == 500030.2)
    t.ok("a delete row has empty frame columns", rl.design_log_row(
        event="delete", outcome="deleted", src=(1, 2, 3, 4))[
        rl.DESIGN_LOG_COLUMNS.index("frame_xmin")] == "")
    try:
        rl.design_log_row(colour="red")
        t.ok("an unknown column is a mistake", False)
    except KeyError:
        t.ok("an unknown column is a mistake", True)
    said = []
    t.ok("a log that cannot be written says so and returns False",
         rl.design_append_log(root, rows, said.append) is False
         and len(said) == 1)
    t.ok("a float as %.12g", named["shift_px"] == "0.4")
finally:
    shutil.rmtree(root, ignore_errors=True)

t.done()
