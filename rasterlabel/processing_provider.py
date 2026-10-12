"""rasterlabel.processing_provider

The RasterLabel algorithms in the Processing toolbox, one for each thing
the Measure menu computes, for Model Designer, batch runs and scripts
(processing.run("rasterlabel:agreement", {...})), so that the numbers of a
paper can be made again without the panel:

    rasterlabel:agreement           Measure ▸ Compare two readings…
    rasterlabel:model_vs_corrected  Measure ▸ Model vs corrected…
    rasterlabel:time_report         Measure ▸ Time…
    rasterlabel:uncertainty_report  Measure ▸ Uncertainty report…
    rasterlabel:dataset_card        Measure ▸ Dataset card…

Each is the engine of its window, handed the same recipe. 
What they read they read only: campaign.json and correction.json with
json.load and the GeoPackage opened read only through OGR, never
Campaign.open() or CorrectionCampaign.open(), which add what is missing and
would write. Each writes one report folder, under the owner's reports/ or
where OUTPUT_FOLDER says, and never the manifest: Processing does not
register the report in it, as the panel does. The checks that need the panel (who is reading, and what the
filter hides from them) are made in prepareAlgorithm, on the main thread;
the burn runs in processAlgorithm with GDAL, OGR and numpy only, so
Processing may run it in the background.

The QGIS classes of Processing are imported when the provider is first
built, not when the module is: the program is also run with QGIS faked,
and a fake has no Processing. The names of their enumerations moved in
QGIS 3.36 to 4 (Qgis.ProcessingNumberParameterType and the like), so each
is looked for under both spellings with first_attr.
"""
import importlib
import json
import os
import types

from qgis.PyQt.QtGui import QIcon

from .constants import (BOOTSTRAP_N, BOOTSTRAP_SEED, BUILD,
                        CORRECTION_MANIFEST, IDLE_DEFAULT_S, JOURNAL_NAME,
                        NAME, PLACE_SIDE_PX, PLACES_CSV, RANDOM_EVERY,
                        REPORT_SUMMARY, first_attr)
from .errors import log
from .naming import from_folder, tidy
from .campaign import (Campaign, operator_word, pass_number, reading_label,
                       readings_in)
from .layers import READINGS_KEY, REPORT_KEY, mark, report_readings_text
from .reports import report_abandon, report_finish, report_folder, report_stamp
from .compare import (CMP_KIND, CmpCancelled, cmp_compare, cmp_label,
                      cmp_plan, cmp_target)
from .correction import (CorrectionCampaign, copy_of_manifest,
                         manifest_in_hand, peek_correction, same_file)
from .geometry import ground_rows_of
from .rasters import BandPlane, open_raster
from .card import (CardCancelled, card_gather_campaign, card_gather_correction, card_names,
                   card_stale_lines, card_summary, card_write)
from .model_vs_corrected import (MVC_SCOPE_WORDS, MVC_SCOPES, MvcCancelled,
                                 mvc_grid_refusal, mvc_read_people,
                                 mvc_report)
from .uncertainty import (UNC_KINDS, UncRefused, Places, unc_default_seed,
                          unc_file_state, unc_net, unc_path_of, unc_plane,
                          unc_report, unc_score_blocks, unc_side_for)
from .ui_compare import compare_unfinished_text, compare_vector_styles
from .ui_mvc import mvc_recipe, mvc_source_trouble
from .ui_time import (TIME_FILES, TIME_FRAME_RULES, TIME_NO_JOURNAL,
                      TIME_NOT_YET, time_read_operations,
                      time_scratch_readings, time_wanted, time_write,
                      TimeCancelled)

PROCESSING_ID = "rasterlabel"
PROCESSING_STATE = {"classes": None, "provider": None, "post": []}
PROCESSING_RULES = ["closed by both readings", "touched by both readings"]
PROCESSING_HELP = (
    "<p>How far two readings of the same frames agree, and where they "
    "differ: the same report as Measure ▸ Compare two readings… in the "
    "panel.</p>"
    "<p>A reading is one operator in one pass, written OPERATOR,pass "
    "(ANNA,1). Only the frames both readings closed are compared by "
    "default (more than 99.5 % of the frame's area painted by each), or "
    "every frame both touched. Out come the confusion matrix with "
    "unlabelled as its own row and column, per class IoU and F1 (Dice), "
    "Cohen's kappa as an agreement statistic between two readings (not "
    "accuracy), quantity and allocation disagreement, each with a frame "
    "bootstrap interval; the disagreement map, the map of pairs and a "
    "GeoPackage of the places where they differ.</p>"
    "<p>The campaign is named by its folder or by its campaign.json. "
    "Nothing in it is changed: the manifest and the "
    "GeoPackage are only read. The report goes in a folder of its own, "
    "under the campaign's reports/agreement/ when no folder is given.</p>")


PROCESSING_GROUP = "Measure"
PROCESSING_GROUP_ID = "measure"
PROCESSING_MVC_SCOPES = [MVC_SCOPE_WORDS[k] for k in MVC_SCOPES]
PROCESSING_TIME_KEYS = [k for k, _ in TIME_FRAME_RULES]
PROCESSING_TIME_RULES = [w for _, w in TIME_FRAME_RULES]
PROCESSING_SAFE = (
    "<p>Nothing in the %s is changed: its manifest and its files are only "
    "read, and the report goes in a new folder of its own, under reports/ "
    "in the same folder when no folder is given. Processing does not list "
    "the report in the manifest, as the panel does.</p>")
PROCESSING_MVC_HELP = (
    "<p>How far the map a model made was from the map a person corrected in "
    "Correct: the same report as Measure ▸ Model vs corrected… in the "
    "panel. The corrected map is the reference, so the model gets its "
    "producer's and user's accuracy, IoU and F1 per class, overall accuracy, "
    "quantity and allocation disagreement, and the net ground of every FROM "
    "-> TO change, read from the pixels. There is no kappa for the "
    "model.</p>"
    "<p>On which ground: the whole map (ground nobody looked at counts as "
    "right, so it is an upper bound); the ground the strokes swept (strokes "
    "go where the model was wrong, so it is a lower bound); or inside the "
    "polygons of a layer, one matrix per polygon, with an interval when "
    "there are five or more (as good as the way the polygons were "
    "chosen). SELECTED_ONLY keeps the selected polygons of the layer.</p>"
    "<p>PEOPLE puts the same numbers for people beside the model's: the "
    "folder of another person's correction of the same map, or of an "
    "agreement report (a script may name their correction.json or "
    "summary.json). Giving another correction shows numbers of it, which "
    "the panel asks about first: here the choice is yours.</p>"
    "<p>Out come the tables, summary.json and, if asked, the map of pairs "
    "(a raster whose values say which model class met which corrected "
    "class).</p>" + PROCESSING_SAFE % "correction")
PROCESSING_TIME_HELP = (
    "<p>How long the drawing took, from the journal of working time the "
    "panel keeps (journal.csv): the same report as Measure ▸ Time… in the "
    "panel. Active time is the sum of the strokes' durations plus the gaps "
    "between them that are not longer than the idle limit; the totals at "
    "30, 60 and 120 s are always written as well, to show the result "
    "holds.</p>"
    "<p>OWNER is a campaign (the readings drawn from scratch: READINGS, "
    "OPERATOR,pass separated by ;  empty means every reading) or a "
    "correction (the time of its strokes). PAIRED_WITH sets a correction "
    "beside the campaign's drawing, or the campaign beside a correction, so "
    "that frames drawn and corrected are compared. FRAMES chooses the "
    "frames: every frame read, the ones closed by the chosen readings, or "
    "the ones both drawn and corrected.</p>"
    "<p>Out come time_per_frame.csv, time_per_class.csv, time_paired.csv "
    "when a pairing is possible, the frames with their minutes per hectare "
    "and time_summary.json.</p>" + PROCESSING_SAFE % "campaign or correction")
