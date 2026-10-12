"""rasterlabel.constants

Numbers, spellings, and what this QGIS calls things.
"""
import hashlib
import os
import sys

from osgeo import ogr
from qgis.core import Qgis, QgsUnitTypes, QgsWkbTypes  # noqa: F401 (first_of())
# pyflakes reads no noqa marks, so the names first_of() looks up by their
# spelling are named once here, where a tool can see that they are meant.
_LOOKED_UP_BY_NAME = (Qgis, QgsUnitTypes, QgsWkbTypes)


NAME = "RasterLabel"
# One file from here on, always the same name, overwritten every time. The
# number goes back on it at 1.0, when there is something to release.
VERSION = "1.1"


# Which of the two shapes is running: the installed package, or the single file
# pasted into the console. The two have different fingerprints because they are
# different bytes, and a report that says only "build 7b6f9f28" leaves the reader
# guessing which one they are being told about.
SHAPE = []


def build_stamp():
    """Eight letters that say exactly which build is running.

    A version number says which release this is meant to be. The fingerprint says
    which bytes are actually running, which is the question a bug report has to
    answer: "1.0" is true of every build that was ever called 1.0, including the
    one somebody edited by hand at four in the afternoon.

    It has to work in both shapes the program takes. Pasted into the console it is
    one file, and the fingerprint is that file. Installed as a plugin it is a
    folder of modules, and the fingerprint of this module alone would change only
    when the constants change, saying "same build" across a rewrite of everything
    else. So the package is fingerprinted as a whole: every .py file beside this
    one, in name order, name and contents both.

    Which of the two it is comes from __package__, not from counting the files in
    the folder. Counting was wrong the moment somebody kept the single file in a
    folder with other Python in it, which is the normal state of the folder a
    person develops in: twenty earlier versions sitting beside the current one
    would make the fingerprint the hash of all twenty, change it whenever any
    of them was touched, and have the report say "package" about a pasted file.
    __package__ is empty for a file run on its own and the package's name when it
    is imported as part of one, which is the question being asked.

    The hash is SHA-256, cut to its first eight letters. MD5 would do the
    job just as well, since nothing here is a secret and nobody is trying
    to forge a build; but MD5 is on every security scanner's list, the one the
    QGIS plugin site runs over each upload included, and a reader seeing
    "weak hash, high severity" should not have to work out that it only names
    a build. The stamp is shown in reports and written into snapshots to be
    read by a person; nothing compares a stamp from one build with one from
    another.
    """
    try:
        frame = sys._getframe(0)
        path = frame.f_code.co_filename
        inside = frame.f_globals.get("__package__") or ""
        here = os.path.dirname(os.path.abspath(path))
        if inside and os.path.exists(os.path.join(here, "__init__.py")):
            SHAPE.append("package")
            digest = hashlib.sha256()
            for name in sorted(f for f in os.listdir(here) if f.endswith(".py")):
                digest.update(name.encode("utf-8"))
                with open(os.path.join(here, name), "rb") as fh:
                    digest.update(fh.read())
            return digest.hexdigest()[:8]
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:8]
    except Exception:
        return "unknown"


BUILD = build_stamp()
SHAPE = SHAPE[0] if SHAPE else "single file"
PREFIX = "rasterlabel"             # namespace of the custom layer properties

# ------------------------------------------------------------ the ground
#  Written against QGIS 3.36 Maidenhead and meant to keep working on what
#  comes after it. QGIS moves its enumerations from one home to another
#  between releases and leaves the old name behind as an alias for a while,
#  so a file that spells only the new name stops running on last year's QGIS
#  and a file that spells only the old one stops running on next year's. Both
#  names are asked for here, once, and the rest of the program uses what came
#  back.
BUILT_FOR = (3, 36)                # the QGIS this was written on
BUILT_FOR_NAME = "Maidenhead"


