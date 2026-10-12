"""rasterlabel.journal

The journal of working time: one row per thing done, written as it happens
into journal.csv beside the campaign or the correction, and never rewritten.

What it holds is what Time needs and nothing more: when a stroke started and
ended, the pauses inside it, who drew it, in which pass, on which frame, of
which class, how large. No keys, no screen, nothing typed. Every row says
when it ended twice over: in milliseconds of time.monotonic(), which never
jumps, for the gaps inside one session, and in UTC, for putting sessions side
by side; the start is the end less the duration.

The two pieces here are the data, not the wiring. Stopwatch times one stroke
from the first press to the last release. Journal appends the rows. Neither
knows about QGIS: the map tools hand the stopwatch's reading to the section,
and the section hands it to the journal, together with an operator and a
pass already spelt the way the readings spell them (campaign.operator_word
and pass_number, which Journal is given rather than importing, so it stays
free of GDAL).

Nothing is written for a campaign or a correction that has not begun a
journal until the first mark is drawn: only then are the file and the
"journal" block of the manifest made (Journal's held). Old campaigns open as
they were.

Here too, in the same voice, are the pieces the rest of the program calls by
name through measure.py: journal_frame_event, told of every frame placed,
moved, deleted or imported; CorrectJournalHook, told of every stroke of
Correct once it is on disk; journal_findings and journal_findings_correction,
for Check. What they need of QGIS (the manifest's block, the signals of the
application) they borrow from ui_time when called, so this module still
imports nothing but the constants.

Writing must never get in the way of drawing. A file that cannot be written
(locked by a spreadsheet on Windows, a full disk, a folder gone) is said once
through the complaint the journal was given, the rows are kept in memory up
to JOURNAL_BUFFER and written on the next row that gets through, in order.
Nothing in here raises.
"""
import csv
import importlib
import io
import os
import sqlite3
import time
import uuid

from datetime import datetime, timezone
from urllib.request import pathname2url

from .constants import (IDLE_DEFAULT_S, JOURNAL_BUFFER, JOURNAL_COLUMNS,
                        JOURNAL_NAME, MARK_ACTIONS, PAUSE_MIN_S)
from .naming import csv_text, csv_untext_row, long_path


