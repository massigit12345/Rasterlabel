"""rasterlabel.design

The sampling design a frame was drawn under, carried as it was given.

A sample drawn in R (spsurvey, sampling, sf) or in AcATaMa arrives as a file
of units with a few columns that matter: which draw it was, from which
stratum, with what inclusion probability and weight, under which design.
Imported as frames, those columns come along into the tiles table, and
every unit of the file gets a row in design_log.csv saying what became of
it. Nothing is estimated here and nothing is derived: a weight is not
worked out from a probability, a probability is not normalised, and a value
that does not read as one is left empty with a flag, its raw text kept in
the log. The analyst does the estimation, with every draw accounted for.

This module is the part that needs no QGIS: which source column is which,
how a value is read, where a frame lands on the pixel grid, what becomes of
every unit of the file (design_plan), the rows of the log, the words the
window and Check say. Standard library only, plus the program's constants
and naming. What it needs of the rest of the program (Check's Finding, the
operator as the readings spell it, the frames of a package) it borrows when
it is wanted, the way the journal does, so it stays importable alone.

The order of a file is its order of fid, and an earlier draw wins: a unit
whose frame would lie over a frame accepted before it is refused, and the
log says which. Which draw wins is therefore the file's to say, and a user
who wants another order sorts the file first; the manifest says so too.
"""
import csv
import importlib
import io
import math
import os
import uuid

from .constants import (DESIGN_ALIASES, DESIGN_FIELDS, DESIGN_LOG,
                        DESIGN_LOG_COLUMNS, DESIGN_TEXT_W)
from .naming import csv_text, csv_untext_row, long_path, now


def design_guess_mapping(names):
    """{design field: source column or None}, guessed from the column names.

    The match is exact and ignores case; for each field the first alias that
    is a column wins. fid is never taken: it is the file's row number, not a
    draw."""
    by_lower = {}
    for n in names:
        if str(n).lower() == "fid":
            continue
        by_lower.setdefault(str(n).lower(), n)
    out = {}
    for field in DESIGN_FIELDS:
        out[field] = None
        for alias in DESIGN_ALIASES[field]:
            if alias in by_lower:
                out[field] = by_lower[alias]
                break
    return out


def design_parse_number(raw):
    """(value, ok) of a value meant as a number, or (None, True) for empty.

    A number is taken as it is. Text is taken with a dot for the decimals, or
    with a single comma and no dot ("0,05", as a European spreadsheet writes
    it). Text with both, "1,000.5", is refused: whether the comma separates
    thousands or decimals cannot be told, and guessing would change the
    number."""
    if raw is None:
        return None, True
    if isinstance(raw, bool):
        return None, False
    if isinstance(raw, (int, float)):
        f = float(raw)
        return (f, True) if math.isfinite(f) else (None, False)
    text = str(raw).strip()
    if not text:
        return None, True
    if "," in text:
        if "." in text or text.count(",") != 1:
            return None, False
        text = text.replace(",", ".")
    try:
        f = float(text)
    except ValueError:
        return None, False
    return (f, True) if math.isfinite(f) else (None, False)


def design_parse_prob(raw):
    """(inclusion probability or None, flag or None). 0 < p <= 1 is kept;
    anything else is left empty and flagged bad_value:incl_prob."""
    value, ok = design_parse_number(raw)
    if value is None and ok:
        return None, None
    if not ok or not (0.0 < value <= 1.0):
        return None, "bad_value:incl_prob"
    return value, None


def design_parse_weight(raw):
    """(weight or None, flag or None). A weight above 0 is kept; anything
    else is left empty and flagged bad_value:weight."""
    value, ok = design_parse_number(raw)
    if value is None and ok:
        return None, None
    if not ok or not value > 0.0:
        return None, "bad_value:weight"
    return value, None


def design_str(raw):
    """A value of the design as text, as it was typed: a number a REAL column
    holds whole (R and pandas write every id as a double) is 12, not 12.0,
    which would not match the design it is joined to. A true decimal
    keeps its digits."""
    if isinstance(raw, float) and math.isfinite(raw) and raw == int(raw):
        return str(int(raw))
    return str(raw)


def design_text(raw, field, width=DESIGN_TEXT_W):
    """(text for a column, flag or None). Trimmed; cut to the width of the
    column, and then flagged truncated:<field>, never cut in silence."""
    if raw is None:
        return None, None
    text = design_str(raw).strip()
    if not text:
        return None, None
    if len(text) > width:
        return text[:width], "truncated:%s" % field
    return text, None


