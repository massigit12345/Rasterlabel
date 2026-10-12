"""rasterlabel.ui_time

Time: how long the drawing took, from the journal the panel keeps.

Two halves. The first is the wiring of the journal into the program: the
journal of the campaign, shared by Annotate and Objects, and the journal of
each correction, beside its operations.csv; the "journal" block of a
manifest, written the moment journal.csv really begins and never before; the
signals that say QGIS went to the background and came back, and the
heartbeat of a view that moves; the switch in Annotate's settings; the quiet
line under the coverage that says how long today has been.

The second is the report. TimeSetup asks which readings drawn from scratch,
which correction, which frames and which idle limit, and time_write writes,
in a folder of its own under reports/time/:

    time_per_frame.csv    one row per source, reading and frame
    time_per_class.csv    one row per source, reading, frame and class, and
                          the readings pooled over the frames ("*")
    time_paired.csv       drawing from scratch against correcting, frame by
                          frame, when a correction on the grid is chosen
    time_frames.gpkg      the frames with their minutes per hectare, + .qml
    time_summary.json     the rule, the inputs with their sha256, the totals
                          at 30, 60 and 120 s, the warnings and the design

The numbers come from effort.py, which is pure; what is read here is the
frames and the polygons of the package (read only, through OGR) and the
journals. Nothing in the campaign or the correction is changed but the list
of reports in its manifest.
"""
import csv
import io
import json
import os

from datetime import datetime, timezone

from osgeo import ogr, osr
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QApplication, QButtonGroup, QComboBox,
                                 QDialog, QGridLayout, QHBoxLayout, QLabel,
                                 QPushButton, QSpinBox)
from qgis.core import (QgsCoordinateReferenceSystem, QgsDistanceArea,
                       QgsGeometry, QgsProject, QgsVectorLayer)

from .constants import (BOOTSTRAP_MIN_FRAMES, CLOSED_SHARE,
                        CORRECTION_MANIFEST, HEARTBEAT_S, IDLE_DEFAULT_S,
                        IDLE_SENSITIVITY, JOURNAL_NAME, MARK_ACTIONS)
from .compat import run_dialog
from .project import canvas
from .errors import hook, log, trouble
from .naming import csv_untext_row, from_folder
from .reports import (report_abandon, report_csv, report_entry, report_finish,
                      report_folder, report_folder_guess, report_header,
                      report_headline, report_inputs, report_json,
                      report_open_problem, report_register, report_stamp,
                      report_text, report_utc)
from .theme import hold_shape, keep_shape, short_combo, titled
from .widgets import narrow_radio, narrow_tick
from .campaign import (Campaign, _area_of_union, _clipped, campaign_read_only,
                       frame_design, manifest_journal, operator_word,
                       pass_number, reading_label, reading_shares,
                       readings_in)
from .journal import (Journal, journal_line, journal_read,
                      journal_session_id)
from .layers import add_report_layer
from .correction import CorrectionCampaign, peek_correction, recent_corrections
from .effort import (EFFORT_CLASS_COLUMNS, EFFORT_DESIGN_COLUMNS,
                     EFFORT_DESIGN_NOTES, EFFORT_FRAME_COLUMNS,
                     EFFORT_PAIRED_COLUMNS, effort_attribute, effort_by_tile,
                     effort_changed_by, effort_class_table,
                     effort_frame_finder, effort_frame_table,
                     effort_grid_relation, effort_legacy_rows,
                     effort_paired_table, effort_parameters, effort_parse_utc,
                     effort_per_ha, effort_sensitivity, effort_totals)
from .dialogs import ReportWindow, report_part, report_where_rows


# The files of a report, by what they are.
TIME_FILES = {"per_frame": "time_per_frame.csv",
              "per_class": "time_per_class.csv",
              "paired": "time_paired.csv",
              "frames": "time_frames.gpkg",
              "style": "time_frames.qml",
              "summary": "time_summary.json"}
TIME_FRAMES_LAYER = "time_frames"
# The three ways of choosing the frames, in the order the window offers them.
TIME_FRAME_RULES = (("read", "every frame read"),
                    ("closed", "closed only"),
                    ("both", "drawn and corrected"))
TIME_GRID_WORDS = {
    "same": "✓ same grid as the campaign",
    "aligned_crs": "⚠ same CRS, pixels not aligned: frames compared by "
                   "position",
    "other": "✘ another CRS: no pairing"}
TIME_SWITCH_TIP = (
    "Write one line per saved action into journal.csv beside the campaign:\n"
    "when it started and ended, who, which pass, frame and class. No keys,\n"
    "no screen, nothing else. Used by Time, under Measure.\n\n"
    "Off, nothing more is written, and the manifest says so.")
TIME_NO_JOURNAL = ("No journal: nothing to measure. Tick 'keep a journal of "
                   "working time' in Annotate's settings.")
TIME_NOT_YET = ("No journal yet: nothing to measure. It begins with the first "
                "stroke, point or box drawn in Annotate or Objects.")
# Graduated colours of the map of minutes per hectare, light to dark.
TIME_RAMP = ("#fff5d6", "#fdd49e", "#fc8d59", "#d7301f", "#7f0000")


#  The journal, wired in
# =====================================================================
def time_block(data):
    """The "journal" block of a manifest, or None."""
    block = data.get("journal") if isinstance(data, dict) else None
    return block if isinstance(block, dict) else None


def time_wanted(data):
    """Whether a journal is to be kept: yes unless the manifest says off."""
    block = time_block(data)
    return True if block is None else block.get("on", True) is not False


def _time_moment(text):
    seconds = effort_parse_utc(text)
    if seconds is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(seconds, timezone.utc)


def _time_seed(journal, path):
    """What earlier sessions of today counted, so the quiet line starts from
    the day so far and not from zero."""
    try:
        if os.path.getsize(path) > 64 * 1024 * 1024:
            return
    except OSError:
        return
    today = datetime.now().astimezone().date()
    rows = []
    for r in journal_read(path):
        s = effort_parse_utc(r.get("t_utc"))
        if s is None:
            continue
        if datetime.fromtimestamp(s, timezone.utc).astimezone().date() \
                == today:
            rows.append(r)
    if not rows:
        return
    res = effort_attribute(rows, IDLE_DEFAULT_S)
    per_op, per_frame = {}, {}
    for (tile, op, _pass), f in res["frames"].items():
        per_op[op] = per_op.get(op, 0.0) + f["active_s"]
        key = (op, tile or "")
        per_frame[key] = per_frame.get(key, 0.0) + f["active_s"]
    journal.seed(per_op, per_frame)


def time_make_journal(folder, session, module, data, save):
    """The journal of one folder. It has begun when the manifest has its
    block and journal.csv is there; otherwise it waits for the first mark,
    and only then is the block written into data and save() called."""
    path = os.path.join(folder, JOURNAL_NAME)
    begun = time_block(data) is not None and os.path.isfile(path)

    def start(journal, first_utc):
        if time_block(data) is None or not os.path.isfile(journal.path):
            data["journal"] = manifest_journal(_time_moment(first_utc))
            try:
                save()
            except Exception as err:
                log("the manifest could not be told that the journal of "
                    "working time began: %s" % err)
            log("journal of working time begun: %s" % journal.path)

    journal = Journal(folder, session, module, operator_word=operator_word,
                      pass_number=pass_number, complain=log,
                      held=not begun, on_start=start)
    journal.switch(time_wanted(data))
    if os.path.isfile(path):
        _time_seed(journal, path)
    return journal


