# How RasterLabel 1.1 computes its numbers

This page is for the methods section of a paper. Every quantity a report
prints is listed with its formula, its unit, the population it is taken
over, how undefined cases are handled and where it is not reported. The
formulas are checked against independent implementations (and, where scipy is
installed, against scipy) in `tests/test_reference_values.py`. Pure
arithmetic lives in `rasterlabel/agreement.py`, `stats.py`, `effort.py`,
`uncertainty.py`, `card.py` and `design.py`.

## 0. Conventions

**Population and pixels.** All pixel counts are pixels of the campaign grid
(Compare, Time, Card) or of the corrected map's grid (Model vs corrected,
Uncertainty), at full resolution. A polygon, frame or reading is turned into
pixels by the centre rule: a pixel belongs to the polygon that contains its
centre (GDAL rasterization with ALL_TOUCHED off). Within one reading the
polygon drawn last wins an overlap. Areas are pixel counts times the pixel
area in m², except for a correction on a map in degrees or in Web Mercator,
where a pixel is not the same ground in every row: there the ground of a set
of pixels, in Correct, in the changed area of the correction's dataset card, in
the classes of a campaign's dataset card (section 5) and in Model vs corrected
(section 3), is the sum of the ground each covers, measured on the ellipsoid
row by row and scaled so that the middle row is the pixel the manifest holds.
In a metric system of its own the two are the same number. A campaign without a
coordinate system has pixel counts only.

**Lines.** A line of width w pixels is the union, over the stretches of the
trace, of rectangles of width w (at a right angle to the stretch), with discs
of radius w/2 on the vertices inside the trace; the first and the last stretch
reach w/2 beyond the end of the trace. A trace exactly along a row or a column
is the cells it crosses grown to the width, as before. A pixel (r, c) belongs
to the line when its centre (c + 1/2, r + 1/2) lies inside, with the sides at
the top and the left included and those at the bottom and the right excluded
when a centre falls exactly on one. The area of the strip is therefore
w(L + w) pixels for a stretch of L pixels, independent of its direction, up to
the discretisation of the grid (a few percent over a line, half a pixel across
at worst for one stretch at 45 degrees). For w = 1, pixels that touch another
only at a corner are completed with the pixel nearest to the trace, so that
the strip is one polygon; this makes a 1 pixel line up to sqrt(2) pixels
across at 45 degrees. The strip is stored as polygons of the class, and the
export burns those polygons; lines drawn before this was corrected keep the
strip they were drawn with.

**Unlabelled and ignore.** In a campaign, 0 means *unlabelled* (nobody painted
the pixel); classes are 1 to 254, and 255 is reserved as the ignore value of
exports. Compare keeps unlabelled as a row and a column of its own in the
confusion matrix, and every agreement figure is then computed over the pixels
**both** readings painted (the block of the matrix without that row and
column). The pixels only A painted, only B painted and neither painted are
counted and reported apart (`only_A`, `only_B`, `neither`); `with_unlabelled`
repeats Po and kappa with unlabelled treated as a class, so that the
alternative reading is on the page. In Model vs corrected there is no
unlabelled code: a pixel is dropped when either map holds its nodata value
(or a non-finite or non-integer value in a float band); a pixel dropped on one
side only is counted as `nodata_mismatch`. In the dataset card, 0 and the
ignore value are left out of the class counts.

**Confusion matrix.** Rows are A (the first reading, or the model), columns are
B (the second reading, or the corrected map, which is the reference; the
orientation of Olofsson et al. 2014). `n_ij` is the number of pixels with
class i in A and class j in B, `n` the total, `p_ij = n_ij / n`, `p_i+` and
`p_+j` the row and column sums, over the K classes considered.

**Undefined values** are NaN in memory, empty in CSV and `null` in JSON,
never 0. A frame where a value is undefined is left out of that value's
spread and bootstrap, and the count of those that were defined is written.

**Intervals.** Every interval is a percentile interval of seeded bootstrap
replicates (section 7). Where "95 %" is written, the 2.5 and 97.5 percentiles
are meant, by linear interpolation between order statistics (type 7 of
Hyndman and Fan 1996, numpy's and R's default). Medians and quartiles over
frames use the same rule.

