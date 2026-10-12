"""rasterlabel.reports

Where a report goes, how its files are written, and how a campaign or a
correction keeps track of the reports made of it.

Every report (agreement, time, model vs corrected, uncertainty, the card)
goes in a folder of its own:

    <owner>/reports/<kind>/<label>_<YYYYmmdd-HHMMSS>/

It is written under the same name ending in .tmp and renamed when the last
file is in, so a folder without that ending is always a whole report and a
cancelled or failed run leaves nothing that looks like one. Nothing is ever
written over: two reports in the same second get -2, -3 after the stamp. A
file loaded in QGIS on Windows cannot be replaced, and a report that
replaced the one a reader was looking at would be a report nobody could
trust anyway.

Inside, the tables and the summary have short fixed names (summary.json,
per_class.csv...). The CSV files are UTF-8 with no byte order mark, commas,
"\\n" at the end of each line and a dot for the decimals, whatever the
machine's locale says, with an undefined value left as an empty cell; the
JSON files write it as null. Both are written to a .partial file first and
moved into place with os.replace, so a reader never sees half of one.

Standard library only, plus the program's constants and naming; no QGIS and
no GDAL.
"""
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil

from datetime import datetime, timezone

from .constants import (BUILD, NAME, REPORT_FORMAT, REPORT_HEADLINES,
                        REPORT_SHORT, REPORT_SUMMARY, REPORT_TMP,
                        REPORTS_FOLDER, REPORTS_KEPT, VERSION)
from .naming import csv_text, inside_folder, long_path, tidy, without_home


def report_utc(when=None):
    """A moment as UTC ISO text to the second, with a Z: 2026-10-08T17:30:00Z."""
    when = when or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.astimezone(timezone.utc)
    return when.astimezone(timezone.utc).replace(microsecond=0) \
        .isoformat().replace("+00:00", "Z")


def report_stamp(when=None):
    """The stamp in a report's folder name, local time: 20261008-1930 to the
    second, 20261008-193005, so two runs a minute apart do not collide."""
    return (when or datetime.now()).strftime("%Y%m%d-%H%M%S")


def report_stem(label=None, when=None):
    """<label>_<stamp>, or the stamp alone: the name a report folder starts
    from, before a -2 is added to it."""
    stem = report_stamp(when)
    if label:
        stem = "%s_%s" % (tidy(str(label), "report"), stem)
    return stem


def report_folder(owner_folder, kind, label=None, when=None):
    """(tmp, final) for a new report of this kind, with tmp made and empty.

    final does not exist and nothing ending in .tmp under that name does
    either: the first free one of <label>_<stamp>, <label>_<stamp>-2, and so
    on. The caller writes into tmp, then calls report_finish(tmp, final), or
    report_abandon(tmp) when the run fails or is cancelled."""
    if kind not in REPORT_SHORT:
        raise ValueError("%r is not a kind of report" % (kind,))
    base = os.path.join(owner_folder, REPORTS_FOLDER, kind)
    stem = report_stem(label, when)
    for n in range(1, 1000):
        name = stem if n == 1 else "%s-%d" % (stem, n)
        final = os.path.join(base, name)
        tmp = final + REPORT_TMP
        if os.path.exists(long_path(final)) or os.path.exists(long_path(tmp)):
            continue
        try:
            os.makedirs(long_path(tmp))
        except FileExistsError:
            continue
        return tmp, final
    raise OSError("no free name for a report in %s" % base)


# QGIS opens a GeoPackage through SQLite, and SQLite on Windows cannot open a
# path of 260 characters or more, the long form with the \\?\ prefix that
# GDAL writes it through included: probed on QGIS 3.36, 3.44 and 4.2, the file was written and the
# layer then said it was not valid ("sqlite3_open ... unable to open
# database file"). A GeoTIFF, a GeoJSON and a .qml are opened through GDAL
# and Qt, which reach past 260 characters, and give no trouble. The 8.3 name
# of a folder would get round it, but only on a volume that keeps them, and
# a report that loads on one machine and not on another is worse than one
# that says at once where it cannot go.
SQLITE_FILES = (".gpkg", ".sqlite", ".sqlite3", ".db")
WINDOWS_PATH_MAX = 259
# SQLite keeps a side file beside the one it opens: -wal and -shm, or, when
# QGIS edits a GeoPackage through a rollback journal as 3.36 does,
# -journal, eight characters more. Start editing and Save edits on a path
# that left no room for it failed with "unable to open database file", the
# layer having loaded and read well. A report that finds its name taken is
# finished as <name>-2... -99: three more in the folder's name, which the
# name of the file is under.
SQLITE_SIDE_FILES = len("-journal")
REPORT_RENUMBER = len("-99")


