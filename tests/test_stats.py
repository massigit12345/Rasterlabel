"""The statistics of the reports, against numbers worked out by hand.

stats.py has the pieces Time and Uncertainty need and nothing installs for
them. Each is checked on a fixture it serves:

- the Wilcoxon signed-rank test on five log-ratios all below 0: W+ = 0 and
  the exact two-sided p = 2/32 = 0.0625; with ties, against every one of
  the 2**n sign patterns counted out; and the normal approximation beside
  the exact one where both apply;
- the cluster ratio estimator (Cochran 1977) on three places, (2, 10),
  (0, 10) and (4, 20): R = 0.15, V = 0.002296875 with N = 10, SE 0.0479257,
  and 0.0572822 without the finite population correction;
- the calibration fixture of Uncertainty: a 10 x 10 map with u8 = 20r + 2c
  and a pixel changed where c < r. Decile cuts [18, 38, ..., 178], decile d
  is row d, its share changed d/10, the AUC of u for the changed pixels
  exactly 0.8, and the capture curve; the same grid read as a probability
  for the ECE, 0.065748;
- ties that collapse the deciles, and a single level;
- the bootstrap of a geometric mean, seeded.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import itertools
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purekit

rl = purekit.load("stats")
t = purekit.Checks()
nan = purekit.isnan

print("Wilcoxon signed rank")
logs = [-1.0, -0.5, -0.2, -0.8, -0.6]
w = rl.st_wilcoxon_signed(logs)
t.ok("five negatives: W+ = 0", w["w_plus"] == 0.0, w)
t.near("exact two-sided p = 2/32", w["p"], 0.0625)
t.ok("and it says exact", w["method"] == "exact")
w = rl.st_wilcoxon_signed([-x for x in logs])
t.near("five positives: the same p", w["p"], 0.0625)
t.ok("W+ = 15", w["w_plus"] == 15.0)
t.ok("zeros are dropped", rl.st_wilcoxon_signed([0, 0] + logs)["n"] == 5)
t.ok("all zeros: no test, no exception",
     nan(rl.st_wilcoxon_signed([0.0, 0.0])["p"]))


def brute(values):
    """Every sign pattern of the ranks, counted out."""
    v = [x for x in values if x != 0]
    a = sorted(abs(x) for x in v)
    rank = {}
    for x in set(a):
        where = [i + 1 for i, y in enumerate(a) if y == x]
        rank[x] = sum(where) / len(where)
    r = [rank[abs(x)] for x in v]
    obs = sum(rk for rk, x in zip(r, v) if x > 0)
    sums = [sum(rk for rk, s in zip(r, signs) if s)
            for signs in itertools.product((0, 1), repeat=len(r))]
    up = sum(1 for s in sums if s >= obs - 1e-12) / len(sums)
    lo = sum(1 for s in sums if s <= obs + 1e-12) / len(sums)
    return min(1.0, 2 * min(up, lo))


tied = [1.0, -1.0, 2.0, 2.0, -3.0, 4.0, 4.0, 4.0, -0.5]
t.near("with ties: exact p equals the count of every sign pattern",
       rl.st_wilcoxon_signed(tied)["p"], brute(tied), 1e-12)
mixed = [0.3, -0.1, 0.25, 0.4, -0.05, 0.2, 0.15, -0.3, 0.6, 0.35]
t.near("and without ties", rl.st_wilcoxon_signed(mixed)["p"], brute(mixed),
       1e-12)
rng = np.random.default_rng(3)
many = list(rng.normal(0.3, 1.0, 40))
exact = rl.st_wilcoxon_signed(many, exact_max=40)
approx = rl.st_wilcoxon_signed(many)
t.ok("above 25 values the normal approximation is used",
     approx["method"].startswith("normal"))
t.near("and it is close to the exact p", approx["p"], exact["p"], 0.01)

print()
print("the cluster ratio estimator, T7")
r = rl.st_ratio_se([2, 0, 4], [10, 10, 20], N=10)
t.near("R = 6/40 = 0.15", r["R"], 0.15)
# residuals 0.5, -1.5, 1.0: squares 3.5, over m - 1 = 1.75, over
# m xbar^2 = 3 (40/3)^2 = 533.33, times 1 - 3/10
t.near("V = 0.002296875", r["se"] ** 2, 0.002296875, 1e-12)
t.near("SE = 0.0479257", r["se"], 0.0479257, 1e-7)
t.near("the fpc is 0.7", r["fpc"], 0.7)
r = rl.st_ratio_se([2, 0, 4], [10, 10, 20])
t.near("without the fpc: SE 0.0572822", r["se"], 0.0572822, 1e-7)
r = rl.st_ratio_se([2], [10], N=10)
t.ok("one place: R but no SE", r["R"] == 0.2 and nan(r["se"]))
t.ok("no place: neither", nan(rl.st_ratio_se([], [])["R"]))

print()
print("the calibration fixture, T5: u8 = 20r + 2c, changed where c < r")
rows_, cols_ = np.mgrid[0:10, 0:10]
u8 = 20 * rows_ + 2 * cols_
marks = cols_ < rows_
h_all = np.bincount(u8.ravel(), minlength=255)
h_chg = np.bincount(u8[marks].ravel(), minlength=255)
h_unc = h_all - h_chg
t.ok("45 changed, 55 not", h_chg.sum() == 45 and h_unc.sum() == 55)
cuts = rl.st_decile_cuts(h_all)
t.ok("decile cuts [18, 38, ..., 178]", cuts == list(range(18, 179, 20)),
     cuts)
cal = rl.st_calibration(h_all, h_chg, "decile")
t.ok("ten deciles of ten pixels", len(cal) == 10
     and all(c["n"] == 10 for c in cal))
t.ok("decile d holds d changed: share 0.0, 0.1, ..., 0.9",
     np.allclose([c["share"] for c in cal], np.arange(10) / 10.0))
t.ok("mean u of decile d = (20d + 9)/254",
     np.allclose([c["mean_u"] for c in cal],
                 [(20 * d + 9) / 254.0 for d in range(10)]))
t.near("the first is 0.035433", cal[0]["mean_u"], 0.035433, 1e-6)
t.near("the last is 0.744094", cal[-1]["mean_u"], 0.744094, 1e-6)
t.ok("u_low and u_high are the levels present",
     cal[0]["u_low"] == 0.0 and abs(cal[0]["u_high"] - 18 / 254) < 1e-12)
t.ok("a level equal to a cut belongs to the lower decile",
     int(rl.st_bin_of([18], cuts)[0]) == 0
     and int(rl.st_bin_of([19], cuts)[0]) == 1)
t.near("AUC of u for the changed pixels = 0.8", rl.st_auc_hist(h_chg, h_unc),
       0.8, 1e-12)
# the same, pixel by pixel, the long way
pos = u8[marks].ravel()
neg = u8[~marks].ravel()
wins = sum((p > n_) + 0.5 * (p == n_) for p in pos for n_ in neg)
t.near("which is the Mann-Whitney count over every pair", wins / (45 * 55),
       0.8, 1e-12)
cap = {round(c["top_share"], 2): c for c in rl.st_capture(h_all, h_chg)}
t.ok("top 10 %: threshold 180/254", cap[0.1]["level"] == 180, cap[0.1])
t.near("and 0.2 of the changes", cap[0.1]["share_of_changes_captured"], 0.2)
t.ok("top 20 %: threshold 160/254", cap[0.2]["level"] == 160)
t.near("and 17/45 of the changes", cap[0.2]["share_of_changes_captured"],
       17 / 45)
t.ok("top 50 %: threshold 100/254", cap[0.5]["level"] == 100)
t.near("and 35/45 of the changes", cap[0.5]["share_of_changes_captured"],
       35 / 45)
t.near("the whole map holds every change",
       cap[1.0]["share_of_changes_captured"], 1.0)
t.near("u_threshold is the level over 254", cap[0.1]["u_threshold"],
       180 / 254)

print()
print("ECE on the same grid read as a probability, T6")
fixed = rl.st_calibration(h_all, h_chg, "fixed")
got = [(c["bin"], c["n"], c["changed"]) for c in fixed]
want = [(0, 13, 1), (1, 13, 2), (2, 13, 3), (3, 12, 5), (4, 13, 8),
        (5, 13, 9), (6, 12, 8), (7, 11, 9)]
t.ok("fixed bins (n, changed) as worked out", got == want, got)
ece = rl.st_ece([c["n"] for c in fixed], [c["share"] for c in fixed],
                [c["mean_u"] for c in fixed])
t.near("ECE = 0.065748", ece, 0.065748, 1e-6)
t.ok("an empty bin is left out of the ECE",
     abs(rl.st_ece([10, 0], [0.5, 0.9], [0.4, 0.1]) - 0.1) < 1e-12)

print()
print("ties, T8")
h3 = np.zeros(255)
h3[[0, 127, 254]] = 100
t.ok("three levels a third each: cuts [0, 127]",
     rl.st_decile_cuts(h3) == [0, 127], rl.st_decile_cuts(h3))
rows3 = rl.st_calibration(h3, np.zeros(255))
t.ok("three rows of 100", [r_["n"] for r_ in rows3] == [100, 100, 100])
t.ok("u 0, 0.5, 1", [(r_["u_low"], r_["u_high"]) for r_ in rows3]
     == [(0.0, 0.0), (127 / 254, 127 / 254), (1.0, 1.0)])
h1 = np.zeros(255)
h1[40] = 50
c1 = np.zeros(255)
c1[40] = 20
t.ok("one level: one row", len(rl.st_calibration(h1, c1)) == 1)
t.near("and AUC 0.5", rl.st_auc_hist(c1, h1 - c1), 0.5)
t.ok("nothing changed: AUC undefined", nan(rl.st_auc_hist(np.zeros(255), h1)))

print()
print("bootstrap of a statistic")
gm = lambda v: math.exp(float(v.mean()))
b1 = rl.st_bootstrap_stat(logs, gm, 2000, 1)
b2 = rl.st_bootstrap_stat(logs, gm, 2000, 1)
t.near("the geometric mean is exp(-0.62) = 0.5379", b1["estimate"],
       math.exp(-0.62), 1e-12)
t.ok("the same seed gives the same interval", b1["ci"] == b2["ci"])
t.ok("lo <= estimate <= hi", b1["ci"][0] <= b1["estimate"] <= b1["ci"][1])
t.ok("every replicate defined", b1["n_valid"] == 2000)
t.ok("the seed is recorded", b1["seed"] == 1 and b1["n_boot"] == 2000)
t.ok("n_boot 0: no interval, with a reason",
     rl.st_bootstrap_stat(logs, gm, 0, 1)["ci"] is None)
t.ok("one value: no interval", rl.st_bootstrap_stat([1.0], gm, 100, 1)
     ["reason"].startswith("fewer"))
lo, hi = rl.st_percentile_ci(list(range(101)))
t.ok("the percentile interval of 0..100 is 2.5..97.5",
     (lo, hi) == (2.5, 97.5), (lo, hi))
t.ok("no defined replicate: both ends NaN",
     all(nan(x) for x in rl.st_percentile_ci([float("nan")])))

t.done()
