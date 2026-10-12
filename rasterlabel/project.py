"""rasterlabel.project

What the QGIS project is holding right now.
"""
import os

from osgeo import osr
from qgis.PyQt.QtGui import QColor
from qgis.core import (Qgis, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsDistanceArea, QgsPointXY,
                       QgsProject, QgsRasterLayer)

from .constants import UNIT_DEGREES, UNIT_METRES
from .compat import iface


def canvas():
    return iface.mapCanvas()


def is_vertex_tool(tool):
    """Whether a map tool is QGIS's own vertex tool.

    It is a class of the QGIS application, not of the libraries a plugin is
    given, so Python only ever sees it as one of its bases. Qt still knows
    its real name, and that name is the same whether it edits every layer or
    the active one only."""
    if tool is None:
        return False
    try:
        return tool.metaObject().className() == "QgsVertexTool"
    except Exception:
        return False


def rgba(colour, alpha=255):
    """QgsFillSymbol.createSimple does not understand '#rrggbbaa': it wants
    'r,g,b,a'. Handing it eight-digit hex makes QGIS discard the colour and
    pick a random one instead."""
    c = QColor(colour)
    return "%d,%d,%d,%d" % (c.red(), c.green(), c.blue(), alpha)


#  Rasters of the project
# =====================================================================
def project_rasters(need_crs=True):
    """The rasters loaded in the project.

    Requiring a CRS always would quietly shut the door on every picture that
    is not a survey: a scan, a photograph, a frame grab.
    Those carry no coordinate reference system, QGIS gives them a pixel grid
    and nothing else, and there is no reason the annotation of one should be
    harder than the annotation of an orthomosaic. Where a CRS is genuinely
    needed, for cutting a square of so many metres, the caller asks for it."""
    out = [l for l in QgsProject.instance().mapLayers().values()
           if isinstance(l, QgsRasterLayer) and l.isValid()
           and (l.crs().isValid() or not need_crs)]
    out.sort(key=lambda l: l.name().lower())
    return out


def reopen_rasters_of(path):
    """Every raster layer of the project on the file at path, made to let go
    of the file and open it again; the layers, in a list.

    QGIS keeps what it learns about a picture, the statistics of its bands
    for a start, in the .aux.xml beside it, and writes the whole of that
    file back when the layer lets go of it. Anything written there by
    anybody else in the meantime is lost: a coordinate system written for a
    picture while QGIS had it open was gone the next time QGIS closed."""
    want = os.path.normcase(os.path.abspath(str(path).split("|")[0]))
    out = []
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsRasterLayer):
            continue
        here = layer.source().split("|")[0]
        try:
            same = os.path.normcase(os.path.abspath(here)) == want
        except Exception:
            same = False
        if not same:
            continue
        # The provider closes the file, writing back what it held, and opens
        # it again; the layer, its style and its system are left as they are.
        try:
            layer.dataProvider().reloadData()
            out.append(layer)
        except Exception:
            pass
    return out


def in_tree_order(layers):
    """The same layers as the Layers panel stacks them, top first.

    project_rasters() sorts by name, which is right for a list to pick from
    and wrong wherever the order means something. Cutouts takes its pixel grid
    from the first layer it is given, and with the names deciding, a layer
    called "72_mappa" always came before one called "aragona" whatever the
    user had put on top. A layer the tree does not hold, or a project with no
    tree to ask, keeps the place it had in the list it came in."""
    layers = list(layers)
    try:
        ids = [node.layerId()
               for node in QgsProject.instance().layerTreeRoot().findLayers()]
    except Exception:
        return layers
    rank = {lid: i for i, lid in enumerate(ids)}
    later = len(rank)
    order = sorted(range(len(layers)),
                   key=lambda i: (rank.get(layers[i].id(), later), i))
    return [layers[i] for i in order]


def proposed_raster(rasters, chosen=None):
    """The raster a window proposes first, out of the list it will show.

    The list is by name, so the first of it is whichever raster happens to
    sort first, and "press Ok straight away" made a campaign on the grid of
    that one: five centimetres where the picture on screen was ten, for good,
    because the grid of a campaign is not changed afterwards. What the person
    has in hand is better evidence: the layer selected in the Layers panel,
    then the one the panel's own box was set to by hand, then the one on top
    of the tree. None for an empty list."""
    rasters = list(rasters)
    if not rasters:
        return None
    try:
        active = iface.activeLayer() if iface is not None else None
    except Exception:
        active = None
    if active is not None:
        for l in rasters:
            if l.id() == active.id():
                return l
    # the box of the panel starts on the first by name; a different one in it
    # was put there by somebody
    if chosen is not None and chosen != rasters[0].id():
        for l in rasters:
            if l.id() == chosen:
                return l
    return in_tree_order(rasters)[0]