## 1. Compare two readings

Population: the pixels, on the campaign grid, whose centre lies in a frame
that both readings annotated, and, by default, both closed. A frame is
closed for a reading when the union of that reading's polygons clipped to the
frame covers **more than 0.995** of the frame's area (planar areas in the
package's system; strict inequality). Untiled campaigns are compared as one
region, with no spread and no interval.

| quantity | formula | unit |
|---|---|---|
| overall agreement `Po` | `sum_g p_gg` | proportion |
| expected agreement `Pe` | `sum_g p_g+ p_+g` | proportion |
| Cohen's kappa | `(Po - Pe) / (1 - Pe)` (Cohen 1960); NaN when `Pe = 1` | -1 to 1 |
| quantity disagreement `Q` | `1/2 sum_g abs(p_g+ - p_+g)` (Pontius and Millones 2011) | proportion |
| allocation disagreement `A` | `sum_g min(p_g+ - p_gg, p_+g - p_gg)` | proportion |
| exchange `E` | `sum over pairs i<j of 2 min(p_ij, p_ji)` (Pontius and Santacruz 2014) | proportion |
| shift `S` | `A - E` | proportion |
| IoU of class g | `n_gg / (n_g+ + n_+g - n_gg)` (Jaccard 1912) | proportion |
| F1 = Dice of class g | `2 n_gg / (n_g+ + n_+g)` (Dice 1945) | proportion |
| agreement seen from A | `n_gg / n_g+` | proportion |
| agreement seen from B | `n_gg / n_+g` | proportion |
| mean IoU | mean of IoU over the classes at least one reading painted | proportion |

`Q + A = 1 - Po` is checked on every call. Kappa is reported only between
people, as an agreement statistic, always beside `Q` and `A` (Pontius and
Millones 2011; Foody 2020). A ratio with a zero denominator is NaN.

*Per class* columns of `per_class.csv` (`quantity`, `allocation`, `exchange`,
`shift`) are the by-category components of Pontius (2019): `q_g = abs(p_g+ -
p_+g)`, `a_g = 2 min(p_g+ - p_gg, p_+g - p_gg)`, `e_g = sum over i != g of 2
min(p_gi, p_ig)`, `s_g = a_g - e_g`. Each pixel of difference concerns two
classes, so they add up to **twice** the overall values. (The Model vs
corrected report writes the halved contribution instead, section 3; the
report says which in its notes.)

*Three summaries of every number.* **Pooled**: computed on the matrix summed
over frames, so every pixel weighs the same. **Per frame**: computed on each
frame's own matrix, then the median and the first and third quartile over
frames, so every frame weighs the same; `n` is the number of frames where the
value was defined. **Interval**: section 7, resampling frames.

*Other numbers.* `only_A`, `only_B`, `neither` are pixel counts (the window
shows each over all pixels of the frames compared). `coverage_A` and
`coverage_B` are the share of a frame's pixels a reading painted. `delay_h` of
a frame is the time from A's last polygon created in the frame to B's first,
in hours, from the `created` stamps (local time, to the second); the
summary gives its median, minimum and maximum over the frames used, and it is
negative if B was drawn before A.

## 2. Time

**Active time.** From `journal.csv`, one session (one run of QGIS) at a time;
sessions are never joined. Each row ends at `mono_ms` on the monotonic clock
and began `dur_ms` earlier. For an idle limit T (60 s unless chosen; 30, 60
and 120 s are always computed):

`active = sum over strokes of (duration - sum of the pauses inside it that are longer than T) + sum of the gaps g between one row's end and the next row's start with g <= T`

A gap of exactly T is active; a gap after a row saying QGIS lost focus is
idle whatever its length. A gap is credited to the next mark (its frame,
reading and class); time that is left when the work stops or the frame
changes is overhead of the frame in hand, reported as class 0 "(no class)". A
stroke of Correct goes to the frame its centre falls in (lowest `tile_id` on
a border), or to "(outside frames)", counted. If a monotonic clock goes back,
the session is split there. If one person was active in two sessions at the
same moment, the overlap is counted once and reported. Pauses are recorded
only when at least 10 s, to a tenth of a second.

