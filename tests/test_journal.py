"""The journal of working time: what it writes, and that it never gets in
the way.

journal.csv is append only and read by Time years later, so its shape is
checked exactly: the header once, the columns in JOURNAL_COLUMNS order, a
seq that counts per session, the end of each row in monotonic milliseconds
and in UTC to the millisecond with a Z. A file that cannot be written must
neither raise nor lose a row: the rows wait and go out in order on the next
write that works, and the trouble is said once. The stopwatch of a stroke
keeps the pauses of ten seconds or more, which is what lets Time take the
long ones out.

A campaign that has not begun a journal writes nothing, neither the file
nor the manifest's block, until the first mark: then the rows that waited
go out in order and the manifest is told once. The day's active time is
kept as the rows go by, for the quiet line. The frame listener and the hook
of Correct write the rows measure.py promises, Check says what it finds,
a row costs a fraction of a millisecond, and a session killed outright
leaves every row it wrote.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import purekit

rl = purekit.load("journal")
t = purekit.Checks()
root = tempfile.mkdtemp(prefix="rl_journal_")


class Clock(object):
    """A clock that says what it is told."""

    def __init__(self, *times):
        self.times = list(times)
        self.now = 0.0

    def __call__(self):
        if self.times:
            self.now = self.times.pop(0)
        return self.now


def operator_word(text):
    """What campaign.operator_word does, for the test."""
    word = " ".join(str(text or "").split()).upper()
    return word or "UNNAMED"


def pass_number(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 1
    return n if n > 0 else 1


try:
    print("the stopwatch of one stroke")
    watch = rl.Stopwatch(clock=Clock(0.0, 5.0, 20.0, 22.0))
    t.ok("not running before the first press", not watch.running)
    watch.begin()
    watch.touch()
    watch.touch()
    watch.touch()
    dur, pauses = watch.take()
    t.ok("touches at 0, 5, 20, 22 s: 22000 ms", dur == 22000, dur)
    t.ok("one pause of 15.0 s; the 5 s and 2 s gaps are not pauses",
         pauses == "15.0", pauses)
    t.ok("taken, it stops", not watch.running and watch.take() is None)
    w2 = rl.Stopwatch(clock=Clock(1.0, 1.5))
    w2.touch()
    w2.touch()
    t.ok("a touch with no begin begins", w2.take() == (500, ""))
    w3 = rl.Stopwatch(clock=Clock(0.0, 10.0, 31.25))
    w3.begin()
    w3.touch()
    w3.touch()
    t.ok("a gap of exactly 10 s is a pause; pauses joined with ;",
         w3.take() == (31250, "10.0;21.2"))
    w3.begin()
    w3.drop()
    t.ok("drop forgets the stroke", w3.take() is None)
    t.ok("pauses read back", rl.journal_pauses("20.0;75.0; bad;") == [20.0,
                                                                     75.0])

    print()
    print("three rows, then the file read back")
    said = []
    base = datetime(2026, 10, 8, 17, 30, 0, 123000, tzinfo=timezone.utc)
    stamps = iter([base, base + timedelta(seconds=1),
                   base + timedelta(seconds=2.5), base])
    j = rl.Journal(root, "1234-abcdef", "annotate",
                   operator_word=operator_word, pass_number=pass_number,
                   complain=said.append, clock=Clock(10.0, 11.0, 12.5),
                   wall=lambda: next(stamps))
    j.note("open")
    j.note("stroke", timing=(15000, "20.0"), operator="  massi ",
           pass_no=None, tile_id="t001", class_code=1, area_m2=12.5,
           x=500001.25, y=4140005.5)
    j.note("save", operator="massi", pass_no=2)
    path = os.path.join(root, "journal.csv")
    text = io.open(path, encoding="utf-8", newline="").read()
    lines = text.split("\n")
    t.ok("the header exactly once", text.count("session,seq,") == 1
         and lines[0] == ",".join(rl.JOURNAL_COLUMNS))
    t.ok("the columns, place among them",
         "place" in rl.JOURNAL_COLUMNS and len(rl.JOURNAL_COLUMNS) == 22)
    t.ok("\\n line ends", "\r" not in text)
    rows = rl.journal_read(path)
    t.ok("three rows, seq 1 2 3", [r["seq"] for r in rows] == [1, 2, 3])
    t.ok("t_utc to the millisecond with a Z", all(re.match(
        r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$", r["t_utc"])
        for r in rows), [r["t_utc"] for r in rows])
    t.ok("the UTC end as given", rows[0]["t_utc"]
         == "2026-10-08T17:30:00.123Z")
    t.ok("mono_ms at the end of each row", [r["mono_ms"] for r in rows]
         == [10000, 11000, 12500])
    t.ok("the stroke's duration and pauses", rows[1]["dur_ms"] == 15000
         and rows[1]["pauses_s"] == "20.0")
    t.ok("operator '  massi ' is MASSI", rows[1]["operator"] == "MASSI")
    t.ok("pass None is 1", rows[1]["pass_no"] == "1")
    t.ok("pass 2 stays 2", rows[2]["pass_no"] == "2")
    t.ok("coordinates with every digit they need",
         rows[1]["x"] == "500001.25" and rows[1]["y"] == "4140005.5")
    t.ok("session and module on every row", all(
        r["session"] == "1234-abcdef" and r["module"] == "annotate"
        for r in rows))
    t.ok("nothing complained", not said, said)
    j2 = rl.Journal(root, "9999-zzzzzz", "annotate")
    j2.note("open")
    t.ok("a second session appends, the header still once",
         io.open(path, encoding="utf-8").read().count("session,seq,") == 1
         and len(rl.journal_read(path)) == 4)
    t.ok("and counts its own seq from 1", rl.journal_read(path)[-1]["seq"]
         == 1)
    j.note("stroke", colour="red")
    t.ok("an unknown column is said, not raised", len(said) == 1
         and "colour" in said[0], said)
    cj = rl.Journal(root, "s", "correct", pass_number=pass_number,
                    name="correct.csv")
    cj.note("correct", pass_no="", ref=7, from_code=0, class_code=3)
    t.ok("Correct has no pass: left empty", rl.journal_read(
        os.path.join(root, "correct.csv"))[0]["pass_no"] == "")
    off = rl.Journal(root, "s", "annotate", name="off.csv")
    off.on = False
    off.note("stroke")
    t.ok("a journal switched off writes nothing",
         not os.path.exists(os.path.join(root, "off.csv")))

    print()
    print("a journal that cannot be written")
    blocked = os.path.join(root, "blocked")
    os.makedirs(blocked)
    os.makedirs(os.path.join(blocked, "journal.csv"))     # a folder, not a file
    said = []
    jb = rl.Journal(blocked, "s1", "annotate", complain=said.append)
    try:
        for i in range(3):
            jb.note("stroke", tile_id="t%03d" % i)
        raised = False
    except Exception:
        raised = True
    t.ok("no exception", not raised)
    t.ok("said once, not three times", len(said) == 1, said)
    t.ok("the rows are kept", len(jb.waiting) == 3)
    os.rmdir(os.path.join(blocked, "journal.csv"))
    jb.note("stroke", tile_id="t003")
    back = rl.journal_read(os.path.join(blocked, "journal.csv"))
    t.ok("the next write flushes them in order",
         [r["tile_id"] for r in back] == ["t000", "t001", "t002", "t003"]
         and [r["seq"] for r in back] == [1, 2, 3, 4])
    t.ok("and nothing waits any more", not jb.waiting)
    small = rl.Journal(os.path.join(root, "missing", "folder"), "s", "annotate",
                       buffer=2)
    for i in range(5):
        small.note("stroke")
    t.ok("past the buffer the oldest rows go, and are counted",
         len(small.waiting) == 2 and small.dropped == 3)
    t.ok("a file that cannot be read gives no rows",
         rl.journal_read(os.path.join(root, "nope.csv")) == [])

    print()
    print("a journal that has not begun writes nothing until the first mark")
    begun = []
    fresh = os.path.join(root, "fresh")
    os.makedirs(fresh)
    stamps2 = iter([base + timedelta(seconds=s) for s in (0, 3, 9, 9.5)])
    jh = rl.Journal(fresh, "77-aaaaaa", "annotate", held=True,
                    on_start=lambda j, first: begun.append(first),
                    clock=Clock(100.0, 103.0, 109.0, 109.5),
                    wall=lambda: next(stamps2))
    jh.note("open")
    jh.note("view")
    t.ok("looking is not working: no file, and the manifest is not told",
         not os.path.exists(os.path.join(fresh, "journal.csv"))
         and begun == [] and len(jh.waiting) == 2)
    t.ok("flush writes nothing either", jh.flush() is False
         and not os.path.exists(os.path.join(fresh, "journal.csv")))
    jh.note("stroke", timing=(4000, "", "brush"), tile_id="t001",
            class_code=2)
    rows = rl.journal_read(os.path.join(fresh, "journal.csv"))
    t.ok("the first mark begins it: the manifest is told once, with the "
         "time of the first row", begun == ["2026-10-08T17:30:00.123Z"],
         begun)
    t.ok("and the rows that waited go out first, in order",
         [r["action"] for r in rows] == ["open", "view", "stroke"]
         and [r["seq"] for r in rows] == [1, 2, 3], rows)
    t.ok("the tool a map tool handed over is written",
         rows[2]["tool"] == "brush" and rows[2]["dur_ms"] == 4000)
    jh.note("class", module="objects", class_code=1)
    rows = rl.journal_read(os.path.join(fresh, "journal.csv"))
    t.ok("from then on every row goes out as it comes",
         len(rows) == 4 and rows[3]["module"] == "objects"
         and len(begun) == 1, rows[-1])
    quiet = os.path.join(root, "quiet")
    os.makedirs(quiet)
    jq = rl.Journal(quiet, "s", "annotate", held=True,
                    on_start=lambda j, f: begun.append(f))
    jq.note("open")
    jq.switch(False)
    jq.note("stroke")
    t.ok("switched off before the first mark: nothing kept, nothing begun",
         not jq.waiting and not os.path.exists(os.path.join(
             quiet, "journal.csv")) and len(begun) == 1)
    jq.switch(True)
    jq.note("stroke")
    t.ok("switched on again, the next mark begins it",
         len(rl.journal_read(os.path.join(quiet, "journal.csv"))) == 1
         and len(begun) == 2)

    print()
    print("today's active time, kept as the rows go by")
    day = datetime.now(timezone.utc)
    live = rl.Journal(os.path.join(root, "live"), "s", "annotate",
                      clock=Clock(0.0, 25.0, 50.0, 230.0, 240.0, 245.0,
                                  262.0, 400.0),
                      wall=lambda: day)
    os.makedirs(os.path.join(root, "live"))
    for action, dur, pauses in (("open", 0, ""), ("stroke", 15000, ""),
                                ("stroke", 10000, ""),
                                ("stroke", 100000, "20.0;75.0"),
                                ("focus_out", 0, ""), ("focus_in", 0, ""),
                                ("stroke", 12000, ""), ("close", 0, "")):
        live.note(action, timing=(dur, pauses), operator="MASSI",
                  tile_id="T1")
    # fixture S without its view row: 10 + 15 + 25 + 25 lead and draw for
    # c1, then the gap of 80 s before the long stroke is idle at 60 s, so
    # 25 of it, 10 to focus_out, 5 and 12 after it
    t.near("the gaps and strokes of the day at 60 s",
           live.active_today("MASSI"), 10 + 15 + 15 + 10 + 25 + 10 + 5 + 12)
    t.near("and the same on the frame",
           live.active_frame("MASSI", "T1"), live.active_today("MASSI"))
    t.ok("nobody else worked", live.active_today("ANNA") == 0)
    t.ok("the quiet line says it in minutes",
         rl.journal_line(live, "MASSI", "T1")
         == "active 1 min today · this frame 1 min",
         rl.journal_line(live, "MASSI", "T1"))
    t.ok("an hour and more as hours and minutes",
         rl.journal_duration_text(4320) == "1 h 12 min"
         and rl.journal_duration_text(360) == "6 min")
    live.seed({"MASSI": 3600.0}, {("MASSI", "T1"): 300.0})
    t.ok("earlier sessions of today are added",
         rl.journal_line(live, "MASSI", "T1").startswith("active 1 h 1 min"))
    t.ok("no journal, no line", rl.journal_line(None, "MASSI") == "")

    print()
    print("frames and Correct, through the names measure.py knows")
    wrote = []

    class Section(object):
        timing = (2500, "", "frame")

        def note(self, action, timing=None, **fields):
            wrote.append((action, timing, fields))
            return {"seq": len(wrote)}

        def pop_timing(self):
            timing, self.timing = self.timing, None
            return timing
    sec = Section()
    rl.journal_frame_event(sec, "new", "t003", None, (0, 0, 10, 20), None)
    t.ok("a frame placed is a frame_new row at its middle, with the time "
         "the frame tool handed over",
         wrote[-1][0] == "frame_new" and wrote[-1][1] == (2500, "", "frame")
         and wrote[-1][2]["x"] == 5.0 and wrote[-1][2]["y"] == 10.0
         and wrote[-1][2]["tile_id"] == "t003", wrote[-1])
    rl.journal_frame_event(sec, "delete", "t003", (0, 0, 10, 20), None, None)
    t.ok("deleted: frame_delete, at where it was",
         wrote[-1][0] == "frame_delete" and wrote[-1][2]["x"] == 5.0)
    t.ok("a section with no journal is left alone",
         rl.journal_frame_event(object(), "move", "t1", None, None, None)
         is None)
    fix = os.path.join(root, "fix")
    os.makedirs(fix)

    class Brush(object):
        def isChecked(self):
            return True

    class Correct(object):
        path = os.path.join(fix, "map_corrected.tif")
        b_round = Brush()
        timing = (6000, "", "round")

        def operator_name(self):
            return "ANNA"

    made = []

    def correction_journal(section):
        j = rl.Journal(os.path.dirname(section.path), "s9", "correct")
        made.append(j)
        return j
    space = rl.journal_borrow.__globals__
    space["time_correction_journal"] = correction_journal
    try:
        csec = Correct()
        hook = rl.CorrectJournalHook(csec)
        state = hook.stroke(csec, {"into": 4, "from_code": None,
                                   "pixels": 120, "changed_m2": 30.0,
                                   "x": 10.5, "y": 20.5, "n": 1,
                                   "place": None})
        hook.undo(csec, state)
        csec.note("refused", timing=(900, ""))
        hook.closing(csec)
    finally:
        space.pop("time_correction_journal", None)
    crows = rl.journal_read(os.path.join(fix, "journal.csv"))
    t.ok("Correct: open, the stroke, its undo, a refused one, close",
         [r["action"] for r in crows]
         == ["open", "correct", "undo", "refused", "close"],
         [r["action"] for r in crows])
    c = crows[1]
    t.ok("the stroke with its class, FROM 0 for any, pixels, ground, middle "
         "and its number in operations.csv",
         (c["class_code"], c["from_code"], c["pixels"], c["area_m2"],
          c["x"], c["y"], c["ref"], c["dur_ms"], c["tool"], c["operator"],
          c["pass_no"]) == ("4", "0", "120", "30", "10.5", "20.5", "1",
                            6000, "round", "ANNA", ""), c)
    t.ok("the time handed over is taken once", csec.timing is None)
    t.ok("the undo names the stroke it took back", crows[2]["ref"] == "1")
    t.ok("journal.csv is the correction's own file",
         hook.files(csec) == [os.path.join(fix, "journal.csv")])
    t.ok("and the line under the tally says the day",
         hook.tally_lines(csec)[0].startswith("active "))
    nobody = rl.CorrectJournalHook(Correct())
    t.ok("with no journal to be had the hook does nothing and says nothing",
         nobody.stroke(Correct(), {"n": 2}) == {"n": 2, "seq": None}
         and nobody.files(None) == [] and nobody.tally_lines(None) == [])

    print()
    print("what Check says of a journal")

    class Finding(object):
        def __init__(self, level, what, detail=""):
            self.level, self.what, self.detail = level, what, detail
    space["Finding"] = Finding

    class Owner(object):
        def __init__(self, folder, data):
            self.folder, self.data = folder, data
    try:
        empty = os.path.join(root, "never")
        os.makedirs(empty)
        t.ok("a campaign that never kept a journal: Check says nothing new",
             rl.journal_findings(Owner(empty, {})) == [])
        said = rl.journal_findings(Owner(fresh, {"journal": {
            "on": True, "file": "journal.csv", "version": 1,
            "since": "2026-10-08T17:30:00Z"}}))
        t.ok("one that does: its rows and sessions",
             len(said) == 1 and said[0].level == "ok"
             and "4 rows in 1 session" in said[0].what,
             [(f.level, f.what) for f in said])
        said = rl.journal_findings(Owner(empty, {"journal": {"on": True}}))
        t.ok("a block with no file is a note",
             [f.level for f in said] == ["note"]
             and "not there" in said[0].what)
        said = rl.journal_findings(Owner(fresh, {}))
        t.ok("a file with no block is a note too",
             "note" in [f.level for f in said])
        said = rl.journal_findings(Owner(empty, {"journal": {"on": False}}))
        t.ok("switched off says so", said and "switched off" in said[0].what)
        with io.open(os.path.join(fix, "operations.csv"), "w",
                     encoding="utf-8", newline="") as fh:
            fh.write("n,when,operator\n1,2026-10-08T10:00:00,ANNA\n"
                     "2,2026-10-08T10:00:20,ANNA\n")
        said = rl.journal_findings_correction(Owner(fix, {"journal": {
            "on": True, "file": "journal.csv"}}))
        t.ok("a correction: strokes of operations.csv with no journal row "
             "are a note", any(f.level == "note" and f.what.startswith(
                 "1 stroke of operations.csv") for f in said),
             [(f.level, f.what) for f in said])
    finally:
        space.pop("Finding", None)

    print()
    print("cheap, and whole after a crash")
    perf = os.path.join(root, "perf")
    os.makedirs(perf)
    jp = rl.Journal(perf, "p", "annotate")
    started = time.perf_counter()
    n = 500
    for i in range(n):
        jp.note("stroke", timing=(1200, ""), operator="ANNA", pass_no=1,
                tile_id="t001", class_code=1, area_m2=12.5, x=1.0, y=2.0)
    per_row = (time.perf_counter() - started) / n * 1000.0
    print("  %.3f ms per row, open, append and close included" % per_row)
    t.ok("a row costs well under the 50 ms a person could notice",
         per_row < 50.0, per_row)
    killed = os.path.join(root, "killed")
    os.makedirs(killed)
    child = ("import sys, os; sys.path.insert(0, %r); import purekit; "
             "rl = purekit.load('journal'); "
             "j = rl.Journal(%r, 'k', 'annotate'); "
             "[j.note('stroke', tile_id='t%%d' %% i) for i in range(5)]; "
             "os._exit(9)" % (HERE, killed))
    done = subprocess.run([sys.executable, "-c", child],
                          capture_output=True, timeout=120)
    back = rl.journal_read(os.path.join(killed, "journal.csv"))
    t.ok("a session killed with no clean up leaves every row it wrote, "
         "readable", done.returncode == 9 and len(back) == 5
         and back[-1]["tile_id"] == "t4", (done.returncode, len(back),
                                           done.stderr[-300:]))
finally:
    shutil.rmtree(root, ignore_errors=True)

t.done()