def project_ellipsoid():
    """The ellipsoid to measure on, never "none".

    A QGIS project whose ellipsoid is set to None/Planimetric answers the
    string "NONE", which is perfectly truthy, so "or "WGS84"" let it through
    and QgsDistanceArea fell back to plane arithmetic in the units of the
    source system. On a projected campaign that is metres and no harm done.
    On a campaign in degrees it means every length and every area, the size of
    a pixel included, comes out about a hundred thousand times too small, and
    the frame the panel then proposes is fifty kilometres across."""
    try:
        name = (QgsProject.instance().ellipsoid() or "").strip()
    except Exception:
        name = ""
    if not name or name.upper() in ("NONE", "PLANIMETRIC"):
        return "WGS84"
    return name


def ellipsoid_for(crs):
    """The ellipsoid to measure in this system on: the project's when the
    system is a real one, and "NONE", the plane, when there is no system.

    QgsDistanceArea given an ellipsoid and no valid system reads the
    coordinates as degrees. On a photograph, whose y runs down to minus the
    number of rows, or on a world file in metres, that gave NaN for every
    area and length; on a small picture whose coordinates stayed inside
    ninety, a 60 x 40 pixel polygon of thirteen million square kilometres.
    On the plane a picture is measured in its own units, which is what its
    manifest calls metres."""
    try:
        valid = crs is not None and crs.isValid()
    except Exception:
        valid = False
    return project_ellipsoid() if valid else "NONE"


def pixel_on_the_ground(layer):
    """Pixel size in metres, measured at the centre of the raster.

    The declared size is in the units of the coordinate system: in geographic
    coordinates those are degrees, and using them as metres produces wrong
    numbers that look right."""
    e = layer.extent()
    return pixel_at(layer.crs(), (e.center().x(), e.center().y()),
                    layer.rasterUnitsPerPixelX(), layer.rasterUnitsPerPixelY())


def pixel_of(crs, gt, size):
    """The same measure for a raster known only by its header: the geotransform
    and the size GDAL reads off the file, with no layer loaded. A correction
    opened from its folder has its working copy and nothing else."""
    nx, ny = size
    dx, dy = abs(gt[1]), abs(gt[5])
    centre = (gt[0] + gt[1] * nx / 2.0, gt[3] + gt[5] * ny / 2.0)
    return pixel_at(crs, centre, dx, dy)


def pixel_at(crs, centre, dx, dy):
    """A pixel of dx by dy units, measured on the ground at centre. A system
    that cannot be measured, or none at all, gives the units themselves: the
    case of a picture, which Geometry and Check already accept."""
    if crs is None or not crs.isValid():
        return dx, dy
    cx, cy = centre
    m = QgsDistanceArea()
    m.setSourceCrs(crs, QgsProject.instance().transformContext())
    m.setEllipsoid(project_ellipsoid())
    try:
        px = m.measureLine(QgsPointXY(cx, cy), QgsPointXY(cx + dx, cy))
        py = m.measureLine(QgsPointXY(cx, cy), QgsPointXY(cx, cy + dy))
        if px > 0 and py > 0:
            return px, py
    except Exception:
        pass
    return dx, dy


def ground_measure(crs):
    """A ruler for lengths in metres in this system, on the project's
    ellipsoid. Cutouts measures the side of what it cut with one, in the
    system of the first layer: there may be no campaign to lend its own.
    A layer with no system gets a ruler on the plane, in its own units: on
    the ellipsoid it measured a picture's side as NaN."""
    m = QgsDistanceArea()
    try:
        m.setSourceCrs(crs, QgsProject.instance().transformContext())
        m.setEllipsoid(ellipsoid_for(crs))
    except Exception:
        pass
    return m


#  Coordinate systems
# =====================================================================
#
# Everything below decides by the units a system counts in, never by its kind
# or by whether it has a code. An orthomosaic can declare WGS 84 with a
# TOWGS84 of seven zeros. GDAL hands that to QGIS as a BOUNDCRS: WGS 84,
# bound to WGS 84 by a transformation that does nothing. QGIS 3.36 gives it no
# EPSG code, so a manifest would keep "" for it and the log say "drawing in
# ?", and isGeographic() answers False, because a bound system is not a
# geographic one by type. Its coordinates are degrees all the same. Reading
# the False as metres would turn the round brush of half a metre into a
# circle half a degree across: the preview would cover the screen and one
# click fill the frame.
def crs_units(crs):
    """What one unit of this system is, as QGIS says it, or None."""
    try:
        return crs.mapUnits()
    except Exception:
        return None


