"""rasterlabel.doctor

One press that says everything a bug report needs, and everything the campaign
itself is unhappy about.

The reasoning is this. A first public release will fail in ways nobody here has
imagined, on rasters and QGIS builds nobody here has seen. There are two useful
answers to that. One is to delay the release until it feels finished, which it
never will. The other is to make a failure cheap to report and cheap to diagnose,
so that the first stranger who hits it can hand over something worth reading in
one press, and so that the program itself can say which of its own invariants no
longer hold.

So there are two halves here. The environment half asks what is running: QGIS, Qt,
GDAL, numpy, Python, the platform, which drivers this GDAL actually has, whether
the campaign folder can be written. The campaign half asks whether what is on disk
still makes sense: a manifest with the fields it needs, tables that exist, class
codes that the legend knows, frames that have not drifted off the pixel grid,
polygon outlines that do not cross themselves, frames whose "closed" column
agrees with what is painted in them, polygons that overlap when they should
not, and, in a campaign drawn in frames, points that sit outside them.

Nothing here changes anything. It reads, it counts, and it writes a report. A tool
that offers to repair what it has just diagnosed is a tool that has to be trusted
twice.
"""
import importlib
import os
from html import escape

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFontMetrics
from qgis.PyQt.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                                 QLabel, QTextBrowser, QVBoxLayout)
from qgis.core import QgsGeometry, QgsProject
from osgeo import gdal, ogr

from .constants import (CLOSED_SHARE, EDITABLE_TABLES, FLAG_BAND_NAME,
                        MAX_CLASS_CODE, NAME, TABLES,
                        TROUBLE_W)
from .compat import run_dialog
from .errors import environment, fixed_font, log, log_path
from .campaign import operator_word, pass_number, reading_label
from .geometry import footprint_fits, joint_of
from .naming import from_folder, long_path, source_of, without_home
from .project import crs_from_text
from .layers import find_mine, my_layers, reads_file
from .rasters import (BandPlane, band_marked, codes_present, is_rotated,
                      pixel_grid, style_of)
from .correction import changes_path_of
from .recovery import (describe_snapshot, snapshots_set_aside,
                       snapshots_waiting)
from .reports import report_missing
from .theme import palette_colours

# Reading every feature of a campaign with a hundred thousand polygons in it in
# order to answer a question about shape would take minutes and tell nobody
# anything new. These are the ceilings, and the report says when it hit one: a
# check that quietly looked at a tenth of the data and said "fine" would be worse
# than no check.
MANY_FEATURES = 20000
MANY_FRAMES = 400
# Comparing every polygon of a frame against every other is quadratic. Two
# hundred thousand pairs is a second or two; the point of the ceiling is that
# pressing Check on a very large campaign must not look like a hang.
MANY_PAIRS = 200000
# Geometry is written as the origin plus a whole number of pixels. A thousandth
# of a pixel is far beyond any rounding the program itself does and far below
# anything a hand edit would produce by accident.
OFF_GRID = 1e-3

OK, NOTE, BAD = "ok", "note", "problem"


class Finding(object):

    def __init__(self, level, what, detail=""):
        self.level = level
        self.what = what
        self.detail = detail

    def __str__(self):
        mark = {OK: "  ok   ", NOTE: "  note ", BAD: "  PROBLEM "}[self.level]
        return mark + self.what + (("\n           " + self.detail)
                                   if self.detail else "")


# =====================================================================
#  What is running
# =====================================================================
WANTED_DRIVERS = [("GTiff", "raster", "GeoTIFF, which every cutout is written as"),
                  ("GPKG", "vector", "the GeoPackage a campaign lives in"),
                  ("PNG", "raster", "PNG cutouts"),
                  ("JPEG", "raster", "JPEG cutouts"),
                  ("ESRI Shapefile", "vector", "Shapefile export"),
                  ("GeoJSON", "vector", "GeoJSON export"),
                  ("KML", "vector", "KML export")]


def about_the_machine():
    out = []
    # The versions come from environment(), the same list the trouble window
    # puts in its report, and only from there. Adding platform, Python or
    # numpy lines here as well would make Check say each of them twice, in two
    # spellings ("Python 3.9.18" and "python 3.9.18"), and two places to keep
    # right means one of them is wrong: the system line is where Windows 11 is
    # told apart from Windows 10. The program's own name and build are left
    # to the first line of environment() for the same reason. What is checked
    # here for numpy is the one thing environment() cannot say, which is why
    # it is missing when it is.
    for label, value in environment():
        out.append(Finding(OK, "%-10s %s" % (label, value)))
    try:
        importlib.import_module("numpy")
    except Exception as err:
        out.append(Finding(BAD, "numpy cannot be imported",
                           "%s. Cutouts and Whole cannot work without it; it "
                           "normally comes with QGIS." % err))
    missing = []
    for name, kind, why in WANTED_DRIVERS:
        try:
            got = (gdal.GetDriverByName(name) if kind == "raster"
                   else ogr.GetDriverByName(name))
        except Exception:
            got = None
        if got is None:
            missing.append((name, why))
    if missing:
        out.append(Finding(NOTE, "this GDAL is missing %d of the formats"
                                 % len(missing),
                           "; ".join("%s (%s)" % (n, w) for n, w in missing)
                           + ". Everything else still works."))
    else:
        out.append(Finding(OK, "every format this program writes is available"))
    where = log_path()
    out.append(Finding(OK, "log file   %s" % where) if where else
               Finding(NOTE, "no log file is being written",
                       "it starts when a campaign or a correction is open, "
                       "beside its manifest."))
    return out


# =====================================================================
#  Whether the campaign still makes sense
# =====================================================================
MANIFEST_WANTS = [("program", "which program wrote it"),
                  ("id", "what the layers in the project are matched against"),
                  ("name", "what the layers are called"),
                  ("classes", "the legend"),
                  ("grid", "the pixel grid every geometry is snapped to")]
GRID_WANTS = [("crs", "the coordinate system"),
              ("origin", "the corner every edge is counted from"),
              ("pixel_m", "the pixel size in metres")]


def about_the_campaign(campaign):
    if campaign is None:
        # Not an alarm: Correct and Cutouts are used with no campaign at all.
        return [Finding(NOTE, "no annotation campaign is open",
                        "Annotate and Objects need one; Correct and Cutouts "
                        "do not.")]
    out = []
    data = campaign.data or {}

    # ---- the manifest
    for key, why in MANIFEST_WANTS:
        if key not in data:
            out.append(Finding(BAD, "the manifest has no '%s'" % key,
                               "it is %s." % why))
    grid = data.get("grid") or {}
    if not isinstance(grid, dict):
        # A hand edit, or a manifest written by something else. Everything below
        # would have asked a string for its keys.
        out.append(Finding(BAD, "the grid is not an object",
                           "it is a %s. This may not be a %s campaign."
                           % (type(grid).__name__, NAME)))
        grid = {}
    else:
        for key, why in GRID_WANTS:
            if key == "crs" and grid.get(key):
                # An EPSG code, or a whole WKT for a system that has
                # no code. Either has to be one QGIS can read back.
                crs = crs_from_text(str(grid.get(key)))
                if not crs.isValid():
                    out.append(Finding(
                        BAD, "the coordinate system of the manifest cannot be "
                        "read", "it says %s. Areas and lengths in metres "
                        "cannot be trusted until it names one QGIS knows."
                        % str(grid.get(key))[:80]))
                continue
            if key in grid and grid.get(key):
                continue
            if key == "crs" and key in grid:
                # Written and empty is not damage, it is the supported case:
                # a raster QGIS opens with no coordinate system declared. The
                # New dialog takes one on purpose (the README says a photograph
                # with no coordinate system is a perfectly good thing to
                # annotate), so calling it a PROBLEM would raise an alarm over
                # the thing the program advertises, which is how a report stops
                # being read.
                out.append(Finding(
                    NOTE, "the raster has no coordinate system",
                    "which is allowed: the drawing is done on the pixel grid "
                    "and every geometry is kept. What is lost is only the "
                    "metres: areas and lengths come from the pixel size in "
                    "the manifest, so they are as good as that number is. "
                    "Give the raster a CRS in QGIS if they have to be exact."))
                continue
            out.append(Finding(BAD, "the grid has no '%s'" % key,
                               "it is %s." % why))
    ref = str(from_folder(grid.get("reference_raster") or "",
                          campaign.folder) or "")
    # A campaign can be made on anything QGIS will open, and a basemap is a URL,