def report_folder_guess(owner_folder, kind, label=None, target=None,
                        when=None):
    """Where a report is going to end up, as far as it can be known before
    anything is made: the folder the person named, or the one report_folder
    would make. A name taken in the meantime adds -2, which report_open_
    problem leaves room for."""
    if target:
        return str(target)
    return os.path.join(owner_folder, REPORTS_FOLDER, kind,
                        report_stem(label, when))


def report_open_problem(folder, names, windows=None):
    """"" if QGIS will be able to open every one of the files named in this
    folder, or, in plain words, why it will not and what to do.

    names are the files the report is to write and QGIS is to load. Only a
    SQLite file (a GeoPackage) is held to a length, and only on Windows;
    windows=True asks the question as Windows answers it, which is how the
    suites ask it on a machine that is not one."""
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return ""
    room = WINDOWS_PATH_MAX - SQLITE_SIDE_FILES - REPORT_RENUMBER
    worst = None
    for name in names or []:
        if os.path.splitext(str(name))[1].lower() not in SQLITE_FILES:
            continue
        n = len(os.path.join(os.path.abspath(str(folder)), str(name)))
        if n > room and (worst is None or n > worst[0]):
            worst = (n, str(name))
    if worst is None:
        return ""
    return ("The GeoPackage of this report, %s, would be at %d characters of "
            "path, and QGIS cannot open and edit one of more than %d on "
            "Windows: the layers would not load, or could not be edited. "
            "Choose a shorter folder for the report, "
            "or move the campaign closer to the root of the drive, %d "
            "characters shorter at least."
            % (worst[1], worst[0], room, worst[0] - room))


def report_finish(tmp, final):
    """Put a complete report in place, and return where it went.

    A folder that took the name in the meantime (another QGIS on the same
    campaign) is left alone, and the report takes the next free name."""
    target = final
    n = 1
    while os.path.exists(long_path(target)):
        n += 1
        target = "%s-%d" % (final, n)
    os.rename(long_path(tmp), long_path(target))
    return target


def report_abandon(tmp):
    """Remove a report that was not finished. Only a folder whose name ends
    in .tmp is ever removed here: a finished report is never touched."""
    if not tmp or not str(tmp).endswith(REPORT_TMP):
        return False
    if os.path.isdir(long_path(tmp)):
        shutil.rmtree(long_path(tmp), ignore_errors=True)
    return not os.path.exists(long_path(tmp))


def _report_piece(text):
    """One piece of the name of a map of a report, made safe for a path
    and never cut: [^A-Za-z0-9_-] runs become one _, as tidy() does."""
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", str(text or "")).strip("_")


# The longest name a map of a report is given, its extension included: a
# file name may not pass 255 characters on Windows, macOS or Linux, and a
# little room is left for the .aux.xml GDAL writes beside a raster.
REPORT_NAME_ROOM = 240


def report_artifact_name(owner_stem, kind, label, part, ext):
    """The name of a raster or a vector of a report.

    <owner stem>_<kind short>_<label>_<part><ext>: the tables inside a
    report folder have short fixed names, but a map is copied out, into a
    paper's figure folder or a colleague's QGIS, and there it has to say
    what it is on its own.

    It is never cut at a fixed length. Sending the whole through tidy(),
    which stops at 48 letters, would give two long readings one name for their
    disagreement map and their map of pairs, cut before _disagreement and
    _pairs. The owner's stem is the stem of a file already on disk, and is
    kept as it is; the label and the part are made safe for a path. Only a
    name that would not fit in REPORT_NAME_ROOM loses the end of its label,
    which is then followed by eight letters of its SHA-1, so two labels
    never meet in one name, and the part and the extension are always
    whole."""
    stem = str(owner_stem or "") or kind
    head = [stem, REPORT_SHORT.get(kind, kind)]
    label = _report_piece(label)
    tail = [_report_piece(part)] if _report_piece(part) else []
    name = "_".join(head + ([label] if label else []) + tail) + ext
    if len(name) <= REPORT_NAME_ROOM or not label:
        return name
    # a mark in a file name, no security (see tidy_tag)
    mark = hashlib.sha1(label.encode("utf-8"),
                        usedforsecurity=False).hexdigest()[:8]
    room = REPORT_NAME_ROOM - (len(name) - len(label)) - len(mark) - 1
    short = label[:max(room, 1)].rstrip("_-") or label[:1]
    return "_".join(head + ["%s_%s" % (short, mark)] + tail) + ext


