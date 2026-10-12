"""rasterlabel.agreement

How far two maps of classes are from each other, pixel by pixel: the
confusion matrix and everything read off it.

One engine for every comparison the program makes. Two readings of the same
frames (two people, or one person twice), and the map a model made against
the map a person corrected, all come down to the same square table: rows
are A, the first reading or the model; columns are B, the second reading or
the corrected map, which is the reference when there is one (the orientation
of Olofsson et al. 2014). What differs is only what the writers call the
numbers: seen from A and from B for two readings, user's and producer's
accuracy for a model.

Numpy, math and json only, and from the program only the statistics beside
it, so it runs and is tested with no QGIS and no GDAL. Nothing in it reads
or writes a file.

The formulas, with where they come from:

- overall agreement Po = sum of the diagonal over n, and the agreement
  expected by chance Pe = sum of p_i+ p_+i; Cohen's kappa = (Po - Pe) /
  (1 - Pe) (Cohen 1960). Kappa is undefined when Pe is 1, a frame with one
  class in both, and comes back NaN rather than 0. It is reported only
  between people, always beside Q and A (Pontius and Millones 2011; Foody
  2020): as a measure of a map's accuracy it is misleading.
- quantity and allocation disagreement (Pontius and Millones 2011):
  q_g = |p_g+ - p_+g|, Q = sum(q_g) / 2; a_g = 2 min(p_g+ - p_gg,
  p_+g - p_gg), A = sum(a_g) / 2; and Q + A = 1 - Po, which is checked on
  every call.
- exchange and shift (Pontius and Santacruz 2014): allocation split into
  pairs of classes swapping places, e_g = sum over i != g of
  2 min(p_gi, p_ig), E = sum(e_g) / 2, and what is left, S = A - E, by
  class s_g = d_g - q_g - e_g with d_g = p_g+ + p_+g - 2 p_gg. The tests
  hold them to the worked example of Pontius (2019, Table 1 and Fig. 1;
  doi:10.1016/j.jag.2018.07.024), which restates the equations of the 2014
  article: ten differences, quantity 2, exchange 4, shift 4, and by class
  exchange 4, 2, 2 and shift 2, 4, 2.
- per class: IoU = n_gg / (n_g+ + n_+g - n_gg), F1 = Dice = 2 n_gg /
  (n_g+ + n_+g), the rate seen from A = n_gg / n_g+ and from B = n_gg /
  n_+g. A ratio with nothing under it is NaN.

Intervals resample whole frames (Efron 1979): the pixels inside one frame
are not independent of each other, and an interval over pixels would be far
too narrow.
"""
import json
import math

import numpy as np

from .stats import st_percentile_ci, st_spread


CM_NAN = float("nan")

# The values of the disagreement map. The names and colours are in
# constants.DISAGREEMENT_CLASSES, which this module does not import.
CM_OUTSIDE = 0
CM_AGREE = 1
CM_DISAGREE = 2
CM_ONLY_A = 3
CM_ONLY_B = 4
CM_NEITHER = 5

# Past this many cells a bincount would spend more memory than the sort of
# np.unique costs in time.
CM_BINCOUNT_MAX = 1 << 22


def cm_codes(*groups):
    """One sorted list of whole codes out of any number of lists of them."""
    out = set()
    for g in groups:
        for c in g if g is not None else []:
            out.add(int(c))
    return sorted(out)


def _cm_whole(values, what):
    """values as int64, refusing anything that is not a whole number."""
    a = np.asarray(values).ravel()
    if a.dtype.kind == "f":
        if not np.all(np.isfinite(a)) or np.any(a != np.floor(a)):
            raise ValueError("%s holds a value that is not a class code" % what)
    elif a.dtype.kind not in "uib":
        raise ValueError("%s is not a band of class codes" % what)
    return a.astype(np.int64)


def _cm_index(values, codes, what):
    """Where each value sits in codes; ValueError on one that is not there."""
    k = codes.size
    idx = np.searchsorted(codes, values)
    bad = idx >= k
    bad |= codes[np.minimum(idx, k - 1)] != values
    if bad.any():
        raise ValueError("%s holds code %d, which is not in the list of codes"
                         % (what, int(values[bad][0])))
    return idx