# not a path. Testing it with os.path.exists would report "it is not where it
# was" about something that was never a file and is perfectly fine.
    looks_like_a_file = ref and "://" not in ref and not ref.lower().startswith(
        ("wms", "xyz", "wmts", "wcs", "postgres", "mssql", "oracle", "memory"))
    if looks_like_a_file and not os.path.exists(ref.split("|")[0]):
        out.append(Finding(NOTE, "the reference raster is not where it was",
                           ref + ". Measurements still work, because the "
                           "grid is in the manifest; a new cutout cannot be cut."))
    elif ref and not looks_like_a_file:
        out.append(Finding(OK, "the reference raster is a service, not a file",
                           ref[:70]))
    if not out:
        out.append(Finding(OK, "the manifest has everything it needs"))

    # ---- the package and its tables
    #
    # Whatever happens here, the three checks at the bottom still run. They
    # are not skipped by an early return, because the case that would skip
    # them is the case that needs them: a package a sync client has moved or
    # locked, with an hour of drawing sitting in the buffers. The report must
    # say more than that the GeoPackage could not be opened: it must also say
    # what is still in memory.
    counts, tables = {}, set()
    readable = True
    if not os.path.exists(campaign.package_path):
        out.append(Finding(BAD, "the GeoPackage is missing",
                           campaign.package_path))
        readable = False
    else:
        try:
            ds = ogr.Open(campaign.package_path)
            if ds is None:
                out.append(Finding(BAD, "the GeoPackage cannot be opened",
                                   "it may be held open by another QGIS, by "
                                   "this one's edit session, or by a sync "
                                   "client."))
                readable = False
            else:
                for i in range(ds.GetLayerCount()):
                    lyr = ds.GetLayerByIndex(i)
                    tables.add(lyr.GetName())
                    counts[lyr.GetName()] = lyr.GetFeatureCount()
            ds = None
        except Exception as err:
            out.append(Finding(BAD, "the GeoPackage cannot be read", str(err)))
            readable = False
    if not readable:
        out.append(_writable(campaign.folder))
        out.extend(_pending(campaign))
        out.extend(_project_layers(campaign))
        out.extend(_moved_corrections(campaign))
        return out
    for table, _, _ in TABLES:
        if table not in tables:
            out.append(Finding(NOTE, "the package has no '%s' table" % table,
                               "a campaign made by an older build; it is added "
                               "the next time the campaign is opened."))
    out.append(Finding(OK, "tables   " + ", ".join(
        "%s %d" % (t, counts.get(t, 0)) for t, _, _ in TABLES)))

    # ---- can it be written
    out.append(_writable(campaign.folder))

    # ---- the legend against what is drawn
    out.extend(_legend_against_features(campaign, counts))

    # ---- shape
    out.extend(_shape(campaign, grid))

    # ---- points, in a campaign drawn in frames
    out.extend(_points_in_frames(campaign, grid))

    # ---- work that never reached the disk
    out.extend(_pending(campaign))

    # ---- the project's own layers
    out.extend(_project_layers(campaign))

    # ---- corrections that now have a campaign of their own
    out.extend(_moved_corrections(campaign))
    return out


def _writable(folder, what="campaign"):
    probe = os.path.join(folder, ".rasterlabel_check")
    try:
        with open(probe, "w") as fh:
            fh.write("x")
        os.remove(probe)
        return Finding(OK, "the %s folder can be written" % what)
    except Exception as err:
        return Finding(BAD, "the %s folder cannot be written" % what,
                       "%s. Nothing can be saved into it: fix this before "
                       "drawing anything else." % err)


def _legend_against_features(campaign, counts):
    """Codes and names on the features, against the legend in the manifest.

    This is the pair that has to agree. The map is painted by name and the masks
    are burned from the code, so a feature whose name is not in the legend is
    invisible, and a feature whose code is not in the legend comes out of an
    export as a number nobody can read back.
    """
    out = []
    classes = campaign.data.get("classes") or []
    by_code = {c.get("code"): c.get("name") for c in classes}
    by_name = {c.get("name"): c.get("code") for c in classes}
    retired = {c.get("name") for c in classes if c.get("retired")}
    unknown_codes, wrong_names, looked = {}, {}, 0
    capped = False
    for table, _, _ in TABLES:
        if table == "tiles" or counts.get(table, 0) == 0:
            continue
        lyr = find_mine(campaign.data.get("id", ""), table)
        if lyr is None:
            continue
        for f in lyr.getFeatures():
            looked += 1
            if looked > MANY_FEATURES:
                capped = True
                break
            try:
                code, name = f["class_code"], f["class_name"]
            except Exception:
                continue
            if code not in by_code:
                unknown_codes.setdefault(code, 0)
                unknown_codes[code] += 1
            elif name != by_code[code]:
                wrong_names.setdefault((name, code), 0)
                wrong_names[(name, code)] += 1
        if capped:
            break
    if unknown_codes:
        out.append(Finding(BAD, "%d things carry a class code the legend does "
                                "not have" % sum(unknown_codes.values()),
                           "codes " + ", ".join(str(c) for c in sorted(
                               unknown_codes, key=lambda x: str(x)))
                           + ". An export would write a number nobody can read "
                             "back. Open Classes and give those codes a name, or "
                             "reclassify the features."))
    if wrong_names:
        out.append(Finding(BAD, "%d things carry a name the legend gives to "
                                "another code" % sum(wrong_names.values()),
                           ", ".join("'%s' with code %s" % (n, c)
                                     for n, c in sorted(wrong_names,
                                                        key=str)[:6])
                           + ". The map paints by name, so these are drawn as "
                             "something they are not: press Classes and Ok, "
                             "which rewrites the names from the codes."))
    wide = sorted(c.get("code") for c in classes
                  if isinstance(c.get("code"), int)
                  and c.get("code") > MAX_CLASS_CODE)
    if wide:
        out.append(Finding(NOTE, "%d class code%s past %d"
                                 % (len(wide), "" if len(wide) == 1 else "s",
                                    MAX_CLASS_CODE),
                           "codes " + ", ".join(str(c) for c in wide[:6])
                           + ". A campaign hands out 1 to %d, and 255 is kept "
                             "for 'ignore'; these came from somewhere else. "
                             "Nothing is lost: a mask with them in it is "
                             "written in 16 bits instead of one byte, so check "
                             "that whatever reads it expects that."
                           % MAX_CLASS_CODE))
    if retired:
        out.append(Finding(NOTE, "%d retired class%s in the legend"
                                 % (len(retired), "" if len(retired) == 1 else "es"),
                           ", ".join(sorted(retired))
                           + ". Retired is normal: the number stays reserved so "
                             "nothing already exported changes meaning."))
    if not unknown_codes and not wrong_names:
        out.append(Finding(OK, "every class code and name agrees with the legend"
                               + (" (first %d things)" % MANY_FEATURES
                                  if capped else "")))
    if not by_name:
        out.append(Finding(BAD, "the legend is empty", "nothing can be drawn."))
    return out


