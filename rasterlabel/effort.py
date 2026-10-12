"""rasterlabel.effort

Active time out of a journal: how much of the time a person spent drawing,
and on which frame, reading and class it was spent.

The rule, which every report writes out beside its numbers:

    Active time is the sum of stroke durations minus the pauses inside them
    longer than T, plus the gaps between events no longer than T. A gap
    longer than T, or one while QGIS was not the active application, is
    idle. A gap is given to the next mark (its class and frame); what is
    left when the work stops or the frame changes is overhead of the frame
    in hand.

T is the idle limit, 60 s unless chosen otherwise, and 30, 60 and 120 s are
always computed as well, because the rule is a convention and a conclusion
that holds at all three does not hang on it. A gap of exactly T is active:
the comparison is strict.

Inside one session every gap is measured on the monotonic clock, which
neither daylight saving nor a clock correction can move; sessions are never
joined to each other. Two QGIS windows on the same campaign are two
sessions, and when the same person shows as active in both at once the
overlap is counted once and said.

A correction has no frames of its own: a stroke of Correct goes to the frame
of the campaign its centre falls in, the lowest tile_id winning on a shared
border, and to "(outside frames)" when there is none, which is counted and
said rather than dropped.

Pure Python and the program's statistics; no QGIS, no GDAL. The areas a
report divides by are handed in by the caller, measured the way the panel
measures a frame.
"""
import bisect
import math

from datetime import datetime, timezone

from .constants import (BOOTSTRAP_MIN_FRAMES, BOOTSTRAP_N, BOOTSTRAP_SEED,
                        CLOSED_SHARE, HEARTBEAT_S, IDLE_DEFAULT_S,
                        IDLE_SENSITIVITY, MARK_ACTIONS, PAUSE_MIN_S)
from .stats import st_bootstrap_stat, st_wilcoxon_signed


EFFORT_OUTSIDE = "(outside frames)"
EFFORT_RULE = ("Active time is the sum of stroke durations minus internal "
               "pauses longer than T, plus gaps between events no longer "
               "than T; a gap longer than T, or while QGIS was not the "
               "active application, is idle. Gaps are attributed to the "
               "next mark (class, frame), overhead to the frame in hand.")
EFFORT_NAN = float("nan")