def qgis_version():
    """(major, minor) of the QGIS underneath, however it chooses to say so.

    QGIS_VERSION_INT is the reliable one: 33600 for 3.36.0. The string is
    there as a second try because a nightly writes things like
    '3.99.0-Master' into it, and (0, 0) as a third, which every comparison
    below reads as "older than anything" and which is the safe way to be
    wrong."""
    try:
        n = int(Qgis.QGIS_VERSION_INT)
        if n > 0:
            return (n // 10000, (n // 100) % 100)
    except Exception:
        pass
    try:
        bits = str(Qgis.QGIS_VERSION).split("-")[0].split(".")
        return (int(bits[0]), int(bits[1]))
    except Exception:
        return (0, 0)


def qgis_version_text():
    try:
        return str(Qgis.QGIS_VERSION)
    except Exception:
        return "%d.%d" % qgis_version()


def first_of(*names):
    """The first of these dotted names that this QGIS actually has.

    Handed 'Qgis.GeometryType.Polygon' and 'QgsWkbTypes.PolygonGeometry' it
    returns whichever exists, new name first. The lookup starts from what is in
    THIS module, which is why Qgis and QgsWkbTypes are both imported at the top
    even though neither is written anywhere else in it. A tool that removes
    imports nothing refers to will take one of them away, and the only sign will
    be that the program stops working on the older QGIS it was still able to
    support. It has happened once already."""
    for name in names:
        head, _, rest = name.partition(".")
        found = first_attr(globals().get(head), rest)
        if found is not None:
            return found
    return None


def first_attr(owner, *paths):
    """The first of these dotted paths that owner has, or None.

    first_of() for a class this module does not import: handed the symbol
    layer class and 'Property.Size', 'PropertySize' it answers with whichever
    this QGIS has. An empty path is the owner itself. The answer is compared
    with None and never taken for true or false, since the member wanted is
    often the first of its enumeration and worth 0."""
    for path in paths:
        obj = owner
        for bit in (path.split(".") if path else []):
            if obj is None:
                break
            obj = getattr(obj, bit, None)
        if obj is not None:
            return obj
    return None

# The two geometry kinds this program draws. Qgis.GeometryType arrived in
# 3.30; QgsWkbTypes.PolygonGeometry is the name before that and is deprecated
# from 3.30 on, so both have to be tried.
GEOM_POLYGON = first_of("Qgis.GeometryType.Polygon",
                        "QgsWkbTypes.PolygonGeometry")
GEOM_LINE = first_of("Qgis.GeometryType.Line", "QgsWkbTypes.LineGeometry")
GEOM_POINT = first_of("Qgis.GeometryType.Point", "QgsWkbTypes.PointGeometry")

# The four levels a message can have. The bare Qgis.Info spellings are the
# pre-3.30 ones. The numbers are what the message bar has always meant by
# them, and are there so that a QGIS which has renamed both still gets a
# message rather than a traceback inside the error reporter. The lookup is
# compared with None, never with "or": Info is worth 0, and on QGIS 4 an
# "or 0" would swap the enum for a bare 0, which PyQt6 refuses as a level.
def _level(number, *paths):
    found = first_of(*paths)
    return number if found is None else found


LEVEL_INFO = _level(0, "Qgis.MessageLevel.Info", "Qgis.Info")
LEVEL_WARNING = _level(1, "Qgis.MessageLevel.Warning", "Qgis.Warning")
LEVEL_CRITICAL = _level(2, "Qgis.MessageLevel.Critical", "Qgis.Critical")
LEVEL_SUCCESS = _level(3, "Qgis.MessageLevel.Success", "Qgis.Success")

# What a coordinate system counts in. Qgis.DistanceUnit arrived in 3.30 and
# QgsUnitTypes.DistanceDegrees is the spelling before it. None when this QGIS
# has neither, and the callers then fall back on isGeographic().
UNIT_DEGREES = first_of("Qgis.DistanceUnit.Degrees", "QgsUnitTypes.DistanceDegrees")
UNIT_METRES = first_of("Qgis.DistanceUnit.Meters", "QgsUnitTypes.DistanceMeters")

# Sizes given in map units, so a point marker follows the zoom the way the
# raster does. Qgis.RenderUnit arrived in 3.30; QgsUnitTypes.RenderMapUnits is
# the spelling before it, still there in QGIS 4 but on its way out.
UNIT_RENDER_MAP = first_of("Qgis.RenderUnit.MapUnits",
                           "QgsUnitTypes.RenderMapUnits")
# Where the number of a frame sits. QgsPalLayerSettings.OverPoint is not
# usable: QGIS 3.44 gave that name to another enum, the point position, and
# the placement setter refuses it: on 3.44 and on QGIS 4
# the frames lose their labels with "a member of enum 'LabelPlacement' is
# expected". Qgis.LabelPlacement.OverPoint is the placement on 3.36 and after.
LABEL_OVER_POINT = first_of("Qgis.LabelPlacement.OverPoint")


def qt_generation():
    """5 or 6, or 0 when even that cannot be told."""
    try:
        from qgis.PyQt.QtCore import QT_VERSION_STR
        return int(str(QT_VERSION_STR).split(".")[0])
    except Exception:
        return 0

STEP_PERCENT = 33
LONG_STEP = 3
ZOOM_FACTOR = 1.25
POLYGON_ALPHA = 150                # 0 opaque background, 255 solid fill

STEP_PX = 4                        # sampling step of the freehand trace, on screen
CLOSE_RADIUS_PX = 16               # how close to the first vertex closes the outline
MIN_AREA_PX = 4                    # below this a new stroke is a fleck and is dropped
# Two polygons of one reading that share less than this much of ONE pixel do not
# overlap: it is the residue GEOS leaves when a border is computed twice, of the
# order of 1e-16 m2, and no pixel centre can fall inside it. Check and Repair read
# the same number, so one cannot report what the other then refuses to touch.
OVERLAP_SHARE = 0.01
TILE_SIDE_PX = 200                 # default side of a new tile, in pixels of ground
BIG_RASTER_PX = 4000               # over this on a side, a raster asks for frames
FIRST_CLASS = {"name": "class 1", "code": 1, "colour": "#d95f02"}
# The class codes a campaign can hand out. A mask is one byte a pixel, 0 is
# "nobody painted it", and 255 is kept back for "ignore", the value training
# code most often reads that way: so a campaign has 254 codes, 1 to 254, and a
# code is never given out twice, retired ones included. Past the last one a
# new class is refused, out loud. Without a ceiling, class 256 would go into
# the byte of the mask as 0, silently.
MAX_CLASS_CODE = 254
IGNORE_CODE = 255
# Who drew a mark that carries no name, wherever it is read.
OPERATOR_BLANK = "UNNAMED"
BRUSH_RADIUS_PX = 10               # default radius of the round brush, in pixels
AUTOSAVE = 20                      # strokes between one automatic save and the next
OPACITY_PERCENT = 50               # how solid the mask under correction starts

ICON_H = 28                        # every key of a block or a module, so the rows line up
PRIMARY_H = 32                     # a module button: the main thing a block offers
PAD = 12                           # air around the word inside a button
GROUP_GAP = 10                     # what separates one group of buttons from the next
FREE_W = 16777215                  # Qt's own "no maximum", for a button let out of its size
WIDE_CELL = 1.6                    # how far past its word a command button may be stretched
FIELD_W = 84                       # every number box, arrows included
LABEL_W = 76                       # the label column beside them
CLASS_H = 24                       # every class chip
LINE_PX = 3                        # how wide a new line is, in raster pixels
# The footprints a point can have, always an odd square so that it has a middle
# pixel to sit on. An even one would have to lean to a side, and a sample that
# leans is a sample nobody can place twice the same way.
POINT_SIZES = (1, 3, 5, 7, 9, 11, 15, 21)
POINT_PX = 1                       # the footprint a new campaign starts with
BANNER_H = 36                      # the class in hand, over the chips
PANEL_W = 252                      # the guess used before there is a width to measure
PANEL_MIN = 250                    # below this no arrangement is possible
CARD_MIN = 300                     # the width one column needs to be usable
CARD_W = 220                       # and the width no card is squeezed below
COLUMNS_MAX = 3                    # more than three and the eye loses the order
# RasterLabel is a vertical bar and nothing else. Dealing the cards sideways
# was written for the panel dragged to the top of the window, and on a wide
# screen that is what it produced: a low strip across a 27 inch monitor, half
# of it empty, every control a long way from every other. The same panel at
# the right hand edge is exactly right. So the sideways dealing is off, the
# top and bottom dock areas are refused, and the panel does not grow past the
# width of a bar. One column, always.
ONE_COLUMN = True
BAR_MAX = 520                      # past this a bar stops being a bar
NAV_W = 30                         # one key of the pad that moves the view
NAV_H = 24
COLUMN_MAX = 430                   # no column grows past this, the space is left
DECK_MIN = 264                     # what one column inside a module needs
DECK_MAX = 4                       # how far a module may spread sideways

# Which card goes in which column, by how many columns there are. The cards
# are, in order: raster, the annotation campaign with Annotate and Objects,
# the correction with Correct, Cutouts, the open module, and moving about,
# which holds the button that detaches the panel as well. The three blocks
# that open a module always stay together, so every module is reached from
# the same place.
PLANS = {1: [[0, 1, 2, 3, 4, 5]],
         2: [[0, 1, 2, 3], [4, 5]],
         3: [[0, 1, 2, 3], [4], [5]]}

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#008300",
           "#8e5ac8", "#d6357a", "#00a2b3", "#8a6a3c", "#5b6770"]