def time_campaign_journal(panel):
    """The journal of the campaign open in the panel, shared by Annotate and
    Objects, made the first time it is asked for. None with no campaign."""
    campaign = getattr(panel, "campaign", None)
    if campaign is None or not getattr(campaign, "folder", None):
        return None
    held = getattr(panel, "_time_journal", None)
    if held is not None and held[0] is campaign:
        return held[1]
    journal = time_make_journal(campaign.folder, journal_session_id(panel),
                                "annotate", campaign.data, campaign.save)
    panel._time_journal = (campaign, journal)
    return journal


def time_correction_journal(section):
    """The journal of the correction Correct is working on, beside its
    operations.csv. A correction still kept inside an annotation campaign has
    no manifest of its own: its journal is written, and no manifest claims
    it."""
    path = getattr(section, "path", "") or ""
    if not path:
        return None
    folder = os.path.dirname(path)
    book = getattr(section, "book", None)
    own = False
    try:
        own = bool(section.own_book())
    except Exception:
        own = False
    data = book.data if own and isinstance(getattr(book, "data", None),
                                           dict) else {}
    save = book.save if own else (lambda: None)
    return time_make_journal(folder, journal_session_id(
        getattr(section, "panel", None)), "correct", data, save)


def time_watch(section, journal, write):
    """QGIS in front or behind, and the view moving: focus_out and focus_in
    rows, and a "view" row at most every HEARTBEAT_S seconds while the map is
    moved. Connected through hook(), so they go with the module."""
    state = {"active": True}

    def changed(st, *rest):
        active = st == Qt.ApplicationState.ApplicationActive
        if active == state["active"]:
            return
        state["active"] = active
        write("focus_in" if active else "focus_out")

    def moved(*args):
        quiet = journal.quiet_s()
        if quiet is None or quiet >= HEARTBEAT_S:
            write("view")

    app = QApplication.instance()
    try:
        if app is not None and hasattr(app, "applicationStateChanged"):
            hook(section, app.applicationStateChanged, changed)
    except Exception as err:
        log("the journal does not hear QGIS go behind: %s" % err)
    try:
        view = canvas()
        if view is not None and hasattr(view, "extentsChanged"):
            hook(section, view.extentsChanged, moved)
    except Exception as err:
        log("the journal does not hear the view move: %s" % err)


def time_note(section, module, action, timing=None, **fields):
    """One row of the campaign's journal from Annotate or Objects, with the
    reading the panel holds and the frame in hand unless the caller says
    otherwise. Never raises: a journal is never a reason for a stroke to
    fail."""
    if not getattr(section, "time_opened", False):
        # what a module does to itself while it is being built is not work
        return None
    try:
        panel = section.panel
        journal = time_campaign_journal(panel)
        if journal is None or not journal.on:
            return None
        if "operator" not in fields:
            fields["operator"] = panel.who_is_drawing()
        if "pass_no" not in fields:
            fields["pass_no"] = panel.which_pass()
        if "tile_id" not in fields:
            tid = ""
            ask = getattr(section, "current_tile_id", None)
            if callable(ask) and getattr(section, "tiled", False):
                try:
                    tid = ask() or ""
                except Exception:
                    tid = ""
            fields["tile_id"] = tid
        row = journal.note(action, timing, module=module, **fields)
        time_show_line(section, journal)
        return row
    except Exception as err:
        log("the journal of working time missed a row: %s" % err)
        return None


def time_take(section):
    """The time a map tool handed to the section for the stroke in hand,
    taken once (the section's pop_timing), or None."""
    pop = getattr(section, "pop_timing", None)
    try:
        return pop() if callable(pop) else None
    except Exception:
        return None


def time_mark(section, action, **fields):
    """One row from a place in Annotate or Objects where something was done.

    Through the section's note(), which a stand-in of the suites may not
    have: then nothing is written. A mark takes the time the map tool handed
    over, unless the caller gives one; a row of context never does, so an
    autosave inside a stroke cannot take the stroke's time from it."""
    note = getattr(section, "note", None)
    if not callable(note):
        return None
    if "timing" in fields:
        timing = fields.pop("timing")
    else:
        timing = time_take(section) if action in MARK_ACTIONS else None
    return note(action, timing=timing, **fields)


def time_centre(geom):
    """(x, y) of the middle of a geometry, or (None, None)."""
    try:
        c = geom.centroid().asPoint()
        return c.x(), c.y()
    except Exception:
        return None, None


def time_vertices(geom):
    """How many vertices a stroke was drawn with, or None."""
    try:
        return int(geom.constGet().nCoordinates())
    except Exception:
        return None


def time_open(section, module):
    """A module opened on the campaign: the "open" row, and the signals."""
    journal = time_campaign_journal(section.panel)
    if journal is None:
        return None
    section.time_opened = True
    time_note(section, module, "open", tile_id="")
    time_watch(section, journal, lambda action: section.note(action))
    return journal


def time_close(section, module):
    """A module closing: the "close" row, and every waiting row out."""
    journal = time_campaign_journal(section.panel)
    if journal is None:
        return
    time_note(section, module, "close")
    journal.flush()


def time_show_line(section, journal=None):
    """The quiet line under the coverage: "active 1 h 12 min today · this
    frame 6 min", hidden while there is no journal."""
    label = getattr(section, "time_line", None)
    if label is None:
        return
    try:
        journal = journal or time_campaign_journal(section.panel)
        who = operator_word(section.panel.who_is_drawing())
        tile = ""
        if getattr(section, "tiled", False):
            try:
                tile = section.current_tile_id() or ""
            except Exception:
                tile = ""
        text = journal_line(journal, who, tile) if journal is not None else ""
        label.setText(text)
        label.setVisible(bool(text))
    except Exception as err:
        log("cannot show the active time: %s" % err)


def time_switch(panel, on, section=None):
    """The tick box in Annotate's settings. Off, the journal stops and the
    manifest says "on": false; on, it goes on, and the manifest says so
    again. A campaign that never kept a journal and is switched off gets a
    block saying off, which is true and keeps the choice."""
    campaign = getattr(panel, "campaign", None)
    if campaign is None:
        return
    journal = time_campaign_journal(panel)
    on = bool(on)
    if journal is not None and journal.on and not on and section is not None:
        time_note(section, "annotate", "close")
        journal.flush()
    block = time_block(campaign.data)
    if block is None:
        if not on:
            campaign.data["journal"] = dict(manifest_journal(), on=False)
    else:
        block["on"] = on
    if block is not None or not on:
        try:
            campaign.save()
        except Exception as err:
            log("cannot write the journal switch into the manifest: %s" % err)
    if journal is not None:
        journal.switch(on)
        if on and section is not None:
            time_note(section, "annotate", "open", tile_id="")
    log("journal of working time %s" % ("on" if on else "off: nothing more "
                                        "is written"))
    if section is not None:
        time_show_line(section, journal)


