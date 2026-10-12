"""Active time out of a journal, against fixtures worked out by hand.

Fixture S, drawing from scratch: one session of MASSI, pass 1, on frame T1
of 50 x 50 m (0.25 ha). Rows as (action, class, end s, duration s, pauses):

    open 0 | stroke c1 25 15 | stroke c1 50 10 | view 100 |
    stroke c2 230 100 "20;75" | focus_out 240 | focus_in 245 |
    stroke c2 262 12 | close 400

so the gaps between one row's end and the next one's start are 10, 15, 50,
30, 10, [out of focus], 5 and 138 s. At an idle limit of 60 s:

    c1    draw 15 + 10 = 25, lead 10 + 15 = 25             50 s
    c2    draw (100 - 75) + 12 = 37, lead 50 + 30 + 5 = 85  122 s
    overhead: the 10 s before focus_out, to T1              10 s
    T1                                                       182 s

and 12.133 min/ha; c1 on 1000 m2 is 8.333 min/ha, c2 on 1500 m2 13.556. At
30 s the gap of 50 is idle and the gap of exactly 30 is not (idle is
strict): c2 = 25 + 12 + 30 + 5 = 72 and T1 = 132. At 120 s the 75 s pause
is work again: c2 = 100 + 12 + 80 + 5 = 197 and T1 = 257. The focus span
is idle at every limit and counted nowhere.

Fixture C, correcting: ANNA in Correct, frames T1 = [0,50] x [0,50] and T2 =
[50,100] x [0,50], strokes placed by where they fall:

    open 0 | correct 10 8 at (10,10) | correct 30 10 at (60,20) |
    correct 106 6 at (70,30) | close 110

At 60 s T1 = 2 + 8 = 10 and T2 = 10 + 10 + 6 + an overhead of 4 = 30, the
gap of 70 being idle; at 120 s it is not, and T2 = 100. On T1, correcting
against drawing: 10/182 = 0.054945, a saving of 94.5 %.

Fixture L, an operations.csv from before the journal: four rows a 20, 70
and 10 s apart give 30 s at 30 and 60 s, and 100 s at 120 s.

Then the tables of a report on the same fixtures, column for column: a
frame drawn before the journal is listed with its time empty, never zero;
the overhead is class 0; the pairing of T1; and the frame bootstrap, which
is numpy's default_rng(1) drawn 2000 times, checked against numpy itself.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purekit

rl = purekit.load("stats", "effort")
t = purekit.Checks()
nan = purekit.isnan

T0 = datetime(2026, 10, 8, 9, 0, 0, tzinfo=timezone.utc)


def row(action, end_s, dur_s=0, cls="", pauses="", tile="T1", session="S1",
        op="MASSI", pass_no="1", seq=[0], x="", y="", utc0=T0, module="annotate"):
    seq[0] += 1
    return {"session": session, "seq": seq[0], "mono_ms": int(end_s * 1000),
            "t_utc": (utc0 + timedelta(seconds=end_s)).isoformat(
                timespec="milliseconds").replace("+00:00", "Z"),
            "dur_ms": int(dur_s * 1000), "pauses_s": pauses, "module": module,
            "action": action, "operator": op, "pass_no": pass_no,
            "tile_id": tile, "class_code": cls, "x": x, "y": y}


S = [row("open", 0), row("stroke", 25, 15, 1), row("stroke", 50, 10, 1),
     row("view", 100), row("stroke", 230, 100, 2, "20.0;75.0"),
     row("focus_out", 240), row("focus_in", 245), row("stroke", 262, 12, 2),
     row("close", 400)]

print("fixture S, drawing from scratch")
for theta, c1, c2, total in ((60, 50, 122, 182), (30, 50, 72, 132),
                             (120, 50, 197, 257)):
    r = rl.effort_attribute(S, theta)
    cells = r["cells"]
    got1 = sum(cells[("T1", "MASSI", "1", 1)][k] for k in ("draw_s", "lead_s"))
    got2 = sum(cells[("T1", "MASSI", "1", 2)][k] for k in ("draw_s", "lead_s"))
    f = r["frames"][("T1", "MASSI", "1")]
    t.near("idle %d s: c1 %d s" % (theta, c1), got1, c1)
    t.near("idle %d s: c2 %d s" % (theta, c2), got2, c2)
    t.near("idle %d s: overhead 10 s" % theta, f["overhead_s"], 10)
    t.near("idle %d s: T1 %d s" % (theta, total), f["active_s"], total)
r = rl.effort_attribute(S, 60)
c2 = r["cells"][("T1", "MASSI", "1", 2)]
t.ok("draw and lead are kept apart: c2 draw 37, lead 85",
     abs(c2["draw_s"] - 37) < 1e-9 and abs(c2["lead_s"] - 85) < 1e-9, c2)
f = r["frames"][("T1", "MASSI", "1")]
t.near("12.133 min/ha on 0.25 ha", rl.effort_per_ha(f["active_s"], 2500),
       182 / 60 / 0.25)
cls = rl.effort_class_totals(r)
t.near("c1 on 1000 m2: 8.333 min/ha",
       rl.effort_per_ha(cls[("MASSI", "1", 1)], 1000), 8.333333333, 1e-6)
t.near("c2 on 1500 m2: 13.556 min/ha",
       rl.effort_per_ha(cls[("MASSI", "1", 2)], 1500), 13.5555556, 1e-6)
t.near("wall 400 s", f["wall_s"], 400)
t.ok("four marks, one session", f["marks"] == 4 and f["sessions"] == 1)
t.ok("first and last in UTC", f["first_utc"] == "2026-10-08T09:00:00.000Z"
     and f["last_utc"] == "2026-10-08T09:06:40.000Z", (f["first_utc"],
                                                       f["last_utc"]))
# the focus span is 245 - 240 = 5 s; at no limit is it anywhere
t.ok("the focus span is counted nowhere, at any limit", all(
    abs(rl.effort_attribute(S, th)["frames"][("T1", "MASSI", "1")]
        ["active_s"] - want) < 1e-9 for th, want in ((300, 400 - 5 - 0),)),
    rl.effort_attribute(S, 300)["frames"][("T1", "MASSI", "1")]["active_s"])
sens = rl.effort_sensitivity(S)
t.ok("30, 60 and 120 s always", sorted(sens) == [30, 60, 120])
t.ok("no area: no min/ha", nan(rl.effort_per_ha(100, 0)))

print()
print("fixture C, correcting, placed by the frames")
frames = {"T1": (0, 0, 50, 50), "T2": (50, 0, 100, 50)}
place = rl.effort_frame_finder(frames)
C = [row("open", 0, tile="", op="ANNA", pass_no="", module="correct"),
     row("correct", 10, 8, 2, tile="", op="ANNA", pass_no="", x=10, y=10,
         module="correct"),
     row("correct", 30, 10, 2, tile="", op="ANNA", pass_no="", x=60, y=20,
         module="correct"),
     row("correct", 106, 6, 2, tile="", op="ANNA", pass_no="", x=70, y=30,
         module="correct"),
     row("close", 110, tile="", op="ANNA", pass_no="", module="correct")]
for theta, t1, t2 in ((60, 10, 30), (30, 10, 30), (120, 10, 100)):
    rc = rl.effort_attribute(C, theta, place)
    t.near("idle %d s: T1 %d s" % (theta, t1),
           rc["frames"][("T1", "ANNA", "")]["active_s"], t1)
    t.near("idle %d s: T2 %d s" % (theta, t2),
           rc["frames"][("T2", "ANNA", "")]["active_s"], t2)
rc = rl.effort_attribute(C, 60, place)
t.near("the 4 s after the last stroke are overhead of T2",
       rc["frames"][("T2", "ANNA", "")]["overhead_s"], 4)
t.ok("no time lost", rc["unplaced_s"] == 0)

print()
print("pairing on T1 at 60 s")
pair = rl.effort_pair({"T1": 182.0}, {"T1": 10.0}, n_boot=200, seed=1)
p = pair["rows"][0]
t.near("ratio 10/182 = 0.054945", p["ratio"], 0.054945, 1e-6)
t.near("saving 94.5 %", p["saving_pct"], 94.505, 1e-3)
t.near("log ratio -2.9014", p["log_ratio"], -2.9014, 1e-4)
t.ok("one frame: no interval", pair["pooled"]["ci_reason"] != ""
     and nan(pair["pooled"]["ci_low"]))
skip = rl.effort_pair({"T1": 182.0, "T2": 0.0, "T3": 5.0},
                      {"T1": 10.0, "T2": 30.0})
t.ok("a frame with no time on one side is skipped and counted",
     skip["pooled"]["n_frames"] == 1 and skip["pooled"]["n_skipped"] == 1
     and skip["pooled"]["skipped"] == ["T2"])

print()
print("the bootstrap and the Wilcoxon test of the pairing")
logs = [-1.0, -0.5, -0.2, -0.8, -0.6]
scratch = {"f%d" % i: 100.0 for i in range(5)}
correct = {"f%d" % i: 100.0 * math.exp(v) for i, v in enumerate(logs)}
a = rl.effort_pair(scratch, correct, 2000, 1)["pooled"]
b = rl.effort_pair(scratch, correct, 2000, 1)["pooled"]
t.near("geometric mean exp(-0.62) = 0.5379", a["ratio"], math.exp(-0.62),
       1e-12)
t.ok("the interval is the same on two runs with seed 1",
     (a["ci_low"], a["ci_high"]) == (b["ci_low"], b["ci_high"]))
t.ok("and it holds the estimate", a["ci_low"] <= a["ratio"] <= a["ci_high"])
t.near("all negative: exact two-sided p = 2/32", a["wilcoxon_p"], 0.0625)
t.near("median of the ratios exp(-0.6)", a["median_ratio"], math.exp(-0.6),
       1e-12)

print()
print("fixture L, operations.csv from before the journal")
whens = ["2026-10-08T10:00:00", "2026-10-08T10:00:20",
         "2026-10-08T10:01:30", "2026-10-08T10:01:40"]
for theta, want in ((60, 30), (30, 30), (120, 100)):
    secs, bad = rl.effort_legacy(whens, theta)
    t.near("idle %d s: %d s" % (theta, want), sum(secs), want)
t.ok("the first row gets nothing", rl.effort_legacy(whens)[0][0] == 0)
t.ok("a when that is not a time is counted",
     rl.effort_legacy(["x", whens[0]])[1] == 1)

print()
print("grids")
g = {"crs": "EPSG:32633", "origin": [0.0, 0.0], "pixel_crs": [0.5, 0.5],
     "pixel_m": [0.5, 0.5]}
t.ok("same CRS, same pixel, origin a whole number of pixels off: same",
     rl.effort_grid_relation(g, dict(g, origin=[10.5, -3.0])) == "same")
t.ok("origin 10.25: aligned_crs",
     rl.effort_grid_relation(g, dict(g, origin=[10.25, 0.0]))
     == "aligned_crs")
t.ok("another pixel size: aligned_crs",
     rl.effort_grid_relation(g, dict(g, pixel_crs=[0.25, 0.25]))
     == "aligned_crs")
t.ok("EPSG:4326 against 32633: other",
     rl.effort_grid_relation(g, dict(g, crs="EPSG:4326")) == "other")
t.ok("the CRS comparison can be handed in",
     rl.effort_grid_relation(g, dict(g, crs="WGS 84 / UTM 33N"),
                             same_crs=lambda a, b: True) == "same")

print()
print("borders and the outside")
t.ok("(50, 10) on the shared border goes to T1, the lowest tile_id",
     rl.effort_frame_of(50, 10, frames) == "T1")
t.ok("(150, 10) is outside every frame",
     rl.effort_frame_of(150, 10, frames) == rl.EFFORT_OUTSIDE)
t.ok("a ring works as a bbox does", rl.effort_frame_of(
    25, 25, {"A": [(0, 0), (50, 0), (50, 50), (0, 50)]}) == "A")
out = rl.effort_attribute(
    [row("correct", 5, 2, 1, tile="", op="ANNA", pass_no="", x=150, y=10,
         module="correct")], 60, place)
t.ok("a stroke outside is counted under (outside frames) and said",
     out["outside"] == 1 and (rl.EFFORT_OUTSIDE, "ANNA", "") in out["frames"]
     and any("outside" in w for w in out["warnings"]))

print()
print("two sessions at once, and a clock going back")
u1 = T0
both = [row("open", 0, session="A", utc0=u1),
        row("stroke", 20, 10, 1, session="A", utc0=u1),
        row("open", 0, session="B", utc0=u1 + timedelta(seconds=5)),
        row("stroke", 20, 10, 1, session="B", utc0=u1 + timedelta(seconds=5))]
rb = rl.effort_attribute(both, 60)
# A is active 0..20, B 5..25 in UTC: 15 s of B lie over A
t.near("the overlap is counted once", rb["frames"][("T1", "MASSI", "1")]
       ["active_s"], 25)
t.near("and reported", rb["overlap_s"], 15)
t.ok("with a warning", any("two sessions" in w for w in rb["warnings"]))
back = [row("open", 0, session="Z"), row("stroke", 50, 10, 1, session="Z"),
        # a restart: the monotonic clock starts again, the UTC one goes on
        row("stroke", 20, 10, 1, session="Z",
            utc0=T0 + timedelta(seconds=100))]
rz = rl.effort_attribute(back, 60)
t.ok("a mono_ms that goes back splits the session",
     any("split" in w for w in rz["warnings"]))
t.near("and the gap across it is not counted",
       rz["frames"][("T1", "MASSI", "1")]["active_s"], 50 + 10)
t.ok("the two pieces are two sessions",
     rz["frames"][("T1", "MASSI", "1")]["sessions"] == 2)

print()
print("the rule as a sentence")
t.ok("it names the idle limit and the attribution",
     "longer than T" in rl.EFFORT_RULE and "next mark" in rl.EFFORT_RULE)

print()
print("the bootstrap is numpy's default_rng(1), resampling frames")
import numpy as np  # noqa: E402
v = np.array(logs)
rng = np.random.default_rng(1)
idx = rng.integers(0, v.size, size=(2000, v.size))
reps = np.exp(v[idx].mean(axis=1))
lo, hi = np.percentile(reps, [2.5, 97.5])
t.near("the low end is the 2.5 % of 2000 draws of default_rng(1)",
       a["ci_low"], lo, 1e-12)
t.near("and the high end the 97.5 %", a["ci_high"], hi, 1e-12)
t.ok("with the seed written down", a["seed"] == 1 and a["n_boot"] == 2000)
few = rl.effort_pair({"a": 10.0, "b": 10.0, "c": 10.0, "d": 10.0},
                     {"a": 5.0, "b": 6.0, "c": 4.0, "d": 7.0}, 2000, 1)
t.ok("below five frames there is no interval at all",
     nan(few["pooled"]["ci_low"]) and few["pooled"]["ci_reason"])

print()
print("the tables, with the columns the README names")
t.ok("time_per_frame.csv",
     list(rl.EFFORT_FRAME_COLUMNS) == [
         "source", "campaign_id", "correction_id", "tile_id", "frame_m2",
         "frame_ha", "operator", "pass_no", "sessions", "marks", "undos",
         "refused", "coverage_pct", "closed_reading", "changed_m2",
         "draw_s_T", "lead_s_T", "overhead_s_T", "active_s_T",
         "min_per_ha_T", "active_s_30", "active_s_60", "active_s_120",
         "wall_s", "first_utc", "last_utc", "journal", "estimated"])
t.ok("time_per_class.csv",
     list(rl.EFFORT_CLASS_COLUMNS) == [
         "source", "campaign_id", "correction_id", "tile_id", "operator",
         "pass_no", "class_code", "class_name", "marks", "draw_s_T",
         "lead_s_T", "active_s_T", "active_s_30", "active_s_60",
         "active_s_120", "class_m2", "class_ha", "min_per_ha_T",
         "share_of_frame_time"])
t.ok("time_paired.csv, the pooled numbers after the frame ones",
     list(rl.EFFORT_PAIRED_COLUMNS)[:14] == [
         "tile_id", "frame_ha", "scratch_operator", "scratch_pass",
         "correct_operator", "scratch_s_T", "correct_s_T", "ratio_T",
         "log_ratio_T", "saving_pct_T", "ratio_30", "ratio_60", "ratio_120",
         "changed_m2"] and {"median_ratio_T", "ci_low_T", "ci_high_T",
                            "n_frames", "n_skipped", "wilcoxon_p"}
     <= set(rl.EFFORT_PAIRED_COLUMNS))
sens = rl.effort_sensitivity(S, (30, 60, 120))
keys = [("T1", "MASSI", "1"), ("T2", "MASSI", "1")]
frows = rl.effort_frame_table(
    "scratch", sens, 60, {"T1": 2500.0, "T2": 2500.0}, keys, "camp", "",
    {("T1", "MASSI", "1"): 1.0, ("T2", "MASSI", "1"): 0.4},
    designs={"T1": {"sample_id": "S1", "stratum": "a", "incl_prob": 0.5,
                    "weight": 2.0}})
f1, f2 = frows
t.near("T1: 182 s at 60", f1["active_s_T"], 182)
t.ok("draw, lead and overhead apart",
     (f1["draw_s_T"], f1["lead_s_T"], f1["overhead_s_T"]) == (62.0, 110.0,
                                                              10.0), f1)
t.near("12.133 min/ha", f1["min_per_ha_T"], 182 / 60 / 0.25)
t.ok("30, 60 and 120 s beside it",
     (f1["active_s_30"], f1["active_s_60"], f1["active_s_120"])
     == (132.0, 182.0, 257.0), f1)
t.ok("covered whole, so closed; journal 1, not estimated",
     f1["coverage_pct"] == 100.0 and f1["closed_reading"] == 1
     and f1["journal"] == 1 and f1["estimated"] == 0)
t.ok("the frame's sampling design comes along", f1["sample_id"] == "S1"
     and f1["weight"] == 2.0)
t.ok("a frame drawn before the journal: listed, its time empty, journal 0, "
     "never zero seconds", f2.get("active_s_T") is None
     and f2["journal"] == 0 and f2["coverage_pct"] == 40.0
     and f2["closed_reading"] == 0, f2)
crows = rl.effort_class_table(
    "scratch", sens, 60, keys,
    {("T1", "MASSI", "1", 1): 1000.0, ("T1", "MASSI", "1", 2): 1500.0},
    {1: "crater", 2: "mud flow"}, "camp")
by = {(r["tile_id"], r["class_code"]): r for r in crows}
t.near("class 1: 8.333 min/ha", by[("T1", 1)]["min_per_ha_T"], 8.3333333,
       1e-6)
t.near("class 2: 13.556 min/ha", by[("T1", 2)]["min_per_ha_T"], 13.5555556,
       1e-6)
t.ok("overhead is class 0, (no class), 10 s",
     by[("T1", 0)]["class_name"] == "(no class)"
     and by[("T1", 0)]["active_s_T"] == 10.0)
t.near("the classes and the overhead share the frame's time",
       sum(by[("T1", c)]["share_of_frame_time"] for c in (0, 1, 2)), 1.0)
t.ok("pooled rows over the frames, tile '*'",
     by[("*", 2)]["active_s_T"] == 122.0
     and by[("*", 2)]["active_s_120"] == 197.0, by.get(("*", 2)))

print()
print("drawn against corrected, frame by frame")
place = rl.effort_frame_finder(frames)
csens = rl.effort_sensitivity(C, (30, 60, 120), place)
s_by = rl.effort_by_tile(sens, keys[:1], "mean")
c_by = rl.effort_by_tile(csens, [("T1", "ANNA", ""), ("T2", "ANNA", "")],
                         "sum")
prows, pooled = rl.effort_paired_table(s_by, c_by, 60, {"T1": 2500.0},
                                       {"T1": ("MASSI", "1", "ANNA")})
t.ok("one frame in both, and the pooled row last",
     [r["tile_id"] for r in prows] == ["T1", "*"], prows)
t.near("ratio 10/182 on T1", prows[0]["ratio_T"], 10 / 182)
t.near("at 120 s 10/257", prows[0]["ratio_120"], 10 / 257)
t.ok("who drew and who corrected", prows[0]["scratch_operator"] == "MASSI"
     and prows[0]["correct_operator"] == "ANNA")
t.ok("pooled: one frame, so no interval", prows[1]["n_frames"] == 1
     and prows[1]["ci_low_T"] != prows[1]["ci_low_T"])
t.ok("and the pooled result at every limit", sorted(pooled) == [30, 60, 120])

print()
print("totals, legacy rows, the rule")
tot = rl.effort_totals(frows)
t.near("frames with no journal time count in neither time nor area",
       tot["T"]["min_per_ha"], 182 / 60 / 0.25)
t.near("and at 30 s", tot[30]["active_s"], 132)
ops = [{"n": i + 1, "when": w, "operator": "ann", "into": "mud flow",
        "x": 10, "y": 10, "pixels": 4, "changed_m2": 1.5}
       for i, w in enumerate(whens)]
legacy, bad = rl.effort_legacy_rows(ops, {"mud flow": 2})
t.ok("operations.csv as journal rows: correct marks, no duration",
     len(legacy) == 4 and not bad and all(
         r["action"] == "correct" and r["dur_ms"] == 0
         and r["class_code"] == 2 and r["operator"] == "ANN"
         for r in legacy))
for theta, want in ((60, 30), (30, 30), (120, 100)):
    lr = rl.effort_attribute(legacy, theta, place)
    t.near("fixture L placed in T1, idle %d s: %d s" % (theta, want),
           lr["frames"][("T1", "ANN", "")]["active_s"], want)
t.ok("the changed ground per frame",
     rl.effort_changed_by(legacy, place) == {("T1", "ANN", ""): 6.0})
untiled = rl.effort_attribute(
    [row("open", 0, tile=""), row("stroke", 20, 10, 1, tile="")], 60,
    default_tile="*")
t.near("a campaign with no frames is one frame, '*'",
       untiled["frames"][("*", "MASSI", "1")]["active_s"], 20)
t.ok("the rule with the limit written in",
     "longer than 60 s" in rl.effort_rule(60)
     and "longer than 60 s" in rl.effort_parameters(60)["rule"]
     and rl.effort_parameters(60)["thresholds"] == [30, 60, 120])

t.done()