def design_values(attrs, mapping, stratum_value=None, design_typed=None):
    """The design of one unit, read from its attributes.

    mapping is {field: column or None}. The stratum may come from a raster
    instead (stratum_value, read at the frame centre by the caller), and the
    design may be typed by the user (design_typed) rather than read from a
    column. Returned: (values {field: value or None}, raw {field: text as
    given}, flags [..], design_full) where design_full is the design text
    uncut, for the manifest."""
    raw = {}
    for field in DESIGN_FIELDS:
        column = mapping.get(field)
        raw[field] = attrs.get(column) if column else None
    if stratum_value is not None:
        raw["stratum"] = stratum_value
    if design_typed is not None:
        raw["design"] = design_typed
    flags = []
    values = {}
    for field in ("sample_id", "stratum", "design"):
        values[field], flag = design_text(raw[field], field)
        if flag and field != "design":
            flags.append(flag)
    values["incl_prob"], flag = design_parse_prob(raw["incl_prob"])
    if flag:
        flags.append(flag)
    values["weight"], flag = design_parse_weight(raw["weight"])
    if flag:
        flags.append(flag)
    full = None if raw["design"] is None \
        else design_str(raw["design"]).strip()
    # the numbers keep the digits the file gave; the three that are text for
    # a column are written as design_text writes them
    texts = ("sample_id", "stratum", "design")
    shown = {f: ("" if raw[f] is None else
                 design_str(raw[f]) if f in texts else str(raw[f]))
             for f in raw}
    return values, shown, flags, full


def design_has_design(values):
    """True when any design field carries a value."""
    return any(values.get(f) not in (None, "") for f in DESIGN_FIELDS)


def design_grid_square(cx, cy, side_px, origin, pixel):
    """The frame of side_px pixels around a centre, on the pixel grid.

    (xmin, ymin, xmax, ymax, col, row). The corner is rounded half up from
    the edges, col = floor((cx - ox)/px - side/2 + 1/2), and every edge is
    the origin plus a whole number of pixels. Half up, not Python's round,
    which rounds half to even: with an odd side a square already on the grid
    which rounds half to even: with an odd side a square already on the grid
    has its centre on a half pixel, and half to even would move half of those
    one pixel off."""
    ox, oy = float(origin[0]), float(origin[1])
    px, py = abs(float(pixel[0])), abs(float(pixel[1]))
    side = int(side_px)
    col = int(math.floor((cx - ox) / px - side / 2.0 + 0.5))
    row = int(math.floor((oy - cy) / py - side / 2.0 + 0.5))
    return (ox + col * px, oy - (row + side) * py, ox + (col + side) * px,
            oy - row * py, col, row)


def design_settings_side(side_m, pixel_m):
    """The side in pixels of a frame of side_m metres: the Settings side."""
    return max(1, int(round(float(side_m) / float(pixel_m))))


def design_own_side(width_px, height_px):
    """(side, resized) for a frame taking a polygon's own size.

    Square within a pixel: the mean of the two sides, not resized. Otherwise
    the longer side, and the frame is flagged resized, because it is not the
    shape the design drew."""
    if abs(width_px - height_px) <= 1.0:
        return max(1, int(round((width_px + height_px) / 2.0))), False
    return max(1, int(round(max(width_px, height_px)))), True


def design_shift_px(src, frame, pixel):
    """How far the frame's edges are from the source's, in pixels: the
    largest of the four."""
    px, py = abs(float(pixel[0])), abs(float(pixel[1]))
    return max(abs(src[0] - frame[0]) / px, abs(src[1] - frame[1]) / py,
               abs(src[2] - frame[2]) / px, abs(src[3] - frame[3]) / py)


def design_summary(decisions):
    """How many units came to each end: {added, completed, already_there,
    duplicate, overlap, outside_raster, no_geometry, transform_failed,
    no_grid, not_written}. A refusal counts under its reason."""
    out = dict.fromkeys(("added", "completed", "already_there", "duplicate",
                         "overlap", "outside_raster", "no_geometry",
                         "transform_failed", "no_grid", "not_written"), 0)
    for d in decisions:
        outcome = d.get("outcome")
        if outcome == "refused":
            for bit in str(d.get("reason") or "").split(";"):
                if bit in out:
                    out[bit] += 1
                    break
        elif outcome in out:
            out[outcome] += 1
    return out


def design_coord(value):
    """A coordinate as the log writes it: every digit a double holds."""
    if value is None or value == "":
        return ""
    return "%.17g" % float(value)


def design_log_row(**fields):
    """One row of design_log.csv, as a list in DESIGN_LOG_COLUMNS order.

    src and frame may be given as 4-tuples (xmin, ymin, xmax, ymax) instead
    of their eight columns; a reason given as a list is joined with ";"."""
    row = dict.fromkeys(DESIGN_LOG_COLUMNS, "")
    src = fields.pop("src", None)
    frame = fields.pop("frame", None)
    for prefix, box in (("src", src), ("frame", frame)):
        if box is not None:
            for name, v in zip(("xmin", "ymin", "xmax", "ymax"), box):
                row["%s_%s" % (prefix, name)] = v
    for key, value in fields.items():
        if key not in row:
            raise KeyError("design_log.csv has no column %s" % key)
        row[key] = value
    if isinstance(row["reason"], (list, tuple)):
        row["reason"] = ";".join(str(r) for r in row["reason"] if r)
    coords = set("%s_%s" % (p, n) for p in ("src", "frame")
                 for n in ("xmin", "ymin", "xmax", "ymax"))
    out = []
    for column in DESIGN_LOG_COLUMNS:
        v = row[column]
        if column in coords:
            out.append(design_coord(v))
        elif v is None:
            out.append("")
        elif isinstance(v, float):
            out.append("%.12g" % v)
        else:
            out.append(str(v))
    return out


