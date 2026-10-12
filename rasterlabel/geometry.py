"""rasterlabel.geometry

The pixel grid, and every measurement made on it.
"""
import math
import numpy as np

from osgeo import gdal
from qgis.PyQt.QtGui import QTransform
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsDistanceArea, QgsGeometry, QgsPointXY, QgsProject,
                       QgsRectangle)

from .constants import GEOM_POLYGON, MIN_AREA_PX, OVERLAP_SHARE
from .project import (crs_from_text, crs_label, ellipsoid_for, in_degrees,
                      in_metres, named_crs, placeholder_crs)
from .errors import log
from .rasters import pixel_grid


# How long a shared border must be to join two polygons, as a share of the
# smaller side of a pixel. Shorter than that is the residue of a border worked
# out twice, not a border.
JOIN_EDGE_PX = 1e-3


def joint_of(a, b, px, py):
    """How two polygons meet: "overlap", "border" or None.

    "overlap" when they share ground above the dust Check and Repair read
    (a hundredth of a pixel), "border" when they share a line of positive
    length and no ground, None when they are apart or only touch at a point.
    Only the first two make one polygon when united; two polygons that meet at
    a corner would unite into a multipolygon or a bow tie."""
    try:
        if not a.boundingBox().intersects(b.boundingBox()):
            return None
        shared = a.intersection(b)
    except Exception:
        return None
    if shared is None or shared.isNull() or shared.isEmpty():
        return None
    try:
        if shared.area() > OVERLAP_SHARE * px * py:
            return "overlap"
        if shared.length() > JOIN_EDGE_PX * min(px, py):
            return "border"
    except Exception:
        return None
    return None