**Per hectare.** minutes per hectare = `active_s / 60 / (area_m2 / 10 000)`.
For a frame the area is the frame's ground area; for a class, the union of
the reading's polygons of that class clipped to the frame (vector area scaled
to ground metres), not a pixel count. A set of frames is summed (seconds and
hectares) before dividing. Frames with no journal time (drawn before the
journal began) are left out of both, never read as 0 s.

**Paired scratch against correction.** Unit: the frame. For every frame with
time `s > 0` drawing from scratch (the mean over the readings that put time
on the frame) and `c > 0` correcting (the sum of the strokes): `r = ln(c /
s)`. The reported ratio is the **geometric mean** `exp(mean r)` (saving =
`100 (1 - ratio)` %), with the median of the plain ratios beside it. Frames
with no time on one side are skipped and counted. The interval resamples the
frames (section 7); the p-value is that of the Wilcoxon signed-rank test on
the `r` (section 8). The ratios at 30, 60 and 120 s are written beside.

## 3. Model vs corrected

Population: the pixels of the corrected map's grid, in one of three scopes.
*Whole map*: every pixel both maps hold (ground nobody looked at counts as
right: an upper bound). *Swept*: pixels a stroke went over, plus pixels marked
as changed (strokes go where the model was wrong: a purposive sample, a lower
bound). *Polygons*: pixels whose centre is in a polygon of a chosen layer;
one matrix per polygon as well. Only polygons from a probability design and
swept whole support an estimate for the map; the report says so.

Rows are the model, columns the corrected map (the reference).

| quantity | formula |
|---|---|
| overall accuracy | `sum_g p_gg` |
| producer's accuracy of g | `n_gg / n_+g` (corrected map's column); omission = 1 - PA |
| user's accuracy of g | `n_gg / n_g+` (model's row); commission = 1 - UA |
| IoU, F1 | as in section 1 |
| `quantity_dis`, `allocation_dis` of g | `abs(p_g+ - p_+g) / 2` and `min(p_g+ - p_gg, p_+g - p_gg)`: the class's contribution, adding up to `Q` and `A` of the whole |
| net change of g (m²) | `(n_+g - n_g+)` times pixel area, or the ground of the pixels of the corrected map less that of the model (section 0): corrected minus model |
| FROM -> TO | `n_ij`, i != j, pixels and m², read from the pixels; `share_of_a = n_ij / n_i+` |

On a map in degrees or in Web Mercator every area in m² (the scope, the
classes, the confusion matrix, the net change, each FROM -> TO and each
polygon) is the ground of its pixels, row by row (section 0), and the report
says so; in a metric system it is the pixels times the pixel.

**Kappa is never reported for the model.** It is reported for the people
side only (another correction of the same pixels, compared as in section 1,
with `Pe`, `Q` and `A`). A campaign's agreement report as the people side is
on other pixels, matched to classes by name then code, and is shown side by
side, not as a paired comparison. `excess_error = IoU_people - IoU_model`.
Logged figures (strokes, m² changed and swept) are gross and never mixed with
the net figures read from the pixels. A stroke that was undone keeps its row in
`operations.csv`, so it is in the logged figures; the manifest says how many
were undone and how much ground that was (`undone`), and the report gives that
part beside them.

*Polygon interval.* With five or more polygons, the polygons are resampled
(section 7) and the statistics recomputed on the pooled matrix of the draw. A
pixel under two polygons counts once in the pooled numbers and once in each
polygon's own matrix, which the report notes.

## 4. Uncertainty