def design_append_log(path, rows, complain=None):
    """Append rows to design_log.csv, with the header when the file is new.

    UTF-8, comma separated, "\\n" line ends. Append only: an import, a move
    and a delete each add rows and nothing is ever rewritten. True when
    written; on an error, complain(text) is told and False comes back."""
    try:
        fresh = not os.path.exists(long_path(path)) \
            or os.path.getsize(long_path(path)) == 0
        with io.open(long_path(path), "a", encoding="utf-8", newline="") as fh:
            out = csv.writer(fh, lineterminator="\n")
            if fresh:
                out.writerow(DESIGN_LOG_COLUMNS)
            for r in rows:
                out.writerow([csv_text(c) for c in r])
    except OSError as err:
        if complain is not None:
            complain("design_log.csv could not be written: %s" % err)
        return False
    return True


#  What becomes of every unit of a file
# =====================================================================
# How much ground two frames may share and still count as only touching, in
# square pixels: the thousandth of a pixel Annotate allows when a frame is
# placed or moved (FRAME_OVERLAP_PX2), so that an import refuses exactly
# what a click would.
DESIGN_OVERLAP_PX2 = 1e-3
# Written into the manifest with every import: which draw wins.
DESIGN_ORDER = "source fid ascending; an earlier draw wins an overlap"
# The reasons a unit is refused, in the words of the log.
DESIGN_REFUSALS = ("duplicate", "overlap", "outside_raster", "no_geometry",
                   "transform_failed", "no_grid")
# Above this many units the window waits for the hand to stop before it
# plans again.
DESIGN_MANY = 5000


def design_borrow(module, name):
    """A function of another module, found when it is wanted: in the single
    file every module shares one namespace, in the package it is an
    attribute of the module named. None when it is not there."""
    found = globals().get(name)
    if callable(found):
        return found
    package = globals().get("__package__") or ""
    if not package:
        return None
    try:
        mod = importlib.import_module("." + module, package)
    except Exception:
        return None
    found = getattr(mod, name, None)
    return found if callable(found) else None


def design_say(text, loud=False):
    """A line in the program's log, when there is one to write it in."""
    say = design_borrow("errors", "log")
    if say is not None:
        try:
            say(text, loud=loud)
        except TypeError:
            say(text)


def design_fingerprint(box):
    """A frame told by its four edges, to the micrometre: the test Import
    frames has used since it stopped comparing the left edge alone, which
    on a regular grid took a whole column for one frame."""
    return tuple(round(float(v), 6) for v in box[:4])