#  Geometry helpers, all derived from the campaign instead of hard coded
# =====================================================================
class Geometry(object):
    """Measurements and buffers in true metres, whatever the campaign CRS is.

    A fixed metric system would be wrong everywhere except where it was
    written. If the campaign already counts in metres it is used as it is,
    otherwise the UTM zone of the site is chosen from its own coordinates.
    Whether it counts in metres is asked of its units, never of its kind: see
    in_degrees() for the orthomosaic that was taken for a metric one."""

    def __init__(self, campaign, crs_override=None):
        grid = campaign.data["grid"]
        self.origin = tuple(grid.get("origin") or (0.0, 0.0))
        written = grid.get("crs") or ""
        self.crs = named_crs(crs_from_text(written), self.origin)
        if placeholder_crs(crs_override):
            # The tables were made with no system, and the GeoPackage put its
            # stand-in there: a sphere in degrees that a photograph's tables
            # carry too. Letting it win made a picture's pixels into degrees.
            log("the tables carry no coordinate system of their own: going by "
                "the manifest, %s" % crs_label(self.crs))
            crs_override = None
        if crs_override is not None and crs_override.isValid():
            crs_override = named_crs(crs_override, self.origin)
            if not self.crs.isValid() or crs_override != self.crs:
                log("the manifest says %s but the layers are in %s: the layers win"
                    % (crs_label(self.crs) if written else "nothing",
                       crs_label(crs_override)))
                self.crs = crs_override
        px, py = grid["pixel_m"]
        self.pixel_m = (px, py)
        self.pixel_area = px * py
        self.min_area = MIN_AREA_PX * self.pixel_area
        # The sliver test runs on the plane, in the units of the campaign
        # system. Measuring it on the ellipsoid means that a failed measurement
        # returns zero and every piece is silently thrown away.
        cx, cy = grid.get("pixel_crs", (px, py))
        self.pixel_crs = (abs(cx), abs(cy))
        self.min_area_flat = MIN_AREA_PX * abs(cx * cy)
        # Campaign units in one metre, along x and along y, from the two sizes
        # of the pixel the manifest already holds. It is what the buffers fall
        # back on when there is no metric system to go through.
        if px and py and cx and cy:
            self.per_metre = (abs(cx / px), abs(cy / py))
        else:
            self.per_metre = (1.0, 1.0)
        ctx = QgsProject.instance().transformContext()
        self.metric = self._metric_crs()
        if self.metric is not None:
            self.to_m = QgsCoordinateTransform(self.crs, self.metric, ctx)
            self.from_m = QgsCoordinateTransform(self.metric, self.crs, ctx)
        else:
            self.to_m = self.from_m = None
            if self.crs.isValid():
                log("no metric system found for %s: metres are turned into its "
                    "units with the pixel size of the manifest, %.6g x %.6g to "
                    "the metre" % ((crs_label(self.crs),) + self.per_metre))
        self.measure = QgsDistanceArea()
        self.measure.setSourceCrs(self.crs, ctx)
        # On the plane when the campaign has no system: an ellipsoid on top of
        # no system would read a picture's pixels as degrees, and every area,
        # length and coverage of it would come out NaN (ellipsoid_for).
        self.measure.setEllipsoid(ellipsoid_for(self.crs))

    def _metric_crs(self):
        """The system distances are worked out in, or None for none.

        None does not mean the campaign system itself, whatever it counts in:
        a campaign in degrees that this could not place would get a half metre
        brush half a degree wide. None sends the buffers to the pixel
        ratio instead, which is never more wrong than the pixel size is."""
        if not self.crs.isValid():
            return None
        if in_metres(self.crs):
            return self.crs
        x, y = self.origin
        if not in_degrees(self.crs):
            # feet, or a unit nobody named: the site is found in degrees
            # through QGIS, and the UTM zone from there
            try:
                p = QgsCoordinateTransform(
                    self.crs, QgsCoordinateReferenceSystem("EPSG:4326"),
                    QgsProject.instance().transformContext()).transform(
                        QgsPointXY(x, y))
                x, y = p.x(), p.y()
            except Exception:
                return None
        if not (-180 <= x <= 180 and -90 <= y <= 90):
            return None
        zone = min(int((x + 180) / 6) + 1, 60)
        code = 32600 + zone if y >= 0 else 32700 + zone
        utm = QgsCoordinateReferenceSystem("EPSG:%d" % code)
        return utm if utm.isValid() else None

    def area(self, g):
        try:
            return self.measure.measureArea(g)
        except Exception:
            return 0.0

    def length(self, g):
        """On the ground, not in degrees. A fissure measured in degrees of
        longitude is a number nobody can put in a paper."""
        try:
            return self.measure.measureLength(g)
        except Exception:
            return 0.0

    def shared_border(self, a, b):
        """The border two polygons have in common, as a line, or None.

        QgsGeometry has no boundary(): only the abstract geometry behind it
        does, so it is asked there and wrapped again. Asking the wrapper
        raises AttributeError, and a caller that treats any error as "they do
        not touch" would read every neighbour as a stranger."""
        try:
            line_a = QgsGeometry(a.constGet().boundary())
            line_b = QgsGeometry(b.constGet().boundary())
        except (AttributeError, TypeError):
            return None
        along = line_a.intersection(line_b)
        if along is None or along.isEmpty():
            return None
        return along

    def _flat(self, g, back=False):
        """A geometry put on a local plane where one unit is one metre, or
        brought back from it: the safety net when there is no metric system.
        The two directions are scaled separately, because a degree of
        longitude and a degree of latitude are not the same length."""
        rx, ry = self.per_metre
        ox, oy = self.origin
        g = QgsGeometry(g)
        if back:
            g.transform(QTransform(rx, 0.0, 0.0, ry, ox, oy))
        else:
            g.transform(QTransform(1.0 / rx, 0.0, 0.0, 1.0 / ry,
                                   -ox / rx, -oy / ry))
        return g

    def buffer(self, geom, metres, segments=12):
        if self.to_m is None:
            return self._flat(self._flat(geom).buffer(metres, segments), True)
        g = QgsGeometry(geom)
        g.transform(self.to_m)
        g = g.buffer(metres, segments)
        g.transform(self.from_m)
        return g

    def parts(self, g):
        """Split into single polygons, dropping the slivers."""
        if g is None or g.isEmpty():
            return []
        g = g.makeValid()
        pieces = g.asGeometryCollection() \
            if (g.isMultipart() or g.type() != GEOM_POLYGON) else [g]
        return [x for x in pieces
                if x.type() == GEOM_POLYGON
                and x.area() >= self.min_area_flat]

    def leftovers(self, g):
        """Split into single polygons, largest first, keeping every piece that
        is more than numerical dust.

        parts() throws away what is under four pixels, which is right for a
        stroke: a stray fleck of a drawing is not worth a polygon. It is wrong
        for ground that a cut leaves behind. That ground was painted a moment
        ago, a frame marked closed counts on it, and a piece thrown away is a
        hole nobody made on purpose, which Fill Gap then could not see. So the
        remainder of a cut, the ground a neighbour takes over and the lobes of
        an untangled outline all come through here and lose only what no pixel
        centre can fall in: a hundredth of a pixel, the residue GEOS leaves
        when a border is worked out twice (the same floor Check uses for an
        overlap)."""
        if g is None or g.isEmpty():
            return []
        g = g.makeValid()
        pieces = g.asGeometryCollection() \
            if (g.isMultipart() or g.type() != GEOM_POLYGON) else [g]
        px, py = self.pixel_crs
        dust = OVERLAP_SHARE * px * py
        kept = [x for x in pieces
                if x.type() == GEOM_POLYGON and x.area() > dust]
        kept.sort(key=lambda x: -x.area())
        return kept

    def square(self, centre, side_m):
        """A square of the given side, centred on a point, in campaign units."""
        h = side_m / 2.0
        if self.to_m is None:
            hx, hy = h * self.per_metre[0], h * self.per_metre[1]
            return QgsGeometry.fromRect(QgsRectangle(
                centre.x() - hx, centre.y() - hy,
                centre.x() + hx, centre.y() + hy))
        g = QgsGeometry.fromPointXY(centre)
        g.transform(self.to_m)
        c = g.asPoint()
        r = QgsGeometry.fromRect(QgsRectangle(c.x() - h, c.y() - h,
                                              c.x() + h, c.y() + h))
        r.transform(self.from_m)
        return r

    def snapped_square(self, centre, side_m):
        """A square whose sides fall on the pixel edges of the campaign raster.

        A frame that ends halfway through a pixel produces a cutout offset by
        half a pixel from the frame that was drawn, and the labels burned from
        it inherit the offset. So the side is rounded to a whole number of
        pixels and the corner is put on a pixel edge. Returns the square and
        how many pixels its side is, or None when there is no usable grid."""
        px, py = self.pixel_crs
        ox, oy = self.origin
        # The origin may be zero. On a plain picture opened in
        # QGIS, a scan or a photograph, the origin very often is exactly (0, 0),
        # and a guard on it would turn the grid down: no squares could be placed
        # and no lines drawn. Only the pixel size says whether there is a grid.
        if px <= 0 or py <= 0:
            return None, 0
        side_px = max(1, int(round(side_m / max(self.pixel_m[0], 1e-12))))
        col = int(round((centre.x() - ox) / px)) - side_px // 2
        row = int(round((oy - centre.y()) / py)) - side_px // 2
        # Every edge as "origin plus a whole number of pixels", never as
        # "the other edge minus a size": the two are the same number and not
        # always the same double, and two frames laid side by side on the same
        # grid would then miss each other by a fraction of a nanometre.
        return QgsGeometry.fromRect(QgsRectangle(
            ox + col * px, oy - (row + side_px) * py,
            ox + (col + side_px) * px, oy - row * py)), side_px

    def strip(self, points, width_px):
        """The ground a traced line claims, as whole pixels.

        A buffer would be the obvious way and it is the wrong one. Buffering a
        line by half a pixel and then burning the result with ALL_TOUCHED off
        gives a trace that breaks into dashes wherever the strip misses a pixel
        centre, and "one pixel wide" would not be one pixel wide. So the pixels
        are chosen one by one, by the rule the mask is burned with (a pixel
        belongs to whoever covers its centre), and the polygon is built back
        from them. The strip is the trace laid as a rectangle width_px pixels
        across, whichever way it runs: see line_pixels() for what is measured.
        Because it is made of whole pixels it burns to exactly those pixels
        and not one more.

        Returns the polygon and how many pixels it covers, or (None, 0) when
        there is no usable grid to snap to."""
        px, py = self.pixel_crs
        ox, oy = self.origin
        if px <= 0 or py <= 0 or len(points) < 2:
            return None, 0
        width_px = max(1, int(width_px))

        # the trace in pixels of the raster: column to the right, row down,
        # and pixel (r, c) has its centre at (c + 0.5, r + 0.5)
        path = np.array([((p.x() - ox) / px, (oy - p.y()) / py)
                         for p in points], dtype=float)
        rows, cols = line_pixels(path, width_px)
        if not len(rows):
            return None, 0

        # runs of neighbouring columns in the same row become one rectangle
        # each, instead of one rectangle per pixel: a 200 pixel trace is a few
        # hundred rectangles rather than a few thousand
        pieces = []
        starts = np.flatnonzero(np.r_[True, (rows[1:] != rows[:-1])
                                      | (cols[1:] != cols[:-1] + 1)])
        ends = np.r_[starts[1:], len(rows)] - 1
        for i, j in zip(starts.tolist(), ends.tolist()):
            r, start, prev = int(rows[i]), int(cols[i]), int(cols[j])
            # Every edge of every rectangle is "origin plus a whole
            # number of pixels", computed that one way and no other. Taking
            # the bottom of a row as "the top minus one pixel" is the same
            # number in arithmetic and not always the same double: at an
            # origin of four million and a pixel of five centimetres the two
            # differ by about half a nanometre, and rows that should share an
            # edge exactly would be left with a gap half a nanometre wide
            # between them. The union would then come back as a heap of
            # separate pieces instead of one strip, and on a thin diagonal
            # every piece would be small enough for the four pixel floor to
            # throw it away: the line would be recorded with its length and
            # its width, and the ground it claimed never painted.
            pieces.append(QgsGeometry.fromRect(QgsRectangle(
                ox + start * px, oy - (r + 1) * py,
                ox + (prev + 1) * px, oy - r * py)))
        return QgsGeometry.unaryUnion(pieces), int(len(rows))

    def regrid(self, rect):
        """The same square moved so that it sits on the grid again, keeping the
        size in pixels it already had."""
        px, py = self.pixel_crs
        ox, oy = self.origin
        if px <= 0 or py <= 0:
            return QgsGeometry.fromRect(rect), 0
        wide = max(1, int(round(rect.width() / px)))
        tall = max(1, int(round(rect.height() / py)))
        col = int(round((rect.xMinimum() - ox) / px))
        row = int(round((oy - rect.yMaximum()) / py))
        return QgsGeometry.fromRect(QgsRectangle(
            ox + col * px, oy - (row + tall) * py,
            ox + (col + wide) * px, oy - row * py)), wide

    def point_fits(self, frame, point, n):
        """Whether a point of footprint n would label only ground inside the
        frame. See footprint_fits for the rule."""
        return footprint_fits(frame, point.x(), point.y(), n, self.origin,
                              self.pixel_crs)


