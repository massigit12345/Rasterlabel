"""rasterlabel.card

The dataset card: one file for people (Markdown) and one for programs
(JSON) that say what a campaign or a correction holds, how it was made and
by which build, in the spirit of datasheets for datasets (Gebru et al. 2021)
and data cards (Pushkarna et al. 2022).

Two halves. The first only turns numbers into text: the rules as sentences,
the STAC label fields, the GeoTIFF tags, the Markdown, and the two files
written atomically. The second counts the numbers (card_gather_campaign,
card_gather_correction): pixels per class in every reading, in all of them
together and in every consensus, burned with the very Stencil and vote that
write the masks, on the campaign grid, by pixel centre; the frames and how
complete each reading made them, by campaign.reading_shares, the one
definition of closed; and for a correction, the map before and after, read
with band_counts, and the pixels a person changed. So the card cannot
disagree with the files it describes. A card only ever states counts that
were made; it claims nothing it did not count.

The numbers of other reports (agreement, time, model vs corrected,
uncertainty) are copied in, never recomputed, from their summary.json, and a
report made before the last change to what it describes is marked "may be
stale".

Nothing here writes into a campaign or a correction: the package is opened
read only, the manifest is only read, and the card goes where the caller
says. No QGIS: GDAL, OGR and numpy only, so it runs headless.
"""
import csv
import io
import os

from datetime import datetime, timezone

import numpy as np
from osgeo import gdal, ogr, osr

from .constants import (BUILD, CARD_FORMAT, CARD_SUFFIX, CLOSED_SHARE,
                        GEOTIFF_TYPE, IGNORE_CODE, LABEL_EXT, MAX_CLASS_CODE,
                        NAME, OPERATOR_BLANK, PIXEL_RULE, PIXEL_RULE_TEXT,
                        PROJ_EXT, REPORTS_FOLDER, REPORT_TMP, SHAPE,
                        STAC_VERSION, STRIP_ROWS, VERSION)
from .naming import csv_untext_row, from_folder, long_path, now
from .errors import environment, log
from .reports import (report_find, report_headline, report_inputs,
                      report_json, report_read, report_stale, report_text,
                      report_utc)
from .campaign import (READING_TABLES, frame_design,
                       frames_by_readings_text, operator_word, pass_number,
                       reading_choices, reading_closed, reading_label,
                       reading_rule, reading_shares, readings_in)
from .rasters import (ConsensusCover, Stencil, band_counts, class_counts,
                      flag_band_of, is_rotated, pixel_grid, vote)
from .geometry import aligned, ground_rows_of, north_up_of, snap
from .correction import changes_path_of, copy_in_folder, tally_operations


# Which reports feed which card.
CARD_FEEDS = {"campaign": ("agreement", "time"),
              "correction": ("model_vs_corrected", "uncertainty", "time")}
# Where each of them keeps its summary: (folder kind under reports/, the
# kind its summary says it is, the name of the summary), tried in order.
# Time names its summary time_summary.json; model vs corrected is looked for
# under its long name and its short one, so the card finds it whichever the
# report settles on.
CARD_FEED_SOURCES = {
    "agreement": (("agreement", "agreement", "summary.json"),),
    "time": (("time", "time", "time_summary.json"),
             ("time", "time", "summary.json")),
    "model_vs_corrected": (
        ("model_vs_corrected", "model_vs_corrected", "summary.json"),
        ("model_vs_corrected", "mvc", "summary.json"),
        ("model_vs_corrected", "model_vs_corrected", "mvc_summary.json"),
        ("mvc", "mvc", "summary.json")),
    "uncertainty": (("uncertainty", "uncertainty", "summary.json"),
                    ("uncertainty", "uncertainty", "uncertainty_summary.json")),
}
CARD_FEED_TITLES = {"agreement": "Agreement", "time": "Time",
                    "model_vs_corrected": "Model vs corrected",
                    "uncertainty": "Uncertainty"}


def card_rules(points_in_mask=None, ignore_index=None, all_rule=""):
    """The rules that made the pixels, as the sentences a card writes."""
    return {
        "pixel_rule": PIXEL_RULE,
        "pixel_rule_text": PIXEL_RULE_TEXT,
        "unlabelled_value": 0,
        "class_codes": "1-%d" % MAX_CLASS_CODE,
        "reserved_value": IGNORE_CODE,
        "ignore_index": ignore_index,
        "within_reading_overlap": "last drawn wins",
        "all_readings": all_rule or "",
        "consensus": "strict majority, n//2+1 of n readings, n being the "
                     "readings that covered the frame",
        "closed": "fullest single reading paints > %s%% of the frame area"
                  % card_percent(CLOSED_SHARE, 1, sign=False),
        "points_in_mask": points_in_mask,
        "lines_in_mask": False,
        "operator_normalisation": "trimmed, upper case, empty = %s"
                                  % OPERATOR_BLANK,
        "default_reading_number": 1,
    }


def card_limits(kind="campaign"):
    """What a card does not say, in so many words."""
    out = ["counts are pixels on the %s grid at full resolution"
           % ("campaign" if kind == "campaign" else "map's"),
           "areas in degrees are approximate: the pixel size is measured "
           "at the centre of the raster",
           "kappa is reported only as an agreement statistic between "
           "readings, never as accuracy (Pontius & Millones 2011; Foody "
           "2020)",
           "operator names are personal data"]
    if kind == "campaign":
        out.insert(1, "0 inside a window is not counted as unlabelled "
                      "ground")
    return out


def card_percent(share, digits=1, sign=True):
    """A share as a percentage, or an empty string when it is undefined."""
    try:
        v = float(share) * 100.0
    except (TypeError, ValueError):
        return ""
    if v != v:
        return ""
    text = ("%%.%df" % digits) % v
    return text + "%" if sign else text


def card_class_names(classes):
    """{code: name} of a legend, retired classes marked as such."""
    out = {}
    for c in classes or []:
        name = c.get("name") or "code %s" % c.get("code")
        out[int(c["code"])] = name + (" (retired)" if c.get("retired")
                                      else "")
    return out


def card_stac_label_fields(product, classes, data, methods=("manual",),
                           description=None, ignore_index=None,
                           reading_rule=""):
    """The STAC label extension fields (v1.0.1) of one described product.

    Filled with the counts the product really holds: label:classes lists the
    classes of the legend still in use and any code the product holds;
    label:overviews gives each of them its pixel count, 0 included. Plus the
    rasterlabel:* fields that say how the counts were made.

    label:overviews names its property_key "class_code", the band of the
    mask the counts are of: the pinned label schema (v1.0.1) wants a string
    there and refuses null, and a raster label has no attribute to name."""
    counts = {int(k): int(v) for k, v in (product.get("counts") or {}).items()}
    live = [c for c in classes or [] if not c.get("retired")]
    names = card_class_names(classes)
    codes = sorted(set(int(c["code"]) for c in live)
                   | set(k for k, v in counts.items() if v))
    if description is None:
        description = ("Hand-drawn class areas of campaign %s, %s, burned on "
                       "the campaign grid by pixel centre; 0 is unlabelled. "
                       "The overview counts the pixels of the band "
                       "class_code." % (data.get("name", ""),
                                        product.get("label", "")))
    return {
        "label:type": "raster",
        "label:properties": None,
        "label:classes": [{"name": None, "classes": codes}],
        "label:description": description,
        "label:methods": list(methods),
        "label:tasks": ["segmentation"],
        "label:overviews": [{"property_key": "class_code", "counts": [
            {"name": names.get(c, "code %d" % c), "count": counts.get(c, 0)}
            for c in codes]}],
        "rasterlabel:version": VERSION,
        "rasterlabel:build": BUILD,
        "rasterlabel:campaign_id": data.get("id", ""),
        "rasterlabel:reading_mode": product.get("mode", ""),
        "rasterlabel:readings": [list(r) for r in product.get("readings")
                                 or []],
        "rasterlabel:reading_rule": reading_rule or "",
        "rasterlabel:pixel_rule": PIXEL_RULE,
        "rasterlabel:unlabelled": 0,
        "rasterlabel:ignore_index": ignore_index,
    }


def card_provenance_metadata(data, card_name=None):
    """The GeoTIFF tags every mask carries beside its reading tags."""
    out = {"RASTERLABEL_BUILD": BUILD,
           "RASTERLABEL_CAMPAIGN_ID": str(data.get("id", "")),
           "RASTERLABEL_PIXEL_RULE": PIXEL_RULE_TEXT,
           "RASTERLABEL_UNLABELLED": "0"}
    if card_name:
        out["RASTERLABEL_CARD"] = os.path.basename(card_name)
    return out


def _card_find(owner_folder, folder_kind, report_kind, owner_id, name):
    """The finished reports under reports/<folder_kind>/ whose summary (of
    this name) says it is a report_kind made of this owner, newest first, as
    (folder, summary). report_find when the two kinds are one word."""
    if folder_kind == report_kind:
        return report_find(owner_folder, report_kind, owner_id, name=name)
    base = os.path.join(owner_folder, REPORTS_FOLDER, folder_kind)
    try:
        names = os.listdir(long_path(base))
    except OSError:
        return []
    found = []
    for n in names:
        if n.endswith(REPORT_TMP):
            continue
        summary = report_read(os.path.join(base, n, name))
        if not isinstance(summary, dict) \
                or summary.get("rasterlabel:report") != report_kind \
                or (summary.get("owner") or {}).get("id") != owner_id:
            continue
        found.append((summary.get("created_utc") or "", n,
                      os.path.join(base, n), summary))
    found.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [(folder, summary) for _, _, folder, summary in found]


def _card_same_input(old, cur):
    a, b = old.get("path") or "", cur.get("path") or ""
    if not a or not b:
        return False
    norm = lambda p: os.path.normcase(os.path.normpath(os.path.abspath(p)))
    return norm(a) == norm(b) or os.path.basename(a) == os.path.basename(b)