# Frames imported with the sampling design they were drawn under carry it in
# five columns of the tiles table, NULL on a frame placed by hand. An older
# package gets them the way it got every column added since: prepare_package
# adds what is missing when the campaign is opened, and touches nothing else.
DESIGN_TILE_COLUMNS = [("sample_id", ogr.OFTString),
                       ("stratum", ogr.OFTString),
                       ("incl_prob", ogr.OFTReal), ("weight", ogr.OFTReal),
                       ("design", ogr.OFTString)]

TABLES = [("tiles", ogr.wkbPolygon,
           [("tile_id", ogr.OFTString), ("side_m", ogr.OFTReal),
            ("note", ogr.OFTString),
            ("created", ogr.OFTString), ("closed", ogr.OFTInteger)]
           + DESIGN_TILE_COLUMNS),
          ("polygons", ogr.wkbMultiPolygon,
           [("class_name", ogr.OFTString), ("class_code", ogr.OFTInteger),
            ("tile_id", ogr.OFTString), ("pass_no", ogr.OFTInteger),
            ("operator", ogr.OFTString), ("created", ogr.OFTString)]),
          ("lines", ogr.wkbMultiLineString,
           [("class_name", ogr.OFTString), ("class_code", ogr.OFTInteger),
            ("tile_id", ogr.OFTString), ("pass_no", ogr.OFTInteger),
            ("operator", ogr.OFTString),
            # the trace is the geometry; the width is how wide a mark it left
            ("width_px", ogr.OFTInteger), ("width_m", ogr.OFTReal),
            ("length_m", ogr.OFTReal),
            # "over" or "under": which way it settled with what it crossed.
            # Kept because it explains the shape of the polygons around it,
            # and a reader who only has the package cannot guess it.
            ("mode", ogr.OFTString), ("created", ogr.OFTString)]),
          ("points", ogr.wkbPoint,
           [("class_name", ogr.OFTString), ("class_code", ogr.OFTInteger),
            ("tile_id", ogr.OFTString), ("pass_no", ogr.OFTInteger),
            ("operator", ogr.OFTString),
            # How much ground the point speaks for, as an odd square of pixels
            # centred on it: 1 is the pixel itself, 3 is a 3 by 3, and so on.
            # The geometry stays the single point that was clicked, because
            # that is what was decided; the footprint is what it stands for.
            ("size_px", ogr.OFTInteger),
            ("conf", ogr.OFTString), ("created", ogr.OFTString)]),
          ("boxes", ogr.wkbPolygon,
           [("class_name", ogr.OFTString), ("class_code", ogr.OFTInteger),
            ("tile_id", ogr.OFTString), ("pass_no", ogr.OFTInteger),
            ("operator", ogr.OFTString),
            ("width_m", ogr.OFTReal), ("height_m", ogr.OFTReal),
            ("created", ogr.OFTString)])]