#  The pixels a traced line claims
# =====================================================================
def line_pixels(path, width):
    """The pixels of a line width pixels wide, as two sorted arrays (rows and
    columns, by row and then by column).

    path is the trace as an array of (column, row) points in pixels of the
    raster, a pixel's centre being at its index plus a half.

    What "width pixels wide" means: each stretch of the trace is a rectangle
    whose sides are width pixels apart, measured at a right angle to the
    stretch, so the ground it claims is width times its length in pixels
    whatever the direction. Only the two ends of the whole trace are squared
    off, half a width beyond the first and the last point, which is what the
    square nib of the brush always did. Inside the trace two stretches meet
    with a round join: a disc half a width in radius on the vertex fills the
    wedge the turn leaves on its outer side. Nothing is then ever farther from
    the trace than half a width, bar the corners of the two ends. Squaring off
    every stretch instead would put a rotated square on each vertex, and a
    freehand trace, which is many short stretches whose directions wobble,
    would come out wider than it was asked to be.

    A pixel belongs to the line when its centre is inside, the rule every
    other mark is burned with. A pixel centre that falls exactly on a side
    belongs to the line on the upper and the left side and not on the lower
    and the right one. The sides are told apart with a margin of a millionth
    of a pixel, because the trace is worked out from map coordinates that are
    not exact to the last bit.

    A trace that runs exactly along a row or a column is the one case that
    is not worked out from its rectangle. It is what it was before lines were
    measured at a right angle: the cells it crosses, grown to the width, so
    that every row and column drawn earlier comes out the same pixel for
    pixel. An even width cannot be centred on pixels and leans up or to the
    left, from the cell the trace is in. Anywhere else an even width leans to
    the pixels nearest to the trace, and by half a pixel up or to the left when
    the trace runs exactly through the pixel centres.

    At one pixel across, a stretch that is not along a row or a column would
    touch itself only at the corners of its pixels, and a line is a thing that
    holds together edge to edge, so the pixels that are missing for that are
    added, each the one nearest to the trace. That is the one place where a
    line is wider than it was asked to be (up to 1.41 pixels at 45 degrees,
    which is the thinnest an unbroken line can be there). A line of two
    pixels or more is never in that case."""
    path = np.asarray(path, dtype=float)
    if not len(path):
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    half = width / 2.0
    tie = 1e-6
    # the same strip whichever way the hand went
    if len(path) > 1 and (tuple(path[-1]) < tuple(path[0])):
        path = path[::-1]
    # a repeated point is no stretch: its direction is not defined, and a
    # click twice on the same spot must not turn the line
    if len(path) > 1:
        far = np.r_[True, np.hypot(*np.diff(path, axis=0).T) > 1e-9]
        path = path[far]

    if np.ptp(path[:, 1]) <= 1e-9:
        return _cells_in_line(path, width, 1)
    if np.ptp(path[:, 0]) <= 1e-9:
        return _cells_in_line(path, width, 0)

    keys = []
    last = len(path) - 2
    for k in range(len(path) - 1):
        a, b = path[k], path[k + 1]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        nx, ny = -uy, ux
        if nx < -1e-9 or (abs(nx) <= 1e-9 and ny < 0):
            nx, ny = -nx, -ny
        lo = -half if k == 0 else 0.0
        hi = length + half if k == last else length
        # a long stretch is taken a piece at a time so that a slanted line
        # across a big raster never needs the whole box that holds it in
        # memory
        t0 = lo
        while t0 < hi:
            t1 = min(t0 + 256.0, hi)
            xs = [a[0] + ux * t0, a[0] + ux * t1]
            ys = [a[1] + uy * t0, a[1] + uy * t1]
            c0 = int(math.floor(min(xs) - half)) - 1
            c1 = int(math.ceil(max(xs) + half)) + 1
            r0 = int(math.floor(min(ys) - half)) - 1
            r1 = int(math.ceil(max(ys) + half)) + 1
            dx = (np.arange(c0, c1 + 1) + 0.5 - a[0])[None, :]
            dy = (np.arange(r0, r1 + 1) + 0.5 - a[1])[:, None]
            along = dx * ux + dy * uy
            across = dx * nx + dy * ny
            inside = ((along > t0 - tie) & (along < t1 - tie)
                      & (across > -half - tie) & (across < half - tie))
            r, c = np.nonzero(inside)
            keys.append(_pixel_key(r + r0, c + c0))
            t0 = t1
    for v in path[1:-1]:
        c0, c1 = int(math.floor(v[0] - half)) - 1, int(math.ceil(v[0] + half)) + 1
        r0, r1 = int(math.floor(v[1] - half)) - 1, int(math.ceil(v[1] + half)) + 1
        dx = (np.arange(c0, c1 + 1) + 0.5 - v[0])[None, :]
        dy = (np.arange(r0, r1 + 1) + 0.5 - v[1])[:, None]
        r, c = np.nonzero(dx * dx + dy * dy < half * half - tie)
        keys.append(_pixel_key(r + r0, c + c0))
    keys = np.unique(np.concatenate(keys))
    if width == 1:
        keys = _close_corners(keys, path)
    return _pixel_unkey(keys)