#  Reading the campaign for a report
# =====================================================================
def time_srs(text):
    """An osr system from a crs text of a manifest, or None."""
    if not text:
        return None
    s = osr.SpatialReference()
    try:
        if s.SetFromUserInput(str(text)) != 0:
            return None
    except Exception:
        return None
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def time_same_crs(a, b):
    """Whether two crs texts mean one system, as osr sees it."""
    sa, sb = time_srs(a), time_srs(b)
    if sa is None or sb is None:
        return str(a or "").strip().upper() == str(b or "").strip().upper()
    return bool(sa.IsSame(sb))


def _time_ring(geom):
    """The outer ring of a frame as [(x, y)]."""
    g = geom
    if g.GetGeometryCount() and g.GetGeometryType() not in (
            ogr.wkbLinearRing,):
        part = g.GetGeometryRef(0)
        if part is not None and part.GetGeometryCount():
            part = part.GetGeometryRef(0)
        g = part if part is not None else g
    return [(g.GetX(i), g.GetY(i)) for i in range(g.GetPointCount())]


def _time_ellipsoid_m2(wkt, srs):
    try:
        crs = QgsCoordinateReferenceSystem.fromWkt(srs.ExportToWkt())
        area = QgsDistanceArea()
        area.setSourceCrs(crs, QgsProject.instance().transformContext())
        area.setEllipsoid(crs.ellipsoidAcronym() or "EPSG:7030")
        return float(area.measureArea(QgsGeometry.fromWkt(wkt)))
    except Exception as err:
        log("cannot measure a frame on the ellipsoid: %s" % err)
        return None


def time_frames(package):
    """The frames of a package: {tile_id: {"ring", "wkt", "planar", "m2"}},
    and the system of the tiles. m2 is the ground: the plane area in metres
    when the system is projected, on the ellipsoid when it is not."""
    out, srs = {}, None
    ds = ogr.Open(package, 0) if os.path.isfile(package) else None
    if ds is None:
        return out, srs
    try:
        lyr = ds.GetLayerByName("tiles")
        if lyr is None:
            return out, srs
        srs = lyr.GetSpatialRef()
        srs = srs.Clone() if srs is not None else None
        unit = 1.0
        projected = srs is not None and bool(srs.IsProjected())
        if projected:
            try:
                unit = float(srs.GetLinearUnits() or 1.0)
            except Exception:
                unit = 1.0
        idx = lyr.GetLayerDefn().GetFieldIndex("tile_id")
        lyr.ResetReading()
        for f in lyr:
            tid = f.GetField(idx) if idx >= 0 else None
            g = f.GetGeometryRef()
            if tid is None or str(tid) == "" or g is None or g.IsEmpty():
                continue
            tid = str(tid)
            if tid in out:
                continue
            planar = g.GetArea()
            wkt = g.ExportToWkt()
            m2 = planar * unit * unit if projected or srs is None \
                else _time_ellipsoid_m2(wkt, srs)
            out[tid] = {"ring": _time_ring(g), "wkt": wkt, "planar": planar,
                        "m2": m2, "geom": g.Clone()}
    finally:
        ds = None
    return out, srs


def time_class_areas(package, frames, tiled=True):
    """{(tile, operator, pass, code): m2} of every reading's class in every
    frame: the union of its polygons clipped to the frame, the way the panel
    measures a frame, in metres of the ground (the plane area scaled by the
    frame's own). In a campaign without frames, the reading's whole class,
    under the frame "*"."""
    out = {}
    ds = ogr.Open(package, 0) if os.path.isfile(package) else None
    if ds is None:
        return out
    try:
        lyr = ds.GetLayerByName("polygons")
        if lyr is None:
            return out
        defn = lyr.GetLayerDefn()
        at = {n: defn.GetFieldIndex(n) for n in ("tile_id", "operator",
                                                 "pass_no", "class_code")}
        pieces = {}
        lyr.ResetReading()
        for f in lyr:
            g = f.GetGeometryRef()
            if g is None or g.IsEmpty():
                continue
            code = f.GetField(at["class_code"]) if at["class_code"] >= 0 \
                else None
            try:
                code = int(code)
            except (TypeError, ValueError):
                continue
            op = operator_word(f.GetField(at["operator"])
                               if at["operator"] >= 0 else None)
            p = str(pass_number(f.GetField(at["pass_no"])
                                if at["pass_no"] >= 0 else None))
            if tiled:
                tid = f.GetField(at["tile_id"]) if at["tile_id"] >= 0 \
                    else None
                tid = None if tid is None else str(tid)
                if tid not in frames:
                    continue
                piece = _clipped(g, frames[tid]["geom"])
                if piece is None or not piece.GetArea() > 0:
                    continue
            else:
                tid, piece = "*", g.Clone()
            pieces.setdefault((tid, op, p, code), []).append(piece)
        for key, held in pieces.items():
            planar = _area_of_union(held)
            frame = frames.get(key[0])
            if frame and frame["planar"] > 0 and frame["m2"] is not None:
                out[key] = planar * frame["m2"] / frame["planar"]
            else:
                out[key] = planar
    finally:
        ds = None
    return out


def time_read_operations(path):
    """The rows of an operations.csv as dicts, or [] when there is none."""
    try:
        with io.open(path, encoding="utf-8", newline="") as fh:
            return [csv_untext_row(r) for r in csv.DictReader(fh)]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def time_correction_choices(panel=None, campaign=None):
    """[(manifest path, words)] of the corrections a report can be set
    against: the one open in the panel, the campaign's own, then the recent
    ones, the same sources Open correction lists."""
    seen, out = set(), []

    def add(path):
        if not path:
            return
        key = os.path.normcase(os.path.abspath(path))
        if key in seen or not os.path.isfile(path):
            return
        seen.add(key)
        data = peek_correction(path) or {}
        name = data.get("name") or os.path.basename(os.path.dirname(path))
        who = str(data.get("operator") or "").strip().upper()
        out.append((path, "%s · %s" % (name, who) if who else name))

    book = getattr(panel, "correction", None) if panel is not None else None
    if book is not None and getattr(book, "folder", None):
        add(os.path.join(book.folder, CORRECTION_MANIFEST))
    data = getattr(campaign, "data", None) or {}
    for item in data.get("corrections") or []:
        moved = item.get("moved_to") if isinstance(item, dict) else None
        if moved:
            moved = from_folder(moved, getattr(campaign, "folder", None))
            add(moved if moved.endswith(".json")
                else os.path.join(moved, CORRECTION_MANIFEST))
    try:
        for path in recent_corrections():
            add(path)
    except Exception as err:
        log("cannot list the recent corrections: %s" % err)
    return out


def time_grid_of(manifest_path):
    data = peek_correction(manifest_path) or {}
    grid = data.get("grid")
    return grid if isinstance(grid, dict) else {}


def time_relation(campaign_data, manifest_path):
    """"same", "aligned_crs" or "other" between a campaign and a correction,
    or None when either is missing."""
    if not campaign_data or not manifest_path:
        return None
    return effort_grid_relation(campaign_data.get("grid") or {},
                                time_grid_of(manifest_path), time_same_crs)