def design_shared_area(a, b):
    """The ground two boxes (xmin, ymin, xmax, ymax) share."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def design_next_tile(ids):
    """The number of the next frame: one past the highest there has ever
    been, the rule Annotate names a frame by (free_tile_id)."""
    top = 0
    for name in ids:
        digits = "".join(c for c in str(name or "") if c.isdigit())
        if digits:
            try:
                top = max(top, int(digits))
            except ValueError:
                pass
    return top + 1


class DesignBoxes(object):
    """Boxes kept in buckets of the ground, so that asking which of them a
    new box overlaps looks at its neighbours and not at all of them. An
    import of five thousand units asked five thousand times of everything
    accepted before it otherwise."""

    def __init__(self):
        self.cell = None
        self.buckets = {}
        self.big = []

    def _keys(self, box):
        c = self.cell
        i0, i1 = int(math.floor(box[0] / c)), int(math.floor(box[2] / c))
        j0, j1 = int(math.floor(box[1] / c)), int(math.floor(box[3] / c))
        if (i1 - i0 + 1) * (j1 - j0 + 1) > 4096:
            return None
        return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]

    def add(self, tile_id, box):
        if box is None:
            return
        if self.cell is None:
            self.cell = max(box[2] - box[0], box[3] - box[1], 1e-9)
        keys = self._keys(box)
        if keys is None:
            self.big.append((tile_id, box))
            return
        for k in keys:
            self.buckets.setdefault(k, []).append((tile_id, box))

    def near(self, box):
        if self.cell is None:
            return []
        keys = self._keys(box)
        if keys is None:
            seen = [e for es in self.buckets.values() for e in es]
        else:
            seen = [e for k in keys for e in self.buckets.get(k, ())]
        return seen + self.big


def design_box_clasher(existing, pixel):
    """clash(box, accepted) -> the names of the frames a box would overlap,
    among the frames there already and the ones accepted so far from the
    file, by the ground they share. Every frame of a campaign is a box on
    its grid, so boxes are enough here; Annotate asks QGIS about the frames
    that are there instead, whatever their shape."""
    px, py = abs(float(pixel[0])), abs(float(pixel[1]))
    tiny = DESIGN_OVERLAP_PX2 * px * py
    index = DesignBoxes()
    for e in existing:
        index.add(str(e.get("tile_id")), e.get("bbox"))
    taken = [0]

    def clash(box, accepted):
        for a in accepted[taken[0]:]:
            index.add(str(a["tile_id"]), a["bbox"])
        taken[0] = len(accepted)
        out = []
        for tid, other in index.near(box):
            if tid not in out and design_shared_area(box, other) > tiny:
                out.append(tid)
        return sorted(out)
    return clash


def design_inside_box(extent):
    """inside(box) -> "in", "partly" or "out" of a raster's extent
    (xmin, ymin, xmax, ymax); always "in" without one."""
    if extent is None:
        return lambda box: "in"
    span = max(abs(extent[2] - extent[0]), abs(extent[3] - extent[1]), 1.0)
    eps = span * 1e-12

    def inside(box):
        if design_shared_area(box, extent) <= 0.0:
            return "out"
        if (box[0] >= extent[0] - eps and box[1] >= extent[1] - eps
                and box[2] <= extent[2] + eps and box[3] <= extent[3] + eps):
            return "in"
        return "partly"
    return inside


def _design_whole(text):
    """Text as a REAL column wrote it, 12.0, read as the whole number it is,
    12: tiles written by earlier builds hold the first, a re-import writes
    the second. Anything else is left as it is."""
    text = str(text).strip()
    head, dot, tail = text.partition(".")
    if dot and tail and not tail.strip("0") and head.lstrip("+-").isdigit():
        return head
    return text


def design_same_value(a, b):
    """Two design values as one: numbers to a millionth of themselves,
    everything else as text (12.0 and 12 are one number even as text)."""
    if a in (None, "") and b in (None, ""):
        return True
    if a in (None, "") or b in (None, ""):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 1e-6 * max(1.0, abs(float(a)))
    return _design_whole(a) == _design_whole(b)


def design_same_unit(a, b):
    """True when two designs are the same draw: the same sample id when
    either has one, otherwise the same values in every field."""
    sa = _design_whole(a.get("sample_id") or "")
    sb = _design_whole(b.get("sample_id") or "")
    if sa or sb:
        return sa == sb
    return all(design_same_value(a.get(f), b.get(f))
               for f in ("stratum", "incl_prob", "weight", "design"))


def _design_order(rows):
    def key(pair):
        i, r = pair
        fid = r.get("fid")
        try:
            return (0, float(fid), i)
        except (TypeError, ValueError):
            return (1, 0.0, i)
    return [r for _, r in sorted(enumerate(rows), key=key)]


def design_plan(rows, existing, clash=None, inside=None, settings_side_px=1,
                own_side=False, origin=(0.0, 0.0), pixel=(1.0, 1.0),
                mapping=None, stratum_of=None, design_typed=None,
                first_tile=None):
    """What becomes of every unit of a file, one decision per row and never
    fewer: added, completed, already there, or refused and why.

    rows: {fid, kind (point, line, polygon or none), bbox in the campaign's
    system or None, transform_ok, attrs {column: value}, parts}. existing:
    the frames there, {tile_id, bbox, design {field: value}}. clash(box,
    accepted) names the frames a box would overlap among those there and
    those accepted so far (design_box_clasher by default); inside(box) says
    "in", "partly" or "out" of the raster (always "in" by default).
    settings_side_px is the side of a frame in Settings, which a point or a
    line always takes; own_side gives a polygon a frame of its own size.
    mapping is {field: column or None}; stratum_of(x, y), when given, reads
    the stratum at the middle of the frame; design_typed is the design
    typed in the window. first_tile is the number the first new frame gets,
    by default one past the highest there.

    The rows are taken in order of fid, and an earlier draw wins. Nothing is
    touched: the same rows give the same decisions, which is what lets the
    window show what will happen before anything does.

    Each decision: fid, kind, outcome, reasons [..] and reason (joined with
    ";", the refusal first), tile_id, other_tile, src and frame boxes,
    src_side_px, frame_side_px, shift_px, col, row, values (what goes into
    the five columns), raw (the text as given) and design_full."""
    px, py = abs(float(pixel[0])), abs(float(pixel[1]))
    mapping = dict(mapping or {})
    if clash is None:
        clash = design_box_clasher(existing, pixel)
    if inside is None:
        inside = design_inside_box(None)
    by_print = {}
    for e in existing:
        if e.get("bbox") is not None:
            by_print.setdefault(design_fingerprint(e["bbox"]), e)
    counter = int(first_tile) if first_tile is not None else \
        design_next_tile([e.get("tile_id") for e in existing])
    ordered = _design_order(rows)
    # The stratum read from a raster takes the place of a column.
    columns = {k: v for k, v in mapping.items()
               if not (k == "stratum" and stratum_of is not None)}

    # The same sample id twice in the file is said on every one of them: a
    # sample drawn with replacement, or a file put together twice.
    seen_ids = {}
    for r in ordered:
        column = mapping.get("sample_id")
        sid, _ = design_text((r.get("attrs") or {}).get(column)
                             if column else None, "sample_id")
        if sid:
            seen_ids[sid] = seen_ids.get(sid, 0) + 1

    mine = {}           # fingerprint -> the frame this file put there
    accepted = []       # {tile_id, bbox} of the frames added so far
    out = []
    for r in ordered:
        kind = r.get("kind") or "none"
        box = r.get("bbox")
        d = {"fid": r.get("fid"), "kind": kind, "outcome": None,
             "tile_id": "", "other_tile": "",
             "src": tuple(box) if box is not None else None, "frame": None,
             "src_side_px": None, "frame_side_px": None, "shift_px": None,
             "col": None, "row": None}
        refusal = None
        flags = []
        if kind == "none" or box is None:
            refusal = "no_geometry"
        elif not r.get("transform_ok", True):
            refusal = "transform_failed"
        elif not (px > 0 and py > 0):
            refusal = "no_grid"
        else:
            cx = (float(box[0]) + float(box[2])) / 2.0
            cy = (float(box[1]) + float(box[3])) / 2.0
            resized = False
            if kind == "polygon":
                wpx = (float(box[2]) - float(box[0])) / px
                hpx = (float(box[3]) - float(box[1])) / py
                square = abs(wpx - hpx) <= 1.0
                src_side = (wpx + hpx) / 2.0 if square else max(wpx, hpx)
                d["src_side_px"] = round(src_side, 6)
                if own_side:
                    side, resized = design_own_side(wpx, hpx)
                else:
                    side = max(1, int(settings_side_px))
                    resized = (not square) or abs(src_side - side) >= 1.0
            else:
                side = max(1, int(settings_side_px))
            frame = design_grid_square(cx, cy, side, origin, pixel)
            d["frame"] = tuple(frame[:4])
            d["col"], d["row"] = frame[4], frame[5]
            d["frame_side_px"] = side
            if kind == "polygon":
                shift = round(design_shift_px(box, frame[:4], pixel), 6)
                d["shift_px"] = shift
                if resized:
                    flags.append("resized")
                elif shift > 1e-3:
                    flags.append("snapped")
            elif kind == "point":
                flags.append("from_point")
            elif kind == "line":
                flags.append("from_line")
            if int(r.get("parts") or 1) > 1:
                flags.append("multipart")
            where = inside(d["frame"])
            if where == "out":
                refusal = "outside_raster"
            elif where == "partly":
                flags.append("partly_outside_raster")

        stratum_value = None
        if stratum_of is not None and refusal is None:
            f = d["frame"]
            try:
                stratum_value = stratum_of((f[0] + f[2]) / 2.0,
                                           (f[1] + f[3]) / 2.0)
            except Exception:
                stratum_value = None
        values, raw, vflags, full = design_values(
            dict(r.get("attrs") or {}), columns,
            stratum_value=stratum_value, design_typed=design_typed)
        flags.extend(vflags)
        if values.get("sample_id") and seen_ids.get(values["sample_id"],
                                                    0) > 1:
            flags.append("duplicate_sample_id")
        d["values"], d["raw"], d["design_full"] = values, raw, full

        if refusal is None:
            fp = design_fingerprint(d["frame"])
            if fp in mine:
                refusal = "duplicate"
                d["other_tile"] = mine[fp]
            elif fp in by_print:
                there = by_print[fp]
                tid = str(there.get("tile_id") or "")
                theirs = there.get("design") or {}
                if not design_has_design(theirs):
                    d["outcome"] = "completed" if design_has_design(values) \
                        else "already_there"
                    d["tile_id"] = d["other_tile"] = tid
                    mine[fp] = tid
                elif design_same_unit(theirs, values):
                    d["outcome"] = "already_there"
                    d["tile_id"] = d["other_tile"] = tid
                    mine[fp] = tid
                else:
                    refusal = "duplicate"
                    d["other_tile"] = tid
        if refusal is None and d["outcome"] is None:
            hit = clash(d["frame"], accepted)
            if hit:
                refusal = "overlap"
                d["other_tile"] = ";".join(hit)
        if refusal is None and d["outcome"] is None:
            tid = "t%03d" % counter
            counter += 1
            d["outcome"] = "added"
            d["tile_id"] = tid
            accepted.append({"tile_id": tid, "bbox": d["frame"]})
            mine[design_fingerprint(d["frame"])] = tid
        if refusal is not None:
            d["outcome"] = "refused"
            flags = [refusal] + flags
        d["reasons"] = flags
        d["reason"] = ";".join(flags)
        out.append(d)
    return out


def design_all_square(rows, pixel):
    """True when every polygon of the rows is square within a pixel, and
    there is at least one: then each can keep its own side."""
    px, py = abs(float(pixel[0])), abs(float(pixel[1]))
    if not (px > 0 and py > 0):
        return False
    seen = False
    for r in rows:
        if r.get("kind") != "polygon" or r.get("bbox") is None:
            continue
        b = r["bbox"]
        if abs((b[2] - b[0]) / px - (b[3] - b[1]) / py) > 1.0:
            return False
        seen = True
    return seen


def design_has_polygons(rows):
    """True when the file has a polygon, which alone can keep its side."""
    return any(r.get("kind") == "polygon" for r in rows)


#  The words
# =====================================================================
def _design_ids(ids, most=4):
    ids = [i for i in ids if i]
    if len(ids) > most:
        return ", ".join(ids[:most]) + ", …"
    return ", ".join(ids)


def design_number_text(value):
    """A number as the panel shows it: six digits at most, no trailing
    zeros."""
    if value is None or value == "":
        return ""
    try:
        return "%.6g" % float(value)
    except (TypeError, ValueError):
        return str(value)


def design_tile_line(values):
    """The quiet line under the list of frames, and its tooltip: "sample
    S017 · stratum 3 · w 20". Empty when the frame has no design."""
    values = values or {}
    bits = []
    if values.get("sample_id") not in (None, ""):
        bits.append("sample %s" % values["sample_id"])
    if values.get("stratum") not in (None, ""):
        bits.append("stratum %s" % values["stratum"])
    if values.get("incl_prob") not in (None, ""):
        bits.append("p %s" % design_number_text(values["incl_prob"]))
    if values.get("weight") not in (None, ""):
        bits.append("w %s" % design_number_text(values["weight"]))
    if not bits and values.get("design") not in (None, ""):
        bits.append("design %s" % values["design"])
    return " · ".join(bits)