def _shape(campaign, grid):
    """Are the frames still on the grid, do the outlines not cross themselves,
    and is the partition still a partition.

    All three are invariants the program maintains by construction, which is
    exactly why they are worth testing: an invariant that is never checked is
    a belief.
    """
    out = []
    try:
        ox, oy = [float(v) for v in grid.get("origin", (0.0, 0.0))]
        px, py = [abs(float(v)) for v in grid.get("pixel_crs")
                  or grid.get("pixel_m") or (1.0, 1.0)]
    except Exception:
        return [Finding(NOTE, "the grid cannot be read, so shape was not checked")]
    if not px or not py:
        return [Finding(NOTE, "the pixel size is zero, so shape was not checked")]

    lyr = find_mine(campaign.data.get("id", ""), "polygons")
    if lyr is None:
        return [Finding(NOTE, "the polygons layer is not in the project, so "
                              "shape was not checked")]

    # What is measured against the grid, and what is not.
    #
    # The frames are: a frame is placed on the grid by snapped_square, a cutout
    # is cut from it, and a frame half a pixel out offsets every image and every
    # mask cut from it for good. That is a defect and is reported as one.
    #
    # The polygons are not. A brush outline follows the hand, vertex by vertex,
    # and is never snapped to anything; checking it would say "4 polygons not
    # on the pixel grid" about four perfectly ordinary polygons, blame the
    # vertex tool for it, and say it about every campaign ever drawn. What is
    # exact at the pixel is the frame, the strip a line claims, the footprint
    # of a point, and the mask burned at export, which is rasterized on the
    # campaign grid with the centre rule and no resampling. The README says the
    # same.
    off_frames, frames_read, frames_unreadable = 0, 0, 0
    frames_left = False
    tiles_layer = find_mine(campaign.data.get("id", ""), "tiles")
    if tiles_layer is not None:
        for t in tiles_layer.getFeatures():
            if frames_read >= MANY_FRAMES:
                frames_left = True
                break
            tg = t.geometry()
            if tg is None or tg.isEmpty():
                continue
            frames_read += 1
            tb = tg.boundingBox()
            try:
                for value, origin, size in ((tb.xMinimum(), ox, px),
                                            (tb.xMaximum(), ox, px),
                                            (tb.yMinimum(), oy, py),
                                            (tb.yMaximum(), oy, py)):
                    whole = (value - origin) / size
                    if abs(whole - round(whole)) > OFF_GRID:
                        off_frames += 1
                        break
            except (ValueError, OverflowError, ZeroDivisionError):
                frames_unreadable += 1

    looked, capped, frames_capped, unreadable = 0, False, False, 0
    crossing = 0
    per_frame = {}
    # the class of each polygon in per_frame, in the same order: two polygons
    # of one class and one reading that meet are one polygon waiting to be
    # merged, which is a different thing to say than "share ground"
    per_class = {}
    frames_kept = set()
    for f in lyr.getFeatures():
        looked += 1
        if looked > MANY_FEATURES:
            capped = True
            break
        g = f.geometry()
        if g is None or g.isEmpty():
            continue
        # An outline that crosses itself. QGIS's vertex tool lets a vertex be
        # dragged across its own polygon's edge, and every later cut against
        # that bow tie fails: the brush stops settling anything near it.
        try:
            if not g.isGeosValid():
                crossing += 1
        except Exception:
            pass
        try:
            # The operator belongs in this key as much as the frame and the
            # pass do. Two people reading the same frame are meant to cover it
            # twice, each from scratch: that is what makes the two readings
            # comparable, and their polygons overlap each other almost
            # everywhere by design. Grouped by frame and pass alone, every one
            # of those pairs would be reported in red as "polygons share ground",
            # on a campaign where nothing is wrong, and the advice under it
            # would be to press Repair. A check that cries wolf about the one thing
            # the campaign is built to do is worse than no check.
            who = operator_word(f["operator"])
        except (KeyError, IndexError):
            who = operator_word(None)
        # Read through the same two functions measure_tile, the filter and
        # the exports read a reading through, so that what Check calls one
        # reading is what the save closed the frame by.
        try:
            key = (f["tile_id"], pass_number(f["pass_no"]), who)
        except Exception:
            key = (None, 1, who)
        # The ceiling counts frames, not readings: three operators on one frame
        # are one frame, and counting them as three switched the closed check
        # off on a campaign of a hundred and fifty frames read three times.
        if len(frames_kept) < MANY_FRAMES or key[0] in frames_kept:
            frames_kept.add(key[0])
            per_frame.setdefault(key, []).append(g)
            try:
                per_class.setdefault(key, []).append(f["class_name"])
            except (KeyError, IndexError):
                per_class.setdefault(key, []).append(None)
        else:
            frames_capped = True

    # What was actually looked at, said once and used by every claim below. A
    # claim measured on a tenth of a campaign must not be printed in the same
    # words as a claim measured on all of it, whether or not it found something.
    partial = []
    if capped:
        partial.append("only the first %d polygons were read" % MANY_FEATURES)
    if frames_capped:
        partial.append("only the first %d frames were kept" % MANY_FRAMES)
    seen_all = not partial

    if unreadable:
        out.append(Finding(NOTE, "%d polygon%s could not be measured"
                                 % (unreadable, "" if unreadable == 1 else "s"),
                           "their coordinates are not numbers, which means a "
                           "corrupt or truncated record. They were skipped; "
                           "everything else was still checked."))
    if crossing:
        out.append(Finding(BAD, "%d polygon outline%s cross%s itself"
                                % (crossing, "" if crossing == 1 else "s",
                                   "es" if crossing == 1 else ""),
                           "a vertex dragged across an edge of its own polygon "
                           "makes a bow tie, and nothing can be cut against "
                           "it. Press Repair in Annotate on that frame: it "
                           "untangles the outline into the polygons it "
                           "encloses before anything else."
                           + ("" if seen_all else
                              " And %s, so there may be more."
                              % " and ".join(partial))))
    if frames_unreadable:
        out.append(Finding(NOTE, "%d frame%s could not be measured"
                                 % (frames_unreadable,
                                    "" if frames_unreadable == 1 else "s"),
                           "their coordinates are not numbers, which means a "
                           "corrupt or truncated record."))
    if off_frames:
        out.append(Finding(BAD, "%d frame%s not on the pixel grid"
                                % (off_frames, "" if off_frames == 1 else "s"),
                           "every cutout and every mask taken from them is "
                           "offset by a fraction of a pixel from the image, "
                           "and nothing in the files says so. A frame is "
                           "placed on the grid when it is made, so one off it "
                           "was moved by something else: the QGIS vertex tool "
                           "on the frames layer, or an import."))
    elif frames_left:
        # "every frame" would be a claim about frames that were never read
        out.append(Finding(NOTE, "the first %d frame%s sit on the pixel grid"
                                 % (frames_read, "" if frames_read == 1 else "s"),
                           "the rest were not measured. This says the "
                           "campaign is big, not that the rest is clean."))
    elif frames_read:
        out.append(Finding(OK, "every frame sits on the pixel grid",
                           "which is what the cutouts and the masks are cut "
                           "on. Brush outlines are vector and follow the hand; "
                           "the mask is burned on the campaign grid at export, "
                           "so it still lines up with the image pixel for "
                           "pixel."))
    # And with no frame at all there is nothing to say. A branch here used to
    # print "not everything was looked at" followed by an empty reason on every
    # campaign drawn without frames, a warning about frames it never had.

    # Not "more than nothing". A border GEOS computed twice, once for each side,
    # leaves an intersection of the order of 1e-16 m2 between two polygons that
    # meet exactly; a vertex move followed by the trim does it about one time in
    # five. Counted as an overlap, it made Check say "1 pair share ground" and
    # Repair, which rightly ignores it, answer "0 overlaps resolved".
    # (joint_of reads that same threshold, so the two cannot drift apart)
    overlaps = 0
    same_class = 0          # of the overlaps, those between polygons of one class
    unmerged = 0            # neighbours of one class that share a border only
    pairs = 0
    stopped = False
    for key, geoms in per_frame.items():
        if stopped:
            break               # and out of the frames too, not just the pairs
        if len(geoms) < 2:
            continue
        for i in range(len(geoms)):
            for j in range(i + 1, len(geoms)):
                if pairs >= MANY_PAIRS:
                    stopped = True
                    break
                pairs += 1
                a, b = geoms[i], geoms[j]
                try:
                    how = joint_of(a, b, px, py)
                except Exception:
                    continue
                if how == "overlap":
                    overlaps += 1
                    if (per_class[key][i] is not None
                            and per_class[key][i] == per_class[key][j]):
                        same_class += 1
                elif (how == "border" and per_class[key][i] is not None
                        and per_class[key][i] == per_class[key][j]):
                    unmerged += 1
            if stopped:
                break
    if overlaps:
        out.append(Finding(BAD, "%d pair%s of polygons share ground"
                                % (overlaps, "" if overlaps == 1 else "s"),
                           "within one frame, one pass and one operator they "
                           "should not: press Repair in Annotate, which gives "
                           "the ground to the smaller one. Two operators "
                           "reading the same frame are not counted here, "
                           "because their readings are meant to cover it twice."
                           + ("" if not same_class else
                              " %d of the pair%s are polygons of one class, "
                              "which Repair also joins into one."
                              % (same_class, "" if same_class == 1 else "s"))
                           + ("" if seen_all and not stopped else
                              " And %s, so this is a floor, not a total."
                              % " and ".join(
                                  partial + (["the comparison stopped after "
                                              "%d pairs" % MANY_PAIRS]
                                             if stopped else [])))))
    elif capped or stopped or frames_capped:
        # Not a clean bill of health, and it must not read like one. The whole
        # value of this report is that what it says can be relied on, so a check
        # that ran out of patience says so instead of printing the same line a
        # finished check prints.
        out.append(Finding(NOTE, "no overlap found, but not everything was "
                                 "looked at",
                           "%s. Nothing here says the rest is clean: it says "
                           "the campaign is big. Repair in Annotate works on "
                           "the frame in hand whatever this found."
                           % ", ".join(
                               ([("only the first %d things were read"
                                  % MANY_FEATURES)] if capped else [])
                               + ([("only the first %d frames were kept"
                                    % MANY_FRAMES)] if frames_capped else [])
                               + ([("the comparison stopped after %d pairs"
                                    % MANY_PAIRS)] if stopped else []))))
    else:
        out.append(Finding(OK, "no two polygons of one reading share ground"))

    if unmerged:
        out.append(Finding(NOTE, "%d pair%s of neighbours of one class are "
                                 "still separate polygons"
                                 % (unmerged, "" if unmerged == 1 else "s"),
                           "same class, same reading and same frame, sharing a "
                           "border. A new mark or a moved vertex joins such "
                           "neighbours as they meet; these were drawn before "
                           "that, or with a QGIS tool. Nothing is wrong with "
                           "the pixels: press Repair in Annotate to join them, "
                           "in one step that Undo takes back."))
    out.extend(_closed_flags(campaign, per_frame, partial))
    return out


