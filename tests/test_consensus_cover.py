"""A consensus counts its majority among the readings that covered the frame.

Four people read, and each frame was read by two of them (a paired design).
The consensus of the four used to need three votes everywhere, so a frame
that two people read could never reach it: they agreed, and the mask held 0.
Now a frame is voted by the readings that covered it, and a pixel needs
n // 2 + 1 of those. The campaign here is drawn so that every case has a
known answer, worked out below from the marks and not from the program:

  f1  A and B both give class 1 over all of it       two readings, agree
  f2  C gives class 1, D class 2                      two readings, disagree
  f3  A gives class 2 over all of it, C over the left half: two readings,
      agree on the left half; on the right half only A painted, and C, who
      began the frame, votes against
  f4  B alone, class 1                                one reading: it stands
  f5  all four: A and B class 1, C and D class 2      2 against 2 is a tie
      for a majority of 3
  outside every frame, A drew a stray mark of class 1; the readings that
      painted anywhere (all four) vote there, so one mark of four falls

and a campaign everyone read in full, whose consensus is what it always was:
the same pixels, a votes file of two bands, the same sentence in the file.
The same rule is held by the Whole raster and its votes file, by Export's
consensus polygons and by the dataset card.

Real GDAL, real GeoPackages; QGIS faked, see correctkit.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import shutil
import sys
import tempfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import correctkit as K                                             # noqa: E402
import impact as F                                                 # noqa: E402
import numpy as np                                                 # noqa: E402
from osgeo import gdal, ogr                                        # noqa: E402

gdal.UseExceptions()
ogr.UseExceptions()
g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_consensus_cover_")

GRID = {"epsg": 32633, "origin": (500000.0, 4140010.0), "pixel": 1.0,
        "size": (60, 10)}
W, H = GRID["size"]
A, B, C, D = ("A", 1), ("B", 1), ("C", 1), ("D", 1)
READINGS = [A, B, C, D]
CLASSES = [{"code": 1, "name": "crater", "colour": "#2a78d6"},
           {"code": 2, "name": "mud flow", "colour": "#eb6834"}]


def px(c0, c1, r0=0, r1=H):
    return F.px_box(GRID, c0, r0, c1, r1)


# five frames of 10 columns, and 10 columns outside every one of them
FRAMES = [("f%d" % (i + 1), px(10 * i, 10 * i + 10), False)
          for i in range(5)]
PAIRED = [
    ("polygons", A, 1, px(0, 10)), ("polygons", B, 1, px(0, 10)),
    ("polygons", C, 1, px(10, 20)), ("polygons", D, 2, px(10, 20)),
    ("polygons", A, 2, px(20, 30)), ("polygons", C, 2, px(20, 25)),
    ("polygons", B, 1, px(30, 40)),
    ("polygons", A, 1, px(40, 50)), ("polygons", B, 1, px(40, 50)),
    ("polygons", C, 2, px(40, 50)), ("polygons", D, 2, px(40, 50)),
    # a stray mark, in no frame: its tile_id is empty
    ("polygons", A, 1, px(50, 60), None),
]


def campaign(name, marks, frames=FRAMES):
    folder = os.path.join(root, name)
    package = F.make_campaign(folder, GRID, frames, marks, classes=CLASSES,
                              name=name, campaign_id=(name * 12)[:12])
    F._tif(os.path.join(folder, "ortho.tif"), GRID,
           np.full((H, W), 100, np.uint8))
    return folder, package


def label_arrays(marks):
    """What each reading painted, pixel by pixel: marks are boxes of whole
    pixels, so the array is read off the boxes themselves."""
    out = {r: np.zeros((H, W), np.uint8) for r in READINGS}
    ox, oy = GRID["origin"]
    for mark in marks:
        table, reading, code, box = mark[:4]
        c0, c1 = int(round(box[0] - ox)), int(round(box[2] - ox))
        r0, r1 = int(round(oy - box[3])), int(round(oy - box[1]))
        out[reading][r0:r1, c0:c1] = code
    return out


def oracle(labels, voters_at):
    """The vote worked out pixel by pixel in plain Python. voters_at(col)
    is the set of readings that vote in that column."""
    classes = np.zeros((H, W), np.uint8)
    votes = np.zeros((H, W), np.uint8)
    painted = np.zeros((H, W), np.uint8)
    voting = np.zeros((H, W), np.uint8)
    for row in range(H):
        for col in range(W):
            who = voters_at(col)
            need = len(who) // 2 + 1
            given = [int(labels[r][row, col]) for r in who]
            voting[row, col] = len(who)
            painted[row, col] = sum(1 for v in given if v)
            for code in set(v for v in given if v):
                n = given.count(code)
                if n >= need:
                    classes[row, col] = code
                    votes[row, col] = n
    return classes, votes, painted, voting


def whole(folder, package, choice, kinds=("mask", "votes"), points_in=False,
          tag="x"):
    outputs = [(k, os.path.join(folder, "%s_%s.tif" % (tag, k)), "GTiff")
               for k in kinds]
    src = gdal.Open(os.path.join(folder, "ortho.tif"))
    recipe = {"ds": src, "scale": 1, "rgb": [1, 1, 1],
              "limits": [(0.0, 255.0)] * 3, "alpha": 45,
              "colours": {1: (42, 120, 214), 2: (235, 104, 52)},
              "outputs": outputs, "package": package, "want_lines": False,
              "want_points": False, "want_boxes": False,
              "points_in_mask": points_in, "dot_px": 1, "reading": choice}
    g["paint_whole"](recipe)
    src = None
    out = {}
    for k, path, _ in outputs:
        ds = gdal.Open(path)
        out[k] = {"pixels": ds.ReadAsArray(), "meta": ds.GetMetadata(),
                  "bands": [ds.GetRasterBand(b + 1).GetDescription()
                            for b in range(ds.RasterCount)],
                  "path": path}
        ds = None
    return out


def consensus_of(package, tag):
    counts = g["readings_in"](package)
    return {c["tag"]: c for c in g["reading_choices"](counts)}[tag]


try:
    folder, package = campaign("paired", PAIRED)
    labels = label_arrays(PAIRED)
    choice = consensus_of(package, "consensus_p1")
    check("the consensus of the four is offered",
          sorted(choice["readings"]) == sorted(READINGS), choice)

    # --------------------------------------------------- who covered what
    print("who covered which frame")
    cover = g["consensus_voters"](package, READINGS)
    got = {t: sorted(r[0] for r in who) for t, who in cover["frames"].items()}
    check("each frame is voted by the readings that have a mark in it",
          got == {"f1": ["A", "B"], "f2": ["C", "D"], "f3": ["A", "C"],
                  "f4": ["B"], "f5": ["A", "B", "C", "D"]}, got)
    check("outside the frames, by the readings that painted anywhere",
          sorted(r[0] for r in cover["outside"]) == ["A", "B", "C", "D"],
          cover["outside"])
    check("and the design is said to be partial, with the frames by the "
          "number of readings",
          cover["partial"] and cover["by_readings"] == {1: 1, 2: 3, 4: 1},
          (cover["partial"], cover["by_readings"]))

    def voters_paired(col):
        if col >= 50:
            return READINGS
        return sorted(cover["frames"]["f%d" % (col // 10 + 1)])

    # -------------------------------------------------- the whole raster
    print()
    print("the whole raster: a frame read by two needs two")
    out = whole(folder, package, choice, kinds=("mask", "votes", "painted"),
                tag="paired")
    mask, votes = out["mask"], out["votes"]
    check("the picture painted with the consensus is written too, in the "
          "class colours", out["painted"]["pixels"].shape == (3, H, W)
          and tuple(int(c) for c in out["painted"]["pixels"][:, 5, 5]) !=
          tuple(int(c) for c in out["painted"]["pixels"][:, 5, 15]),
          out["painted"]["pixels"][:, 5, 5])
    want_c, want_v, want_p, want_n = oracle(labels, voters_paired)
    m = mask["pixels"]
    check("f1: two readings give class 1, and class 1 it is",
          (m[:, 0:10] == 1).all(), np.unique(m[:, 0:10]))
    check("f2: one gives 1 and one gives 2, no majority, 0",
          (m[:, 10:20] == 0).all(), np.unique(m[:, 10:20]))
    check("f3: both gave class 2 on the left half, and it is class 2",
          (m[:, 20:25] == 2).all(), np.unique(m[:, 20:25]))
    check("f3: on the right half only A painted, C began the frame and "
          "votes against, 0", (m[:, 25:30] == 0).all(),
          np.unique(m[:, 25:30]))
    check("f4: a frame one reading covered is that reading's",
          (m[:, 30:40] == 1).all(), np.unique(m[:, 30:40]))
    check("f5: two against two is a tie for three, 0",
          (m[:, 40:50] == 0).all(), np.unique(m[:, 40:50]))
    check("outside the frames, a mark of one reading in four falls",
          (m[:, 50:60] == 0).all(), np.unique(m[:, 50:60]))
    check("the whole mask is the one worked out by hand",
          np.array_equal(m, want_c), int((m != want_c).sum()))
    v = votes["pixels"]
    check("the votes file has a band for the readings that voted",
          votes["bands"] == ["votes", "readings_labelled",
                             "readings_voting"], votes["bands"])
    check("votes, painted and voting are the ones worked out by hand",
          np.array_equal(v[0], want_v) and np.array_equal(v[1], want_p)
          and np.array_equal(v[2], want_n),
          [int((v[i] != w).sum()) for i, w in
           enumerate((want_v, want_p, want_n))])
    check("the readings that voted: 2 in f1, f2 and f3, 1 in f4, 4 in f5",
          [int(v[2][0, 10 * i + 5]) for i in range(6)] == [2, 2, 2, 1, 4, 4],
          [int(v[2][0, 10 * i + 5]) for i in range(6)])
    check("the file says it is a majority among the readings of the frame",
          "covered that frame" in mask["meta"].get(
              "RASTERLABEL_READING_RULE", "")
          and "covered that frame" in votes["meta"].get(
              "RASTERLABEL_READING_RULE", ""), mask["meta"])
    check("and how many frames were read by how many",
          votes["meta"].get("RASTERLABEL_FRAMES_READ_BY")
          == "1 frame by 1 reading, 3 frames by 2 readings, "
             "1 frame by 4 readings", votes["meta"])
    check("the mask keeps its single band", mask["pixels"].ndim == 2
          and mask["bands"] == ["class_code"], mask["bands"])

    # ------------------------------------------------------ a full design
    print()
    print("everyone read every frame: what it always was")
    FULL = []
    pattern = {A: (1, 1, 2, 1, 2), B: (1, 2, 2, 1, 1),
               C: (1, 2, 1, 2, 2), D: (2, 2, 1, 1, 1)}
    for r, codes in pattern.items():
        for i, code in enumerate(codes):
            FULL.append(("polygons", r, code, px(10 * i, 10 * i + 10)))
    folder_f, package_f = campaign("full", FULL)
    labels_f = label_arrays(FULL)
    choice_f = consensus_of(package_f, "consensus_p1")
    cover_f = g["consensus_voters"](package_f, READINGS)
    check("every reading covers every frame, so the design is not partial",
          not cover_f["partial"] and all(
              len(w) == 4 for w in cover_f["frames"].values()), cover_f)
    out_f = whole(folder_f, package_f, choice_f, tag="full")
    # the vote as it was: n // 2 + 1 of all four everywhere
    old = oracle(labels_f, lambda col: READINGS)
    check("the mask is the plain vote of four: three of four",
          np.array_equal(out_f["mask"]["pixels"], old[0]),
          int((out_f["mask"]["pixels"] != old[0]).sum()))
    check("the votes file has two bands, as ever",
          out_f["votes"]["bands"] == ["votes", "readings_labelled"]
          and out_f["votes"]["pixels"].shape == (2, H, W),
          (out_f["votes"]["bands"], out_f["votes"]["pixels"].shape))
    check("and its votes and painted counts are the plain ones",
          np.array_equal(out_f["votes"]["pixels"][0], old[1])
          and np.array_equal(out_f["votes"]["pixels"][1], old[2]))
    rule_f = out_f["mask"]["meta"].get("RASTERLABEL_READING_RULE", "")
    check("the sentence in the file is the old one",
          rule_f == "consensus of 4 readings: each pixel takes the class at "
                    "least 3 of them gave it, a strict majority, and is 0 "
                    "where no class has one", rule_f)
    check("nothing about frames read by fewer readings",
          "RASTERLABEL_FRAMES_READ_BY" not in out_f["votes"]["meta"]
          and "RASTERLABEL_FRAMES_READ_BY" not in out_f["mask"]["meta"])
    stack = list(labels_f[r] for r in READINGS)
    plain = g["vote"](stack)
    everyone = g["vote"](stack, np.ones((4, H, W), bool))
    check("vote() with every reading voting is vote() without",
          all(np.array_equal(a, b) for a, b in zip(plain, everyone)))

    # --------------------------------------------------------- the ties
    print()
    print("ties and single readings, on arrays")
    one = np.array([[1, 1, 2, 0]], np.uint8)
    two = np.array([[1, 2, 2, 0]], np.uint8)
    three = np.array([[2, 0, 0, 3]], np.uint8)
    only_two = np.array([[True, True, True, True]])
    member = np.stack([only_two, only_two, ~only_two])    # the third is out
    cl, vo, pa = g["vote"]([one, two, three], member)
    check("a reading that did not cover the frame gives no vote and no "
          "label: of the two that did, both must agree",
          cl.tolist() == [[1, 0, 2, 0]] and vo.tolist() == [[2, 0, 2, 0]]
          and pa.tolist() == [[2, 2, 2, 0]], (cl, vo, pa))
    solo = np.stack([np.array([[True, False]]), np.array([[False, False]])])
    cl, vo, pa = g["vote"]([np.array([[3, 3]], np.uint8),
                            np.array([[4, 4]], np.uint8)], solo)
    check("a frame one reading covered: its class wins with one vote; "
          "a frame nobody covered holds nothing",
          cl.tolist() == [[3, 0]] and vo.tolist() == [[1, 0]]
          and pa.tolist() == [[1, 0]], (cl, vo, pa))
    four = [np.array([[1]], np.uint8), np.array([[1]], np.uint8),
            np.array([[2]], np.uint8), np.array([[2]], np.uint8)]
    cl, vo, pa = g["vote"](four, np.ones((4, 1, 1), bool))
    check("two against two, of four: no class has the three it needs",
          cl.tolist() == [[0]] and vo.tolist() == [[0]]
          and pa.tolist() == [[4]], (cl, vo, pa))
    cl, vo, pa = g["vote"](four[:3], np.ones((3, 1, 1), bool))
    check("two against one, of three: two it is",
          cl.tolist() == [[1]] and vo.tolist() == [[2]], (cl, vo))

    # --------------------------------------------------------- the export
    print()
    print("the export: the polygons of a frame are voted by its readings")

    def export(package, choice, tag, tile_id=None):
        recipe = {"tables": ["polygons"], "driver": "GPKG",
                  "extension": ".gpkg", "one_file": True, "crs": None,
                  "tile_id": tile_id,
                  "folder": os.path.join(root, "x_" + tag),
                  "reading": choice}
        written, failed, notes = g["write_vectors"](package, recipe, "camp")
        ds = ogr.Open(written[0])
        lyr = ds.GetLayerByName("polygons")
        rows = []
        for f in lyr:
            rows.append({"tile": f.GetField("tile_id"),
                         "code": f.GetField("class_code"),
                         "votes": f.GetField("votes"),
                         "readings": f.GetField("readings"),
                         "area": f.GetGeometryRef().GetArea()})
        lyr = ds = None
        return written[0], rows

    path, rows = export(package, choice, "paired")
    by_tile = {}
    for r in rows:
        by_tile.setdefault(r["tile"], []).append(
            (r["code"], r["votes"], r["readings"], round(r["area"], 6)))
    check("f1: class 1, 2 votes of 2 readings, the whole frame",
          by_tile.get("f1") == [(1, 2, 2, 100.0)], by_tile.get("f1"))
    check("f2: no ground, the two disagree", "f2" not in by_tile,
          by_tile.get("f2"))
    check("f3: class 2 where both gave it, half the frame, of 2 readings",
          by_tile.get("f3") == [(2, 2, 2, 50.0)], by_tile.get("f3"))
    check("f4: the reading that covered it, one vote of one",
          by_tile.get("f4") == [(1, 1, 1, 100.0)], by_tile.get("f4"))
    check("f5: the tie holds no ground", "f5" not in by_tile,
          by_tile.get("f5"))
    check("the stray mark outside the frames does not stand",
          set(by_tile) == {"f1", "f3", "f4"}, sorted(by_tile))
    _, one_frame = export(package, choice, "f3", tile_id="f3")
    check("one frame asked for is voted by its own readings",
          [(r["tile"], r["code"], r["votes"], r["readings"])
           for r in one_frame] == [("f3", 2, 2, 2)], one_frame)
    burned = gdal.GetDriverByName("MEM").Create("", W, H, 1, gdal.GDT_Byte)
    ox, oy = GRID["origin"]
    burned.SetGeoTransform((ox, 1.0, 0, oy, 0, -1.0))
    vds = ogr.Open(path)
    gdal.RasterizeLayer(burned, [1], vds.GetLayerByName("polygons"),
                        options=["ATTRIBUTE=class_code"])
    vds = None
    check("burned, the polygons are the consensus mask, pixel for pixel",
          np.array_equal(burned.ReadAsArray(), m),
          int((burned.ReadAsArray() != m).sum()))
    burned = None
    path, rows = export(package_f, choice_f, "full")
    check("everyone read every frame: three votes of four, as ever",
          rows and all(r["readings"] == 4 and r["votes"] >= 3
                       for r in rows),
          [(r["tile"], r["votes"], r["readings"]) for r in rows])

    # ------------------------------------------------------------ the card
    print()
    print("the dataset card counts the same vote")
    def manifest(where):
        with open(os.path.join(where, "campaign.json"),
                  encoding="utf-8") as fh:
            return json.load(fh)

    card = g["card_gather_campaign"](manifest(folder), folder, package)
    cons = {p["tag"]: p for p in card["products"]}["consensus_p1"]
    mask_counts = {int(k): int(n) for k, n in zip(*np.unique(
        m[m > 0], return_counts=True))}
    check("the card counts the pixels of the mask the Whole raster wrote",
          {int(k): v for k, v in cons["counts"].items()} == mask_counts,
          (cons["counts"], mask_counts))
    check("the votes the card counts are the file's",
          {int(k): v for k, v in cons["votes_histogram"].items()
           if int(k)} == {int(k): int(n) for k, n in zip(*np.unique(
               v[0][v[0] > 0], return_counts=True))},
          cons["votes_histogram"])
    check("without a majority: what was painted and did not stand",
          cons["no_majority_px"] == int(((v[1] > 0) & (v[0] == 0)).sum()),
          (cons["no_majority_px"], int(((v[1] > 0) & (v[0] == 0)).sum())))
    check("painted by every reading of the frame, with no class in the "
          "majority: f2 and f5",
          cons["all_painted_disagree_px"] == 200,
          cons["all_painted_disagree_px"])
    check("the card says the design is partial and how the frames were read",
          cons.get("partial_design") is True
          and {int(k): n for k, n in cons["frames_by_readings"].items()}
          == {1: 1, 2: 3, 4: 1}, cons.get("frames_by_readings"))
    check("with the rule that was used", "covered that frame" in cons["rule"],
          cons["rule"])
    line = g["card_consensus_line"](cons)
    check("and the sentence under the table says it",
          "covered its frame" in line and "3 frames by 2 readings" in line
          and "agreed by 2 readings" in line, line)
    card_f = g["card_gather_campaign"](manifest(folder_f), folder_f,
                                       package_f)
    cons_f = {p["tag"]: p for p in card_f["products"]}["consensus_p1"]
    check("a campaign read in full: no new fields, the old sentence",
          "partial_design" not in cons_f
          and "frames_by_readings" not in cons_f
          and "of 4" in g["card_consensus_line"](cons_f),
          g["card_consensus_line"](cons_f))
    counts_f = {int(k): int(n) for k, n in zip(*np.unique(
        out_f["mask"]["pixels"][out_f["mask"]["pixels"] > 0],
        return_counts=True))}
    check("and its counts are those of the mask",
          {int(k): v for k, v in cons_f["counts"].items()} == counts_f,
          (cons_f["counts"], counts_f))

    # ----------------------------------------------- points in the vote
    print()
    print("points that go into the mask cover the frame too")
    POINTS = [("polygons", A, 1, px(0, 10)),
              ("points", B, 1, px(0, 1, 0, 1))]
    folder_p, package_p = campaign("points", POINTS,
                                   frames=FRAMES[:1])
    without = g["consensus_voters"](package_p, [A, B])
    within = g["consensus_voters"](package_p, [A, B], points_in=True)
    check("a point is not a mark of the frame unless points are in the mask",
          sorted(r[0] for r in without["frames"]["f1"]) == ["A"]
          and sorted(r[0] for r in within["frames"]["f1"]) == ["A", "B"],
          (without["frames"], within["frames"]))
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