DESIGN_REFUSED_WORDS = {
    "duplicate": "a duplicate of",
    "overlap": "overlap with",
    "outside_raster": "outside the raster",
    "no_geometry": "no geometry",
    "transform_failed": "cannot be brought into the campaign's system",
    "no_grid": "the campaign has no pixel grid",
}


def design_import_count(decisions):
    """How many frames an import writes: the added and the completed."""
    return sum(1 for d in decisions if d.get("outcome") in ("added",
                                                            "completed"))


def design_preview(decisions):
    """What the window says will happen, a line each: the added (and how),
    the completed, the ones already there, then each kind of refusal with
    the frames it is about, and the values that could not be read."""
    lines = []
    added = [d for d in decisions if d.get("outcome") == "added"]

    def having(ds, flag):
        return sum(1 for d in ds if flag in (d.get("reasons") or ()))
    how = ["%d moved onto the grid" % having(added, "snapped"),
           "%d resized" % having(added, "resized")]
    for flag, words in (("from_point", "from points"),
                        ("from_line", "from lines"),
                        ("multipart", "from shapes of several parts"),
                        ("partly_outside_raster",
                         "partly outside the raster")):
        n = having(added, flag)
        if n:
            how.append("%d %s" % (n, words))
    lines.append("%d added: %s" % (len(added), ", ".join(how)))
    done = [d for d in decisions if d.get("outcome") == "completed"]
    if done:
        lines.append("%d completed: the design written into frames already "
                     "there (%s)" % (len(done),
                                     _design_ids([d["tile_id"]
                                                  for d in done])))
    there = [d for d in decisions if d.get("outcome") == "already_there"]
    if there:
        lines.append("%d already there (%s)"
                     % (len(there), _design_ids([d["tile_id"]
                                                 for d in there])))
    refused = [d for d in decisions if d.get("outcome") == "refused"]
    for why in DESIGN_REFUSALS:
        ds = [d for d in refused if (d.get("reasons") or [""])[0] == why]
        if not ds:
            continue
        words = DESIGN_REFUSED_WORDS[why]
        if why in ("duplicate", "overlap"):
            others = []
            for d in ds:
                for t in str(d.get("other_tile") or "").split(";"):
                    if t and t not in others:
                        others.append(t)
            lines.append("%d refused: %s %s" % (len(ds), words,
                                                _design_ids(others)))
        else:
            lines.append("%d refused: %s" % (len(ds), words))
    if not refused:
        lines.append("none refused")
    bad = {}
    for d in decisions:
        for r in d.get("reasons") or ():
            if r.startswith("bad_value:") or r.startswith("truncated:"):
                bad[r] = bad.get(r, 0) + 1
    if bad:
        lines.append("values left empty or cut: %s" % ", ".join(
            "%s%s %d" % (k.split(":", 1)[1].replace("_", " "),
                         " cut" if k.startswith("truncated") else "", n)
            for k, n in sorted(bad.items())))
    twice = sum(1 for d in decisions
                if "duplicate_sample_id" in (d.get("reasons") or ()))
    if twice:
        lines.append("%d units share a sample id with another unit of the "
                     "file" % twice)
    return lines


