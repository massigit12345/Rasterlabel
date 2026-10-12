"""rasterlabel.stats

The few pieces of statistics the reports need, written out so that nothing
has to be installed for them: a spread over frames, a bootstrap interval, the
Wilcoxon signed-rank test, a ratio estimator with its standard error, and the
histogram arithmetic of a calibration curve.

Numpy and math only, and nothing from the rest of the program, so every
function here can be tried on a machine with no QGIS and no GDAL, against
numbers worked out by hand. An undefined value is NaN, never 0 and never an
exception: a frame with one class has no kappa, and a report has to be able
to say "undefined" and carry on.

Every random draw goes through numpy.random.default_rng(seed), so the same
seed gives the same interval on every machine and every version of the
program, and the seed is what a report writes down beside the interval.
"""
import math

import numpy as np


ST_NAN = float("nan")


def st_finite(values):
    """The values as a float array, with NaN and None left out."""
    out = []
    for v in values if values is not None else []:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return np.asarray(out, dtype=np.float64)


def st_spread(values):
    """Median, first and third quartile, and how many values were defined.

    Linear interpolation between the order statistics (Hyndman and Fan's type
    7, numpy's default), the same rule R's quantile() uses by default, so a
    reader checking a number in R gets the same number. A frame whose value
    is undefined is left out and not counted in n."""
    v = st_finite(values)
    if not v.size:
        return {"median": ST_NAN, "q1": ST_NAN, "q3": ST_NAN, "n": 0}
    q1, med, q3 = np.percentile(v, [25.0, 50.0, 75.0])
    return {"median": float(med), "q1": float(q1), "q3": float(q3),
            "n": int(v.size)}


def st_percentile_ci(samples, level=0.95):
    """(low, high) of the bootstrap replicates, by the percentile method.

    Efron's percentile interval (Efron and Tibshirani 1993, chapter 13): the
    (1 - level)/2 and (1 + level)/2 quantiles of the replicates. A replicate
    whose statistic is undefined is left out; with none left, both ends are
    NaN."""
    v = st_finite(samples)
    if not v.size:
        return (ST_NAN, ST_NAN)
    tail = (100.0 - level * 100.0) / 2.0
    lo, hi = np.percentile(v, [tail, 100.0 - tail])
    return (float(lo), float(hi))


def st_bootstrap_stat(values, fn, n_boot, seed, level=0.95, min_n=2):
    """A statistic of a sample with its bootstrap interval.

    The sample is drawn again n_boot times with replacement, the same size
    as itself, and fn is computed on each draw (Efron 1979). fn takes a float
    array and returns a number, NaN when it is undefined. What comes back
    says how it was done: the estimate on the sample itself, the interval or
    None, the number of replicates and the seed, how many replicates gave a
    defined value, and why there is no interval when there is none."""
    v = st_finite(values)
    out = {"estimate": float(fn(v)) if v.size else ST_NAN, "ci": None,
           "n": int(v.size), "n_boot": int(n_boot or 0), "seed": seed,
           "level": level, "n_valid": 0,
           "method": "percentile; resampled with replacement", "reason": ""}
    if not n_boot or n_boot <= 0:
        out["reason"] = "no resampling asked for"
        return out
    if v.size < max(1, min_n):
        out["reason"] = "fewer than %d values" % max(1, min_n)
        return out
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, v.size, size=(int(n_boot), v.size))
    reps = np.array([fn(v[row]) for row in idx], dtype=np.float64)
    out["n_valid"] = int(np.isfinite(reps).sum())
    out["ci"] = list(st_percentile_ci(reps, level))
    return out


def _st_exact_upper(ranks2, w2):
    """P(W+ >= w) and P(W+ <= w) under the null, exactly.

    ranks2 are the ranks doubled, so a tie's half rank is a whole number, and
    w2 is W+ doubled the same way. Under the null hypothesis each rank is
    positive or negative with probability one half, independently, so the
    distribution of W+ is the count of the 2**n sign patterns giving each
    sum. That count is built one rank at a time, which is exact with ties as
    well as without, and cheap for the n <= 25 it is used for."""
    total = int(sum(ranks2))
    counts = np.zeros(total + 1, dtype=np.float64)
    counts[0] = 1.0
    for r in ranks2:
        r = int(r)
        shifted = np.zeros_like(counts)
        shifted[r:] = counts[:total + 1 - r]
        counts = counts + shifted
    counts /= counts.sum()
    w2 = int(round(w2))
    return float(counts[w2:].sum()), float(counts[:w2 + 1].sum())