# The tables that are held open for editing while somebody draws, and that a
# save has to commit. save() and unsaved() both read this, so they cannot drift
# apart.
EDITABLE_TABLES = ("polygons", "lines", "tiles", "points", "boxes")

MIN_BOX_PX = 6                     # a rectangle smaller than this is a misclick
HANDLE_PX = 10                     # how close to a corner counts as grabbing it
MOVE_PX = 6                        # under this, a drag was a click that wobbled
KEEP_BOX = 40                      # per cent of a box that must survive a cutout

# The two catalogue schemas a cutout folder declares. Pinned to a released
# version on purpose: a validator has to be able to fetch exactly the document
# the files were written against, years later.
STAC_VERSION = "1.0.0"
LABEL_EXT = "https://stac-extensions.github.io/label/v1.0.1/schema.json"
PROJ_EXT = "https://stac-extensions.github.io/projection/v1.1.0/schema.json"
GEOTIFF_TYPE = "image/tiff; application=geotiff"

# ------------------------------------------------------------ when it breaks
#  Everything below is about the moment something fails. A failure that
#  goes only into the QGIS log is true, complete, and unread: the user
#  sees a button that does nothing and has no way of telling a locked file
#  from a full disk from a bug. A window is rude, and that is the point. It says
#  what was being attempted, what the machine said, and what is worth trying,
#  in that order, and it keeps the technical detail one click away for the
#  times it has to be sent to somebody.
#
#  The rules that turn an exception into advice are a plain list, read from
#  the top, first match wins. They are guesses, and they say so: a wrong guess
#  followed by the real message is still better than the real message alone.
TRACE_LINES = 40                   # how much of the traceback the report keeps
TROUBLE_W = 500                    # the text column of the window, in pixels