def card_feed_stale(summary, current_inputs, summary_path=None):
    """(stale, reason) of a report the card copies.

    When the report wrote down the files it was made from, the rule of
    reports.report_stale: a sha256 that differs from the file's now, or, with
    no sha, a file newer than the one recorded. When it wrote down none of
    the files the card is made from, the summary itself is compared by time
    with the newest of them: a report older than the last change is marked."""
    current = list(current_inputs or [])
    recorded = (summary or {}).get("inputs") or []
    if any(_card_same_input(old, cur) for old in recorded for cur in current):
        return report_stale(summary, current)
    if not summary_path:
        return False, ""
    try:
        made = report_utc(datetime.fromtimestamp(
            os.path.getmtime(long_path(summary_path)), timezone.utc))
    except OSError:
        return False, ""
    for cur in current:
        when = cur.get("mtime_utc")
        if when and when > made:
            return True, "%s is newer than the report" % os.path.basename(
                cur.get("path") or "")
    return False, ""


def card_feed(owner_folder, kind, owner_id, current_inputs):
    """The newest report of this kind made of this owner, as the card
    copies it: {source, created_utc, stale, stale_reason, headline}, or
    None when there is none."""
    for folder_kind, report_kind, name in CARD_FEED_SOURCES.get(
            kind, ((kind, kind, "summary.json"),)):
        found = _card_find(owner_folder, folder_kind, report_kind, owner_id,
                           name)
        if not found:
            continue
        folder, summary = found[0]
        stale, why = card_feed_stale(summary, current_inputs,
                                     os.path.join(folder, name))
        return {"source": os.path.relpath(folder, owner_folder)
                .replace("\\", "/") + "/" + name,
                "created_utc": summary.get("created_utc", ""),
                "stale": stale, "stale_reason": why,
                "headline": report_headline(kind,
                                            summary.get("headline") or {})}
    return None


def card_feed_refused(owner_folder, kind, owner_id):
    """Sentences about the summaries of this kind of report that are in the
    owner's reports/ but are not taken: made of another campaign or
    correction, or not a report of this kind."""
    out = []
    seen = set()
    for folder_kind, report_kind, name in CARD_FEED_SOURCES.get(
            kind, ((kind, kind, "summary.json"),)):
        base = os.path.join(owner_folder, REPORTS_FOLDER, folder_kind)
        try:
            names = sorted(os.listdir(long_path(base)))
        except OSError:
            continue
        for n in names:
            path = os.path.join(base, n, name)
            if n.endswith(REPORT_TMP) or path in seen \
                    or not os.path.isfile(long_path(path)):
                continue
            seen.add(path)
            summary = report_read(path)
            if not isinstance(summary, dict):
                out.append("%s/%s/%s is not a report the card can read, and "
                           "is left out" % (folder_kind, n, name))
                continue
            if summary.get("rasterlabel:report") not in (report_kind, kind):
                continue
            if (summary.get("owner") or {}).get("id") != owner_id:
                out.append("%s/%s was made of another %s (id %s), and is "
                           "left out" % (folder_kind, n, (summary.get(
                               "owner") or {}).get("kind") or "owner",
                               (summary.get("owner") or {}).get("id")))
    return sorted(set(out))


def card_feeds(owner_folder, owner_kind, owner_id, current_inputs):
    """{kind: feed or None} for every report that feeds this kind of card."""
    return {k: card_feed(owner_folder, k, owner_id, current_inputs)
            for k in CARD_FEEDS.get(owner_kind, ())}


