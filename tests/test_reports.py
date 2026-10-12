"""Where a report goes and how its files are written.

The promises reports.py makes to every kind of report, checked on a
temporary folder:

- a report is written under <name>.tmp and only renamed when finished; two
  in the same second get -2; nothing is ever written over, and abandoning a
  run removes its .tmp folder and never a finished report;
- summary.json starts with the same header block every time, writes NaN as
  null, sorts its keys, and appears whole or not at all;
- a CSV is UTF-8 with no byte order mark, commas, "\\n", a dot for the
  decimals, %.12g for floats and an empty cell where a value is undefined;
- the manifest keeps the newest REPORTS_KEPT entries of each kind;
- a report is found only when its summary says it is of that kind and of
  that owner, and it is stale when a file it was made from has changed.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import purekit

rl = purekit.load("reports")
t = purekit.Checks()
root = tempfile.mkdtemp(prefix="rl_reports_")
owner = os.path.join(root, "aragona_2025")
os.makedirs(owner)

print("the measuring modules need neither QGIS nor GDAL")
for name in ("reports", "journal", "effort", "design"):
    plain, sibling = purekit.imports_of(name)
    t.ok("%s imports no QGIS, Qt or GDAL" % name, not [
        m for m in plain if m in ("qgis", "osgeo", "PyQt5", "PyQt6", "sip")],
        plain)
    t.ok("%s borrows only from the pure modules" % name, set(sibling) <= {
        "constants", "naming", "stats", "agreement", "reports"}, sibling)
# The card counts its pixels with the burning and voting that write the
# masks, so it reads GDAL; it still takes nothing from QGIS or Qt itself,
# and borrows only the modules that count (the text half is pure, and is
# tried without GDAL in test_card_text).
plain, sibling = purekit.imports_of("card")
t.ok("card imports no QGIS or Qt", not [
    m for m in plain if m in ("qgis", "PyQt5", "PyQt6", "sip")], plain)
t.ok("card borrows only the modules that count", set(sibling) <= {
    "constants", "naming", "stats", "agreement", "reports", "errors",
    "campaign", "rasters", "geometry", "correction"}, sibling)
print()

try:
    print("the folder of a report")
    when = datetime.datetime(2026, 10, 8, 19, 30, 5)
    tmp, final = rl.report_folder(owner, "agreement", "ANNA_p1_vs_BRUNO_p1",
                                  when)
    t.ok("reports/<kind>/<label>_<stamp>", final == os.path.join(
        owner, "reports", "agreement", "ANNA_p1_vs_BRUNO_p1_20261008-193005"),
        final)
    t.ok("written under .tmp first", tmp == final + ".tmp"
         and os.path.isdir(tmp) and not os.path.exists(final))
    tmp2, final2 = rl.report_folder(owner, "agreement", "ANNA_p1_vs_BRUNO_p1",
                                    when)
    t.ok("a second one in the same second gets -2",
         final2 == final + "-2", final2)
    rl.report_json(os.path.join(tmp, "summary.json"), {"x": 1})
    done = rl.report_finish(tmp, final)
    t.ok("finishing renames .tmp to the name", done == final
         and os.path.isdir(final) and not os.path.exists(tmp))
    tmp3, final3 = rl.report_folder(owner, "agreement", "ANNA_p1_vs_BRUNO_p1",
                                    when)
    t.ok("a finished name is never taken again", final3 not in (final,)
         and not final3.endswith("193005"), final3)
    t.ok("abandoning removes the .tmp", rl.report_abandon(tmp3)
         and not os.path.exists(tmp3))
    t.ok("and refuses a folder that is not a .tmp",
         rl.report_abandon(final) is False and os.path.isdir(final))
    rl.report_abandon(tmp2)
    tmp4, final4 = rl.report_folder(owner, "time", None, when)
    t.ok("no label: the stamp alone", os.path.basename(final4)
         == "20261008-193005", final4)
    os.makedirs(final4)
    t.ok("finishing onto a name taken meanwhile takes the next",
         rl.report_finish(tmp4, final4) == final4 + "-2")
    try:
        rl.report_folder(owner, "nonsense")
        t.ok("an unknown kind is refused", False)
    except ValueError:
        t.ok("an unknown kind is refused", True)
    t.ok("a label is made safe for a path",
         os.path.basename(rl.report_folder(owner, "card", "a b/c", when)[1])
         .startswith("a_b_c_"))
    t.ok("a map of a report names itself",
         rl.report_artifact_name("aragona_2025", "model_vs_corrected", "swept",
                                 "pairs", ".tif")
         == "aragona_2025_mvc_swept_pairs.tif")
    # Cut at 48 letters as one name, two long readings gave their
    # disagreement map and their map of pairs one name, cut before the part.
    long_label = "FIRST_LONG_OPERATOR_p1_vs_SECOND_LONG_OPERATOR_p2"
    names = [rl.report_artifact_name("aragona_2025_survey", "agreement",
                                     long_label, part, ".tif")
             for part in ("disagreement", "pairs")]
    t.ok("a long label is not cut, and each map keeps its part",
         names == ["aragona_2025_survey_agreement_%s_disagreement.tif"
                   % long_label,
                   "aragona_2025_survey_agreement_%s_pairs.tif" % long_label],
         names)
    huge = [rl.report_artifact_name("x" * 120, "agreement", "A" * 150 + tail,
                                    "disagreement", ".tif")
            for tail in ("_1", "_2")]
    t.ok("a name past the room keeps its part and its extension whole",
         all(len(n) <= 240 and n.endswith("_disagreement.tif")
             for n in huge), [len(n) for n in huge])
    t.ok("and two labels that differ only at the end stay two names",
         huge[0] != huge[1], huge)
    t.ok("the stem of a file on disk is kept as it is",
         rl.report_artifact_name("land cover.v2_corrected",
                                 "model_vs_corrected", "swept", "pairs",
                                 ".tif")
         == "land cover.v2_corrected_mvc_swept_pairs.tif")

    print()
    print("summary.json")
    h = rl.report_header("agreement", {"kind": "campaign", "id": "abc123",
                                       "name": "aragona_2025",
                                       "folder": owner})
    t.ok("the header keys", sorted(h) == sorted([
        "rasterlabel:report", "report_format", "program", "version", "build",
        "created_utc", "owner"]), sorted(h))
    t.ok("version 1.1, format 1, the build of this file",
         h["version"] == "1.1" and h["report_format"] == 1
         and h["build"] == rl.BUILD and len(h["build"]) == 8)
    t.ok("created in UTC with a Z", h["created_utc"].endswith("Z")
         and "T" in h["created_utc"])
    t.ok("owner id", h["owner"]["id"] == "abc123")
    path = os.path.join(root, "s.json")
    rl.report_json(path, dict(h, overall=float("nan"), n=3,
                              ci=(0.25, float("inf")), z={"b": 1, "a": 2}))
    text = io.open(path, encoding="utf-8").read()
    back = json.loads(text)
    t.ok("NaN and infinity written as null", back["overall"] is None
         and back["ci"] == [0.25, None])
    t.ok("keys sorted", text.index('"a"') < text.index('"b"'))
    t.ok("no .partial left behind", not os.path.exists(path + ".partial"))

    class Boom(object):
        pass
    try:
        rl.report_json(path, {"bad": Boom()})
    except TypeError:
        pass
    t.ok("a failed write leaves the old file whole and no .partial",
         json.loads(io.open(path, encoding="utf-8").read())["n"] == 3
         and not os.path.exists(path + ".partial"))

    print()
    print("CSV")
    csvp = os.path.join(root, "t.csv")
    rl.report_csv(csvp, ["code", "name", "iou", "n", "ok"],
                  [[1, "crater, big", 2 / 3, 10, True],
                   [2, "mud flow", float("nan"), None, False],
                   [3, "città", 1e-20, 12345678901234, False]])
    raw = open(csvp, "rb").read()
    t.ok("no byte order mark", not raw.startswith(b"\xef\xbb\xbf"))
    t.ok("\\n line ends, no \\r", b"\r" not in raw and raw.endswith(b"\n"))
    lines = raw.decode("utf-8").split("\n")
    t.ok("header once", lines[0] == "code,name,iou,n,ok")
    t.ok("floats %.12g with a dot, text quoted when it has a comma",
         lines[1] == '1,"crater, big",0.666666666667,10,1', lines[1])
    t.ok("undefined is an empty cell", lines[2] == "2,mud flow,,,0", lines[2])
    t.ok("UTF-8 text and small floats kept",
         lines[3] == "3,città,1e-20,12345678901234,0", lines[3])

    print()
    print("the manifest's list of reports")
    data = {}
    for i in range(55):
        rl.report_register(data, rl.report_entry(
            "agreement", "id%d" % i, "A_vs_B", "2026-10-08T17:%02d:00Z" % i,
            "reports\\agreement\\x%d" % i, {"overall": 0.5}))
    rl.report_register(data, rl.report_entry("time", "t1", "", "x",
                                             "reports/time/a", {}))
    kept = [e for e in data["reports"] if e["kind"] == "agreement"]
    t.ok("the newest REPORTS_KEPT of a kind are kept",
         len(kept) == rl.REPORTS_KEPT == 50 and kept[0]["id"] == "id5"
         and kept[-1]["id"] == "id54")
    t.ok("other kinds are untouched", rl.report_newest(data, "time")["id"]
         == "t1")
    t.ok("the newest of a kind", rl.report_newest(data, "agreement")["id"]
         == "id54")
    t.ok("folders with forward slashes", "\\" not in kept[0]["folder"])
    t.ok("no entry of a kind: None", rl.report_newest(data, "card") is None)
    t.ok("headline with exactly the fixed keys",
         sorted(rl.report_headline("time", {"idle_s": 60, "extra": 1}))
         == sorted(rl.REPORT_HEADLINES["time"]))
    t.ok("an entry whose folder is gone is listed", [
        e["id"] for e in rl.report_missing(
            {"reports": [rl.report_entry("agreement", "here", "", "",
                                         os.path.relpath(final, owner), {}),
                         rl.report_entry("agreement", "gone", "", "",
                                         "reports/agreement/nope", {})]},
            owner)] == ["gone"])
    t.ok("one quiet line about an entry", rl.report_describe(
        kept[-1]).startswith("agreement A vs B, 2026-10-08 17:54"))

    print()
    print("finding a report again")
    package = os.path.join(owner, "annotation.gpkg")
    with open(package, "wb") as fh:
        fh.write(b"first")
    inputs = rl.report_inputs([package, os.path.join(owner, "nope.gpkg")])
    t.ok("inputs: sha256, bytes, mtime",
         inputs[0]["sha256"] == rl.report_sha256(package)
         and inputs[0]["bytes"] == 5 and inputs[0]["mtime_utc"].endswith("Z"))
    t.ok("a missing input is listed with nulls", inputs[1]["sha256"] is None)

    def make(kind, owner_id, label, stamp, summary_kind=None):
        tmp_, fin_ = rl.report_folder(owner, kind, label, stamp)
        s = rl.report_header(summary_kind or kind,
                             {"kind": "campaign", "id": owner_id})
        s["created_utc"] = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        s["inputs"] = rl.report_inputs([package])
        rl.report_json(os.path.join(tmp_, "summary.json"), s)
        return rl.report_finish(tmp_, fin_)

    older = make("agreement", "abc123", "x", datetime.datetime(2026, 1, 1))
    newer = make("agreement", "abc123", "y", datetime.datetime(2026, 2, 1))
    make("agreement", "other", "z", datetime.datetime(2026, 3, 1))
    make("agreement", "abc123", "w", datetime.datetime(2026, 4, 1), "time")
    os.makedirs(os.path.join(owner, "reports", "agreement", "v.tmp"))
    found = rl.report_find(owner, "agreement", "abc123")
    t.ok("only this owner's reports of this kind, newest first",
         [f for f, _ in found] == [newer, older], [f for f, _ in found])
    t.ok("nothing of a kind never made", rl.report_find(owner, "card",
                                                        "abc123") == [])
    summary = found[0][1]
    stale, why = rl.report_stale(summary, rl.report_inputs([package]))
    t.ok("the same package: not stale", stale is False, why)
    time.sleep(0.05)
    with open(package, "wb") as fh:
        fh.write(b"second")
    stale, why = rl.report_stale(summary, rl.report_inputs([package]))
    t.ok("a changed package: stale, and why", stale and "changed" in why, why)
    moved = os.path.join(root, "elsewhere", "annotation.gpkg")
    os.makedirs(os.path.dirname(moved))
    shutil.copy(package, moved)
    stale, why = rl.report_stale(summary, rl.report_inputs([moved]))
    t.ok("matched by name when the campaign has moved", stale, why)
    nosha = dict(summary, inputs=[dict(summary["inputs"][0], sha256=None,
                                       mtime_utc="2000-01-01T00:00:00Z")])
    t.ok("no sha recorded: the mtime decides",
         rl.report_stale(nosha, rl.report_inputs([package]))[0])
    os.remove(package)
    t.ok("a file that is gone makes it stale",
         rl.report_stale(summary, rl.report_inputs([package]))[0])

    print()
    print("what a report says of the place of its files")
    with open(package, "wb") as fh:
        fh.write(b"third")
    own = rl.report_inputs([package], owner)
    t.ok("a file inside the folder of the report is named from it",
         own[0]["path"] == "annotation.gpkg", own[0]["path"])
    t.ok("with the numbers of the file all the same",
         own[0]["sha256"] == rl.report_sha256(package) and own[0]["bytes"] == 5)
    outside = rl.report_inputs([moved], owner)
    t.ok("one outside it keeps its path", outside[0]["path"] == moved,
         outside[0]["path"])
    t.ok("a missing one is named the same way",
         rl.report_inputs([os.path.join(owner, "nope.gpkg")],
                          owner)[0]["path"] == "nope.gpkg")
    shown = dict(summary, inputs=own)
    t.ok("a report that names its input from the folder still knows it is "
         "the same file", rl.report_stale(shown, rl.report_inputs([package]))
         == (False, ""), rl.report_stale(shown, rl.report_inputs([package])))
    with open(package, "wb") as fh:
        fh.write(b"fourth")
    t.ok("and when it has changed",
         rl.report_stale(shown, rl.report_inputs([package]))[0])
    home = os.path.expanduser("~")
    homed = os.path.join(root, "homed.json")
    rl.report_json(homed, {"owner": {"folder": os.path.join(home, "work", "c")},
                           "list": [home + os.sep + "x.tif"],
                           "note": "home is " + home})
    text = io.open(homed, encoding="utf-8").read()
    t.ok("the home folder of whoever wrote a summary is not in it",
         home not in text and home.replace("\\", "\\\\") not in text
         and "~" in text, text)
    kept = json.loads(text)
    t.ok("and the path under it reads ~ and then the rest",
         kept["owner"]["folder"].startswith("~")
         and kept["owner"]["folder"].endswith("c"), kept["owner"]["folder"])
finally:
    shutil.rmtree(root, ignore_errors=True)

t.done()