PROCESSING_UNCERTAINTY_HELP = (
    "<p>Where a model was unsure against where a person changed its map: "
    "the same report as Measure ▸ Uncertainty report… in the panel. It "
    "needs a correction that has an uncertainty source chosen in Correct "
    "(a probability, an entropy, a margin or votes) and reads the file of "
    "uncertainty, the record of changed pixels and the places of the walk "
    "that Correct kept. If the file of uncertainty is missing or out of "
    "date, open the correction in Correct once: it is made again there, "
    "and this algorithm never makes it.</p>"
    "<p>Out come the share of pixels changed per decile of uncertainty for "
    "the random places (with a standard error), the purposive places and "
    "the whole map (a lower bound), the AUC of the uncertainty as a "
    "detector of the changed pixels, the ECE when u is 1 - p, how much of "
    "the change the most uncertain part of the map holds, and, if asked, "
    "the picture of the curve. AUC and ECE are those of the random places "
    "when there are some, else of the whole map.</p>"
    + PROCESSING_SAFE % "correction")
PROCESSING_CARD_HELP = (
    "<p>A description of a dataset, for a paper or a repository: the same "
    "card as Measure ▸ Dataset card… in the panel, a page of Markdown for "
    "people and a JSON file for programs, with the SHA-256 of the files it "
    "describes. For a campaign it counts every reading's pixels, the "
    "consensus products and the frames; for a correction, the pixels "
    "before and after, what a person changed from what into what, and "
    "the operations. The reports already written are copied into it, "
    "marked as such when they are older than the last change.</p>"
    "<p>With the panel open on the same campaign, a reading hidden from "
    "the reader it holds (blind passes, one operator at a time) refuses "
    "the card, as it does in the panel.</p>"
    + PROCESSING_SAFE % "campaign or correction")


def processing_enum(owner, *paths):
    """The member of a Processing enumeration under whichever spelling
    this QGIS has, None when it has none."""
    return first_attr(owner, *paths)


def processing_panel():
    """The panel, when one is up: launch keeps it, and Processing asks it
    who is reading. None otherwise (a script, a QGIS with no panel)."""
    state = None
    package = globals().get("__package__") or ""
    try:
        if package:
            state = getattr(importlib.import_module(".launch", package),
                            "_RASTERLABEL", None)
        else:
            state = globals().get("_RASTERLABEL")
    except Exception:
        state = None
    return state[2] if state else None


def processing_reading(text):
    """(operator, pass) from "ANNA,1", "ANNA, pass 1" or "ANNA" (pass 1)."""
    text = str(text or "").strip()
    if not text:
        return None
    who, _, rest = text.rpartition(",") if "," in text else (text, "", "1")
    digits = "".join(ch for ch in rest if ch.isdigit())
    return (operator_word(who), pass_number(digits or 1))


class ProcessingRefusal(Exception):
    """A request the Processing algorithms refuse, said in words."""


def processing_text(value):
    return str(value or "").strip()