def _cells_in_line(path, width, axis):
    """A trace along a row (axis 1: every point has the same row) or along a
    column (axis 0), as it was drawn before lines were measured at a right
    angle: the cells from the first to the last, each grown to the width."""
    low = -(width // 2)
    steps = np.arange(low, low + width)
    across = int(math.floor(path[0, axis]))
    along = np.arange(int(math.floor(path[:, 1 - axis].min())),
                      int(math.floor(path[:, 1 - axis].max())) + 1)
    along = np.unique((along[:, None] + steps[None, :]).ravel())
    across = across + steps
    if axis == 1:
        rows, cols = np.repeat(across, len(along)), np.tile(along, len(across))
    else:
        rows, cols = np.tile(along, len(across)), np.repeat(across, len(along))
    return _pixel_unkey(np.unique(_pixel_key(rows, cols)))


_KEY_SHIFT = 1 << 32
_KEY_OFFSET = 1 << 30


def _pixel_key(rows, cols):
    """One integer for a pixel, in the order rows then columns, so that
    sorting the keys sorts the pixels and sets of them can be told apart
    without a Python loop."""
    return ((np.asarray(rows, dtype=np.int64) + _KEY_OFFSET) * _KEY_SHIFT
            + (np.asarray(cols, dtype=np.int64) + _KEY_OFFSET))


def _pixel_unkey(keys):
    return ((keys // _KEY_SHIFT) - _KEY_OFFSET,
            (keys % _KEY_SHIFT) - _KEY_OFFSET)


def _has_pixel(keys, rows, cols):
    want = _pixel_key(rows, cols)
    at = np.searchsorted(keys, want)
    at[at == len(keys)] = 0
    return keys[at] == want


def _close_corners(keys, path):
    """Pixels added so that no two touch only at a corner: of the two that
    would join them, the one whose centre is nearer to the trace."""
    a, b = path[:-1], path[1:]
    if not len(a):
        return keys
    for _ in range(4):
        rows, cols = _pixel_unkey(keys)
        add = []
        # the contacts that run down to the right, then those down to the
        # left: (r, c) with (r + 1, c + sign) and neither pixel between them
        for sign in (1, -1):
            lone = (_has_pixel(keys, rows + 1, cols + sign)
                    & ~_has_pixel(keys, rows, cols + sign)
                    & ~_has_pixel(keys, rows + 1, cols))
            if not lone.any():
                continue
            r, c = rows[lone], cols[lone]
            one = np.stack([r, c + sign], axis=1)
            two = np.stack([r + 1, c], axis=1)
            take_one = (_near_trace(one, a, b) <= _near_trace(two, a, b))
            add.append(_pixel_key(np.where(take_one, one[:, 0], two[:, 0]),
                                  np.where(take_one, one[:, 1], two[:, 1])))
        if not add:
            break
        keys = np.unique(np.concatenate([keys] + add))
    return keys


def _near_trace(pixels, a, b):
    """How far the centres of pixels (row, column pairs) are from the trace
    whose stretches run from a to b."""
    out = np.empty(len(pixels))
    step = max(1, 2000000 // max(len(a), 1))
    ab = b - a
    sq = np.maximum((ab * ab).sum(axis=1), 1e-18)
    for i in range(0, len(pixels), step):
        p = pixels[i:i + step]
        dx = (p[:, 1] + 0.5)[:, None] - a[None, :, 0]
        dy = (p[:, 0] + 0.5)[:, None] - a[None, :, 1]
        f = np.clip((dx * ab[None, :, 0] + dy * ab[None, :, 1]) / sq,
                    0.0, 1.0)
        out[i:i + step] = np.hypot(dx - f * ab[None, :, 0],
                                   dy - f * ab[None, :, 1]).min(axis=1)
    return out


#  Number boxes measured in pixels of the grid
# =====================================================================
def spin_decimals(px):
    """How many decimals a box stepping by one pixel of px needs: enough for
    the pixel to read within one percent of itself, and never fewer than
    two. Two decimals made the radius minimum of a 2 mm raster read 0.00 m,
    and the box rounds every value it holds to what it shows."""
    px = abs(float(px or 0.0))
    if not px or px != px or px == float("inf"):
        return 2
    for d in range(2, 9):
        if abs(round(px, d) - px) <= 0.01 * px:
            return d
    return 8


def spin_suffix(geometry):
    """What the number boxes of a campaign count in: metres when it has a
    coordinate system, pixels for a picture, whose units are its pixels, and
    the units of its world file for a picture placed by one without a
    system, whose units are nobody's metres."""
    try:
        if geometry.crs.isValid():
            return " m"
        px, py = geometry.pixel_crs
    except Exception:
        return " m"
    if abs(px - 1.0) < 1e-9 and abs(py - 1.0) < 1e-9:
        return " px"
    return " u"


def fit_spin(box, px, low_px, high_px, ceiling, value_px, suffix=" m"):
    """A number box of lengths, fitted to the pixel it is counted in.

    Limits fixed for a 5 cm orthophoto (a radius of 200 m at most, a step of
    one metre, a frame side from half a metre) fail on other grids. On a 250 m
    MODIS grid the radius minimum would be above its maximum and the brush
    locked at one pixel; at 30 m it could not pass seven pixels; at 1 cm
    every click of an arrow would move it a hundred pixels; at 2 mm the
    smallest frame would be 250 pixels. So the box steps by one pixel, goes
    from low_px pixels to high_px pixels or the ceiling in metres, whichever
    is more, shows as many decimals as the pixel needs, and starts at
    value_px pixels."""
    px = abs(float(px or 0.0))
    if not px or px != px or px == float("inf"):
        px = 1.0
    box.setDecimals(spin_decimals(px))
    box.setRange(low_px * px, max(float(ceiling), high_px * px))
    box.setSingleStep(px)
    box.setSuffix(suffix)
    box.setValue(value_px * px)


# How far inside the frame a footprint has to be, in pixels. A footprint that
# meets the frame edge exactly is inside it, but the two edges are the same
# number computed two ways and need not be the same double. A thousandth of a
# pixel is the same allowance Check gives a frame on the grid.
FOOTPRINT_SLACK = 1e-3


def footprint_box(x, y, n, origin, pixel):
    """The square of whole pixels a point of footprint n stands for, as
    (xmin, ymin, xmax, ymax), or None with no grid.

    It is the square the export burns, built the same way the Stencil in
    rasters.py builds it: the pixel holding the point is found first and the
    square is grown n // 2 pixels from it on every side, so it is n pixels
    across wherever inside the pixel the click landed. The two have to agree,
    because this is what decides whether a point may be dropped in a frame,
    and that is what decides what the mask holds."""
    ox, oy = origin
    px, py = abs(pixel[0]), abs(pixel[1])
    if px <= 0 or py <= 0:
        return None
    try:
        n = int(n or 1)
    except (TypeError, ValueError):
        n = 1
    n = max(1, n)
    col = int(math.floor((x - ox) / px))
    row = int(math.floor((oy - y) / py))
    half = n // 2
    return (ox + (col - half) * px, oy - (row + half + 1) * py,
            ox + (col + half + 1) * px, oy - (row - half) * py)


def footprint_fits(frame, x, y, n, origin, pixel):
    """Whether every pixel of a point's footprint lies inside the frame.

    The rule for points in a tiled campaign. An area or a line is clipped to
    the frame when it is drawn, so nothing outside a frame is ever labelled.
    A point cannot be clipped: the export grows it into its whole square, on
    the whole raster, whatever frame it was dropped in. So a point whose
    square would reach past the frame edge is refused instead, and the frame
    then bounds what a point labels exactly as it bounds a stroke. With no
    grid to build a square on, the point itself has to be in the frame."""
    if frame is None or frame.isEmpty():
        return False
    square = footprint_box(x, y, n, origin, pixel)
    if square is None:
        return frame.intersects(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
    sx = FOOTPRINT_SLACK * abs(pixel[0])
    sy = FOOTPRINT_SLACK * abs(pixel[1])
    inner = QgsGeometry.fromRect(QgsRectangle(
        square[0] + sx, square[1] + sy, square[2] - sx, square[3] - sy))
    return frame.contains(inner)


def on_edge(value):
    """A coordinate that should fall exactly on a pixel edge misses it by a
    billionth, because it was obtained subtracting two numbers in the millions
    and a double has no room left down there. Left alone, ceil then turns a
    frame of 200 pixels into a cutout of 201 and the pieces stop stacking."""
    whole = round(value)
    return whole if abs(value - whole) < 1e-6 else value


def snap(gt, size, rect, clip=True):
    """The window of a rectangle on a raster grid, clipped to the raster.

    Without the clipping the window keeps the size the rectangle asked for even
    where it hangs over the edge, and the part outside comes back as nodata.
    That is what a dataset of equally sized pieces needs at the border of the
    survey, where the clipped window would be a few pixels narrower and the
    piece would no longer stack with the others.

    Whichever way the grid runs. A raster written north-down, with a
    positive pixel height, has its first row at the bottom: the top of the
    rectangle is then the higher row and the bottom the lower one, and
    taking them as they came gave a window of negative height. Correct said
    "the stroke falls outside the map" for every stroke on such a map, and
    Cutouts the same of every click. The two edges are put in order first,
    rows and columns alike."""
    xa = on_edge((rect.xMinimum() - gt[0]) / gt[1])
    xb = on_edge((rect.xMaximum() - gt[0]) / gt[1])
    ya = on_edge((rect.yMaximum() - gt[3]) / gt[5])
    yb = on_edge((rect.yMinimum() - gt[3]) / gt[5])
    c0, c1 = int(np.floor(min(xa, xb))), int(np.ceil(max(xa, xb)))
    r0, r1 = int(np.floor(min(ya, yb))), int(np.ceil(max(ya, yb)))
    if clip:
        c0, c1 = max(0, min(c0, size[0])), max(0, min(c1, size[0]))
        r0, r1 = max(0, min(r0, size[1])), max(0, min(r1, size[1]))
    return c0, r0, c1 - c0, r1 - r0


def ground_rows(measure, gt, nx, ny, centre_m2):
    """The ground area of one pixel in every row of the map, in m2, or None
    when one value serves the whole map.

    A pixel of a map in degrees, or in Web Mercator, is not the same ground
    at the top and at the bottom: the further from the equator, the less of
    the ground a pixel covers. The area of the pixels a stroke changed would
    be the pixel at the middle of the map times their number, which comes out
    1.6 times too much at 55 to 60 north on a map of 0 to 60 north, and 0.87
    times at the equator. Measured here on the ellipsoid, as the area of the
    stroke is, at the middle column of a sample of rows and followed between
    them, then scaled so that the middle row is the pixel the manifest holds.

    None when the top and the bottom of the map measure alike, within a
    ten thousandth, which is every map in a metric system of its own (UTM,
    a national grid): its numbers are then the ones they always were.

    measure is a QgsDistanceArea set on the map's system. Correct, the
    Dataset card and Model vs corrected all ask here, so that the area they
    report for the changed pixels is the one the log holds."""
    if measure is None or ny < 2 or not centre_m2:
        return None
    x0 = gt[0] + (nx // 2) * gt[1]

    def one(row):
        y0 = gt[3] + row * gt[5]
        rect = QgsRectangle(min(x0, x0 + gt[1]), min(y0, y0 + gt[5]),
                            max(x0, x0 + gt[1]), max(y0, y0 + gt[5]))
        return abs(float(measure.measureArea(QgsGeometry.fromRect(rect))))

    try:
        top, mid, bottom = one(0), one(ny // 2), one(ny - 1)
        if not (mid > 0 and np.isfinite([top, mid, bottom]).all()):
            return None
        if max(abs(top - mid), abs(bottom - mid)) <= 1e-4 * mid:
            return None
        rows = np.unique(np.linspace(0, ny - 1, min(ny, 257))
                         .round().astype(np.int64))
        areas = np.array([one(int(r)) for r in rows])
    except Exception as err:
        log("the area of a pixel could not be measured row by row, so one "
            "value is used for the whole map: %s" % err)
        return None
    if not (areas > 0).all():
        return None
    return np.interp(np.arange(ny), rows, areas) * (centre_m2 / mid)


def ground_rows_of(crs_text, gt, nx, ny, centre_m2):
    """ground_rows for a map known by its system (a WKT or the text a
    manifest holds), its geotransform and its size alone, as a report reads
    it from the files: measured on the same ellipsoid Geometry would use.
    None when there is no valid system."""
    crs = crs_from_text(crs_text)
    if not crs.isValid() or not centre_m2:
        return None
    crs = named_crs(crs, (gt[0], gt[3]))
    measure = QgsDistanceArea()
    measure.setSourceCrs(crs, QgsProject.instance().transformContext())
    measure.setEllipsoid(ellipsoid_for(crs))
    return ground_rows(measure, gt, nx, ny, centre_m2)


def window_transform(gt, col, row):
    """The geotransform of a window, with the rotation terms forced to zero."""
    return (gt[0] + col * gt[1], gt[1], 0.0, gt[3] + row * gt[5], 0.0, gt[5])


def aligned(a, b):
    """True when b sits on the same grid as a: same pixel size, no rotation,
    and an origin that differs by a whole number of pixels."""
    if abs(a[1] - b[1]) > 1e-12 or abs(a[5] - b[5]) > 1e-12:
        return False
    if abs(a[2]) + abs(a[4]) + abs(b[2]) + abs(b[4]) > 0:
        return False
    dx = (b[0] - a[0]) / a[1]
    dy = (b[3] - a[3]) / a[5]
    return abs(dx - round(dx)) < 1e-6 and abs(dy - round(dy)) < 1e-6


def north_up(gt, rows):
    """The grid of a raster stored bottom row first (a positive pixel height),
    described from its top row down: the same pixels, the same ground, the
    rows counted the other way. A grid that is rotated is returned as it is.

    A north-down raster that sets the grid of the cutouts would get every
    click refused as "outside the first layer" without this: its row of the
    top edge is the larger number, so the window would come out with a
    negative height."""
    if gt[5] <= 0 or gt[2] or gt[4]:
        return tuple(gt)
    return (gt[0], gt[1], 0.0, gt[3] + rows * gt[5], 0.0, -gt[5])


def north_up_of(ds):
    """The grid of a dataset, top row first when it is stored bottom row
    first. A file with no geotransform at all is not stored any way round:
    it is on the grid QGIS draws it on, rasters.pixel_grid, y = -row. GDAL
    hands it (0, 1, 0, 0, 0, 1) instead, rows going up, and a cutout of a
    picture with no georeference was "outside the first layer" or, on a
    click, cut beside the square clicked."""
    return north_up(pixel_grid(ds), ds.RasterYSize)


def resampling_for(role, coarser):
    """The way a layer is resampled onto a grid it does not sit on.

    Classes never get a value they do not hold: the class most of the ground
    under a larger pixel has (mode), or the one under its centre (nearest).
    Nearest alone, onto a pixel forty times larger, took one small pixel out
    of 1600 and gave a ten metre pixel the class of a patch at its centre
    while the class around it covered nine tenths of it. An image is
    averaged onto a larger pixel and interpolated onto a smaller one: by
    nearest a pattern finer than the new pixel comes out as stripes that are
    not on the ground (aliasing), and a surface read onto a finer grid as
    steps."""
    if role == "classes":
        return "mode" if coarser else "near"
    return "average" if coarser else "bilinear"


def read_on_grid(ds, bands, gt, w, h, role="classes", wkt=None,
                 src_wkt=None, pad_nan=False):
    """The given bands over the given window, and how they were read.

    An exact read when the raster is on that grid; otherwise the raster is
    resampled onto it, by resampling_for(role), each band on its own so that
    each keeps its own nodata (not the nodata of the first band for all of
    them). wkt, given only for a layer in another coordinate system
    than the grid, is the system of the grid: the layer is then reprojected
    onto it. src_wkt is the system of the layer when its file does not say
    it, as when the system was set in QGIS. A window that hangs over the edge
    still comes back at the full size.

    Where there is no raster under the window, a band with a nodata gets its
    nodata and a band without one gets NaN, in both reads: the caller can
    tell padding from data. Zeros would be black pixels in an image and look
    like ground.

    pad_nan leaves NaN where there is no raster under the window even for a
    band that has a nodata: a map of classes cut with an ignore value tells
    the padding, its own nodata and its codes apart, and turns the first two
    into the ignore value whatever the band declares.

    Returns the array, the nodata of each band, and the resampling used
    ("" for the exact read)."""
    own = pixel_grid(ds)
    nodata = [ds.GetRasterBand(b).GetNoDataValue() for b in bands]
    flip = False
    if wkt is None and not aligned(gt, own) and own[5] > 0:
        # rows stored bottom first: the same grid, read and turned over
        up = north_up_of(ds)
        if up != tuple(own) and aligned(gt, up):
            own, flip = up, True
    if wkt is None and aligned(gt, own):
        c = int(round((gt[0] - own[0]) / own[1]))
        r = int(round((gt[3] - own[3]) / own[5]))
        out = np.full((len(bands), h, w), np.nan, np.float64)
        c0, r0 = max(c, 0), max(r, 0)
        c1, r1 = min(c + w, ds.RasterXSize), min(r + h, ds.RasterYSize)
        if c1 > c0 and r1 > r0:
            for i, b in enumerate(bands):
                if flip:
                    block = ds.GetRasterBand(b).ReadAsArray(
                        c0, ds.RasterYSize - r1, c1 - c0, r1 - r0)[::-1]
                else:
                    block = ds.GetRasterBand(b).ReadAsArray(
                        c0, r0, c1 - c0, r1 - r0)
                out[i, r0 - r:r1 - r, c0 - c:c1 - c] = block
        for i, nd in enumerate(nodata):
            if nd is not None and not pad_nan:
                out[i] = np.where(np.isnan(out[i]), nd, out[i])
        return out, nodata, ""
    tops = (gt[3], gt[3] + h * gt[5])
    bounds = (gt[0], min(tops), gt[0] + w * gt[1], max(tops))
    # Coarser is decided on the ground: how many pixels of the layer one
    # pixel of the grid holds, with the layer's own pixel measured in the
    # system of the grid when it is reprojected.
    mine = abs(own[1] * own[5] - own[2] * own[4])
    if wkt:
        try:
            guess = gdal.Warp("", ds, format="VRT", dstSRS=wkt,
                              **({"srcSRS": src_wkt} if src_wkt else {}))
            g2 = guess.GetGeoTransform()
            mine = abs(g2[1] * g2[5] - g2[2] * g2[4])
            guess = None
        except Exception:
            mine = 0.0
    coarser = bool(mine) and abs(gt[1] * gt[5]) > mine * 1.0002
    method = resampling_for(role, coarser)
    out = np.full((len(bands), h, w), np.nan, np.float64)
    for i, b in enumerate(bands):
        one = gdal.Translate("", ds, format="VRT", bandList=[b])
        options = {"format": "MEM", "outputBounds": bounds, "width": w,
                   "height": h, "resampleAlg": method,
                   "outputType": gdal.GDT_Float64, "dstNodata": float("nan")}
        if nodata[i] is not None:
            options["srcNodata"] = nodata[i]
        if wkt:
            options["dstSRS"] = wkt
            if src_wkt:
                options["srcSRS"] = src_wkt
        mem = gdal.Warp("", one, **options)
        out[i] = mem.GetRasterBand(1).ReadAsArray().astype(np.float64)
        mem = one = None
        if nodata[i] is not None and not pad_nan:
            out[i] = np.where(np.isnan(out[i]), nodata[i], out[i])
    return out, nodata, method
