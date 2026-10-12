"""The arithmetic of uncertainty-guided correction, against numbers worked
out by hand.

uncertainty.py taken out of the shipped file with stats and reports, and
nothing else (purekit): no QGIS, no GDAL, no Qt.

T1  the kind and the scale guessed from a band's name: "probabilita x255"
    a probability on 255, "entropia x255" an entropy, "classe", "validita"
    and "Band 3" nothing (and 10000 for a UInt16 that stays under it),
    "margin_p1_p2" a margin on 1, "votes" only beside "readings_labelled";
T2  a probability on 255, [255, 128, 51, 0] -> [0, 127, 203, 255]: 0 under
    a class is no value;
T3  an entropy whose nodata is 0, [0, 255, 51] -> [0, 254, 51], the 0 read
    as a value and counted; under the class nodata, no value at all;
T4  votes [2, 1, 0, 0] of [2, 2, 3, 0] readings -> [0, 127, 254, 255];
T5  the calibration fixture, 10 x 10, u8 = 20r + 2c, changed where c < r:
    the decile cuts, a share d/10 in decile d, mean u (20d + 9)/254, an AUC
    of exactly 0.8, and the capture curve;
T6  the same grid read as a probability: the fixed bins, ECE 0.065748, the
    expected error equal to mean u;
T7  the cluster ratio estimator on three places, with and without the
    finite population correction, and none with one place;
T8  ties that collapse the deciles, and a single level: one row, AUC 0.5,
    "no ranking possible";
T9  the blocks of a 4 x 4 map: one too empty to be a place, the ranks, the
    tie broken by the maximum and then row by row;
T10 the walk: every third place drawn from the seeded permutation, a place
    already done joining the random sample without a visit, Skip, ◀, and
    the file read back giving the same next place;
T11 a record of changes started again after the strokes: the report is
    refused and nothing is written; a net change the record does not hold
    makes the record inconsistent in the summary.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purekit                                                     # noqa: E402

rl = purekit.load("stats", "reports", "uncertainty")
t = purekit.Checks()
root = tempfile.mkdtemp(prefix="rl_unc_math_")

try:
    print("uncertainty.py needs neither QGIS nor Qt")
    import ast
    tree = ast.parse(open(os.path.join(purekit.PKG, "uncertainty.py"),
                          encoding="utf-8").read())
    top = sorted(set((n.module or "").split(".")[0] if isinstance(
        n, ast.ImportFrom) and not n.level else a.name.split(".")[0]
        for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
        and not getattr(n, "level", 0) for a in n.names))
    t.ok("no QGIS and no Qt at its top: the picture imports Qt when it is "
         "drawn", not [m for m in top if m in ("qgis", "PyQt5", "PyQt6")],
         top)

    print()
    print("T1 the kind and the scale, from the name of the band")
    kind, scale = rl.unc_guess_kind, rl.unc_guess_scale
    t.ok("'probabilita x255', Byte: probability on 255",
         (kind("probabilita x255"), scale("probabilita x255", "Byte"))
         == ("probability", 255.0))
    t.ok("'entropia x255': entropy on 255",
         (kind("entropia x255"), scale("entropia x255", "Byte"))
         == ("entropy", 255.0))
    t.ok("'classe' says nothing", kind("classe") is None)
    t.ok("'validita' says nothing", kind("validita") is None)
    t.ok("'margin_p1_p2', Float32: margin on 1",
         (kind("margin_p1_p2"), scale("margin_p1_p2", "Float32"))
         == ("margin", 1.0))
    t.ok("'votes' beside 'readings_labelled': votes",
         kind("votes", ["votes", "readings_labelled"]) == "votes")
    t.ok("'votes' alone is not", kind("votes", ["votes"]) is None)
    t.ok("'Band 3', UInt16 up to 9000: no kind, a scale of 10000",
         kind("Band 3") is None
         and scale("Band 3", "UInt16", None, 9000) == 10000.0)
    t.ok("and 65535 when it goes higher",
         scale("Band 3", "UInt16", None, 40000) == 65535.0)
    t.ok("a GDAL scale set: the read applies it, scale 1",
         scale("Band 2", "Int16", 0.001) == 1.0)
    t.ok("an Int32 with nothing said: ask", scale("x", "Int32") is None)

    print()
    print("T2 a probability on 255")
    spec = {"kind": "probability", "scale": 255.0}
    u8, said = rl.unc_to_u8(np.array([255, 128, 51, 0]), None, spec,
                            np.ones(4, bool))
    t.ok("[255, 128, 51, 0] -> [0, 127, 203, 255]",
         u8.tolist() == [0, 127, 203, 255], u8.tolist())
    t.ok("the 0 under a class is the one with no value",
         said["no_value"] == 1 and said["valid_px"] == 3, said)
    nan = rl.unc_to_u8(np.array([np.nan, 0.5]), None,
                       {"kind": "probability", "scale": 1.0},
                       np.ones(2, bool))[0]
    t.ok("a Float32 probability with NaN: no value there",
         nan.tolist() == [255, 127], nan.tolist())

    print()
    print("T3 an entropy whose nodata is 0")
    spec = {"kind": "entropy", "scale": 255.0}
    u8, said = rl.unc_to_u8(np.array([0, 255, 51]), None, spec,
                            np.ones(3, bool), band_nodata=0)
    t.ok("[0, 255, 51] -> [0, 254, 51]", u8.tolist() == [0, 254, 51],
         u8.tolist())
    t.ok("the 0 is read as a value, and counted",
         said["zero_read_as_value"] == 1, said)
    u8, said = rl.unc_to_u8(np.array([0, 255, 51]), None, spec,
                            np.zeros(3, bool), band_nodata=0)
    t.ok("under the class nodata: no value at all",
         u8.tolist() == [255, 255, 255] and said["zero_read_as_value"] == 0,
         (u8.tolist(), said))
    u8, said = rl.unc_to_u8(np.array([-10.0, 300.0]), None,
                            {"kind": "uncertainty", "scale": 255.0},
                            np.ones(2, bool))
    t.ok("values outside 0-1 are clipped, and counted",
         u8.tolist() == [0, 254] and said["clipped_px"] == 2, said)

    print()
    print("T4 the votes of a consensus")
    u8, said = rl.unc_to_u8(np.array([2, 1, 0, 0]), np.array([2, 2, 3, 0]),
                            {"kind": "votes", "scale": 1.0},
                            np.ones(4, bool))
    t.ok("u = 1 - votes / labelled -> [0, 127, 254, 255]",
         u8.tolist() == [0, 127, 254, 255], u8.tolist())

    print()
    print("T5 the calibration fixture")
    r = np.arange(10)[:, None]
    c = np.arange(10)[None, :]
    U8 = (20 * r + 2 * c).astype(np.uint8)
    MARKS = (c < r).astype(np.uint8)
    t.ok("45 changed, 55 not", int(MARKS.sum()) == 45)
    cal = rl.unc_calibrate(U8, MARKS, None, None, "uncertainty")
    t.ok("decile cuts [18, 38, ..., 178]",
         cal["cuts"] == [18, 38, 58, 78, 98, 118, 138, 158, 178], cal["cuts"])
    dec = [x for x in cal["rows"] if x["scope"] == "whole_map"
           and x["binning"] == "decile"]
    t.ok("ten deciles of ten pixels", len(dec) == 10
         and all(x["n_px"] == 10 for x in dec), [x["n_px"] for x in dec])
    t.ok("decile d has d changed: share 0.0, 0.1, ..., 0.9",
         [x["changed_px"] for x in dec] == list(range(10))
         and all(abs(x["share_changed"] - d / 10.0) < 1e-12
                 for d, x in enumerate(dec)))
    t.ok("mean u (20d + 9)/254",
         all(abs(x["mean_u"] - (20 * d + 9) / 254.0) < 1e-12
             for d, x in enumerate(dec)), [x["mean_u"] for x in dec][:3])
    t.ok("the whole map is labelled a lower bound",
         all(x["note"] == rl.UNC_NOTE_WHOLE for x in dec))
    t.near("AUC = 0.8 exactly", cal["auc"]["whole_map"], 0.8, 1e-12)
    t.ok("no expected error for a kind that is not a probability",
         all(x["expected_error"] is None for x in dec))
    cap = {round(x["top_share"], 2): x for x in cal["capture"]
           if x["scope"] == "whole_map"}
    t.near("top 10 %: u from 180/254", cap[0.1]["u_threshold"], 180 / 254.0)
    t.near("and 20 % of the changes", cap[0.1]["share_of_changes_captured"],
           0.2)
    t.near("top 20 %: u from 160/254", cap[0.2]["u_threshold"], 160 / 254.0)
    t.near("and 17/45 of the changes",
           cap[0.2]["share_of_changes_captured"], 17 / 45.0, 1e-9)
    t.near("top 50 %: u from 100/254", cap[0.5]["u_threshold"], 100 / 254.0)
    t.near("and 35/45 of the changes",
           cap[0.5]["share_of_changes_captured"], 35 / 45.0, 1e-9)
    t.ok("no random place done: no curve for them",
         cal["auc"]["random_places"] is None
         and not [x for x in cal["rows"] if x["scope"] != "whole_map"])

    print()
    print("T6 the same grid, read as a probability")
    p_raw = 254 - U8.astype(np.int64)
    u8p, _ = rl.unc_to_u8(p_raw, None, {"kind": "probability",
                                        "scale": 254.0},
                          np.ones(U8.shape, bool))
    t.ok("1 - p gives the same bytes back", np.array_equal(u8p, U8))
    cal = rl.unc_calibrate(u8p, MARKS, None, None, "probability")
    fixed = [x for x in cal["rows"] if x["scope"] == "whole_map"
             and x["binning"] == "fixed"]
    t.ok("fixed bins (n, changed): 13/1 13/2 13/3 12/5 13/8 13/9 12/8 11/9",
         [(x["bin"], x["n_px"], x["changed_px"]) for x in fixed]
         == [(0, 13, 1), (1, 13, 2), (2, 13, 3), (3, 12, 5), (4, 13, 8),
             (5, 13, 9), (6, 12, 8), (7, 11, 9)],
         [(x["bin"], x["n_px"], x["changed_px"]) for x in fixed])
    t.near("ECE = 0.065748", cal["ece"]["whole_map"], 0.065748, 1e-6)
    t.ok("the expected error is mean u",
         all(x["expected_error"] == x["mean_u"] for x in fixed))

    print()
    print("T7 the cluster ratio estimator")
    got = rl.st_ratio_se([2, 0, 4], [10, 10, 20], 10)
    t.near("R = 0.15", got["R"], 0.15)
    t.near("V = 0.002296875 with m = 3 of N = 10", got["se"] ** 2,
           0.002296875, 1e-12)
    t.near("SE 0.0479257", got["se"], 0.0479257, 1e-7)
    t.near("SE 0.0572822 without the fpc",
           rl.st_ratio_se([2, 0, 4], [10, 10, 20])["se"], 0.0572822, 1e-7)
    p_all = np.zeros((3, 255), np.int64)
    p_chg = np.zeros((3, 255), np.int64)
    for k, (y, x) in enumerate(((2, 10), (0, 10), (4, 20))):
        p_all[k, 50], p_chg[k, 50] = x, y
    rows = rl.unc_scope_rows("random_places", p_all.sum(0), p_chg.sum(0),
                             np.zeros(255, np.int64), [], "uncertainty",
                             p_all, p_chg, 10)
    t.near("in the rows of the random places, the same SE",
           rows[0]["se_share"], 0.0479257, 1e-7)
    t.ok("labelled design-based", rows[0]["note"] == rl.UNC_NOTE_RANDOM)
    t.near("and a 95 % interval of 1.96 SE", rows[0]["ci95_high"],
           0.15 + 1.96 * 0.0479257, 1e-6)
    rows = rl.unc_scope_rows("purposive_places", p_all.sum(0), p_chg.sum(0),
                             np.zeros(255, np.int64), [], "uncertainty",
                             p_all, p_chg, 10)
    t.near("the purposive places: without the fpc", rows[0]["se_share"],
           0.0572822, 1e-7)
    t.ok("labelled a spread, not a design-based SE",
         rows[0]["note"] == rl.UNC_NOTE_PURPOSIVE)
    rows = rl.unc_scope_rows("random_places", p_all[:1].sum(0),
                             p_chg[:1].sum(0), np.zeros(255, np.int64), [],
                             "uncertainty", p_all[:1], p_chg[:1], 10)
    t.ok("one place: no SE", rows[0]["se_share"] is None
         and rl.st_ratio_se([2], [10], 10)["se"] != rl.st_ratio_se(
             [2], [10], 10)["se"])

    print()
    print("T8 ties, and a single level")
    tied = np.repeat(np.array([0, 127, 254], np.uint8), 100).reshape(3, 100)
    marks = np.zeros(tied.shape, np.uint8)
    marks[2, :40] = 1
    cal = rl.unc_calibrate(tied, marks, None, None, "uncertainty")
    t.ok("the cuts collapse to [0, 127]", cal["cuts"] == [0, 127],
         cal["cuts"])
    dec = [x for x in cal["rows"] if x["binning"] == "decile"]
    t.ok("three deciles of 100", [x["n_px"] for x in dec] == [100] * 3,
         [x["n_px"] for x in dec])
    t.ok("u_low, u_high 0/0, 0.5/0.5, 1/1",
         [(x["u_low"], x["u_high"]) for x in dec]
         == [(0.0, 0.0), (0.5, 0.5), (1.0, 1.0)])
    one = np.full((4, 25), 127, np.uint8)
    marks = np.zeros(one.shape, np.uint8)
    marks[0, :10] = 1
    cal = rl.unc_calibrate(one, marks, None, None, "uncertainty")
    dec = [x for x in cal["rows"] if x["binning"] == "decile"]
    t.ok("a single level: one row", len(dec) == 1, len(dec))
    t.near("AUC 0.5", cal["auc"]["whole_map"], 0.5)
    t.ok("and said to be a single level", cal["single_level"])
    folder = os.path.join(root, "single")
    os.makedirs(folder)
    res = rl.unc_report({"kind": "correction", "id": "abc", "name": "one",
                         "folder": folder}, {"name": "one", "id": "abc"},
                        {"kind": "uncertainty", "scale": 254.0},
                        {"u8": one, "marks": marks, "net": None}, None, {},
                        operations=1, draw=False)
    t.ok("the report says no ranking is possible",
         any("no ranking possible" in n for n in res["summary"]["notes"]),
         res["summary"]["notes"])

    print()
    print("T9 the blocks of a 4 x 4 map")
    u = np.zeros((4, 4), np.uint8)
    u[:2, :2] = 51            # 0.2
    u[:2, 2:] = 229           # 0.9
    u[2:, :2] = 127           # 0.5
    u[2:, 2:] = 229
    u[2, 2] = u[2, 3] = u[3, 2] = 255      # three class pixels of nodata
    blocks = rl.unc_score_blocks(u, 2)
    t.ok("four blocks, three of them eligible (BR is 25 % valid)",
         blocks["eligible"].tolist() == [True, True, True, False],
         blocks["eligible"].tolist())
    ranked = [(int(blocks["bi"][b]), int(blocks["bj"][b]))
              for b in rl.unc_rank(blocks)]
    t.ok("ranks: TR 1, BL 2, TL 3", ranked == [(0, 1), (1, 0), (0, 0)],
         ranked)
    places = rl.Places.from_blocks(os.path.join(root, "t9.csv"), blocks,
                                   (0.0, 1.0, 0.0, 0.0, 0.0, -1.0), 4, 4, 1)
    t.ok("N = 3", places.N == 3)
    t.near("mean u of TL 51/254", places.by_id["b0_0"]["mean_u"], 51 / 254.)
    tie = np.zeros((2, 6), np.uint8)
    tie[:, 0:2] = [[100, 100], [100, 100]]
    tie[:, 2:4] = [[50, 150], [100, 100]]          # same mean, higher max
    tie[:, 4:6] = [[100, 100], [100, 100]]
    order = [int(blocks_j) for blocks_j in
             rl.unc_score_blocks(tie, 2)["bj"][rl.unc_rank(
                 rl.unc_score_blocks(tie, 2))]]
    t.ok("equal means: the higher maximum first, then left to right",
         order == [1, 0, 2], order)
    sliver = np.full((4, 4), 255, np.uint8)
    sliver[:, 0] = 10
    t.ok("a sliver one pixel wide is no place",
         not rl.unc_score_blocks(sliver, 4)["eligible"].any())
    t.ok("the side is raised until the map holds no more than MAX_PLACES",
         rl.unc_side_for(1000000, 1000000, 256, 200000) > 256
         and rl.unc_side_for(100000, 100000, 256, 200000) == 256)

    print()
    print("T10 the walk")
    grid = np.zeros((8, 10), np.uint8)
    for k in range(20):
        i, j = divmod(k, 5)
        grid[2 * i:2 * i + 2, 2 * j:2 * j + 2] = 10 + 12 * k
    blocks = rl.unc_score_blocks(grid, 2)
    path = os.path.join(root, "places.csv")
    walk = rl.Places.from_blocks(path, blocks, (0.0, 1.0, 0.0, 8.0, 0.0,
                                                -1.0), 10, 8, 7, 3, True)
    t.ok("N = 20", walk.N == 20)
    perm = np.random.default_rng(7).permutation(20)
    ids = ["b%d_%d" % divmod(int(k), 5) for k in perm]
    t.ok("random_order follows default_rng(7).permutation(20)",
         [r["place_id"] for r in sorted(walk.rows,
                                        key=lambda r: r["random_order"])]
         == ids)
    # the walk as the rule says, worked out apart from the class
    by_rank = sorted(walk.rows, key=lambda r: r["purposive_rank"])
    want, seen, draws = [], set(), 0
    joined_want = []
    while len(seen) < 20:
        k = len(want)
        if (k + 1) % 3 == 0 and draws < 20:
            while draws < 20 and ids[draws] in seen:
                joined_want.append(ids[draws])
                draws += 1
            if draws < 20:
                want.append(("random", ids[draws]))
                seen.add(ids[draws])
                draws += 1
                continue
        rest = [r["place_id"] for r in by_rank if r["place_id"] not in seen]
        if not rest:
            break
        want.append(("purposive", rest[0]))
        seen.add(rest[0])
    got = []
    first = walk.next("t")
    t.ok("the first place is the most uncertain",
         first["place_id"] == by_rank[0]["place_id"]
         and first["selection"] == "purposive")
    walk.done("ANNA", "t", False, 0)
    got.append((first["selection"], first["place_id"]))
    skipped = None
    while True:
        row = walk.next("t")
        if row is None:
            break
        got.append((row["selection"], row["place_id"]))
        if row["selection"] == "random" and skipped is None:
            skipped = row["place_id"]
            walk.skip("t")
        else:
            walk.done("ANNA", "t", False, 1)
        if len(got) == 7:
            mid = list(walk.upcoming(3))
            back = walk.back(walk.offered()[-1])
            before = [(r["place_id"], r["status"]) for r in walk.rows]
            t.ok("◀ gives the place before and changes no status",
                 back is not None and back["offer_no"] == 6
                 and before == [(r["place_id"], r["status"])
                                for r in walk.rows])
            walk.save()
            again = rl.Places(path, 2, 7, 3, True).load()
            t.ok("read back, the walk goes on to the same places",
                 [r["place_id"] for r in again.upcoming(3)]
                 == [r["place_id"] for r in mid])
            # a name that begins like a formula is quoted in the file and
            # comes back as it was, however often it is saved
            again.path = path + ".copy"
            again.rows[0]["operator"] = "@ANNA"
            again.save()
            for trip in (1, 2):
                twice = rl.Places(again.path, 2, 7, 3, True).load()
                t.ok("an operator that begins with @ is the same after %d "
                     "trip%s through the file" % (trip, "" if trip == 1
                                                  else "s"),
                     twice.rows[0]["operator"] == "@ANNA",
                     twice.rows[0]["operator"])
                twice.save()
    t.ok("offers 3, 6, 9, ... are random, in the order of the permutation",
         got[:len(want)] == want, (got[:8], want[:8]))
    t.ok("every offer is the k-th: random exactly where 3 divides k",
         all((sel == "random") == ((k + 1) % 3 == 0)
             for k, (sel, _) in enumerate(got[:9])))
    c = walk.counts()
    joined = [r for r in walk.rows if r["design_use"] == rl.UNC_DESIGN_REUSED]
    t.ok("places drawn after they were done as purposive joined the "
         "random sample without a visit", len(joined) > 0
         and len(got) == 20 and len(set(p for _, p in got)) == 20
         and sorted(r["place_id"] for r in joined) == sorted(joined_want),
         (len(joined), len(got), sorted(r["place_id"] for r in joined), sorted(joined_want)))
    t.ok("they are random now, with their purposive rank kept",
         all(r["selection"] == "random" and r["purposive_rank"]
             for r in joined))
    rnd = sorted((r for r in walk.rows if r["selection"] == "random"),
                 key=lambda r: r["random_order"])
    t.ok("the random places are the first m of the permutation",
         [r["place_id"] for r in rnd] == ids[:len(rnd)])
    t.ok("m counts them, and the one skipped",
         c["random_drawn_m"] == len(rnd) and c["random_skipped"] == 1, c)
    t.ok("the skipped place is skipped",
         walk.by_id[skipped]["status"] == "skipped")
    t.near("inclusion probability m/N", walk.inclusion(), len(rnd) / 20.0)
    t.ok("nothing left", not walk.remaining() and walk.next() is None)
    # the skipped place counts in no curve
    marks = np.ones(grid.shape, np.uint8)
    cal = rl.unc_calibrate(grid, marks, None, walk, "uncertainty")
    t.ok("a skipped place is in no scope",
         skipped not in [r["place_id"] for r in cal["place_rows"]])

    print()
    print("T11 the record of changes")
    folder = os.path.join(root, "restarted")
    os.makedirs(folder)
    owner = {"kind": "correction", "id": "c0ffee", "name": "fix",
             "folder": folder}
    refused = None
    try:
        rl.unc_report(owner, {"name": "fix"}, {"kind": "uncertainty",
                                               "scale": 254.0},
                      {"u8": U8, "marks": np.zeros(U8.shape, np.uint8),
                       "net": None}, None, {"changes": "x_changes.tif"},
                      operations=5, draw=False)
    except rl.UncRefused as err:
        refused = str(err)
    t.ok("an empty record after 5 operations: refused, and said why",
         refused is not None and "started again" in refused
         and "5 operations" in refused, refused)
    t.ok("and nothing is written", os.listdir(folder) == [],
         os.listdir(folder))
    net = MARKS.copy()
    net[0, 9] = 1                       # changed, but not on the record
    res = rl.unc_report(owner, {"name": "fix", "grid": {"pixel_m": [1, 1]}},
                        {"kind": "uncertainty", "scale": 254.0},
                        {"u8": U8, "marks": MARKS, "net": net}, None,
                        {"changes": "x_changes.tif"}, operations=5,
                        draw=False)
    summary = json.load(open(os.path.join(res["folder"], "summary.json"),
                             encoding="utf-8"))
    t.ok("a net change the record does not hold: not consistent",
         summary["changes_record"]["consistent"] is False
         and summary["changes_record"]["net_not_marked_px"] == 1,
         summary["changes_record"])
    t.ok("the summary is a report of kind uncertainty, of this owner",
         summary["rasterlabel:report"] == "uncertainty"
         and summary["owner"]["id"] == "c0ffee"
         and summary["version"] == "1.1")
    t.ok("its headline has exactly the fixed keys",
         sorted(summary["headline"]) == sorted(
             ["kind", "auc_random", "auc_whole", "ece_random",
              "random_done", "purposive_done"]), summary["headline"])
    t.ok("in reports/uncertainty/<stamp>",
         os.path.dirname(res["folder"]) == os.path.join(
             folder, "reports", "uncertainty"), res["folder"])
    t.ok("with its tables", all(os.path.exists(os.path.join(
        res["folder"], f)) for f in ("calibration.csv", "capture.csv",
                                     "places.csv", "strokes.csv")))
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(t.done())
