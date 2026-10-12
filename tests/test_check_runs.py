"""Check runs to the end on a real campaign, and says what is true about it.

Every other test of the Check button read its source text, or ran it with no
campaign open. Neither ever executed the half that looks at a campaign, which
is the half that matters, and that is how this shipped:

    ValueError: too many values to unpack (expected 2)
      in _closed_flags, for (where, _pass), geoms in per_frame.items()

The grouping key had grown a third member, the operator, so that two people
reading one frame would stop being reported as an overlap. Every check of the
text passed. The first time the code ran, on the first campaign with a frame in
it, the whole report fell over.

So here it runs. QGIS is faked; the geometry is not. QgsGeometry is replaced by
a thin wrapper around shapely, which is GEOS, the same library QGIS hands the
arithmetic to, so an intersection, an area or a validity test here is the real
one. The campaign is the one from the session that found the bug: one frame,
two operators who each covered all of it, one genuine overlap inside the second
operator's reading, a raster with no coordinate system, and, added on top, a
polygon whose outline crosses itself.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile

ROOT = os.environ.get("RL_ROOT")
if not ROOT:
    print("set RL_ROOT to the repository root")
    sys.exit(2)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness_imports                                             # noqa: E402
harness_imports            # it builds the fakes on import

try:
    from shapely.geometry import Polygon, box                      # noqa: E402
    from shapely.ops import unary_union                            # noqa: E402
except ImportError:
    print("shapely is not installed:  pip install shapely")
    sys.exit(2)

from rasterlabel import doctor                                     # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


# ------------------------------------------------- geometry, through GEOS
class Box(object):
    def __init__(self, b):
        self.b = b

    def xMinimum(self): return self.b[0]
    def yMinimum(self): return self.b[1]
    def xMaximum(self): return self.b[2]
    def yMaximum(self): return self.b[3]

    def intersects(self, other):
        a, o = self.b, other.b
        return not (a[2] < o[0] or o[2] < a[0] or a[3] < o[1] or o[3] < a[1])


class Pt(object):
    def __init__(self, x, y):
        self._x, self._y = x, y

    def x(self): return self._x
    def y(self): return self._y


class G(object):
    """The parts of QgsGeometry that Check uses, done by GEOS."""

    def __init__(self, shape):
        self.s = shape

    def isEmpty(self): return self.s is None or self.s.is_empty
    def isNull(self): return self.s is None
    def area(self): return self.s.area
    def length(self): return self.s.length
    def boundingBox(self): return Box(self.s.bounds)
    def isGeosValid(self, *a): return self.s.is_valid

    def vertices(self):
        geoms = getattr(self.s, "geoms", [self.s])
        for g in geoms:
            for x, y in g.exterior.coords:
                yield Pt(x, y)

    def intersection(self, other):
        try:
            return G(self.s.intersection(other.s))
        except Exception:
            return G(None)              # what QGIS hands back on a GEOS error

    def makeValid(self):
        from shapely.validation import make_valid
        return G(make_valid(self.s))

    @staticmethod
    def unaryUnion(geoms):
        try:
            return G(unary_union([g.s for g in geoms]))
        except Exception:
            return G(None)


doctor.QgsGeometry = G


# ---------------------------------------------------- layers and features
class Feature(object):
    def __init__(self, shape, **values):
        self._g = G(shape)
        self.values = values

    def geometry(self): return self._g
    def __getitem__(self, key): return self.values[key]


class Field(object):
    def __init__(self, n): self._n = n
    def name(self): return self._n


class Layer(object):
    def __init__(self, features, fields):
        self._f = features
        self._fields = [Field(n) for n in fields]

    def getFeatures(self, *a): return iter(self._f)
    def fields(self): return self._fields
    def isEditable(self): return True
    def isModified(self): return False


PX = 0.05                       # metres, the size of a pixel of that raster
OX, OY = 500.0, 1000.0          # the grid origin
FRAME = box(OX, OY - 200 * PX, OX + 200 * PX, OY)       # 200 by 200 pixels


def cut(a, b):
    return a.difference(b)


# OPERATOR 1: a clean partition of the frame, two classes
op1_c3 = box(OX, OY - 200 * PX, OX + 120 * PX, OY)
op1_c2 = cut(FRAME, op1_c3)
# OP2: another reading of the same frame, mostly the other way round, with one
# genuine overlap between its own two polygons
op2_c2 = box(OX, OY - 200 * PX, OX + 90 * PX, OY)
op2_c3 = box(OX + 85 * PX, OY - 200 * PX, OX + 200 * PX, OY)
# and, on top, a bow tie: a vertex dragged across its own polygon's edge
bow = Polygon([(OX + 10 * PX, OY - 10 * PX), (OX + 30 * PX, OY - 30 * PX),
               (OX + 30 * PX, OY - 10 * PX), (OX + 10 * PX, OY - 30 * PX)])

common = dict(tile_id="t001", pass_no=1)
polygons = [
    Feature(op1_c3, class_name="class 3", class_code=3, operator="OPERATOR 1",
            **common),
    Feature(op1_c2, class_name="class 2", class_code=2, operator="OPERATOR 1",
            **common),
    Feature(op2_c2, class_name="class 2", class_code=2, operator="OP2",
            **common),
    Feature(op2_c3, class_name="class 3", class_code=3, operator="OP2",
            **common),
    Feature(bow, class_name="class 2", class_code=2, operator="OPERATOR 3",
            **common),
]
tiles = [Feature(FRAME, tile_id="t001", closed=1, side_m=10.0)]
LAYERS = {
    "polygons": Layer(polygons, ["class_name", "class_code", "tile_id",
                                 "pass_no", "operator", "created"]),
    "tiles": Layer(tiles, ["tile_id", "side_m", "note", "created", "closed"]),
    "lines": Layer([], ["class_name", "class_code"]),
    "points": Layer([], ["class_name", "class_code"]),
    "boxes": Layer([], ["class_name", "class_code"]),
}
doctor.find_mine = lambda cid, role: LAYERS.get(role)


# ------------------------------------------------- the package on disk
class OgrLayer(object):
    def __init__(self, name, n): self._n, self._c = name, n
    def GetName(self): return self._n
    def GetFeatureCount(self): return self._c


class OgrDs(object):
    def __init__(self):
        self.layers = [OgrLayer(t, len(LAYERS[t]._f))
                       for t in ("tiles", "polygons", "lines", "points", "boxes")]

    def GetLayerCount(self): return len(self.layers)
    def GetLayerByIndex(self, i): return self.layers[i]


doctor.ogr.Open = lambda path, *a: OgrDs()

folder = tempfile.mkdtemp(prefix="rl_check_")


class Campaign(object):
    def __init__(self):
        self.folder = folder
        self.package_path = os.path.join(folder, "annotation.gpkg")
        open(self.package_path, "wb").close()
        self.data = {
            "program": "RasterLabel", "id": "84f72dcb72ff",
            "name": "campaigntest2", "with_tiles": True,
            "classes": [{"name": "class 1", "code": 1, "colour": "#d95f02"},
                        {"name": "class 2", "code": 2, "colour": "#cdeb09"},
                        {"name": "class 3", "code": 3, "colour": "#1baf7a"}],
            "grid": {"reference_raster": "", "crs": "",
                     "origin": [OX, OY], "pixel_crs": [PX, PX],
                     "pixel_m": [PX, PX]},
        }


try:
    print("Check runs to the end on a campaign with a frame in it")
    try:
        text, bad, notes = doctor.report(Campaign())
        finished = True
    except Exception:
        import traceback
        traceback.print_exc()
        text, bad, notes, finished = "", -1, -1, False
    check("it does not stop with an error", finished)
    check("and writes the campaign half of the report",
          "THE CAMPAIGN" in text and "tables" in text)

    print()
    print("two readings of one frame are not an overlap")
    # OPERATOR 1 is a clean partition. OP2 overlaps itself by five pixels'
    # width. Between the two operators the overlap is everywhere, by design.
    check("one pair is reported, the one inside OP2's own reading",
          "1 pair of polygons share ground" in text,
          [l for l in text.splitlines() if "share ground" in l])
    check("not the cross-operator pairs, which used to be five",
          "5 pairs" not in text and "4 pairs" not in text)
    check("and the advice says why two readings are left out",
          "meant to cover it twice" in text)

    print()
    print("a raster with no coordinate system is not damage")
    check("no PROBLEM line about the crs", "the grid has no 'crs'" not in text)
    check("a note saying what is lost instead",
          "the raster has no coordinate system" in text)

    print()
    print("the grid is measured where it is promised")
    check("on the frame, which is on it",
          "every frame sits on the pixel grid" in text)
    check("not on brush outlines, which never were",
          "polygons not on the pixel grid" not in text)

    print()
    print("the outline that crosses itself is found")
    check("one outline crosses itself", "1 polygon outline crosses itself" in text,
          [l for l in text.splitlines() if "cross" in l])
    check("and the report sends it to Repair", "untangles the outline" in text)

    print()
    print("the closed column, which is the line that crashed")
    check("it is compared with the drawing and agrees",
          "every frame's 'closed' column agrees" in text,
          [l for l in text.splitlines() if "closed" in l])

    print()
    print("a frame off the grid would be a real problem, and is called one")
    tiles[0] = Feature(box(OX + 0.3 * PX, OY - 200 * PX, OX + 200.3 * PX, OY),
                       tile_id="t001", closed=1, side_m=10.0)
    LAYERS["tiles"]._f = tiles
    text2, bad2, _ = doctor.report(Campaign())
    check("it is reported", "1 frame not on the pixel grid" in text2,
          [l for l in text2.splitlines() if "grid" in l])
    check("as a problem, not a note",
          any(l.strip().startswith("PROBLEM") and "frame not on the pixel grid"
              in l for l in text2.splitlines()))

    # ------------------------------------------------------------------
    print()
    print("a sliver of 1e-16 left by GEOS after a vertex move is not an overlap")
    # Two polygons of one reading meeting along a border that GEOS computed
    # twice: their intersection has an area of the order of 1e-16. Repair
    # leaves it alone, rightly, and Check used to call it "share ground", so
    # the two buttons disagreed for ever: "1 pair" then "0 overlaps resolved".
    left = box(OX, OY - 200 * PX, OX + 100 * PX, OY)
    nudged = Polygon([(OX + 100 * PX - 1e-13, OY - 200 * PX),
                      (OX + 200 * PX, OY - 200 * PX), (OX + 200 * PX, OY),
                      (OX + 100 * PX, OY)])
    check("the sliver really has an area above zero",
          0 < left.intersection(nudged).area < 1e-9,
          left.intersection(nudged).area)
    polygons[:] = [Feature(left, class_name="class 2", class_code=2,
                           operator="OPERATOR 1", **common),
                   Feature(nudged, class_name="class 3", class_code=3,
                           operator="OPERATOR 1", **common)]
    tiles[0] = Feature(FRAME, tile_id="t001", closed=1, side_m=10.0)
    LAYERS["tiles"]._f = tiles
    text3, _, _ = doctor.report(Campaign())
    check("no pair is reported", "of polygons share ground" not in text3,
          [l for l in text3.splitlines() if "share ground" in l])
    check("the reading is called clean",
          "no two polygons of one reading share ground" in text3)

    print()
    print("a real overlap of a single pixel still is one")
    over = box(OX + 99 * PX, OY - 200 * PX, OX + 200 * PX, OY)
    polygons[1] = Feature(over, class_name="class 3", class_code=3,
                          operator="OPERATOR 1", **common)
    text4, _, _ = doctor.report(Campaign())
    check("it is reported", "1 pair of polygons share ground" in text4,
          [l for l in text4.splitlines() if "share ground" in l])

    print()
    print("neighbours of one class that were never joined are a note, not a problem")
    polygons[:] = [Feature(left, class_name="class 2", class_code=2,
                           operator="OPERATOR 1", **common),
                   Feature(box(OX + 100 * PX, OY - 200 * PX,
                               OX + 200 * PX, OY),
                           class_name="class 2", class_code=2,
                           operator="OPERATOR 1", **common)]
    text6, bad6, _ = doctor.report(Campaign())
    check("they are named, with Repair as the way out",
          "1 pair of neighbours of one class are still separate polygons"
          in text6 and "press Repair" in text6,
          [l for l in text6.splitlines() if "neighbours" in l])
    check("and no overlap is reported for them",
          "of polygons share ground" not in text6)
    polygons[1] = Feature(box(OX + 100 * PX, OY - 200 * PX, OX + 200 * PX, OY),
                          class_name="class 3", class_code=3,
                          operator="OPERATOR 1", **common)
    text7, _, _ = doctor.report(Campaign())
    check("neighbours of two classes are the partition, not a note",
          "still separate polygons" not in text7)
    polygons[1] = Feature(over, class_name="class 2", class_code=2,
                          operator="OPERATOR 1", **common)
    text8, _, _ = doctor.report(Campaign())
    check("an overlap between polygons of one class says Repair joins them",
          "1 pair of polygons share ground" in text8
          and "of one class, which Repair also joins" in text8,
          [l for l in text8.splitlines() if "share ground" in l])

    print()
    print("a campaign with no frames says nothing about frames it never had")
    LAYERS["tiles"]._f = []
    polygons[:] = [Feature(left, class_name="class 2", class_code=2,
                           operator="OPERATOR 1", tile_id="", pass_no=1)]
    camp = Campaign()
    camp.data["with_tiles"] = False
    text5, _, _ = doctor.report(camp)
    check("no 'not everything was looked at' with no reason after it",
          "nothing off the pixel grid, but not everything was looked at"
          not in text5,
          [l for l in text5.splitlines() if "grid" in l])

    print()
    print("a frame whose polygons were not read is not judged")
    # Over the ceiling, Check stops reading polygons. A frame whose polygons
    # all lie past the ceiling was then measured at 0% and, being marked
    # closed, reported as a PROBLEM about a frame nobody had looked at.
    saved_cap = doctor.MANY_FEATURES
    doctor.MANY_FEATURES = 1
    try:
        t2 = box(OX + 300 * PX, OY - 200 * PX, OX + 500 * PX, OY)
        LAYERS["tiles"]._f = [Feature(FRAME, tile_id="t001", closed=0,
                                      side_m=10.0),
                              Feature(t2, tile_id="t002", closed=1,
                                      side_m=10.0)]
        polygons[:] = [Feature(left, class_name="class 2", class_code=2,
                               operator="OPERATOR 1", **common),
                       Feature(t2, class_name="class 2", class_code=2,
                               operator="OPERATOR 1", tile_id="t002",
                               pass_no=1)]
        text6, _, _ = doctor.report(Campaign())
        check("t002 is not said to be 0% painted",
              "t002 says closed and is 0.0% painted" not in text6,
              [l for l in text6.splitlines() if "closed" in l])
    finally:
        doctor.MANY_FEATURES = saved_cap

    print()
    print("a check that measured only some frames does not say all are on the grid")
    saved_frames = doctor.MANY_FRAMES
    doctor.MANY_FRAMES = 1
    try:
        LAYERS["tiles"]._f = [Feature(FRAME, tile_id="t001", closed=1,
                                      side_m=10.0),
                              Feature(box(OX + 300 * PX, OY - 200 * PX,
                                          OX + 500 * PX, OY),
                                      tile_id="t002", closed=1, side_m=10.0)]
        # t001 painted and closed, t002 empty and marked closed: only the first
        # frame is read, so the second must not be vouched for either way
        polygons[:] = [Feature(FRAME, class_name="class 2", class_code=2,
                               operator="A", tile_id="t001", pass_no=1)]
        text7, _, _ = doctor.report(Campaign())
        check("no 'every frame sits on the pixel grid' after reading one of two",
              "every frame sits on the pixel grid" not in text7,
              [l for l in text7.splitlines() if "grid" in l])
        check("it says how many it measured",
              "first 1 frame" in text7,
              [l for l in text7.splitlines() if "grid" in l])
        check("nor that every frame's 'closed' column agrees",
              "every frame's 'closed' column agrees" not in text7,
              [l for l in text7.splitlines() if "closed" in l])

        print()
        print("three readings of one frame are one frame, not three")
        doctor.MANY_FRAMES = 2
        LAYERS["tiles"]._f = [Feature(FRAME, tile_id="t001", closed=1,
                                      side_m=10.0)]
        polygons[:] = [Feature(FRAME, class_name="class 2", class_code=2,
                               operator=who, tile_id="t001", pass_no=1)
                       for who in ("A", "B", "C")]
        text8, _, _ = doctor.report(Campaign())
        check("the closed column is still checked",
              "the 'closed' column was not checked" not in text8
              and "only the first 2 frames" not in text8,
              [l for l in text8.splitlines() if "closed" in l or "frames" in l])
    finally:
        doctor.MANY_FRAMES = saved_frames

    print()
    print("closed is one reading, never two operators added together")
    # Two operators at sixty per cent each, in different places: together
    # they cover the frame. The save used to write that frame closed, a
    # complete reading nobody made; Check measures readings, and must call it.
    anna = box(OX, OY - 200 * PX, OX + 120 * PX, OY)
    bruno = box(OX + 80 * PX, OY - 200 * PX, OX + 200 * PX, OY)
    LAYERS["tiles"]._f = [Feature(FRAME, tile_id="t001", closed=1,
                                  side_m=10.0)]
    polygons[:] = [Feature(anna, class_name="class 2", class_code=2,
                           operator="Anna", tile_id="t001", pass_no=1),
                   Feature(bruno, class_name="class 3", class_code=3,
                           operator="BRUNO", tile_id="t001", pass_no=None)]
    text12, _, _ = doctor.report(Campaign())
    flagged = [l for l in text12.splitlines() if "disagrees" in l]
    check("a frame marked closed on two half readings is a problem",
          any(l.strip().startswith("PROBLEM") for l in flagged), flagged)
    check("and the report says which reading it measured",
          "60.0% painted in its fullest reading" in text12,
          [l for l in text12.splitlines() if "painted" in l])
    LAYERS["tiles"]._f = [Feature(FRAME, tile_id="t001", closed=0,
                                  side_m=10.0)]
    text13, _, _ = doctor.report(Campaign())
    check("the same frame marked open agrees",
          "every frame's 'closed' column agrees" in text13,
          [l for l in text13.splitlines() if "closed" in l])
    polygons.append(Feature(cut(FRAME, anna), class_name="class 3",
                            class_code=3, operator="ANNA ", tile_id="t001",
                            pass_no=1))
    text14, _, _ = doctor.report(Campaign())
    check("and once ANNA has painted the rest, however her name was typed, "
          "open is the one that disagrees",
          "t001 says open and is 100.0% painted" in text14,
          [l for l in text14.splitlines() if "painted" in l])

    print()
    print("a class code past 254 is said")
    camp = Campaign()
    camp.data["classes"].append({"name": "far", "code": 300,
                                 "colour": "#000000"})
    text15, _, _ = doctor.report(camp)
    check("as a note, with the code and the 16 bit mask it means",
          "1 class code past 254" in text15 and "16 bits" in text15,
          [l for l in text15.splitlines() if "254" in l])
    check("and a legend within the codes says nothing about it",
          "class code past" not in text14)

    # ------------------------------------------------------------------
    # The correction campaign open in Correct has a section of its own. It
    # runs on the fakes of harness_imports: a working copy of 400 by 300
    # pixels holding the codes 1 and 3, nodata 0, with a flag band.
    print()
    print("the correction open in Correct is looked over too")
    from rasterlabel.correction import CorrectionCampaign          # noqa: E402
    fix = os.path.join(folder, "fix")
    os.makedirs(fix)
    open(os.path.join(fix, "map_corrected.tif"), "wb").close()
    with open(os.path.join(fix, "operations.csv"), "w") as f:
        f.write("n,when\n1,a\n2,b\n")
    book = CorrectionCampaign(fix)
    book.data = {"program": "RasterLabel", "kind": "correction", "format": 1,
                 "id": "c0ffee", "name": "fix", "source": "/gone/map.tif",
                 "band": 1, "working_copy": "map_corrected.tif",
                 "grid": {"crs": "EPSG:32633", "origin": [400000.0, 4100000.0],
                          "pixel_m": [0.05, 0.05], "size": [400, 300]},
                 "classes": [{"code": 1, "name": "a", "colour": "#000000"},
                             {"code": 3, "name": "b", "colour": "#ffffff"}],
                 "operations": 2}
    text9, bad9, _ = doctor.report(Campaign(), book)
    check("it has a section of its own", "THE CORRECTION" in text9)
    check("a whole manifest says nothing about its keys",
          "the manifest has no" not in text9.split("THE CORRECTION")[1])
    check("every code of the copy has a class",
          "every code in the copy has a class, 2 in all" in text9,
          text9.split("THE CORRECTION")[1][:600])
    check("the map it started from, gone, is a note",
          "the map it started from is not where it was" in text9)
    check("operations.csv agreeing with the count says nothing",
          "operations.csv has" not in text9)
    check("WHERE says where the correction is",
          "correction  %s" % fix in text9 and "map_corrected.tif" in text9)
    book.data["classes"] = book.data["classes"][:1]
    book.data["grid"]["size"] = [10, 10]
    book.data["operations"] = 5
    del book.data["kind"]
    text10, bad10, _ = doctor.report(Campaign(), book)
    part = text10.split("THE CORRECTION")[1]
    check("a code without a class is a note",
          "1 code in the copy without a class" in part, part[:800])
    check("a copy off the grid of the manifest is a problem",
          "PROBLEM the working copy is not on the grid of the manifest" in part,
          part[:800])
    check("a missing key is a problem", "the manifest has no 'kind'" in part)
    check("a log that disagrees with the count is a note",
          "operations.csv has 2 rows and the manifest counts 5" in part)
    check("and the problems are counted", bad10 > bad9, (bad9, bad10))
    text11, _, _ = doctor.report(None, book)
    check("with no campaign the campaign half is a note, not an alarm",
          "no annotation campaign is open" in text11
          and "PROBLEM the GeoPackage" not in text11)
finally:
    shutil.rmtree(folder, ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