def card_cell(value):
    """A number as the Markdown tables write it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if value != value:
            return ""
        if value == int(value) and abs(value) < 1e15:
            return "%d" % value
        return "%.4g" % value
    return str(value)


def card_values(items):
    """A list of numbers for a line of the Markdown: [value, low, high] as
    "value (low to high)", [low, high] as "low to high", any other list as
    its numbers with commas; an entry a report left empty (no bootstrap, so
    no interval) is left out rather than written as a bare comma."""
    shown = [card_cell(x) for x in items]
    if len(shown) == 3 and all(shown):
        return "%s (%s to %s)" % tuple(shown)
    if len(shown) == 2 and all(shown):
        return "%s to %s" % tuple(shown)
    return ", ".join(s for s in shown if s)


def card_table(header, rows):
    """A Markdown table."""
    out = ["| " + " | ".join(str(h) for h in header) + " |",
           "|" + "---|" * len(header)]
    for r in rows:
        out.append("| " + " | ".join(card_cell(v) for v in r) + " |")
    return out


def _card_column(product):
    tag = product.get("tag") or product.get("label") or product.get("mode")
    return str(tag).replace("_", " ")


def _card_counts(product):
    return {int(k): int(v) for k, v in (product.get("counts") or {}).items()}


def card_described(card):
    """The product the card describes: the one named by its STAC block, or
    the consensus over every pass, the first consensus, the only reading,
    "all", in that order."""
    products = card.get("products") or []
    if not products:
        return None
    named = (card.get("stac") or {}).get("describes")
    for p in products:
        if named and p.get("label") == named:
            return p
    # reading_choices calls both kinds of consensus "consensus"; the one of
    # every reading is told apart by its tag
    for p in products:
        if p.get("mode") == "consensus_all" or (
                p.get("mode") == "consensus"
                and p.get("tag") == "consensus_all"):
            return p
    for p in products:
        if p.get("mode") == "consensus":
            return p
    ones = [p for p in products if p.get("mode") == "one"]
    if len(ones) == 1:
        return ones[0]
    for p in products:
        if p.get("mode") == "all":
            return p
    return products[0]


def card_consensus_line(product):
    """The sentence under the class table about one consensus."""
    votes = {int(k): int(v) for k, v in
             (product.get("votes_histogram") or {}).items()}
    n = len(product.get("readings") or [])
    none = int(product.get("no_majority_px") or 0)
    differ = int(product.get("all_painted_disagree_px") or 0)
    if product.get("partial_design"):
        # some frames were read by fewer readings than the vote holds, so
        # "of n" would not say who was asked: the majority is of the
        # readings of each frame
        agreed = ", ".join("%d px agreed by %d reading%s"
                           % (votes[k], k, "" if k == 1 else "s")
                           for k in sorted(votes, reverse=True)
                           if k and votes[k])
        read = frames_by_readings_text(
            {int(k): int(v) for k, v in
             (product.get("frames_by_readings") or {}).items()})
        return ("%s: %s, %d px without a majority (%d painted by every "
                "reading of the frame with no class in the majority, %d by "
                "fewer). A pixel needs a majority of the readings that "
                "covered its frame: %s" % (
                    _card_column(product), agreed or "no pixel agreed",
                    none, differ, none - differ, read or "no frame read"))
    agreed = ", ".join("%d px agreed by %d of %d" % (votes[k], k, n)
                       for k in sorted(votes, reverse=True) if k and votes[k])
    if n == 2:
        tail = "(%d painted by both differently, %d by one only)" \
            % (differ, none - differ)
    else:
        # all n painted and no class holds a majority: with three readings
        # that is three different classes, with more it may be two and two
        how = "differently" if n == 3 else "with no class in the majority"
        tail = "(%d painted by all %d %s, %d by fewer)" \
            % (differ, n, how, none - differ)
    label = _card_column(product)
    return "%s: %s, %d px without a majority %s" % (
        label, agreed or "no pixel agreed", none, tail)


def _card_campaign_classes(card, lines):
    products = card.get("products") or []
    if not products:
        lines.append("Nothing drawn yet: no reading holds a mark.")
        return
    names = card_class_names(card.get("classes"))
    ones = [p for p in products if p.get("mode") == "one"]
    rest = [p for p in products if p.get("mode") == "all"]
    cons = [p for p in products if str(p.get("mode", "")).startswith(
        "consensus")]
    described = card_described(card)
    wide = len(ones) > 4
    main = ([] if wide else ones) + rest + cons
    # every class of the legend in use, and any code a product holds; a
    # retired class with no pixel anywhere is not a row of zeros
    codes = sorted(set(k for p in products for k, v in
                       _card_counts(p).items() if v)
                   | set(int(c["code"]) for c in card.get("classes") or []
                         if not c.get("retired")))
    total = float(described.get("labelled_px") or 0) if described else 0.0
    header = ["code", "class"] + [_card_column(p) for p in main]
    if described is not None:
        header.append("share (%s)" % _card_column(described))
    rows = []
    for c in codes:
        row = [c, names.get(c, "code %d (not in the legend)" % c)]
        row += [_card_counts(p).get(c, 0) for p in main]
        if described is not None:
            share = _card_counts(described).get(c, 0) / total if total else None
            row.append(card_percent(share) if share is not None else "")
        rows.append(row)
    lines.extend(card_table(header, rows))
    for p in cons:
        lines.append("")
        lines.append(card_consensus_line(p))
    if wide:
        lines.append("")
        lines.append("Each reading:")
        lines.append("")
        lines.extend(card_table(
            ["code", "class"] + [_card_column(p) for p in ones],
            [[c, names.get(c, "code %d" % c)]
             + [_card_counts(p).get(c, 0) for p in ones] for c in codes]))


def _card_feed_lines(card, lines):
    for kind in ("agreement", "time", "model_vs_corrected", "uncertainty"):
        feed = card.get(kind)
        if not feed:
            continue
        lines.append("")
        lines.append("## %s" % CARD_FEED_TITLES[kind])
        lines.append("")
        line = "From %s" % feed.get("source", "")
        if feed.get("stale"):
            line += " (may be stale: %s)" % (feed.get("stale_reason")
                                              or "older than the data")
        lines.append(line + ".")
        lines.append("")
        for key, value in sorted((feed.get("headline") or {}).items()):
            if value is None:
                continue
            if isinstance(value, dict):
                value = "; ".join(
                    "%s %s" % (k, text) for k, text in (
                        (k, card_values(v) if isinstance(v, list)
                         else card_cell(v))
                        for k, v in sorted(value.items())) if text)
            elif isinstance(value, list):
                value = card_values(value)
            if value == "":
                continue
            label = key.replace("_", " ")
            if key == "kappa":
                label += " (agreement statistic)"
            lines.append("- %s: %s" % (label, card_cell(value)))


def card_render_markdown(card):
    """The card as Markdown, in a fixed order, the same text for the same
    card but for the date line."""
    kind = card.get("kind", "campaign")
    owner = card.get(kind) or {}
    software = card.get("software") or {}
    lines = ["# Dataset card: %s" % owner.get("name", ""), "",
             "%s %s, build %s, written %s" % (
                 software.get("name", NAME), software.get("version", VERSION),
                 software.get("build", BUILD), card.get("written", "")), ""]
    lines.append("## What this is")
    lines.append("")
    if kind == "campaign":
        lines.append("Classes drawn by hand in the annotation campaign %s "
                     "(id %s), with the readings that drew them and the "
                     "frames they cover. Operator names are personal data "
                     "and appear as they are in the package."
                     % (owner.get("name", ""), owner.get("id", "")))
    else:
        lines.append("The classes of %s, corrected by hand in RasterLabel "
                     "(correction %s, id %s)." % (
                         owner.get("source", ""), owner.get("name", ""),
                         owner.get("id", "")))
    grid = card.get("grid") or {}
    lines += ["", "## Grid and system", ""]
    lines.append("- coordinate system: %s" % (grid.get("crs_label")
                                             or grid.get("crs") or "none"))
    for key in ("origin", "pixel_crs", "pixel_m", "size_px"):
        if grid.get(key) is not None:
            lines.append("- %s: %s" % (key.replace("_", " "), ", ".join(
                card_cell(v) for v in grid[key])))
    if grid.get("pixel_area_m2") is not None:
        lines.append("- pixel area: %s m2" % card_cell(grid["pixel_area_m2"]))
    if grid.get("reference_raster"):
        there = grid.get("reference_present")
        lines.append("- reference raster: %s%s" % (
            grid["reference_raster"], "" if there else
            " (not found: the size of the grid is unknown, and the windows "
            "are not clipped to it)" if there is False else ""))
    for key, word in (("qgis", "QGIS"), ("gdal", "GDAL"),
                      ("python", "Python")):
        if software.get(key):
            lines.append("- %s %s" % (word, software[key]))
    lines += ["", "## Classes and pixels", ""]
    if kind == "campaign":
        _card_campaign_classes(card, lines)
    else:
        _card_correction_pixels(card, lines)
    if kind == "campaign":
        lines += ["", "## Readings", ""]
        readings = card.get("readings") or []
        if readings:
            lines.extend(card_table(
                ["operator", "pass", "polygons", "lines", "points", "boxes",
                 "frames complete", "frames touched"],
                [[r.get("operator"), r.get("pass")]
                 + [(r.get("marks") or {}).get(t, 0)
                    for t in ("polygons", "lines", "points", "boxes")]
                 + [r.get("frames_complete", 0), r.get("frames_touched", 0)]
                 for r in readings]))
            if card.get("operators"):
                lines.append("")
                lines.append("Operators: %s. Passes: %s." % (
                    ", ".join(card["operators"]),
                    ", ".join(str(p) for p in card.get("passes") or [])))
        else:
            lines.append("No reading yet.")
        frames = card.get("frames") or {}
        lines += ["", "## Frames", ""]
        n = frames.get("count", 0)
        lines.append("%d frame%s; %d closed as stored, %d as recomputed now."
                     % (n, "" if n == 1 else "s",
                        frames.get("closed_stored", 0),
                        frames.get("closed_recomputed", 0)))
        for m in frames.get("mismatches") or []:
            lines.append("- %s: stored %s, fullest reading %s at %s: press "
                         "Save" % (m.get("tile_id"), m.get("stored"),
                                   m.get("fullest_reading"),
                                   card_percent(m.get("fullest_share"))))
        if frames.get("extra_fields"):
            lines.append("- the frames also carry: %s (listed as found, not "
                         "interpreted)" % ", ".join(frames["extra_fields"]))
    else:
        _card_operations(card, lines)
        bands = owner.get("bands") or []
        if bands:
            lines += ["", "## Bands of the map", ""]
            lines.extend(card_table(
                ["band", "description", "type", "nodata"],
                [[b.get("band"), b.get("description") or "", b.get("type"),
                  b.get("nodata")] for b in bands]))
    lines += ["", "## Rules", ""]
    for key, value in sorted((card.get("rules") or {}).items()):
        if value is None or value == "":
            continue
        lines.append("- %s: %s" % (key.replace("_", " "), card_cell(value)))
    _card_feed_lines(card, lines)
    files = _card_owned_files(kind, owner) + list(card.get("exports") or [])
    if files:
        lines += ["", "## Files", ""]
        lines.extend(card_table(
            ["file", "role", "SHA-256", "verified"],
            [[e.get("path"), e.get("role"), e.get("sha256") or "",
              "" if e.get("verified") is None else
              "yes" if e.get("verified") else
              "no%s" % (": " + e["verified_reason"]
                        if e.get("verified_reason") else "")]
             for e in files]))
    lines += ["", "## What this card does not say", ""]
    for sentence in card.get("limits") or card_limits(kind):
        lines.append("- %s" % sentence)
    return "\n".join(lines) + "\n"


def _card_owned_files(kind, owner):
    """The files the card is made from, as rows of its Files table."""
    if kind == "campaign":
        keys = (("package", "package"),)
    else:
        keys = (("working_copy", "working copy"), ("changes", "changes"))
    out = []
    for key, role in keys:
        if owner.get(key) and owner.get(key + "_sha256"):
            out.append({"path": owner[key], "role": role,
                        "sha256": owner[key + "_sha256"], "verified": None})
    return out


def _card_correction_pixels(card, lines):
    pixels = card.get("pixels") or {}
    names = card_class_names(card.get("classes"))
    before = {int(k): v for k, v in (pixels.get("before") or {}).items()}
    after = {int(k): v for k, v in (pixels.get("after") or {}).items()}
    codes = sorted(set(before) | set(after) | set(names))
    rows = []
    for c in codes:
        b = before.get(c) if pixels.get("before") is not None else None
        a = after.get(c, 0)
        rows.append([c, names.get(c, "code %d" % c),
                     "" if b is None else b, a,
                     "" if b is None else "%+d" % (a - b)])
    lines.extend(card_table(["code", "class", "before", "after", "change"],
                            rows))
    if pixels.get("before") is None and pixels.get("before_reason"):
        lines.append("")
        lines.append("Before: not counted, %s." % pixels["before_reason"])
    if pixels.get("changed_px") is not None:
        lines.append("")
        lines.append("%d px changed by hand, %s of the map." % (
            pixels["changed_px"], card_percent(pixels.get("changed_share"))))
    for p in pixels.get("changed_pairs_px") or []:
        lines.append("- %s -> %s: %d px" % (
            names.get(int(p["from"]), "code %s" % p["from"]),
            names.get(int(p["to"]), "code %s" % p["to"]), int(p["px"])))


def _card_operations(card, lines):
    ops = card.get("operations") or {}
    lines += ["", "## Operations", ""]
    lines.append("%d operations; %s." % (ops.get("count", 0), ", ".join(
        "%s %d" % (k, v) for k, v in sorted(
            (ops.get("by_operator") or {}).items())) or "nobody named"))
    for key in ("first", "last", "changed_m2_logged", "changed_m2_measured",
                "swept_m2", "swept_over_changed"):
        if ops.get(key) is not None:
            lines.append("- %s: %s" % (key.replace("_", " "),
                                       card_cell(ops[key])))


def card_names(stem):
    """(markdown name, json name) of a card for this stem."""
    return stem + CARD_SUFFIX + ".md", stem + CARD_SUFFIX + ".json"


def card_write(card, folder, stem):
    """Write the card as <stem>_card.md and <stem>_card.json, atomically.

    Returns the two paths. The JSON carries card_format, which is the
    version of this layout and not of the program."""
    card = dict(card)
    card.setdefault("card_format", CARD_FORMAT)
    md_name, json_name = card_names(stem)
    md = report_text(os.path.join(folder, md_name),
                     card_render_markdown(card))
    js = report_json(os.path.join(folder, json_name), card)
    return [md, js]


#  Counting: the grid
# =====================================================================
class _CardRect(object):
    """A rectangle as geometry.snap asks for one, (xmin, ymin, xmax, ymax),
    without QGIS."""

    def __init__(self, xmin, ymin, xmax, ymax):
        self.box = (float(xmin), float(ymin), float(xmax), float(ymax))

    def xMinimum(self):
        return self.box[0]

    def yMinimum(self):
        return self.box[1]

    def xMaximum(self):
        return self.box[2]

    def yMaximum(self):
        return self.box[3]


def card_srs(text):
    """A coordinate system out of what a manifest or a file says (EPSG:32633,
    a WKT), in longitude-latitude axis order, or None when it says none."""
    if not text:
        return None
    srs = osr.SpatialReference()
    try:
        if srs.SetFromUserInput(str(text)) != 0:
            return None
    except Exception:
        return None
    try:
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    except Exception:
        pass
    return srs


def card_crs_label(srs):
    """The name of a system and its code: WGS 84 / UTM zone 33N (EPSG:32633)."""
    if srs is None:
        return ""
    name = srs.GetName() or ""
    auth = srs.GetAuthorityName(None)
    code = srs.GetAuthorityCode(None)
    if auth and code:
        return "%s (%s:%s)" % (name, auth, code) if name else \
            "%s:%s" % (auth, code)
    return name


def card_epsg(srs):
    """The EPSG code of a system, or None when it has none."""
    if srs is None:
        return None
    try:
        held = srs.Clone()
        if not held.GetAuthorityCode(None):
            held.AutoIdentifyEPSG()
        if (held.GetAuthorityName(None) or "").upper() == "EPSG":
            code = held.GetAuthorityCode(None)
            return int(code) if code and code.isdigit() else None
    except Exception:
        return None
    return None


def _card_row_m2(ds, grid, area):
    """The ground of one pixel in every row of the copy (ground_rows), or
    None where one value serves or the map's system cannot be read. The
    system is the copy's own, else the one the manifest names."""
    try:
        return ground_rows_of(ds.GetProjection() or grid.get("crs") or "",
                              ds.GetGeoTransform(), ds.RasterXSize,
                              ds.RasterYSize, area)
    except Exception as err:
        log("the card cannot measure the pixel row by row, so one value is "
            "used for the whole map: %s" % err)
        return None