def st_wilcoxon_signed(values, exact_max=25):
    """The Wilcoxon signed-rank test that the median of values is 0.

    Wilcoxon (1945). Zeros are dropped, as Wilcoxon did, and tied absolute
    values share their mean rank. W+ is the sum of the ranks of the positive
    values. Two-sided p: exact for up to exact_max non-zero values, from the
    full null distribution of W+; above that, the normal approximation with
    the tie correction of the variance and a continuity correction of one
    half. Five values all of one sign give W+ = 0 or 15 and p = 2/32."""
    v = st_finite(values)
    v = v[v != 0]
    n = int(v.size)
    out = {"n": n, "w_plus": ST_NAN, "w_minus": ST_NAN, "p": ST_NAN, "method": ""}
    if n == 0:
        out["method"] = "no value different from 0"
        return out
    a = np.abs(v)
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(n, dtype=np.float64)
    sorted_a = a[order]
    i = 0
    ties = []
    while i < n:
        j = i
        while j + 1 < n and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        if j > i:
            ties.append(j - i + 1)
        i = j + 1
    w_plus = float(ranks[v > 0].sum())
    out["w_plus"] = w_plus
    out["w_minus"] = float(ranks[v < 0].sum())
    if n <= exact_max:
        upper, lower = _st_exact_upper(np.round(ranks * 2).astype(int),
                                       w_plus * 2)
        out["p"] = min(1.0, 2.0 * min(upper, lower))
        out["method"] = "exact"
        return out
    mean = n * (n + 1) / 4.0
    var = n * (n + 1) * (2 * n + 1) / 24.0 - sum(t ** 3 - t for t in ties) / 48.0
    if var <= 0:
        out["method"] = "normal approximation: no variance"
        return out
    z = max(0.0, abs(w_plus - mean) - 0.5) / math.sqrt(var)
    out["p"] = min(1.0, math.erfc(z / math.sqrt(2.0)))
    out["method"] = "normal approximation, tie and continuity corrected"
    return out


def st_ratio_se(y, x, N=None):
    """A ratio of totals over clusters, and its standard error.

    The ratio estimator of Cochran (1977, section 6.3), with places (or
    frames) as the clusters: R = sum(y) / sum(x), and

        V(R) = (1 - m/N) * sum((y_i - R x_i)**2) / (m - 1) / (m * xbar**2)

    with m clusters in the sample and xbar = sum(x) / m. The finite
    population correction 1 - m/N is applied only when N, the number of
    clusters there are to draw from, is given; without it the same number is
    a spread between clusters, not a design-based standard error, and the
    caller has to say so. Fewer than two clusters: no standard error."""
    yy = np.asarray([float(v) for v in y], dtype=np.float64)
    xx = np.asarray([float(v) for v in x], dtype=np.float64)
    m = int(yy.size)
    out = {"R": ST_NAN, "se": ST_NAN, "m": m, "fpc": None}
    if m == 0 or xx.sum() <= 0:
        return out
    r = float(yy.sum() / xx.sum())
    out["R"] = r
    if m < 2:
        return out
    xbar = xx.sum() / m
    fpc = 1.0
    if N:
        fpc = max(0.0, 1.0 - m / float(N))
        out["fpc"] = fpc
    var = fpc * float(((yy - r * xx) ** 2).sum()) / (m - 1) / (m * xbar ** 2)
    out["se"] = math.sqrt(var)
    return out


def st_auc_hist(h_pos, h_neg):
    """The area under the ROC curve, from two histograms over the same levels.

    The probability that a level drawn from the positives is higher than one
    drawn from the negatives, ties counted one half: the Mann-Whitney U over
    the product of the two counts (Hanley and McNeil 1982). Here the levels
    are the uncertainty, the positives the pixels a person changed:

        AUC = sum_v Hpos[v] * (Cneg(<v) + Hneg[v] / 2) / (Npos * Nneg)

    NaN when either side is empty."""
    p = np.asarray(h_pos, dtype=np.float64)
    q = np.asarray(h_neg, dtype=np.float64)
    n_pos, n_neg = p.sum(), q.sum()
    if n_pos <= 0 or n_neg <= 0:
        return ST_NAN
    below = np.concatenate([[0.0], np.cumsum(q)[:-1]])
    return float((p * (below + 0.5 * q)).sum() / (n_pos * n_neg))