def design_refused_text(counts):
    """"overlap 2, duplicate 1", or "overlap" when it is the one reason."""
    parts = [(r, int(counts.get(r) or 0)) for r in DESIGN_REFUSALS
             if counts.get(r)]
    if len(parts) == 1:
        return parts[0][0].replace("_", " ")
    return ", ".join("%s %d" % (r.replace("_", " "), n) for r, n in parts)


def design_done_text(decisions, source_name):
    """What the box says after an import: the counts, and where every unit
    of the file is written down."""
    counts = design_summary(decisions)
    refused = sum(counts.get(r, 0) for r in DESIGN_REFUSALS)
    bits = ["%d frame%s added" % (counts["added"],
                                  "" if counts["added"] == 1 else "s")]
    if counts["completed"]:
        bits.append("%d completed" % counts["completed"])
    bits.append("%d already there" % counts["already_there"])
    if refused:
        bits.append("%d refused (%s)" % (refused,
                                         design_refused_text(counts)))
    else:
        bits.append("0 refused")
    if counts["not_written"]:
        bits.append("%d not written" % counts["not_written"])
    n = len(decisions)
    return ("%s. %s in the campaign folder lists all %d feature%s of %s, "
            "one row each." % (", ".join(bits), DESIGN_LOG, n,
                               "" if n == 1 else "s", source_name))