def _card_campaign_rows(grid, gt, size, wkt):
    """The ground of one pixel in every row of the campaign's grid
    (ground_rows), or None where one value serves: a metric system of its
    own, a grid whose size or system is not known, or a turned grid, whose
    rows are not parallels."""
    if size is None or is_rotated(gt):
        return None
    try:
        return ground_rows_of(wkt or grid.get("crs") or "", gt, size[0],
                              size[1], grid.get("pixel_area_m2"))
    except Exception as err:
        log("the card cannot measure the pixel row by row, so one value is "
            "used for the whole map: %s" % err)
        return None


def _card_open(path):
    """A raster opened read only, or None."""
    if not path or not os.path.isfile(long_path(path)):
        return None
    try:
        return gdal.OpenEx(path, gdal.OF_RASTER | gdal.OF_READONLY)
    except Exception:
        return None


def card_campaign_grid(data, folder, notes=None):
    """(grid block, gt, size or None, wkt) of a campaign.

    The grid is the manifest's: gt = (origin x, pixel x, 0, origin y, 0,
    -pixel y). The reference raster is opened read only for its size; when
    it is there and on that grid its own geotransform is used, which is the
    one the Whole raster writes on. When it is missing, or on another grid,
    the size is unknown and no window is clipped to it, and the card says
    so."""
    notes = notes if notes is not None else []
    g = data.get("grid") or {}
    origin = [float(v) for v in (g.get("origin") or [0.0, 0.0])]
    pc = [abs(float(v)) for v in (g.get("pixel_crs") or [1.0, 1.0])]
    pm = [abs(float(v)) for v in (g.get("pixel_m") or pc)]
    gt = (origin[0], pc[0], 0.0, origin[1], 0.0, -pc[1])
    srs = card_srs(g.get("crs"))
    wkt = srs.ExportToWkt() if srs is not None else ""
    # a way from the folder, or from ~, as the manifest keeps it
    ref = str(from_folder(g.get("reference_raster") or "",
                          folder)).split("|")[0]
    size, present, on_grid = None, None, None
    if ref:
        path = ref if os.path.isabs(ref) else os.path.join(folder, ref)
        ds = _card_open(path)
        present = ds is not None
        if ds is not None:
            # top row first, as the manifest says it: a reference stored
            # bottom row first is the same pixels
            held = north_up_of(ds)
            if is_rotated(held):
                gt, size, on_grid = tuple(held), (ds.RasterXSize,
                                                  ds.RasterYSize), True
                notes.append("the reference raster is rotated: the counts "
                             "are on its own turned grid, whole raster")
            elif aligned(gt, held):
                gt, size, on_grid = tuple(held), (ds.RasterXSize,
                                                  ds.RasterYSize), True
            else:
                on_grid = False
                notes.append("the reference raster %s is not on the grid of "
                             "the campaign: its size is not used, and no "
                             "window is clipped to it"
                             % os.path.basename(ref))
            ds = None
        else:
            notes.append("the reference raster %s is not there: the size of "
                         "the grid is unknown, and no window is clipped to "
                         "it" % os.path.basename(ref))
    block = {"crs": str(g.get("crs") or ""), "crs_label": card_crs_label(srs),
             "origin": [gt[0], gt[3]], "pixel_crs": [abs(gt[1]), abs(gt[5])],
             "pixel_m": pm, "pixel_area_m2": pm[0] * pm[1],
             "size_px": list(size) if size else None,
             "reference_raster": os.path.basename(ref) if ref else "",
             "reference_present": present,
             "aligned_with_reference": on_grid}
    if srs is not None and srs.IsGeographic():
        notes.append("the campaign is in degrees: the areas in m2 are "
                     "approximate, the pixel counts exact")
    if srs is None:
        notes.append("the campaign has no coordinate system: areas are in "
                     "the units it declares, the pixel counts exact, and no "
                     "STAC Item is written")
    return block, gt, size, wkt


def _card_strip_gt(gt, col, row):
    """The geotransform of the window whose corner is pixel (col, row) of
    the grid, rotation terms and all."""
    return (gt[0] + col * gt[1] + row * gt[2], gt[1], gt[2],
            gt[3] + col * gt[4] + row * gt[5], gt[4], gt[5])


def _card_window(gt, size, box):
    """The window (c0, r0, w, h) of a box (xmin, ymin, xmax, ymax) on the
    grid, clipped to it when its size is known; the whole raster on a
    rotated grid, where a box is no window."""
    if box is None:
        return (0, 0, 0, 0)
    if is_rotated(gt):
        return (0, 0, size[0], size[1]) if size else (0, 0, 0, 0)
    return snap(gt, size or (0, 0), _CardRect(*box), clip=size is not None)


def _card_union(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]),
            max(a[3], b[3]))


class CardCancelled(Exception):
    """Raised by a progress callback to stop the gathering of a card."""


def _card_tick(progress, text, done, total):
    if progress is None:
        return
    try:
        progress(text, done, total)
    except CardCancelled:
        raise
    except Exception as err:
        log("the progress of the card could not be shown: %s" % err)


def _card_add(counts, values):
    """Pixels per value of an array added into counts."""
    a = np.asarray(values)
    if not a.size:
        return counts
    if a.dtype == np.uint8:
        n = np.bincount(a.ravel(), minlength=256)
        for code in np.nonzero(n)[0].tolist():
            counts[code] = counts.get(code, 0) + int(n[code])
        return counts
    for code, k in class_counts(a).items():
        counts[code] = counts.get(code, 0) + int(k)
    return counts