def report_header(kind, owner):
    """The block every summary.json starts with.

    owner is {kind: campaign|correction, id, name, folder}. The build is the
    fingerprint of the bytes that wrote the report, which is what a reader
    needs to find the exact code again."""
    return {"rasterlabel:report": kind, "report_format": REPORT_FORMAT,
            "program": NAME, "version": VERSION, "build": BUILD,
            "created_utc": report_utc(),
            "owner": {"kind": owner.get("kind", ""),
                      "id": owner.get("id", ""),
                      "name": owner.get("name", ""),
                      "folder": owner.get("folder", "")}}


def report_sha256(path, chunk=1 << 20):
    """The SHA-256 of a file, read a MiB at a time, or None if it cannot be
    read."""
    digest = hashlib.sha256()
    try:
        with open(long_path(path), "rb") as fh:
            while True:
                block = fh.read(chunk)
                if not block:
                    break
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def report_inputs(paths, folder=None):
    """What a report was made from: path, sha256, bytes and mtime of each.

    A file that is not there is listed with null in place of the numbers, so
    the summary says it was looked for.

    With folder, the one the report is written for, a file inside it is named
    by its way from there: a summary that is zipped and sent does not carry
    the name of whoever made it in every line. Without it the whole path,
    which is what the files as they are now are compared with."""
    out = []
    for p in paths:
        shown = inside_folder(p, folder) if folder else p
        try:
            st = os.stat(long_path(p))
            out.append({"path": shown, "sha256": report_sha256(p),
                        "bytes": int(st.st_size),
                        "mtime_utc": report_utc(datetime.fromtimestamp(
                            st.st_mtime, timezone.utc))})
        except OSError:
            out.append({"path": shown, "sha256": None, "bytes": None,
                        "mtime_utc": None})
    return out


