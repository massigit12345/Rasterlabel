"""Every number a report prints, against an independent implementation.

The engines (agreement, stats, effort, journal, uncertainty, design, the
numbers of the model vs corrected report and of the dataset card) are held
here to straightforward re-implementations written in this file from the
published formulas, to numbers worked out on paper, and, where scipy is
installed, to scipy. Nothing here calls the engine to produce its own
expected value.

  M   the confusion matrix and what is read off it: overall agreement,
      Cohen's kappa (1960), quantity and allocation disagreement (Pontius
      and Millones 2011), exchange and shift (Pontius and Santacruz 2014;
      the worked example of Pontius 2019), IoU, Dice, producer's and user's
      accuracy; on random matrices and on the edge cases: an empty class, a
      class only A has, perfect agreement, no agreement at all, one class,
      two classes, the unlabelled row and column
  S   the spread over frames (quartiles by Hyndman and Fan's type 7), the
      percentile interval, and the frame bootstrap, rebuilt from its
      description; a sanity range from scipy.stats.bootstrap
  W   the Wilcoxon signed-rank test: exact against the enumeration of every
      sign pattern (zeros dropped, ties on mid-ranks); the normal
      approximation against the textbook formula; scipy where it applies
  T   active time from the gaps between events at 30, 60 and 120 s, a
      worked session, random sessions against a reference, and the live
      figure of the journal against the report's
  P   the paired scratch/correction ratio: the geometric mean of the
      per-frame ratios, its Wilcoxon p and its bootstrap interval
  V   model vs corrected: producer's and user's accuracy, IoU, F1, quantity
      and allocation per class, the net change of each FROM -> TO, the
      polygon bootstrap and the people side with kappa
  U   uncertainty: the conversion of probability, entropy, margin and votes
      to u, the AUC (against the pairwise count and scipy's Mann-Whitney U),
      the ECE, the calibration deciles, the capture curve, the cluster ratio
      estimator against a simulation, the ranking and the random places
  C   the card: the majority n // 2 + 1, the consensus of readings against
      a count by pixel, the closed share 0.995
  D   the design import: a weight is one over its inclusion probability

scipy is optional. Without it the checks that use it say SKIP, loudly, and
the run ends by counting them; RL_REQUIRE_SCIPY=1 (or --require-scipy of
tests/run.py) turns the skip into a failure. Everything else needs numpy
alone.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import collections
import itertools
import math
import os
import sys
import tempfile
import shutil

from datetime import datetime
from fractions import Fraction

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purekit                                                     # noqa: E402

try:
    import scipy
    import scipy.stats as sst
except ImportError:
    scipy = sst = None

rl = purekit.load("stats", "agreement", "reports", "design", "journal",
                  "effort", "correction", "model_vs_corrected", "card",
                  "uncertainty")
t = purekit.Checks()
nan = float("nan")
root = tempfile.mkdtemp(prefix="rl_reference_")
skipped = []


def need_scipy(what):
    """True when scipy is there; otherwise a loud SKIP line, counted."""
    if sst is not None:
        return True
    print("  SKIP  (scipy is not installed, NOT CHECKED) " + what)
    skipped.append(what)
    return False


def same(a, b, tol=1e-12):
    """Equal to a tolerance, NaN equal to NaN, None equal to None."""
    if a is None or b is None:
        return a is None and b is None
    a, b = float(a), float(b)
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def all_same(xs, ys, tol=1e-12):
    return len(xs) == len(ys) and all(same(x, y, tol) for x, y in zip(xs, ys))


def pct7(values, q):
    """The q-th percentile (0-100) by Hyndman and Fan's type 7, from the
    definition: h = (n - 1) q / 100 on the sorted values, interpolated."""
    v = sorted(float(x) for x in values)
    h = (len(v) - 1) * q / 100.0
    lo = int(math.floor(h))
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (h - lo) * (v[hi] - v[lo])


# --------------------------------------------------------------------- M
# The reference for a confusion matrix, from the formulas in the papers.
def ref_matrix(C):
    """The numbers of a K x K table of counts (rows A or the map, columns B
    or the reference) by the published formulas. NaN where undefined."""
    K = len(C)
    N = sum(sum(r) for r in C)
    out = {"n": N}
    row_c = [sum(C[i]) for i in range(K)]
    col_c = [sum(C[i][j] for i in range(K)) for j in range(K)]
    per = []
    for g in range(K):
        cgg = C[g][g]
        per.append({
            "iou": cgg / (row_c[g] + col_c[g] - cgg)
            if row_c[g] + col_c[g] - cgg else nan,
            "dice": 2.0 * cgg / (row_c[g] + col_c[g])
            if row_c[g] + col_c[g] else nan,
            "ua": cgg / row_c[g] if row_c[g] else nan,
            "pa": cgg / col_c[g] if col_c[g] else nan,
            "n_A": row_c[g], "n_B": col_c[g]})
    out["per"] = per
    if N == 0:
        for k in ("po", "pe", "kappa", "Q", "A", "E", "S"):
            out[k] = nan
        for g in range(K):
            per[g].update(q=nan, a=nan, e=nan, s=nan)
        out["mean_iou"] = nan
        return out
    p = [[C[i][j] / float(N) for j in range(K)] for i in range(K)]
    pr = [sum(p[i]) for i in range(K)]                 # p_g+
    pc = [sum(p[i][j] for i in range(K)) for j in range(K)]   # p_+g
    po = sum(p[g][g] for g in range(K))
    pe = sum(pr[g] * pc[g] for g in range(K))
    out["po"], out["pe"] = po, pe
    # Cohen (1960), in counts as Congalton writes it
    tr = sum(C[g][g] for g in range(K))
    cross = sum(row_c[g] * col_c[g] for g in range(K))
    den = N * N - cross
    out["kappa"] = (N * tr - cross) / float(den) if den else nan
    # Pontius and Millones (2011)
    out["Q"] = sum(abs(pc[g] - pr[g]) for g in range(K)) / 2.0
    out["A"] = sum(min(pr[g] - p[g][g], pc[g] - p[g][g]) for g in range(K))
    # Pontius and Santacruz (2014): pairs swapping places
    out["E"] = sum(2.0 * min(p[i][j], p[j][i])
                   for i in range(K) for j in range(i + 1, K))
    out["S"] = out["A"] - out["E"]
    ious = []
    for g in range(K):
        d_g = pr[g] + pc[g] - 2.0 * p[g][g]
        q_g = abs(pr[g] - pc[g])
        e_g = sum(2.0 * min(p[g][i], p[i][g]) for i in range(K) if i != g)
        per[g].update(q=q_g, a=d_g - q_g, e=e_g, s=d_g - q_g - e_g)
        if row_c[g] + col_c[g] > 0:
            ious.append(per[g]["iou"])
    out["mean_iou"] = sum(ious) / len(ious) if ious else nan
    return out


def check_matrix(name, C, unlabelled=None, kappa=True):
    """cm_metrics of C, against ref_matrix of the same table. With
    unlabelled, C has that code first (0) and the reference gets the rest."""
    C = np.asarray(C, dtype=np.int64)
    K = C.shape[0]
    codes = list(range(K))
    m = rl.cm_metrics(C, codes, unlabelled=unlabelled, kappa=kappa)
    inner = C[1:, 1:] if unlabelled is not None else C
    ref = ref_matrix(inner.tolist())
    o = m["overall"]
    ok = True
    pairs = [("po", o["po"], ref["po"]), ("pe", o["pe"], ref["pe"]),
             ("quantity", o["quantity"], ref["Q"]),
             ("allocation", o["allocation"], ref["A"]),
             ("exchange", o["exchange"], ref["E"]),
             ("shift", o["shift"], ref["S"]),
             ("mean_iou", o["mean_iou"], ref["mean_iou"])]
    if kappa:
        pairs.append(("kappa", o["kappa"], ref["kappa"]))
    else:
        ok &= "kappa" not in o
    bad = [(k, a, b) for k, a, b in pairs if not same(a, b)]
    for c, r in zip(m["per_class"], ref["per"]):
        for k, a, b in (("iou", c["iou"], r["iou"]), ("f1", c["f1"], r["dice"]),
                        ("rate_A", c["rate_A"], r["ua"]),
                        ("rate_B", c["rate_B"], r["pa"]),
                        ("q", c["q"], r["q"]), ("a", c["a"], r["a"]),
                        ("e", c["e"], r["e"]), ("s", c["s"], r["s"])):
            if not same(a, b):
                bad.append((c["code"], k, a, b))
        if (c["n_A"], c["n_B"]) != (r["n_A"], r["n_B"]):
            bad.append((c["code"], "counts"))
    if ref["n"] > 0 and not (abs(o["quantity"] + o["allocation"]
                                 - (1.0 - o["po"])) < 1e-12):
        bad.append(("Q + A != 1 - Po",))
    if ref["n"] > 0 and not same(ref["Q"] + ref["A"], 1.0 - ref["po"]):
        bad.append(("reference: Q + A != 1 - Po",))
    if unlabelled is not None:
        c = m["counts"]
        if (c["only_A"], c["only_B"], c["neither"], c["both"]) != (
                int(C[1:, 0].sum()), int(C[0, 1:].sum()), int(C[0, 0]),
                int(inner.sum())):
            bad.append(("counts of only A, only B, neither", c))
    return t.ok(name, ok and not bad, bad[:3])


print("M: a table worked out on paper")
# 100 pixels, rows A, columns B: [[40, 10], [5, 45]].
#   row sums 50 50, column sums 45 55; Po = 0.85; Pe = .5 * .45 + .5 * .55 =
#   0.5; kappa = (0.85 - 0.5) / 0.5 = 0.7; Q = (|.5-.45| + |.5-.55|) / 2 =
#   0.05; A = min(.1, .05) + min(.05, .1) = 0.10; Q + A = 0.15 = 1 - Po;
#   exchange 2 min(.10, .05) = 0.10, shift 0; IoU(1) = 40 / (50 + 45 - 40);
#   Dice(1) = 80 / 95; user's 40 / 50, producer's 40 / 45.
M0 = np.array([[40, 10], [5, 45]])
m0 = rl.cm_metrics(M0, [1, 2], unlabelled=None, kappa=True)
o0, c0 = m0["overall"], m0["per_class"]
t.near("Po 0.85", o0["po"], 0.85)
t.near("Pe 0.5", o0["pe"], 0.5)
t.near("kappa 0.7", o0["kappa"], 0.7)
t.near("quantity 0.05", o0["quantity"], 0.05)
t.near("allocation 0.10", o0["allocation"], 0.10)
t.near("exchange 0.10", o0["exchange"], 0.10)
t.near("shift 0", o0["shift"], 0.0, 1e-12)
t.near("IoU of class 1 is 40/55", c0[0]["iou"], 40.0 / 55.0)
t.near("Dice of class 1 is 80/95", c0[0]["f1"], 80.0 / 95.0)
t.near("user's accuracy of class 1 (from A) is 40/50", c0[0]["rate_A"], 0.8)
t.near("producer's accuracy of class 1 (from B) is 40/45", c0[0]["rate_B"],
       40.0 / 45.0)
t.near("mean IoU is the mean of 40/55 and 45/60", o0["mean_iou"],
       (40.0 / 55.0 + 45.0 / 60.0) / 2.0)

print()
print("M: the edge cases")
check_matrix("K = 1, 7 pixels", [[7]])
check_matrix("K = 1, no pixel", [[0]])
check_matrix("K = 2, all agreement", [[30, 0], [0, 70]])
check_matrix("K = 2, no agreement at all (a swap)", [[0, 30], [20, 0]])
check_matrix("K = 3, no agreement at all (a cycle)",
             [[0, 5, 0], [0, 0, 5], [5, 0, 0]])
check_matrix("K = 3, a class that neither has", [[5, 1, 0], [2, 6, 0],
                                                [0, 0, 0]])
check_matrix("K = 3, a class only A has", [[5, 1, 0], [2, 6, 0], [3, 4, 0]])
check_matrix("K = 3, a class only B has", [[5, 1, 2], [2, 6, 3], [0, 0, 0]])
check_matrix("K = 2, one class everywhere in both (Pe = 1)", [[9, 0], [0, 0]])
check_matrix("K = 2, A paints one class only, B two", [[3, 7], [0, 0]])
check_matrix("no pixel at all", np.zeros((3, 3), dtype=np.int64))
o1 = rl.cm_metrics(np.array([[9, 0], [0, 0]]), [1, 2], None, True)["overall"]
t.ok("Pe = 1: kappa is NaN, not 0 and not an error", math.isnan(o1["kappa"])
     and o1["pe"] == 1.0)
o2 = rl.cm_metrics(np.array([[0, 5], [5, 0]]), [1, 2], None, True)["overall"]
t.near("no agreement at all: Po 0, kappa -1", o2["kappa"], -1.0)
o3 = rl.cm_metrics(np.array([[0, 5], [5, 0]]), [1, 2], None, True)
t.ok("a pure swap is all exchange: quantity 0, shift 0",
     same(o3["overall"]["quantity"], 0.0) and same(o3["overall"]["shift"], 0.0)
     and same(o3["overall"]["exchange"], 1.0), o3["overall"])
o4 = rl.cm_metrics(np.array([[10, 0], [10, 0]]), [1, 2], None, True)["overall"]
t.ok("class 2 swallowed by class 1: all quantity, no allocation",
     same(o4["quantity"], 0.5) and same(o4["allocation"], 0.0), o4)

print()
print("M: with the unlabelled row and column (code 0 first)")
# Rows A, columns B: the pixel is unlabelled when nobody painted it.
MU = np.array([[50, 4, 6], [3, 20, 5], [7, 2, 13]])
check_matrix("three classes plus unlabelled", MU, unlabelled=0)
mu = rl.cm_metrics(MU, [0, 1, 2], unlabelled=0, kappa=True)
t.ok("only A 10 (3 + 7), only B 10 (4 + 6), neither 50, both 40, total 110",
     mu["counts"] == {"total": 110, "both": 40, "only_A": 10, "only_B": 10,
                      "neither": 50}, mu["counts"])
t.near("Po over the pixels both painted: (20 + 13) / 40", mu["overall"]["po"],
       33.0 / 40.0)
check_matrix("unlabelled, a class only A has",
             [[10, 0, 2, 0], [3, 8, 1, 0], [0, 1, 5, 0], [4, 2, 2, 0]], 0)
check_matrix("unlabelled, nobody painted anything", [[25, 0, 0], [0, 0, 0],
                                                    [0, 0, 0]], 0)
mn = rl.cm_metrics(np.array([[25, 0, 0], [0, 0, 0], [0, 0, 0]]), [0, 1, 2], 0,
                   True)
t.ok("nobody painted: every rate is NaN and the counts are right",
     math.isnan(mn["overall"]["po"]) and math.isnan(mn["overall"]["kappa"])
     and mn["counts"]["neither"] == 25 and mn["counts"]["both"] == 0)

print()
print("M: the worked example of Pontius (2019, Table 1), by my own count")
# Off-diagonal entries C12 1, C13 2, C21 4, C23 0, C31 1, C32 2: ten
# differences. Quantity: rows 3 4 3, columns 5 3 2, |3-5| + |4-3| + |3-2| =
# 4, half is 2. Exchange: pair 1-2 2 min(1, 4) = 2, pair 1-3 2 min(2, 1) =
# 2, pair 2-3 2 min(0, 2) = 0: 4. Allocation 10 - 2 = 8, shift 8 - 4 = 4.
for diag in (0, 5, 37):
    MP = [[diag, 1, 2], [4, diag, 0], [1, 2, diag]]
    check_matrix("diagonal %d, against the formulas" % diag, MP)
    mp = rl.cm_metrics(np.array(MP), [1, 2, 3], None, False)
    nn = float(np.sum(MP))
    got = [mp["overall"][k] * nn for k in ("quantity", "exchange", "shift")]
    t.ok("diagonal %d: quantity 2, exchange 4, shift 4 of 10" % diag,
         all_same(got, [2.0, 4.0, 4.0], 1e-9), got)

print()
print("M: random tables")
rng = np.random.default_rng(20260101)
bad = []
for case in range(300):
    K = int(rng.integers(1, 8))
    N = int(rng.choice([1, 5, 50, 1000, 100000]))
    conc = float(rng.choice([0.05, 0.3, 1.0, 5.0]))
    w = rng.dirichlet(np.full(K * K, conc))
    if rng.random() < 0.4:                      # an empty class
        z = int(rng.integers(0, K))
        w = w.reshape(K, K)
        w[z, :] = 0
        w[:, z] = 0
        w = (w.ravel() / w.sum()) if w.sum() > 0 else np.full(K * K, 1.0 / K / K)
    C = rng.multinomial(N, w).reshape(K, K)
    codes = list(range(K))
    m = rl.cm_metrics(C, codes, None, True)
    ref = ref_matrix(C.tolist())
    o = m["overall"]
    for k, a, b in (("po", o["po"], ref["po"]), ("kappa", o["kappa"],
                                                   ref["kappa"]),
                    ("Q", o["quantity"], ref["Q"]),
                    ("A", o["allocation"], ref["A"]),
                    ("E", o["exchange"], ref["E"]),
                    ("S", o["shift"], ref["S"]),
                    ("miou", o["mean_iou"], ref["mean_iou"])):
        if not same(a, b, 1e-10):
            bad.append((case, k, a, b))
    for c, r in zip(m["per_class"], ref["per"]):
        for k, a, b in (("iou", c["iou"], r["iou"]), ("f1", c["f1"], r["dice"]),
                        ("ua", c["rate_A"], r["ua"]),
                        ("pa", c["rate_B"], r["pa"]), ("e", c["e"], r["e"]),
                        ("s", c["s"], r["s"])):
            if not same(a, b, 1e-10):
                bad.append((case, c["code"], k, a, b))
t.ok("300 random tables (K 1 to 7, empty classes, N from 1 to 1e5) agree",
     not bad, bad[:4])

print()
print("M: the confusion matrix counted from pixels")
bad = []
for case in range(60):
    n = int(rng.integers(0, 300))
    K = int(rng.integers(1, 6))
    cs = sorted(rng.choice(np.arange(-3, 3000), size=K, replace=False))
    a = rng.choice(cs, size=n)
    b = rng.choice(cs, size=n)
    want = collections.Counter(zip(a.tolist(), b.tolist()))
    M = rl.cm_confusion(a, b, cs)
    if not (all(int(M[i, j]) == want.get((x, y), 0)
                for i, x in enumerate(cs) for j, y in enumerate(cs))
            and int(M.sum()) == n):
        bad.append((case, "cm_confusion"))
    if rl.cm_accumulate({}, a, b) != dict(want):
        bad.append((case, "cm_accumulate"))
    wide = rl.cm_accumulate({}, a * 70000, b * 70000 + 1)
    if wide != {(x * 70000, y * 70000 + 1): v for (x, y), v in want.items()}:
        bad.append((case, "past 32 bits of key"))
t.ok("60 random pairs of maps (codes negative and past 16 bits): row = A's "
     "code, column = B's code, each pair counted as a Counter counts it",
     not bad, bad[:3])
refused = False
try:
    rl.cm_confusion([1, 2], [1, 9], [1, 2])
except ValueError:
    refused = True
t.ok("a code that is not in the list is an error, not a pixel dropped",
     refused)

print()
print("M: the pooled value and the median over frames")
frames = [rng.multinomial(int(rng.integers(20, 200)),
                          rng.dirichlet(np.ones(9) * 2)).reshape(3, 3)
          for _ in range(9)]
stack = np.array(frames)
summ = rl.cm_summarize(stack, ["f%d" % i for i in range(9)], [0, 1, 2],
                       n_boot=0, unlabelled=0, kappa=True)
pool = ref_matrix(stack.sum(axis=0)[1:, 1:].tolist())
t.ok("pooled = the reference on the summed table (pixels weigh equally)",
     same(summ["pooled"]["overall"]["po"], pool["po"])
     and same(summ["pooled"]["overall"]["kappa"], pool["kappa"]))
per_frame_po = [ref_matrix(f[1:, 1:].tolist())["po"] for f in frames]
sp = summ["spread"]["po"]
t.ok("the spread is the median and quartiles of the frame values (type 7)",
     same(sp["median"], pct7(per_frame_po, 50))
     and same(sp["q1"], pct7(per_frame_po, 25))
     and same(sp["q3"], pct7(per_frame_po, 75)) and sp["n"] == 9, sp)
t.ok("a frame's kappa left out when undefined: n counts the defined ones",
     rl.st_spread([0.5, nan, 0.7, None])["n"] == 2)
wl = summ["with_unlabelled"]
full = ref_matrix(stack.sum(axis=0).tolist())
t.ok("with the unlabelled as a class of its own: Po and kappa of the whole "
     "table", same(wl["po"], full["po"]) and same(wl["kappa"], full["kappa"]))

# --------------------------------------------------------------------- S
print()
print("S: the percentile interval and the frame bootstrap")
reps = rng.normal(size=1000).tolist()
lo, hi = rl.st_percentile_ci(reps, 0.95)
t.ok("the 95 % interval is the 2.5 and 97.5 percentiles (type 7)",
     same(lo, pct7(reps, 2.5)) and same(hi, pct7(reps, 97.5)), (lo, hi))
lo, hi = rl.st_percentile_ci([1.0, nan, 2.0, 3.0, None], 0.9)
t.ok("a replicate that is undefined is left out", same(lo, pct7([1, 2, 3], 5))
     and same(hi, pct7([1, 2, 3], 95)))
t.ok("no replicate defined: both ends NaN",
     all(math.isnan(v) for v in rl.st_percentile_ci([nan, nan])))

F = 12
frames = [rng.multinomial(int(rng.integers(100, 400)),
                          rng.dirichlet(np.ones(4) * 3)).reshape(2, 2)
          for _ in range(F)]
stack = np.array(frames)


def po_of(M):
    M = np.asarray(M, dtype=float)
    return float(np.trace(M) / M.sum())


def stat_po(M):
    return {"po": po_of(M)}


for chunk in (250, 7):
    got = rl.cm_bootstrap(stack, stat_po, 2000, 5, chunk=chunk)
    # rebuilt from its description: F frames drawn with replacement is one
    # multinomial weight per frame; the percentile interval of Po
    w = np.random.default_rng(5).multinomial(F, [1.0 / F] * F, size=2000)
    pooled = np.einsum("bf,fij->bij", w.astype(float), stack.astype(float))
    reps = [po_of(m) for m in pooled]
    want = (pct7(reps, 2.5), pct7(reps, 97.5))
    t.ok("bootstrap interval of Po rebuilt from the description (seed 5, "
         "2000 draws, chunk %d)" % chunk,
         all_same(got["ci"]["po"], want, 1e-12), (got["ci"], want))
t.ok("it says how it was made: resamples, seed, level, method",
     got["resamples"] == 2000 and got["seed"] == 5 and got["level"] == 0.95
     and "percentile" in got["method"] and "frames" in got["method"])
t.ok("five frames is enough, four is not",
     rl.cm_bootstrap(stack[:5], stat_po, 50, 1)["ci"] is not None
     and rl.cm_bootstrap(stack[:4], stat_po, 50, 1)["ci"] is None
     and "fewer than 5" in rl.cm_bootstrap(stack[:4], stat_po, 50, 1)["reason"])
t.ok("the same seed gives the same interval, another gives another",
     rl.cm_bootstrap(stack, stat_po, 300, 9)["ci"]
     == rl.cm_bootstrap(stack, stat_po, 300, 9)["ci"]
     and rl.cm_bootstrap(stack, stat_po, 300, 9)["ci"]
     != rl.cm_bootstrap(stack, stat_po, 300, 10)["ci"])
if need_scipy("scipy.stats.bootstrap as a sanity range for the frame "
              "bootstrap of Po"):
    res = sst.bootstrap((np.arange(F),),
                        lambda idx: po_of(stack[np.asarray(idx, dtype=int)]
                                          .sum(axis=0)),
                        n_resamples=4000, method="percentile",
                        confidence_level=0.95, random_state=11)
    ours = rl.cm_bootstrap(stack, stat_po, 2000, 1)["ci"]["po"]
    sd = float(np.std(reps))
    t.ok("scipy's percentile bootstrap lands on ours within 0.25 of a "
         "standard error at both ends (Monte Carlo noise)",
         abs(res.confidence_interval.low - ours[0]) < 0.25 * sd + 1e-3
         and abs(res.confidence_interval.high - ours[1]) < 0.25 * sd + 1e-3,
         (res.confidence_interval, ours, sd))

b1 = rl.st_bootstrap_stat([1.0, 2.0, 3.0, 4.0, 10.0], lambda v: float(v.mean()),
                          500, 3)
rng3 = np.random.default_rng(3)
idx = rng3.integers(0, 5, size=(500, 5))
vals = np.array([1.0, 2.0, 3.0, 4.0, 10.0])
means = vals[idx].mean(axis=1)
t.ok("st_bootstrap_stat: n values drawn with replacement, the mean "
     "recomputed, the percentile interval",
     all_same(b1["ci"], (pct7(means, 2.5), pct7(means, 97.5))), b1["ci"])
t.ok("fewer than 2 values: no interval and the reason",
     rl.st_bootstrap_stat([1.0], lambda v: v.mean(), 100, 1)["ci"] is None)

# --------------------------------------------------------------------- W
print()
print("W: the Wilcoxon signed-rank test")


def midranks(a):
    order = sorted(range(len(a)), key=lambda i: a[i])
    ranks = [0.0] * len(a)
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and a[order[j + 1]] == a[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def wilcoxon_enumerated(x):
    """Two-sided exact p by listing every sign pattern of the mid-ranks of
    the non-zero values: the share of patterns at least as far from the mean
    of W+ as the one seen. Zeros are dropped (Wilcoxon 1945)."""
    v = [float(a) for a in x if a != 0]
    n = len(v)
    if n == 0:
        return nan, nan, 0
    r = midranks([abs(a) for a in v])
    w_obs = sum(rk for a, rk in zip(v, r) if a > 0)
    mean = sum(r) / 2.0
    far = 0
    for signs in itertools.product((0, 1), repeat=n):
        w = sum(rk for s, rk in zip(signs, r) if s)
        if abs(w - mean) >= abs(w_obs - mean) - 1e-9:
            far += 1
    return min(1.0, far / float(2 ** n)), w_obs, n


def wilcoxon_normal(x):
    """The normal approximation by the textbook formula: continuity
    correction of one half, tie correction of the variance."""
    v = [float(a) for a in x if a != 0]
    n = len(v)
    r = midranks([abs(a) for a in v])
    w = sum(rk for a, rk in zip(v, r) if a > 0)
    ties = collections.Counter(abs(a) for a in v)
    var = n * (n + 1) * (2 * n + 1) / 24.0 \
        - sum(k ** 3 - k for k in ties.values()) / 48.0
    z = max(0.0, abs(w - n * (n + 1) / 4.0) - 0.5) / math.sqrt(var)
    return math.erfc(z / math.sqrt(2.0))


bad = []
for case in range(60):
    n = int(rng.integers(1, 13))
    kind = case % 3
    if kind == 0:
        x = rng.normal(0.4, 1.0, n)                     # no ties
    elif kind == 1:
        x = np.round(rng.normal(0.4, 1.0, n), 0)        # ties and zeros
    else:
        x = rng.integers(-3, 5, n).astype(float)        # many ties and zeros
    want_p, want_w, want_n = wilcoxon_enumerated(x.tolist())
    got = rl.st_wilcoxon_signed(x)
    if got["n"] != want_n:
        bad.append((case, "n", got["n"], want_n))
    elif want_n and (not same(got["p"], want_p, 1e-12)
                     or not same(got["w_plus"], want_w)):
        bad.append((case, x.tolist(), got["p"], want_p))
    elif want_n and got["method"] != "exact":
        bad.append((case, "method", got["method"]))
t.ok("60 samples of 1 to 12 values (ties, zeros): exact p equals the "
     "enumeration of all 2^n sign patterns on mid-ranks", not bad, bad[:3])
g5 = rl.st_wilcoxon_signed([1, 2, 3, 4, 5])
t.near("five values of one sign: W+ 15 and p = 2/32", g5["p"], 2.0 / 32.0)
t.ok("all zeros: no test (NaN, said)", math.isnan(rl.st_wilcoxon_signed(
    [0, 0, 0.0])["p"]) and rl.st_wilcoxon_signed([0, 0])["n"] == 0)
t.near("one value: p = 1", rl.st_wilcoxon_signed([2.5])["p"], 1.0)
t.ok("zeros are dropped, as Wilcoxon did: n counts the others",
     rl.st_wilcoxon_signed([0, 0, 1.5, -0.5, 2.0])["n"] == 3)
x = rng.normal(0.3, 1.0, 40)
x[::7] = np.round(x[::7], 0)
g = rl.st_wilcoxon_signed(x)
t.ok("above 25 non-zero values: the normal approximation, tie and "
     "continuity corrected", "normal approximation" in g["method"]
     and same(g["p"], wilcoxon_normal(x.tolist()), 1e-12), g)
t.ok("exactly 25 is still exact, 26 is approximate",
     rl.st_wilcoxon_signed(rng.normal(0.2, 1, 25))["method"] == "exact"
     and rl.st_wilcoxon_signed(rng.normal(0.2, 1, 26))["method"].startswith(
         "normal"))
big = rng.normal(0.25, 1.0, 40)
exact_big = rl._st_exact_upper(np.round(np.array(midranks(
    [abs(a) for a in big])) * 2).astype(int),
    sum(r for a, r in zip(big, midranks([abs(a) for a in big])) if a > 0) * 2)
p_exact_big = min(1.0, 2.0 * min(exact_big))
t.ok("at 40 values the approximation is within 0.01 of the exact p",
     abs(rl.st_wilcoxon_signed(big)["p"] - p_exact_big) < 0.01,
     (rl.st_wilcoxon_signed(big)["p"], p_exact_big))
if need_scipy("scipy.stats.wilcoxon against the signed-rank test"):
    bad = []
    for case in range(80):
        n = int(rng.integers(2, 26))
        x = rng.normal(rng.uniform(-0.5, 0.8), 1.0, n)
        a = rl.st_wilcoxon_signed(x)["p"]
        b = sst.wilcoxon(x, method="exact").pvalue
        if not same(a, b, 1e-10):
            bad.append((n, a, b))
    t.ok("no ties, up to 25 values: equal to scipy.stats.wilcoxon(method="
         "'exact') (which is scipy's default for these)", not bad, bad[:3])
    bad = []
    for case in range(40):
        n = int(rng.integers(26, 90))
        x = np.round(rng.normal(rng.uniform(-0.3, 0.6), 1.0, n), 1)
        a = rl.st_wilcoxon_signed(x)
        if a["n"] <= 25:
            continue
        b = sst.wilcoxon(x, method="approx", correction=True,
                         zero_method="wilcox").pvalue
        if not same(a["p"], b, 1e-10):
            bad.append((n, a["p"], b))
    t.ok("above 25 non-zero values, with ties and zeros: equal to "
         "scipy.stats.wilcoxon(method='approx', correction=True, "
         "zero_method='wilcox'); NOT to its default, which has no "
         "continuity correction", not bad, bad[:3])
    xs = rng.normal(0.35, 1.0, 40)
    t.ok("and the default of scipy (no continuity correction) differs "
         "slightly, as the documentation says",
         not same(rl.st_wilcoxon_signed(xs)["p"],
                  sst.wilcoxon(xs, method="approx").pvalue, 1e-6))

# --------------------------------------------------------------------- T
print()
print("T: active time")
S_ = 1000


# Local noon of a day with no change of clock, so that a session of a few
# hours stays inside one local day (the live figure is the figure of a day).
NOON = datetime(2026, 3, 3, 12, 0, 0).timestamp()


def event(seq, action, end_s, dur_s=0.0, pauses="", tile="t1", op="ANNA",
          session="s1", code=1, base=NOON):
    return {"session": session, "seq": seq, "mono_ms": int(round(end_s * S_)),
            "dur_ms": int(round(dur_s * S_)), "action": action,
            "pauses_s": pauses, "tile_id": tile, "operator": op,
            "pass_no": "1", "class_code": code, "module": "annotate",
            "t_utc": rl.effort_format_utc(base + end_s)}


# A session worked out by hand. Each stroke is (end, duration); the gap
# before a stroke is its start less the end of the row before.
#   1 stroke  ends 10, lasts 2 (start 8)            first row: no gap
#   2 stroke  ends 20, lasts 1 (start 19): gap 9    active at every limit
#   3 stroke  ends 81, lasts 1 (start 80): gap 60   exactly 60: active at
#                                                   60 and 120, idle at 30
#   4 stroke  ends 183, lasts 1 (start 182): gap 101   idle at 30 and 60,
#                                                   active at 120
#   5 focus_out at 190 (gap 7 before it, active)
#   6 stroke  ends 196, lasts 1 (start 195): gap 5, but after a focus_out
#   7 stroke  ends 300, lasts 70, pauses 61.0 and 25.0 (start 230): gap 34
#   8 stroke  ends 301, lasts 0.5, start 300.5, gap 0.5
rows = [event(1, "stroke", 10, 2), event(2, "stroke", 20, 1),
        event(3, "stroke", 81, 1), event(4, "stroke", 183, 1),
        event(5, "focus_out", 190), event(6, "stroke", 196, 1),
        event(7, "stroke", 300, 70, "61.0;25.0"),
        event(8, "stroke", 301, 0.5)]
want = {}
# strokes: 2 + 1 + 1 + 1 + 1 + 70 - pauses + 0.5
#   T = 30:  pauses over 30: 61.0 -> 70 - 61 = 9
#   T = 60:  pauses over 60: 61.0 -> 9
#   T = 120: none -> 70
# gaps (not after the focus_out): g2 = 9, g3 = 60, g4 = 101, g5 = 7, g7 = 34
#   (the 5 s gap before row 6 is idle: it follows a focus_out), g8 = 0.5
want[30] = (2 + 1 + 1 + 1 + 1 + 9 + 0.5) + (9 + 7 + 0.5)
want[60] = (2 + 1 + 1 + 1 + 1 + 9 + 0.5) + (9 + 60 + 7 + 34 + 0.5)
want[120] = (2 + 1 + 1 + 1 + 1 + 70 + 0.5) + (9 + 60 + 101 + 7 + 34 + 0.5)
for T in (30, 60, 120):
    res = rl.effort_attribute(rows, T, default_tile="*")
    got = sum(f["active_s"] for f in res["frames"].values()) \
        + res["unplaced_s"]
    t.near("worked session at %d s: %.1f s of active time" % (T, want[T]),
           got, want[T], 1e-9)
sens = rl.effort_sensitivity(rows, default_tile="*")
t.ok("effort_sensitivity gives 30, 60 and 120 in one go",
     sorted(sens) == [30, 60, 120] and all_same(
         [sum(f["active_s"] for f in sens[T]["frames"].values()) for T in
          (30, 60, 120)], [want[30], want[60], want[120]]))
one = rl.effort_attribute([event(1, "stroke", 10, 1), event(2, "stroke", 71, 1)],
                          60, default_tile="*")
two = rl.effort_attribute([event(1, "stroke", 10, 1),
                           event(2, "stroke", 71.001, 1)], 60,
                          default_tile="*")
t.near("a gap of exactly T is active", sum(f["active_s"] for f in
                                           one["frames"].values()), 2 + 60.0)
t.near("a gap of T + 1 ms is idle", sum(f["active_s"] for f in
                                        two["frames"].values()), 2.0)
pz = rl.effort_attribute([event(1, "stroke", 100, 100, "60.0")], 60,
                         default_tile="*")
pz2 = rl.effort_attribute([event(1, "stroke", 100, 100, "60.1")], 60,
                          default_tile="*")
t.ok("a pause of exactly T stays in the stroke, one longer comes out",
     same(sum(f["active_s"] for f in pz["frames"].values()), 100.0)
     and same(sum(f["active_s"] for f in pz2["frames"].values()), 100.0
              - 60.1))


def ref_active(events, T):
    """The rule as the report states it, in one pass: strokes less their
    pauses longer than T, plus the gaps no longer than T that do not follow
    a focus_out. Strokes in MARK_ACTIONS; every row ends at mono_ms and
    starts dur_ms before it."""
    total, prev_end, prev_act = 0.0, None, None
    marks = set(rl.MARK_ACTIONS)
    for e in sorted(events, key=lambda r: r["seq"]):
        end = e["mono_ms"] / 1000.0
        dur = e["dur_ms"] / 1000.0
        if prev_end is not None:
            gap = max(0.0, end - dur - prev_end)
            if gap <= T and prev_act != "focus_out":
                total += gap
        if e["action"] in marks:
            pauses = [float(p) for p in e["pauses_s"].split(";") if p]
            total += max(0.0, dur - sum(p for p in pauses if p > T))
        prev_end, prev_act = end, e["action"]
    return total


def random_session(rng, n, session="s1", t0=100.0, ops=("ANNA",)):
    out, clock = [], t0
    acts = ["stroke", "stroke", "stroke", "point", "view", "frame", "class",
            "focus_out", "focus_in", "undo", "save"]
    for k in range(n):
        gap = float(rng.choice([0, 0.5, 3, 29, 30, 31, 59, 60, 61, 119, 120,
                                121, 400]))
        act = acts[int(rng.integers(0, len(acts)))]
        dur = float(rng.choice([0, 0.25, 1, 4, 20, 90])) \
            if act in rl.MARK_ACTIONS else 0.0
        pauses = ""
        if dur >= 30 and rng.random() < 0.5:
            pauses = ";".join("%.1f" % p for p in rng.choice(
                [10.0, 30.0, 31.0, 60.0, 61.0], size=1))
            if float(pauses.split(";")[0]) > dur:
                pauses = ""
        clock += gap + dur
        out.append(event(k + 1, act, clock, dur, pauses,
                         tile=("t%d" % int(rng.integers(1, 4)))
                         if rng.random() < 0.7 else "",
                         op=ops[int(rng.integers(0, len(ops)))],
                         session=session))
    return out


bad = []
for case in range(60):
    evs = random_session(rng, int(rng.integers(1, 60)))
    for T in (30, 60, 120):
        res = rl.effort_attribute(evs, T, default_tile="*")
        got = sum(f["active_s"] for f in res["frames"].values()) \
            + res["unplaced_s"]
        if not same(got, ref_active(evs, T), 1e-9):
            bad.append((case, T, got, ref_active(evs, T)))
t.ok("60 random sessions: the total over frames is the reference rule at "
     "30, 60 and 120 s", not bad, bad[:3])
bad = []
for case in range(40):
    evs = random_session(rng, int(rng.integers(2, 80)))
    jr = rl.Journal(root, "s1", "annotate", idle_s=60)
    for e in evs:
        jr._live(dict(e))
    live = jr.active_today()
    res = rl.effort_attribute(evs, 60, default_tile="*")
    rep = sum(f["active_s"] for f in res["frames"].values()) \
        + res["unplaced_s"]
    if not same(live, rep, 1e-9):
        bad.append((case, live, rep))
t.ok("40 random sessions: the live figure under the coverage line is the "
     "report's number at 60 s", not bad, bad[:3])
two_sessions = random_session(rng, 20, "s1") + random_session(
    rng, 20, "s2", t0=900000.0)
res = rl.effort_attribute(two_sessions, 60, default_tile="*")
t.ok("sessions are never joined: the total is the sum of the two",
     same(sum(f["active_s"] for f in res["frames"].values())
          + res["unplaced_s"],
          ref_active([e for e in two_sessions if e["session"] == "s1"], 60)
          + ref_active([e for e in two_sessions if e["session"] == "s2"], 60),
          1e-9))
# A clock that goes back: rows 1-2 are one run of the clock (a stroke of 1 s,
# a gap of 9 s, a stroke of 1 s: 11 s), rows 3-4 another (1 + 3 + 1 = 5 s).
back = [event(1, "stroke", 50, 1), event(2, "stroke", 60, 1),
        event(3, "stroke", 5, 1), event(4, "stroke", 9, 1)]
res = rl.effort_attribute(back, 60, default_tile="*")
t.ok("a monotonic clock that goes back splits the session there, says so, "
     "and no gap is counted across the split",
     len(res["warnings"]) == 1 and same(sum(
         f["active_s"] for f in res["frames"].values()), 11 + 5, 1e-9),
     (res["warnings"], res["frames"]))


def utc_event(seq, session, mono_s, utc_s, dur_s, op="ANNA", tile="t1"):
    e = event(seq, "stroke", mono_s, dur_s, tile=tile, op=op, session=session)
    e["t_utc"] = rl.effort_format_utc(NOON + utc_s)
    return e


# Two QGIS windows on one campaign, each with its own monotonic clock: the
# first works from 0 to 100 s (ten strokes of 10 s, no gaps), the second
# from 50 to 150 s. The same person: the time they overlap is counted once.
w1 = [utc_event(k + 1, "w1", 1000 + 10 * (k + 1), 10 * (k + 1), 10)
      for k in range(10)]
w2 = [utc_event(k + 1, "w2", 7 + 10 * (k + 1), 50 + 10 * (k + 1), 10)
      for k in range(10)]
res = rl.effort_attribute(w1 + w2, 60, default_tile="*")
t.near("one person in two windows at once: 100 + 100 - 50 s overlap = 150 s",
       sum(f["active_s"] for f in res["frames"].values()), 150.0, 1e-6)
t.near("and the overlap is reported: 50 s", res["overlap_s"], 50.0, 1e-6)
w2b = [utc_event(k + 1, "w2", 7 + 10 * (k + 1), 50 + 10 * (k + 1), 10,
                 op="BEA") for k in range(10)]
res = rl.effort_attribute(w1 + w2b, 60, default_tile="*")
t.near("two people at once do not overlap: 200 s",
       sum(f["active_s"] for f in res["frames"].values()), 200.0, 1e-6)

# Operations kept before the journal: only the end of each stroke, to the
# second; a gap no longer than the limit goes to the later row.
whens = ["2026-03-03T12:00:00", "2026-03-03T12:00:20", "2026-03-03T12:03:00",
         "2026-03-03T12:03:50", "not a time", "2026-03-03T12:04:10"]
secs, unreadable = rl.effort_legacy(whens, 60)
t.ok("legacy rows: 0, 20, 0 (160 s is idle), 50, unreadable 0, then the gap "
     "from the last readable row, 20", secs == [0.0, 20.0, 0.0, 50.0, 0.0,
                                               20.0] and unreadable == 1,
     (secs, unreadable))
ops = [{"when": w, "operator": "ana", "into": "wood", "x": 0, "y": 0}
       for w in whens if w != "not a time"]
legacy, bad_n = rl.effort_legacy_rows(ops, {"wood": 2})
res = rl.effort_attribute(legacy, 60, default_tile="*")
t.near("the same rows through the report's own rule give the same total",
       sum(f["active_s"] for f in res["frames"].values()), 20 + 50 + 20,
       1e-6)

print()
print("T: per hectare, per frame, per class")
t.near("90 s on 0.5 ha is 3 minutes a hectare", rl.effort_per_ha(90, 5000.0),
       3.0)
t.ok("no area: NaN, not 0", math.isnan(rl.effort_per_ha(90, 0))
     and math.isnan(rl.effort_per_ha(90, None)))
evs = [event(1, "stroke", 10, 4, tile="t1", code=1),
       event(2, "stroke", 20, 2, tile="t1", code=2),
       event(3, "stroke", 40, 5, tile="t2", code=1),
       event(4, "stroke", 50, 10, tile="t2", code=2)]
res = rl.effort_attribute(evs, 60)
# t1: row 1 draws 4 s; row 2 starts at 18 and row 1 ended at 10, a gap of
# 8 s that goes to the next mark (class 2): 4 + 8 + 2 = 14 s. t2: row 3
# starts at 35, the gap from 20 is 15 s, goes to row 3; 15 + 5, then row 4
# starts at 40, where row 3 ended: 10 s: 30 s in all.
fr = {k[0]: v for k, v in res["frames"].items()}
t.near("frame t1: 4 s of drawing, 8 s of gap given to the next mark, 2 s",
       fr["t1"]["active_s"], 4 + 8 + 2)
t.near("frame t2: 15 s of gap, 5 s and 10 s of strokes", fr["t2"]["active_s"],
       15 + 5 + 10)
cls = rl.effort_class_totals(res)
t.near("class 2 gets the gap before its strokes: (8 + 2) in t1, 10 in t2",
       cls[("ANNA", "1", 2)], 8 + 2 + 10)
fm = {"t1": 5000.0, "t2": 10000.0}
rows_f = rl.effort_frame_table("campaign", {60: res, 30: res, 120: res}, 60,
                               fm)
tot = rl.effort_totals(rows_f)
t.near("minutes per hectare of the set: seconds / 60 over the hectares",
       tot["T"]["min_per_ha"], 44.0 / 60.0 / 1.5, 1e-9)
t.near("hours", tot["T"]["active_h"], 44.0 / 3600.0, 1e-12)

# The tables must add up: over its classes a frame's time is the frame's
# time, at the chosen limit and at each of 30, 60 and 120 s, and the pooled
# row of a class is the sum of its frames. A longer limit keeps gaps that a
# shorter one calls idle, so overhead can exist at 120 s and not at 60 s.
bad = []
for case in range(80):
    evs = random_session(rng, int(rng.integers(2, 60)), ops=("ANNA", "BEA"))
    res_all = {T: rl.effort_attribute(evs, T) for T in (30, 60, 120)}
    main = res_all[60]
    keys = sorted(main["frames"], key=lambda k: tuple(str(v) for v in k))
    crows = rl.effort_class_table("c", res_all, 60, keys)
    frows = rl.effort_frame_table("c", res_all, 60,
                                  {k[0]: 10000.0 for k in keys}, keys)
    for fk in keys:
        mine = [r for r in crows
                if (r["tile_id"], r["operator"], r["pass_no"]) == fk]
        for T, col in ((60, "active_s_T"), (30, "active_s_30"),
                       (60, "active_s_60"), (120, "active_s_120")):
            f = res_all[T]["frames"].get(fk)
            want_t = f["active_s"] if f else 0.0
            if not same(sum(r[col] for r in mine), want_t, 1e-9):
                bad.append((case, fk, col, sum(r[col] for r in mine), want_t))
    for r in frows:
        for T in (30, 60, 120):
            f = res_all[T]["frames"].get((r["tile_id"], r["operator"],
                                          r["pass_no"]))
            got = r.get("active_s_%d" % T)
            if (f is None) != (got is None) or (f and not same(
                    f["active_s"], got, 1e-9)):
                bad.append((case, "frame table", T, r["tile_id"]))
    for col in ("active_s_T", "active_s_30", "active_s_120"):
        if not same(sum(r[col] for r in crows if r["tile_id"] == "*"),
                    sum(r[col] for r in crows if r["tile_id"] != "*"), 1e-9):
            bad.append((case, "pooled", col))
t.ok("80 random sessions of two people: class rows add up to the frame at "
     "every limit, the pooled rows to the frames, the frame table's 30/60/"
     "120 columns to the reports at those limits", not bad, bad[:3])

# --------------------------------------------------------------------- P
print()
print("P: scratch against correction")
scratch = {"t%d" % i: float(s) for i, s in enumerate(
    [600, 540, 800, 450, 700, 650, 520, 900, 480, 610, 0, 300], 1)}
correct = {"t%d" % i: float(s) for i, s in enumerate(
    [300, 420, 380, 460, 310, 280, 500, 350, 200, 330, 100, 0], 1)}
pr = rl.effort_pair(scratch, correct, 2000, 1)
# frames in the order of their ids as text (t1, t10, t11, t12, t2, ...): the
# order the engine draws them in, which fixes what a seed gives
both = sorted(k for k in scratch if scratch[k] > 0 and correct[k] > 0)
ratios = [correct[k] / scratch[k] for k in both]
logs = [math.log(r) for r in ratios]
gm = math.exp(sum(logs) / len(logs))
pool = pr["pooled"]
t.ok("frames with no time on one side are skipped and counted, not read "
     "as infinitely fast", pool["n_frames"] == 10 and pool["n_skipped"] == 2
     and sorted(pool["skipped"]) == ["t11", "t12"], pool)
t.near("the ratio is the geometric mean of the per-frame ratios", pool["ratio"],
       gm, 1e-12)
t.near("the saving is 100 (1 - ratio) per cent", pool["saving_pct"],
       100.0 * (1.0 - gm), 1e-9)
t.near("the median ratio is the plain median of the ratios",
       pool["median_ratio"], pct7(ratios, 50), 1e-12)
wp = wilcoxon_enumerated(logs)[0]
t.near("Wilcoxon p of the log ratios (exact, 10 frames)", pool["wilcoxon_p"],
       wp, 1e-12)
idx = np.random.default_rng(1).integers(0, 10, size=(2000, 10))
lg = np.array(logs)
reps = np.exp(lg[idx].mean(axis=1))
t.ok("the interval: 2000 draws of 10 frames with replacement, the geometric "
     "mean of each, percentiles (seed 1)",
     all_same([pool["ci_low"], pool["ci_high"]],
              [pct7(reps, 2.5), pct7(reps, 97.5)], 1e-12),
     (pool["ci_low"], pool["ci_high"]))
few = rl.effort_pair({"a": 10, "b": 20, "c": 30, "d": 40},
                     {"a": 5, "b": 9, "c": 20, "d": 10}, 2000, 1)["pooled"]
t.ok("four frames: no interval, and it says why",
     math.isnan(few["ci_low"]) and "fewer than 5" in few["ci_reason"], few)
if need_scipy("scipy.stats.wilcoxon and bootstrap on the paired log ratios"):
    t.near("the p equals scipy.stats.wilcoxon(method='exact') of the logs",
           pool["wilcoxon_p"], sst.wilcoxon(logs, method="exact").pvalue,
           1e-10)
    res = sst.bootstrap((lg,), lambda v: float(np.exp(np.mean(v))),
                        n_resamples=4000, method="percentile",
                        random_state=5)
    sd = float(np.std(reps))
    t.ok("scipy's percentile bootstrap of the geometric mean lands within "
         "0.25 standard errors of ours",
         abs(res.confidence_interval.low - pool["ci_low"]) < 0.25 * sd + 1e-3
         and abs(res.confidence_interval.high - pool["ci_high"])
         < 0.25 * sd + 1e-3,
         (res.confidence_interval, pool["ci_low"], pool["ci_high"]))

# --------------------------------------------------------------------- V
print()
print("V: model against the corrected map")
names = {1: "water", 2: "wood", 3: "field"}
MV = np.array([[500, 40, 10], [30, 300, 60], [20, 25, 415]])   # model x corr.
pairs = {(a, b): int(MV[a - 1, b - 1]) for a in (1, 2, 3) for b in (1, 2, 3)}
result = {"recipe": {"names": names, "pixel_m2": 100.0},
          "codes": [1, 2, 3], "pairs": pairs, "other_pairs": {},
          "polygons": [], "grid": {"pixel_area": 100.0}, "scope": "whole"}
s = rl.mvc_summarize(result, {})
ref = ref_matrix(MV.tolist())
pc = {c["code"]: c for c in s["metrics"]["per_class"]}
ok = True
for g in (1, 2, 3):
    r = ref["per"][g - 1]
    ok &= same(pc[g]["rate_B"], r["pa"]) and same(pc[g]["rate_A"], r["ua"]) \
        and same(pc[g]["iou"], r["iou"]) and same(pc[g]["f1"], r["dice"])
t.ok("producer's accuracy is the share of the corrected map's class the "
     "model found (column), user's the share of the model's class that "
     "stood (row); IoU and F1 as in the reference", ok)
t.ok("overall accuracy, quantity, allocation: the reference",
     same(s["metrics"]["overall"]["po"], ref["po"])
     and same(s["metrics"]["overall"]["quantity"], ref["Q"])
     and same(s["metrics"]["overall"]["allocation"], ref["A"])
     and same(s["metrics"]["overall"]["quantity"]
              + s["metrics"]["overall"]["allocation"], 1 - ref["po"]))
t.ok("never a kappa for the model", "kappa" not in s["metrics"]["overall"])
# a hand-checkable class: water. Model painted 500 + 40 + 10 = 550, the
# corrected map 500 + 30 + 20 = 550; 500 agree. PA = UA = 500/550.
t.near("water: PA = UA = 500/550", pc[1]["rate_B"], 500.0 / 550.0)
t.ok("the pairs: pixels, FROM -> TO, from the pixels",
     {(r["a"], r["b"]): r["pixels"] for r in s["pairs"] if r["changed"]}
     == {(a, b): v for (a, b), v in pairs.items() if a != b})
t.ok("transitions sorted by pixels, the largest first, all in m2 (x 100)",
     [r["pixels"] for r in s["transitions"]] == sorted(
         [r["pixels"] for r in s["transitions"]], reverse=True)
     and all(r["area_m2"] == r["pixels"] * 100.0 for r in s["transitions"]))
t.ok("the share of the model's class: pixels over its row",
     all(same(r["share_of_a"], r["pixels"] / float(MV[r["a"] - 1].sum()))
         for r in s["pairs"]))
t.ok("net change of a class (per_class.csv): corrected less model, in m2",
     all(c["n_B"] - c["n_A"] == int(MV[:, c["code"] - 1].sum()
                                    - MV[c["code"] - 1].sum())
         for c in s["metrics"]["per_class"]))

print()
print("V: the polygon bootstrap")
polys = []
for k in range(8):
    one = rng.multinomial(int(rng.integers(150, 400)),
                          rng.dirichlet(np.ones(9) * 2)).reshape(3, 3)
    polys.append({"fid": k + 1, "pixels": int(one.sum()), "swept": 0,
                  "changed": int(one.sum() - np.trace(one)),
                  "pairs": {(a + 1, b + 1): int(one[a, b])
                            for a in range(3) for b in range(3)}})
pmats = np.array([[[p["pairs"][(a, b)] for b in (1, 2, 3)] for a in (1, 2, 3)]
                  for p in polys])
res8 = dict(result, polygons=polys, scope="polygons",
            pairs={(a, b): int(pmats.sum(axis=0)[a - 1, b - 1])
                   for a in (1, 2, 3) for b in (1, 2, 3)})
s8 = rl.mvc_summarize(res8, {})
w = np.random.default_rng(1).multinomial(8, [1.0 / 8] * 8, size=2000)
pooled = np.einsum("bf,fij->bij", w.astype(float), pmats.astype(float))


def iou_of(M, g):
    M = np.asarray(M, dtype=float)
    return M[g, g] / (M[g].sum() + M[:, g].sum() - M[g, g])


ci = s8["bootstrap"]["ci"]
t.ok("IoU of each class: 2000 draws of 8 polygons with replacement (seed 1), "
     "percentiles",
     all(all_same(ci["iou:%d" % (g + 1)],
                  [pct7([iou_of(m, g) for m in pooled], 2.5),
                   pct7([iou_of(m, g) for m in pooled], 97.5)], 1e-12)
         for g in range(3)))
t.ok("it names polygons and not frames",
     "polygons" in s8["bootstrap"]["method"])
res4 = dict(res8, polygons=polys[:4])
s4 = rl.mvc_summarize(res4, {})
t.ok("four polygons: no interval, and the reason says polygons",
     s4["bootstrap"]["ci"] is None and "polygons" in s4["bootstrap"]["reason"]
     and "5" in s4["bootstrap"]["reason"], s4["bootstrap"])

print()
print("V: the people side, with kappa")
other = {(a, b): int(rng.integers(0, 120)) + (200 if a == b else 0)
         for a in (1, 2, 3) for b in (1, 2, 3)}
res_p = dict(result, other_pairs=other)
sp_ = rl.mvc_summarize(res_p, {}, people={"kind": "correction",
                                          "operator": "BEA", "name": "c2"})
OM = np.array([[other[(a, b)] for b in (1, 2, 3)] for a in (1, 2, 3)])
refp = ref_matrix(OM.tolist())
po_ = sp_["people"]["overall"]
t.ok("two people: overall, kappa, expected agreement, quantity and "
     "allocation from the reference",
     same(po_["oa"], refp["po"]) and same(po_["kappa"], refp["kappa"])
     and same(po_["pe"], refp["pe"]) and same(po_["quantity"], refp["Q"])
     and same(po_["allocation"], refp["A"]), (po_, refp["kappa"]))
t.ok("their IoU and F1 are the reference's, class by class",
     all(same(sp_["people"]["matched"][g]["iou"], refp["per"][g - 1]["iou"])
         and same(sp_["people"]["matched"][g]["f1"], refp["per"][g - 1]["dice"])
         for g in (1, 2, 3)))
sbs = {r["code"]: r for r in sp_["side_by_side"]}
t.ok("excess error is people's IoU less the model's (above 0: the model is "
     "further from the corrected map than two people are from each other)",
     all(same(sbs[g]["excess_error"], refp["per"][g - 1]["iou"]
              - ref["per"][g - 1]["iou"]) for g in (1, 2, 3)))

# --------------------------------------------------------------------- U
print()
print("U: from a model's band to u")
U = 254


def rhalf(x):
    return int(math.floor(x * U + 0.5))


raw = np.array([255, 128, 51, 0, 200, 300, -4], dtype=float)
valid = np.ones(raw.shape, dtype=bool)
u8, said = rl.unc_to_u8(raw, None, {"kind": "probability", "scale": 255.0},
                        valid, band_nodata=None)
want = []
for r in raw:
    if r == 0:
        want.append(255)             # the probability of a class is never 0
    else:
        v = min(1.0, max(0.0, r / 255.0))
        want.append(rhalf(1.0 - v))
t.ok("probability p on 255: u = 1 - p, stored as floor(254 u + 1/2); a 0 "
     "under a class has no value; values past 0..1 clipped",
     u8.tolist() == want, (u8.tolist(), want))
t.ok("and 2 pixels were clipped, 1 had no value", said["clipped_px"] == 2
     and said["no_value"] == 1, said)
for kind, fn in (("entropy", lambda v: v), ("uncertainty", lambda v: v),
                 ("margin", lambda v: 1.0 - v)):
    raw = rng.uniform(-0.1, 1.1, 200)
    u8, said = rl.unc_to_u8(raw, None, {"kind": kind, "scale": 1.0},
                            np.ones(200, dtype=bool))
    want = [rhalf(fn(min(1.0, max(0.0, r)))) for r in raw]
    t.ok("%s: u = %s" % (kind, "1 - m" if kind == "margin" else "the value"),
         u8.tolist() == want)
raw = rng.uniform(0, 1, 100)
u8, _ = rl.unc_to_u8(raw, None, {"kind": "probability", "scale": 1.0},
                     np.ones(100, dtype=bool))
t.ok("quantisation: u is kept to within half a level (1/508) of 1 - p",
     np.all(np.abs(u8 / 254.0 - (1 - raw)) <= 0.5 / 254.0 + 1e-12))
votes = np.array([2, 1, 0, 0, 3, 5], dtype=float)
lab = np.array([2, 2, 3, 0, 3, 4], dtype=float)
u8, said = rl.unc_to_u8(votes, lab, {"kind": "votes"},
                        np.ones(6, dtype=bool))
want = [rhalf(1.0 - v / n) if n >= 1 else 255 for v, n in zip(votes, lab)]
want[5] = rhalf(1.0 - 1.0)           # 5 votes of 4 readings: clipped to 1
t.ok("votes v of n readings labelled: u = 1 - v/n, no value where n is 0",
     u8.tolist() == want, (u8.tolist(), want))
u8, said = rl.unc_to_u8(np.array([0.0, 255.0, 51.0]), None,
                        {"kind": "entropy", "scale": 255.0},
                        np.ones(3, dtype=bool), band_nodata=0.0)
t.ok("an entropy whose nodata is 0 under a class: the 0 is a value (u 0), "
     "counted", u8.tolist() == [0, 254, rhalf(51 / 255.0)]
     and said["zero_read_as_value"] == 1, (u8.tolist(), said))
u8, _ = rl.unc_to_u8(np.array([100.0, 200.0]), None,
                     {"kind": "uncertainty", "scale": 255.0},
                     np.array([True, False]))
t.ok("outside the class band: no value", u8.tolist() == [rhalf(100 / 255.0),
                                                        255])
u8, _ = rl.unc_to_u8(np.array([50.0]), None,
                     {"kind": "uncertainty", "scale": 100.0},
                     np.array([True]), gain=0.5, offset=10.0)
t.ok("the band's own GDAL scale and offset come first: (raw g + o) / scale",
     u8.tolist() == [rhalf((50 * 0.5 + 10) / 100.0)])

print()
print("U: the AUC")


def auc_pairs(u, changed):
    pos = u[changed]
    neg = u[~changed]
    if not len(pos) or not len(neg):
        return nan
    s = 0.0
    for a in pos:
        s += float((neg < a).sum()) + 0.5 * float((neg == a).sum())
    return s / (len(pos) * len(neg))


bad = []
for case in range(50):
    n = int(rng.integers(2, 400))
    levels = int(rng.choice([2, 5, 30, 254]))
    u = rng.integers(0, levels, n)
    p_ch = 1.0 / (1.0 + np.exp(-(u - levels / 2.0) / max(1.0, levels / 6.0)))
    ch = rng.random(n) < p_ch * rng.choice([0.2, 0.7, 1.0])
    h_all = np.bincount(u, minlength=U)
    h_chg = np.bincount(u[ch], minlength=U)
    got = rl.st_auc_hist(h_chg, h_all - h_chg)
    if not same(got, auc_pairs(u, ch), 1e-12):
        bad.append((case, got, auc_pairs(u, ch)))
    elif sst is not None and ch.any() and (~ch).any():
        uu = sst.mannwhitneyu(u[ch], u[~ch], alternative="two-sided",
                              use_continuity=False).statistic
        if not same(got, uu / float(ch.sum() * (~ch).sum()), 1e-12):
            bad.append((case, "scipy", got, uu))
t.ok("50 random maps (ties everywhere): the AUC is the share of "
     "(changed, unchanged) pairs in which the changed pixel has the higher "
     "u, ties one half%s"
     % ("" if sst is not None else " [scipy part NOT CHECKED]"), not bad,
     bad[:2])
if sst is None:
    need_scipy("scipy.stats.mannwhitneyu: AUC = U / (n1 n2)")
t.near("all ties: 0.5", rl.st_auc_hist([0, 3, 0], [0, 4, 0]), 0.5)
t.near("perfect: changed all above unchanged = 1",
       rl.st_auc_hist([0, 0, 5], [5, 0, 0]), 1.0)
t.near("worst: 0", rl.st_auc_hist([5, 0, 0], [0, 0, 5]), 0.0)
t.ok("no changed pixel (or no unchanged): NaN, not 0.5",
     math.isnan(rl.st_auc_hist([0, 0], [3, 4]))
     and math.isnan(rl.st_auc_hist([3, 4], [0, 0])))

print()
print("U: the ECE, the deciles and the capture curve, by pixels")


def floor_tenths(level):
    """The fixed bin of a level: tenths of the scale, the last one closed."""
    return min(9, int(math.floor(Fraction(level, U) * 10)))


bad = []
for case in range(25):
    n = int(rng.integers(30, 2500))
    u = np.clip(rng.normal(rng.uniform(40, 200), rng.uniform(10, 80), n)
                .round(), 0, 253).astype(np.uint8)
    p_err = np.clip(u / 254.0 * rng.uniform(0.3, 1.3), 0, 1)
    ch = (rng.random(n) < p_err).astype(np.uint8)
    img = u.reshape(1, -1)
    mk = ch.reshape(1, -1)
    cal = rl.unc_calibrate(img, mk, None, None, "probability")
    # ECE: ten equal bins of u (tenths of the scale, the last one closed);
    # in each, the share changed against the mean u
    bins = collections.defaultdict(list)
    for lv, c in zip(u.tolist(), ch.tolist()):
        bins[floor_tenths(lv)].append((lv / 254.0, c))
    ece = sum(len(v) / float(n) * abs(np.mean([c for _, c in v])
                                      - np.mean([x for x, _ in v]))
              for v in bins.values())
    if not same(cal["ece"]["whole_map"], ece, 1e-10):
        bad.append((case, "ece", cal["ece"]["whole_map"], ece))
    # AUC, whole map
    if not same(cal["auc"]["whole_map"], auc_pairs(u, ch.astype(bool)), 1e-12):
        bad.append((case, "auc"))
    # deciles: cut k is the lowest level whose cumulative count reaches kN/10
    cnt = collections.Counter(u.tolist())
    top = max(cnt)
    cuts, cum, lv = set(), 0, 0
    levels = sorted(cnt)
    for k in range(1, 10):
        cum = 0
        for lv in levels:
            cum += cnt[lv]
            if Fraction(cum) >= Fraction(k * n, 10):
                break
        if lv < top:
            cuts.add(lv)
    if sorted(cuts) != cal["cuts"]:
        bad.append((case, "cuts", cal["cuts"], sorted(cuts)))
    else:
        rows = [r for r in cal["rows"] if r["scope"] == "whole_map"
                and r["binning"] == "decile"]
        want_rows = collections.OrderedDict()
        for lv, c in zip(u.tolist(), ch.tolist()):
            b = sum(1 for cut in sorted(cuts) if cut < lv)
            e = want_rows.setdefault(b, [0, 0])
            e[0] += 1
            e[1] += c
        if [(r["bin"], r["n_px"], r["changed_px"]) for r in rows] != \
                [(b, v[0], v[1]) for b, v in sorted(want_rows.items())]:
            bad.append((case, "decile rows"))
        elif not all(same(r["share_changed"], r["changed_px"] / float(r["n_px"]))
                     for r in rows):
            bad.append((case, "share"))
    # capture: whole levels, from the highest u down, until the area reaches t
    for row in [r for r in cal["capture"] if r["scope"] == "whole_map"]:
        tt = Fraction(str(row["top_share"]))
        area = caught = 0
        for lv in sorted(cnt, reverse=True):
            area += cnt[lv]
            caught += int(ch[u == lv].sum())
            if Fraction(area) >= tt * n:
                break
        want_c = caught / float(ch.sum()) if ch.sum() else nan
        if not (row["level"] == lv and same(row["share_of_area"], area / n)
                and same(row["share_of_changes_captured"], want_c)
                and same(row["u_threshold"], lv / 254.0)):
            bad.append((case, "capture", row, lv, area, caught))
t.ok("25 random maps: ECE (ten equal bins of u, last closed), AUC, decile "
     "cuts and rows, capture curve all equal the count by pixel", not bad,
     bad[:2])
t.ok("capture: the 100 % row holds all the change", all(
    same(r["share_of_changes_captured"], 1.0) for r in cal["capture"]
    if r["top_share"] == 1.0 and r["scope"] == "whole_map"))
# worked: ten levels of ten pixels, 100 in all; the share asked for is
# reached exactly at a level (no float slack may move it): the top 10 % is
# level 9, the top 20 % level 8; every changed pixel at level 9 and 3
hh = np.zeros(255, dtype=np.int64)
hc = np.zeros(255, dtype=np.int64)
hh[:10] = 10
hc[9], hc[3] = 5, 5
cap = {r["top_share"]: r for r in rl.st_capture(hh, hc)}
t.ok("capture, shares reached exactly: 1 % and 10 % stop at level 9 (a "
     "level comes whole, so 10 % of the area), 20 % at level 8, 100 % at "
     "level 0",
     cap[0.01]["level"] == 9 and cap[0.10]["level"] == 9
     and cap[0.20]["level"] == 8 and cap[1.0]["level"] == 0
     and same(cap[0.10]["share_of_area"], 0.1)
     and same(cap[0.10]["share_of_changes_captured"], 0.5)
     and same(cap[0.30]["share_of_changes_captured"], 0.5)
     and same(cap[0.50]["share_of_changes_captured"], 0.5)
     and same(cap[1.0]["share_of_changes_captured"], 1.0), cap)

# worked: three levels a third each: cuts [0, 127]; three parts
h = np.zeros(255, dtype=np.int64)
h[[0, 127, 254]] = 10
t.ok("three levels a third each give the cuts [0, 127]",
     rl.st_decile_cuts(h) == [0, 127])
t.ok("the same fixed bin, whichever way it is asked: level 127 of 254 is in "
     "the sixth tenth, 253 and 254 in the last",
     [int(v) for v in rl.st_fixed_bin(np.array([0, 25, 26, 127, 253, 254]))]
     == [floor_tenths(v) for v in (0, 25, 26, 127, 253, 254)])
t.ok("expected calibration error of a perfect curve is 0, of a constant "
     "0.3 gap is 0.3",
     same(rl.st_ece([10, 20], [0.2, 0.7], [0.2, 0.7]), 0.0)
     and same(rl.st_ece([10, 20], [0.5, 1.0], [0.2, 0.7]), 0.3)
     and same(rl.st_ece([10, 0], [0.5, 1.0], [0.2, 0.7]), 0.3)
     and math.isnan(rl.st_ece([0], [0.5], [0.2])))

print()
print("U: the cluster ratio estimator, against a simulation")
# A population of 60 places with x_i pixels in a bin and y_i changed. Draw
# 20 places without replacement many times: the standard deviation of the
# ratio estimate over the draws is the true standard error, and the
# estimator's own average must come out within a few percent of it. The
# finite population correction matters here: 20 of 60.
pop_x = rng.integers(40, 400, 60).astype(float)
pop_y = np.array([rng.binomial(int(x), 0.15 + 0.25 * rng.random())
                  for x in pop_x], dtype=float)
est, ses, ses_nofpc = [], [], []
for _ in range(6000):
    pick = rng.choice(60, size=20, replace=False)
    got = rl.st_ratio_se(pop_y[pick], pop_x[pick], N=60)
    est.append(got["R"])
    ses.append(got["se"] ** 2)
    ses_nofpc.append(rl.st_ratio_se(pop_y[pick], pop_x[pick])["se"] ** 2)
true_se = float(np.std(est))
t.ok("the mean estimated variance with the fpc is the true variance of the "
     "ratio over draws (within 6 %)",
     abs(math.sqrt(float(np.mean(ses))) / true_se - 1.0) < 0.06,
     (math.sqrt(float(np.mean(ses))), true_se))
t.ok("without N the fpc is not applied: the standard error is larger by "
     "1 / sqrt(1 - 20/60)",
     abs(math.sqrt(float(np.mean(ses_nofpc)) / float(np.mean(ses)))
         - 1.0 / math.sqrt(1.0 - 20.0 / 60.0)) < 1e-9)
yy, xx = np.array([3.0, 8.0, 5.0]), np.array([20.0, 50.0, 40.0])
r_ = yy.sum() / xx.sum()
var = ((yy - r_ * xx) ** 2).sum() / 2.0 / (3 * (xx.sum() / 3) ** 2)
t.near("Cochran (1977, 6.3) by hand on three places",
       rl.st_ratio_se(yy, xx)["se"], math.sqrt(var), 1e-12)
t.near("with N = 12 the variance is multiplied by 1 - 3/12",
       rl.st_ratio_se(yy, xx, 12)["se"], math.sqrt(var * 0.75), 1e-12)
t.ok("one place: the ratio but no standard error",
     math.isnan(rl.st_ratio_se([3.0], [20.0])["se"])
     and same(rl.st_ratio_se([3.0], [20.0])["R"], 0.15))

print()
print("U: the share changed per bin, with its standard error and interval")
# Eight random places of a map of 40 (N), each with its own histogram of u
# and of the pixels changed in it; the rows of the report, by hand: in a
# bin, x_i the pixels of place i and y_i those changed, R = sum y / sum x,
# SE from Cochran's formula with the finite population correction 1 - 8/40,
# the interval R +- 1.96 SE cut to 0..1.
m_, big_n = 8, 40
p_all = np.zeros((m_, 255), dtype=np.int64)
p_chg = np.zeros((m_, 255), dtype=np.int64)
for i in range(m_):
    lv = np.clip(rng.normal(120, 60, 400).round(), 0, 253).astype(int)
    ch = rng.random(400) < lv / 300.0
    p_all[i] = np.bincount(lv, minlength=255)
    p_chg[i] = np.bincount(lv[ch], minlength=255)
h_all, h_chg = p_all.sum(axis=0), p_chg.sum(axis=0)
cuts_ = rl.st_decile_cuts(h_all)
rows_ = rl.unc_scope_rows("random_places", h_all, h_chg, np.zeros(255, int),
                          cuts_, "probability", p_all, p_chg, big_n)
bad = []
for r in rows_:
    if r["binning"] != "fixed":
        continue
    lo = [lv for lv in range(255) if floor_tenths(lv) == r["bin"]]
    x = p_all[:, lo].sum(axis=1).astype(float)
    y = p_chg[:, lo].sum(axis=1).astype(float)
    R = y.sum() / x.sum()
    xbar = x.sum() / m_
    var = (1 - m_ / float(big_n)) * ((y - R * x) ** 2).sum() / (m_ - 1)         / (m_ * xbar ** 2)
    se = math.sqrt(var)
    if not (same(r["share_changed"], R) and same(r["se_share"], se)
            and same(r["ci95_low"], max(0.0, R - 1.96 * se))
            and same(r["ci95_high"], min(1.0, R + 1.96 * se))
            and r["n_px"] == int(x.sum()) and r["changed_px"] == int(y.sum())
            and r["places"] == int((x > 0).sum())):
        bad.append((r["bin"], r["share_changed"], R, r["se_share"], se))
t.ok("tenths of the scale: share, SE (fpc 1 - m/N), the 1.96 interval, the "
     "pixels and the places that hold the bin all as by hand", not bad,
     bad[:2])
t.ok("expected error is the mean u in the bin for a probability, absent "
     "for the other kinds",
     all(r["expected_error"] is not None for r in rows_)
     and all(r["expected_error"] is None for r in rl.unc_scope_rows(
         "whole_map", h_all, h_chg, np.zeros(255, int), cuts_, "entropy")))
t.ok("the decile cuts of a single level, of nothing and of the top level "
     "alone",
     rl.st_decile_cuts(np.eye(255, dtype=np.int64)[7] * 50) == []
     and rl.st_decile_cuts(np.zeros(255, dtype=np.int64)) == []
     and rl.st_decile_cuts(np.eye(255, dtype=np.int64)[254] * 3) == [])

print()
print("U: ranking the places and the random sample")
bad = []
for case in range(30):
    ny, nx = int(rng.integers(3, 40)), int(rng.integers(3, 40))
    side = int(rng.integers(2, 9))
    img = rng.integers(0, 255, (ny, nx)).astype(np.uint8)
    img[rng.random((ny, nx)) < 0.2] = 255
    img[rng.random((ny, nx)) < 0.3] = 40         # ties between places
    blocks = rl.unc_score_blocks(img, side)
    order = rl.unc_rank(blocks)
    want = []
    for b in range(blocks["bi"].size):
        i, j = int(blocks["bi"][b]), int(blocks["bj"][b])
        win = img[i * side:(i + 1) * side, j * side:(j + 1) * side]
        v = win[win < 255].astype(float)
        npx = win.size
        if v.size == 0 or v.size < 0.5 * npx:
            continue
        want.append((-v.sum() / v.size, -v.max(), i, j))
    want.sort()
    got = [(-blocks["sum"][b] / blocks["n_valid"][b], -blocks["max"][b],
            int(blocks["bi"][b]), int(blocks["bj"][b])) for b in order]
    if [(g[2], g[3]) for g in got] != [(w[2], w[3]) for w in want]:
        bad.append((case, got[:3], want[:3]))
t.ok("30 random maps: places ranked by mean u, then max u, then row, then "
     "column; only those with half their pixels valid", not bad, bad[:1])
img = rng.integers(0, 254, (24, 24)).astype(np.uint8)
blocks = rl.unc_score_blocks(img, 4)
N = int(blocks["eligible"].sum())
t.ok("36 places of 4 x 4", N == 36)
freq = collections.Counter()
seeds = range(300)
for sd in seeds:
    pl = rl.Places.from_blocks(os.path.join(root, "w%d.csv" % sd), blocks,
                               (0.0, 1.0, 0.0, 24.0, 0.0, -1.0), 24, 24, sd,
                               5, True)
    perm = np.random.default_rng(sd).permutation(N)
    for k in range(10):                       # ten offers: two draws due
        row = pl.next("t")
        pl.done("A", "t", False, 0)
    rnd = sorted((r for r in pl.rows if r["selection"] == "random"),
                 key=lambda r: r["random_order"])
    m = len(rnd)
    first = sorted(pl.rows, key=lambda r: r["random_order"])[:m]
    if [r["place_id"] for r in rnd] != [r["place_id"] for r in first]:
        bad.append(("not the first m of the permutation", sd))
    pi = pl.fill_inclusion()
    if not same(pi, pl.counts()["random_drawn_m"] / float(N)):
        bad.append(("inclusion", sd))
    for r in rnd:
        freq[r["place_id"]] += 1
t.ok("300 seeds: the random places are always the first m of the seeded "
     "permutation, and the inclusion probability is m / N", not bad, bad[:2])
ms = [c for c in freq.values()]
share = sum(ms) / (300.0 * N)
spread = max(abs(c / 300.0 - share) for c in freq.values())
t.ok("and over seeds every place is as likely to be in the sample as any "
     "other (largest departure from the mean share < 0.12)", spread < 0.12,
     (share, spread))

# --------------------------------------------------------------------- C
print()
print("C: the card")
# The shipped file, cut into its modules (what the program runs), not the
# package beside it.
_, shipped = purekit.sections()
src_rasters = shipped["rasters"]
src_campaign = shipped["campaign"]
src_card = shipped["card"]


def function_source(text, name):
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(text, node)
    raise LookupError(name)


ns = {"np": np}
exec(function_source(src_campaign, "majority"), ns)
exec(function_source(src_rasters, "vote"), ns)
t.ok("a consensus needs n // 2 + 1 readings: 2 of 2, 2 of 3, 3 of 4, 3 of "
     "5", [ns["majority"](n) for n in (1, 2, 3, 4, 5, 6)] == [1, 2, 2, 3, 3, 4]
     and all(ns["majority"](n) == n // 2 + 1 for n in range(1, 40)))
bad = []
for case in range(60):
    n = int(rng.integers(1, 7))
    npx = int(rng.integers(1, 80))
    ncls = int(rng.integers(1, 5))
    labels = [rng.integers(0, ncls + 1, npx).astype(np.uint8)
              for _ in range(n)]
    classes, votes, labelled = ns["vote"](labels)
    for px in range(npx):
        col = [int(l[px]) for l in labels]
        painted = [c for c in col if c]
        cnt = collections.Counter(painted)
        win = [c for c, k in cnt.items() if k >= n // 2 + 1]
        want_c = win[0] if win else 0
        want_v = cnt[want_c] if win else 0
        if len(win) > 1 or (int(classes[px]), int(votes[px]),
                            int(labelled[px])) != (want_c, want_v,
                                                   len(painted)):
            bad.append((case, px, col, int(classes[px]), int(votes[px])))
t.ok("60 random sets of 1 to 6 readings: the consensus class is the one a "
     "strict majority painted, 0 otherwise; votes and 'painted' counted "
     "per pixel; never two classes", not bad, bad[:2])
t.near("a frame is closed above 0.995 of its area", rl.CLOSED_SHARE, 0.995)
t.ok("the card says so: strict majority n//2+1, closed above 99.5 %",
     "strict majority, n//2+1 of n readings" in src_card
     and rl.card_rules()["closed"] == "fullest single reading paints > 99.5% "
     "of the frame area", rl.card_rules()["closed"])
t.ok("reading_closed is strict: 0.995 itself is not closed, 0.9951 is",
     "float(s) > CLOSED_SHARE" in src_campaign)
t.ok("a share is a percentage with one decimal, empty when undefined",
     rl.card_percent(0.995) == "99.5%" and rl.card_percent(nan) == ""
     and rl.card_percent(0.12345, 2, sign=False) == "12.35")
cons = {"mode": "consensus", "label": "consensus", "tag": "consensus",
        "readings": [["A", 1], ["B", 1], ["C", 1]],
        "votes_histogram": {"0": 20, "2": 30, "3": 50},
        "no_majority_px": 20, "all_painted_disagree_px": 12}
line = rl.card_consensus_line(cons)
t.ok("the sentence under the table: pixels agreed by 3 of 3 and by 2 of 3, "
     "the ones without a majority split in painted by all and by fewer",
     "50 px agreed by 3 of 3, 30 px agreed by 2 of 3" in line
     and "20 px without a majority" in line and "12 painted by all 3" in line
     and "8 by fewer" in line, line)
cons4 = dict(cons, readings=[["A", 1], ["B", 1], ["C", 1], ["D", 1]],
             votes_histogram={"3": 40, "4": 40})
line4 = rl.card_consensus_line(cons4)
t.ok("with four readings or more 'all painted' does not claim they painted "
     "differently (two and two is no majority either)",
     "painted by all 4 with no class in the majority" in line4
     and "differently" not in line4, line4)

# --------------------------------------------------------------------- D
print()
print("D: the design: a weight is one over its inclusion probability")
for p_, w_ in ((0.05, 20.0), (0.25, 4.0), (1.0, 1.0), (0.3, 1 / 0.3)):
    pp, fp = rl.design_parse_prob(str(p_))
    ww, fw = rl.design_parse_weight(repr(w_))
    t.ok("p %g, w %g: both kept, w p = 1" % (p_, w_),
         fp is None and fw is None and abs(ww * pp - 1.0) < 1e-12)
t.ok("a probability must be in (0, 1]: 0, 1.2, -0.1, text and NaN are "
     "refused and flagged, 1 and 1e-9 are kept",
     all(rl.design_parse_prob(v) == (None, "bad_value:incl_prob")
         for v in ("0", "1.2", "-0.1", "abc", "nan", "inf"))
     and rl.design_parse_prob("1")[0] == 1.0
     and rl.design_parse_prob("1e-9")[0] == 1e-9)
t.ok("a weight must be above 0 (it may be below 1 or above 100000)",
     all(rl.design_parse_weight(v) == (None, "bad_value:weight")
         for v in ("0", "-3", "x"))
     and rl.design_parse_weight("0.5")[0] == 0.5
     and rl.design_parse_weight("250000")[0] == 250000.0)
t.ok("a comma as the decimal mark is read, 1,000.5 is refused",
     rl.design_parse_prob("0,05") == (0.05, None)
     and rl.design_parse_weight("1,000.5") == (None, "bad_value:weight"))
frames = {"t1": {"incl_prob": 0.05, "weight": 20.0},
          "t2": {"incl_prob": 0.05, "weight": 20.000001},       # within 1e-6
          "t3": {"incl_prob": 0.05, "weight": 20.001},          # 2e-5 off
          "t4": {"incl_prob": 0.3333, "weight": 3.0},           # a rounded p
          "t5": {"incl_prob": 0.05, "weight": None},
          "t6": {"incl_prob": None, "weight": 7.0}}


class Finding(object):
    def __init__(self, level, what, detail=""):
        self.level, self.what, self.detail = level, what, detail


rl.design_findings.__globals__["Finding"] = Finding
rl.design_findings.__globals__["frame_design"] = lambda p: dict(frames)
pkg = os.path.join(root, "design.gpkg")
open(pkg, "wb").close()
owner = type("O", (), {"folder": root, "package_path": pkg, "data": {}})()
found = rl.design_findings(owner)
odd = [f for f in found if "weight is not one over" in f.what]
t.ok("Check names the frames whose w x p differs from 1 by more than "
     "1e-6 (absolute), and only those: t3 and t4; a frame missing p or w "
     "is not judged", len(odd) == 1 and "on 2 frames" in odd[0].what
     and "t3" in odd[0].detail and "t4" in odd[0].detail
     and "t1" not in odd[0].detail and "t2" not in odd[0].detail
     and "t5" not in odd[0].detail and "t6" not in odd[0].detail,
     [(f.what, f.detail) for f in found])

# ------------------------------------------------------------------ Journal
print()
print("T: the stopwatch of a stroke")
clock = [0.0]
sw = rl.Stopwatch(clock=lambda: clock[0])
sw.begin()
for at in (3.0, 14.0, 24.0, 24.5, 40.0):
    clock[0] = at
    sw.touch()
dur_ms, pauses = sw.take()
t.ok("a stroke lasts from the first touch to the last; a gap of 10 s or "
     "more between touches is kept as a pause (11, 10, 15.5), to a tenth",
     dur_ms == 40000 and pauses == "11.0;10.0;15.5", (dur_ms, pauses))
clock[0] = 100.0
sw.begin()
clock[0] = 109.9
sw.touch()
t.ok("a gap under 10 s is not a pause (9.9 s)", sw.take() == (9900, ""))
clock[0] = 200.0
sw.begin()
clock[0] = 210.0
sw.touch()
t.ok("a gap of exactly 10 s is", sw.take()[1] == "10.0")

# Compare: the hours from A's last mark in a frame to B's first
cmp_ns = purekit.load("stats", "agreement", "reports", "design", "journal",
                      "effort", "compare")
t.near("delay: B's first mark 26.5 h after A's last",
       cmp_ns._cmp_delay("2026-03-04T14:30:00", "2026-03-03T12:00:00"), 26.5)
t.near("and negative when B was drawn first",
       cmp_ns._cmp_delay("2026-03-03T10:00:00", "2026-03-03T12:00:00"), -2.0)
t.ok("an unreadable time: no delay", cmp_ns._cmp_delay("", "2026-03-03T12:00:00")
     is None)

shutil.rmtree(root, ignore_errors=True)

print()
if skipped:
    print("NOT CHECKED, scipy is not installed (%d): " % len(skipped))
    for s_ in skipped:
        print("   " + s_)
    if os.environ.get("RL_REQUIRE_SCIPY", "") not in ("", "0"):
        t.ok("scipy is required here (RL_REQUIRE_SCIPY) and is missing",
             False, "%d checks skipped" % len(skipped))
else:
    print("scipy %s: every scipy cross-check ran" % scipy.__version__)
t.done()