def in_degrees(crs):
    """True when the coordinates of this system are degrees. mapUnits() looks
    through a binding that isGeographic() stops at; a QGIS that cannot say
    what its units are called is asked the old question instead."""
    if crs is None or not crs.isValid():
        return False
    units = crs_units(crs)
    if units is not None and UNIT_DEGREES is not None:
        return units == UNIT_DEGREES
    return bool(crs.isGeographic())


def in_metres(crs):
    """True when one unit of this system is one metre."""
    if crs is None or not crs.isValid():
        return False
    units = crs_units(crs)
    if units is not None and UNIT_METRES is not None:
        return units == UNIT_METRES
    return not crs.isGeographic()


def crs_wkt(crs):
    """The whole definition, in the WKT that keeps everything: WKT2 where this
    QGIS has it, so a binding and its transformation survive the round trip."""
    for owner, names in ((Qgis, ("CrsWktVariant", "Preferred")),
                         (QgsCoordinateReferenceSystem, ("WKT_PREFERRED",))):
        variant = owner
        for name in names:
            variant = getattr(variant, name, None)
        if variant is not None:
            try:
                return crs.toWkt(variant)
            except Exception:
                pass
    return crs.toWkt()


def crs_from_text(text):
    """The system a manifest names. It holds an EPSG code, or a whole WKT for
    a system the registry does not know, or "" for a raster with none: the
    manifests written by RasterLabel 1.0 hold only the first and the last."""
    text = (text or "").strip()
    if not text:
        return QgsCoordinateReferenceSystem()
    if "[" in text:
        make = getattr(QgsCoordinateReferenceSystem, "fromWkt", None)
        if make is not None:
            return make(text)
        crs = QgsCoordinateReferenceSystem()
        crs.createFromWkt(text)
        return crs
    return QgsCoordinateReferenceSystem(text)


def crs_to_text(crs):
    """What the manifest keeps of a system: its code when it has one, the
    whole WKT when it has none, and "" only when there is no system at all.

    Keeping authid() and nothing else would write a perfectly good system
    without a code as "", which is what a photograph with no coordinate
    system writes. Everything that read the manifest afterwards would take
    the orthomosaic for a picture."""
    if crs is None or not crs.isValid():
        return ""
    return crs.authid() or crs_wkt(crs)


_NAMED_CRS = {}


def named_crs(crs, near=None):
    """The same system under its EPSG name, when it has one.

    A system with a code is handed back as it is. One without is put to PROJ,
    the identification gdalsrsinfo runs, and a registered system is taken only
    when PROJ is certain of it AND moving a point from one to the other leaves
    the point where it was. The second test is what keeps a WGS 84 bound by a
    real datum shift from being called EPSG:4326: the name would be shorter
    and every polygon would land metres away from the picture. near, in the
    units of crs, is where that point is taken, the site itself when known.
    Anything that goes wrong hands back the system unchanged."""
    if crs is None or not crs.isValid():
        return crs
    try:
        if crs.authid():
            return crs
        wkt = crs_wkt(crs)
    except Exception:
        return crs
    key = (wkt, tuple(near) if near is not None else None)
    if key in _NAMED_CRS:
        return _NAMED_CRS[key]
    found = crs
    try:
        srs = osr.SpatialReference()
        srs.ImportFromWkt(wkt)
        matches = srs.FindMatches() or []
    except Exception:
        matches = []
    for match, confidence in matches:
        if confidence < 100:
            continue
        try:
            code = "%s:%s" % (match.GetAuthorityName(None),
                              match.GetAuthorityCode(None))
            candidate = QgsCoordinateReferenceSystem(code)
        except Exception:
            continue
        if candidate.isValid() and same_ground(crs, candidate, near):
            found = candidate
            break
    _NAMED_CRS[key] = found
    return found


def same_ground(a, b, near=None):
    """True when a point of a, moved into b, has the same coordinates there:
    two names for one system. Asked at near when given, otherwise in the
    middle of the area b is meant for."""
    if crs_units(a) != crs_units(b):
        return False
    ctx = QgsProject.instance().transformContext()
    try:
        if near is not None:
            point = QgsPointXY(float(near[0]), float(near[1]))
        else:
            middle = b.bounds().center()
            point = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem("EPSG:4326"), a, ctx).transform(
                    QgsPointXY(middle.x(), middle.y()))
        moved = QgsCoordinateTransform(a, b, ctx).transform(point)
    except Exception:
        return False
    # a billionth of a degree is about a tenth of a millimetre on the ground
    tolerance = 1e-9 if in_degrees(a) else 1e-4
    return (abs(moved.x() - point.x()) <= tolerance
            and abs(moved.y() - point.y()) <= tolerance)