def _points_in_frames(campaign, grid):
    """In a campaign drawn in frames, does every point sit inside its frame.

    Areas and lines are clipped to the frame they are drawn in, and points are
    refused outside it, footprint and all. Points dropped by an earlier
    build were not: they went down wherever the click was, a point outside
    every frame was written with no frame at all, and the export burned its
    footprint on ground no frame covers. Those are found here, and so are
    points whose tile_id names a frame other than the one they sit in, which
    a move of that frame would leave behind.

    A note, not a problem: nothing is broken, and the mask says what was
    drawn. But a frame is meant to bound what is labelled, and these do not
    keep to it."""
    if not (campaign.data or {}).get("with_tiles"):
        return []
    points = find_mine(campaign.data.get("id", ""), "points")
    tiles = find_mine(campaign.data.get("id", ""), "tiles")
    if points is None or tiles is None:
        return []
    try:
        origin = tuple(float(v) for v in grid.get("origin", (0.0, 0.0)))
        # A manifest with no pixel size at all is judged on the point alone,
        # not on a square of one map unit that would have nothing to do with
        # the raster: a metre "pixel" on a 5 cm survey would call every point
        # near an edge outside.
        pixel = tuple(abs(float(v)) for v in grid.get("pixel_crs")
                      or grid.get("pixel_m") or (0.0, 0.0))
    except Exception:
        return [Finding(NOTE, "the grid cannot be read, so the points were "
                              "not checked against the frames")]
    # Every frame, not the first few hundred: a point in a frame past a cap
    # would have been counted outside every frame, which it is not. A frame is
    # one square, so reading them all costs little; the points are what is
    # capped. Each frame keeps its bounding box, so that a point is tested
    # with GEOS only against the frames that could hold it.
    frames, named_frames = [], {}
    for t in tiles.getFeatures():
        g = t.geometry()
        if g is None or g.isEmpty():
            continue
        try:
            tid = t["tile_id"]
        except (KeyError, IndexError):
            tid = None
        tid = str(tid) if tid is not None else ""
        try:
            b = g.boundingBox()
            bounds = (b.xMinimum(), b.yMinimum(), b.xMaximum(), b.yMaximum())
        except Exception:
            bounds = None
        frames.append((tid, g, bounds))
        named_frames.setdefault(tid, []).append((tid, g, bounds))
    try:
        has_size = "size_px" in [f.name() for f in points.fields()]
    except Exception:
        has_size = False
    outside, wrong, looked, capped = 0, 0, 0, False
    for f in points.getFeatures():
        looked += 1
        if looked > MANY_FEATURES:
            capped = True
            break
        g = f.geometry()
        if g is None or g.isEmpty():
            continue
        try:
            b = g.boundingBox()
            x, y = b.xMinimum(), b.yMinimum()
        except Exception:
            continue
        n = 1
        if has_size:
            try:
                n = max(1, int(f["size_px"] or 1))
            except (KeyError, IndexError, TypeError, ValueError):
                n = 1
        try:
            named = f["tile_id"]
        except (KeyError, IndexError):
            named = None
        named = "" if named is None else str(named)
        # The frame it names is asked first. Frames may overlap, and a point
        # in the overlap that names the second of the two is where it belongs:
        # taking the first frame that holds it would have called it misnamed.
        if _fits_one(named_frames.get(named, ()), x, y, n, origin, pixel):
            continue
        if _fits_one(frames, x, y, n, origin, pixel):
            wrong += 1
        else:
            outside += 1
    if looked == 0:
        return []
    partial = (" Only the first %d points were read, so there may be more."
               % MANY_FEATURES) if capped else ""
    out = []
    if outside:
        out.append(Finding(
            NOTE, "%d point%s outside every frame"
                  % (outside, "" if outside == 1 else "s"),
            "the point, or the square of pixels it stands for, is not wholly "
            "inside any frame, so the export labels ground no frame covers. "
            "Points are refused there now; these were dropped by an earlier "
            "build. To clean up: in Annotate take Points, untick \"only the "
            "current tile\" if it is ticked so that the ones with no "
            "frame are drawn, and right click each one to remove it (removing "
            "works anywhere), then drop it again "
            "inside the frame it belongs to, further in from the edge or with "
            "a smaller point size if it was its square that reached past the "
            "edge. In QGIS, Select by Expression on the points layer with "
            "\"tile_id\" = '' or \"tile_id\" IS NULL finds the ones that "
            "have no frame at all." + partial))
    if wrong:
        out.append(Finding(
            NOTE, "%d point%s inside a frame other than the one %s"
                  % (wrong, "" if wrong == 1 else "s",
                     "it names" if wrong == 1 else "they name"),
            "the tile_id says one frame and the point sits in another, so "
            "moving or deleting its frame would leave it behind. To clean "
            "up: select the frame it sits in, take Points, right click the "
            "point to remove it and drop it again, which writes the frame's "
            "name on it." + partial))
    if not out:
        out.append(Finding(
            OK if not capped else NOTE,
            "every point sits inside the frame it names" if not capped else
            "the first %d points sit inside the frame they name"
            % MANY_FEATURES,
            "" if not capped else "the rest were not read."))
    return out