#  Counting: what the package holds
# =====================================================================
def card_marks_by_reading(package, gt=None, dot_px=1):
    """Every reading of the package, read once, read only:
    {(operator, pass): {"marks": {table: n}, "envelope": box of its polygons,
    "points_envelope": box of its points' squares, "footprint_px": the
    pixels its points stand for, "codes": {code: marks}}}.

    The reading of a mark through operator_word and pass_number, as
    everywhere; a point's footprint is size_px squared, size_px under 1
    taken as the default the Whole raster burns."""
    out = {}
    ds = None
    try:
        ds = ogr.Open(package, 0) if package and os.path.isfile(
            long_path(package)) else None
    except Exception as err:
        log("the card cannot read %s: %s" % (os.path.basename(package), err))
        ds = None
    if ds is None:
        return out
    step = max(abs(gt[1]), abs(gt[5])) if gt else 0.0
    try:
        for table in READING_TABLES:
            lyr = ds.GetLayerByName(table)
            if lyr is None:
                continue
            defn = lyr.GetLayerDefn()
            who = defn.GetFieldIndex("operator")
            when = defn.GetFieldIndex("pass_no")
            code_i = defn.GetFieldIndex("class_code")
            size_i = defn.GetFieldIndex("size_px")
            lyr.ResetReading()
            for f in lyr:
                r = (operator_word(f.GetField(who) if who >= 0 else None),
                     pass_number(f.GetField(when) if when >= 0 else None))
                e = out.setdefault(r, {"marks": {t: 0 for t in
                                                 READING_TABLES},
                                       "envelope": None,
                                       "points_envelope": None,
                                       "footprint_px": 0, "codes": {}})
                e["marks"][table] += 1
                try:
                    code = int(f.GetField(code_i) or 0) if code_i >= 0 else 0
                except (TypeError, ValueError):
                    code = 0
                e["codes"][code] = e["codes"].get(code, 0) + 1
                geom = f.GetGeometryRef()
                if geom is None or geom.IsEmpty():
                    continue
                if table == "polygons":
                    x0, x1, y0, y1 = geom.GetEnvelope()
                    e["envelope"] = _card_union(e["envelope"],
                                                (x0, y0, x1, y1))
                elif table == "points":
                    try:
                        n = int(f.GetField(size_i) or 0) if size_i >= 0 else 0
                    except (TypeError, ValueError):
                        n = 0
                    if n < 1:
                        n = int(dot_px or 1)
                    e["footprint_px"] += n * n
                    x0, x1, y0, y1 = geom.GetEnvelope()
                    pad = (n // 2 + 1) * step
                    e["points_envelope"] = _card_union(
                        e["points_envelope"],
                        (x0 - pad, y0 - pad, x1 + pad, y1 + pad))
            lyr = None
    finally:
        ds = None
    return out


def _card_ground(m2, classes, row_m2, first):
    """Add the ground of the pixels of each class of a strip into m2
    ({code: m2}), row by row: the strip starts at row `first` of the grid
    row_m2 (ground_rows) was measured on."""
    rows = row_m2[first:first + classes.shape[0]]
    for code in np.unique(classes).tolist():
        per_row = (classes == code).sum(axis=1)
        m2[int(code)] = m2.get(int(code), 0.0) + float(np.dot(per_row, rows))


def card_burn(package, choice, gt, window, wkt, points_in_mask=False,
              dot_px=1, tick=None, shares=None, row_m2=None):
    """The pixels one product holds in a window of the grid, burned strip by
    strip exactly as paint_whole burns the mask: the same Stencils, the same
    keep filter, the points on top only when they go into the mask, and for
    a consensus the same vote.

    Returns {"counts": {code: px}, 0 included, "wide": a code past a byte};
    a consensus also "votes" and "labelled" ({k: px}), "no_majority" and
    "all_disagree" (painted by every reading that voted there, with no
    class in the majority), and "partial", "frames_by_readings" when some
    frame was read by fewer of the readings than the vote holds (the vote is
    then of the readings that covered each frame, as in paint_whole).

    shares is reading_shares' answer when the caller has it. row_m2 is the
    ground of one pixel in every row of the grid (geometry.ground_rows), for
    a map in degrees or in Web Mercator: "m2" then holds the ground of each
    class, added up row by row; None where one pixel area serves."""
    mode = choice.get("mode", "all")
    chosen = [tuple(r) for r in choice.get("readings") or []]
    keep = None if mode == "all" else set(chosen)
    c0, r0, w, h = [int(v) for v in window]
    out = {"counts": {}, "wide": False}
    if mode == "consensus":
        out.update(votes={}, labelled={}, no_majority=0, all_disagree=0,
                   partial=False, frames_by_readings={})
    if row_m2 is not None and r0 >= 0 and r0 + h <= len(row_m2):
        out["m2"] = {}
    else:
        row_m2 = None
    if w <= 0 or h <= 0:
        return out
    grid = tuple(gt)
    held = []
    cover = None
    try:
        voters, areas, dots = [], None, None
        if mode == "consensus":
            cover = ConsensusCover(package, wkt, chosen, points_in_mask,
                                   shares)
            out["partial"] = cover.partial
            out["frames_by_readings"] = dict(cover.info["by_readings"])
            for r in chosen:
                own = Stencil(package, "polygons", "class_code", wkt,
                              keep={r})
                own_dots = Stencil(package, "points", "class_code", wkt,
                                   size_field="size_px", grid=grid,
                                   fallback=dot_px, keep={r}) \
                    if points_in_mask else None
                voters.append((own, own_dots))
                held += [own, own_dots]
        else:
            areas = Stencil(package, "polygons", "class_code", wkt, keep=keep)
            dots = Stencil(package, "points", "class_code", wkt,
                           size_field="size_px", grid=grid, fallback=dot_px,
                           keep=keep) if points_in_mask else None
            held += [areas, dots]
        out["wide"] = any(s is not None and s.kind != gdal.GDT_Byte
                          for s in held)
        row = 0
        while row < h:
            take = min(STRIP_ROWS, h - row)
            strip = _card_strip_gt(grid, c0, r0 + row)
            # burned from the pixels of the whole grid, as paint_whole does
            at = {"whole": grid, "col": c0, "row": r0 + row}
            if mode == "consensus":
                labels = []
                for own, own_dots in voters:
                    label = own.burn_into(strip, w, take, wkt, **at)
                    if own_dots is not None:
                        d = own_dots.burn_into(strip, w, take, wkt, **at)
                        label = np.where(d > 0, d, label)
                    labels.append(label)
                member = cover.voting(strip, w, take, wkt, **at)
                classes, votes, labelled = vote(labels, member)
                _card_add(out["counts"], classes)
                _card_add(out["votes"], votes)
                _card_add(out["labelled"], labelled)
                voting = cover.how_many(member, labelled.shape)
                out["no_majority"] += int(((labelled > 0)
                                           & (classes == 0)).sum())
                out["all_disagree"] += int(((labelled == voting)
                                            & (voting > 0)
                                            & (classes == 0)).sum())
            else:
                classes = areas.burn_into(strip, w, take, wkt, **at)
                if dots is not None:
                    d = dots.burn_into(strip, w, take, wkt, **at)
                    classes = np.where(d > 0, d, classes)
                _card_add(out["counts"], classes)
            if row_m2 is not None:
                _card_ground(out["m2"], classes, row_m2, r0 + row)
            row += take
            if tick is not None:
                tick(row, h)
    finally:
        for s in held:
            if s is not None:
                s.close()
        if cover is not None:
            cover.close()
    return out


def _card_sorted(counts, drop_zero=True):
    return {int(k): int(v) for k, v in sorted(counts.items())
            if v and (int(k) != 0 or not drop_zero)}


def _card_product(choice, burned, window, pixel_area):
    """One entry of card["products"]. The ground of a class is the pixel
    area times its pixels, or, where burned holds "m2" (a map in degrees or
    in Web Mercator), the sum of the ground of each pixel, row by row."""
    counts = _card_sorted(burned["counts"])
    labelled = sum(counts.values())
    partial = bool(burned.get("partial"))
    ground = burned.get("m2")
    entry = {"mode": choice.get("mode", "all"),
             "label": choice.get("label", ""),
             "tag": choice.get("tag") or ("all" if choice.get("mode") ==
                                          "all" else ""),
             "readings": [[r[0], int(r[1])] for r in
                          choice.get("readings") or []],
             "rule": reading_rule(choice, partial),
             "window_px": [int(v) for v in window],
             "counts": counts, "labelled_px": labelled,
             "m2": {k: round(ground.get(k, 0.0), 6) for k in counts}
             if ground is not None
             else {k: round(v * pixel_area, 6) for k, v in counts.items()},
             "share": {k: round(v / float(labelled), 6)
                       for k, v in counts.items()} if labelled else {}}
    if entry["mode"] == "consensus":
        entry["votes_histogram"] = _card_sorted(burned["votes"], False)
        entry["labelled_histogram"] = _card_sorted(burned["labelled"], False)
        entry["no_majority_px"] = int(burned["no_majority"])
        entry["all_painted_disagree_px"] = int(burned["all_disagree"])
        if partial:
            # said only when it differs from the plain vote, so a card of a
            # campaign everyone read in full is what it always was
            entry["partial_design"] = True
            entry["frames_by_readings"] = {
                int(k): int(v) for k, v in
                sorted(burned["frames_by_readings"].items())}
    return entry


def card_frames(package, data, gt, size, wkt, readings, progress=None,
                done=0, total=0):
    """The frames block: every frame, its pixels, and what each reading made
    of it. Complete is campaign.reading_shares' rule, the one definition of
    closed (the fullest single reading covers more than CLOSED_SHARE of the
    frame's area); painted_px and the counts per class come from burning the
    reading over the frame's window. Returns (block, {reading: (touched,
    complete)})."""
    block = {"count": 0, "closed_stored": 0, "closed_recomputed": 0,
             "mismatches": [], "extra_fields": [], "per_frame": []}
    per_reading = {r: [0, 0] for r in readings}
    if not data.get("with_tiles", True):
        return block, per_reading
    frames = []
    ds = None
    try:
        ds = ogr.Open(package, 0) if package and os.path.isfile(
            long_path(package)) else None
        tiles = ds.GetLayerByName("tiles") if ds is not None else None
        if tiles is not None:
            defn = tiles.GetLayerDefn()
            idx = defn.GetFieldIndex("tile_id")
            closed_i = defn.GetFieldIndex("closed")
            seen = set()
            tiles.ResetReading()
            for f in tiles:
                tid = f.GetField(idx) if idx >= 0 else None
                if tid is None or str(tid) == "" or str(tid) in seen:
                    continue
                geom = f.GetGeometryRef()
                if geom is None or geom.IsEmpty() or not geom.GetArea() > 0:
                    continue
                seen.add(str(tid))
                x0, x1, y0, y1 = geom.GetEnvelope()
                try:
                    stored = int(f.GetField(closed_i) or 0) \
                        if closed_i >= 0 else 0
                except (TypeError, ValueError):
                    stored = 0
                frames.append((str(tid), (x0, y0, x1, y1), 1 if stored else 0))
            tiles = None
    except Exception as err:
        log("the card cannot read the frames: %s" % err)
    finally:
        ds = None
    frames.sort(key=lambda t: t[0])
    if not frames:
        return block, per_reading
    shares = reading_shares(package)
    stencils = {}
    try:
        for r in readings:
            stencils[r] = Stencil(package, "polygons", "class_code", wkt,
                                  keep={r})
        for i, (tid, box, stored) in enumerate(frames):
            window = _card_window(gt, size, box) if not is_rotated(gt) \
                else (0, 0, 0, 0)
            by = shares.get(tid) or {}
            closed = reading_closed(by) if by else set()
            entry = {"tile_id": tid, "frame_px": int(window[2] * window[3]),
                     "closed_stored": stored, "readings": {}}
            for r in sorted(by, key=lambda r: (r[1], r[0])):
                if r not in per_reading:
                    per_reading[r] = [0, 0]
                per_reading[r][0] += 1
                if r in closed:
                    per_reading[r][1] += 1
                counts = {}
                if r in stencils and window[2] > 0 and window[3] > 0:
                    counts = _card_sorted(_card_add({}, stencils[r].burn_into(
                        _card_strip_gt(gt, window[0], window[1]),
                        window[2], window[3], wkt, whole=tuple(gt),
                        col=window[0], row=window[1])))
                entry["readings"][reading_label(r)] = {
                    "share_area": round(float(by[r]), 6),
                    "painted_px": int(sum(counts.values())),
                    "counts": counts}
            recomputed = 1 if closed else 0
            block["count"] += 1
            block["closed_stored"] += stored
            block["closed_recomputed"] += recomputed
            if stored != recomputed:
                fullest = max(by.items(), key=lambda kv: (kv[1], kv[0])) \
                    if by else (None, 0.0)
                block["mismatches"].append({
                    "tile_id": tid, "stored": stored,
                    "fullest_share": round(float(fullest[1]), 6),
                    "fullest_reading": reading_label(fullest[0])
                    if fullest[0] else ""})
            block["per_frame"].append(entry)
            _card_tick(progress, "frames (%d of %d)" % (i + 1, len(frames)),
                       done + i + 1, total)
    finally:
        for s in stencils.values():
            s.close()
    design = frame_design(package)
    block["extra_fields"] = sorted({k for row in design.values()
                                    for k, v in row.items()
                                    if v is not None and v != ""})
    return block, per_reading


def card_software():
    """The software block: this build, and what it ran on."""
    try:
        rows = dict(environment())
    except Exception as err:
        log("the card cannot list the versions: %s" % err)
        rows = {}
    return {"name": NAME, "version": VERSION, "build": BUILD,
            "shape": SHAPE, "qgis": rows.get("QGIS"), "qt": rows.get("Qt"),
            "gdal": rows.get("GDAL"), "numpy": rows.get("numpy"),
            "python": rows.get("Python"), "system": rows.get("system")}


def _card_classes(classes):
    out = []
    for c in sorted(classes or [], key=lambda c: int(c.get("code", 0))):
        out.append({"code": int(c.get("code", 0)), "name": c.get("name", ""),
                    "colour": c.get("colour", ""),
                    "retired": bool(c.get("retired", False))})
    return out


def _card_same_choice(a, b):
    if not a or not b:
        return False
    ra = sorted(tuple(r) for r in a.get("readings") or [])
    rb = sorted(tuple(r) for r in b.get("readings") or [])
    return a.get("mode", "all") == b.get("mode", "all") and ra == rb


def _card_find_product(products, describe):
    """The product a describe names: a choice, a label or a tag."""
    if describe is None:
        return None
    for p in products:
        if isinstance(describe, dict):
            if _card_same_choice(p, describe):
                return p
        elif describe in (p.get("label"), p.get("tag")):
            return p
    return None


#  Counting: the files written beside the card
# =====================================================================
def _card_counts_in_file(export, ignore_index=None):
    """{code: px} of a mask, 0 and the ignore value left out: the tally
    paint_whole kept as it wrote (export["counts"]), or the file read back."""
    held = export.get("counts")
    counts = {}
    if held is not None:
        if isinstance(held, dict):
            counts = {int(k): int(v) for k, v in held.items()}
        else:
            a = np.asarray(held).ravel()
            counts = {i: int(v) for i, v in enumerate(a.tolist()) if v}
    else:
        ds = _card_open(export.get("path"))
        if ds is None:
            return None
        try:
            counts = band_counts(ds.GetRasterBand(1), None)
        finally:
            ds = None
    drop = {0} | ({int(ignore_index)} if ignore_index is not None else set())
    return {k: v for k, v in sorted(counts.items()) if v and k not in drop}


def _card_grid_of(export):
    """(gt, (w, h)) of an exported raster: given, or read from its header."""
    gt, size = export.get("gt"), export.get("size")
    if gt is not None and size is not None:
        return tuple(gt), tuple(size)
    ds = _card_open(export.get("path"))
    if ds is None:
        return None, None
    try:
        return pixel_grid(ds), (ds.RasterXSize, ds.RasterYSize)
    finally:
        ds = None


def card_exports(exports, where, package, products, gt, wkt,
                 points_in_mask=False, dot_px=1, ignore_index=None):
    """The exports block: each file with its role, its SHA-256 and size, and
    for a mask the counts it holds and whether they are the card's.

    A mask is verified when it is at scale 1 on the campaign grid: its
    counts must be those of its product restricted to its extent. The
    product's own counts when its window lies inside the mask, a burn of the
    product over the mask's extent otherwise. A mask at 1:n, or on another
    grid, is not on the campaign's pixels and is said so."""
    out = []
    for e in exports or []:
        path = e.get("path") or ""
        facts = report_inputs([path])[0]
        try:
            rel = os.path.relpath(path, where).replace("\\", "/") if where \
                else os.path.basename(path)
            # a file outside the folder of the card is named, not located:
            # the way up from it to there runs through the name of whoever
            # made it
            if rel.startswith("../") or os.path.isabs(rel):
                rel = os.path.basename(path)
        except ValueError:
            rel = os.path.basename(path)
        choice = e.get("reading") or {}
        role = e.get("role") or "mask"
        scale = int(e.get("scale") or 1)
        entry = {"role": role, "path": rel, "sha256": facts["sha256"],
                 "bytes": facts["bytes"],
                 "reading_mode": choice.get("mode") or e.get("reading_mode")
                 or "", "reading": choice.get("label") or "",
                 "scale": scale, "verified": None, "verified_reason": ""}
        if role == "mask":
            in_file = _card_counts_in_file(e, ignore_index)
            entry["counts_in_file"] = in_file
            entry["verified"], entry["verified_reason"] = _card_verify(
                e, in_file, package, products, gt, wkt, points_in_mask,
                dot_px, scale)
        out.append(entry)
    return out


def _card_verify(export, in_file, package, products, gt, wkt, points_in_mask,
                 dot_px, scale):
    if in_file is None:
        return False, "the file cannot be read back"
    if scale != 1:
        return False, ("scale 1:%d: its pixels are not the campaign's, so "
                       "its counts are not the card's" % scale)
    choice = export.get("reading") or {"mode": "all"}
    product = None
    for p in products:
        if _card_same_choice(p, choice):
            product = p
            break
    if product is None:
        return False, "its reading is not one the card counted"
    egt, esize = _card_grid_of(export)
    if egt is None or not aligned(tuple(gt), tuple(egt)):
        return False, "it is on another grid than the campaign's"
    col = int(round((egt[0] - gt[0]) / gt[1]))
    row = int(round((egt[3] - gt[3]) / gt[5]))
    c0, r0, w, h = product["window_px"]
    if w <= 0 or h <= 0:
        expected = {}
    elif col <= c0 and row <= r0 and c0 + w <= col + esize[0] \
            and r0 + h <= row + esize[1]:
        expected = {int(k): int(v) for k, v in product["counts"].items()}
    else:
        expected = _card_sorted(card_burn(
            package, choice, gt, (col, row, esize[0], esize[1]), wkt,
            points_in_mask, dot_px)["counts"])
    if expected == in_file:
        return True, ""
    codes = sorted(set(expected) | set(in_file))
    differ = ["%d: %d in the file, %d counted" % (c, in_file.get(c, 0),
                                                 expected.get(c, 0))
              for c in codes if in_file.get(c, 0) != expected.get(c, 0)]
    return False, "the file holds other counts (%s)" % "; ".join(differ[:4])


def _card_count_frames(package):
    """How many frames the package holds, for the progress only."""
    try:
        ds = ogr.Open(package, 0) if package and os.path.isfile(
            long_path(package)) else None
        lyr = ds.GetLayerByName("tiles") if ds is not None else None
        n = int(lyr.GetFeatureCount()) if lyr is not None else 0
        lyr = ds = None
        return max(n, 0)
    except Exception:
        return 0


#  The campaign's card
# =====================================================================
def card_gather_campaign(campaign_data, folder, package=None, progress=None,
                         exports=None, ignore_index=None,
                         points_in_mask=False, describe=None, dot_px=1,
                         where=None):
    """The card of a campaign, as a dict ready for card_write.

    campaign_data is campaign.json as read (nothing is written into it);
    package the GeoPackage, opened read only. The products are the ones the
    Export and Whole raster windows offer (campaign.reading_choices): every
    reading together, each reading alone, each consensus. progress(text,
    done, total) is told how far along it is. exports, from the Whole
    raster or the Export, lists the files written beside the card, as dicts
    {path, role ("mask", "votes", "vectors"...), reading (the choice), scale,
    gt, size, counts (paint_whole's tally, optional)}; where is the folder
    the card goes in, which their paths are given relative to. describe
    names the product the STAC fields describe (a choice, a label or a tag);
    by default the consensus of every reading, the first consensus, the only
    reading, or every reading together."""
    data = campaign_data or {}
    package = package or os.path.join(folder, "annotation.gpkg")
    notes = []
    grid, gt, size, wkt = card_campaign_grid(data, folder, notes)
    facts = report_inputs([package])[0]
    marks = card_marks_by_reading(package, gt, dot_px)
    readings = sorted(marks, key=lambda r: (r[1], r[0]))
    totals = readings_in(package) if os.path.isfile(long_path(package)) \
        else {}
    mine = {r: sum(m["marks"].values()) for r, m in marks.items()}
    if totals != mine:
        notes.append("the marks counted reading by reading (%s) are not "
                     "those readings_in finds (%s)" % (
                         sum(mine.values()), sum(totals.values())))
    choices = reading_choices(totals or mine) if readings else []
    tiled = bool(data.get("with_tiles", True))
    n_frames = _card_count_frames(package) if tiled else 0
    total = len(choices) + n_frames
    pixel_area = grid["pixel_area_m2"]
    # the ground of a pixel in every row, where the map is in degrees or in
    # Web Mercator and the centre pixel is not every row's
    row_m2 = _card_campaign_rows(grid, gt, size, wkt)
    if row_m2 is not None:
        notes[:] = [t for t in notes
                    if not t.startswith("the campaign is in degrees")]
        notes.append("the pixel is not the same ground in every row: the m2 "
                     "of a class add up the ground of each row, measured on "
                     "the ellipsoid and scaled so that the middle row is "
                     "the pixel area of the manifest; the pixel counts are "
                     "exact")
    # measured once, for every consensus that asks who covered which frame
    shares = reading_shares(package) if any(
        c.get("mode") == "consensus" for c in choices) else None

    products, wide = [], False
    for i, choice in enumerate(choices):
        box = None
        for r in choice.get("readings") or []:
            held = marks.get(tuple(r)) or {}
            box = _card_union(box, held.get("envelope"))
            if points_in_mask:
                box = _card_union(box, held.get("points_envelope"))
        window = _card_window(gt, size, box)
        words = "%s (%d of %d)" % (choice.get("label", ""), i + 1, total)

        def tick(row, h, words=words, i=i):
            _card_tick(progress, words, i + float(row) / max(h, 1), total)

        _card_tick(progress, words, i, total)
        burned = card_burn(package, choice, gt, window, wkt, points_in_mask,
                           dot_px, tick, shares, row_m2)
        wide = wide or burned["wide"]
        products.append(_card_product(choice, burned, window, pixel_area))

    frames, per_reading = card_frames(package, data, gt, size, wkt, readings,
                                      progress, len(choices), total)
    reading_rows = []
    for r in readings:
        m = marks[r]
        touched, complete = per_reading.get(r, [0, 0])
        tag = next((c["tag"] for c in choices if c.get("mode") == "one"
                    and [tuple(x) for x in c["readings"]] == [r]),
                   "%s_p%d" % r)
        reading_rows.append({"operator": r[0], "pass": int(r[1]),
                             "label": reading_label(r), "tag": tag,
                             "marks": dict(m["marks"]),
                             "points_footprint_px": int(m["footprint_px"]),
                             "frames_touched": touched,
                             "frames_complete": complete})
    classes = _card_classes(data.get("classes"))
    legend = {c["code"]: c for c in classes}
    used = {}
    for m in marks.values():
        for code, n in m["codes"].items():
            used[code] = used.get(code, 0) + n
    if wide:
        notes.append("a code past %d is held by a mark (a manifest edited by "
                     "hand): it is counted in a type wider than a byte, as "
                     "the mask is written" % MAX_CLASS_CODE)
    if not readings:
        notes.append("nothing drawn yet: no reading holds a mark")
    if any((m["marks"].get("lines") or 0) for m in marks.values()):
        notes.append("lines are counted as marks, never as pixels: no mask "
                     "holds them")
    if not points_in_mask and any(m["footprint_px"] for m in marks.values()):
        notes.append("points are not in these pixel counts, as they are not "
                     "in the mask by default; their footprint is given "
                     "reading by reading")
    if any(p["mode"] == "all" and len(p["readings"]) > 1 for p in products):
        notes.append("every reading together is burned in the order of the "
                     "package: where two readings overlap, the mark stored "
                     "last wins")
    if frames["mismatches"]:
        notes.append("%d frame%s stored as closed or open otherwise than "
                     "the readings now say: press Save in Annotate"
                     % (len(frames["mismatches"]),
                        "" if len(frames["mismatches"]) == 1 else "s"))

    card = {"card_format": CARD_FORMAT, "kind": "campaign",
            "written": now(), "software": card_software(),
            "campaign": {"name": data.get("name", ""),
                         "id": data.get("id", ""),
                         "created": data.get("created", ""),
                         "modified": data.get("modified", ""),
                         "with_tiles": tiled,
                         "folder": os.path.basename(os.path.normpath(folder)),
                         "package": os.path.basename(package),
                         "package_sha256": facts["sha256"],
                         "package_bytes": facts["bytes"],
                         "package_mtime": facts["mtime_utc"]},
            "grid": grid,
            "rules": card_rules(points_in_mask=bool(points_in_mask),
                                ignore_index=ignore_index,
                                all_rule=reading_rule({"mode": "all"})),
            "classes": classes,
            "codes_not_in_legend": sorted(c for c in used
                                          if c and c not in legend),
            "retired_with_marks": sorted(c for c in used if c in legend
                                         and legend[c]["retired"]),
            "readings": reading_rows,
            "operators": sorted({r[0] for r in readings}),
            "passes": sorted({int(r[1]) for r in readings}),
            "frames": frames, "products": products,
            "exports": card_exports(exports, where, package, products, gt,
                                    wkt, points_in_mask, dot_px,
                                    ignore_index),
            "agreement": None, "time": None, "model_vs_corrected": None,
            "uncertainty": None}
    # the STAC fields of the one product they describe
    described = _card_find_product(products, describe)
    card["stac"] = {"describes": described["label"] if described else None}
    described = described or card_described(card) or {
        "label": "nothing drawn yet", "counts": {}, "mode": "",
        "readings": []}
    card["stac"] = {"describes": described.get("label"),
                    "stac_extensions": [LABEL_EXT],
                    "properties": card_stac_label_fields(
                        described, classes, data, ignore_index=ignore_index,
                        reading_rule=described.get("rule") or "")}
    # the reports made of this campaign, copied, never recomputed
    for kind, feed in card_feeds(folder, "campaign", data.get("id", ""),
                                 [facts]).items():
        card[kind] = feed
        notes.extend(card_feed_refused(folder, kind, data.get("id", "")))
    card["limits"] = card_limits("campaign") + notes
    _card_tick(progress, "done", total, total)
    return card


#  The correction's card
# =====================================================================
def card_gather_correction(book_data, folder, progress=None):
    """The card of a correction, as a dict ready for card_write.

    after is the working copy's class band counted with band_counts, nodata
    left out; before, the source map's, when it is there and the size of
    the copy. One strip pass over the record of changes (and the source and
    the copy) gives the pixels a person changed and from what into what. The
    record of changes is the authority; operations.csv is the log, and where
    the two disagree the card says so. Nothing in the correction is
    written."""
    data = book_data or {}
    notes = []
    rel = str(data.get("working_copy") or "").strip()
    copy = copy_in_folder(folder, rel) if rel else \
        str((data.get("files") or [""])[0])
    band_no = int(data.get("band") or 1)
    changes = changes_path_of(data, copy) if copy else ""
    # the manifest on disk holds the map by its way from the folder
    source = str(from_folder(data.get("source") or "", folder)).split("|")[0]
    g = data.get("grid") or {}
    pm = [abs(float(v)) for v in (g.get("pixel_m") or g.get("pixel_crs")
                                  or [1.0, 1.0])]
    area = pm[0] * pm[1]
    cds = _card_open(copy)
    if cds is None:
        raise IOError("the working copy %s cannot be read"
                      % os.path.basename(copy or "?"))
    sds = chg = None
    try:
        w, h = cds.RasterXSize, cds.RasterYSize
        cband = cds.GetRasterBand(band_no)
        # The pixel is not the same ground in every row of a map in degrees
        # or in Web Mercator: the changed ground is added up row by row, as
        # Correct logged it, or the two figures would disagree on such a map
        # with nothing undone. None where one value serves.
        row_m2 = _card_row_m2(cds, g, area)
        nodata = data.get("nodata")
        if nodata is None:
            nodata = cband.GetNoDataValue()
        if nodata is not None and nodata == nodata and \
                float(nodata) == int(nodata):
            nodata = int(nodata)
        bands = []
        for b in range(1, cds.RasterCount + 1):
            held = cds.GetRasterBand(b)
            nd = held.GetNoDataValue()
            bands.append({"band": b, "description": held.GetDescription()
                          or "", "type": gdal.GetDataTypeName(held.DataType),
                          "nodata": nd if nd is None or nd != nd or
                          float(nd) != int(nd) else int(nd)})
        _card_tick(progress, "the corrected map", 0, 3)
        after = {int(k): int(v) for k, v in
                 sorted(band_counts(cband, nodata).items())}
        before, reason, sband = None, "", None
        if not source:
            reason = "the correction names no source map"
        else:
            sds = _card_open(source)
            if sds is None:
                reason = ("the source map %s is not there"
                          % os.path.basename(source))
            elif (sds.RasterXSize, sds.RasterYSize) != (w, h):
                reason = ("the source map is %d x %d pixels and the copy "
                          "%d x %d" % (sds.RasterXSize, sds.RasterYSize, w, h))
            elif band_no > sds.RasterCount:
                reason = "the source map has no band %d" % band_no
            else:
                sband = sds.GetRasterBand(band_no)
                _card_tick(progress, "the map as it came", 1, 3)
                before = {int(k): int(v) for k, v in
                          sorted(band_counts(sband, nodata).items())}
        # which pixels a person changed
        chg_band = None
        if changes and os.path.isfile(long_path(changes)):
            chg = _card_open(changes)
            if chg is not None and (chg.RasterXSize, chg.RasterYSize) == \
                    (w, h):
                chg_band = chg.GetRasterBand(1)
            elif chg is not None:
                notes.append("the record of changes is not the size of the "
                             "copy, and is not read")
        if chg_band is None and chg is None:
            flag = flag_band_of(cds)
            if flag:
                chg_band = cds.GetRasterBand(flag)
        changed, pairs, changed_m2 = None, {}, 0.0
        pairs_m2 = {}
        if chg_band is None:
            notes.append("there is no record of which pixels a person "
                         "changed: the changed pixels are not counted")
        else:
            changed = 0
            for row in range(0, h, STRIP_ROWS):
                take = min(STRIP_ROWS, h - row)
                hit = chg_band.ReadAsArray(0, row, w, take) == 1
                n = int(hit.sum())
                changed += n
                if row_m2 is not None:
                    per_row = hit.sum(axis=1)
                    changed_m2 += float(np.dot(per_row,
                                               row_m2[row:row + take]))
                if n and sband is not None:
                    s = sband.ReadAsArray(0, row, w, take)[hit]
                    a = cband.ReadAsArray(0, row, w, take)[hit]
                    both = np.stack([s.astype(np.int64), a.astype(np.int64)],
                                    axis=1)
                    found, inverse, k = np.unique(
                        both, axis=0, return_inverse=True,
                        return_counts=True)
                    inverse = np.asarray(inverse).reshape(-1)
                    if row_m2 is not None:
                        # the row of each picked pixel, in the order picked
                        ground = np.bincount(
                            inverse, weights=row_m2[row + np.nonzero(hit)[0]],
                            minlength=len(k))
                    for i, ((f, t), m) in enumerate(zip(found.tolist(),
                                                        k.tolist())):
                        pairs[(f, t)] = pairs.get((f, t), 0) + int(m)
                        if row_m2 is not None:
                            pairs_m2[(f, t)] = (pairs_m2.get((f, t), 0.0)
                                                + float(ground[i]))
            _card_tick(progress, "the changed pixels", 2, 3)
    finally:
        sband = cband = chg_band = None
        cds = sds = chg = None
    valid = sum(after.values())
    delta = None
    if before is not None:
        delta = {c: after.get(c, 0) - before.get(c, 0)
                 for c in sorted(set(before) | set(after))}
    pixels = {"before": before, "before_reason": reason, "after": after,
              "delta": delta, "changed_px": changed,
              "changed_share": round(changed / float(valid), 6)
              if changed is not None and valid else None,
              "changed_pairs_px": [
                  {"from": f, "to": t, "px": n,
                   "m2": round(pairs_m2[(f, t)] if row_m2 is not None
                               else n * area, 6)}
                  for (f, t), n in sorted(pairs.items()) if f != t],
              "changed_back_px": sum(n for (f, t), n in pairs.items()
                                     if f == t)}
    if before is None and changed:
        notes.append("from what into what is not counted: %s" % reason)

    # the log of strokes
    ops_path = os.path.join(os.path.dirname(copy), "operations.csv")
    tally = tally_operations(ops_path)
    by_operator, first, last = {}, None, None
    if os.path.isfile(long_path(ops_path)):
        try:
            with io.open(long_path(ops_path), newline="",
                         encoding="utf-8") as fh:
                for row in map(csv_untext_row, csv.DictReader(fh)):
                    who = operator_word(row.get("operator"))
                    by_operator[who] = by_operator.get(who, 0) + 1
                    when = (row.get("when") or "").strip()
                    if when:
                        first = when if first is None else first
                        last = when
        except Exception as err:
            log("the card cannot read %s: %s" % (ops_path, err))
    measured = None
    if changed is not None:
        measured = round(changed_m2 if row_m2 is not None
                         else changed * area, 6)
    logged = tally["changed_m2"]
    if measured is not None and abs(logged - measured) > 1e-6 * max(
            1.0, measured):
        notes.append("the log says %s m2 changed and the record of changes "
                     "%s m2: undone strokes are not subtracted from the log; "
                     "the record of changes is the authority"
                     % (card_cell(float(logged)), card_cell(float(measured))))
    operations = {"count": tally["operations"], "by_operator": by_operator,
                  "first": first, "last": last,
                  "changed_m2_logged": logged,
                  "changed_m2_measured": measured,
                  "swept_m2": tally["swept_m2"],
                  "swept_over_changed": round(tally["swept_m2"] / logged, 4)
                  if logged else None,
                  "pairs_logged": tally["pairs"]}

    srs = card_srs(g.get("crs"))
    copy_facts = report_inputs([copy])[0]
    chg_facts = report_inputs([changes])[0] if changes and os.path.isfile(
        long_path(changes)) else None
    owner = {"name": data.get("name", ""), "id": data.get("id", ""),
             "created": data.get("created", ""),
             "last_opened": data.get("last_opened", ""),
             "operators": list(data.get("operators") or
                               ([data["operator"]] if data.get("operator")
                                else [])),
             "source": os.path.basename(source) if source else "",
             "source_present": bool(source) and os.path.isfile(
                 long_path(source)),
             "band": band_no, "bands": bands,
             "working_copy": os.path.basename(copy),
             "working_copy_sha256": copy_facts["sha256"],
             "changes": os.path.basename(changes) if changes else "",
             "changes_sha256": chg_facts["sha256"] if chg_facts else None}
    for key in ("migrated_from", "resumed"):
        if data.get(key):
            owner[key] = data[key]
    # the folder of the campaign it came from is named, not located
    if isinstance(owner.get("migrated_from"), dict) \
            and owner["migrated_from"].get("campaign"):
        owner["migrated_from"] = dict(
            owner["migrated_from"], campaign=os.path.basename(os.path.normpath(
                str(owner["migrated_from"]["campaign"]))))
    origin = g.get("origin") or [None, None]
    grid = {"crs": str(g.get("crs") or ""), "crs_label": card_crs_label(srs),
            "origin": list(origin),
            "pixel_crs": list(g.get("pixel_crs") or pm), "pixel_m": pm,
            "pixel_area_m2": area, "size_px": [w, h],
            "reference_raster": os.path.basename(copy),
            "reference_present": True, "aligned_with_reference": None}
    classes = _card_classes(data.get("classes"))
    rules = {"pixel_rule": PIXEL_RULE,
             "pixel_rule_text": "a stroke changes the pixels whose centre it "
                                "covers",
             "nodata_value": nodata, "nodata_counted": False,
             "class_codes": "the map's own values, with no ceiling",
             "changed": "the record of changes (1 where a person changed the "
                        "pixel) is the authority; operations.csv is the log",
             "classes_confirmed": data.get("classes_confirmed") or None}
    if srs is not None and srs.IsGeographic():
        notes.append("the map is in degrees: the areas in m2 are "
                     "approximate, the pixel counts exact")
    card = {"card_format": CARD_FORMAT, "kind": "correction",
            "written": now(), "software": card_software(),
            "correction": owner, "grid": grid, "rules": rules,
            "classes": classes, "pixels": pixels, "operations": operations,
            "exports": [], "agreement": None, "time": None,
            "model_vs_corrected": None, "uncertainty": None}
    product = {"label": "the corrected map", "mode": "correction",
               "readings": [], "counts": after}
    card["stac"] = {
        "describes": product["label"], "stac_extensions": [LABEL_EXT],
        "properties": card_stac_label_fields(
            product, classes, data, methods=("automated", "manual"),
            description="Classes of %s, corrected by hand in RasterLabel; "
                        "the overview counts the pixels of band %d of the "
                        "corrected copy, nodata left out." % (
                            os.path.basename(source) or "a map", band_no))}
    current = [copy_facts] + ([chg_facts] if chg_facts else [])
    for kind, feed in card_feeds(folder, "correction", data.get("id", ""),
                                 current).items():
        card[kind] = feed
        notes.extend(card_feed_refused(folder, kind, data.get("id", "")))
    card["limits"] = card_limits("correction") + notes
    _card_tick(progress, "done", 3, 3)
    return card


#  Beside a mask: the STAC Item
# =====================================================================
def card_lonlat(box, wkt):
    """(geometry, bbox) of a box (xmin, ymin, xmax, ymax) in longitude and
    latitude, the only geometry a STAC Item may carry, or (None, None) with
    no system to turn it with."""
    srs = card_srs(wkt)
    if srs is None:
        return None, None
    corners = [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]),
               (box[0], box[3])]
    target = osr.SpatialReference()
    target.ImportFromEPSG(4326)
    try:
        target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    except Exception:
        pass
    if not srs.IsSame(target):
        try:
            turn = osr.CoordinateTransformation(srs, target)
            corners = [tuple(turn.TransformPoint(x, y)[:2])
                       for x, y in corners]
        except Exception as err:
            log("cannot put the mask in degrees: %s" % err)
            return None, None
    ring = [[round(x, 9), round(y, 9)] for x, y in corners]
    ring.append(ring[0])
    # the exterior ring of a GeoJSON polygon runs counter-clockwise, and a
    # transform can turn a ring over
    if sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:])) < 0:
        ring.reverse()
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return ({"type": "Polygon", "coordinates": [ring]},
            [min(xs), min(ys), max(xs), max(ys)])