def cm_confusion(a, b, codes):
    """The K x K matrix of pixel counts: rows the codes of a, columns of b.

    codes is the full list, sorted, unlabelled included where it counts as a
    row of its own. A code of a or b that is not in it is an error, not a
    pixel quietly dropped."""
    cs = np.asarray(cm_codes(codes), dtype=np.int64)
    if not cs.size:
        raise ValueError("no codes to count by")
    aa = _cm_whole(a, "A")
    bb = _cm_whole(b, "B")
    if aa.size != bb.size:
        raise ValueError("A and B do not have the same number of pixels")
    k = cs.size
    ia = _cm_index(aa, cs, "A")
    ib = _cm_index(bb, cs, "B")
    return np.bincount(ia * k + ib, minlength=k * k).reshape(k, k) \
        .astype(np.int64)


def cm_accumulate(pairs, a, b):
    """Add the (a, b) pairs of these pixels into the dict pairs, and return it.

    For maps whose codes are not known in advance: a thematic map in sixteen
    bits, codes past 255, negative codes. Small ranges are counted with one
    bincount over the offsets; anything wider with np.unique over one int64
    key per pixel, a in the high 32 bits and b in the low ones."""
    if pairs is None:
        pairs = {}
    aa = _cm_whole(a, "A")
    bb = _cm_whole(b, "B")
    if aa.size != bb.size:
        raise ValueError("A and B do not have the same number of pixels")
    if not aa.size:
        return pairs
    a0, a1 = int(aa.min()), int(aa.max())
    b0, b1 = int(bb.min()), int(bb.max())
    span_b = b1 - b0 + 1
    if (a1 - a0 + 1) * span_b <= CM_BINCOUNT_MAX:
        counts = np.bincount((aa - a0) * span_b + (bb - b0))
        for key in np.nonzero(counts)[0]:
            pair = (int(key // span_b) + a0, int(key % span_b) + b0)
            pairs[pair] = pairs.get(pair, 0) + int(counts[key])
        return pairs
    if min(a0, b0) < -(1 << 31) or max(a1, b1) >= (1 << 31):
        raise ValueError("a class code does not fit in 32 bits")
    keys = (aa << 32) | (bb & 0xFFFFFFFF)
    found, counts = np.unique(keys, return_counts=True)
    for key, n in zip(found.tolist(), counts.tolist()):
        low = key & 0xFFFFFFFF
        if low >= (1 << 31):
            low -= 1 << 32
        pair = (key >> 32, low)
        pairs[pair] = pairs.get(pair, 0) + int(n)
    return pairs


def cm_from_pairs(pairs, codes=None):
    """(M, codes) from a dict of pair counts, over the codes given and seen."""
    seen = set()
    for (ca, cb) in pairs:
        seen.add(int(ca))
        seen.add(int(cb))
    cs = cm_codes(codes, seen)
    where = {c: i for i, c in enumerate(cs)}
    m = np.zeros((len(cs), len(cs)), dtype=np.int64)
    for (ca, cb), n in pairs.items():
        m[where[int(ca)], where[int(cb)]] += int(n)
    return m, cs


def _cm_ratio(top, bottom):
    return float(top) / float(bottom) if bottom else CM_NAN


def cm_metrics(M, codes, unlabelled=0, kappa=False, pixel_m2=None):
    """Everything read off one confusion matrix, as plain numbers.

    unlabelled is the code that means "nobody painted it" (0 for two
    readings), or None when every code is a class (a thematic map). When it
    is given, its row and column are counted apart: only A painted, only B
    painted, neither did. Every rate is then taken over the pixels both
    painted, which is what agreement between two readings means. kappa adds
    Cohen's kappa; leave it out for a model. pixel_m2 adds the areas.

    Returned: counts, overall {n, po, pe, kappa?, quantity, allocation,
    exchange, shift, disagreement, mean_iou}, and per_class, one entry per
    class in code order with code, n_A, n_B, n_same, rate_A, rate_B, iou,
    f1, q, a, e, s. Undefined is NaN."""
    m = np.asarray(M, dtype=np.int64)
    cs = [int(c) for c in codes]
    if m.shape != (len(cs), len(cs)):
        raise ValueError("the matrix is %s but there are %d codes"
                         % (m.shape, len(cs)))
    u = cs.index(int(unlabelled)) \
        if unlabelled is not None and int(unlabelled) in cs else None
    keep = [i for i in range(len(cs)) if i != u]
    block = m[np.ix_(keep, keep)] if keep else np.zeros((0, 0), np.int64)
    n = int(block.sum())
    counts = {"total": int(m.sum()), "both": n}
    if u is not None:
        counts["only_A"] = int(m[keep, u].sum()) if keep else 0
        counts["only_B"] = int(m[u, keep].sum()) if keep else 0
        counts["neither"] = int(m[u, u])
    if pixel_m2:
        counts["m2"] = {k: v * float(pixel_m2) for k, v in counts.items()}
    k = len(keep)
    if n > 0:
        p = block / float(n)
        row = p.sum(axis=1)
        col = p.sum(axis=0)
        d = np.diag(p)
        po = float(d.sum())
        pe = float((row * col).sum())
        q = np.abs(row - col)
        a = 2.0 * np.minimum(row - d, col - d)
        pair_min = 2.0 * np.minimum(p, p.T)
        np.fill_diagonal(pair_min, 0.0)
        e = pair_min.sum(axis=1)
        quantity = float(q.sum() / 2.0)
        allocation = float(a.sum() / 2.0)
        exchange = float(e.sum() / 2.0)
        if abs(quantity + allocation - (1.0 - po)) > 1e-9:
            raise ArithmeticError("quantity plus allocation is not the "
                                  "disagreement: %r + %r != 1 - %r"
                                  % (quantity, allocation, po))
        overall = {"n": n, "po": po, "pe": pe, "quantity": quantity,
                   "allocation": allocation, "exchange": exchange,
                   "shift": allocation - exchange, "disagreement": 1.0 - po}
        if kappa:
            overall["kappa"] = (po - pe) / (1.0 - pe) \
                if abs(1.0 - pe) > 1e-12 else CM_NAN
    else:
        q = a = e = np.full(k, CM_NAN)
        overall = {"n": 0, "po": CM_NAN, "pe": CM_NAN, "quantity": CM_NAN,
                   "allocation": CM_NAN, "exchange": CM_NAN,
                   "shift": CM_NAN, "disagreement": CM_NAN}
        if kappa:
            overall["kappa"] = CM_NAN
    per_class = []
    ious = []
    for j, i in enumerate(keep):
        n_a = int(block[j, :].sum())
        n_b = int(block[:, j].sum())
        same = int(block[j, j])
        entry = {"code": cs[i], "n_A": n_a, "n_B": n_b, "n_same": same,
                 "rate_A": _cm_ratio(same, n_a),
                 "rate_B": _cm_ratio(same, n_b),
                 "iou": _cm_ratio(same, n_a + n_b - same),
                 "f1": _cm_ratio(2 * same, n_a + n_b),
                 "q": float(q[j]), "a": float(a[j]), "e": float(e[j]),
                 "s": float(a[j] - e[j])}
        if pixel_m2:
            entry["m2_A"] = n_a * float(pixel_m2)
            entry["m2_B"] = n_b * float(pixel_m2)
            entry["m2_same"] = same * float(pixel_m2)
        if n_a + n_b > 0:
            ious.append(entry["iou"])
        per_class.append(entry)
    # The mean over the classes either side painted: a class absent from
    # both says nothing about how well they agree on it.
    overall["mean_iou"] = float(sum(ious) / len(ious)) if ious else CM_NAN
    return {"codes": cs, "unlabelled": unlabelled, "counts": counts,
            "overall": overall, "per_class": per_class}


def cm_pair_dtype(K):
    """The narrowest unsigned type that holds every pair value of K codes.

    The values run 1 .. K*K, with 0 left for "outside", so a Byte holds
    them while K*K <= 255, that is up to 15 codes."""
    if K * K <= 255:
        return "uint8"
    if K * K <= 65535:
        return "uint16"
    return "uint32"


def cm_pair_values(a, b, codes, inside=None):
    """The pair map: 1 + i*K + j where A has codes[i] and B codes[j].

    0 outside the comparison. One encoding for every report: it holds any
    code of any width, and a value can be read back with cm_pair_of."""
    cs = np.asarray(cm_codes(codes), dtype=np.int64)
    k = cs.size
    aa = np.asarray(a)
    shape = aa.shape
    flat_a = aa.ravel()
    flat_b = np.asarray(b).ravel()
    mask = np.ones(flat_a.size, dtype=bool) if inside is None \
        else np.asarray(inside, dtype=bool).ravel()
    out = np.zeros(flat_a.size, dtype=cm_pair_dtype(k))
    if mask.any():
        ia = _cm_index(_cm_whole(flat_a[mask], "A"), cs, "A")
        ib = _cm_index(_cm_whole(flat_b[mask], "B"), cs, "B")
        out[mask] = 1 + ia * k + ib
    return out.reshape(shape)


def cm_pair_of(value, codes):
    """(code of A, code of B) for one value of the pair map, None for 0."""
    cs = cm_codes(codes)
    v = int(value)
    if v <= 0:
        return None
    i, j = divmod(v - 1, len(cs))
    if i >= len(cs):
        raise ValueError("%d is not a pair of %d codes" % (v, len(cs)))
    return (cs[i], cs[j])


def cm_disagreement_values(a, b, inside=None, unlabelled=0):
    """The disagreement map, one byte a pixel.

    0 outside, 1 both painted the same class, 2 both painted and differ,
    3 only A painted, 4 only B painted, 5 neither painted."""
    aa = np.asarray(a)
    bb = np.asarray(b)
    in_a = aa != unlabelled
    in_b = bb != unlabelled
    out = np.full(aa.shape, CM_NEITHER, dtype=np.uint8)
    out[in_a & in_b & (aa == bb)] = CM_AGREE
    out[in_a & in_b & (aa != bb)] = CM_DISAGREE
    out[in_a & ~in_b] = CM_ONLY_A
    out[~in_a & in_b] = CM_ONLY_B
    if inside is not None:
        out[~np.asarray(inside, dtype=bool)] = CM_OUTSIDE
    return out


def cm_coverage(values, inside=None, unlabelled=0):
    """The share of the pixels inside that carry a class."""
    v = np.asarray(values)
    mask = np.ones(v.shape, dtype=bool) if inside is None \
        else np.asarray(inside, dtype=bool)
    total = int(mask.sum())
    return _cm_ratio(int(((v != unlabelled) & mask).sum()), total)


def cm_stat_values(metrics):
    """The numbers of one cm_metrics result that get a spread and an interval.

    Flat, by name: the overall ones, and iou:<code> and f1:<code> per class.
    The same names are used for a frame, for the pooled matrix and for every
    bootstrap replicate, so they line up."""
    o = metrics["overall"]
    out = {}
    for key in ("po", "kappa", "quantity", "allocation", "exchange", "shift",
                "mean_iou"):
        if key in o:
            out[key] = o[key]
    for c in metrics["per_class"]:
        out["iou:%d" % c["code"]] = c["iou"]
        out["f1:%d" % c["code"]] = c["f1"]
    return out


def cm_bootstrap(Ms, stats, n_boot, seed, min_frames=5, level=0.95,
                 chunk=250):
    """Frame-level bootstrap intervals for the statistics of a pooled matrix.

    Ms is the stack of per-frame matrices, F x K x K. stats takes one pooled
    matrix and returns {name: value}. Each replicate draws F frames with
    replacement, which is a multinomial weight per frame (Efron 1979); the
    replicate's matrix is the weighted sum, computed with einsum a chunk of
    replicates at a time so memory stays bounded. The interval is the
    percentile one. Below min_frames frames there is no interval, and the
    reason says so."""
    stack = np.asarray(Ms, dtype=np.float64)
    f = int(stack.shape[0]) if stack.ndim == 3 else 0
    out = {"resamples": int(n_boot or 0), "seed": seed, "level": level,
           "method": "percentile; frames resampled with replacement",
           "min_frames": int(min_frames), "frames": f, "ci": None,
           "n_valid": {}, "reason": ""}
    if not n_boot or n_boot <= 0:
        out["reason"] = "no resampling asked for"
        return out
    if f < max(1, int(min_frames)):
        out["reason"] = "fewer than %d frames: no interval" % int(min_frames)
        return out
    rng = np.random.default_rng(seed)
    weights = rng.multinomial(f, [1.0 / f] * f, size=int(n_boot))
    reps = {}
    for start in range(0, int(n_boot), max(1, int(chunk))):
        pooled = np.einsum("bf,fij->bij", weights[start:start + chunk], stack)
        for one in pooled:
            for name, value in stats(np.rint(one).astype(np.int64)).items():
                reps.setdefault(name, []).append(value)
    out["ci"] = {name: list(st_percentile_ci(v, level))
                 for name, v in sorted(reps.items())}
    out["n_valid"] = {name: int(np.isfinite(np.asarray(v, dtype=np.float64))
                                .sum()) for name, v in sorted(reps.items())}
    return out


def cm_summarize(Ms, ids, codes, n_boot=2000, seed=1, unlabelled=0,
                 kappa=False, min_frames=5, pixel_m2=None, level=0.95):
    """Pooled values, the spread over frames and the bootstrap, in one go.

    Pooled: cm_metrics of the summed matrix, so pixels weigh equally. The
    spread: median and quartiles of each value frame by frame, so frames
    weigh equally; a frame where a value is undefined is left out of that
    value's n. The bootstrap: frame-level, as cm_bootstrap. With unlabelled
    given, a second, labelled block "with_unlabelled" has Po and kappa with
    unlabelled taken as a class of its own."""
    stack = np.asarray(Ms, dtype=np.int64)
    if stack.ndim != 3:
        stack = stack.reshape((0, len(codes), len(codes)))
    total = stack.sum(axis=0) if stack.shape[0] else \
        np.zeros((len(codes), len(codes)), dtype=np.int64)
    pooled = cm_metrics(total, codes, unlabelled, kappa, pixel_m2)
    frames = []
    values = {}
    for fid, one in zip(ids, stack):
        metrics = cm_metrics(one, codes, unlabelled, kappa, pixel_m2)
        frames.append({"id": fid, "metrics": metrics})
        for name, v in cm_stat_values(metrics).items():
            values.setdefault(name, []).append(v)
    out = {"pooled": pooled, "frames": frames,
           "spread": {name: st_spread(v) for name, v in sorted(values.items())},
           "bootstrap": cm_bootstrap(
               stack, lambda m: cm_stat_values(
                   cm_metrics(m, codes, unlabelled, kappa)),
               n_boot, seed, min_frames, level)}
    if unlabelled is not None:
        whole = cm_metrics(total, codes, None, True)["overall"]
        out["with_unlabelled"] = {"po": whole["po"], "kappa": whole["kappa"],
                                  "note": "unlabelled counted as a class"}
    return out


def cm_name(code, names, unlabelled=0):
    """The word for a code: its class, "unlabelled", or "code N (not in the
    legend)" for a code the classes do not hold."""
    if code in names:
        return names[code]
    if unlabelled is not None and code == unlabelled:
        return "unlabelled"
    return "code %d (not in the legend)" % code


def cm_wide_rows(M, codes, names, unlabelled=0, corner="A \\ B"):
    """The matrix as rows of a table: a header, then one row per code of A."""
    cs = [int(c) for c in codes]
    head = [corner] + ["%d %s" % (c, cm_name(c, names, unlabelled))
                       for c in cs]
    rows = [head]
    m = np.asarray(M)
    for i, c in enumerate(cs):
        rows.append(["%d %s" % (c, cm_name(c, names, unlabelled))]
                    + [int(v) for v in m[i]])
    return rows


def cm_long_rows(M, codes, names, tile_id="ALL", unlabelled=0,
                 pixel_m2=None):
    """The non-empty cells as long rows: tile_id, code_A, name_A, code_B,
    name_B, pixels, area_m2 (empty when the pixel area is not known)."""
    cs = [int(c) for c in codes]
    m = np.asarray(M)
    rows = []
    for i, ca in enumerate(cs):
        for j, cb in enumerate(cs):
            n = int(m[i, j])
            if not n:
                continue
            rows.append([tile_id, ca, cm_name(ca, names, unlabelled), cb,
                         cm_name(cb, names, unlabelled), n,
                         n * float(pixel_m2) if pixel_m2 else None])
    return rows


def cm_jsonable(obj):
    """obj with NaN turned into None and numpy numbers into Python ones, so
    json.dumps writes null where a value is undefined."""
    if isinstance(obj, dict):
        return {str(k): cm_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [cm_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return cm_jsonable(obj.tolist())
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    return obj


def cm_dumps(obj):
    """obj as JSON text, NaN written as null, keys sorted."""
    return json.dumps(cm_jsonable(obj), sort_keys=True, indent=1,
                      ensure_ascii=False, allow_nan=False)