def _fits_one(frames, x, y, n, origin, pixel):
    """Whether a point's footprint lies wholly inside one of these frames.

    The bounding box of each frame is compared first, which is plain
    arithmetic: thousands of points against hundreds of frames would
    otherwise be a million GEOS calls for a report that has to come back
    while the person waits."""
    for _, fg, bounds in frames:
        if bounds is not None and not (bounds[0] <= x <= bounds[2]
                                       and bounds[1] <= y <= bounds[3]):
            continue
        try:
            if footprint_fits(fg, x, y, n, origin, pixel):
                return True
        except Exception:
            continue
    return False


def _closed_flags(campaign, per_frame, partial=()):
    """Does the closed column agree with what is painted in the frame.

    closed is the column that says a frame is a complete reading and can be
    handed to somebody. It is written at save time from the coverage, so it can
    disagree with the drawing in exactly one way: the drawing changed and no save
    has happened since. A frame marked closed with a hole in it is the worst
    thing this program can produce, because it is wrong in a way that looks
    finished, and this is the only place that would ever notice.

    Measured on the plane rather than on the ellipsoid: it is a ratio of two
    areas in the same system, so the difference cancels, and this is a
    disagreement test rather than a measurement.
    """
    tiles = find_mine(campaign.data.get("id", ""), "tiles")
    if tiles is None or not per_frame:
        return []
    names = set()
    try:
        names = {f.name() for f in tiles.fields()}
    except Exception:
        pass
    if "closed" not in names:
        return [Finding(NOTE, "the frames have no 'closed' column",
                        "a campaign made by an older build.")]
    if partial:
        # Measured on what was read, a frame whose polygons lie past the
        # ceiling comes out 0% painted, and if it is marked closed it would be
        # reported as a PROBLEM about a frame nobody has looked at.
        return [Finding(NOTE, "the 'closed' column was not checked",
                        "%s, so the coverage of some frames is unknown."
                        % " and ".join(partial))]
    wrong, looked, left = [], 0, False
    for f in tiles.getFeatures():
        looked += 1
        if looked > MANY_FRAMES:
            left = True
            break
        try:
            tid = f["tile_id"]
            said = int(f["closed"] or 0)
            frame = f.geometry()
        except Exception:
            continue
        if frame is None or frame.isEmpty():
            continue
        whole = frame.area()
        if not whole:
            continue
        best, best_key = 0.0, None
        # The key is (frame, pass, operator) and is read by position, never
        # unpacked by shape. It was unpacked as two values; the operator was
        # then added to the key to stop two readings of one frame from being
        # called an overlap, and Check stopped with "too many values to
        # unpack" on every campaign with a frame in it. The best reading of
        # the frame, whoever made it, is what "closed" is compared with: one
        # reading on its own, never two operators added together, which is
        # what the save writes closed from too.
        for key, geoms in per_frame.items():
            if key[0] != tid:
                continue
            try:
                clipped = [g.intersection(frame) for g in geoms]
                clipped = [g for g in clipped if g is not None and not g.isEmpty()]
                if not clipped:
                    continue
                one = (QgsGeometry.unaryUnion(clipped) if len(clipped) > 1
                       else clipped[0])
                share = one.area() / whole
                if share > best:
                    best, best_key = share, key
            except Exception:
                continue
        really = best > CLOSED_SHARE
        if bool(said) != really:
            wrong.append((tid, said, best, best_key))
    if not wrong and left:
        # "every frame" would vouch for frames that were never read
        return [Finding(NOTE, "the 'closed' column agrees in the first %d "
                              "frames" % MANY_FRAMES,
                        "the rest were not compared. This says the campaign "
                        "is big, not that the rest is right.")]
    if not wrong:
        return [Finding(OK, "every frame's 'closed' column agrees with what is "
                            "painted in it")]
    shut = [w for w in wrong if w[1]]
    return [Finding(BAD if shut else NOTE,
                    "%d frame%s whose 'closed' column disagrees with the drawing"
                    % (len(wrong), "" if len(wrong) == 1 else "s"),
                    ", ".join("%s says %s and is %.1f%% painted%s"
                              % (tid, "closed" if said else "open", share * 100,
                                 " in its fullest reading, %s"
                                 % reading_label((key[2], key[1]))
                                 if key is not None else "")
                              for tid, said, share, key in wrong[:6])
                    + (". A frame marked closed is one somebody is told they "
                       "can hand over. Press Save: the column is rewritten from "
                       "the coverage every time." if shut else
                       ". Press Save and they will agree again."))]


def _pending(campaign):
    out = []
    waiting = []
    for role in EDITABLE_TABLES:
        lyr = find_mine(campaign.data.get("id", ""), role)
        if lyr is not None and lyr.isEditable() and lyr.isModified():
            waiting.append(role)
    if waiting:
        out.append(Finding(NOTE, "work not yet on disk in " + ", ".join(waiting),
                           "press Save. It is in the recovery file meanwhile."))
    # With the running session's name, or the file this very session wrote a
    # second ago would be reported as an afternoon somebody lost, with advice to
    # close the campaign and open it again to be asked about it.
    mine = ""
    try:
        from .launch import _RASTERLABEL
        if _RASTERLABEL:
            net = _RASTERLABEL[2].recovery
            mine = net.session if net is not None else ""
    except Exception:
        mine = ""
    left = snapshots_waiting(campaign.folder, mine,
                             campaign.data.get("id", ""))
    if left:
        out.append(Finding(NOTE, "%d recovery file%s from an earlier session"
                                 % (len(left), "" if len(left) == 1 else "s"),
                           "; ".join(describe_snapshot(h, r)
                                     for _, h, r in left[:3])
                           + ". Close the campaign and open it again to be "
                             "asked about them."))
    # And the files dealt with earlier. A file turned down at the question is
    # work that is not in the package, kept as text, and a campaign holding
    # one is not "everything on disk", so it is counted here even though the
    # file was renamed out of the way when "Not now" was answered.
    aside = snapshots_set_aside(campaign.folder, campaign.data.get("id", ""))
    if aside:
        dropped = [a for a in aside if a[1] == "discarded"]
        shown = sorted(aside, key=lambda a: a[1] != "discarded")[:4]
        out.append(Finding(
            NOTE, "%d recovery file%s set aside in %s%s" % (
                len(aside), "" if len(aside) == 1 else "s",
                os.path.join(os.path.basename(campaign.folder), "recovery"),
                ", %d of them discarded: that work is not in the package"
                % len(dropped) if dropped else ""),
            "; ".join("%s (%s): %s" % (
                os.path.basename(path),
                "discarded" if how == "discarded" else
                "put back, or declined by an earlier build",
                describe_snapshot(h, r)) for path, how, h, r in shown)
            + ". They are plain text. To be asked about a discarded one "
              "again, take .discarded off the end of its name and open the "
              "campaign again; do the same with .restored only after reading "
              "it, because work already put back would be put back twice. "
              "Delete them once nothing in them is wanted."))
    if not out:
        out.append(Finding(OK, "everything drawn is on disk"))
    return out