def card_extent(gt, w, h):
    """(xmin, ymin, xmax, ymax) of a raster of this geotransform and size."""
    xs = [gt[0] + c * gt[1] + r * gt[2] for c, r in ((0, 0), (w, 0), (0, h),
                                                    (w, h))]
    ys = [gt[3] + c * gt[4] + r * gt[5] for c, r in ((0, 0), (w, 0), (0, h),
                                                    (w, h))]
    return (min(xs), min(ys), max(xs), max(ys))


def card_projection(gt, w, h, wkt):
    """The proj:* fields of a raster (projection extension v1.1.0)."""
    srs = card_srs(wkt)
    out = {"proj:shape": [int(h), int(w)],
           "proj:transform": [gt[1], gt[2], gt[0], gt[4], gt[5], gt[3],
                              0.0, 0.0, 1.0],
           "proj:bbox": list(card_extent(gt, w, h)),
           "proj:epsg": card_epsg(srs)}
    if out["proj:epsg"] is None and srs is not None:
        try:
            out["proj:wkt2"] = srs.ExportToWkt(["FORMAT=WKT2_2018"])
        except Exception:
            out["proj:wkt2"] = srs.ExportToWkt()
    return out


def _card_datetime(card):
    """The moment the card was written, as STAC writes one."""
    try:
        when = datetime.fromisoformat(str(card.get("written")))
        return report_utc(when.astimezone(timezone.utc))
    except (TypeError, ValueError):
        return report_utc()


