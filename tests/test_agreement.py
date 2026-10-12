"""The confusion matrix and every number read off it, against hand work.

agreement.py is the one engine behind Compare two readings and Model vs
corrected, so its numbers are checked here against fixtures small enough to
work out on paper, and the working is written beside each one:

  F1   ten pixels, two readings, unlabelled as a row and column of its own
  F2   two classes swapped: all of the disagreement is exchange
  F3   one class everywhere: kappa undefined, not 0 and not an error
  F4   no pixel painted by both: every rate undefined, the counts still right
  T1-T5 the 4 x 4 map with three classes,
       the model against the corrected map (no kappa), and two people
       against each other (with kappa), on the whole map and the ground the
       strokes swept
  T16  random maps: quantity plus allocation is always the disagreement

  PS   the worked example of Pontius (2019, Table 1 and Fig. 1), which
       restates the equations of Pontius and Santacruz (2014): exchange is
       2 min(C_ij, C_ji) summed over the pairs, shift what is left of
       allocation, by class and overall

then the spread over frames and the frame bootstrap.

The module is read out of the shipped file with no QGIS and no GDAL, and an
AST check keeps it that way: numpy, math and json, and the statistics
beside it, and nothing else.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purekit

rl = purekit.load("stats", "agreement")
t = purekit.Checks()
nan = purekit.isnan

print("agreement.py imports only numpy, math, json and the stats beside it")
plain, sibling = purekit.imports_of("agreement")
t.ok("absolute imports are numpy, math and json", set(plain) <= {
    "numpy", "math", "json"}, plain)
t.ok("the only sibling is stats", set(sibling) <= {"stats"}, sibling)
plain, sibling = purekit.imports_of("stats")
t.ok("stats imports numpy and math only", set(plain) <= {"numpy", "math"},
     plain)
t.ok("and nothing of the program", not sibling, sibling)

# ------------------------------------------------------------------ F1
print()
print("F1: ten pixels, rows A, columns B, codes 0 1 2")
A = np.array([1, 1, 1, 1, 2, 2, 2, 0, 0, 1])
B = np.array([1, 1, 1, 2, 2, 2, 0, 0, 2, 1])
codes = [0, 1, 2]
M = rl.cm_confusion(A, B, codes)
t.ok("M = [[1,0,1],[0,4,1],[1,0,2]]",
     M.tolist() == [[1, 0, 1], [0, 4, 1], [1, 0, 2]], M.tolist())
m = rl.cm_metrics(M, codes, unlabelled=0, kappa=True)
c = m["counts"]
t.ok("both 7, only A 1, only B 1, neither 1",
     (c["both"], c["only_A"], c["only_B"], c["neither"]) == (7, 1, 1, 1), c)
o = m["overall"]
# the block both painted is [[4,1],[0,2]], n = 7
t.near("Po = 6/7", o["po"], 6 / 7)
# rows 5/7, 2/7; columns 4/7, 3/7: Pe = 20/49 + 6/49
t.near("Pe = 26/49", o["pe"], 26 / 49)
t.near("kappa = (6/7 - 26/49) / (1 - 26/49) = 16/23", o["kappa"], 16 / 23)
# q = |5/7 - 4/7| and |2/7 - 3/7|; a = 2 min(5/7 - 4/7, 4/7 - 4/7) = 0
t.near("Q = 1/7", o["quantity"], 1 / 7)
t.near("A = 0", o["allocation"], 0.0)
t.near("exchange 0", o["exchange"], 0.0)
t.near("shift 0", o["shift"], 0.0)
t.near("Q + A = 1 - Po", o["quantity"] + o["allocation"], 1 - o["po"])
pc = {e["code"]: e for e in m["per_class"]}
t.near("IoU 1 = 4 / (5 + 4 - 4) = 0.8", pc[1]["iou"], 0.8)
t.near("IoU 2 = 2 / (2 + 3 - 2) = 2/3", pc[2]["iou"], 2 / 3)
t.near("Dice 1 = 8/9", pc[1]["f1"], 8 / 9)
t.near("Dice 2 = 0.8", pc[2]["f1"], 0.8)
t.ok("agree from A = [0.8, 1.0]",
     [round(pc[k]["rate_A"], 12) for k in (1, 2)] == [0.8, 1.0])
t.ok("agree from B = [1.0, 2/3]",
     abs(pc[1]["rate_B"] - 1.0) < 1e-12 and abs(pc[2]["rate_B"] - 2 / 3) < 1e-12)
t.near("mean IoU over the two classes", o["mean_iou"], (0.8 + 2 / 3) / 2)
t.ok("unlabelled is not a class of per_class", 0 not in pc)
dis = rl.cm_disagreement_values(A, B)
t.ok("disagreement codes [1,1,1,2,1,1,3,5,4,1]",
     dis.tolist() == [1, 1, 1, 2, 1, 1, 3, 5, 4, 1], dis.tolist())
t.ok("and 0 outside", rl.cm_disagreement_values(
    A, B, inside=np.arange(10) < 9).tolist()[-1] == 0)
pair = rl.cm_pair_values(A, B, codes)
# value = 1 + i*K + j with K = 3: (1,1) = 5, (1,2) = 6, (2,2) = 9,
# (2,0) = 7, (0,0) = 1, (0,2) = 3
t.ok("pair values under the one encoding",
     pair.tolist() == [5, 5, 5, 6, 9, 9, 7, 1, 3, 5], pair.tolist())
t.ok("pair of codes (1,2) with codes [0,1,2] is 6",
     rl.cm_pair_values(np.array([1]), np.array([2]), codes).tolist() == [6])
t.ok("and every value reads back",
     all(rl.cm_pair_of(v, codes) == (int(a), int(b))
         for v, a, b in zip(pair.tolist(), A, B)))
t.ok("0 is outside", rl.cm_pair_of(0, codes) is None)
t.ok("a Byte holds 3 codes", rl.cm_pair_dtype(3) == "uint8")
t.ok("15 codes still fit a Byte, 16 do not",
     rl.cm_pair_dtype(15) == "uint8" and rl.cm_pair_dtype(16) == "uint16")
t.ok("255 codes fit 16 bits, 256 need 32",
     rl.cm_pair_dtype(255) == "uint16" and rl.cm_pair_dtype(256) == "uint32")
big = list(range(0, 255))
v = rl.cm_pair_values(np.array([254]), np.array([0]), big)
t.ok("codes 254 and 0 of 0..254: 1 + 254*255 + 0", int(v[0]) == 1 + 254 * 255)
t.ok("the largest value is K*K", int(rl.cm_pair_values(
    np.array([254]), np.array([254]), big)[0]) == 255 * 255)
t.near("coverage of A is 0.8", rl.cm_coverage(A), 0.8)
t.near("coverage of B is 0.8", rl.cm_coverage(B), 0.8)

try:
    rl.cm_confusion(np.array([1, 3]), np.array([1, 1]), codes)
    t.ok("a code outside codes is refused", False)
except ValueError as err:
    t.ok("a code outside codes is refused", "3" in str(err), err)
try:
    rl.cm_confusion(np.array([1.5]), np.array([1.0]), codes)
    t.ok("a value that is not a whole number is refused", False)
except ValueError:
    t.ok("a value that is not a whole number is refused", True)

# ------------------------------------------------------------------ F2
print()
print("F2: two classes swapped")
M2 = rl.cm_confusion([1, 1, 2, 2], [2, 1, 1, 2], codes)
o2 = rl.cm_metrics(M2, codes, 0, kappa=True)
t.near("Po 0.5", o2["overall"]["po"], 0.5)
t.near("Pe 0.5", o2["overall"]["pe"], 0.5)
t.near("kappa 0", o2["overall"]["kappa"], 0.0)
t.near("Q 0", o2["overall"]["quantity"], 0.0)
t.near("A 0.5", o2["overall"]["allocation"], 0.5)
t.near("exchange 2 min(1/4, 1/4) = 0.5", o2["overall"]["exchange"], 0.5)
t.near("shift 0", o2["overall"]["shift"], 0.0)
t.ok("IoU 1/3 for both", all(abs(e["iou"] - 1 / 3) < 1e-12
                             for e in o2["per_class"]))

# ------------------------------------------------------------------ PS
print()
print("PS: the worked example of Pontius (2019), Table 1")
# Pontius R.G. Jr. (2019) Component intensities to relate difference by
# category with difference overall. Int J Appl Earth Obs Geoinf 77,
# doi:10.1016/j.jag.2018.07.024. Its equations (1)-(4) are those of Pontius
# and Santacruz (2014), doi:10.1080/2150704X.2014.969814. Three categories,
# off-diagonal entries C12 1, C13 2, C21 4, C23 0, C31 1, C32 2: ten
# observations of difference. The text gives the exchange of each pair (1-2:
# two, 1-3: two, 2-3: zero) and Fig. 1 the intensities: quantity 20 % of the
# difference overall, quantity plus exchange 60 %, so exchange 40 % and
# shift 40 %; by category, exchange more intensive than overall in 1, less
# in 2, equal in 3, and shift less in 1, more in 2, equal in 3. The
# diagonal is not a difference and must not change any of it.
for diag in (0, 5, 37):
    MP = np.array([[diag, 1, 2], [4, diag, 0], [1, 2, diag]])
    n_ps = MP.sum()
    ops = rl.cm_metrics(MP, [1, 2, 3], unlabelled=None)
    ov = ops["overall"]
    per = ops["per_class"]
    d_j = [(e["q"] + e["a"]) * n_ps for e in per]
    t.near("diagonal %d: difference overall 10" % diag,
           ov["disagreement"] * n_ps, 10.0, 1e-9)
    t.near("diagonal %d: quantity 2" % diag, ov["quantity"] * n_ps, 2.0, 1e-9)
    t.near("diagonal %d: exchange 4" % diag, ov["exchange"] * n_ps, 4.0, 1e-9)
    t.near("diagonal %d: shift 4" % diag, ov["shift"] * n_ps, 4.0, 1e-9)
    t.ok("diagonal %d: difference by category 8, 7, 5" % diag,
         np.allclose(d_j, [8, 7, 5]), d_j)
    t.ok("diagonal %d: quantity by category 2, 1, 1" % diag,
         np.allclose([e["q"] * n_ps for e in per], [2, 1, 1]))
    t.ok("diagonal %d: exchange by category 4, 2, 2" % diag,
         np.allclose([e["e"] * n_ps for e in per], [4, 2, 2]),
         [e["e"] * n_ps for e in per])
    t.ok("diagonal %d: shift by category 2, 4, 2" % diag,
         np.allclose([e["s"] * n_ps for e in per], [2, 4, 2]),
         [e["s"] * n_ps for e in per])
D_ps = ov["disagreement"]
t.near("quantity is 20 % of the difference overall",
       ov["quantity"] / D_ps, 0.20, 1e-12)
t.near("quantity plus exchange is 60 %",
       (ov["quantity"] + ov["exchange"]) / D_ps, 0.60, 1e-12)
t.near("so shift is 40 %", ov["shift"] / D_ps, 0.40, 1e-12)
e_int = [e["e"] / (e["q"] + e["a"]) for e in per]
s_int = [e["s"] / (e["q"] + e["a"]) for e in per]
E_int = ov["exchange"] / D_ps
S_int = ov["shift"] / D_ps
t.ok("exchange: category 1 more intensive than overall, 2 less, 3 equal",
     e_int[0] > E_int and e_int[1] < E_int and abs(e_int[2] - E_int) < 1e-12,
     (e_int, E_int))
t.ok("shift: category 1 less intensive than overall, 2 more, 3 equal",
     s_int[0] < S_int and s_int[1] > S_int and abs(s_int[2] - S_int) < 1e-12,
     (s_int, S_int))

# ------------------------------------------------------------------ F3
print()
print("F3: one class everywhere")
M3 = rl.cm_confusion([1] * 6, [1] * 6, codes)
o3 = rl.cm_metrics(M3, codes, 0, kappa=True)
t.near("Pe 1", o3["overall"]["pe"], 1.0)
t.ok("kappa undefined (NaN), not an exception", nan(o3["overall"]["kappa"]))
t.near("Po 1", o3["overall"]["po"], 1.0)
t.near("IoU 1", o3["per_class"][0]["iou"], 1.0)
t.ok("the absent class has IoU NaN", nan(o3["per_class"][1]["iou"]))
t.near("and is left out of the mean", o3["overall"]["mean_iou"], 1.0)

# ------------------------------------------------------------------ F4
print()
print("F4: nobody painted where the other did")
M4 = rl.cm_confusion([1, 1, 0, 0, 0], [0, 0, 2, 2, 0], codes)
o4 = rl.cm_metrics(M4, codes, 0, kappa=True)
t.ok("Po NaN", nan(o4["overall"]["po"]))
t.ok("Q and A NaN", nan(o4["overall"]["quantity"])
     and nan(o4["overall"]["allocation"]))
t.ok("counts: both 0, only A 2, only B 2, neither 1",
     (o4["counts"]["both"], o4["counts"]["only_A"], o4["counts"]["only_B"],
      o4["counts"]["neither"]) == (0, 2, 2, 1), o4["counts"])
t.ok("and nothing raised on the way", True)
js = rl.cm_dumps(o4)
t.ok("NaN goes out as null", "null" in js and "NaN" not in js)

# ------------------------------------------------------------------ T1-T5
print()
print("model vs corrected, fixture F: 4 x 4, classes 1 olive, 2 crop, 3 mud")
S = np.array([[1, 1, 2, 2], [1, 1, 2, 2], [3, 3, 2, 2], [3, 3, 3, 0]])
C = np.array([[1, 1, 1, 2], [1, 1, 2, 2], [3, 2, 2, 2], [3, 3, 3, 0]])
C2 = np.array([[1, 1, 2, 2], [1, 1, 2, 2], [3, 2, 2, 2], [3, 3, 3, 0]])
valid = S != 0
pairs = rl.cm_accumulate({}, S[valid], C[valid])
MF, cf = rl.cm_from_pairs(pairs, [1, 2, 3])
t.ok("T1 cm = [[4,0,0],[1,5,0],[0,1,4]]",
     MF.tolist() == [[4, 0, 0], [1, 5, 0], [0, 1, 4]] and cf == [1, 2, 3],
     MF.tolist())
mf = rl.cm_metrics(MF, cf, unlabelled=None, kappa=False, pixel_m2=100.0)
of = mf["overall"]
t.ok("N = 15", of["n"] == 15)
t.near("OA 13/15", of["po"], 13 / 15)
pf = mf["per_class"]
t.ok("PA (rate from the corrected map) [0.8, 5/6, 1]",
     np.allclose([e["rate_B"] for e in pf], [0.8, 5 / 6, 1.0]))
t.ok("UA (rate from the model) [1, 5/6, 0.8]",
     np.allclose([e["rate_A"] for e in pf], [1.0, 5 / 6, 0.8]))
t.ok("IoU [0.8, 5/7, 0.8]",
     np.allclose([e["iou"] for e in pf], [0.8, 5 / 7, 0.8]))
t.ok("F1 [8/9, 5/6, 8/9]",
     np.allclose([e["f1"] for e in pf], [8 / 9, 5 / 6, 8 / 9]))
t.near("Q 1/15", of["quantity"], 1 / 15)
t.near("A 1/15", of["allocation"], 1 / 15)
t.near("D 2/15", of["disagreement"], 2 / 15)
t.ok("q_k [1/15, 0, 1/15]", np.allclose([e["q"] for e in pf],
                                        [1 / 15, 0, 1 / 15]))
t.ok("a_k [0, 2/15, 0]", np.allclose([e["a"] for e in pf], [0, 2 / 15, 0]))
t.ok("no kappa for the model", "kappa" not in of)
t.near("areas from the pixel size: olive 400 m2 in the model",
       pf[0]["m2_A"], 400.0)
t.ok("transitions: crop->olive and mud->crop, one pixel each",
     sorted((a, b) for (a, b), n in pairs.items() if a != b)
     == [(2, 1), (3, 2)])

R = np.zeros_like(S, dtype=bool)
R[0:2, :] = True
R[2, 1] = True
inside = valid & R
MS, _ = rl.cm_from_pairs(rl.cm_accumulate({}, S[inside], C[inside]),
                         [1, 2, 3])
t.ok("T3 swept cm = [[4,0,0],[1,3,0],[0,1,0]]",
     MS.tolist() == [[4, 0, 0], [1, 3, 0], [0, 1, 0]], MS.tolist())
ms = rl.cm_metrics(MS, [1, 2, 3], None)
t.near("OA 7/9", ms["overall"]["po"], 7 / 9)
ps = ms["per_class"]
t.ok("PA [0.8, 0.75, undefined]",
     abs(ps[0]["rate_B"] - 0.8) < 1e-12 and abs(ps[1]["rate_B"] - 0.75) < 1e-12
     and nan(ps[2]["rate_B"]))
t.ok("UA [1, 0.75, 0]", np.allclose([e["rate_A"] for e in ps],
                                    [1.0, 0.75, 0.0]))
t.ok("IoU [0.8, 0.6, 0]", np.allclose([e["iou"] for e in ps],
                                      [0.8, 0.6, 0.0]))
t.near("Q 1/9", ms["overall"]["quantity"], 1 / 9)
t.near("A 1/9", ms["overall"]["allocation"], 1 / 9)
t.near("share of the map 9/15", inside.sum() / valid.sum(), 0.6)
t.ok("undefined PA goes out as null in JSON",
     '"rate_B": null' in rl.cm_dumps(ps[2]))

MP, _ = rl.cm_from_pairs(rl.cm_accumulate({}, C2[valid], C[valid]),
                         [1, 2, 3])
t.ok("T4 people cm = [[4,0,0],[1,6,0],[0,0,4]]",
     MP.tolist() == [[4, 0, 0], [1, 6, 0], [0, 0, 4]], MP.tolist())
mp = rl.cm_metrics(MP, [1, 2, 3], None, kappa=True)
t.near("OA 14/15", mp["overall"]["po"], 14 / 15)
t.ok("IoU [0.8, 6/7, 1]", np.allclose([e["iou"] for e in mp["per_class"]],
                                      [0.8, 6 / 7, 1.0]))
t.near("pe 0.346667", mp["overall"]["pe"], 0.346667, 1e-6)
t.near("kappa 0.897959", mp["overall"]["kappa"], 0.897959, 1e-6)
t.near("Q 1/15", mp["overall"]["quantity"], 1 / 15)
t.near("A 0", mp["overall"]["allocation"], 0.0)
excess = [(1 - a["iou"]) - (1 - b["iou"])
          for a, b in zip(mf["per_class"], mp["per_class"])]
t.ok("side by side excess: olive 0, crop 1/7, mud 0.2",
     np.allclose(excess, [0.0, 0.142857, 0.2], atol=1e-6), excess)

MP5, _ = rl.cm_from_pairs(rl.cm_accumulate({}, C2[inside], C[inside]),
                          [1, 2, 3])
mp5 = rl.cm_metrics(MP5, [1, 2, 3], None, kappa=True)
t.near("T5 people on the swept ground: OA 8/9", mp5["overall"]["po"], 8 / 9)
ious = [e["iou"] for e in mp5["per_class"]]
t.ok("IoU [0.8, 0.8, undefined]", abs(ious[0] - 0.8) < 1e-12
     and abs(ious[1] - 0.8) < 1e-12 and nan(ious[2]), ious)
t.near("kappa 0.780488", mp5["overall"]["kappa"], 0.780488, 1e-6)

print()
print("codes of any width")
wide = rl.cm_accumulate({}, np.array([1000, 3000, -5], dtype=np.int32),
                        np.array([2000, 3000, 70000], dtype=np.int32))
t.ok("unique path: codes past 16 bits and negative ones",
     wide == {(1000, 2000): 1, (3000, 3000): 1, (-5, 70000): 1}, wide)
small = rl.cm_accumulate({}, S.astype(np.uint16) * 1000,
                         C.astype(np.uint16) * 1000)
t.ok("UInt16 codes 1000/2000/3000 give the same counts",
     sorted(small.values()) == sorted(rl.cm_accumulate(
         {}, S, C).values()))
f32 = rl.cm_accumulate({}, S.astype(np.float32), C.astype(np.float32))
t.ok("and whole floats too", f32 == rl.cm_accumulate({}, S, C))
again = rl.cm_accumulate(dict(pairs), S[valid], C[valid])
t.ok("accumulating adds", again[(1, 1)] == 2 * pairs[(1, 1)])

print()
print("T16: on random maps, Q + A is the disagreement")
rng = np.random.default_rng(16)
worst = 0.0
for _ in range(20):
    a = rng.integers(1, 7, size=(50, 50))
    b = np.where(rng.random((50, 50)) < 0.6, a, rng.integers(1, 7, (50, 50)))
    mr = rl.cm_metrics(rl.cm_confusion(a, b, range(1, 7)), list(range(1, 7)),
                       None)
    d = mr["overall"]["disagreement"]
    qa = mr["overall"]["quantity"] + mr["overall"]["allocation"]
    halves = sum(e["q"] + e["a"] for e in mr["per_class"]) / 2
    es = mr["overall"]["exchange"] + mr["overall"]["shift"]
    worst = max(worst, abs(d - qa), abs(halves - d),
                abs(es - mr["overall"]["allocation"]))
t.ok("|D - (Q + A)| < 1e-9, sum(q + a)/2 = D, E + S = A", worst < 1e-9, worst)

# ------------------------------------------------------------------ frames
print()
print("the spread over frames")
sp = rl.st_spread([0.5, 0.75, 1.0, 1.0, float("nan")])
t.ok("median 0.875, q1 0.6875, q3 1.0, n 4 (the NaN left out)",
     (sp["median"], sp["q1"], sp["q3"], sp["n"]) == (0.875, 0.6875, 1.0, 4),
     sp)

print()
print("the frame bootstrap")
six = np.stack([M] * 6)
s6 = rl.cm_summarize(six, ["t%d" % i for i in range(6)], codes, n_boot=200,
                     seed=1, unlabelled=0, kappa=True)
ci = s6["bootstrap"]["ci"]
pool = s6["pooled"]["overall"]
t.ok("six identical frames: every interval is the pooled value",
     all(abs(ci[k][0] - pool[n]) < 1e-12 and abs(ci[k][1] - pool[n]) < 1e-12
         for k, n in (("po", "po"), ("kappa", "kappa"),
                      ("mean_iou", "mean_iou"))), ci["po"])
t.ok("and per class IoU too", abs(ci["iou:1"][0] - 0.8) < 1e-12
     and abs(ci["iou:1"][1] - 0.8) < 1e-12)
pooled = rl.cm_metrics(six.sum(axis=0), codes, 0, kappa=True)["overall"]
t.ok("pooled = metrics of the summed matrix", pool == pooled)
four = rl.cm_summarize(np.stack([M] * 4), list("abcd"), codes, 200, 1)
t.ok("four frames: no interval", four["bootstrap"]["ci"] is None)
t.ok("and the reason says why", four["bootstrap"]["reason"].startswith(
    "fewer than 5 frames"), four["bootstrap"]["reason"])
none = rl.cm_summarize(six, list("abcdef"), codes, 0, 1)
t.ok("n_boot 0: no interval", none["bootstrap"]["ci"] is None)
mixed = np.stack([M, M2, M3, M, M2, M3, M])
b1 = rl.cm_summarize(mixed, list("abcdefg"), codes, 300, 7, kappa=True)
b2 = rl.cm_summarize(mixed, list("abcdefg"), codes, 300, 7, kappa=True)
b3 = rl.cm_summarize(mixed, list("abcdefg"), codes, 300, 8, kappa=True)
t.ok("the same seed gives the same intervals",
     b1["bootstrap"]["ci"] == b2["bootstrap"]["ci"])
t.ok("a different seed may differ (and here does)",
     b1["bootstrap"]["ci"] != b3["bootstrap"]["ci"])
t.ok("the record says resamples, seed and method",
     b1["bootstrap"]["resamples"] == 300 and b1["bootstrap"]["seed"] == 7
     and "percentile" in b1["bootstrap"]["method"])
t.ok("lo <= pooled <= hi for overall agreement",
     b1["bootstrap"]["ci"]["po"][0] <= b1["pooled"]["overall"]["po"]
     <= b1["bootstrap"]["ci"]["po"][1])
t.ok("kappa undefined on F3 frames is left out of the spread",
     b1["spread"]["kappa"]["n"] == 5, b1["spread"]["kappa"])
t.ok("the unlabelled block is labelled as such",
     "with_unlabelled" in b1 and "class" in b1["with_unlabelled"]["note"])
whole = rl.cm_metrics(M, codes, None, kappa=True)["overall"]
t.near("with unlabelled as a class, Po is 7/10", whole["po"], 0.7)

print()
print("table rows")
rows = rl.cm_wide_rows(M, codes, {1: "crater", 2: "mud flow"})
t.ok("the wide matrix has a header and one row per code",
     rows[0] == ["A \\ B", "0 unlabelled", "1 crater", "2 mud flow"]
     and rows[2] == ["1 crater", 0, 4, 1], rows)
long_rows = rl.cm_long_rows(M, codes, {1: "crater"}, "t001", 0, 0.0025)
t.ok("the long rows list the non-empty cells", len(long_rows) == 6
     and long_rows[0][:6] == ["t001", 0, "unlabelled", 0, "unlabelled", 1])
t.ok("and a code missing from the legend is named so",
     any("not in the legend" in r[4] for r in long_rows))
t.near("area of a cell", long_rows[0][6], 0.0025)

t.done()