# What a GeoPackage calls a table that was given no system. The two names are
# the ones the GeoPackage standard gives srs_id 0 and -1, and GDAL reads them
# back as real systems: a WGS 84 sized sphere with an unknown datum, in
# degrees, for the first. A table of a photograph with no coordinate system is
# in one of them, and so were the tables of the orthomosaic above when its
# system did not reach the GeoPackage. Neither says anything about the ground.
PLACEHOLDER_SRS = ("Undefined geographic SRS", "Undefined Cartesian SRS")


def placeholder_crs(crs):
    """True for the stand-in a GeoPackage gives a table with no system."""
    try:
        return (crs is not None and crs.isValid() and not crs.authid()
                and (crs.description() or "").strip() in PLACEHOLDER_SRS)
    except Exception:
        return False


def crs_label(crs, near=None):
    """How a system is written in the log and on the panel: its EPSG code, its
    own or the one named_crs finds, and failing both its description, so that
    nothing reads "?" while a perfectly good system is in use."""
    if crs is None or not crs.isValid():
        return "no coordinate system"
    named = named_crs(crs, near)
    try:
        if named.authid():
            return named.authid()
        return "%s (no EPSG code)" % (crs.description() or "a custom system")
    except Exception:
        return "a custom system"


#  Where a raster is, as STAC writes it
# =====================================================================
def lonlat_footprint(box, wkt):
    """The outline of a box (xmin, ymin, xmax, ymax) in longitude and
    latitude, which is the only geometry a STAC item may carry, whatever
    the data is in: (geometry, bbox), or (None, None) with no system to
    turn it with. A transform that fails raises, and the caller says so."""
    xmin, ymin, xmax, ymax = box
    corners = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]
    source = QgsCoordinateReferenceSystem()
    if wkt:
        source.createFromWkt(wkt)
    target = QgsCoordinateReferenceSystem("EPSG:4326")
    if not source.isValid():
        return None, None
    if target.isValid() and source != target:
        tr = QgsCoordinateTransform(source, target, QgsProject.instance())
        corners = [(p.x(), p.y()) for p in
                   (tr.transform(QgsPointXY(x, y)) for x, y in corners)]
    ring = [[round(x, 9), round(y, 9)] for x, y in corners]
    ring.append(ring[0])
    ring = counter_clockwise(ring)
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return ({"type": "Polygon", "coordinates": [ring]},
            [min(xs), min(ys), max(xs), max(ys)])


def counter_clockwise(ring):
    """A closed ring of [x, y] with its points turned counter-clockwise, as
    the exterior ring of a GeoJSON polygon must be (RFC 7946); the ring
    itself when it already is, or has no area to turn."""
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))
    return list(reversed(ring)) if area < 0 else ring


def wkt2_of(wkt):
    """The WKT2 (2019) text of a system given as WKT of any version, which
    is what the projection extension asks proj:wkt2 to hold; None when it
    cannot be made. The WKT1 of a QGIS layer is not that, and a reader of
    the field takes it for what it says it is."""
    try:
        srs = osr.SpatialReference()
        srs.ImportFromWkt(wkt)
        return srs.ExportToWkt(["FORMAT=WKT2_2019"]) or None
    except Exception:
        return None


def projection_of(gt, w, h, wkt, box):
    """The proj:* fields (projection extension) of a raster of this grid,
    size and system over the box (xmin, ymin, xmax, ymax)."""
    crs = QgsCoordinateReferenceSystem()
    if wkt:
        crs.createFromWkt(wkt)
    out = {"proj:shape": [int(h), int(w)],
           "proj:transform": [gt[1], gt[2], gt[0], gt[4], gt[5], gt[3],
                              0.0, 0.0, 1.0],
           "proj:bbox": [box[0], box[1], box[2], box[3]]}
    authid = named_crs(crs).authid() if crs.isValid() else ""
    if authid.upper().startswith("EPSG:") and authid[5:].isdigit():
        out["proj:epsg"] = int(authid[5:])
    else:
        out["proj:epsg"] = None
        text = wkt2_of(wkt) if wkt else None
        if text:
            out["proj:wkt2"] = text
    return out
