"""Points keep to the frame, like areas and lines do: run, not read.

In a tiled campaign a stroke is clipped to the frame in the list and a line is
clipped to it, and outside it nothing is drawn. A point used to go down
wherever the click landed, inside a frame or not, with the name of whatever
frame it happened to fall in, or none: and the export burned its whole square
of pixels there, on ground no frame covered. A campaign drawn without frames
is the one for points anywhere.

What has to hold, each case run through the methods of AnnotationSection
themselves (editkit borrows them unchanged and lets GEOS do the arithmetic):

  tiled   a click inside the frame in the list drops a point carrying its name;
          a click outside it, or with no frame picked, drops nothing and says
          so in the words a line uses; a point whose square of pixels would
          reach past the frame edge is refused too, because the export burns
          the whole square and nothing would clip it
  free    a point goes anywhere, as before
  moves   a point dragged out of its frame with the vertex tool is put back;
          one dragged within it stays; a frame moved with its contents takes
          its points along; removing and reclassing work anywhere
  Check   in a tiled campaign it counts the points outside every frame, and
          the ones that name a frame other than the one they sit in
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import sys

if not os.environ.get("RL_ROOT"):
    print("set RL_ROOT to the repository root")
    sys.exit(2)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import editkit as K
except ImportError as err:
    print("cannot build the kit: %s (pip install shapely)" % err)
    sys.exit(2)
from shapely.geometry import Point, box

from rasterlabel import doctor                                     # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def attempt(name, fn):
    """Run one case; an error is a failure of that case, not of the suite."""
    try:
        return fn()
    except Exception as err:
        import traceback
        traceback.print_exc()
        check(name + " (it ran)", False, "%s: %s" % (type(err).__name__, err))
        return None


# The grid of editkit: one unit a pixel, origin at (0, 10). T1 is ten pixels a
# side and sits on it, T2 sits beside it with a gap of ten pixels between.
T1 = box(0, 0, 10, 10)
T2 = box(20, 0, 30, 10)

# tile_of is what drop_point used to call, and is borrowed when it is there so
# that this suite runs the old drop_point too, and shows what it did.
for name in ("drop_point", "point_refusal", "tile_at", "tile_of",
             "remove_point_at", "reclass_point_at"):
    if name in K.SA.AnnotationSection.__dict__:
        setattr(K.Host, name, K.SA.AnnotationSection.__dict__[name])


class Chip(object):
    def __init__(self): self.on = False
    def isChecked(self): return self.on


class Drawing(K.Panel):
    def who_is_drawing(self): return "OP1"
    def which_pass(self): return 1


def campaign(tiled=True, tile_id="t001"):
    polys = K.Layer("polygons")
    tiles = None
    if tiled:
        tiles = K.Layer("tiles")
        K.put(tiles, T1, tile_id="t001")
        K.put(tiles, T2, tile_id="t002")
    points = K.Layer("points")
    points.fields_ = K.Fields(K.Field(n) for n in K.FIELDS + ["size_px",
                                                              "conf"])
    host = K.Host(polys, tiles, tile_id=tile_id)
    host.layers["points"] = points
    host.panel = Drawing()
    host.uncertain = Chip()
    host.size = 1
    host.point_size = lambda: host.size
    host.current_code = lambda: 1
    if hasattr(host, "watch_point_moves"):
        host.watch_point_moves()
    return host, points


def drop(host, x, y, size=1):
    host.size = size
    before = len(K.Bar.said)
    host.drop_point(K.Pt(x, y))
    K.Loop.run()
    return K.Bar.said[before:]


def rows(layer):
    return list(layer.getFeatures())


# ------------------------------------------------------------- tiled, inside
print("tiled: a click inside the frame in the list")


def inside():
    host, points = campaign()
    said = drop(host, 5.5, 5.5)
    got = rows(points)
    check("drops one point", len(got) == 1, len(got))
    check("carrying the frame's name",
          got and got[0]["tile_id"] == "t001", got and got[0]["tile_id"])
    check("and its size", got and got[0]["size_px"] == 1)
    check("and says nothing against it",
          not [s for s in said if "nothing drawn" in s], said)


attempt("inside", inside)

# ------------------------------------------------------------ tiled, outside
print()
print("tiled: a click outside the frame in the list")


def outside():
    host, points = campaign()
    said = drop(host, 15.0, 5.0)
    check("drops nothing between the frames", len(rows(points)) == 0,
          len(rows(points)))
    check("and says so in the words a line uses",
          any("nothing drawn: the point fell outside the tile" in s
              for s in said), said)

    said = drop(host, 25.0, 5.0)
    check("drops nothing in another frame either", len(rows(points)) == 0)
    check("and names the frame it is in",
          any("nothing drawn: the point fell outside the tile" in s
              and "t002" in s for s in said), said)

    said = drop(host, -40.0, 90.0)
    check("nor far away from every frame", len(rows(points)) == 0)


attempt("outside", outside)


def no_frame():
    host, points = campaign(tile_id=None)
    said = drop(host, 5.5, 5.5)
    check("with no frame picked nothing is dropped", len(rows(points)) == 0,
          len(rows(points)))
    check("and the bar says no tile selected",
          any("no tile selected" in s for s in said), said)


attempt("no frame", no_frame)

# --------------------------------------------------------------- the edge
print()
print("tiled: the square of pixels has to fit in the frame")


def edge():
    host, points = campaign()
    # a single pixel in the first and in the last column is inside
    drop(host, 0.5, 5.5, 1)
    drop(host, 9.5, 5.5, 1)
    check("a 1 px point in the edge pixels of the frame goes in",
          len(rows(points)) == 2, len(rows(points)))
    # 3 x 3 in the edge pixel reaches one pixel out: refused
    said = drop(host, 0.5, 5.5, 3)
    check("a 3 x 3 point in the edge pixel is refused",
          len(rows(points)) == 2, len(rows(points)))
    check("and the bar says it is the footprint, and how far in to click",
          any("nothing drawn" in s and "3 x 3 footprint" in s
              and "1 pixel of room" in s for s in said), said)
    drop(host, 1.5, 5.5, 3)
    drop(host, 8.5, 8.5, 3)
    check("one pixel further in it fits, on either side",
          len(rows(points)) == 4, len(rows(points)))
    said = drop(host, 9.5, 1.5, 3)
    check("and on the right edge it is refused again",
          len(rows(points)) == 4, said)
    # 9 x 9 needs four pixels of room on every side: only the middle of a
    # ten pixel frame has it
    drop(host, 5.5, 5.5, 9)
    drop(host, 4.5, 4.5, 9)
    check("a 9 x 9 point fits where it has four pixels of room",
          len(rows(points)) == 6, len(rows(points)))
    drop(host, 3.5, 5.5, 9)
    check("and not where it has three", len(rows(points)) == 6)
    # on the right edge itself the point is in the pixel beyond the frame
    said = drop(host, 10.0, 5.5, 1)
    check("a click exactly on the right edge is in the next pixel: refused",
          len(rows(points)) == 6, said)
    drop(host, 0.0, 10.0, 1)
    check("and exactly on the top left corner it is the first pixel: in",
          len(rows(points)) == 7, len(rows(points)))
    for f in rows(points):
        sq = K.GEO.footprint_box(f.geometry().s.x, f.geometry().s.y,
                                 f["size_px"], (0.0, 10.0), (1.0, 1.0))
        if not T1.contains(box(*sq)):
            check("every square written lies inside the frame", False, sq)
            break
    else:
        check("every square written lies inside the frame", True)


attempt("edge", edge)


def same_as_export():
    """The square the rule tests is the square the export burns: the Stencil in
    rasters.py, its formula written out as it is there."""
    import math
    ox, oy, dx, dy = 0.0, 10.0, 1.0, -1.0
    for x, y, n in ((0.5, 5.5, 3), (9.99, 0.01, 9), (3.0, 7.0, 1),
                    (4.25, 2.75, 5)):
        col = int(math.floor((x - ox) / dx))
        row = int(math.floor((y - oy) / dy))
        half = n // 2
        x0 = ox + (col - half) * dx
        x1 = ox + (col + half + 1) * dx
        y0 = oy + (row - half) * dy
        y1 = oy + (row + half + 1) * dy
        want = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        got = K.GEO.footprint_box(x, y, n, (ox, oy), (dx, abs(dy)))
        if got is None or max(abs(a - b) for a, b in zip(got, want)) > 1e-12:
            check("the footprint is the export's square", False, (got, want))
            return
    check("the footprint is the export's square", True)


attempt("same as export", same_as_export)

# ------------------------------------------------------------------- free
print()
print("free: a campaign without frames takes points anywhere")


def free():
    host, points = campaign(tiled=False)
    for x, y in ((5.5, 5.5), (15.0, 5.0), (-40.0, 90.0), (10.0, 5.5)):
        drop(host, x, y, 9)
    got = rows(points)
    check("every click drops its point", len(got) == 4, len(got))
    check("with no frame name", all(f["tile_id"] == "" for f in got),
          [f["tile_id"] for f in got])


attempt("free", free)

# --------------------------------------------------------- moved by hand
print()
print("a point moved with the vertex tool stays in its frame")


def moves():
    host, points = campaign()
    drop(host, 5.5, 5.5, 3)
    fid = rows(points)[0].id()
    before = len(K.Bar.said)
    points.drag(fid, Point(6.5, 6.5))
    K.Loop.run()
    check("dragged within its frame it stays where it was put",
          K.shape_of(points, fid).coords[0] == (6.5, 6.5),
          K.shape_of(points, fid))
    points.drag(fid, Point(15.0, 5.0))
    K.Loop.run()
    check("dragged out of it, it is put back",
          K.shape_of(points, fid).coords[0] == (6.5, 6.5),
          K.shape_of(points, fid))
    check("and the bar says why",
          any("point put back" in s for s in K.Bar.said[before:]),
          K.Bar.said[before:])
    points.drag(fid, Point(25.5, 5.5))
    K.Loop.run()
    check("into another frame too",
          K.shape_of(points, fid).coords[0] == (6.5, 6.5))
    points.drag(fid, Point(9.5, 5.5))
    K.Loop.run()
    check("and to where its square would reach past the edge",
          K.shape_of(points, fid).coords[0] == (6.5, 6.5))
    # Ctrl+Z after a good drag is not a drag, and is not walked back
    points.drag(fid, Point(4.5, 4.5))
    K.Loop.run()
    points.undoStack().undo()
    K.Loop.run()
    check("an undo is not taken for a drag",
          K.shape_of(points, fid).coords[0] == (6.5, 6.5),
          K.shape_of(points, fid))

    # a point an earlier build left with no frame: dragging it into a frame
    # does not give it one, and the bar says so plainly
    shost, spoints = campaign()
    stray = K.put(spoints, Point(15.0, 5.0), tile_id="", class_name="a",
                  class_code=1, size_px=1)
    spoints.startEditing()
    before = len(K.Bar.said)
    spoints.drag(stray, Point(5.5, 2.5))
    K.Loop.run()
    check("a point with no frame dragged into one is put back",
          K.shape_of(spoints, stray).coords[0] == (15.0, 5.0),
          K.shape_of(spoints, stray))
    check("and the bar says it carries no frame",
          any("point put back" in s and "carries no frame" in s
              for s in K.Bar.said[before:]), K.Bar.said[before:])

    fhost, fpoints = campaign(tiled=False)
    drop(fhost, 5.5, 5.5)
    ffid = rows(fpoints)[0].id()
    fpoints.drag(ffid, Point(-50.0, 70.0))
    K.Loop.run()
    check("in a free campaign a point is dragged anywhere",
          K.shape_of(fpoints, ffid).coords[0] == (-50.0, 70.0))


attempt("moves", moves)


def cleanup():
    host, points = campaign()
    # a point left outside every frame by an earlier build
    old = K.put(points, Point(15.0, 5.0), tile_id="", class_name="a",
                class_code=1, size_px=1)
    points.startEditing()
    host.class_name = "b"
    host.current_code = lambda: 2
    host.point_at = lambda p: points.getFeature(old)
    host.reclass_point_at(K.Pt(15.0, 5.0))
    check("a point outside can still be reclassed",
          points.getFeature(old)["class_name"] == "b")
    host.remove_point_at(K.Pt(15.0, 5.0))
    check("and removed", not points.getFeature(old).isValid())


attempt("cleanup", cleanup)


class Ask(object):
    """QMessageBox, answering its first button: move with the contents."""
    Warning = Cancel = AcceptRole = DestructiveRole = 0

    def __init__(self, *a): self.buttons = []
    def setIcon(self, *a): pass
    def setWindowTitle(self, *a): pass
    def setText(self, *a): pass
    def setInformativeText(self, *a): pass
    def setDefaultButton(self, *a): pass
    def button(self, *a): return None

    def addButton(self, *a):
        b = object()
        self.buttons.append(b)
        return b

    def clickedButton(self): return self.buttons[0]


# The program asks for QMessageBox.StandardButton.Yes, QMessageBox.Icon.Warning
# and the like, the spelling Qt 5 and Qt 6 share: the stand-in answers to
# those through itself.
Ask.Icon = Ask.StandardButton = Ask.ButtonRole = Ask


def carried():
    host, points = campaign()
    drop(host, 5.5, 5.5)
    drop(host, 1.5, 1.5)
    points.commitChanges()
    points.startEditing()
    before = len(K.Bar.said)
    real = (K.SA.QMessageBox, K.SA.run_dialog)
    K.SA.QMessageBox, K.SA.run_dialog = Ask, (lambda d: None)
    try:
        frame = [f for f in host.tile_layer.getFeatures()
                 if f["tile_id"] == "t001"][0]
        host.move_tile(frame, 3.0, 0.0)
        K.Loop.run()
    finally:
        K.SA.QMessageBox, K.SA.run_dialog = real
    where = sorted(f.geometry().s.coords[0] for f in rows(points))
    check("a frame moved with its contents takes its points along",
          where == [(4.5, 1.5), (8.5, 5.5)], where)
    check("and the move is not taken for a drag out of the frame",
          not [s for s in K.Bar.said[before:] if "point put back" in s],
          K.Bar.said[before:])
    check("they still carry the frame's name",
          all(f["tile_id"] == "t001" for f in rows(points)))


attempt("carried", carried)

# ---------------------------------------------------------------- Check
print()
print("Check counts the points that do not keep to their frame")


class Campaign(object):
    def __init__(self, tiled=True):
        self.data = {"id": "x", "with_tiles": tiled,
                     "grid": {"origin": [0.0, 10.0], "pixel_crs": [1.0, 1.0],
                              "pixel_m": [1.0, 1.0]}}


def doctor_finds():
    points = K.Layer("points")
    points.fields_ = K.Fields(K.Field(n) for n in K.FIELDS + ["size_px"])
    tiles = K.Layer("tiles")
    K.put(tiles, T1, tile_id="t001")
    K.put(tiles, T2, tile_id="t002")
    K.put(points, Point(5.5, 5.5), tile_id="t001", size_px=3)    # fine
    K.put(points, Point(25.5, 5.5), tile_id="t002", size_px=1)   # fine
    K.put(points, Point(15.0, 5.0), tile_id="", size_px=1)       # outside
    K.put(points, Point(-4.0, 3.0), tile_id=None, size_px=1)     # outside
    K.put(points, Point(0.5, 5.5), tile_id="t001", size_px=3)    # past edge
    K.put(points, Point(6.5, 6.5), tile_id="t002", size_px=1)    # misnamed
    layers = {"points": points, "tiles": tiles}
    real = doctor.find_mine
    doctor.find_mine = lambda cid, role: layers.get(role)
    try:
        if not hasattr(doctor, "_points_in_frames"):
            check("Check looks at the points at all", False)
            return
        camp = Campaign()
        found = doctor._points_in_frames(camp, camp.data["grid"])
        text = "\n".join(str(f) for f in found)
        print(text)
        check("three points outside every frame, the one whose square "
              "crosses the edge among them",
              "3 points outside every frame" in text, text)
        check("one point inside a frame other than the one it names",
              "1 point inside a frame other than the one it names" in text,
              text)
        check("as notes, not problems",
              found and all(f.level == doctor.NOTE for f in found),
              [f.level for f in found])
        check("and it says how to clean up",
              "right click" in text and "remove" in text, text)
        check("and is wired into the report",
              "_points_in_frames(campaign, grid)" in open(
                  doctor.__file__, encoding="utf-8").read())

        free = doctor._points_in_frames(Campaign(tiled=False),
                                        camp.data["grid"])
        check("a free campaign is not judged on frames", free == [], free)

        clean = K.Layer("points")
        clean.fields_ = points.fields_
        K.put(clean, Point(5.5, 5.5), tile_id="t001", size_px=3)
        layers["points"] = clean
        good = doctor._points_in_frames(camp, camp.data["grid"])
        check("a clean campaign is called clean",
              any(f.level == doctor.OK and "every point sits inside" in f.what
                  for f in good), [str(f) for f in good])

        # Frames may overlap. A point in the overlap that names the second
        # frame is where it belongs, and is not to be called misnamed because
        # the first frame happens to hold it too.
        lapped = K.Layer("tiles")
        K.put(lapped, T1, tile_id="t001")
        K.put(lapped, box(5, 0, 15, 10), tile_id="t003")
        both = K.Layer("points")
        both.fields_ = points.fields_
        K.put(both, Point(7.5, 5.5), tile_id="t003", size_px=3)
        layers["points"], layers["tiles"] = both, lapped
        found = doctor._points_in_frames(camp, camp.data["grid"])
        check("a point in two overlapping frames that names the second is "
              "not misnamed",
              any(f.level == doctor.OK for f in found) and not any(
                  "other than" in f.what for f in found),
              [str(f) for f in found])

        # More frames than the cap on frames elsewhere in Check: a point in
        # the last of them is inside its frame, not outside every frame.
        many = K.Layer("tiles")
        last = doctor.MANY_FRAMES + 5
        for i in range(last + 1):
            K.put(many, box(i * 20, 0, i * 20 + 10, 10),
                  tile_id="t%03d" % (i + 1))
        far = K.Layer("points")
        far.fields_ = points.fields_
        K.put(far, Point(last * 20 + 5.5, 5.5), tile_id="t%03d" % (last + 1),
              size_px=1)
        layers["points"], layers["tiles"] = far, many
        found = doctor._points_in_frames(camp, camp.data["grid"])
        check("a point in a frame past the first %d is in its frame"
              % doctor.MANY_FRAMES,
              any(f.level == doctor.OK for f in found) and not any(
                  "outside" in f.what for f in found),
              [str(f) for f in found])

        # A manifest with no pixel size: the point itself is judged, not a
        # square of one map unit invented for it.
        tiny = K.Layer("tiles")
        K.put(tiny, box(0, 0, 0.5, 0.5), tile_id="t001")
        near = K.Layer("points")
        near.fields_ = points.fields_
        K.put(near, Point(0.25, 0.25), tile_id="t001", size_px=1)
        layers["points"], layers["tiles"] = near, tiny
        # the kit leaves QgsPointXY a dummy in geometry.py; this one path
        # builds a point from two numbers, so it gets the kit's point
        from rasterlabel import geometry as GM
        was = GM.QgsPointXY
        GM.QgsPointXY = K.Pt
        try:
            found = doctor._points_in_frames(camp, {"origin": [0.0, 10.0]})
        finally:
            GM.QgsPointXY = was
        check("with no pixel size in the grid, a point inside its frame is "
              "inside it",
              any(f.level == doctor.OK for f in found),
              [str(f) for f in found])
    finally:
        doctor.find_mine = real


doctor.QgsGeometry = K.G
attempt("doctor", doctor_finds)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