def report_clean(obj):
    """obj made fit for JSON: NaN and infinity as None, tuples as lists,
    sets sorted, numpy numbers as Python ones (through their .item())."""
    if isinstance(obj, dict):
        return {str(k): report_clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [report_clean(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return [report_clean(v) for v in sorted(obj, key=str)]
    if hasattr(obj, "tolist") and not isinstance(obj, (str, bytes)):
        return report_clean(obj.tolist())
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        obj = obj.item()
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    return obj


def report_cell(value):
    """One CSV cell: empty for None and NaN, floats as %.12g, the rest as
    text. Booleans are written 1 and 0, which every reader takes."""
    if value is None:
        return ""
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return "%.12g" % value if math.isfinite(value) else ""
    return csv_text(str(value))


def _report_replace(path, write):
    """Write through a .partial beside path, then move it into place."""
    partial = path + ".partial"
    try:
        write(partial)
        os.replace(long_path(partial), long_path(path))
    except BaseException:
        try:
            os.remove(long_path(partial))
        except OSError:
            pass
        raise
    return path


def report_csv(path, header, rows):
    """A table as CSV, atomically, in the conventions above."""
    def write(target):
        with io.open(long_path(target), "w", encoding="utf-8",
                     newline="") as fh:
            out = csv.writer(fh, lineterminator="\n")
            if header:
                out.writerow([csv_text(str(h)) for h in header])
            for row in rows:
                out.writerow([report_cell(v) for v in row])
    return _report_replace(path, write)


def report_homeless(obj):
    """obj with the home folder of whoever is running written ~ in every
    text: a report is zipped and sent, and the folders it names (the owner's,
    a source map's) are under it."""
    if isinstance(obj, dict):
        return {k: report_homeless(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [report_homeless(v) for v in obj]
    if isinstance(obj, str):
        return without_home(obj)
    return obj


def report_json(path, obj):
    """obj as JSON, atomically: NaN as null, keys sorted, one space indent."""
    text = json.dumps(report_homeless(report_clean(obj)), sort_keys=True,
                      indent=1,
                      ensure_ascii=False, allow_nan=False) + "\n"
    return report_text(path, text)


def report_text(path, text):
    """Text as a UTF-8 file with "\\n" line ends, atomically."""
    def write(target):
        with io.open(long_path(target), "w", encoding="utf-8",
                     newline="\n") as fh:
            fh.write(text)
    return _report_replace(path, write)


def report_headline(kind, values):
    """The headline of a report, with exactly the keys fixed for its kind.

    A key the writer did not give is there as None; a key it gave that is
    not on the list is left out, so the card can rely on the shape."""
    keys = REPORT_HEADLINES.get(kind, ())
    return {k: values.get(k) for k in keys}


def report_entry(kind, report_id, label, created_utc, folder, headline):
    """One entry of data["reports"]: what the manifest remembers of a report.

    folder is relative to the owner's folder, with forward slashes, so the
    entry still points at the report after the whole campaign is moved."""
    return {"kind": kind, "id": report_id, "label": label or "",
            "created_utc": created_utc,
            "folder": str(folder).replace("\\", "/"),
            "headline": report_clean(headline or {})}


def report_register(data, entry, kept=REPORTS_KEPT):
    """Add entry to data["reports"], keeping the newest kept of its kind.

    The manifest is the campaign's or the correction's, and the caller saves
    it the usual way (Campaign.save, CorrectionCampaign.save). The report
    folders themselves are never removed here: only the list is trimmed."""
    reports = data.setdefault("reports", [])
    reports.append(entry)
    same = [i for i, e in enumerate(reports) if e.get("kind") == entry["kind"]]
    drop = set(same[:max(0, len(same) - kept)])
    data["reports"] = [e for i, e in enumerate(reports) if i not in drop]
    return entry


def report_newest(data, kind):
    """The newest entry of this kind in data["reports"], or None."""
    found = [e for e in data.get("reports") or [] if e.get("kind") == kind]
    return found[-1] if found else None


def report_missing(data, owner_folder):
    """The entries of data["reports"] whose folder is not there any more."""
    out = []
    for e in data.get("reports") or []:
        rel = e.get("folder") or ""
        if not rel or not os.path.isdir(long_path(
                os.path.join(owner_folder, *rel.split("/")))):
            out.append(e)
    return out


def report_read(path):
    """A summary.json read back, or None when it is missing or not JSON."""
    try:
        with io.open(long_path(path), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def report_find(owner_folder, kind, owner_id, name=REPORT_SUMMARY):
    """The finished reports of this kind made of this owner, newest first.

    Each is (folder, summary). A report counts only when its summary says it
    is of this kind and was made of the owner with this id: a folder copied
    in from another campaign, or a file somebody named summary.json, is not
    mistaken for one. Folders still ending in .tmp are not finished and are
    skipped."""
    base = os.path.join(owner_folder, REPORTS_FOLDER, kind)
    try:
        names = os.listdir(long_path(base))
    except OSError:
        return []
    found = []
    for n in names:
        if n.endswith(REPORT_TMP):
            continue
        folder = os.path.join(base, n)
        summary = report_read(os.path.join(folder, name))
        if not isinstance(summary, dict):
            continue
        if summary.get("rasterlabel:report") != kind:
            continue
        if (summary.get("owner") or {}).get("id") != owner_id:
            continue
        found.append((summary.get("created_utc") or "", n, folder, summary))
    found.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [(folder, summary) for _, _, folder, summary in found]


def _report_same_path(a, b):
    # ~ is the home folder the report was written with (see report_homeless)
    norm = lambda p: os.path.normcase(os.path.normpath(os.path.abspath(
        os.path.expanduser(p))))
    return norm(a) == norm(b)


def _report_way_ends(current, way):
    """Whether the file current is at the end of way, a path a report wrote
    down relative to the folder it was made for."""
    if not way or os.path.isabs(way) or way.startswith("~"):
        return False
    tail = os.path.normcase(os.path.normpath(way))
    full = os.path.normcase(os.path.normpath(current))
    return full.endswith(os.sep + tail)


def report_stale(summary, current):
    """(stale, reason): whether the files a report was made from have changed.

    current lists the files as they are now, in the shape of report_inputs.
    An input whose sha256 was recorded is stale when the sha differs; one
    recorded without a sha is compared by mtime. A file matched by full path
    first, by name second, so a campaign moved to another disk is still
    recognised. An input that is now missing makes the report stale too."""
    now = list(current or [])
    for old in (summary or {}).get("inputs") or []:
        path = old.get("path") or ""
        match = [c for c in now if _report_same_path(c.get("path", ""), path)
                 or _report_way_ends(c.get("path", ""), path)]
        if not match:
            base = os.path.basename(path)
            match = [c for c in now
                     if os.path.basename(c.get("path", "")) == base]
        if not match:
            continue
        cur = match[0]
        if cur.get("sha256") is None and cur.get("mtime_utc") is None:
            return True, "%s is not there any more" % os.path.basename(path)
        if old.get("sha256") and cur.get("sha256"):
            if old["sha256"] != cur["sha256"]:
                return True, "%s has changed since" % os.path.basename(path)
            continue
        if old.get("mtime_utc") and cur.get("mtime_utc") \
                and cur["mtime_utc"] > old["mtime_utc"]:
            return True, "%s is newer than the report" % os.path.basename(path)
    return False, ""


def report_describe(entry):
    """One quiet line about a report entry, for a tally or a tooltip."""
    when = (entry.get("created_utc") or "").replace("T", " ").rstrip("Z")
    words = entry.get("kind", "report").replace("_", " ")
    if entry.get("label"):
        words += " " + str(entry["label"]).replace("_", " ")
    return "%s, %s UTC" % (words, when[:16]) if when else words