#  One window at a time, and never the same window twice in a breath. A
#  signal that fires on every mouse move can fail on every mouse move, and a
#  modal dialog inside that loop is a machine that has to be killed from the
#  task manager. The second and following copies of the same failure go to the
#  log and the message bar.
STORM_SECONDS = 4.0

#  Rasters: the arithmetic both modules stand on
#
#  One window convention for the whole program: floor on the low side, ceil
#  on the high side, nothing added. One burning convention: a pixel belongs to
#  a polygon when its centre is inside it, which is how the reference masks
#  were made, so a corrected map and an exported label stay comparable with
#  them pixel for pixel.
# =====================================================================
MAX_WINDOW_PX = 40000000           # a stroke or a cutout larger than this is refused
UNDO_DEPTH = 60                    # how many raster windows are kept to undo

# The formats a whole raster can come out as. A campaign may well be a folder
# of photographs rather than a survey, so a plain picture format has to be on
# the list beside the GeoTIFF, and the mask needs one that keeps its values
# untouched: JPEG would quietly reshuffle the class codes.
WHOLE_FORMATS = [
    # label, driver, extension, keeps exact values, takes a geotransform
    ("GeoTIFF", "GTiff", ".tif", True, True),
    ("PNG", "PNG", ".png", True, False),
    ("JPEG", "JPEG", ".jpg", False, False),
]