def time_scratch_readings(folder, data):
    """{(operator, pass): frames with journal time} of the readings drawn in
    a campaign, the ones only in the package listed with 0."""
    counts = {}
    path = os.path.join(folder, JOURNAL_NAME)
    rows = [r for r in journal_read(path)
            if r.get("module") in ("annotate", "objects")] \
        if os.path.isfile(path) else []
    if rows:
        res = effort_attribute(rows, IDLE_DEFAULT_S,
                               default_tile=None if data.get("with_tiles")
                               else "*")
        for (tile, op, p), f in res["frames"].items():
            key = (operator_word(op), pass_number(p))
            counts[key] = counts.get(key, 0) + 1
    try:
        for key in readings_in(os.path.join(folder, Campaign.PACKAGE)):
            counts.setdefault(key, 0)
    except Exception as err:
        log("cannot read the readings of the campaign: %s" % err)
    return counts


#  The report
# =====================================================================
def _time_names(classes):
    out = {}
    for c in classes or []:
        try:
            out[int(c.get("code"))] = str(c.get("name") or "")
        except (TypeError, ValueError, AttributeError):
            continue
    return out


def _time_codes(classes):
    return {name: code for code, name in _time_names(classes).items()}


def time_target(owner_folder, chosen=None):
    """(tmp, final) of a new report: under reports/time/ as reports.py
    makes it, or the folder typed in the window when it is another."""
    if chosen:
        base = os.path.join(owner_folder, "reports", "time")
        if os.path.normcase(os.path.abspath(os.path.dirname(chosen))) \
                != os.path.normcase(os.path.abspath(base)):
            final = chosen
            n = 1
            while os.path.exists(final) or os.path.exists(final + ".tmp"):
                n += 1
                final = "%s-%d" % (chosen, n)
            os.makedirs(final + ".tmp")
            return final + ".tmp", final
    return report_folder(owner_folder, "time")


def time_path_problem(owner_folder, chosen=None, windows=None):
    """"" if QGIS will be able to open the map of the frames the report
    writes, or why not, before a folder is made: on Windows a path of 260
    characters or more is not one SQLite opens (see report_open_problem)."""
    folder = report_folder_guess(owner_folder, "time", None, chosen)
    return report_open_problem(folder, [TIME_FILES["frames"]], windows)


def time_write_gpkg(path, frames, srs, values):
    """The frames with their numbers, one polygon each: the map figure."""
    drv = ogr.GetDriverByName("GPKG")
    ds = drv.CreateDataSource(path)
    if ds is None:
        raise IOError("cannot write %s" % path)
    try:
        lyr = ds.CreateLayer(TIME_FRAMES_LAYER, srs, ogr.wkbPolygon,
                             ["GEOMETRY_NAME=geom"])
        lyr.CreateField(ogr.FieldDefn("tile_id", ogr.OFTString))
        for name in ("frame_ha", "scratch_s", "correct_s", "scratch_min_ha",
                     "correct_min_ha", "ratio"):
            lyr.CreateField(ogr.FieldDefn(name, ogr.OFTReal))
        for tile in sorted(values):
            frame = frames.get(tile)
            if frame is None:
                continue
            f = ogr.Feature(lyr.GetLayerDefn())
            f.SetField("tile_id", tile)
            for name, v in values[tile].items():
                if v is not None and v == v:
                    f.SetField(name, float(v))
            g = frame["geom"].Clone()
            if g.GetGeometryType() != ogr.wkbPolygon:
                g = ogr.ForceToPolygon(g)
            f.SetGeometry(g)
            lyr.CreateFeature(f)
            f = None
        lyr = None
    finally:
        ds = None
    return path


def _time_rgb(colour):
    c = colour.lstrip("#")
    return "%d,%d,%d,255" % (int(c[0:2], 16), int(c[2:4], 16),
                             int(c[4:6], 16))