def card_stac_item_for_mask(card, mask_path, gt, w, h, wkt, votes_path=None,
                            card_name=None):
    """The STAC Item of a mask written by Whole raster, or None when the mask
    has no coordinate system (a photo): label and projection extensions, the
    label:* and rasterlabel:* fields of the card, the mask as the labels
    asset and the votes beside it as metadata."""
    geometry, bbox = card_lonlat(card_extent(gt, w, h), wkt)
    if geometry is None:
        return None
    stem = os.path.splitext(os.path.basename(mask_path))[0]
    properties = dict((card.get("stac") or {}).get("properties") or {})
    properties["datetime"] = _card_datetime(card)
    properties.update(card_projection(gt, w, h, wkt))
    assets = {"labels": {"href": "./" + os.path.basename(mask_path),
                         "type": GEOTIFF_TYPE,
                         "roles": ["labels", "labels-raster"],
                         "title": "class codes"}}
    if votes_path:
        assets["votes"] = {"href": "./" + os.path.basename(votes_path),
                           "type": GEOTIFF_TYPE, "roles": ["metadata"],
                           "title": "votes, and readings that painted"}
    links = []
    if card_name:
        links.append({"rel": "describedby",
                      "href": "./" + os.path.basename(card_name),
                      "type": "application/json", "title": "dataset card"})
    return {"type": "Feature", "stac_version": STAC_VERSION,
            "stac_extensions": [LABEL_EXT, PROJ_EXT], "id": stem,
            "geometry": geometry, "bbox": bbox, "properties": properties,
            "links": links, "assets": assets}