STRIP_ROWS = 512                   # how many output rows are held at a time
STRIP_PX = 2000000                 # how many pixels of a band are read at once when it is counted

#  The correction module
# =====================================================================
# Which pixels a person changed. RasterLabel 1.0 kept it as one more band of the
# working copy, under this name; it is now a raster of its own beside the copy,
# <copy>_changes.tif, whose one band still carries the name.
FLAG_BAND_NAME = "corrected"
CHANGES_SUFFIX = "_changes"
# A class map holds a handful of codes, a photograph thousands. Past this many
# distinct values a band is not offered one chip per value: it is not a class
# map, and a legend that long could not be read anyway.
MAX_THEMATIC_CLASSES = 256
# A correction keeps a campaign of its own, in a folder the user chooses: this
# manifest, the working copy beside it, operations.csv and the log. It needs
# no annotation campaign, so nothing about it lives in campaign.json.
CORRECTION_MANIFEST = "correction.json"
CORRECTION_FORMAT = 1
# What QGIS remembers on this machine, under one root: the corrections opened
# lately, the operator last typed, and how Cutouts was last set up. Kept out of
# every manifest on purpose, because Cutouts saves no campaign at all.
SETTINGS_ROOT = "rasterlabel"
RECENT_MAX = 8

#  The panel
# =====================================================================
# =====================================================================
#  Taking the work out
#
#  The campaign lives in one GeoPackage because that is the honest way to keep
#  four tables, their classes and their projection in a single file that can be
#  moved without losing anything. It is not, however, the file everyone else
#  wants. A colleague opens shapefiles, a web map wants GeoJSON, someone drops
#  a KML onto Google Earth to show a landowner where the survey went, and a
#  statistician would rather have a table with a column of coordinates than any
#  of those. None of that is a reason to change how the work is stored: it is a
#  reason to be able to write a copy of it out in whatever shape is asked for.
#
#  A copy. Nothing here writes back into the campaign.
# =====================================================================
FORMATS = [
    ("GeoPackage: every table in one file", "GPKG", ".gpkg", True, None),
    ("Shapefile: one set of files per table", "ESRI Shapefile", ".shp", False,
     None),
    ("GeoJSON: one file per table, for the web", "GeoJSON", ".geojson", False,
     "EPSG:4326"),
    ("KML: one file, for Google Earth", "KML", ".kml", True, "EPSG:4326"),
    ("CSV: a table with the geometry written out as text", "CSV", ".csv", False,
     None),
]


# =====================================================================
#  Measuring
#
#  What the panel can say about the work once it is done: how far two
#  readings agree, how long the drawing took, how far a model's map is from
#  the map a person corrected, how sure the model was where it was changed,
#  and a card that puts the numbers of a campaign or a correction in one
#  file. Every number below is read by more than one of them, which is why
#  they live here and not in the modules that use them.
# =====================================================================
# A frame is closed when one reading covers more of it than this, by area.
# measure_tile, Check, Compare, the card, Time and the ignore value all read
# this one number, so none of them can call closed what another calls open.
CLOSED_SHARE = 0.995

# Every report goes in a folder of its own under the campaign or the
# correction: reports/<kind>/<label>_<YYYYmmdd-HHMMSS>/. It is written under
# a name ending in .tmp and renamed when it is complete, so a folder without
# that ending is always a whole report, and none is ever written over.
REPORTS_FOLDER = "reports"
REPORT_FORMAT = 1
REPORT_TMP = ".tmp"
REPORT_SUMMARY = "summary.json"
REPORTS_KEPT = 50                  # entries of one kind kept in the manifest
REPORT_KINDS = ("agreement", "time", "model_vs_corrected", "uncertainty",
                "card")