def time_qml(values, field="scratch_min_ha"):
    """The style of the map of the frames, as a .qml QGIS reads beside the
    file: graduated colours on the minutes per hectare, up to five classes
    of equal count, light for quick frames and dark for slow ones. Written
    as text, the way the styles of the rasters are, so it needs nothing of
    QGIS to be written. None when no frame has a value."""
    values = sorted(v for v in values
                    if isinstance(v, (int, float)) and v == v)
    if not values:
        return None
    k = min(len(TIME_RAMP), len(values))
    edges = [values[int(round(i * (len(values) - 1) / float(k)))]
             for i in range(k)] + [values[-1]]
    ranges, symbols = [], []
    for i in range(k):
        lo, hi = edges[i], edges[i + 1]
        colour = _time_rgb(TIME_RAMP[i * (len(TIME_RAMP) - 1)
                                     // max(1, k - 1)])
        ranges.append('      <range lower="%.6f" upper="%.6f" symbol="%d" '
                      'label="%.1f - %.1f min/ha" render="true"/>'
                      % (lo, hi, i, lo, hi))
        props = (("color", colour), ("outline_color", "51,51,51,255"),
                 ("outline_style", "solid"), ("outline_width", "0.3"),
                 ("outline_width_unit", "MM"), ("style", "solid"))
        symbols.append(
            '      <symbol type="fill" name="%d" alpha="1" '
            'clip_to_extent="1" force_rhr="0">\n'
            '        <layer class="SimpleFill" enabled="1" locked="0" '
            'pass="0">\n'
            '          <Option type="Map">\n%s\n          </Option>\n%s\n'
            '        </layer>\n      </symbol>'
            % (i, "\n".join('            <Option name="%s" type="QString" '
                            'value="%s"/>' % kv for kv in props),
               "\n".join('          <prop k="%s" v="%s"/>' % kv
                         for kv in props)))
    return ("<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n"
            '<qgis version="3.36.0" styleCategories="Symbology">\n'
            '  <renderer-v2 type="graduatedSymbol" attr="%s" '
            'graduatedMethod="GraduatedColor" symbollevels="0" '
            'forceraster="0" enableorderby="0">\n'
            '    <ranges>\n%s\n    </ranges>\n'
            '    <symbols>\n%s\n    </symbols>\n'
            '  </renderer-v2>\n</qgis>\n'
            % (field, "\n".join(ranges), "\n".join(symbols)))


def time_plan_owner(kind, folder, data):
    return {"kind": kind, "id": data.get("id", ""),
            "name": data.get("name", ""), "folder": folder}


class TimeCancelled(Exception):
    """Raised inside time_write when canceled() says stop."""


def _time_check(canceled):
    if canceled is not None and canceled():
        raise TimeCancelled("Cancelled: nothing was written.")


def time_write(plan, canceled=None):
    """Write a report of working time. plan is what TimeSetup.plan() gives:

    campaign      the campaign's folder, or None
    readings      [(operator, pass)] drawn from scratch
    correction    the correction's manifest path, or None
    idle_s        the idle limit T
    frames        "read", "closed" or "both"
    owner         "campaign" or "correction": whose reports/ it goes in
    folder        the folder chosen in the window, or None
    maps          whether to load the map of the frames into QGIS
    live          the open Campaign or CorrectionCampaign of the owner, whose
                  manifest is told of the report; None to read it from disk
    register      False to leave the owner's manifest alone (the report is
                  not listed in it): what the Processing algorithm does

    canceled, when given, is called between the steps; when it returns True
    TimeCancelled is raised and nothing is left behind.

    Returns {"folder", "files", "headline", "summary", "frames", "paired",
    "warnings"}."""
    _time_check(canceled)
    idle = int(plan.get("idle_s") or IDLE_DEFAULT_S)
    limits = sorted(set([idle] + list(IDLE_SENSITIVITY)))
    warnings, notes, skipped = [], [], {}
    camp_folder = plan.get("campaign")
    camp_data, package = {}, None
    frames, srs, class_m2, coverage, designs = {}, None, {}, {}, {}
    tiled = True
    inputs = []
    if camp_folder:
        # the package is read below by path; the datasource goes at once
        camp_data = campaign_read_only(camp_folder)[0]
        package = os.path.join(camp_folder, Campaign.PACKAGE)
        tiled = bool(camp_data.get("with_tiles", True))
        if tiled:
            frames, srs = time_frames(package)
        else:
            _, srs = time_frames(package)
        class_m2 = time_class_areas(package, frames, tiled)
        if tiled:
            for tile, by in reading_shares(package).items():
                for (op, p), share in by.items():
                    coverage[(tile, op, str(p))] = share
        designs = frame_design(package) if tiled else {}
        inputs.append(package)
    frame_m2 = {t: v["m2"] for t, v in frames.items()}
    names = _time_names(camp_data.get("classes"))
    chosen = {(operator_word(r[0]), str(pass_number(r[1])))
              for r in plan.get("readings") or []}

    # drawn from scratch
    s_rows, s_res, s_keys = [], None, []
    if camp_folder:
        jpath = os.path.join(camp_folder, JOURNAL_NAME)
        if os.path.isfile(jpath):
            inputs.insert(0, jpath)
            s_rows = [r for r in journal_read(jpath)
                      if r.get("module") in ("annotate", "objects")]
        s_res = effort_sensitivity(s_rows, limits, None,
                                   None if tiled else "*")
        warnings.extend(s_res[idle]["warnings"])
        timed = {k for k in s_res[idle]["frames"] if k[1:] in chosen}
        drawn = {(k[0], k[1], k[2]) for k in class_m2 if k[1:3] in chosen}
        drawn |= {k for k, share in coverage.items()
                  if k[1:] in chosen and share > 0}
        if not tiled:
            for k in list(drawn):
                frame_m2.setdefault(k, sum(
                    v for c, v in class_m2.items() if c[:3] == k))
        s_keys = sorted(timed | drawn, key=lambda k: tuple(map(str, k)))
        before = [k for k in s_keys if k not in timed]
        if before:
            notes.append(
                "%d frame%s of the chosen readings %s drawn before the "
                "journal began, or with it off: %s time is not recorded "
                "(journal = 0, the time left empty, never zero)"
                % (len(before), "" if len(before) == 1 else "s",
                   "was" if len(before) == 1 else "were",
                   "its" if len(before) == 1 else "their"))
        if not s_rows:
            notes.append("this campaign has no journal of working time: "
                         "nothing drawn from scratch is measured")

    _time_check(canceled)
    # corrected
    c_res, c_keys, c_rows, changed, c_class = None, [], [], {}, {}
    c_data, relation, estimated = {}, None, 0
    c_path = plan.get("correction")
    c_folder = os.path.dirname(c_path) if c_path else None
    if c_path:
        with io.open(c_path, encoding="utf-8") as fh:
            c_data = json.load(fh)
        relation = time_relation(camp_data, c_path) if camp_folder else None
        cj = os.path.join(c_folder, JOURNAL_NAME)
        ops_path = os.path.join(c_folder, "operations.csv")
        if os.path.isfile(cj):
            inputs.append(cj)
            c_rows = [r for r in journal_read(cj)
                      if r.get("module") == "correct"]
        ops = time_read_operations(ops_path)
        if os.path.isfile(ops_path):
            inputs.append(ops_path)
        refs = {str(r.get("ref") or "") for r in c_rows
                if r.get("action") == "correct"}
        missing = [r for r in ops if str(r.get("n") or "") not in refs]
        if not c_rows and ops:
            c_rows, bad = effort_legacy_rows(ops, _time_codes(
                c_data.get("classes")))
            estimated = 1
            warnings.append(
                "the correction has no journal: its time is estimated from "
                "the end of each stroke in operations.csv, to the second, "
                "with no start and no pauses (estimated = 1)")
            if bad:
                warnings.append("%d rows of operations.csv have no readable "
                                "time and are left out" % bad)
        elif missing:
            notes.append(
                "%d stroke%s of the correction %s no row in its journal "
                "(made before it began, or with it off): %s time is not "
                "recorded" % (len(missing), "" if len(missing) == 1 else "s",
                              "has" if len(missing) == 1 else "have",
                              "its" if len(missing) == 1 else "their"))
        placed = frames and relation in ("same", "aligned_crs")
        frame_of = effort_frame_finder(
            {t: v["ring"] for t, v in frames.items()}) if placed else None
        default = None if placed else "*"
        if relation == "other":
            warnings.append("the correction is in another coordinate system "
                            "than the campaign: no pairing, and its time is "
                            "given for the correction as a whole")
        elif relation == "aligned_crs":
            warnings.append("the correction's pixels are not aligned with "
                            "the campaign's: frames compared by position")
        c_res = effort_sensitivity(c_rows, limits, frame_of, default)
        warnings.extend(c_res[idle]["warnings"])
        c_keys = sorted(c_res[idle]["frames"], key=lambda k: tuple(map(str,
                                                                      k)))
        changed = effort_changed_by(c_rows, frame_of, default)
        for r in c_rows:
            if r.get("action") != "correct":
                continue
            tile = (frame_of(r) if frame_of is not None else None) or default
            try:
                code = int(float(r.get("class_code") or 0))
                m2 = float(r.get("area_m2") or 0.0)
            except ValueError:
                continue
            key = (tile, str(r.get("operator") or ""), "", code)
            c_class[key] = c_class.get(key, 0.0) + m2

    _time_check(canceled)
    # which frames
    rule = plan.get("frames") or "read"
    if rule == "closed":
        keep = []
        for k in s_keys:
            share = coverage.get(k)
            if share is not None and share > CLOSED_SHARE:
                keep.append(k)
            else:
                skipped[k[0]] = "not closed by %s, pass %s" % (k[1], k[2])
        s_keys = keep
        closed = {k[0] for k in s_keys}
        for k in c_keys:
            if k[0] not in closed:
                skipped.setdefault(k[0], "not closed by a chosen reading")
        c_keys = [k for k in c_keys if k[0] in closed]
    elif rule == "both" and c_path:
        a = {k[0] for k in s_keys}
        b = {k[0] for k in c_keys}
        for t in (a ^ b):
            skipped[t] = "drawn only" if t in a else "corrected only"
        s_keys = [k for k in s_keys if k[0] in b]
        c_keys = [k for k in c_keys if k[0] in a]

    _time_check(canceled)
    cid, corr_id = camp_data.get("id", ""), c_data.get("id", "")
    frame_rows = []
    if s_res is not None:
        frame_rows += effort_frame_table(
            "scratch", s_res, idle, frame_m2, s_keys, cid, "", coverage,
            None, 1, 0, designs)
    if c_res is not None:
        frame_rows += effort_frame_table(
            "correct", c_res, idle, frame_m2, c_keys, cid, corr_id, None,
            changed, 1, estimated, designs)
    class_rows = []
    if s_res is not None:
        class_rows += effort_class_table("scratch", s_res, idle, s_keys,
                                         class_m2, names, cid, "")
    if c_res is not None:
        class_rows += effort_class_table(
            "correct", c_res, idle, c_keys, c_class,
            _time_names(c_data.get("classes")) or names, cid, corr_id)

    paired_rows, pooled = [], {}
    pairing = bool(c_path and s_res is not None and frames
                   and relation in ("same", "aligned_crs"))
    if pairing:
        s_by = effort_by_tile(s_res, s_keys, "mean")
        c_by = effort_by_tile(c_res, c_keys, "sum")
        who = {}
        for t in set(s_by[idle]) | set(c_by[idle]):
            sk = [k for k in s_keys if k[0] == t]
            ck = [k for k in c_keys if k[0] == t]
            who[t] = (";".join(sorted({k[1] for k in sk})),
                      ";".join(sorted({k[2] for k in sk})),
                      ";".join(sorted({k[1] for k in ck})))
        by_tile = {}
        for (t, _op, _p), m2 in changed.items():
            by_tile[t] = by_tile.get(t, 0.0) + m2
        paired_rows, pooled = effort_paired_table(
            s_by, c_by, idle, frame_m2, who, by_tile)
    elif c_path and camp_folder:
        notes.append("no pairing: %s" % (
            "the correction is not on the campaign's grid"
            if relation == "other" else
            "the campaign has no frames" if not frames else
            "no reading drawn from scratch was chosen"))

    # the folder
    owner_kind = plan.get("owner") or ("campaign" if camp_folder
                                       else "correction")
    owner_folder = camp_folder if owner_kind == "campaign" else c_folder
    owner_data = camp_data if owner_kind == "campaign" else c_data
    if frames:
        problem = time_path_problem(owner_folder, plan.get("folder"))
        if problem:
            raise ValueError(problem)
    tmp, final = time_target(owner_folder, plan.get("folder"))
    files = []
    try:
        _time_check(canceled)
        report_csv(os.path.join(tmp, TIME_FILES["per_frame"]),
                   _time_columns(EFFORT_FRAME_COLUMNS, frame_rows),
                   _time_rows(EFFORT_FRAME_COLUMNS, frame_rows))
        files.append(TIME_FILES["per_frame"])
        report_csv(os.path.join(tmp, TIME_FILES["per_class"]),
                   list(EFFORT_CLASS_COLUMNS),
                   _time_rows(EFFORT_CLASS_COLUMNS, class_rows))
        files.append(TIME_FILES["per_class"])
        if pairing:
            report_csv(os.path.join(tmp, TIME_FILES["paired"]),
                       list(EFFORT_PAIRED_COLUMNS),
                       _time_rows(EFFORT_PAIRED_COLUMNS, paired_rows))
            files.append(TIME_FILES["paired"])
        _time_check(canceled)
        values = {}
        for r in frame_rows:
            t = r["tile_id"]
            if t not in frames:
                continue
            v = values.setdefault(t, {"frame_ha": r["frame_ha"],
                                      "scratch_s": None, "correct_s": None})
            col = "scratch_s" if r["source"] == "scratch" else "correct_s"
            if r.get("active_s_T") is not None:
                v.setdefault("_" + col, []).append(r["active_s_T"])
        for t, v in values.items():
            s = v.pop("_scratch_s", None)
            c = v.pop("_correct_s", None)
            v["scratch_s"] = sum(s) / len(s) if s else None
            v["correct_s"] = sum(c) if c else None
            m2 = frame_m2.get(t)
            v["scratch_min_ha"] = effort_per_ha(v["scratch_s"], m2) \
                if v["scratch_s"] is not None else None
            v["correct_min_ha"] = effort_per_ha(v["correct_s"], m2) \
                if v["correct_s"] is not None else None
            v["ratio"] = v["correct_s"] / v["scratch_s"] \
                if v["scratch_s"] and v["correct_s"] else None
        gpkg = None
        if values:
            gpkg = time_write_gpkg(os.path.join(tmp, TIME_FILES["frames"]),
                                   frames, srs, values)
            files.append(TIME_FILES["frames"])
            field = "scratch_min_ha" if any(
                v.get("scratch_min_ha") is not None for v in values.values()) \
                else "correct_min_ha"
            qml = time_qml([v.get(field) for v in values.values()], field)
            if qml:
                report_text(os.path.join(tmp, TIME_FILES["style"]), qml)
                files.append(TIME_FILES["style"])

        _time_check(canceled)
        scratch_rows_ = [r for r in frame_rows if r["source"] == "scratch"]
        correct_rows_ = [r for r in frame_rows if r["source"] == "correct"]
        st = effort_totals(scratch_rows_)
        ct = effort_totals(correct_rows_)
        main = pooled.get(idle) or {}
        ratio = main.get("ratio") if pairing else None
        headline = report_headline("time", {
            "idle_s": idle,
            "active_h": st["T"]["active_h"] + ct["T"]["active_h"],
            "min_per_ha_scratch": st["T"]["min_per_ha"]
            if scratch_rows_ else None,
            "min_per_ha_correct": ct["T"]["min_per_ha"]
            if correct_rows_ else None,
            "ratio": ratio,
            "ratio_ci": [main.get("ci_low"), main.get("ci_high")]
            if pairing else None,
            "n_paired": main.get("n_frames") if pairing else 0})
        sensitivity = {}
        for t in IDLE_SENSITIVITY:
            sensitivity[str(t)] = {
                "active_h_scratch": st[t]["active_h"],
                "active_h_correct": ct[t]["active_h"],
                "min_per_ha_scratch": st[t]["min_per_ha"],
                "min_per_ha_correct": ct[t]["min_per_ha"],
                "ratio": (pooled.get(t) or {}).get("ratio")
                if pairing else None}
        summary = report_header("time", time_plan_owner(
            owner_kind, owner_folder, owner_data))
        summary.update({
            "inputs": report_inputs(inputs, owner_folder),
            "parameters": dict(effort_parameters(idle), frames=rule),
            "headline": headline,
            "readings": [reading_label((r[0], int(r[1])))
                         for r in sorted(chosen)],
            "campaign": {"id": cid, "name": camp_data.get("name", ""),
                         "folder": camp_folder,
                         "journal": bool(s_rows)} if camp_folder else None,
            "correction": {"id": corr_id, "name": c_data.get("name", ""),
                           "folder": c_folder, "grid_relation": relation,
                           "journal": bool(c_rows) and not estimated,
                           "estimated": bool(estimated)} if c_path else None,
            "frames_used": sorted({r["tile_id"] for r in frame_rows}),
            "frames_skipped": skipped,
            "totals": {"scratch": st["T"], "correct": ct["T"]},
            "sensitivity": sensitivity,
            "pooled": {str(t): p for t, p in pooled.items()},
            "warnings": warnings, "notes": notes,
            "design_notes": EFFORT_DESIGN_NOTES,
            "files": files + [TIME_FILES["summary"]]})
        report_json(os.path.join(tmp, TIME_FILES["summary"]), summary)
        _time_check(canceled)
        done = report_finish(tmp, final)
    except BaseException:
        report_abandon(tmp)
        raise
    result = {"folder": done, "files": files + [TIME_FILES["summary"]],
              "headline": headline, "summary": summary,
              "frames": frame_rows, "classes": class_rows,
              "paired": paired_rows, "warnings": warnings, "notes": notes}
    if plan.get("register", True):
        _time_register(plan, owner_kind, owner_folder, done, summary,
                       headline)
    if plan.get("maps") and gpkg:
        _time_load(plan, owner_kind, owner_folder, owner_data, done)
    log("time written to %s" % done)
    return result


def _time_columns(columns, rows):
    extra = [c for c in EFFORT_DESIGN_COLUMNS
             if any(c in r for r in rows)]
    return list(columns) + extra


def _time_rows(columns, rows):
    cols = _time_columns(columns, rows) if columns is EFFORT_FRAME_COLUMNS \
        else list(columns)
    return [[r.get(c) for c in cols] for r in rows]


def _time_owner_object(plan, kind, folder):
    live = plan.get("live")
    if live is not None:
        return live
    if kind == "campaign":
        obj = Campaign(folder)
        obj.data = campaign_read_only(folder)[0]
        return obj
    return CorrectionCampaign.open(folder)


def _time_register(plan, kind, folder, done, summary, headline):
    """The report in the manifest's list of reports, saved the usual way."""
    try:
        owner = _time_owner_object(plan, kind, folder)
        rel = os.path.relpath(done, folder).replace("\\", "/")
        report_register(owner.data, report_entry(
            "time", os.path.basename(done), "", summary.get("created_utc")
            or report_utc(), rel, headline))
        owner.save()
    except Exception as err:
        log("the report is written but the manifest does not list it: %s"
            % err)


def _time_load(plan, kind, folder, data, done):
    """The map of the frames into QGIS, in the report's group."""
    try:
        owner = _time_owner_object(plan, kind, folder)
        path = os.path.join(done, TIME_FILES["frames"])
        lyr = QgsVectorLayer("%s|layername=%s" % (path, TIME_FRAMES_LAYER),
                             "time frames", "ogr")
        if not lyr.isValid():
            log("the map of time will not load: %s" % path)
            return None
        qml = os.path.join(done, TIME_FILES["style"])
        if os.path.isfile(qml):
            lyr.loadNamedStyle(qml)
        return add_report_layer(lyr, owner, "time", os.path.basename(done),
                                "frames")
    except Exception as err:
        log("cannot load the map of time: %s" % err)
        return None


#  The window
# =====================================================================
class TimeSetup(QDialog):
    """What a report of working time is made of: the readings drawn from
    scratch, the correction set against them, the frames, the idle limit and
    where it goes. One column, 300 pixels wide."""

    def __init__(self, parent, campaign=None, correction=None, owner=None,
                 reading=None):
        super().__init__(parent)
        self.setWindowTitle(titled("Time"))
        self.campaign = campaign
        self.owner = owner or ("campaign" if campaign is not None
                               else "correction")
        self.live = None
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        row = 0

        grid.addWidget(report_part("Drawn from scratch"), row, 0, 1, 3)
        row += 1
        self.readings = []
        if campaign is not None:
            counts = time_scratch_readings(campaign.folder, campaign.data)
            held = (operator_word((reading or {}).get("operator")),
                    pass_number((reading or {}).get("pass")))
            for key in sorted(counts, key=lambda r: (r[1], r[0])):
                n = counts[key]
                # wraps: an operator's name can be as long as it likes
                box = narrow_tick("%s · %d frame%s" % (
                    reading_label(key), n, "" if n == 1 else "s"))
                box.setChecked(key == held)
                box.setToolTip("The time %s spent drawing, from the journal."
                               % reading_label(key))
                grid.addWidget(box, row, 0, 1, 3)
                self.readings.append((box, key))
                row += 1
            if self.readings and not any(b.isChecked()
                                         for b, _ in self.readings):
                self.readings[0][0].setChecked(True)
        if not self.readings:
            none = QLabel("no reading: only the correction is measured"
                          if campaign is None else "nothing drawn yet")
            none.setObjectName("quiet")
            grid.addWidget(none, row, 0, 1, 3)
            row += 1

        grid.addWidget(report_part("Corrected"), row, 0, 1, 3)
        row += 1
        self.correction = short_combo(QComboBox())
        self.correction.addItem("none", "")
        for path, words in time_correction_choices(parent, campaign):
            self.correction.addItem(words, path)
        if correction:
            i = self.correction.findData(correction)
            if i < 0:
                self.correction.addItem(os.path.basename(
                    os.path.dirname(correction)), correction)
                i = self.correction.count() - 1
            self.correction.setCurrentIndex(i)
        self.correction.setToolTip(
            "A correction of a model's map on the same grid: its strokes go "
            "to the\nframe they fall in, and drawing from scratch is set "
            "against correcting,\nframe by frame.")
        grid.addWidget(self.correction, row, 0, 1, 3)
        row += 1
        self.grid_note = QLabel("")
        self.grid_note.setObjectName("quiet")
        self.grid_note.setWordWrap(True)
        grid.addWidget(self.grid_note, row, 0, 1, 3)
        row += 1

        grid.addWidget(report_part("Which frames"), row, 0, 1, 3)
        row += 1
        self.rule = QButtonGroup(self)
        self.rule_buttons = {}
        for i, (key, words) in enumerate(TIME_FRAME_RULES):
            b = narrow_radio(words)
            self.rule.addButton(b, i)
            self.rule_buttons[key] = b
            grid.addWidget(b, row, 0, 1, 3)
            row += 1
        self.rule_buttons["read"].setChecked(True)

        grid.addWidget(report_part("What counts"), row, 0, 1, 3)
        row += 1
        grid.addWidget(QLabel("Idle after"), row, 0)
        self.idle = QComboBox()
        for s in IDLE_SENSITIVITY:
            self.idle.addItem("%d s" % s, s)
        self.idle.addItem("other…", 0)
        self.idle.setCurrentIndex(self.idle.findData(IDLE_DEFAULT_S))
        self.idle.setToolTip(
            "A pause longer than this, between two things done or inside a "
            "stroke,\nis not counted as work.")
        grid.addWidget(self.idle, row, 1)
        self.other = QSpinBox()
        self.other.setRange(10, 900)
        self.other.setValue(IDLE_DEFAULT_S)
        self.other.setSuffix(" s")
        self.other.setVisible(False)
        grid.addWidget(self.other, row, 2)
        row += 1
        also = QLabel("30, 60 and 120 s are written too")
        also.setObjectName("quiet")
        also.setWordWrap(True)
        grid.addWidget(also, row, 0, 1, 3)
        row += 1

        folder = self.owner_folder()
        start = os.path.join(folder, "reports", "time", report_stamp()) \
            if folder else ""
        row, self.folder, self.maps = report_where_rows(grid, row, start)
        self.path_note = QLabel("")
        self.path_note.setObjectName("warning")
        self.path_note.setWordWrap(True)
        self.path_note.setVisible(False)
        grid.addWidget(self.path_note, row, 0, 1, 3)
        row += 1

        keys = QHBoxLayout()
        keys.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        keys.addWidget(cancel)
        self.b_write = QPushButton("Write")
        self.b_write.setDefault(True)
        self.b_write.clicked.connect(self.accept)
        keys.addWidget(self.b_write)
        grid.addLayout(keys, row, 0, 1, 3)

        self.correction.currentIndexChanged.connect(self.refresh)
        self.idle.currentIndexChanged.connect(self.refresh)
        self.folder.textChanged.connect(self.refresh)
        for b, _ in self.readings:
            b.toggled.connect(self.refresh)
        self.refresh()
        keep_shape(self, 300)

    def owner_folder(self):
        if self.owner == "campaign" and self.campaign is not None:
            return self.campaign.folder
        path = self.correction.currentData() if hasattr(self, "correction") \
            else ""
        return os.path.dirname(path) if path else ""

    def chosen_correction(self):
        return self.correction.currentData() or None

    def idle_s(self):
        s = self.idle.currentData()
        return int(s) if s else int(self.other.value())

    def refresh(self, *args):
        self.other.setVisible(not self.idle.currentData())
        path = self.chosen_correction()
        relation = time_relation(getattr(self.campaign, "data", None), path)
        self.grid_note.setText(TIME_GRID_WORDS.get(relation, "")
                               if path and self.campaign is not None else
                               ("the correction alone, with no frames"
                                if path else ""))
        self.grid_note.setVisible(bool(self.grid_note.text()))
        self.rule_buttons["both"].setEnabled(bool(path))
        if not path and self.rule_buttons["both"].isChecked():
            self.rule_buttons["read"].setChecked(True)
        wanted = any(b.isChecked() for b, _ in self.readings) or bool(path)
        # the map of the frames is a GeoPackage, written when the campaign
        # has frames; QGIS must be able to open it where it is asked to go
        problem = ""
        folder = self.owner_folder()
        if folder and self.campaign is not None \
                and self.campaign.data.get("with_tiles", True):
            problem = time_path_problem(
                folder, self.folder.text().strip() or None)
        self.path_note.setText(problem)
        self.path_note.setVisible(bool(problem))
        self.b_write.setEnabled(wanted and not problem)
        if self.layout() is not None and self.isVisible():
            hold_shape(self, 300)

    def chosen_rule(self):
        for key, b in self.rule_buttons.items():
            if b.isChecked():
                return key
        return "read"

    def plan(self):
        return {"campaign": self.campaign.folder if self.campaign is not None
                else None,
                "readings": [key for b, key in self.readings
                             if b.isChecked()],
                "correction": self.chosen_correction(),
                "idle_s": self.idle_s(), "frames": self.chosen_rule(),
                "owner": self.owner,
                "folder": self.folder.text().strip() or None,
                "maps": self.maps.isChecked(), "live": self.live}

    def write(self):
        """The report, written now, without a window: what Write does."""
        return time_write(self.plan())


def time_report_window(parent, result):
    """The numbers of a report just written, in the window every report
    shares."""
    head = result["headline"]
    frames = result["frames"]
    n = len({r["tile_id"] for r in frames})
    scope = "%d frame%s · active %s" % (
        n, "" if n == 1 else "s", _time_hours(head.get("active_h")))
    headline = [("idle after", "%d s" % head.get("idle_s")),
                ("drawn, min/ha", head.get("min_per_ha_scratch")),
                ("corrected, min/ha", head.get("min_per_ha_correct"))]
    if head.get("ratio") is not None:
        ci = head.get("ratio_ci") or [None, None]
        headline.append(("corrected/drawn", head.get("ratio")))
        none = ci[0] is None or ci[0] != ci[0]
        headline.append(("95% CI", "—, fewer than %d frames"
                         % BOOTSTRAP_MIN_FRAMES if none else
                         "%s – %s" % (_time_num(ci[0]),
                                            _time_num(ci[1]))))
        headline.append(("frames paired", head.get("n_paired")))
    rows = [[r["source"], r["tile_id"], r["operator"],
             None if r.get("active_s_T") is None else r["active_s_T"] / 60.0,
             r.get("min_per_ha_T")] for r in frames]
    tables = [{"title": "Per frame", "columns": ["source", "frame", "who",
                                                 "active min", "min/ha"],
               "rows": rows}]
    notes = ["⚠ " + w for w in result.get("warnings") or []] \
        + list(result.get("notes") or [])
    notes.append(result["summary"]["parameters"]["rule"])
    d = ReportWindow(parent, "Time", scope, headline, tables, notes,
                     result["folder"])
    return d


def _time_hours(h):
    if h is None:
        return "—"
    minutes = int(round(h * 60))
    return "%d h %d min" % (minutes // 60, minutes % 60) if minutes >= 60 \
        else "%d min" % minutes


def _time_num(v):
    return "—" if v is None or v != v else "%.2f" % v


def _time_flush(panel):
    held = getattr(panel, "_time_journal", None)
    if held is not None:
        held[1].flush()
    for hook_ in getattr(getattr(panel, "section", None), "stroke_hooks",
                         None) or []:
        flush = getattr(hook_, "flush", None)
        if callable(flush):
            try:
                flush(panel.section)
            except Exception:
                pass


def _time_run(panel, d):
    try:
        result = d.write()
    except Exception as err:
        trouble(err, "Time")
        return None
    run_dialog(time_report_window(panel, result))
    return result


def time_start(panel):
    """Measure, Time..., from ANNOTATION CAMPAIGN."""
    campaign = panel.campaign
    if campaign is None:
        return None
    _time_flush(panel)
    book = getattr(panel, "correction", None)
    d = TimeSetup(panel, campaign, correction=os.path.join(
        book.folder, CORRECTION_MANIFEST) if book is not None else None,
        owner="campaign", reading=panel.reading())
    d.live = campaign
    if not run_dialog(d):
        return None
    return _time_run(panel, d)


def time_start_correction(panel):
    """Measure, Time..., from CORRECTION: the open correction chosen, and
    the report in the correction's own reports/."""
    book = getattr(panel, "correction", None)
    if book is None:
        return None
    _time_flush(panel)
    d = TimeSetup(panel, getattr(panel, "campaign", None),
                  correction=os.path.join(book.folder, CORRECTION_MANIFEST),
                  owner="correction",
                  reading=panel.reading() if panel.campaign is not None
                  else None)
    d.live = book
    if not run_dialog(d):
        return None
    return _time_run(panel, d)


def time_enabled(panel):
    campaign = getattr(panel, "campaign", None)
    if campaign is None:
        return False, "Open a campaign first."
    if os.path.isfile(os.path.join(campaign.folder, JOURNAL_NAME)):
        return True, ""
    if not time_wanted(campaign.data):
        return False, TIME_NO_JOURNAL
    return False, TIME_NOT_YET


def time_enabled_correction(panel):
    book = getattr(panel, "correction", None)
    if book is None:
        return False, "Open a correction first."
    folder = getattr(book, "folder", "") or ""
    if os.path.isfile(os.path.join(folder, JOURNAL_NAME)):
        return True, ""
    if time_read_operations(os.path.join(folder, "operations.csv")):
        return True, ""
    return False, ("Nothing to measure yet: no stroke of this correction is "
                   "on record.")