def processing_owner_of(text, kinds=("campaign", "correction")):
    """(kind, folder, data) of the campaign or the correction a path names:
    its folder, or its campaign.json or correction.json. The manifest is
    read with json.load and nothing else; the GeoPackage is not opened."""
    where = processing_text(text)
    if not where:
        raise ProcessingRefusal(
            "Name a campaign or a correction: its folder, or its "
            "campaign.json or correction.json.")
    where = os.path.abspath(where)
    manifests = {"campaign": Campaign.MANIFEST,
                 "correction": CORRECTION_MANIFEST}
    if os.path.isfile(where):
        name = os.path.basename(where).lower()
        found = [k for k, m in manifests.items() if m.lower() == name]
        folder = os.path.dirname(where)
        if not found:
            raise ProcessingRefusal(
                "%s is neither a campaign.json nor a correction.json."
                % where)
    elif os.path.isdir(where):
        folder = where
        found = [k for k, m in manifests.items()
                 if os.path.isfile(os.path.join(folder, m))]
        if not found:
            raise ProcessingRefusal(
                "%s holds no campaign.json and no correction.json."
                % where)
        if len(found) > 1:
            raise ProcessingRefusal(
                "%s holds both a campaign.json and a correction.json: name "
                "the one wanted." % where)
    else:
        raise ProcessingRefusal("%s is not there." % where)
    kind = found[0]
    if kind not in kinds:
        raise ProcessingRefusal(
            "%s is a %s; this needs %s." % (
                folder, kind, " or ".join("a " + k for k in kinds)))
    manifest = os.path.join(folder, manifests[kind])
    try:
        with open(manifest, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as err:
        raise ProcessingRefusal("%s cannot be read as a %s: %s"
                                % (manifest, kind, err))
    if not isinstance(data, dict):
        raise ProcessingRefusal("%s is not the manifest of a %s."
                                % (manifest, kind))
    # A manifest holds the map it was made from by its way from its folder.
    # What is in hand here is for the reports, which open that map: whole, as
    # the panel has it. Nothing is written back.
    if kind == "correction":
        manifest_in_hand(data, folder)
    else:
        grid = data.get("grid")
        if isinstance(grid, dict) and grid.get("reference_raster"):
            grid["reference_raster"] = from_folder(grid["reference_raster"],
                                                   folder)
    return kind, folder, data


def processing_target(value):
    """The report folder OUTPUT_FOLDER asks for: None when it is empty or
    Processing's temporary one (the report then goes under reports/ of the
    campaign or the correction); a folder that holds something gets a
    folder of its own inside it, an empty one is used as it is."""
    target = processing_text(value)
    if not target or target == "TEMPORARY_OUTPUT":
        return None
    target = os.path.abspath(target)
    if os.path.isdir(target):
        if os.listdir(target):
            return os.path.join(target, "report_%s" % report_stamp())
        os.rmdir(target)
    return target


def processing_free(path):
    """The first of path, path-2, path-3... that nothing, a .tmp beside it
    included, has taken."""
    for n in range(1, 1000):
        name = path if n == 1 else "%s-%d" % (path, n)
        if not os.path.exists(name) and not os.path.exists(name + ".tmp"):
            return name
    raise ProcessingRefusal("no free name for a report at %s" % path)


def processing_readings(text, known):
    """[(operator, pass)] from "ANNA,1; BRUNO,1" (all of known when empty);
    a reading the campaign does not hold is refused, naming those it has."""
    parts = [p for p in processing_text(text).split(";") if p.strip()]
    if not parts:
        return sorted(known, key=lambda r: (r[1], r[0]))
    out = []
    for part in parts:
        r = processing_reading(part)
        if r not in known:
            have = ", ".join(reading_label(k) for k in sorted(
                known, key=lambda k: (k[1], k[0]))) or "none"
            raise ProcessingRefusal(
                "%s is not a reading of this campaign (it has %s)."
                % (reading_label(r), have))
        if r not in out:
            out.append(r)
    return out


def processing_gate(data, readings, what, verb):
    """The panel's blind gate over these readings, when a panel is up on
    this same campaign: None when it lets them be seen, else its words.
    Without a panel there is no reader to blind."""
    panel = processing_panel()
    book = getattr(panel, "campaign", None) if panel is not None else None
    if book is None or book.data.get("id") != data.get("id"):
        return None
    gate = getattr(panel, "blind_gate", None)
    if not callable(gate):
        return None
    hidden = [r for r in readings if gate([r])]
    return gate(hidden, what, verb) if hidden else None


def processing_polygons(layer, wkt, selected_only, transform_context):
    """The polygons of a layer in the system of the map, as WKB: [{fid,
    wkb}]. Run on the main thread, where the layer lives."""
    from qgis.core import (QgsCoordinateReferenceSystem,
                           QgsCoordinateTransform, QgsGeometry)
    target = QgsCoordinateReferenceSystem()
    target.createFromWkt(wkt or "")
    transform = None
    if target.isValid() and layer.crs().isValid() and layer.crs() != target:
        transform = QgsCoordinateTransform(layer.crs(), target,
                                           transform_context)
    features = layer.selectedFeatures() if selected_only \
        else layer.getFeatures()
    out = []
    for f in features:
        geom = QgsGeometry(f.geometry())
        if geom is None or geom.isEmpty():
            continue
        if transform is not None:
            geom.transform(transform)
        out.append({"fid": int(f.id()), "wkb": bytes(geom.asWkb())})
    return out


def processing_people(text, mine):
    """The people to set the model beside: another person's correction of
    the same map (its folder or correction.json), or the summary.json of an
    agreement report (its folder or the file). None when text is empty."""
    where = processing_text(text)
    if not where:
        return None
    where = os.path.abspath(where)
    folder = where if os.path.isdir(where) else os.path.dirname(where)
    name = os.path.basename(where).lower()
    if os.path.isfile(os.path.join(folder, CORRECTION_MANIFEST)) and (
            os.path.isdir(where) or name == CORRECTION_MANIFEST):
        manifest = os.path.join(folder, CORRECTION_MANIFEST)
        if same_file(manifest, os.path.join(mine["folder"],
                                            CORRECTION_MANIFEST)):
            raise ProcessingRefusal(
                "PEOPLE is the correction being measured: name another "
                "person's correction of the same map, or an agreement "
                "report.")
        data = peek_correction(manifest)
        if not data:
            raise ProcessingRefusal("%s cannot be read as a correction."
                                    % manifest)
        copy = copy_of_manifest(manifest, data)
        if not copy or not os.path.isfile(copy):
            raise ProcessingRefusal(
                "The working copy of the other correction is not there: %s"
                % (copy or "(nothing named)"))
        mine_source = str(mine["data"].get("source") or "").split("|")[0]
        if not same_file(str(data.get("source") or "").split("|")[0],
                         mine_source):
            raise ProcessingRefusal(
                "The other correction is of another map than this one: it "
                "started from %s, this from %s." % (data.get("source"),
                                                    mine_source))
        who = operator_word(data.get("operator")) or "?"
        return {"kind": "correction", "manifest": manifest, "path": copy,
                "band": int(data.get("band", 1) or 1), "operator": who,
                "name": os.path.basename(folder)}
    try:
        return mvc_read_people(where)
    except IOError as err:
        raise ProcessingRefusal(str(err))


def processing_mvc_job(folder, data, scope, layer, selected_only,
                       transform_context, people_text, write_map):
    """Everything model_vs_corrected needs, checked as the panel checks it
    (the map it started from is there and on the grid of the copy, the copy
    is there) and read, never written. layer is a QGIS polygon layer for the
    scope "polygons". Returns {recipe, record, folder, people}."""
    book = CorrectionCampaign(folder)
    book.data = data
    copy = book.working_path
    if not copy or not os.path.isfile(copy):
        raise ProcessingRefusal(
            "The working copy of this correction is missing: %s"
            % (copy or "(none named)"))
    trouble = mvc_source_trouble(book)
    if trouble:
        raise ProcessingRefusal(trouble)
    why = mvc_grid_refusal(str(data.get("source")).split("|")[0], copy,
                           "the map it started from", empty_ok=True)
    if why:
        raise ProcessingRefusal(why[0].upper() + why[1:] + ".")
    polygons = None
    if scope == "polygons":
        if layer is None:
            raise ProcessingRefusal(
                "Inside the polygons needs a polygon layer: set POLYGONS.")
        ds = open_raster(copy)
        wkt = ds.GetProjection() if ds is not None else ""
        ds = None
        polygons = processing_polygons(layer, wkt, selected_only,
                                       transform_context)
        if not polygons:
            raise ProcessingRefusal(
                "No polygon to compare inside: %s has %s." % (
                    layer.name(), "none selected" if selected_only
                    else "none"))
    people = processing_people(people_text, {"folder": folder,
                                             "data": data})
    pm = (data.get("grid") or {}).get("pixel_m") or []
    try:
        area = abs(float(pm[0]) * float(pm[1])) if len(pm) >= 2 else 0.0
    except (TypeError, ValueError):
        area = 0.0
    # The pixel is not the same ground in every row of a map in degrees or in
    # Web Mercator: the panel hands the comparison the ground row by row
    # (ground_rows), and so does this, from the copy, so that a run in the
    # toolbox reports the area the panel does. None where one value serves.
    row_m2 = None
    cds = open_raster(copy)
    if cds is not None:
        try:
            row_m2 = ground_rows_of(
                cds.GetProjection() or (data.get("grid") or {}).get("crs")
                or "", cds.GetGeoTransform(), cds.RasterXSize,
                cds.RasterYSize, area)
        except Exception as err:
            log("the area of a pixel could not be measured row by row, so "
                "one value is used for the whole map: %s" % err)
        cds = None
    section = types.SimpleNamespace(path=copy,
                                    band_no=int(data.get("band", 1) or 1),
                                    pixel_area_m2=area, row_m2=row_m2)
    asked = {"scope": scope, "polygons": polygons,
             "layer": layer.name() if layer is not None
             and scope == "polygons" else None,
             "selected_only": selected_only if scope == "polygons" else None,
             "people": people, "write_map": write_map}
    return {"recipe": mvc_recipe(book, section, asked), "record": data,
            "folder": folder, "people": people}


def processing_places(folder, record, u8, gt):
    """The places of the walk as the file in the correction's folder has
    them, rescored to the uncertainty as it is now; cut afresh, in memory,
    when there is no file. Nothing is saved."""
    ny, nx = u8.shape
    settings = dict(record.get("places") or {})
    side = unc_side_for(nx, ny, int(settings.get("side_px") or PLACE_SIDE_PX))
    seed = settings.get("seed")
    if seed is None:
        seed = unc_default_seed(record.get("id"), record.get("name", ""))
    every = settings.get("random_every")
    every = RANDOM_EVERY if every is None else int(every)
    blind = bool(settings.get("blind", every > 0))
    path = os.path.join(folder, PLACES_CSV)
    places = None
    if os.path.exists(path):
        try:
            places = Places(path, side, seed, every, blind).load()
        except IOError as err:
            log(str(err))
            places = None
        if places is not None and places.rows and places.side != side:
            if any(r["status"] for r in places.rows):
                side = places.side
            else:
                places = None
        if places is not None and not places.rows:
            places = None
    blocks = unc_score_blocks(u8, side)
    if places is None:
        return Places.from_blocks(path, blocks, gt, nx, ny, seed, every,
                                  blind)
    places.rescore(blocks)
    places.seed, places.random_every = int(seed), int(every)
    places.blind = blind
    return places


def processing_unc_job(folder, data, target, draw):
    """The uncertainty report's inputs, read from the files of the
    correction and checked as the panel checks them. Nothing is written."""
    spec = data.get("uncertainty")
    if not isinstance(spec, dict) or spec.get("kind") not in UNC_KINDS:
        raise ProcessingRefusal(
            "This correction has no uncertainty chosen: choose one in "
            "Correct first (UNCERTAINTY, Source).")
    book = CorrectionCampaign(folder)
    book.data = data
    copy = book.working_path
    if not copy or not os.path.isfile(copy):
        raise ProcessingRefusal("The working copy of this correction is "
                                "missing: %s" % (copy or "(none named)"))
    derived = unc_path_of(copy, data)
    state, why = unc_file_state(derived, spec, folder)
    if state != "ok":
        raise ProcessingRefusal(
            "The file of uncertainty, %s, is %s (%s). Open the correction "
            "in Correct once: it is made again there." % (
                os.path.basename(derived),
                "not there" if state == "missing" else state, why))
    ds = open_raster(copy)
    if ds is None:
        raise ProcessingRefusal("The working copy cannot be read: %s" % copy)
    try:
        nx, ny = ds.RasterXSize, ds.RasterYSize
        band_no = int(data.get("band", 1) or 1)
        band = ds.GetRasterBand(band_no)
        nodata = band.GetNoDataValue()
        gt = tuple(ds.GetGeoTransform())
    finally:
        band = None
        ds = None
    # the maps stay in their files and are read a strip at a time, as
    # Correct reads them: a map of hundreds of millions of pixels is not
    # held whole to be measured
    values = BandPlane(copy, band_no)
    u8 = unc_plane(derived, nx, ny)
    if u8 is None:
        raise ProcessingRefusal(
            "%s is not on the grid of the working copy: choose the "
            "uncertainty again in Correct." % os.path.basename(derived))
    changes = book.changes_path
    marks = None
    if os.path.isfile(changes):
        cds = open_raster(changes)
        if cds is not None:
            if (cds.RasterXSize, cds.RasterYSize) == (nx, ny):
                marks = BandPlane(changes, 1)
            cds = None
    net = unc_net(values, data.get("source"), band_no, nodata)
    places = processing_places(folder, data, u8, gt)
    owner = {"kind": "correction", "id": data.get("id", ""),
             "name": data.get("name", ""), "folder": folder}
    paths = {"copy": copy, "changes": changes, "derived": derived,
             "places_csv": os.path.join(folder, PLACES_CSV),
             "operations": os.path.join(folder, "operations.csv"),
             "journal": os.path.join(folder, JOURNAL_NAME),
             "source": data.get("source")}
    return {"owner": owner, "record": data, "spec": spec,
            "arrays": {"u8": u8, "marks": marks, "net": net},
            "places": places, "paths": paths,
            "operations": data.get("operations", 0), "folder": folder,
            "target": processing_free(target) if target else None,
            "draw": draw}


def processing_time_job(owner_text, paired_text, readings_text, idle_s,
                        rule, target):
    """The plan time_write is handed: a campaign or a correction, and the
    other one when it is wanted too, and the checks the panel makes before
    it offers Time."""
    kind, folder, data = processing_owner_of(owner_text)
    campaign = correction = None
    camp_data = {}
    if kind == "campaign":
        campaign, camp_data = folder, data
        if not os.path.isfile(os.path.join(folder, JOURNAL_NAME)):
            raise ProcessingRefusal(
                TIME_NO_JOURNAL if not time_wanted(data) else TIME_NOT_YET)
    else:
        correction = os.path.join(folder, CORRECTION_MANIFEST)
        if not os.path.isfile(os.path.join(folder, JOURNAL_NAME)) and \
                not time_read_operations(os.path.join(folder,
                                                      "operations.csv")):
            raise ProcessingRefusal(
                "Nothing to measure yet: no stroke of this correction is "
                "on record.")
    if processing_text(paired_text):
        other, other_folder, other_data = processing_owner_of(paired_text)
        if other == kind:
            raise ProcessingRefusal(
                "PAIRED_WITH must be a %s to go with this %s."
                % ("correction" if kind == "campaign" else "campaign", kind))
        if kind == "campaign":
            correction = os.path.join(other_folder, CORRECTION_MANIFEST)
        else:
            campaign, camp_data = other_folder, other_data
    readings = []
    if campaign:
        readings = processing_readings(
            readings_text, set(time_scratch_readings(campaign, camp_data)))
    if rule == "both" and not correction:
        raise ProcessingRefusal(
            "'Drawn and corrected' needs a correction: set PAIRED_WITH.")
    if rule == "closed" and not campaign:
        raise ProcessingRefusal("'Closed only' needs a campaign.")
    return {"campaign": campaign, "readings": readings,
            "correction": correction, "idle_s": int(idle_s), "frames": rule,
            "owner": kind, "folder": target, "maps": False, "live": None,
            "register": False}


def processing_card_job(owner_text):
    """What the dataset card is gathered from, and the checks of the panel:
    the package or the working copy is there, and no reading is hidden from
    the reader the panel holds."""
    kind, folder, data = processing_owner_of(owner_text)
    if kind == "campaign":
        package = os.path.join(folder, Campaign.PACKAGE)
        if not os.path.isfile(package):
            raise ProcessingRefusal(
                "The campaign has no package to describe: %s is not in its "
                "folder." % Campaign.PACKAGE)
        refusal = processing_gate(
            data, sorted(readings_in(package), key=lambda r: (r[1], r[0])),
            "card", "write the card")
        if refusal:
            raise ProcessingRefusal(refusal)
        stem = tidy(data.get("name") or "campaign", "campaign")
    else:
        book = CorrectionCampaign(folder)
        book.data = data
        copy = book.working_path
        if not copy or not os.path.isfile(copy):
            raise ProcessingRefusal(
                "The working copy of this correction is not there%s. Put it "
                "back beside correction.json, then write the card."
                % (": " + os.path.basename(copy) if copy else ""))
        package = None
        stem = book.stem
    return {"kind": kind, "folder": folder, "data": data,
            "package": package, "stem": stem}


def processing_classes():
    """The provider and the algorithm classes, built once."""
    if PROCESSING_STATE["classes"] is not None:
        return PROCESSING_STATE["classes"]
    from qgis.core import (Qgis, QgsProcessing, QgsProcessingAlgorithm,
                           QgsProcessingContext, QgsProcessingException,
                           QgsProcessingLayerPostProcessorInterface,
                           QgsProcessingOutputFile,
                           QgsProcessingOutputNumber,
                           QgsProcessingOutputRasterLayer,
                           QgsProcessingOutputVectorLayer,
                           QgsProcessingParameterBoolean,
                           QgsProcessingParameterEnum,
                           QgsProcessingParameterFile,
                           QgsProcessingParameterFolderDestination,
                           QgsProcessingParameterNumber,
                           QgsProcessingParameterString,
                           QgsProcessingParameterVectorLayer,
                           QgsProcessingProvider)
    integer = processing_enum(Qgis, "ProcessingNumberParameterType.Integer")
    if integer is None:
        integer = processing_enum(QgsProcessingParameterNumber, "Integer")
    temporary = getattr(QgsProcessing, "TEMPORARY_OUTPUT",
                        "TEMPORARY_OUTPUT")
    folder_kind = processing_enum(Qgis, "ProcessingFileParameterBehavior."
                                  "Folder")
    if folder_kind is None:
        folder_kind = processing_enum(QgsProcessingParameterFile,
                                      "Behavior.Folder", "Folder")
    polygon_type = processing_enum(Qgis, "ProcessingSourceType.VectorPolygon")
    if polygon_type is None:
        polygon_type = processing_enum(QgsProcessing, "TypeVectorPolygon")
    no_threading = processing_enum(Qgis, "ProcessingAlgorithmFlag."
                                   "NoThreading")
    if no_threading is None:
        no_threading = processing_enum(QgsProcessingAlgorithm,
                                       "FlagNoThreading")

    class ReportLayerMarks(QgsProcessingLayerPostProcessorInterface):
        """A map of the report, loaded by Processing, marked as the panel
        marks its own: so the filter of a blind reader switches it off."""

        def __init__(self, owner_id, readings, part, style=None):
            super().__init__()
            self.owner_id = owner_id
            self.readings = readings
            self.part = part
            self.style = style

        def postProcessLayer(self, layer, context, feedback):  # noqa: N802
            try:
                mark(layer, self.owner_id, "report:%s:%s:%s" % (
                    CMP_KIND, cmp_label(*self.readings), self.part))
                layer.setCustomProperty(REPORT_KEY, CMP_KIND)
                layer.setCustomProperty(READINGS_KEY,
                                        report_readings_text(self.readings))
                if self.style and os.path.isfile(self.style):
                    layer.loadNamedStyle(self.style)
                    layer.triggerRepaint()
            except Exception as err:
                log("a map of the agreement report was loaded unmarked: %s"
                    % err)

    class AgreementAlgorithm(QgsProcessingAlgorithm):
        """rasterlabel:agreement"""

        def __init__(self):
            super().__init__()
            self.job = None

        def name(self):
            return "agreement"

        def group(self):
            return PROCESSING_GROUP

        def groupId(self):  # noqa: N802
            return PROCESSING_GROUP_ID

        def displayName(self):  # noqa: N802
            return "Agreement between two readings"

        def shortHelpString(self):  # noqa: N802
            return PROCESSING_HELP

        def createInstance(self):  # noqa: N802
            return type(self)()

        def initAlgorithm(self, config=None):  # noqa: N802
            # a folder parameter, as in the other four: it takes the
            # campaign's folder or its campaign.json
            self.addParameter(QgsProcessingParameterFile(
                "CAMPAIGN", "Campaign (its folder, or campaign.json)",
                folder_kind, "", None, False))
            self.addParameter(QgsProcessingParameterString(
                "READING_A", "Reading A (OPERATOR,pass, e.g. ANNA,1)"))
            self.addParameter(QgsProcessingParameterString(
                "READING_B", "Reading B (OPERATOR,pass, e.g. BRUNO,1)"))
            self.addParameter(QgsProcessingParameterEnum(
                "FRAMES", "Frames", PROCESSING_RULES, False, 0))
            self.addParameter(QgsProcessingParameterBoolean(
                "POINTS_IN", "Count the points, as in the mask", False))
            self.addParameter(QgsProcessingParameterNumber(
                "RESAMPLES", "Bootstrap resamples (0 = no interval)",
                integer, BOOTSTRAP_N, False, 0, 1000000))
            self.addParameter(QgsProcessingParameterNumber(
                "SEED", "Seed", integer, BOOTSTRAP_SEED, False, 0,
                2 ** 31 - 1))
            self.addParameter(QgsProcessingParameterBoolean(
                "ALLOW_UNFINISHED",
                "Compare even when a reading is unfinished", False))
            self.addParameter(QgsProcessingParameterFolderDestination(
                "OUTPUT_FOLDER", "Report folder (empty: reports/agreement/ "
                "in the campaign)", None, True))
            self.addOutput(QgsProcessingOutputRasterLayer(
                "DISAGREEMENT", "Disagreement map"))
            self.addOutput(QgsProcessingOutputRasterLayer(
                "PAIRS", "Map of pairs"))
            self.addOutput(QgsProcessingOutputVectorLayer(
                "VECTORS", "Places of disagreement"))
            self.addOutput(QgsProcessingOutputFile("SUMMARY", "summary.json"))
            for key, words in (("OVERALL", "Overall agreement"),
                               ("KAPPA", "Kappa (agreement statistic)"),
                               ("QUANTITY", "Quantity disagreement"),
                               ("ALLOCATION", "Allocation disagreement"),
                               ("MEAN_IOU", "Mean IoU"),
                               ("FRAMES_USED", "Frames compared")):
                self.addOutput(QgsProcessingOutputNumber(key, words))

        def prepareAlgorithm(self, parameters, context, feedback):  # noqa: N802
            manifest = self.parameterAsFile(parameters, "CAMPAIGN", context)
            if manifest and os.path.isdir(manifest):
                manifest = os.path.join(manifest, "campaign.json")
            if not manifest or not os.path.isfile(manifest):
                raise QgsProcessingException(
                    "No campaign.json at %s." % (manifest or "(nothing)"))
            folder = os.path.dirname(os.path.abspath(manifest))
            try:
                with open(manifest, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError) as err:
                raise QgsProcessingException(
                    "%s cannot be read as a campaign: %s" % (manifest, err))
            package = os.path.join(folder, "annotation.gpkg")
            if not os.path.isfile(package):
                raise QgsProcessingException(
                    "The campaign has no annotation.gpkg beside %s."
                    % os.path.basename(manifest))
            a = processing_reading(self.parameterAsString(
                parameters, "READING_A", context))
            b = processing_reading(self.parameterAsString(
                parameters, "READING_B", context))
            if a is None or b is None:
                raise QgsProcessingException(
                    "Name both readings as OPERATOR,pass, for example ANNA,1.")
            panel = processing_panel()
            if panel is not None and getattr(panel, "campaign", None) \
                    is not None and panel.campaign.data.get("id") \
                    == data.get("id"):
                refusal = panel.blind_gate([a, b])
                if refusal:
                    raise QgsProcessingException(refusal)
            rule = ("touched" if self.parameterAsEnum(
                parameters, "FRAMES", context) == 1 else "closed")
            points = self.parameterAsBool(parameters, "POINTS_IN", context)
            plan = cmp_plan(data, package, a, b, rule, points)
            if plan["refusal"]:
                raise QgsProcessingException(plan["refusal"])
            if not plan["used"]:
                raise QgsProcessingException(
                    "No frame qualifies: none was %s by both %s and %s."
                    % ("closed" if plan["frame_rule"] == "closed"
                       else "touched", reading_label(a), reading_label(b)))
            unfinished = compare_unfinished_text(plan, len(plan["used"]))
            if unfinished and not self.parameterAsBool(
                    parameters, "ALLOW_UNFINISHED", context):
                raise QgsProcessingException(
                    unfinished.rsplit(". Compare the", 1)[0]
                    + ". Set ALLOW_UNFINISHED to compare all the same.")
            target = self.parameterAsString(parameters, "OUTPUT_FOLDER",
                                            context) or ""
            if target == temporary:
                target = ""
            if target:
                target = os.path.abspath(target)
                if os.path.isdir(target):
                    if os.listdir(target):
                        target = os.path.join(target, "%s_%s" % (
                            cmp_label(a, b), report_stamp()))
                    else:
                        os.rmdir(target)
            self.job = {"data": data, "folder": folder, "package": package,
                        "plan": plan, "target": target or None,
                        "n_boot": self.parameterAsInt(parameters,
                                                      "RESAMPLES", context),
                        "seed": self.parameterAsInt(parameters, "SEED",
                                                    context),
                        "result": None}
            return True

        def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
            job = self.job
            if job is None:
                raise QgsProcessingException("The algorithm was not prepared.")
            n = max(1, len(job["plan"]["used"]))

            def tick(done, total):
                feedback.setProgress(100.0 * done / max(total, n))

            try:
                result = cmp_compare(job, tick, feedback.isCanceled)
            except CmpCancelled:
                raise QgsProcessingException("Cancelled: nothing was written.")
            except QgsProcessingException:
                raise
            except Exception as err:
                raise QgsProcessingException("Nothing was written: %s" % err)
            job["result"] = result
            folder, files = result["folder"], result["files"]
            o = result["summary"]["pooled"]["overall"]
            out = {"OUTPUT_FOLDER": folder,
                   "DISAGREEMENT": os.path.join(folder,
                                                files["disagreement"]),
                   "PAIRS": os.path.join(folder, files["pairs"]),
                   "VECTORS": os.path.join(folder, files["vectors"])
                   + "|layername=disagreement",
                   "SUMMARY": os.path.join(folder, "summary.json"),
                   "OVERALL": o["po"], "KAPPA": o.get("kappa"),
                   "QUANTITY": o["quantity"], "ALLOCATION": o["allocation"],
                   "MEAN_IOU": o["mean_iou"],
                   "FRAMES_USED": len(result["ids"])}
            feedback.pushInfo("%s vs %s: %d frame%s, overall %.4f, written in "
                              "%s" % (reading_label(job["plan"]["A"]),
                                      reading_label(job["plan"]["B"]),
                                      len(result["ids"]),
                                      "" if len(result["ids"]) == 1 else "s",
                                      o["po"], folder))
            self.load_on_completion(context, job, out)
            return out

        def load_on_completion(self, context, job, out):
            """The maps, for QGIS to load when the run is over, marked as
            the panel marks its own (and the frames left out)."""
            plan = job["plan"]
            readings = [plan["A"], plan["B"]]
            owner = job["data"].get("id", "")
            stem = os.path.splitext(job["result"]["files"]["vectors"])[0]
            folder = job["result"]["folder"]
            try:
                project = context.project()
                if project is None:
                    return
                for key, part, style in (
                        ("DISAGREEMENT", "disagreement", None),
                        ("VECTORS", "polygons", os.path.join(
                            folder, stem + "_polygons.qml"))):
                    post = ReportLayerMarks(owner, readings, part, style)
                    PROCESSING_STATE["post"].append(post)
                    details = QgsProcessingContext.LayerDetails(
                        "%s_%s" % (stem, part), project, key)
                    details.setPostProcessor(post)
                    context.addLayerToLoadOnCompletion(out[key], details)
            except Exception as err:
                log("the maps of the agreement report are written but will "
                    "not be loaded: %s" % err)

        def postProcessAlgorithm(self, context, feedback):  # noqa: N802
            result = (self.job or {}).get("result")
            if result:
                try:
                    compare_vector_styles(os.path.join(
                        result["folder"], result["files"]["vectors"]))
                except Exception as err:
                    feedback.pushInfo("no style for the polygons: %s" % err)
            return {}

    class MeasureAlgorithm(QgsProcessingAlgorithm):
        """What the algorithms of the Measure menu share. A request is
        read and checked in prepareAlgorithm, on the main thread, where the
        layers live (self.measure_prepare); the work is done in processAlgorithm
        (self.measure_run). Whatever is refused or fails reaches Processing as a
        QgsProcessingException that says why, and nothing is left behind."""
        NAME = ""
        TITLE = ""
        HELP = ""
        NO_THREADING = False

        def __init__(self):
            super().__init__()
            self.job = None

        def name(self):
            return self.NAME

        def displayName(self):  # noqa: N802
            return self.TITLE

        def group(self):
            return PROCESSING_GROUP

        def groupId(self):  # noqa: N802
            return PROCESSING_GROUP_ID

        def shortHelpString(self):  # noqa: N802
            return self.HELP

        def createInstance(self):  # noqa: N802
            return type(self)()

        def flags(self):
            base = super().flags()
            if self.NO_THREADING and no_threading is not None:
                return base | no_threading
            return base

        def measure_prepare(self, parameters, context, feedback):
            raise NotImplementedError

        def measure_run(self, job, parameters, context, feedback):
            raise NotImplementedError

        def prepareAlgorithm(self, parameters, context, feedback):  # noqa: N802
            try:
                self.job = self.measure_prepare(parameters, context, feedback)
            except ProcessingRefusal as err:
                raise QgsProcessingException(str(err))
            return True

        def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
            if self.job is None:
                raise QgsProcessingException("The algorithm was not prepared.")
            try:
                return self.measure_run(self.job, parameters, context, feedback)
            except QgsProcessingException:
                raise
            except (ProcessingRefusal, UncRefused) as err:
                raise QgsProcessingException(str(err))
            except (CmpCancelled, MvcCancelled, CardCancelled, TimeCancelled):
                raise QgsProcessingException("Cancelled: nothing was written.")
            except Exception as err:
                raise QgsProcessingException("Nothing was written: %s" % err)

        def folder_of(self, parameters, context, key):
            return self.parameterAsFile(parameters, key, context)

        def target_of(self, parameters, context):
            return processing_target(self.parameterAsString(
                parameters, "OUTPUT_FOLDER", context))

    class ModelVsCorrectedAlgorithm(MeasureAlgorithm):
        """rasterlabel:model_vs_corrected"""
        NAME = "model_vs_corrected"
        TITLE = "Model vs corrected"
        HELP = PROCESSING_MVC_HELP

        def initAlgorithm(self, config=None):  # noqa: N802
            self.addParameter(QgsProcessingParameterFile(
                "CORRECTION", "Correction (its folder, or correction.json)",
                folder_kind, "", None, False))
            self.addParameter(QgsProcessingParameterEnum(
                "SCOPE", "On which ground", PROCESSING_MVC_SCOPES, False, 0))
            self.addParameter(QgsProcessingParameterVectorLayer(
                "POLYGONS", "Polygons (for 'inside the polygons')",
                [polygon_type] if polygon_type is not None else [], None,
                True))
            self.addParameter(QgsProcessingParameterBoolean(
                "SELECTED_ONLY", "Selected polygons only", False))
            self.addParameter(QgsProcessingParameterFile(
                "PEOPLE", "People to set the model beside: the folder of "
                "another person's correction of the same map, or of an "
                "agreement report (optional)", folder_kind, "", None, True))
            self.addParameter(QgsProcessingParameterBoolean(
                "WRITE_MAP", "Write the map of pairs", True))
            self.addParameter(QgsProcessingParameterFolderDestination(
                "OUTPUT_FOLDER", "Report folder (empty: "
                "reports/model_vs_corrected/ in the correction)", None, True))
            self.addOutput(QgsProcessingOutputFile("SUMMARY", "summary.json"))
            self.addOutput(QgsProcessingOutputRasterLayer(
                "PAIRS_MAP", "Map of pairs"))
            for key, words in (("OVERALL", "Overall accuracy of the model"),
                               ("QUANTITY", "Quantity disagreement"),
                               ("ALLOCATION", "Allocation disagreement"),
                               ("PIXELS", "Pixels compared")):
                self.addOutput(QgsProcessingOutputNumber(key, words))

        def measure_prepare(self, parameters, context, feedback):
            kind, folder, data = processing_owner_of(
                self.folder_of(parameters, context, "CORRECTION"),
                ("correction",))
            scope = MVC_SCOPES[self.parameterAsEnum(parameters, "SCOPE",
                                                    context)]
            layer = self.parameterAsVectorLayer(parameters, "POLYGONS",
                                                context) \
                if scope == "polygons" else None
            job = processing_mvc_job(
                folder, data, scope, layer,
                self.parameterAsBool(parameters, "SELECTED_ONLY", context),
                context.transformContext(),
                self.parameterAsFile(parameters, "PEOPLE", context),
                self.parameterAsBool(parameters, "WRITE_MAP", context))
            job["target"] = self.target_of(parameters, context)
            return job

        def measure_run(self, job, parameters, context, feedback):
            def tick(done, total):
                feedback.setProgress(100.0 * done / max(1, total))
                return not feedback.isCanceled()

            result = mvc_report(job["recipe"], job["record"], job["folder"],
                                job["people"], job["target"], tick,
                                feedback.isCanceled)
            folder = result["folder"]
            o = result["summarized"]["metrics"]["overall"]
            made = (result.get("map") or {}).get("path") or ""
            feedback.pushInfo(
                "model vs corrected, %s: the model agrees on %.4f of %d px, "
                "written in %s" % (MVC_SCOPE_WORDS[result["scope"]],
                                   o["po"], result["summarized"]["n"],
                                   folder))
            out = {"OUTPUT_FOLDER": folder,
                   "SUMMARY": os.path.join(folder, REPORT_SUMMARY),
                   "PAIRS_MAP": made, "OVERALL": o["po"],
                   "QUANTITY": o["quantity"], "ALLOCATION": o["allocation"],
                   "PIXELS": result["summarized"]["n"]}
            if made:
                self.load_on_completion(context, out)
            return out

        def load_on_completion(self, context, out):
            """The map of pairs, for QGIS to load when the run is over."""
            try:
                project = context.project()
                if project is None:
                    return
                name = os.path.splitext(os.path.basename(out["PAIRS_MAP"]))[0]
                context.addLayerToLoadOnCompletion(
                    out["PAIRS_MAP"], QgsProcessingContext.LayerDetails(
                        name, project, "PAIRS_MAP"))
            except Exception as err:
                log("the map of pairs is written but will not be loaded: %s"
                    % err)

    class TimeReportAlgorithm(MeasureAlgorithm):
        """rasterlabel:time_report"""
        NAME = "time_report"
        TITLE = "Time report"
        HELP = PROCESSING_TIME_HELP
        NO_THREADING = True

        def initAlgorithm(self, config=None):  # noqa: N802
            self.addParameter(QgsProcessingParameterFile(
                "OWNER", "Campaign or correction (its folder, or its "
                "campaign.json or correction.json)", folder_kind, "", None,
                False))
            self.addParameter(QgsProcessingParameterFile(
                "PAIRED_WITH", "A correction to set beside a campaign's "
                "drawing, or the campaign of a correction (optional)",
                folder_kind, "", None, True))
            self.addParameter(QgsProcessingParameterString(
                "READINGS", "Readings drawn from scratch (OPERATOR,pass; "
                "separate several with ;  empty: every reading)", None,
                False, True))
            self.addParameter(QgsProcessingParameterNumber(
                "IDLE_S", "Idle limit, in seconds (a gap longer than this "
                "is not work)", integer, IDLE_DEFAULT_S, False, 1, 86400))
            self.addParameter(QgsProcessingParameterEnum(
                "FRAMES", "Frames", PROCESSING_TIME_RULES, False, 0))
            self.addParameter(QgsProcessingParameterFolderDestination(
                "OUTPUT_FOLDER", "Report folder (empty: reports/time/ in "
                "the campaign, or in the correction)", None, True))
            self.addOutput(QgsProcessingOutputFile(
                "SUMMARY", "time_summary.json"))
            for key, words in (
                    ("ACTIVE_H", "Active time, hours"),
                    ("MIN_PER_HA_SCRATCH", "Drawing from scratch, minutes "
                     "per hectare"),
                    ("MIN_PER_HA_CORRECT", "Correcting, minutes per hectare"),
                    ("RATIO", "Correcting over drawing, frame by frame"),
                    ("FRAMES_USED", "Frames in the report")):
                self.addOutput(QgsProcessingOutputNumber(key, words))

        def measure_prepare(self, parameters, context, feedback):
            rule = PROCESSING_TIME_KEYS[self.parameterAsEnum(
                parameters, "FRAMES", context)]
            plan = processing_time_job(
                self.folder_of(parameters, context, "OWNER"),
                self.folder_of(parameters, context, "PAIRED_WITH"),
                self.parameterAsString(parameters, "READINGS", context),
                self.parameterAsInt(parameters, "IDLE_S", context), rule,
                self.target_of(parameters, context))
            return {"plan": plan}

        def measure_run(self, job, parameters, context, feedback):
            result = time_write(job["plan"], feedback.isCanceled)
            folder, head = result["folder"], result["headline"]
            used = result["summary"].get("frames_used") or []
            for line in result["warnings"]:
                feedback.pushInfo("warning: %s" % line)
            feedback.pushInfo("time: %d frame%s, active %s h, written in %s"
                              % (len(used), "" if len(used) == 1 else "s",
                                 head.get("active_h"), folder))
            return {"OUTPUT_FOLDER": folder,
                    "SUMMARY": os.path.join(folder, TIME_FILES["summary"]),
                    "ACTIVE_H": head.get("active_h"),
                    "MIN_PER_HA_SCRATCH": head.get("min_per_ha_scratch"),
                    "MIN_PER_HA_CORRECT": head.get("min_per_ha_correct"),
                    "RATIO": head.get("ratio"), "FRAMES_USED": len(used)}

    class UncertaintyReportAlgorithm(MeasureAlgorithm):
        """rasterlabel:uncertainty_report"""
        NAME = "uncertainty_report"
        TITLE = "Uncertainty report"
        HELP = PROCESSING_UNCERTAINTY_HELP
        NO_THREADING = True

        def initAlgorithm(self, config=None):  # noqa: N802
            self.addParameter(QgsProcessingParameterFile(
                "CORRECTION", "Correction (its folder, or correction.json) "
                "with an uncertainty chosen", folder_kind, "", None, False))
            self.addParameter(QgsProcessingParameterBoolean(
                "DRAW", "Draw the picture of the curve (calibration.png)",
                True))
            self.addParameter(QgsProcessingParameterFolderDestination(
                "OUTPUT_FOLDER", "Report folder (empty: "
                "reports/uncertainty/ in the correction)", None, True))
            self.addOutput(QgsProcessingOutputFile("SUMMARY", "summary.json"))
            for key, words in (
                    ("AUC", "AUC of the uncertainty (random places when "
                     "there are, else the whole map)"),
                    ("AUC_RANDOM", "AUC, random places"),
                    ("AUC_WHOLE", "AUC, whole map"),
                    ("ECE", "ECE (random places when there are, else the "
                     "whole map; only when u is 1 - p)"),
                    ("ECE_RANDOM", "ECE, random places"),
                    ("ECE_WHOLE", "ECE, whole map"),
                    ("RANDOM_DONE", "Random places done")):
                self.addOutput(QgsProcessingOutputNumber(key, words))

        def measure_prepare(self, parameters, context, feedback):
            kind, folder, data = processing_owner_of(
                self.folder_of(parameters, context, "CORRECTION"),
                ("correction",))
            return processing_unc_job(
                folder, data, self.target_of(parameters, context),
                self.parameterAsBool(parameters, "DRAW", context))

        def measure_run(self, job, parameters, context, feedback):
            def tick(done, total):
                feedback.setProgress(100.0 * done / max(1, total))
                return not feedback.isCanceled()

            result = unc_report(
                job["owner"], job["record"], job["spec"], job["arrays"],
                job["places"], job["paths"], job["operations"],
                job["target"], tick, job["draw"])
            folder = result["folder"]
            summary = result["summary"]
            head = summary.get("headline") or {}
            ece_fixed = summary.get("ece_fixed") or {}
            auc_r, auc_w = head.get("auc_random"), head.get("auc_whole")
            ece_r, ece_w = ece_fixed.get("random_places"), \
                ece_fixed.get("whole_map")
            feedback.pushInfo(
                "uncertainty: AUC %s on the random places, %s on the whole "
                "map; written in %s" % (auc_r, auc_w, folder))
            return {"OUTPUT_FOLDER": folder,
                    "SUMMARY": os.path.join(folder, REPORT_SUMMARY),
                    "AUC": auc_r if auc_r is not None else auc_w,
                    "AUC_RANDOM": auc_r, "AUC_WHOLE": auc_w,
                    "ECE": ece_r if ece_r is not None else ece_w,
                    "ECE_RANDOM": ece_r, "ECE_WHOLE": ece_w,
                    "RANDOM_DONE": head.get("random_done")}

    class DatasetCardAlgorithm(MeasureAlgorithm):
        """rasterlabel:dataset_card"""
        NAME = "dataset_card"
        TITLE = "Dataset card"
        HELP = PROCESSING_CARD_HELP

        def initAlgorithm(self, config=None):  # noqa: N802
            self.addParameter(QgsProcessingParameterFile(
                "OWNER", "Campaign or correction (its folder, or its "
                "campaign.json or correction.json)", folder_kind, "", None,
                False))
            self.addParameter(QgsProcessingParameterFolderDestination(
                "OUTPUT_FOLDER", "Card folder (empty: reports/card/ in the "
                "campaign, or in the correction)", None, True))
            self.addOutput(QgsProcessingOutputFile("CARD_MD", "Card, Markdown"))
            self.addOutput(QgsProcessingOutputFile("CARD_JSON", "Card, JSON"))

        def measure_prepare(self, parameters, context, feedback):
            job = processing_card_job(self.folder_of(parameters, context,
                                                     "OWNER"))
            job["target"] = self.target_of(parameters, context)
            return job

        def measure_run(self, job, parameters, context, feedback):
            def progress(text, done, total):
                feedback.setProgress(100.0 * float(done) / max(float(total),
                                                               1.0))
                feedback.setProgressText("dataset card, %s" % text)
                if feedback.isCanceled():
                    raise CardCancelled("Cancelled: nothing was written.")

            if job["kind"] == "campaign":
                card = card_gather_campaign(job["data"], job["folder"],
                                            job["package"], progress=progress)
            else:
                card = card_gather_correction(job["data"], job["folder"],
                                              progress=progress)
            if feedback.isCanceled():
                raise CardCancelled("Cancelled: nothing was written.")
            if job["target"]:
                tmp, final = cmp_target(job["target"])
            else:
                tmp, final = report_folder(job["folder"], "card")
            try:
                card_write(card, tmp, job["stem"])
                done = report_finish(tmp, final)
            except BaseException:
                report_abandon(tmp)
                raise
            md_name, json_name = card_names(job["stem"])
            feedback.pushInfo("dataset card written in %s: %s and .json. %s"
                              % (done, md_name, card_summary(card)))
            for line in card_stale_lines(card):
                feedback.pushInfo(line)
            return {"OUTPUT_FOLDER": done,
                    "CARD_MD": os.path.join(done, md_name),
                    "CARD_JSON": os.path.join(done, json_name)}

    class RasterLabelProvider(QgsProcessingProvider):
        """RasterLabel in the Processing toolbox."""

        def id(self):
            return PROCESSING_ID

        def name(self):
            return NAME

        def longName(self):  # noqa: N802
            return "%s: measures of an annotation campaign" % NAME

        def icon(self):
            here = os.path.dirname(os.path.abspath(globals().get(
                "__file__") or "."))
            path = os.path.join(here, "icon.svg")
            return QIcon(path) if os.path.isfile(path) else \
                QgsProcessingProvider.icon(self)

        def loadAlgorithms(self):  # noqa: N802
            self.addAlgorithm(AgreementAlgorithm())
            self.addAlgorithm(ModelVsCorrectedAlgorithm())
            self.addAlgorithm(TimeReportAlgorithm())
            self.addAlgorithm(UncertaintyReportAlgorithm())
            self.addAlgorithm(DatasetCardAlgorithm())

    PROCESSING_STATE["classes"] = (RasterLabelProvider, AgreementAlgorithm)
    return PROCESSING_STATE["classes"]


def processing_registry():
    try:
        from qgis.core import QgsApplication
        registry = getattr(QgsApplication, "processingRegistry", None)
        return registry() if callable(registry) else None
    except Exception:
        return None


def processing_register():
    """Put RasterLabel's provider in the Processing toolbox, once.

    Called by the plugin's initProcessing and by every start of the panel,
    so the single file pasted into the console has it too. A provider of
    this build already there is left as it is; one from another build (an
    earlier paste) gives way to this one. Returns the provider, or None
    where there is no Processing."""
    registry = processing_registry()
    if registry is None:
        return None
    try:
        old = registry.providerById(PROCESSING_ID)
        if old is not None:
            if getattr(old, "rasterlabel_build", None) == BUILD:
                return old
            registry.removeProvider(old)
        provider = processing_classes()[0]()
        provider.rasterlabel_build = BUILD
        if not registry.addProvider(provider):
            log("the Processing provider could not be added")
            return None
        PROCESSING_STATE["provider"] = provider
        return provider
    except Exception as err:
        log("RasterLabel is not in the Processing toolbox: %s" % err)
        return None


def processing_unregister():
    """Take the provider out of the toolbox again (the plugin's unload)."""
    registry = processing_registry()
    if registry is None:
        return False
    try:
        old = registry.providerById(PROCESSING_ID)
        if old is not None:
            registry.removeProvider(old)
        PROCESSING_STATE["provider"] = None
        del PROCESSING_STATE["post"][:]
        return old is not None
    except Exception as err:
        log("the Processing provider could not be taken away: %s" % err)
        return False