**From the model's band to u.** `u` in [0, 1], higher is less sure, stored as
a byte `floor(254 u + 1/2)` (0 to 254; 255 no value). With `v = (raw * gain +
offset) / scale` (the band's own GDAL scale and offset, then the scale chosen)
clipped to [0, 1]: probability `u = 1 - v` (a raw 0 or nodata under a class
has no value); entropy `u = v`, margin `u = 1 - v`, ready-made uncertainty
`u = v`; votes `u = 1 - votes / readings_labelled` (no value where no reading
labelled the pixel). Quantisation error is at most 1/508. An entropy in nats
is divided by ln K by the user. `readings_labelled` counts the readings that
painted the pixel, so in a frame that only one reading covered, the class that
reading gave has 1 vote of 1 and `u = 0`: u says how far the readers of the
frame agreed, not how many readers there were (`readings_voting`, the third
band of the votes file, says how many).

**Places and ranking.** The map is cut into square places of 256 pixels (more
on very large maps, so that there are at most 200 000), from the top left.
A place is eligible when at least half its pixels have a value. Rank: highest
mean u, then highest max u, then row, then column.

**Random sample of places.** One place in five (settable) is taken instead
from `numpy.random.default_rng(seed).permutation(N)` over all N eligible
places in row-major order. The places so drawn are always the first m entries
of the permutation, a simple random sample of places without replacement of
size m, with inclusion probability **m / N** (m counts places drawn, whether
done or skipped). A draw that falls on a place already reviewed as purposive
joins the sample without a visit and is flagged as not blind. m is not fixed
in advance: it depends on when the review stopped and on how many draws
landed on places already visited, so m / N is conditional on that, and the
sample is simple random only approximately in the strict design-based sense.
Places chosen by uncertainty are purposive and are excluded, by name, from
every design-based figure.

**Calibration.** For a bin, `share changed = changed pixels / pixels`, where
changed means marked by a stroke of a person (a pixel changed and changed
back stays marked; `share_net` counts only pixels whose class differs from
the map the correction started from). Two binnings: **deciles of u**, whose
cuts are, for k = 1..9, the lowest level at which the cumulative pixel count
of the whole map reaches `k N / 10` (equal cuts are kept once; a cut at the
highest level is dropped, so ties give fewer bins), and a level equal to a cut
belongs to the lower bin; **tenths of the scale**, bin `min(9, floor(10 u))`,
the last bin closed. The same cuts are used in every scope. `mean_u` is the
mean level over 254 in the bin; for a probability it is the model's expected
error.

*Standard error.* For the random places, places are the clusters of a ratio
estimator (Cochran 1977, section 6.3): with m done places, `x_i` their pixels
in the bin and `y_i` those changed, `R = sum y / sum x`, `Var(R) = (1 - m / N)
sum (y_i - R x_i)^2 / ((m - 1) m xbar^2)`, `xbar = sum x / m`; places holding
none of the bin count with `x_i = y_i = 0`. The interval is `R ± 1.96 SE` cut
to [0, 1]: a normal interval, which is optimistic with few places. For the
purposive places the same arithmetic without the finite population
correction is written as a spread between places, not a design-based
standard error. For the whole map no standard error is given, and the figure
is a lower bound of the error (unreviewed pixels count as right). Fewer than
two places: no standard error.

**AUC.** Of u as a detector of the changed pixels: the probability that a
changed pixel has a higher u than an unchanged one, ties counted one half;
equal to the Mann-Whitney U statistic over `n_changed n_unchanged` (Mann and
Whitney 1947; Hanley and McNeil 1982), computed exactly from the two
histograms over the 255 levels. NaN if either side is empty. Given for the
random places, the purposive places and the whole map, pooled over pixels
(no interval).

**ECE** (only when u = 1 - p): `sum_b (n_b / N) abs(share changed_b - mean_u_b)`
over the ten fixed bins above, empty bins left out (Naeini et al. 2015; Guo
et al. 2017). Bins are equal-width in u, closed at the top only for the last;
the usual binning on confidence p = 1 - u differs at bin edges only.

**Capture curve.** Levels are taken from the highest u down, whole levels at a
time. For a share t of the area (1, 2, 5, 10, 20, 30, 50, 100 %), the first
level at which the area reached is at least t of the map gives the
threshold, the share of the area actually reached (ties come whole), and the
share of all changed pixels inside it.

## 5. Dataset card

`counts[code]` is the number of pixels with that class code in the product
over the campaign grid (code 0, unlabelled, and the ignore value excluded);
`share` is the count over the labelled pixels of the product, rounded to six
decimals. Products: all readings together (the polygon stored last wins),
each reading alone, and consensuses. **Consensus** of a set of readings. For
each frame, V is the set of readings of the set that covered it, a reading
having covered a frame when it has a polygon with the frame's `tile_id` that
has some area inside the frame (and, when points are in the mask, a point with
that `tile_id`); it need not have closed it. A pixel inside the frame takes the
class that at least `|V| // 2 + 1` of the readings in V gave it (a strict
majority of V, so of two readings both must agree, never a tie) and 0
otherwise; a reading outside V gives no vote and no label there. Outside every
frame V is the set of readings that painted anywhere in the campaign (a
free-hand campaign is all of it, and a stray mark of one reading out of four
needs three to stand). When every reading covered every frame, V is the whole
set everywhere and the rule is `n // 2 + 1` of n. `votes` is how many readings
gave that class, `labelled` how many of V painted the pixel at all, and
`readings_voting` (the third band of the votes file, written only when some
frame was read by fewer readings than the set holds) `|V|` at the pixel.
`no_majority_px` counts pixels painted by at least one reading without a
majority; `all_painted_disagree_px` the ones painted by every reading in V,
with no class in the majority. `frames_by_readings` (card, only when the design is
partial) is how many frames each size of V has. The consensus polygons of Export
carry the same numbers: `readings` is `|V|` of their frame, `votes` how many of
them gave the class. The m² of each class is the sum, over its pixels, of the
ground of the pixel in its row (section 0) on a map in degrees or in Web
Mercator, and the pixel count times the pixel area in a metric system. Frames:
closed above 0.995 as in section 1. Reports (agreement, time, model vs
corrected, uncertainty) are copied into the card, never recomputed.

## 6. Sampling design import

`incl_prob` must satisfy `0 < p <= 1`, `weight > 0`; anything else is left
empty and flagged. Values are kept as given: a weight is not computed from
the probability. Check reports, as a fact, the frames where `abs(weight *
incl_prob - 1) > 1e-6` (so a weight rounded to four digits is reported);
nothing is changed. A comma as the only separator is read as the decimal
mark; text with both a comma and a dot is refused.

## 7. The frame bootstrap

Resampling unit: the **frame** (Compare), the **polygon** (Model vs
corrected) or the **paired frame** (Time). Pixels are never resampled, since
neighbouring pixels are not independent. Replicates: 2000, seed 1,
`numpy.random.default_rng(seed)`, level 0.95, the percentile method
(Efron 1979; Efron and Tibshirani 1993, ch. 13). Matrices: a draw of F units
with replacement is a multinomial weight per unit, `rng.multinomial(F, [1/F]
* F)` for each replicate; the replicate's matrix is the weighted sum of the
unit matrices and every statistic is recomputed on it. Time: `rng.integers(0,
F, size=(B, F))` indexes the log ratios and the geometric mean is recomputed.
Replicates where a statistic is undefined are left out and their number
(`n_valid`) written. **Not reported:** with fewer than **five** units no
interval is given and the reason is written (the same rule for frames,
polygons and paired frames); a campaign without frames has none. The interval
describes variation over the units at hand; frames are seldom a random
sample, so it is not an interval for a population unless they were drawn by a
probability design. The order of the units (sorted by id as text) fixes what
a given seed gives.

## 8. Wilcoxon signed-rank test

Two-sided test that the median of the values is 0 (Wilcoxon 1945). Zeros are
dropped; tied absolute values share their mid-rank; `W+` is the sum of the
ranks of the positive values. With up to **25** non-zero values the p-value
is exact: the full null distribution of `W+`, each rank positive or negative
with probability 1/2, built by counting (exact with ties too, i.e. the
permutation distribution on mid-ranks), `p = min(1, 2 min(P(W+ <= w), P(W+
>= w)))`. Above 25, the normal approximation with a continuity correction of
1/2 and the tie correction of the variance: `z = (abs(W+ - n(n+1)/4) - 1/2) /
sqrt(n(n+1)(2n+1)/24 - sum(t^3 - t)/48)`, `p = erfc(z / sqrt 2)`. Relation to
`scipy.stats.wilcoxon` (scipy 1.13, checked in the suite): without ties or zeros and up to
25 values it equals `method="exact"`, which is scipy's default there; above 25
it equals `method="approx", correction=True`, but **not** scipy's default,
which has no continuity correction and, from 26 values, uses the exact test
up to 50; with ties or zeros scipy's default falls back to the normal
approximation, while this code stays exact up to 25 (the exact permutation
p on mid-ranks). The test is given with the paired time ratio only.

## References

- Cohen J (1960) A coefficient of agreement for nominal scales. *Educational and Psychological Measurement* 20(1):37-46. doi:10.1177/001316446002000104
- Dice LR (1945) Measures of the amount of ecologic association between species. *Ecology* 26(3):297-302. doi:10.2307/1932409
- Efron B (1979) Bootstrap methods: another look at the jackknife. *The Annals of Statistics* 7(1):1-26. doi:10.1214/aos/1176344552
- Efron B, Tibshirani RJ (1993) *An Introduction to the Bootstrap*. Springer US, Boston, MA. doi:10.1007/978-1-4899-4541-9
- Foody GM (2020) Explaining the unsuitability of the kappa coefficient in the assessment and comparison of the accuracy of thematic maps obtained by image classification. *Remote Sensing of Environment* 239:111630. doi:10.1016/j.rse.2019.111630
- Guo C, Pleiss G, Sun Y, Weinberger KQ (2017) On calibration of modern neural networks. *Proceedings of the 34th International Conference on Machine Learning*, PMLR 70:1321-1330.
- Hanley JA, McNeil BJ (1982) The meaning and use of the area under a receiver operating characteristic (ROC) curve. *Radiology* 143(1):29-36. doi:10.1148/radiology.143.1.7063747
- Hyndman RJ, Fan Y (1996) Sample quantiles in statistical packages. *The American Statistician* 50(4):361-365. doi:10.1080/00031305.1996.10473566
- Jaccard P (1912) The distribution of the flora in the alpine zone. *New Phytologist* 11(2):37-50. doi:10.1111/j.1469-8137.1912.tb05611.x
- Mann HB, Whitney DR (1947) On a test of whether one of two random variables is stochastically larger than the other. *The Annals of Mathematical Statistics* 18(1):50-60. doi:10.1214/aoms/1177730491
- Naeini MP, Cooper GF, Hauskrecht M (2015) Obtaining well calibrated probabilities using Bayesian binning. *Proceedings of the 29th AAAI Conference on Artificial Intelligence*, 2901-2907.
- Olofsson P, Foody GM, Herold M, Stehman SV, Woodcock CE, Wulder MA (2014) Good practices for estimating area and assessing accuracy of land change. *Remote Sensing of Environment* 148:42-57. doi:10.1016/j.rse.2014.02.015
- Pontius RG Jr, Millones M (2011) Death to Kappa: birth of quantity disagreement and allocation disagreement for accuracy assessment. *International Journal of Remote Sensing* 32(15):4407-4429. doi:10.1080/01431161.2011.552923
- Pontius RG Jr, Santacruz A (2014) Quantity, exchange, and shift components of difference in a square contingency table. *International Journal of Remote Sensing* 35(21):7543-7554. doi:10.1080/2150704X.2014.969814
- Pontius RG Jr (2019) Component intensities to relate difference by category with difference overall. *International Journal of Applied Earth Observation and Geoinformation* 77:94-99. doi:10.1016/j.jag.2018.07.024
- Cochran WG (1977) *Sampling Techniques*, 3rd edn. Wiley, New York.
- Wilcoxon F (1945) Individual comparisons by ranking methods. *Biometrics Bulletin* 1(6):80-83. doi:10.2307/3001968