# The short word a raster or a vector of a report carries in its name, so a
# file copied out of its folder still says what it is.
REPORT_SHORT = {"agreement": "agreement", "time": "time",
                "model_vs_corrected": "mvc", "uncertainty": "unc",
                "card": "card"}
# The numbers each kind puts in its "headline", and that the card copies.
# Fixed here so the writer and the reader cannot drift apart.
REPORT_HEADLINES = {
    "agreement": ("A", "B", "kind", "frames_used", "overall", "overall_ci",
                  "kappa", "kappa_ci", "quantity", "allocation", "mean_iou",
                  "per_class_iou"),
    "time": ("idle_s", "active_h", "min_per_ha_scratch",
             "min_per_ha_correct", "ratio", "ratio_ci", "n_paired"),
    "model_vs_corrected": ("scope", "pixels", "oa", "quantity", "allocation",
                           "per_class_iou", "people_oa", "people_kappa"),
    "uncertainty": ("kind", "auc_random", "auc_whole", "ece_random",
                    "random_done", "purposive_done"),
    "card": (),
}

# Confidence intervals resample whole frames, never pixels: pixels side by
# side are not independent, and an interval over them would be far too
# narrow. Percentile method, 95 %, seeded, and the seed is written down.
# Below five frames there is no interval at all.
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 1
BOOTSTRAP_MIN_FRAMES = 5
BOOTSTRAP_LEVEL = 0.95
BOOTSTRAP_CHUNK = 250              # replicates summed at a time

# Agreement between two readings
MAX_POLYGONS_PER_FRAME = 20000     # past this a frame's disagreement is not drawn
# The codes of the disagreement map. 0 is outside every compared frame.
DISAGREEMENT_CLASSES = [
    {"code": 1, "name": "agree", "colour": "#1baf7a"},
    {"code": 2, "name": "disagree", "colour": "#d6357a"},
    {"code": 3, "name": "only A", "colour": "#2a78d6"},
    {"code": 4, "name": "only B", "colour": "#eda100"},
    {"code": 5, "name": "neither", "colour": "#c8c8c8"},
]

# Time: the journal of working time, one row per thing done, append only
JOURNAL_NAME = "journal.csv"
JOURNAL_VERSION = 1
JOURNAL_COLUMNS = ("session", "seq", "mono_ms", "t_utc", "dur_ms", "pauses_s",
                   "module", "action", "tool", "operator", "pass_no",
                   "tile_id", "class_code", "from_code", "n_vertices",
                   "area_m2", "pixels", "x", "y", "place", "ref", "note")
JOURNAL_BUFFER = 2000              # rows kept in memory while the file refuses
IDLE_DEFAULT_S = 60                # a gap longer than this is not work
IDLE_SENSITIVITY = (30, 60, 120)   # always written as well, to show it holds
PAUSE_MIN_S = 10                   # a stop inside a stroke worth writing down
HEARTBEAT_S = 5                    # at most one "view" row this often
# The rows that own time: what the gap before them was spent on.
MARK_ACTIONS = ("stroke", "under", "line", "point", "point_remove",
                "point_reclass", "reclass", "fill_gaps", "repair",
                "vertex_edit", "box", "box_reshape", "box_reclass",
                "box_delete", "correct", "undo", "discard", "refused")
# The rows that only say where the work was: no class, and no time of their
# own beyond what is counted as overhead of the frame in hand.
CONTEXT_ACTIONS = ("open", "close", "focus_out", "focus_in", "view", "frame",
                   "frame_new", "frame_move", "frame_delete", "frame_import",
                   "reading", "class", "save", "place_done", "place_skip")

# Model vs corrected: which pixels a stroke of Correct went over
REVIEWED_SUFFIX = "_reviewed"
REVIEWED_BAND_NAME = "reviewed"
REVIEWED_MEANING = "1 a stroke of Correct covered this pixel, 0 no stroke did"