def _project_layers(campaign):
    """Layers in the project that read this package but are not marked as ours.

    A QGIS project saves its layers. Reopen the project and they come back; if
    the program does not recognise them it adds a second set on top, and the map
    draws everything twice. claim_strays fixes it at open, and this says whether
    it worked.
    """
    target = os.path.normcase(os.path.abspath(campaign.package_path))
    mine, theirs = 0, []
    for lyr in QgsProject.instance().mapLayers().values():
        try:
            here = os.path.normcase(os.path.abspath(source_of(lyr).split("|")[0]))
        except Exception:
            continue
        if here != target:
            continue
        if lyr.customProperty("rasterlabel/campaign"):
            mine += 1
        else:
            theirs.append(lyr.name())
    # And the other way round: marked as the campaign's and reading another
    # file, the original of a copied folder or the old place of a moved one.
    # Every stroke would go there, or nowhere (layers.drop_stale).
    elsewhere = [lyr for lyr in my_layers(campaign.data.get("id", ""))
                 if lyr.customProperty("rasterlabel/role")
                 in [t for t, _, _ in TABLES]
                 and not reads_file(lyr, campaign.package_path)]
    if elsewhere:
        return [Finding(BAD, "%d of the campaign's layer%s read another file "
                             "than its GeoPackage" % (
                                 len(elsewhere),
                                 "" if len(elsewhere) == 1 else "s"),
                        "; ".join("%s: %s%s" % (
                            lyr.name(), source_of(lyr),
                            "" if lyr.isValid() else ", not there")
                            for lyr in elsewhere[:5])
                        + ". What is drawn would not reach this campaign. "
                          "Close the campaign and open it again: they are "
                          "replaced by layers of its own file.")]
    if theirs:
        return [Finding(NOTE, "%d layer%s read this package but are not the "
                              "campaign's" % (len(theirs),
                                              "" if len(theirs) == 1 else "s"),
                        ", ".join(theirs[:6])
                        + ". The map may draw the same thing twice. Close the "
                          "campaign and open it again: the layers already there "
                          "are adopted instead of being doubled.")]
    return [Finding(OK, "%d layer%s in the project, all the campaign's"
                        % (mine, "" if mine == 1 else "s"))]


# =====================================================================
#  Whether the correction still makes sense
# =====================================================================
CORRECTION_WANTS = [("program", "which program wrote it"),
                    ("kind", "what kind of manifest this is"),
                    ("format", "the version of the manifest"),
                    ("id", "what its layer in the project is matched against"),
                    ("name", "what it is called"),
                    ("source", "the map it started from"),
                    ("band", "the band that holds the classes"),
                    ("working_copy", "the copy that is corrected"),
                    ("grid", "the pixel grid areas are measured on"),
                    ("classes", "the classes the chips are drawn with")]


def about_the_correction(book):
    """The correction campaign open in Correct, looked over as the campaign
    is: the manifest, the working copy, the map it came from, the classes
    against the codes in the copy, the log of operations. Nothing is
    repaired."""
    out = []
    data = book.data or {}
    for key, why in CORRECTION_WANTS:
        if key not in data:
            out.append(Finding(BAD, "the manifest has no '%s'" % key,
                               "it is %s." % why))
    grid = data.get("grid") or {}
    if not isinstance(grid, dict):
        out.append(Finding(BAD, "the grid is not an object",
                           "it is a %s." % type(grid).__name__))
        grid = {}
    text = str(grid.get("crs") or "")
    if text and not crs_from_text(text).isValid():
        out.append(Finding(BAD, "the coordinate system of the manifest cannot "
                                "be read",
                           "it says %s. Areas in m2 cannot be trusted until "
                           "it names one QGIS knows." % text[:80]))
    elif "crs" in grid and not text:
        out.append(Finding(NOTE, "the map has no coordinate system",
                           "which is allowed: areas are counted in the pixel "
                           "size of the manifest."))
    for key in ("origin", "pixel_m"):
        if grid and not grid.get(key):
            out.append(Finding(BAD, "the grid has no '%s'" % key,
                               "it is %s." % dict(GRID_WANTS)[key]))

    # ---- the working copy
    path = book.working_path
    ds = None
    if not path or not os.path.exists(path):
        out.append(Finding(BAD, "the working copy is missing", path or "?"))
    else:
        try:
            ds = gdal.Open(path)
        except Exception:
            ds = None
        if ds is None:
            out.append(Finding(BAD, "the working copy cannot be opened", path))
    if ds is not None:
        for look in (_copy_like_its_map, _changes_beside):
            try:
                out.extend(look(ds, path, data))
            except Exception as err:
                out.append(Finding(NOTE, "part of the working copy could not "
                                         "be looked at", str(err)))
        size = grid.get("size")
        # the grid QGIS draws the copy on, the one the strokes land on
        gt = pixel_grid(ds)
        if is_rotated(gt):
            out.append(Finding(BAD, "the working copy has a rotated pixel grid",
                               "Correct does not open it: a stroke would "
                               "change pixels beside the ones under it. Warp "
                               "the map north-up and correct that one."))
        drift = []
        if size and list(size) != [ds.RasterXSize, ds.RasterYSize]:
            drift.append("%d x %d pixels, the manifest says %d x %d"
                         % (ds.RasterXSize, ds.RasterYSize, size[0], size[1]))
        origin = grid.get("origin")
        if origin and gt and (abs(gt[0] - origin[0]) > 1e-6 * max(1, abs(gt[1]))
                              or abs(gt[3] - origin[1]) > 1e-6 * max(1, abs(gt[5]))):
            drift.append("its corner is %.6f, %.6f, the manifest says %.6f, "
                         "%.6f" % (gt[0], gt[3], origin[0], origin[1]))
        if drift:
            out.append(Finding(BAD, "the working copy is not on the grid of "
                                    "the manifest",
                               "; ".join(drift) + ". It was replaced or "
                               "edited by something else."))
        try:
            band = ds.GetRasterBand(int(data.get("band", 1)))
            nodata = band.GetNoDataValue()
            # a strip at a time: the band of a large map is not held whole
            present = set(codes_present(
                BandPlane(path, int(data.get("band", 1))), nodata))
        except Exception as err:
            present = None
            out.append(Finding(BAD, "the class band cannot be read", str(err)))
        if present is not None:
            listed = {c.get("code") for c in data.get("classes") or []}
            unnamed = sorted(present - listed)
            if unnamed:
                out.append(Finding(NOTE, "%d code%s in the copy without a class"
                                         % (len(unnamed),
                                            "" if len(unnamed) == 1 else "s"),
                                   ", ".join(str(v) for v in unnamed[:12])
                                   + ". Each is given a class when the "
                                     "correction is opened."))
            if nodata is not None and nodata in listed:
                out.append(Finding(BAD, "the nodata value is listed as a class",
                                   "%s. Painting it would erase pixels, not "
                                   "correct them: change it in Classes." % nodata))
            if not unnamed and not (nodata is not None and nodata in listed):
                out.append(Finding(OK, "every code in the copy has a class, %d "
                                       "in all" % len(listed)))
        ds = None

    # ---- the map it started from
    source = str(data.get("source") or "")
    if source and not os.path.exists(source.split("|")[0]):
        out.append(Finding(NOTE, "the map it started from is not where it was",
                           source + ". The copy is corrected all the same; "
                           "'show the original beside it' cannot work."))

    # ---- the log of operations against the count
    log_csv = os.path.join(os.path.dirname(path or book.folder), "operations.csv")
    rows = None
    if os.path.exists(log_csv):
        try:
            with open(log_csv, encoding="utf-8", errors="replace") as fh:
                rows = max(0, sum(1 for line in fh if line.strip()) - 1)
        except Exception:
            rows = None
    counted = int(data.get("operations", 0) or 0)
    if rows is not None and rows != counted:
        out.append(Finding(NOTE, "operations.csv has %d rows and the manifest "
                                 "counts %d" % (rows, counted),
                           "an undo keeps its row in the log, so the two can "
                           "differ; the log is the history."))
    elif rows is None and counted:
        out.append(Finding(NOTE, "the manifest counts %d operations and there "
                                 "is no operations.csv" % counted,
                           "the history of the strokes is not there."))

    out.append(_writable(book.folder, "correction"))
    return out