def st_ece(n, observed, expected):
    """Expected calibration error over bins.

    ECE = sum_b (n_b / N) |observed_b - expected_b| (Naeini, Cooper and
    Hauskrecht 2015; Guo et al. 2017): the gap between the error a model
    stated and the error found, weighted by how much of the map each bin
    holds. Bins with nothing in them are left out."""
    nn = np.asarray(n, dtype=np.float64)
    ob = np.asarray(observed, dtype=np.float64)
    ex = np.asarray(expected, dtype=np.float64)
    keep = (nn > 0) & np.isfinite(ob) & np.isfinite(ex)
    total = nn[keep].sum()
    if total <= 0:
        return ST_NAN
    return float((nn[keep] / total * np.abs(ob[keep] - ex[keep])).sum())


def st_decile_cuts(h_all, parts=10):
    """The levels that cut a histogram into parts of equal count.

    L_k = the lowest level whose cumulative count reaches k N / parts, for k
    = 1 .. parts-1. A level equal to a cut belongs to the lower part. Tied
    levels make cuts coincide, and they are kept once; a cut at the highest
    level present, or above it, separates nothing and is dropped. So three
    levels a third each give the cuts [0, 127], and three parts."""
    h = np.asarray(h_all, dtype=np.float64)
    total = h.sum()
    if total <= 0:
        return []
    cum = np.cumsum(h)
    top = int(np.nonzero(h)[0].max())
    cuts = set()
    for k in range(1, parts):
        target = k * total / parts
        level = int(np.searchsorted(cum, target - 1e-9 * total, side="left"))
        if level < top:
            cuts.add(level)
    return sorted(cuts)


def st_bin_of(levels, cuts):
    """The part each level falls in: how many cuts lie below it."""
    return np.searchsorted(np.asarray(cuts, dtype=np.int64),
                           np.asarray(levels), side="left")


def st_fixed_bin(levels, top=254, parts=10):
    """The fixed bin of a level: tenths of the scale, the last one closed."""
    v = np.asarray(levels, dtype=np.int64)
    return np.minimum(parts - 1, (v * parts) // top)


def st_calibration(h_all, h_chg, binning="decile", top=254, parts=10,
                   cuts=None):
    """The calibration curve as rows, one per bin that holds anything.

    h_all[v] counts the pixels at level v, h_chg[v] those of them a person
    changed. binning "decile" cuts by st_decile_cuts (or by the cuts given,
    so every scope can share the cuts of the whole map); "fixed" by tenths of
    the scale. Each row: bin, u_low and u_high (the lowest and highest level
    present, over top), n, changed, share = changed / n, and mean_u = the
    mean level over top."""
    h = np.asarray(h_all, dtype=np.float64)
    c = np.asarray(h_chg, dtype=np.float64)
    levels = np.arange(h.size)
    if binning == "fixed":
        bins = st_fixed_bin(levels, top, parts)
    else:
        if cuts is None:
            cuts = st_decile_cuts(h, parts)
        bins = st_bin_of(levels, cuts)
    rows = []
    for b in sorted(set(int(x) for x in bins[h > 0])):
        inside = (bins == b) & (h > 0)
        n = float(h[inside].sum())
        changed = float(c[inside].sum())
        present = levels[inside]
        rows.append({"bin": b, "u_low": float(present.min()) / top,
                     "u_high": float(present.max()) / top,
                     "n": int(round(n)), "changed": int(round(changed)),
                     "share": changed / n if n else ST_NAN,
                     "mean_u": float((levels[inside] * h[inside]).sum())
                     / (top * n) if n else ST_NAN})
    return rows


def st_capture(h_all, h_chg, tops=(0.01, 0.02, 0.05, 0.10, 0.20, 0.30,
                                   0.50, 1.00), top=254):
    """How much of the change the most uncertain part of the map holds.

    The levels are taken from the highest down, adding up area and changes.
    For each share t, the first level at which the area reached reaches t of
    the whole gives the threshold, the share of the area actually reached
    (ties at a level come whole), and the share of all the changes inside
    it."""
    h = np.asarray(h_all, dtype=np.float64)
    c = np.asarray(h_chg, dtype=np.float64)
    total, changes = h.sum(), c.sum()
    rows = []
    if total <= 0:
        return rows
    area = np.cumsum(h[::-1])
    caught = np.cumsum(c[::-1])
    for t in tops:
        k = int(np.searchsorted(area, t * total - 1e-9 * total, side="left"))
        k = min(k, area.size - 1)
        level = h.size - 1 - k
        rows.append({"top_share": t, "level": level,
                     "u_threshold": float(level) / top,
                     "share_of_area": float(area[k] / total),
                     "changed_captured": int(round(caught[k])),
                     "share_of_changes_captured":
                         float(caught[k] / changes) if changes > 0 else ST_NAN})
    return rows