def journal_utc_ms(when=None):
    """UTC to the millisecond, with a Z: 2026-10-08T17:30:00.123Z."""
    when = when or datetime.now(timezone.utc)
    return when.astimezone(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def journal_pauses_text(pauses):
    """The pauses as the journal writes them: seconds to one decimal, ";"."""
    return ";".join("%.1f" % p for p in pauses)


def journal_pauses(text):
    """The pauses of a row back as a list of seconds."""
    out = []
    for bit in str(text or "").split(";"):
        bit = bit.strip()
        if bit:
            try:
                out.append(float(bit))
            except ValueError:
                pass
    return out


class Stopwatch(object):
    """The time of one stroke, from its first touch to its last.

    begin() on the first press, touch() on every press, move and release,
    take() when the stroke is handed over. Every gap of at least PAUSE_MIN_S
    seconds between two touches is kept as a pause, so that Time can later
    leave out of the stroke the pauses longer than its idle limit. The clock
    is time.monotonic unless another is given, which is how the tests drive
    it."""

    def __init__(self, clock=None, pause_min_s=PAUSE_MIN_S):
        self.clock = clock or time.monotonic
        self.pause_min_s = pause_min_s
        self.start = None
        self.last = None
        self.pauses = []

    @property
    def running(self):
        return self.start is not None

    def begin(self):
        self.start = self.last = self.clock()
        self.pauses = []

    def touch(self):
        """One more sign of life. A touch with no begin begins."""
        now = self.clock()
        if self.start is None:
            self.start = self.last = now
            self.pauses = []
            return
        if now - self.last >= self.pause_min_s:
            self.pauses.append(now - self.last)
        self.last = now

    def take(self):
        """(dur_ms, pauses_s) of the stroke so far, and the watch stops.

        None when nothing was begun. The duration runs to the last touch,
        which is the release: the time between letting go and the stroke
        being handed over is the program's, not the person's."""
        if self.start is None:
            return None
        out =(int(round((self.last - self.start) * 1000)),
               journal_pauses_text(self.pauses))
        self.start = self.last = None
        self.pauses = []
        return out

    def drop(self):
        """Forget the stroke without a reading."""
        self.start = self.last = None
        self.pauses = []


# What begins a journal: a mark, or a frame placed, moved, deleted or
# imported. Opening a module, looking around, choosing a class or a pass
# waits with the rows that follow until one of these comes.
JOURNAL_BEGINS = frozenset(MARK_ACTIONS) | {"frame_new", "frame_move",
                                            "frame_delete", "frame_import"}


class Journal(object):
    """Append-only rows of journal.csv in one folder, for one session.

    session is the id of this QGIS (recovery's session id in the program),
    module the one writing unless a row says otherwise: annotate, objects or
    correct. operator_word and pass_number, when given, spell the operator
    and the pass of every row; complain(text) is told, once, when the file
    cannot be written. clock and wall stand in for time.monotonic and the
    UTC clock in the tests.

    held is for a journal that has not begun: a campaign whose manifest says
    nothing of a journal yet. Its rows wait in memory, and nothing at all is
    written, not the file and not the manifest, until the first mark (a
    stroke, a point, a box...): looking at a campaign is not working on it,
    and a manifest must never claim a journal nobody writes. At the first
    mark on_start(journal, t_utc of the first row) is called, which is where
    the program writes the "journal" block into the manifest, and then the
    waiting rows go out in order with the mark.

    It also keeps, as it goes, the active time of the day at the default
    idle limit, per operator and per frame, by the same rule as Time: the
    quiet line under the coverage in Annotate and under the tally in Correct
    is read from it, without reading the file again."""

    def __init__(self, folder, session, module, name=JOURNAL_NAME,
                 operator_word=None, pass_number=None, complain=None,
                 clock=None, wall=None, buffer=JOURNAL_BUFFER, held=False,
                 on_start=None, idle_s=IDLE_DEFAULT_S):
        self.folder = folder
        self.path = os.path.join(folder, name)
        self.session = session
        self.module = module
        self.operator_word = operator_word
        self.pass_number = pass_number
        self.complain = complain
        self.clock = clock or time.monotonic
        self.wall = wall or (lambda: datetime.now(timezone.utc))
        self.buffer = buffer
        self.seq = 0
        self.waiting = []
        self.complained = False
        self.dropped = 0
        self.on = True
        self.held = bool(held)
        self.on_start = on_start
        self.written = 0
        # the active time of today, kept as the rows go by
        self.idle_s = float(idle_s)
        self.live_day = None
        self.live_today = {}
        self.live_frame = {}
        self.live_end = None
        self.live_last = None
        self.live_tile = ""
        self.live_operator = ""
        self.last_mono = None

    def _say(self, text):
        if self.complained or self.complain is None:
            return
        self.complained = True
        try:
            self.complain(text)
        except Exception:
            pass

    def row(self, action, timing=None, module=None, **fields):
        """The row this would write, as a dict over JOURNAL_COLUMNS.

        timing is what a map tool handed over: (dur_ms, pauses_s), and the
        word of the tool as a third item when it gave one."""
        self.seq += 1
        timing = tuple(timing or (0, ""))
        dur_ms, pauses = (timing + (0, ""))[:2]
        out = dict.fromkeys(JOURNAL_COLUMNS, "")
        out.update({"session": self.session, "seq": self.seq,
                    "mono_ms": int(self.clock() * 1000),
                    "t_utc": journal_utc_ms(self.wall()),
                    "dur_ms": int(dur_ms or 0), "pauses_s": pauses or "",
                    "module": module or self.module, "action": action})
        if len(timing) > 2 and timing[2] and not fields.get("tool"):
            out["tool"] = timing[2]
        unknown = []
        for key, value in fields.items():
            if key in out and key not in ("session", "seq", "mono_ms",
                                          "t_utc", "module", "action"):
                out[key] = "" if value is None else value
            else:
                unknown.append(key)
        if unknown:
            self._say("the journal has no column %s" % ", ".join(unknown))
        if self.operator_word is not None and "operator" in fields:
            try:
                out["operator"] = self.operator_word(fields["operator"])
            except Exception:
                pass
        if self.pass_number is not None and "pass_no" in fields \
                and out["module"] != "correct":
            try:
                out["pass_no"] = self.pass_number(fields["pass_no"])
            except Exception:
                pass
        return out

    def note(self, action, timing=None, module=None, **fields):
        """Write one row, now. Returns the row, written or kept waiting, or
        None while the journal is switched off."""
        if not self.on:
            return None
        row = self.row(action, timing, module, **fields)
        self._live(row)
        self.waiting.append(row)
        if self.held:
            if action not in JOURNAL_BEGINS:
                if len(self.waiting) > self.buffer:
                    # the first row, the opening, is the one kept longest
                    gone = len(self.waiting) - self.buffer
                    self.waiting = self.waiting[:1] + self.waiting[1 + gone:]
                return row
            self.held = False
            self._begin()
        if len(self.waiting) > self.buffer:
            self.dropped += len(self.waiting) - self.buffer
            self.waiting = self.waiting[-self.buffer:]
        self.flush()
        return row

    def _begin(self):
        """The first mark: the manifest is told from when on rows are kept,
        before the first row is on disk."""
        if self.on_start is None:
            return
        first = self.waiting[0]["t_utc"] if self.waiting \
            else journal_utc_ms(self.wall())
        try:
            self.on_start(self, first)
        except Exception as err:
            if self.complain is not None:
                try:
                    self.complain("the manifest could not be told that the "
                                  "journal began: %s" % err)
                except Exception:
                    pass

    def switch(self, on):
        """On or off. Off, nothing more is kept; rows waiting for the first
        mark are forgotten with it, never written later."""
        self.on = bool(on)
        if not self.on and self.held:
            self.waiting = []

    def flush(self):
        """Write every row still waiting. True when none is left. A journal
        that has not begun writes nothing."""
        if not self.waiting:
            return True
        if self.held:
            return False
        try:
            fresh = not os.path.exists(long_path(self.path)) \
                or os.path.getsize(long_path(self.path)) == 0
            with io.open(long_path(self.path), "a", encoding="utf-8",
                         newline="") as fh:
                out = csv.writer(fh, lineterminator="\n")
                if fresh:
                    out.writerow(JOURNAL_COLUMNS)
                for r in self.waiting:
                    out.writerow([journal_cell(r[c]) for c in JOURNAL_COLUMNS])
        except OSError as err:
            self._say("journal.csv could not be written (%s); the rows are "
                      "kept and written as soon as it can be" % err)
            return False
        self.written += len(self.waiting)
        self.waiting = []
        return True

    # ------------------------------------------------------- today, live
    def _live(self, row):
        """Today's active time, one row more, at the default idle limit: the
        gap before the row when it is no longer than the limit and QGIS was
        in front, and a mark's own duration less its long pauses."""
        end = row["mono_ms"] / 1000.0
        dur = max(0, int(row.get("dur_ms") or 0)) / 1000.0
        start = end - dur
        day = journal_local_day(row.get("t_utc"))
        if day != self.live_day:
            self.live_day = day
            self.live_today = {}
            self.live_frame = {}
        op = str(row.get("operator") or "") or self.live_operator
        tile = str(row.get("tile_id") or "")
        action = row.get("action")
        is_mark = action in MARK_ACTIONS
        if self.live_end is not None and self.live_last != "focus_out" \
                and end >= self.live_end:
            gap = max(0.0, start - self.live_end)
            if gap <= self.idle_s:
                self._live_add(op, tile if is_mark and tile
                               else self.live_tile, gap)
        if is_mark:
            draw = dur - sum(p for p in journal_pauses(row.get("pauses_s"))
                             if p > self.idle_s)
            self._live_add(op, tile or self.live_tile, max(0.0, draw))
        self.live_end = end
        self.live_last = action
        self.last_mono = end
        if tile:
            self.live_tile = tile
        if op:
            self.live_operator = op

    def _live_add(self, op, tile, seconds):
        if seconds <= 0:
            return
        self.live_today[op] = self.live_today.get(op, 0.0) + seconds
        key = (op, tile or "")
        self.live_frame[key] = self.live_frame.get(key, 0.0) + seconds

    def seed(self, today, frames):
        """What the earlier sessions of today already counted:
        {operator: s} and {(operator, tile): s}."""
        for op, s in (today or {}).items():
            self.live_today[op] = self.live_today.get(op, 0.0) + float(s)
        for key, s in (frames or {}).items():
            self.live_frame[key] = self.live_frame.get(key, 0.0) + float(s)
        if self.live_day is None:
            self.live_day = datetime.now().astimezone().date()

    def active_today(self, operator=None):
        """Seconds of active time today, of one operator or of everybody."""
        if operator is None:
            return sum(self.live_today.values())
        return self.live_today.get(operator, 0.0)

    def active_frame(self, operator, tile):
        """Seconds of active time today on one frame, of one operator."""
        return self.live_frame.get((operator, tile or ""), 0.0)

    def quiet_s(self):
        """Seconds since the last row of this session, or None before it."""
        if self.last_mono is None:
            return None
        return self.clock() - self.last_mono


def journal_local_day(utc_text):
    """The local day of a row's t_utc, or None."""
    try:
        when = datetime.fromisoformat(str(utc_text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone().date()


def journal_duration_text(seconds):
    """Minutes as the quiet line says them: 6 min, 1 h 12 min."""
    minutes = int((seconds or 0.0) // 60)
    if minutes < 60:
        return "%d min" % minutes
    return "%d h %d min" % (minutes // 60, minutes % 60)


def journal_line(journal, operator=None, tile=None):
    """The quiet line: "active 1 h 12 min today · this frame 6 min", or ""
    with no journal running."""
    if journal is None or not journal.on:
        return ""
    text = "active %s today" % journal_duration_text(
        journal.active_today(operator))
    if tile:
        text += " · this frame %s" % journal_duration_text(
            journal.active_frame(operator or "", tile))
    return text


# What the panel says about the journal, in the tooltips of the line and
# the tick box: what is kept, and that nothing else is.
JOURNAL_TOOLTIP = (
    "The journal of working time: every saved action (a stroke, a point, a\n"
    "box, a frame placed or moved, a class chosen, a pass changed) adds one\n"
    "line to journal.csv beside the campaign, with when it started and\n"
    "ended, who, which pass, frame and class. No keys, no mouse tracks, no\n"
    "screen, nothing else.\n\n"
    "Active time is the sum of the gaps between those lines; a gap longer\n"
    "than %d s, or one while QGIS was not in front, is not counted. Time,\n"
    "under Measure, writes it out per frame, per reading and per class."
    % IDLE_DEFAULT_S)


#  The session, and names borrowed late
# =====================================================================
_JOURNAL_SESSION = []


def journal_borrow(module, name):
    """A function of another module, found when it is wanted: in the single
    file every module shares one namespace, in the package it is an
    attribute of the module named. None when it is not there. The journal
    imports nothing of the program but its constants, so it stays as pure
    as Time's engine; what it needs of QGIS it borrows this way."""
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


def journal_session_id(panel=None):
    """The session a row is filed under: recovery's session id of the
    campaign open in the panel, which is what the recovery files of the same
    run are named after; with none, one id for this run of the program, made
    the same way and kept."""
    net = getattr(panel, "recovery", None)
    sid = getattr(net, "session", None)
    if isinstance(sid, str) and sid:
        return sid
    if not _JOURNAL_SESSION:
        make = journal_borrow("recovery", "_recovery_session")
        try:
            sid = make() if make is not None else ""
        except Exception:
            sid = ""
        _JOURNAL_SESSION.append(sid or "%d-%s" % (os.getpid(),
                                                  uuid.uuid4().hex[:6]))
    return _JOURNAL_SESSION[0]


#  Where the frames and Correct come in (measure.py)
# =====================================================================
def journal_frame_event(section, kind, tile_id, before, after, feature):
    """A frame placed, moved, deleted or imported, once it is committed: one
    row, frame_new, frame_move, frame_delete or frame_import, at its middle,
    with the time the frame tool handed over when it was the tool's."""
    note = getattr(section, "note", None)
    if not callable(note):
        return None
    pop = getattr(section, "pop_timing", None)
    timing = pop() if callable(pop) else None
    box = after or before
    x = y = None
    if box:
        try:
            x = (float(box[0]) + float(box[2])) / 2.0
            y = (float(box[1]) + float(box[3])) / 2.0
        except (TypeError, ValueError, IndexError):
            x = y = None
    return note("frame_%s" % kind, timing=timing, tool="frame",
                tile_id=tile_id or "", x=x, y=y)


class CorrectJournalHook(object):
    """The journal of a correction, beside its operations.csv.

    One row per stroke of Correct, "correct", once the stroke is on disk,
    with the class it wrote, the class it changed (0 for any), the pixels
    and the ground it changed, its middle and its number in operations.csv
    as ref; "undo" with the number of the stroke it took back; "class" when
    TO is chosen; "open" and "close". operations.csv itself is not touched.
    The section gets a note() of its own from here, which the map tools use
    for a stroke that was refused."""

    def __init__(self, section):
        self.section = section
        make = journal_borrow("ui_time", "time_correction_journal")
        self.journal = make(section) if make is not None else None
        section.note = self.note
        if self.journal is not None:
            self.note("open")
            watch = journal_borrow("ui_time", "time_watch")
            if watch is not None:
                watch(section, self.journal, self.note)

    def note(self, action, timing=None, **fields):
        if self.journal is None:
            return None
        if "operator" not in fields:
            try:
                fields["operator"] = self.section.operator_name()
            except Exception:
                pass
        try:
            return self.journal.note(action, timing, **fields)
        except Exception:
            return None

    def stroke(self, section, ctx):
        timing = getattr(section, "timing", None)
        section.timing = None
        tool = ""
        try:
            tool = "round" if section.b_round.isChecked() else "brush"
        except Exception:
            tool = ""
        from_code = ctx.get("from_code")
        row = self.note("correct", timing, tool=tool,
                        class_code=ctx.get("into"),
                        from_code=0 if from_code is None else from_code,
                        pixels=ctx.get("pixels"),
                        area_m2=ctx.get("changed_m2"),
                        x=ctx.get("x"), y=ctx.get("y"),
                        place=ctx.get("place") or "", ref=ctx.get("n"))
        return {"n": ctx.get("n"), "seq": row["seq"] if row else None}

    def undo(self, section, state):
        self.note("undo", ref=(state or {}).get("n"))

    def flush(self, section):
        if self.journal is not None:
            self.journal.flush()

    def closing(self, section):
        if self.journal is not None:
            self.note("close")
            self.journal.flush()

    def files(self, section):
        return [self.journal.path] if self.journal is not None else []

    def tally_lines(self, section):
        if self.journal is None or not self.journal.on:
            return []
        try:
            who = self.section.operator_name()
        except Exception:
            who = None
        return [journal_line(self.journal, who)]


#  What Check says of it
# =====================================================================
def journal_finding(level, what, detail=""):
    """A line of Check, made by Check's own Finding."""
    make = journal_borrow("doctor", "Finding")
    if make is None:
        return None
    return make(level, what, detail)


def journal_local_text(utc_text):
    """A UTC moment of the journal as the local time, to the second, that
    the "created" of every mark is written in."""
    text = str(utc_text or "").strip()
    if not text:
        return ""
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone().replace(tzinfo=None).isoformat(
        timespec="seconds")


def journal_marks_before(package, since_local,
                         tables=("polygons", "lines", "points", "boxes")):
    """How many marks of the package were made before a local moment, read
    by SQLite with the file open read only. None when it cannot be read."""
    if not since_local or not os.path.isfile(long_path(package)):
        return None
    try:
        uri = "file:%s?mode=ro" % pathname2url(os.path.abspath(package))
        con = sqlite3.connect(uri, uri=True)
    except Exception:
        return None
    total = 0
    try:
        for table in tables:
            try:
                n = con.execute('SELECT COUNT(*) FROM "%s" WHERE created < ? '
                                'AND created IS NOT NULL AND created <> \'\''
                                % table, (since_local,)).fetchone()[0]
            except sqlite3.Error:
                continue
            total += int(n or 0)
    finally:
        con.close()
    return total


def _journal_summary(rows):
    sessions = {str(r.get("session") or "") for r in rows}
    last = rows[-1].get("t_utc") if rows else ""
    return ("%d row%s in %d session%s, the last at %s UTC"
            % (len(rows), "" if len(rows) == 1 else "s", len(sessions),
               "" if len(sessions) == 1 else "s",
               str(last).replace("T", " ").rstrip("Z")[:19]))


def _journal_state(owner):
    data = getattr(owner, "data", None) or {}
    folder = getattr(owner, "folder", None) or ""
    block = data.get("journal")
    block = block if isinstance(block, dict) else None
    name = (block or {}).get("file") or JOURNAL_NAME
    path = os.path.join(folder, name)
    there = os.path.isfile(long_path(path))
    return data, folder, block, path, there


def journal_findings(owner):
    """Check, on the journal of an annotation campaign. Nothing at all for a
    campaign that has never kept one, so an old campaign reads as it did."""
    data, folder, block, path, there = _journal_state(owner)
    if block is None and not there:
        return []
    out = []
    rows = journal_read(path) if there else []
    if block is not None and block.get("on") is False:
        out.append(journal_finding(
            "ok", "the journal of working time is switched off",
            (_journal_summary(rows) + " from before") if rows else
            "nothing was kept: Time has nothing to measure"))
    elif rows:
        out.append(journal_finding("ok", "journal of working time: "
                                   + _journal_summary(rows)))
    if block is not None and block.get("on", True) and not there:
        out.append(journal_finding(
            "note", "the manifest says a journal of working time is kept, "
            "but %s is not there" % os.path.basename(path),
            "moved or deleted by hand: Time cannot measure what it held"))
    if there and block is None:
        out.append(journal_finding(
            "note", "%s is there but the manifest does not say since when"
            % os.path.basename(path),
            "the time before its first row is not recorded"))
    since = journal_local_text((block or {}).get("since")) or (
        journal_local_text(rows[0].get("t_utc")) if rows else "")
    before = journal_marks_before(os.path.join(folder, "annotation.gpkg"),
                                  since)
    if before:
        out.append(journal_finding(
            "note", "%d mark%s in the package %s drawn before the journal "
            "began" % (before, "" if before == 1 else "s",
                       "was" if before == 1 else "were"),
            "their time is not recorded, never zero: Time lists their frames "
            "with no active time"))
    return [f for f in out if f is not None]


def journal_findings_correction(owner):
    """Check, on the journal of a correction: its rows, and the strokes of
    operations.csv that it has no row for."""
    data, folder, block, path, there = _journal_state(owner)
    ops = os.path.join(folder, "operations.csv")
    if block is None and not there:
        return []
    out = []
    rows = journal_read(path) if there else []
    if block is not None and block.get("on") is False:
        out.append(journal_finding("ok", "the journal of working time is "
                                   "switched off for this correction"))
    elif rows:
        out.append(journal_finding("ok", "journal of working time: "
                                   + _journal_summary(rows)))
    if block is not None and block.get("on", True) and not there:
        out.append(journal_finding(
            "note", "the manifest says a journal of working time is kept, "
            "but %s is not there" % os.path.basename(path)))
    refs = {str(r.get("ref") or "") for r in rows
            if r.get("action") == "correct"}
    numbers = []
    try:
        with io.open(long_path(ops), encoding="utf-8", newline="") as fh:
            numbers = [str(r.get("n") or "") for r in csv.DictReader(fh)]
    except (OSError, csv.Error, UnicodeDecodeError):
        numbers = []
    missing = [n for n in numbers if n and n not in refs]
    if missing:
        out.append(journal_finding(
            "note", "%d stroke%s of operations.csv %s no row in %s"
            % (len(missing), "" if len(missing) == 1 else "s",
               "has" if len(missing) == 1 else "have",
               os.path.basename(path)),
            "made before the journal began or while it was off: Time "
            "estimates their time from operations.csv, and says so"))
    return [f for f in out if f is not None]


def journal_cell(value):
    """One cell: floats with twelve significant figures, the rest as text."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return "%.12g" % value
    return "" if value is None else csv_text(str(value))


def journal_read(path):
    """Every row of a journal as a dict, the numbers that order them as ints.

    seq, mono_ms and dur_ms come back as int (0 when empty or broken); every
    other column as the text written. A file that cannot be read gives []."""
    out = []
    try:
        with io.open(long_path(path), encoding="utf-8", newline="") as fh:
            for row in map(csv_untext_row, csv.DictReader(fh)):
                for key in ("seq", "mono_ms", "dur_ms"):
                    try:
                        row[key] = int(float(row.get(key) or 0))
                    except ValueError:
                        row[key] = 0
                out.append(row)
    except OSError:
        return []
    return out