def card_write_mask_item(card, mask_path, gt, w, h, wkt, votes_path=None,
                         card_name=None):
    """Write the STAC Item of a mask beside it, <mask stem>.stac.json, and
    return its path; None when the mask has no coordinate system."""
    item = card_stac_item_for_mask(card, mask_path, gt, w, h, wkt,
                                   votes_path, card_name)
    if item is None:
        return None
    path = os.path.splitext(mask_path)[0] + ".stac.json"
    return report_json(path, item)


#  What the information box says
# =====================================================================
def card_stale_lines(card):
    """One sentence per fed report older than the last change."""
    owner = "campaign" if card.get("kind") == "campaign" else "correction"
    out = []
    for kind in ("agreement", "time", "model_vs_corrected", "uncertainty"):
        feed = card.get(kind)
        if feed and feed.get("stale"):
            out.append("The %s report is older than the last change to the "
                       "%s: its numbers are marked as such."
                       % (CARD_FEED_TITLES[kind].lower(), owner))
    return out


def card_summary(card):
    """The sentence after "Dataset card written in ...": what it holds."""
    if card.get("kind") == "campaign":
        products = card.get("products") or []
        n_read = len(card.get("readings") or [])
        n_cons = len([p for p in products if p.get("mode") == "consensus"])
        frames = card.get("frames") or {}
        bits = ["%d reading%s" % (n_read, "" if n_read == 1 else "s")]
        if n_cons:
            bits.append("%d consensus" % n_cons)
        if card.get("campaign", {}).get("with_tiles", True):
            bits.append("%d frame%s (%d closed)" % (
                frames.get("count", 0), "" if frames.get("count", 0) == 1
                else "s", frames.get("closed_recomputed", 0)))
        return ("%s. Pixel counts on the campaign grid, by pixel centre."
                % ", ".join(bits))
    pixels = card.get("pixels") or {}
    ops = card.get("operations") or {}
    bits = []
    if pixels.get("changed_px") is not None:
        bits.append("%d px changed by hand (%s of the map)" % (
            pixels["changed_px"], card_percent(pixels.get("changed_share"))
            or "0.0%"))
    bits.append("%d operation%s" % (ops.get("count", 0),
                                    "" if ops.get("count", 0) == 1 else "s"))
    return "%s. Pixel counts on the map's own grid, nodata left out." \
        % ", ".join(bits)