#  The log and the manifest
# =====================================================================
def design_log_path(folder):
    """Where a campaign keeps design_log.csv: at its root, beside the
    journal and the manifest."""
    return os.path.join(folder, DESIGN_LOG)


def _design_cell(values, raw, field):
    v = (values or {}).get(field)
    if v not in (None, ""):
        return v
    return (raw or {}).get(field) or ""


def design_log_rows(decisions, import_id, when, operator, source_file, crs):
    """The rows of design_log.csv for one import, one per unit."""
    out = []
    for d in decisions:
        values, raw = d.get("values") or {}, d.get("raw") or {}
        fid = d.get("fid")
        out.append(design_log_row(
            import_id=import_id, when=when, operator=operator,
            event="import", source_file=source_file,
            source_fid="" if fid is None else fid,
            sample_id=_design_cell(values, raw, "sample_id"),
            stratum=_design_cell(values, raw, "stratum"),
            incl_prob_raw=raw.get("incl_prob") or "",
            weight_raw=raw.get("weight") or "",
            design=d.get("design_full") or "",
            outcome=d.get("outcome") or "", reason=d.get("reason") or "",
            tile_id=d.get("tile_id") or "",
            other_tile=d.get("other_tile") or "",
            src=d.get("src"), frame=d.get("frame"),
            src_side_px=d.get("src_side_px"),
            frame_side_px=d.get("frame_side_px"),
            shift_px=d.get("shift_px"), crs=crs or ""))
    return out


def design_not_written(decisions, why):
    """The decisions of an import whose commit failed: every unit is
    not_written, with the reason, so that a failed import is in the log
    too. Nothing was put in the package, so no frame is named."""
    why = "commit failed: %s" % str(why or "unknown").replace(";", ",")
    out = []
    for d in decisions:
        e = dict(d)
        e["outcome"] = "not_written"
        e["reasons"] = [why]
        e["reason"] = why
        e["tile_id"] = ""
        out.append(e)
    return out


def design_import_id():
    """The name of one import, in its log rows and its manifest entry."""
    return uuid.uuid4().hex[:8]


def design_source_name(path):
    """The file a design came from, as the log names it: its name alone.
    The manifest keeps its way from the campaign's folder, from ~ when that
    is far (naming.beside_folder), and a manifest written before keeps the
    whole path."""
    return os.path.basename(str(path or "").split("|")[0])


def design_read_log(path):
    """The rows of design_log.csv as dicts, [] when there is none."""
    try:
        with io.open(long_path(path), encoding="utf-8", newline="") as fh:
            return [csv_untext_row(r) for r in csv.DictReader(fh)]
    except (OSError, csv.Error):
        return []


def design_manifest_entry(import_id, when, operator, source, source_crs,
                          mapping, design_full, own_side, side_px, counts):
    """The entry an import adds to the manifest's "designs" list."""
    return {"id": import_id, "when": when, "operator": operator,
            "source": source, "source_crs": source_crs or "",
            "mapping": dict(mapping), "design": design_full or "",
            "side": "own" if own_side else "settings",
            "side_px": None if own_side else side_px,
            "order": DESIGN_ORDER, "counts": dict(counts),
            "log": DESIGN_LOG}


#  A frame of the design moved or deleted, and Check
# =====================================================================
def design_plain(value):
    """A value of a QGIS feature as Python: NULL as None, text trimmed."""
    if value is None:
        return None
    is_null = getattr(value, "isNull", None)
    if callable(is_null):
        try:
            if is_null():
                return None
        except Exception:
            pass
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def design_feature_values(feature):
    """{field: value} of the design a frame carries; None where it has no
    such column or the column is empty."""
    out = {}
    for field in DESIGN_FIELDS:
        try:
            out[field] = design_plain(feature[field])
        except Exception:
            out[field] = None
    return out


def design_operator(section):
    """The operator in hand, spelled as the readings spell it."""
    name = ""
    ask = getattr(section, "operator_name", None)
    if callable(ask):
        try:
            name = ask()
        except Exception:
            name = ""
    word = design_borrow("campaign", "operator_word")
    if word is not None:
        return word(name)
    return str(name or "").strip().upper()


def design_crs_of(section):
    """The authid of the campaign's system, "" for one without."""
    try:
        return section.geometry.crs.authid() or ""
    except Exception:
        return ""