# The dataset card
CARD_FORMAT = 1
CARD_SUFFIX = "_card"
PIXEL_RULE = "centre"
PIXEL_RULE_TEXT = ("centre: a pixel takes the class of the polygon its "
                   "centre falls in")

# The value written where nobody painted. "zero" is what every build before
# this one wrote; "ignore" writes the ignore value instead; "frames" writes
# it outside every frame only, and 0 inside them ("none of these").
UNLABELLED_MODES = ("zero", "ignore", "frames")
RASTER_EXT = "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
CLASSIFICATION_EXT = ("https://stac-extensions.github.io/classification/"
                      "v2.0.0/schema.json")

# Frames imported with the sampling design they were drawn under. The five
# columns are in the tiles table (DESIGN_TILE_COLUMNS, above TABLES); these
# are their names, in the order every table of the design writes them.
# Written out rather than read off DESIGN_TILE_COLUMNS, so that the modules
# that need no GDAL can have them too.
DESIGN_FIELDS = ("sample_id", "stratum", "incl_prob", "weight", "design")
DESIGN_TEXT_W = 80                 # the width of a text column in the package
DESIGN_LOG = "design_log.csv"
# The names R (spsurvey, sampling, sf) and AcATaMa give these columns. The
# match ignores case and is exact; the first name that is there wins; fid is
# never taken, because it is the file's row number and not a draw.
DESIGN_ALIASES = {
    "sample_id": ("sample_id", "sampleid", "siteid", "site_id", "plot_id",
                  "plotid", "point_id", "id_unit", "id"),
    "stratum": ("stratum", "strata", "strat", "stratum_id", "h"),
    "incl_prob": ("incl_prob", "inclusion_prob", "inclusion_probability",
                  "pik", "pi", "ip", "prob"),
    "weight": ("weight", "design_weight", "wgt", "w", "sw", "weights"),
    "design": ("design", "design_name", "sampling_design"),
}
DESIGN_LOG_COLUMNS = ("import_id", "when", "operator", "event", "source_file",
                      "source_fid", "sample_id", "stratum", "incl_prob_raw",
                      "weight_raw", "design", "outcome", "reason", "tile_id",
                      "other_tile", "src_xmin", "src_ymin", "src_xmax",
                      "src_ymax", "frame_xmin", "frame_ymin", "frame_xmax",
                      "frame_ymax", "src_side_px", "frame_side_px",
                      "shift_px", "crs")
DESIGN_OUTCOMES = ("added", "completed", "already_there", "refused",
                   "not_written", "moved", "deleted")

# Uncertainty-guided correction
PLACE_SIDE_PX = 256                # the side of one place to review
PLACE_VALID_SHARE = 0.5            # a place needs this much of the map in it
MAX_PLACES = 200000
RANDOM_EVERY = 5                   # one place in this many is drawn at random
U_LEVELS = 254                     # u is kept as a byte, 0..254
U_NODATA = 255                     # and 255 is "no value"
UNCERTAINTY_SUFFIX = "_uncertainty"
PLACES_CSV = "uncertainty_places.csv"
PLACES_GEOJSON = "uncertainty_places.geojson"
# What a band's description says it holds, read lower case, first match wins.
KIND_WORDS = [("votes", r"votes"),
              ("entropy", r"entrop"),
              ("margin", r"margin"),
              ("uncertainty", r"incert|uncert|variance|\bstd\b|\bsd\b"),
              ("probability", r"prob|conf|softmax|pmax|max_?p")]
OVERLAY_OPACITY = 60

# The blind switch of a reading, in the words of Annotate's settings and of
# the window that asks who is drawing: one rule, said once.
BLIND_WORDS = "blind: show only this pass"
BLIND_TIP = (
    "On, the only work you see is the pass you are drawing: every other\n"
    "pass of this operator is hidden, the earlier ones and the later ones.\n"
    "Redrawing with another pass in front of you turns the new reading\n"
    "into a copy of it, and the agreement between the two stops measuring\n"
    "anything.")