def effort_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def effort_float(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def effort_parse_utc(text):
    """Seconds since 1970 of a journal's t_utc, or None."""
    t = str(text or "").strip()
    if not t:
        return None
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(t)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


def effort_format_utc(seconds):
    if seconds is None:
        return ""
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def effort_sessions(rows):
    """The rows in sessions, each in the order it was written.

    ([(session id, [rows])], warnings). A row whose monotonic time goes
    backwards cannot belong to the same run of the clock: the session is
    closed there and what follows is a session of its own, "<id>#2"."""
    by = {}
    order = []
    for r in rows:
        sid = str(r.get("session") or "")
        if sid not in by:
            by[sid] = []
            order.append(sid)
        by[sid].append(r)
    out, warnings = [], []
    for sid in order:
        events = sorted(by[sid], key=lambda r: effort_int(r.get("seq")))
        piece, part, last = [], 1, None
        for r in events:
            mono = effort_int(r.get("mono_ms"))
            if last is not None and mono < last:
                out.append((sid if part == 1 else "%s#%d" % (sid, part),
                            piece))
                warnings.append("session %s: the clock went back at row %s, "
                                "so it was split there"
                                % (sid, r.get("seq")))
                part += 1
                piece = []
            piece.append(r)
            last = mono
        if piece:
            out.append((sid if part == 1 else "%s#%d" % (sid, part), piece))
    return out, warnings


def _effort_on_segment(px, py, ax, ay, bx, by, eps=1e-9):
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if abs(cross) > eps * max(1.0, abs(bx - ax) + abs(by - ay)):
        return False
    return (min(ax, bx) - eps <= px <= max(ax, bx) + eps
            and min(ay, by) - eps <= py <= max(ay, by) + eps)


def effort_ring(shape):
    """A frame as a ring of (x, y): a bbox (xmin, ymin, xmax, ymax) or a
    ring already."""
    if len(shape) == 4 and all(isinstance(v, (int, float)) for v in shape):
        x0, y0, x1, y1 = [float(v) for v in shape]
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [(float(x), float(y)) for x, y in shape]


def effort_in_ring(x, y, ring):
    """True when the point is inside the ring or on its edge."""
    n = len(ring)
    inside = False
    for i in range(n):
        ax, ay = ring[i]
        bx, by = ring[(i + 1) % n]
        if _effort_on_segment(x, y, ax, ay, bx, by):
            return True
        if (ay > y) != (by > y):
            cx = ax + (y - ay) * (bx - ax) / (by - ay)
            if cx > x:
                inside = not inside
    return inside


def effort_frame_of(x, y, frames):
    """The frame a point falls in: the lowest tile_id among those holding it,
    or EFFORT_OUTSIDE. frames is {tile_id: bbox or ring}."""
    for tile in sorted(frames):
        if effort_in_ring(x, y, effort_ring(frames[tile])):
            return tile
    return EFFORT_OUTSIDE


def effort_frame_finder(frames):
    """A frame_of for effort_attribute, from the frames as above: it places a
    row by its x, y, and gives None to a row that has none."""
    rings = {t: effort_ring(s) for t, s in frames.items()}

    def frame_of(row):
        x, y = effort_float(row.get("x")), effort_float(row.get("y"))
        if x is None or y is None:
            return None
        for tile in sorted(rings):
            if effort_in_ring(x, y, rings[tile]):
                return tile
        return EFFORT_OUTSIDE
    return frame_of


def _effort_cell():
    return {"draw_s": 0.0, "lead_s": 0.0, "marks": 0, "undos": 0,
            "refused": 0}


def _effort_frame():
    return {"draw_s": 0.0, "lead_s": 0.0, "overhead_s": 0.0, "marks": 0,
            "undos": 0, "refused": 0, "sessions": set(), "wall_s": 0.0,
            "first_utc": None, "last_utc": None}


def effort_attribute(rows, idle_s=IDLE_DEFAULT_S, frame_of=None,
                     default_tile=None):
    """Active time out of journal rows, at one idle limit.

    frame_of(row) places a mark that carries no tile_id (a stroke of
    Correct); a row with a tile_id keeps its own. A row that is not a mark
    takes its own tile_id, or the frame of the last mark of its session.
    default_tile is the frame of every row that has none otherwise: "*" for
    a campaign drawn without frames, or a correction measured on its own.

    Returned:
    - cells: {(tile_id, operator, pass_no, class_code): {draw_s, lead_s,
      marks, undos, refused}}. class_code 0 is "(no class)".
    - frames: {(tile_id, operator, pass_no): {draw_s, lead_s, overhead_s,
      active_s, marks, undos, refused, sessions, wall_s, first_utc,
      last_utc}}.
    - outside: how many marks fell outside every frame; unplaced_s: active
      time that could not be given a frame; overlap_s: time counted once
      because the same operator was active in two sessions at once;
      warnings.
    """
    theta = float(idle_s)
    sessions, warnings = effort_sessions(rows)
    cells, frames = {}, {}
    out = {"idle_s": idle_s, "cells": cells, "frames": frames,
           "outside": 0, "unplaced_s": 0.0, "overlap_s": 0.0,
           "warnings": warnings}
    segments = {}

    def frame(key):
        if key not in frames:
            frames[key] = _effort_frame()
        return frames[key]

    def flush(pending, key):
        if pending <= 0:
            return
        if key is None or key[0] is None:
            out["unplaced_s"] += pending
            return
        frame(key)["overhead_s"] += pending

    for sid, events in sessions:
        pending = 0.0
        prev_key = None
        prev_end = None
        prev_action = None
        mark_key = None
        reading = ("", "")
        offset = None
        spans = {}
        for r in events:
            action = str(r.get("action") or "")
            end = effort_int(r.get("mono_ms")) / 1000.0
            dur = max(0, effort_int(r.get("dur_ms"))) / 1000.0
            start = end - dur
            utc_end = effort_parse_utc(r.get("t_utc"))
            if offset is None and utc_end is not None:
                offset = utc_end - end
            op = str(r.get("operator") or "")
            pass_no = str(r.get("pass_no") or "")
            if op or pass_no:
                reading = (op, pass_no)
            tile = str(r.get("tile_id") or "") or None
            is_mark = action in MARK_ACTIONS
            if tile is None and is_mark and frame_of is not None:
                tile = frame_of(r)
            if tile is None and mark_key is not None:
                tile = mark_key[0]
            if tile is None and default_tile is not None:
                tile = default_tile
            key = (tile, reading[0], reading[1]) if tile is not None else None
            if prev_end is not None:
                gap = max(0.0, start - prev_end)
                if gap > theta or prev_action == "focus_out":
                    flush(pending, prev_key)
                    pending = 0.0
                else:
                    pending += gap
            if is_mark:
                draw = dur - sum(p for p in
                                 _effort_pauses(r.get("pauses_s")) if p > theta)
                draw = max(0.0, draw)
                code = effort_int(r.get("class_code"))
                if tile == EFFORT_OUTSIDE:
                    out["outside"] += 1
                if key is None:
                    out["unplaced_s"] += pending + draw
                else:
                    cell = cells.setdefault(key + (code,), _effort_cell())
                    f = frame(key)
                    for target in (cell, f):
                        target["draw_s"] += draw
                        target["lead_s"] += pending
                        if action == "undo":
                            target["undos"] += 1
                        elif action in ("refused", "discard"):
                            target["refused"] += 1
                        else:
                            target["marks"] += 1
                    f["sessions"].add(sid)
                    if offset is not None and op:
                        segments.setdefault(op, []).append(
                            [start - pending + offset, end + offset, sid,
                             key + (code,), pending, draw])
                pending = 0.0
                mark_key = key
            elif action in ("frame", "reading") and mark_key is not None \
                    and key != mark_key:
                flush(pending, mark_key)
                pending = 0.0
            if key is not None:
                lo, hi = spans.get(key, (start, end))
                spans[key] = (min(lo, start), max(hi, end))
                if offset is not None:
                    f = frame(key)
                    a, b = start + offset, end + offset
                    f["first_utc"] = a if f["first_utc"] is None \
                        else min(f["first_utc"], a)
                    f["last_utc"] = b if f["last_utc"] is None \
                        else max(f["last_utc"], b)
            prev_key = key
            prev_end = end
            prev_action = action
        flush(pending, prev_key)
        for key, (lo, hi) in spans.items():
            frame(key)["wall_s"] += hi - lo
    _effort_overlaps(segments, cells, frames, out)
    if out["outside"]:
        warnings.append("%d marks outside every frame, counted under %s"
                        % (out["outside"], EFFORT_OUTSIDE))
    for f in frames.values():
        f["active_s"] = f["draw_s"] + f["lead_s"] + f["overhead_s"]
        f["sessions"] = len(f["sessions"])
        f["first_utc"] = effort_format_utc(f["first_utc"])
        f["last_utc"] = effort_format_utc(f["last_utc"])
    return out


def _effort_pauses(text):
    out = []
    for bit in str(text or "").split(";"):
        f = effort_float(bit.strip()) if bit.strip() else None
        if f is not None:
            out.append(f)
    return out


def _effort_overlaps(segments, cells, frames, out):
    """Count once the time one operator was active in two sessions at once.

    Each mark's active span runs from the start of its lead time to the end
    of its stroke, in UTC. Where a span of a later session lies over spans
    of an earlier one, the overlapping seconds are taken off its lead first
    and then off its draw, and the total is reported."""
    for op, segs in segments.items():
        by = {}
        for s in segs:
            by.setdefault(s[2], []).append(s)
        if len(by) < 2:
            continue
        order = sorted(by, key=lambda sid: min(s[0] for s in by[sid]))
        done = []
        total = 0.0
        for sid in order:
            mine = sorted(by[sid], key=lambda s: s[0])
            if done:
                merged = _effort_merge([(s[0], s[1]) for s in done])
                starts = [m[0] for m in merged]
                for s in mine:
                    o = _effort_overlap(s[0], s[1], merged, starts)
                    if o <= 0:
                        continue
                    o = min(o, s[4] + s[5])
                    take_lead = min(o, s[4])
                    take_draw = o - take_lead
                    for target in (cells.get(s[3]), frames.get(s[3][:3])):
                        if target is not None:
                            target["lead_s"] -= take_lead
                            target["draw_s"] -= take_draw
                    total += o
            done.extend(mine)
        if total > 0:
            out["overlap_s"] += total
            out["warnings"].append(
                "%s was active in two sessions at once for %.0f s, counted "
                "once" % (op, total))


def _effort_merge(spans):
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def _effort_overlap(a, b, merged, starts):
    i = max(0, bisect.bisect_right(starts, a) - 1)
    total = 0.0
    while i < len(merged) and merged[i][0] < b:
        total += max(0.0, min(b, merged[i][1]) - max(a, merged[i][0]))
        i += 1
    return total


def effort_sensitivity(rows, thresholds=IDLE_SENSITIVITY, frame_of=None,
                       default_tile=None):
    """effort_attribute at every idle limit asked for: {T: result}."""
    return {t: effort_attribute(rows, t, frame_of, default_tile)
            for t in thresholds}


def effort_class_totals(result):
    """{(operator, pass_no, class_code): active seconds} over every frame."""
    out = {}
    for (tile, op, pass_no, code), c in result["cells"].items():
        key = (op, pass_no, code)
        out[key] = out.get(key, 0.0) + c["draw_s"] + c["lead_s"]
    return out


def effort_per_ha(seconds, m2):
    """Minutes per hectare, or NaN with no area."""
    if seconds is None or not m2 or m2 <= 0:
        return EFFORT_NAN
    return float(seconds) / 60.0 / (float(m2) / 1e4)


def effort_legacy(whens, idle_s=IDLE_DEFAULT_S):
    """Seconds per row of an operations.csv kept before the journal existed.

    Only the end of each stroke is known there, to the second. A gap to the
    row before no longer than the idle limit goes to the later row; the
    first row, and a row after an idle gap, get 0. ([seconds], unreadable)
    with unreadable the count of "when" values that are not a time."""
    out, bad, last = [], 0, None
    for w in whens:
        try:
            t = datetime.fromisoformat(str(w).strip()).timestamp()
        except ValueError:
            bad += 1
            out.append(0.0)
            continue
        if last is None:
            out.append(0.0)
        else:
            gap = t - last
            out.append(gap if 0 <= gap <= idle_s else 0.0)
        last = t
    return out, bad


def effort_grid_relation(ga, gb, same_crs=None):
    """How two grids relate: "same", "aligned_crs" or "other".

    "same" when the coordinate system is the same, the pixels are the same
    size, and one origin is a whole number of pixels from the other: then
    the frames of the one are frames of the other, pixel for pixel.
    "aligned_crs" when only the coordinate system is the same: frames are
    then compared by position. "other" means no pairing at all. same_crs
    decides whether two crs texts mean one system (osr's IsSame in the
    program); without it they are compared as text."""
    if not ga or not gb:
        return "other"
    ca, cb = ga.get("crs") or "", gb.get("crs") or ""
    same = same_crs(ca, cb) if same_crs is not None \
        else ca.strip().upper() == cb.strip().upper()
    if not same:
        return "other"
    try:
        pa = [float(v) for v in ga["pixel_crs"]]
        pb = [float(v) for v in gb["pixel_crs"]]
        oa = [float(v) for v in ga["origin"]]
        ob = [float(v) for v in gb["origin"]]
    except (KeyError, TypeError, ValueError):
        return "aligned_crs"
    for u, v in zip(pa, pb):
        if abs(u - v) > 1e-9 * max(abs(u), abs(v), 1e-300):
            return "aligned_crs"
    for u, v, p in zip(oa, ob, pa):
        steps = (v - u) / p
        if abs(steps - round(steps)) > 1e-6:
            return "aligned_crs"
    return "same"


def effort_pair(scratch, correct, n_boot=BOOTSTRAP_N, seed=BOOTSTRAP_SEED,
                level=0.95, min_frames=BOOTSTRAP_MIN_FRAMES):
    """Drawing from scratch against correcting, frame by frame.

    scratch and correct are {tile_id: active seconds}. For every frame in
    both with time on both sides, r = ln(correct / scratch). The ratio is the
    geometric mean exp(mean r), with its frame-bootstrap interval (seeded,
    percentile) and the Wilcoxon signed-rank p of r; the median of the plain
    ratios is given beside it. A frame with no time on one side is skipped
    and counted, never read as infinitely fast."""
    rows, skipped, logs = [], [], []
    for tile in sorted(set(scratch) & set(correct)):
        s, c = scratch.get(tile), correct.get(tile)
        if not s or not c or s <= 0 or c <= 0:
            skipped.append(tile)
            continue
        r = math.log(c / s)
        logs.append(r)
        rows.append({"tile_id": tile, "scratch_s": s, "correct_s": c,
                     "ratio": c / s, "log_ratio": r,
                     "saving_pct": 100.0 * (1.0 - c / s)})
    boot = st_bootstrap_stat(logs, lambda v: math.exp(float(v.mean()))
                             if v.size else EFFORT_NAN, n_boot, seed, level,
                             min_frames)
    ratios = sorted(x["ratio"] for x in rows)
    if ratios:
        mid = len(ratios) // 2
        median = ratios[mid] if len(ratios) % 2 else \
            (ratios[mid - 1] + ratios[mid]) / 2.0
    else:
        median = EFFORT_NAN
    ratio = math.exp(sum(logs) / len(logs)) if logs else EFFORT_NAN
    ci = boot["ci"] or [EFFORT_NAN, EFFORT_NAN]
    pooled = {"tile_id": "*", "n_frames": len(rows), "n_skipped": len(skipped),
              "skipped": skipped, "ratio": ratio, "median_ratio": median,
              "saving_pct": 100.0 * (1.0 - ratio) if logs else EFFORT_NAN,
              "ci_low": ci[0], "ci_high": ci[1], "n_boot": boot["n_boot"],
              "seed": seed, "ci_reason": boot["reason"],
              "wilcoxon_p": st_wilcoxon_signed(logs)["p"]}
    return {"rows": rows, "pooled": pooled}


#  The tables of a report
# =====================================================================
# The columns of the three tables, in their order. "_T" is the idle limit
# chosen in the window, written in the summary as idle_s; 30, 60 and 120 s
# are always there beside it, so a table read years later says what it is
# and the sensitivity of a conclusion can be read off the same rows.
EFFORT_FRAME_COLUMNS = (
    "source", "campaign_id", "correction_id", "tile_id", "frame_m2",
    "frame_ha", "operator", "pass_no", "sessions", "marks", "undos",
    "refused", "coverage_pct", "closed_reading", "changed_m2", "draw_s_T",
    "lead_s_T", "overhead_s_T", "active_s_T", "min_per_ha_T", "active_s_30",
    "active_s_60", "active_s_120", "wall_s", "first_utc", "last_utc",
    "journal", "estimated")
EFFORT_CLASS_COLUMNS = (
    "source", "campaign_id", "correction_id", "tile_id", "operator",
    "pass_no", "class_code", "class_name", "marks", "draw_s_T", "lead_s_T",
    "active_s_T", "active_s_30", "active_s_60", "active_s_120", "class_m2",
    "class_ha", "min_per_ha_T", "share_of_frame_time")
EFFORT_PAIRED_COLUMNS = (
    "tile_id", "frame_ha", "scratch_operator", "scratch_pass",
    "correct_operator", "scratch_s_T", "correct_s_T", "ratio_T",
    "log_ratio_T", "saving_pct_T", "ratio_30", "ratio_60", "ratio_120",
    "changed_m2", "median_ratio_T", "ci_low_T", "ci_high_T", "n_frames",
    "n_skipped", "wilcoxon_p")
# Appended to the frames table when the frames carry a sampling design, so
# a frame can be weighted by whoever reads the table.
EFFORT_DESIGN_COLUMNS = ("sample_id", "stratum", "incl_prob", "weight")
EFFORT_NO_CLASS = "(no class)"
EFFORT_LEGACY_SESSION = "operations.csv"
EFFORT_DESIGN_NOTES = [
    "Unit: the frame. One operator meets a frame once, from scratch or "
    "correcting, so there is no memory carried over; pairs are therefore "
    "across operators, and the operator effect is balanced by crossing.",
    "Crossed, counterbalanced design: split 2N frames into S1 and S2 matched "
    "by stratum; group G1 draws S1 from scratch and corrects S2, G2 the "
    "other way round; half of each group starts with scratch (AB/BA); "
    "frames in random order, seeded, the seed recorded; two warm-up frames "
    "per condition left out.",
    "Blindness: scratch readers do not see the model map (hide its layer); "
    "scratch readings use a pass of their own with 'blind' and 'one "
    "operator at a time' on; correctors work frame by frame on the same "
    "grid.",
    "Analysis: the per-frame paired log-ratio with its frame bootstrap "
    "interval; outside the program, from time_per_frame.csv, "
    "ln(active_s) ~ condition + order + ln(frame_ha) + (1|operator) + "
    "(1|frame), again at 30, 60 and 120 s.",
    "Sample size for a paired log-ratio of SD s: n = ((1.96 + 0.84) s / "
    "|ln rho|)^2. With s = 0.6, halving the time (rho = 0.5) needs 6 frames "
    "and a 30 % saving (rho = 0.7) 23: pilot s, and plan at least 12 frames "
    "per operator and condition.",
]


def _effort_seconds(res, key):
    f = res["frames"].get(key) if res else None
    return None if f is None else f["active_s"]


def effort_frame_table(source, results, idle_s, frame_m2, keys=None,
                       campaign_id="", correction_id="", coverage=None,
                       changed=None, journal=1, estimated=0, designs=None,
                       thresholds=IDLE_SENSITIVITY):
    """The rows of time_per_frame.csv for one source, as dicts.

    results is {idle limit: effort_attribute result} with idle_s and every
    one of thresholds in it. keys are the (tile_id, operator, pass_no) to
    write, in order; left out, every frame of the result. A key with no
    journal time (a frame drawn before the journal existed) is written with
    the time empty and journal 0, never as zero seconds. frame_m2 is
    {tile_id: m2}, or {key: m2} where the area is the reading's own (a
    campaign without frames); coverage {(tile, operator, pass): share
    0..1}; changed {(tile, operator, pass): m2}; designs {tile:
    {sample_id...}}."""
    main = results[idle_s]
    if keys is None:
        keys = sorted(main["frames"], key=lambda k: tuple(str(v) for v in k))
    rows = []
    for key in keys:
        tile, op, pass_no = key
        f = main["frames"].get(key)
        fm = frame_m2 or {}
        m2 = fm[key] if key in fm else fm.get(tile)
        share = (coverage or {}).get(key)
        row = {"source": source, "campaign_id": campaign_id,
               "correction_id": correction_id, "tile_id": tile,
               "frame_m2": m2, "frame_ha": None if m2 is None else m2 / 1e4,
               "operator": op, "pass_no": pass_no,
               "coverage_pct": None if share is None else 100.0 * share,
               "closed_reading": None if share is None
               else (1 if share > CLOSED_SHARE else 0),
               "changed_m2": (changed or {}).get(key),
               "journal": 1 if (f is not None and journal) else 0,
               "estimated": 1 if (f is not None and estimated) else 0}
        if f is None:
            row.update({"sessions": 0, "marks": 0, "undos": 0, "refused": 0})
        else:
            row.update({
                "sessions": f["sessions"], "marks": f["marks"],
                "undos": f["undos"], "refused": f["refused"],
                "draw_s_T": f["draw_s"], "lead_s_T": f["lead_s"],
                "overhead_s_T": f["overhead_s"], "active_s_T": f["active_s"],
                "min_per_ha_T": effort_per_ha(f["active_s"], m2),
                "wall_s": f["wall_s"], "first_utc": f["first_utc"],
                "last_utc": f["last_utc"]})
            for t in thresholds:
                row["active_s_%d" % t] = _effort_seconds(results.get(t), key)
        design = (designs or {}).get(tile)
        if design:
            for k in EFFORT_DESIGN_COLUMNS:
                row[k] = design.get(k)
        rows.append(row)
    return rows


def effort_class_table(source, results, idle_s, keys, class_m2=None,
                       class_names=None, campaign_id="", correction_id="",
                       thresholds=IDLE_SENSITIVITY):
    """The rows of time_per_class.csv for one source: one per frame,
    reading and class of the frames in keys, then one pooled row per reading
    and class over those frames, with tile_id "*". class_code 0 is the time
    no mark claimed, overhead, "(no class)". class_m2 is {(tile, operator,
    pass, code): m2}, the area of that reading's class in the frame."""
    main = results[idle_s]
    names = dict(class_names or {})
    names.setdefault(0, EFFORT_NO_CLASS)
    areas = class_m2 or {}
    rows, pooled = [], {}

    def cell_of(res, ckey):
        c = (res or {}).get("cells", {}).get(ckey)
        return None if c is None else c["draw_s"] + c["lead_s"]

    for fkey in keys:
        f = main["frames"].get(fkey)
        if f is None:
            continue
        codes = sorted({k[3] for k in main["cells"] if k[:3] == fkey})
        # Overhead is written under "(no class)". It has a row when it is
        # there at the chosen limit or at any of the others: a longer limit
        # keeps gaps that a shorter one calls idle, and a frame's time at
        # 30, 60 and 120 s must add up over its classes at each of them.
        if 0 not in codes and any(
                (res or {}).get("frames", {}).get(fkey, {}).get(
                    "overhead_s", 0) > 0
                for res in [main] + [results.get(t) for t in thresholds]):
            codes = [0] + codes
        for code in codes:
            ckey = fkey + (code,)
            c = main["cells"].get(ckey)
            draw = c["draw_s"] if c else 0.0
            lead = (c["lead_s"] if c else 0.0) + \
                (f["overhead_s"] if code == 0 else 0.0)
            active = draw + lead
            m2 = areas.get(ckey) if code else None
            row = {"source": source, "campaign_id": campaign_id,
                   "correction_id": correction_id, "tile_id": fkey[0],
                   "operator": fkey[1], "pass_no": fkey[2],
                   "class_code": code, "class_name": names.get(
                       code, "code %s" % code),
                   "marks": c["marks"] if c else 0, "draw_s_T": draw,
                   "lead_s_T": lead, "active_s_T": active,
                   "class_m2": m2, "class_ha": None if m2 is None
                   else m2 / 1e4,
                   "min_per_ha_T": effort_per_ha(active, m2),
                   "share_of_frame_time": active / f["active_s"]
                   if f["active_s"] > 0 else None}
            for t in thresholds:
                res = results.get(t)
                v = cell_of(res, ckey) or 0.0
                if code == 0 and res is not None:
                    fr = res["frames"].get(fkey)
                    v += fr["overhead_s"] if fr else 0.0
                row["active_s_%d" % t] = v
            rows.append(row)
            p = pooled.setdefault((fkey[1], fkey[2], code), {
                "marks": 0, "draw_s_T": 0.0, "lead_s_T": 0.0,
                "active_s_T": 0.0, "class_m2": None,
                "by": {t: 0.0 for t in thresholds}})
            p["marks"] += row["marks"]
            for k in ("draw_s_T", "lead_s_T", "active_s_T"):
                p[k] += row[k]
            for t in thresholds:
                p["by"][t] += row["active_s_%d" % t]
            if m2 is not None:
                p["class_m2"] = (p["class_m2"] or 0.0) + m2
    totals = {}
    for (op, pass_no, code), p in pooled.items():
        totals[(op, pass_no)] = totals.get((op, pass_no), 0.0) \
            + p["active_s_T"]
    for (op, pass_no, code) in sorted(pooled, key=lambda k: (
            str(k[0]), str(k[1]), k[2])):
        p = pooled[(op, pass_no, code)]
        total = totals.get((op, pass_no), 0.0)
        row = {"source": source, "campaign_id": campaign_id,
               "correction_id": correction_id, "tile_id": "*",
               "operator": op, "pass_no": pass_no, "class_code": code,
               "class_name": names.get(code, "code %s" % code),
               "marks": p["marks"], "draw_s_T": p["draw_s_T"],
               "lead_s_T": p["lead_s_T"], "active_s_T": p["active_s_T"],
               "class_m2": p["class_m2"],
               "class_ha": None if p["class_m2"] is None
               else p["class_m2"] / 1e4,
               "min_per_ha_T": effort_per_ha(p["active_s_T"], p["class_m2"]),
               "share_of_frame_time": p["active_s_T"] / total
               if total > 0 else None}
        for t in thresholds:
            row["active_s_%d" % t] = p["by"][t]
        rows.append(row)
    return rows


def effort_by_tile(results, keys, how="mean"):
    """{idle limit: {tile_id: seconds}} over the readings of keys: the mean
    of the readings that put time on the frame (drawing from scratch, where
    two people may each have drawn it), or their sum (correcting, where the
    strokes of one correction add up)."""
    out = {}
    for t, res in results.items():
        per = {}
        for key in keys:
            f = res["frames"].get(key)
            if f is None or f["active_s"] <= 0:
                continue
            per.setdefault(key[0], []).append(f["active_s"])
        out[t] = {tile: (sum(v) / len(v) if how == "mean" else sum(v))
                  for tile, v in per.items()}
    return out


def effort_paired_table(scratch, correct, idle_s, frame_m2=None, who=None,
                        changed=None, thresholds=IDLE_SENSITIVITY,
                        n_boot=BOOTSTRAP_N, seed=BOOTSTRAP_SEED):
    """The rows of time_paired.csv, and the pooled result at the chosen
    limit and at each of the thresholds.

    scratch and correct are effort_by_tile's {limit: {tile: s}}. who is
    {tile: (scratch operators, scratch passes, correct operators)} as text.
    The last row is the pooled one, tile_id "*"."""
    limits = sorted(set([idle_s] + list(thresholds)))
    pairs = {t: effort_pair(scratch.get(t, {}), correct.get(t, {}), n_boot,
                            seed) for t in limits}
    main = pairs[idle_s]
    by_t = {t: {r["tile_id"]: r for r in pairs[t]["rows"]} for t in pairs}
    rows = []
    for r in main["rows"]:
        tile = r["tile_id"]
        m2 = (frame_m2 or {}).get(tile)
        names = (who or {}).get(tile, ("", "", ""))
        row = {"tile_id": tile, "frame_ha": None if m2 is None else m2 / 1e4,
               "scratch_operator": names[0], "scratch_pass": names[1],
               "correct_operator": names[2], "scratch_s_T": r["scratch_s"],
               "correct_s_T": r["correct_s"], "ratio_T": r["ratio"],
               "log_ratio_T": r["log_ratio"], "saving_pct_T": r["saving_pct"],
               "changed_m2": (changed or {}).get(tile)}
        for t in thresholds:
            other = by_t[t].get(tile)
            row["ratio_%d" % t] = other["ratio"] if other else None
        rows.append(row)
    pooled = main["pooled"]
    ratio = pooled["ratio"]
    total = {"tile_id": "*", "ratio_T": ratio,
             "log_ratio_T": math.log(ratio)
             if ratio == ratio and ratio > 0 else None,
             "saving_pct_T": pooled["saving_pct"],
             "median_ratio_T": pooled["median_ratio"],
             "ci_low_T": pooled["ci_low"], "ci_high_T": pooled["ci_high"],
             "n_frames": pooled["n_frames"], "n_skipped": pooled["n_skipped"],
             "wilcoxon_p": pooled["wilcoxon_p"],
             "scratch_s_T": sum(r["scratch_s"] for r in main["rows"]),
             "correct_s_T": sum(r["correct_s"] for r in main["rows"]),
             "changed_m2": sum(v for v in (changed or {}).values()
                               if v is not None) if changed else None}
    for t in thresholds:
        total["ratio_%d" % t] = pairs[t]["pooled"]["ratio"]
    rows.append(total)
    return rows, {t: p["pooled"] for t, p in pairs.items()}


def effort_totals(frame_rows, thresholds=IDLE_SENSITIVITY):
    """Hours and minutes per hectare of a set of frame rows, at the chosen
    limit ("T") and at each threshold. Rows with no journal time are left
    out of both the time and the area, so a frame drawn before the journal
    began does not make the rest look faster."""
    out = {}
    timed = [r for r in frame_rows if r.get("active_s_T") is not None]
    ha = sum(r["frame_ha"] for r in timed if r.get("frame_ha"))
    for name, col in [("T", "active_s_T")] + [
            (t, "active_s_%d" % t) for t in thresholds]:
        s = sum(r.get(col) or 0.0 for r in timed)
        out[name] = {"active_h": s / 3600.0, "active_s": s,
                     "frames": len(timed), "ha": ha,
                     "min_per_ha": s / 60.0 / ha if ha > 0 else EFFORT_NAN}
    return out


def effort_legacy_rows(operations, codes=None):
    """Journal rows made out of an operations.csv kept before the journal:
    one "correct" mark per stroke, at its local "when" read as the moment
    the stroke ended, with no duration. Read through effort_attribute, a
    gap no longer than the limit goes to the later stroke and the first
    stroke gets nothing, the rule of effort_legacy, with the frames the
    strokes fall in. codes is {class name: code}. ([rows], unreadable)."""
    out, bad = [], 0
    # A row of a kept operations.csv has no reading and no frame; the empty
    # text is held in a name so that no literal sits beside the column name
    # "pass_no", which a scanner of source reads as a hard-coded password.
    nothing = ""
    for i, r in enumerate(operations or []):
        when = str(r.get("when") or "").strip()
        try:
            t = datetime.fromisoformat(when)
        except ValueError:
            bad += 1
            continue
        if t.tzinfo is None:
            t = t.astimezone()
        seconds = t.timestamp()
        name = str(r.get("into") or "")
        out.append({"session": EFFORT_LEGACY_SESSION, "seq": i + 1,
                    "mono_ms": int(round(seconds * 1000)),
                    "t_utc": effort_format_utc(seconds), "dur_ms": 0,
                    "pauses_s": "", "module": "correct", "action": "correct",
                    "operator": str(r.get("operator") or "").strip().upper(),
                    "pass_no": nothing, "tile_id": nothing,
                    "class_code": (codes or {}).get(name, 0),
                    "x": r.get("x"), "y": r.get("y"),
                    "pixels": r.get("pixels"),
                    "area_m2": r.get("changed_m2"), "ref": r.get("n")})
    return out, bad


def effort_changed_by(rows, frame_of=None, default_tile=None):
    """{(tile, operator, pass): m2 changed} of the "correct" rows, placed the
    way effort_attribute places them."""
    out = {}
    for r in rows:
        if r.get("action") != "correct":
            continue
        tile = str(r.get("tile_id") or "") or (
            frame_of(r) if frame_of is not None else None) or default_tile
        if tile is None:
            continue
        key = (tile, str(r.get("operator") or ""), str(r.get("pass_no") or ""))
        m2 = effort_float(r.get("area_m2"))
        out[key] = out.get(key, 0.0) + (m2 or 0.0)
    return out


def effort_rule(idle_s):
    """The rule with the limit written in, for the summary and the paper."""
    return EFFORT_RULE.replace("than T", "than %g s" % float(idle_s))


def effort_parameters(idle_s):
    """What the summary says the numbers were made with."""
    return {"idle_s": idle_s, "thresholds": list(IDLE_SENSITIVITY),
            "pause_min_s": PAUSE_MIN_S, "heartbeat_s": HEARTBEAT_S,
            "rule": effort_rule(idle_s), "rule_T": EFFORT_RULE,
            "n_boot": BOOTSTRAP_N, "seed": BOOTSTRAP_SEED,
            "bootstrap": "frames resampled with replacement, percentile "
                         "95 %%, numpy default_rng(seed); no interval below "
                         "%d frames" % BOOTSTRAP_MIN_FRAMES}