def _copy_like_its_map(ds, path, data):
    """The working copy against the map it corrects: the same bands, in the
    same order, with the same names, types and nodata. The correction of a
    thematic map is a thematic map, and a copy that is not the original band
    for band does not open the way the original does."""
    flag = None
    for b in range(1, ds.RasterCount + 1):
        if (ds.GetRasterBand(b).GetDescription() or "").lower() == FLAG_BAND_NAME:
            flag = b
    if flag is not None:
        return [Finding(NOTE, "the working copy still has the '%s' band of an "
                              "earlier build" % FLAG_BAND_NAME,
                        "it is moved to the file beside the copy the next "
                        "time Correct opens it, and the copy is left with the "
                        "bands of the map it corrects.")]
    source = str(data.get("source") or "").split("|")[0]
    if not source or not os.path.exists(source):
        return []
    try:
        src = gdal.Open(source)
    except Exception:
        src = None
    if src is None:
        return []
    wrong = []
    if src.RasterCount != ds.RasterCount:
        wrong.append("%d bands, the map has %d" % (ds.RasterCount,
                                                   src.RasterCount))
    else:
        for b in range(1, ds.RasterCount + 1):
            x, y = src.GetRasterBand(b), ds.GetRasterBand(b)
            if (x.GetDescription() or "") != (y.GetDescription() or ""):
                wrong.append("band %d is '%s', the map's is '%s'"
                             % (b, y.GetDescription(), x.GetDescription()))
            if x.DataType != y.DataType:
                wrong.append("band %d is %s, the map's is %s"
                             % (b, gdal.GetDataTypeName(y.DataType),
                                gdal.GetDataTypeName(x.DataType)))
            a, z = x.GetNoDataValue(), y.GetNoDataValue()
            if not (a == z or (a is not None and z is not None
                               and a != a and z != z)):
                wrong.append("band %d has nodata %s, the map's is %s"
                             % (b, z, a))
    src = None
    if wrong:
        return [Finding(NOTE, "the working copy is not the map it corrects "
                              "band for band",
                        "; ".join(wrong[:6]) + ". It opens differently from "
                        "the original.")]
    return [Finding(OK, "the working copy has the %d band%s of the map it "
                        "corrects, in its order" % (ds.RasterCount,
                                                    "" if ds.RasterCount == 1
                                                    else "s"))]


def _grid_words(gt):
    return "origin %g, %g, pixel %g x %g" % (gt[0], gt[3], gt[1], gt[5])


def _changes_beside(ds, path, data):
    """The record of which pixels a person changed, beside the copy, and
    the .qml the corrected map opens with."""
    out = []
    changes = changes_path_of(data, path)
    name = os.path.basename(changes)
    flagged = any((ds.GetRasterBand(b).GetDescription() or "").lower()
                  == FLAG_BAND_NAME for b in range(1, ds.RasterCount + 1))
    if not os.path.exists(long_path(changes)):
        if not flagged:
            out.append(Finding(NOTE, "%s is not beside the working copy" % name,
                               "the strokes still work; which pixels a person "
                               "changed is not known until it is there. Correct "
                               "starts a new, empty one when it opens."))
    else:
        try:
            rec = gdal.Open(changes)
        except Exception:
            rec = None
        if rec is None:
            out.append(Finding(BAD, "%s cannot be opened" % name, changes))
        elif (rec.RasterXSize, rec.RasterYSize) != (ds.RasterXSize,
                                                    ds.RasterYSize):
            out.append(Finding(BAD, "%s is not on the grid of the copy" % name,
                               "%d x %d pixels, the copy %d x %d. It is not "
                               "the record of this copy."
                               % (rec.RasterXSize, rec.RasterYSize,
                                  ds.RasterXSize, ds.RasterYSize)))
        elif pixel_grid(rec) != pixel_grid(ds):
            # a copy written by an earlier build for a picture with no
            # georeference: GDAL's default grid, which QGIS draws beside the
            # picture
            out.append(Finding(NOTE, "%s is not drawn where the copy is" % name,
                               "its grid is %s, the copy's %s. Correct puts it "
                               "on the grid of the copy the next time it opens."
                               % (_grid_words(pixel_grid(rec)),
                                  _grid_words(pixel_grid(ds)))))
        else:
            try:
                marked = band_marked(rec)
            except Exception:
                marked = None
            out.append(Finding(OK, "%s records %s pixel%s changed by a person"
                               % (name, "?" if marked is None else marked,
                                  "" if marked == 1 else "s")))
        rec = None
    style = style_of(path)
    if not os.path.exists(long_path(style)):
        out.append(Finding(NOTE, "%s is not beside the working copy"
                                 % os.path.basename(style),
                           "QGIS opens the corrected map without its classes "
                           "until it is there. Correct writes it when it opens."))
    else:
        out.append(Finding(OK, "%s is beside the copy: QGIS opens it with its "
                               "classes" % os.path.basename(style)))
    return out


def _moved_corrections(campaign):
    """Corrections the campaign manifest still lists and that have a campaign
    of their own, whose folder is not there."""
    out = []
    for item in campaign.data.get("corrections", []) or []:
        where = from_folder(item.get("moved_to"), campaign.folder)
        if where and not os.path.exists(where):
            out.append(Finding(NOTE, "correction '%s' was moved to its own "
                                     "campaign at %s, which is not there any "
                                     "more" % (item.get("name", "?"), where),
                               "the record in campaign.json is kept, with its "
                               "files, and nothing else depends on it."))
    return out


# =====================================================================
#  The report, and the window it is shown in
# =====================================================================
def reports_findings(owner):
    """The reports the manifest of a campaign or a correction lists whose
    folder is not there any more: moved, renamed or deleted by hand. Nothing
    at all while it lists none."""
    data = getattr(owner, "data", None) or {}
    folder = getattr(owner, "folder", None)
    if not folder or not data.get("reports"):
        return []
    gone = report_missing(data, folder)
    if not gone:
        return []
    return [Finding(NOTE, "%d report%s the manifest lists %s not there"
                    % (len(gone), "" if len(gone) == 1 else "s",
                       "is" if len(gone) == 1 else "are"),
                    ", ".join(str(e.get("folder") or "?") for e in gone[:4])
                    + (", ..." if len(gone) > 4 else ""))]