def design_frame_event(section, kind, tile_id, before, after, feature):
    """A frame of the design moved or deleted, once it is committed: a row
    in design_log.csv, the old frame in src_* and the new one in frame_*
    (empty for a delete). A frame placed by hand, with no design, writes
    nothing, and neither does a new or an imported frame: the import writes
    its own rows. Registered in measure.FRAME_LISTENERS."""
    if kind not in ("move", "delete") or feature is None:
        return None
    values = design_feature_values(feature)
    if not design_has_design(values):
        return None
    folder = getattr(getattr(section, "campaign", None), "folder", None)
    if not folder:
        return None
    px = py = 0.0
    try:
        px, py = section.geometry.pixel_crs
    except Exception:
        pass
    side_before = side_after = shift = None
    if before is not None and px:
        side_before = round((before[2] - before[0]) / px, 6)
    if after is not None and px:
        side_after = round((after[2] - after[0]) / px, 6)
        if before is not None and py:
            shift = round(design_shift_px(before, after, (px, py)), 6)
    row = design_log_row(
        when=now(), operator=design_operator(section), event=kind,
        sample_id=values.get("sample_id") or "",
        stratum=values.get("stratum") or "",
        incl_prob_raw=design_number_text(values.get("incl_prob")),
        weight_raw=design_number_text(values.get("weight")),
        design=values.get("design") or "",
        outcome="moved" if kind == "move" else "deleted",
        tile_id=tile_id or "", src=before,
        frame=after if kind == "move" else None,
        src_side_px=side_before, frame_side_px=side_after, shift_px=shift,
        crs=design_crs_of(section))
    return design_append_log(design_log_path(folder), [row],
                             lambda text: design_say(text, loud=True))


def design_finding(level, what, detail=""):
    """A line of Check, made by Check's own Finding."""
    make = design_borrow("doctor", "Finding")
    if make is None:
        return None
    return make(level, what, detail)


def design_findings(owner):
    """Check, on the sampling design of a campaign: how many frames carry
    one; the draws an import refused, which make the sample annotated not
    the sample drawn; the frames of a design moved or deleted after it was
    imported; and the frames whose weight is not one over their inclusion
    probability, said as a fact. Nothing at all for a campaign that has
    never had a design, so an old campaign reads as it did."""
    data = getattr(owner, "data", None) or {}
    folder = getattr(owner, "folder", None) or ""
    designs = [d for d in (data.get("designs") or []) if isinstance(d, dict)]
    read = design_borrow("campaign", "frame_design")
    package = getattr(owner, "package_path", None)
    frames = {}
    if read is not None and package and os.path.exists(package):
        try:
            frames = read(package) or {}
        except Exception:
            frames = {}
    path = design_log_path(folder) if folder else ""
    there = bool(path) and os.path.isfile(long_path(path))
    if not designs and not frames and not there:
        return []
    out = []
    n = len(frames)
    if designs:
        out.append(design_finding(
            "ok", "%d frame%s carr%s a sample of %d imported design%s"
            % (n, "" if n == 1 else "s", "ies" if n == 1 else "y",
               len(designs), "" if len(designs) == 1 else "s")))
    elif n:
        out.append(design_finding(
            "ok", "%d frame%s carr%s a sampling design" %
            (n, "" if n == 1 else "s", "ies" if n == 1 else "y")))
    for d in designs:
        counts = d.get("counts") or {}
        refused = sum(int(counts.get(r) or 0) for r in DESIGN_REFUSALS)
        if refused:
            source = os.path.basename(str(d.get("source") or "")) or "a file"
            out.append(design_finding(
                "note", "%d draw%s of %s never became frames (%s)"
                % (refused, "" if refused == 1 else "s", source,
                   design_refused_text(counts)),
                "the sample annotated is not the sample drawn: %s lists "
                "them" % DESIGN_LOG))
    if designs and not there:
        out.append(design_finding(
            "note", "the manifest lists %d imported design%s but %s is not "
            "there" % (len(designs), "" if len(designs) == 1 else "s",
                       DESIGN_LOG),
            "moved or deleted by hand: what became of each draw is no "
            "longer written down"))
    rows = design_read_log(path) if there else []
    moved = sorted({r.get("tile_id") or "?" for r in rows
                    if r.get("event") == "move"})
    gone = sorted({r.get("tile_id") or "?" for r in rows
                   if r.get("event") == "delete"})
    if moved or gone:
        bits = []
        if moved:
            bits.append("%d moved" % len(moved))
        if gone:
            bits.append("%d deleted" % len(gone))
        out.append(design_finding(
            "note", "frames of an imported design were %s after the import"
            % " and ".join(bits),
            "%s: the frames annotated are not all where the design drew "
            "them; %s has a row for each" % (_design_ids(moved + gone),
                                            DESIGN_LOG)))
    odd = []
    for tid, v in sorted(frames.items()):
        p, w = v.get("incl_prob"), v.get("weight")
        try:
            if p is not None and w is not None \
                    and abs(float(w) * float(p) - 1.0) > 1e-6:
                odd.append(tid)
        except (TypeError, ValueError):
            pass
    if odd:
        out.append(design_finding(
            "note", "on %d frame%s the weight is not one over the inclusion "
            "probability" % (len(odd), "" if len(odd) == 1 else "s"),
            "%s: kept as given, nothing was changed" % _design_ids(odd)))
    return [f for f in out if f is not None]