def more_findings(found, owner):
    """What the measuring modules have to say about this campaign or
    correction (measure.DOCTOR_CAMPAIGN and DOCTOR_CORRECTION): each one
    asked in turn, and one that fails says so instead of taking Check
    down with it."""
    out = []
    for ask in found or []:
        try:
            out.extend(ask(owner) or [])
        except Exception as err:
            out.append(Finding(NOTE, "a check of the measures could not run",
                               "%s: %s" % (getattr(ask, "__name__", "?"),
                                           err)))
    return out


def report(campaign, correction=None, campaign_too=True, more=None):
    """The report as text, with how many problems and notes it holds.

    campaign_too=False leaves the annotation campaign out altogether: the
    Check in CORRECTION reports on the correction and on what is running,
    and a line about the campaign there would answer a question nobody
    asked. more is {"campaign": [fn], "correction": [fn]}: what the
    measuring modules check, fn(owner) -> [Finding], added to each part."""
    more = more or {}
    machine = about_the_machine()
    camp = about_the_campaign(campaign) if campaign_too else []
    if campaign_too and campaign is not None:
        camp += more_findings(more.get("campaign"), campaign)
    fixes = about_the_correction(correction) if correction is not None else []
    if correction is not None:
        fixes += more_findings(more.get("correction"), correction)
    bad = [f for f in machine + camp + fixes if f.level == BAD]
    notes = [f for f in machine + camp + fixes if f.level == NOTE]
    lines = []
    if bad:
        lines.append("%d problem%s found." % (len(bad), "" if len(bad) == 1 else "s"))
    elif notes:
        lines.append("Nothing is broken. %d thing%s worth knowing."
                     % (len(notes), "" if len(notes) == 1 else "s"))
    else:
        lines.append("Everything checks out.")
    lines.append("")
    lines.append("WHAT IS RUNNING")
    lines.extend(str(f) for f in machine)
    if campaign_too:
        lines.append("")
        lines.append("THE CAMPAIGN")
        lines.extend(str(f) for f in camp)
    if correction is not None:
        lines.append("")
        lines.append("THE CORRECTION")
        lines.extend(str(f) for f in fixes)
    if campaign is not None or correction is not None:
        lines.append("")
        lines.append("WHERE")
    if campaign is not None:
        lines.append("  folder   %s" % campaign.folder)
        lines.append("  package  %s" % campaign.package_path)
    if correction is not None:
        lines.append("  correction  %s" % correction.folder)
        lines.append("  manifest    %s" % correction.manifest_path)
        lines.append("  copy        %s" % correction.working_path)
    if campaign is not None or correction is not None:
        where = log_path()
        if where:
            lines.append("  log      %s" % where)
    lines.append("")
    lines.append("Paste this into a bug report. It says which build it is, what "
                 "it was running on,")
    lines.append("and what the campaign looked like, which is most of what "
                 "anybody needs to begin.")
    # pasted into public issues: the home folder, and with it the name of
    # whoever is running, is written ~
    return without_home("\n".join(lines)), len(bad), len(notes)


def report_html(text):
    """The report as the window shows it: the problems first, in the colour
    of a problem, then every line in its section with its mark coloured,
    wrapped to the window. The text itself, the one that is copied, is not
    changed: this is only how it is read."""
    c = palette_colours()
    ink = {"PROBLEM": c["danger"], "note": c["step_ink"] if not c["dark"]
           else "#e6c86e", "ok": c["dim"]}
    # A finding is a row of two cells, its mark and its words, so every
    # message starts at the same column and a long one wraps under itself,
    # not back under the mark: one space after the mark left them ragged.
    try:
        mark = QFontMetrics(fixed_font()).horizontalAdvance("problem") + 12
    except Exception:
        mark = 64

    def finding(tag, colour, words, dim=None):
        return ("<table cellspacing='0' cellpadding='0' "
                "style='margin-left:12px'><tr>"
                "<td width='%d' valign='top' style='white-space:nowrap'>"
                "%s</td><td valign='top'%s>%s</td></tr></table>"
                % (mark, "<span style='color:%s'><b>%s</b></span>"
                   % (colour, tag) if tag else "",
                   " style='color:%s'" % dim if dim else "", words))
    rows, problems, level = [], [], None
    lines = text.splitlines()[1:]           # the first is the headline
    for line in lines:
        bare = line.strip()
        if not bare:
            rows.append("<div>&nbsp;</div>")
            level = None
            continue
        if not line.startswith(" "):
            rows.append("<div style='margin-top:4px'><b>%s</b></div>"
                        % escape(bare))
            level = None
            continue
        word = bare.split()[0]
        if word in ink and line.startswith("  " + word):
            level = word
            rest = bare[len(word):].strip()
            row = finding("problem" if word == "PROBLEM" else word,
                          ink[word], escape(rest))
            rows.append(row)
            if word == "PROBLEM":
                problems.append(row)
        else:
            # the detail under a finding, under its words, or a line of WHERE
            row = finding("", "", escape(bare), c["dim"]) if level else \
                ("<div style='margin-left:12px; color:%s'>%s</div>"
                 % (c["text"], escape(bare)))
            rows.append(row)
            if level == "PROBLEM":
                problems.append(row)
    head = ""
    if problems:
        head = ("<div><b>What is wrong</b></div>" + "".join(problems)
                + "<div>&nbsp;</div><div><b>The whole report</b></div>")
    return head + "".join(rows)


class Report(QDialog):
    """The report, in a window, with one button that matters: Copy."""

    def __init__(self, parent, text, bad, notes):
        super().__init__(parent)
        self.setWindowTitle("%s: Check" % NAME)
        self.text = text
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        headline = ("%d problem%s found" % (bad, "" if bad == 1 else "s") if bad
                    else "Nothing is broken" if notes else "Everything checks out")
        top = QLabel(headline)
        font = top.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.1)
        top.setFont(font)
        if bad:
            top.setObjectName("warn")
        outer.addWidget(top)
        if notes and not bad:
            said = QLabel("%d thing%s worth knowing, marked note below."
                          % (notes, "" if notes == 1 else "s"))
            said.setObjectName("quiet")
            outer.addWidget(said)
        # Read as a list and wrapped to the window, in the fixed font of the
        # system so the columns of the versions line up. A raw dump would be cut
        # off at the right edge behind a scroll bar, with problems, notes and
        # fine lines all alike.
        box = QTextBrowser()
        box.setReadOnly(True)
        box.setOpenLinks(False)
        box.setFont(fixed_font())
        box.setHtml(report_html(text))
        box.setMinimumWidth(TROUBLE_W)
        box.setMinimumHeight(360)
        self.view = box
        outer.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        copy = bb.addButton("Copy report", QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(self.copy)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    def copy(self):
        try:
            QApplication.clipboard().setText(self.text)
            log("the check report is on the clipboard")
        except Exception as err:
            log("the report could not be copied: %s" % err)


def check(parent, campaign, correction=None, campaign_too=True, more=None):
    """Look everything over and show it. Changes nothing.

    The work happens on the thread that draws the window, so on a large campaign
    the window stops answering for a few seconds. An hourglass is the answer: it
    says "working", which is the difference between waiting and believing the
    program has died. Doing it on another thread would mean reading QGIS
    layers from a thread that does not own them.
    """
    try:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    except Exception:
        pass
    try:
        text, bad, notes = report(campaign, correction, campaign_too, more)
    finally:
        try:
            QApplication.restoreOverrideCursor()
        except Exception:
            pass
    for line in text.splitlines():
        if line.strip():
            log("check: " + line.strip())
    d = Report(parent, text, bad, notes)
    d.setWindowModality(Qt.WindowModality.WindowModal)
    d.resize(TROUBLE_W + 60, 560)
    run_dialog(d)           # one place in the program knows how Qt spells exec
    return bad
