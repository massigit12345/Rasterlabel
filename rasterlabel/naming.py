"""rasterlabel.naming

Turning a word into something safe to put in a path.
"""
import hashlib
import os
import re
import sys

from datetime import datetime


def now():
    return datetime.now().isoformat(timespec="seconds")


def sql_text(s):
    """A string inside a QGIS expression, with the quotes doubled.

    The operator box can be typed into. A name carrying an apostrophe would
    leave the renderer expression syntactically broken, and a broken filter in
    QGIS hides nothing at all: everything would come into view at the one
    moment when nothing should.

    The backslash is doubled too, and first, because inside a QGIS string a
    backslash escapes the character after it: a frame or an operator ending
    in one swallowed the closing quote and broke the filter just the same.
    This is for QGIS expressions only. SQLite, which is what OGR hands a where
    clause on a GeoPackage to, does not escape with a backslash, and there the
    apostrophe alone is doubled (see export.py)."""
    return "'" + str(s).replace("\\", "\\\\").replace("'", "''") + "'"


def glob_like(folder, stem):
    """True if anything in the folder already starts with this name.

    Not just one file: a cutout is a family, the image, the mask, the pictures
    and the STAC item, and any one of them being there means the name is spoken
    for. A folder that cannot be listed is treated as occupied, because writing
    into a folder we cannot read is how things get overwritten."""
    try:
        for entry in os.listdir(long_path(folder)):
            if entry == stem or entry.startswith(stem + "_") \
                    or entry.startswith(stem + "."):
                return True
    except OSError:
        return True
    return False


def long_path(path):
    """The path in the form Windows lets Python reach past 260 characters.

    GDAL opens and writes long paths through the wide Windows calls, so a
    cutout in a deep folder, or with long layer names in its file names, did
    land on disk. Python's own os.path.exists() then said it was not there,
    the cutout was reported as "not written" and abandoned, and the file it
    had just written stayed behind, belonging to nothing. The \\\\?\\ prefix
    is how Windows is asked to skip the limit; everywhere else, and for a
    path that is short enough, the path comes back as it was."""
    if os.name != "nt" or not path:
        return path
    full = os.path.abspath(path)
    if len(full) < 248 or full.startswith("\\\\?\\"):
        return path
    if full.startswith("\\\\"):
        return "\\\\?\\UNC\\" + full[2:]
    return "\\\\?\\" + full


def guess_role(layer):
    """One band, or a band that calls itself classes, means a class map."""
    provider = layer.dataProvider()
    for b in range(1, provider.bandCount() + 1):
        if "class" in provider.generateBandName(b).lower():
            return "classes"
    return "classes" if provider.bandCount() == 1 else "image"


def tidy(text, fallback="layer"):
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", text).strip("_")[:48] or fallback


def tidy_tag(text, fallback="layer", room=48):
    """tidy() for a layer's name that ends up inside the name of a file.

    Cut at 48 letters a long name lost its end, and the end is what tells one
    layer from another: "..._disag_classes" and "..._disag_probabilities",
    two maps of one model, became one name. A name that fits is as tidy()
    makes it. A longer one keeps its beginning, so it can still be
    recognised, and its last words whole (the role, the class, the year, the
    number), and gives up its middle for six letters of the SHA-1 of the whole
    name, so that two names never meet in one. The result is room letters at
    most. room is for a tag already made and being read back, which must come
    back as it was."""
    whole = re.sub(r"[^A-Za-z0-9_\-]+", "_", text).strip("_")
    if len(whole) <= room:
        return whole or fallback
    # a mark in a file name, no security: usedforsecurity says so to the
    # scanners that read every SHA-1 as a weak password hash
    mark = hashlib.sha1(whole.encode("utf-8"),
                        usedforsecurity=False).hexdigest()[:6]
    tail = whole[-(room // 2):]
    # begin the ending at a word: the first separator in it, if there is one
    seps = [i for i, ch in enumerate(tail) if ch in "_-"]
    tail = tail[seps[0]:] if seps else "_" + tail
    head = whole[:max(1, room - len(mark) - 1 - len(tail))].rstrip("_-")
    return "%s-%s%s" % (head or whole[:1], mark, tail)


def source_of(layer):
    return layer.source().split("|")[0]


#  Text that leaves the program
# =====================================================================
# A spreadsheet reads a cell that begins with one of these as a formula, and
# runs it: a class called =HYPERLINK(...) in a table somebody opens in Excel
# is code, not a name.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_PLAIN_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


def csv_text(value):
    """What a CSV cell may say: a text that a spreadsheet would run as a
    formula gets a single quote in front, which spreadsheets drop on display
    and which keeps the cell a piece of text.

    Only text is touched. A number, whether it comes as a number or as the
    digits of one ("-0.25", "1e-3"), is left as it is: a negative coordinate
    must stay a number, and the column of them is read back as such. Anything
    that is not a string comes back unchanged."""
    if isinstance(value, str) and value.startswith(_FORMULA_START) \
            and not _PLAIN_NUMBER.match(value.strip()):
        return "'" + value
    return value


def csv_untext(value):
    """The text as it was before csv_text put a quote in front of it, for a
    reader that compares a cell with a name it holds."""
    if isinstance(value, str) and value[:1] == "'" \
            and value[1:2] in _FORMULA_START \
            and not _PLAIN_NUMBER.match(value[1:].strip()):
        return value[1:]
    return value


def csv_untext_row(row):
    """A row read back from a CSV as a dict, every cell as csv_text found it
    before it was written."""
    return {k: csv_untext(v) for k, v in row.items()}


def ctrl_name():
    """The name of the key Qt calls Ctrl, as the person at the keyboard sees
    it: on a Mac Qt maps Ctrl to the Command key, and "Ctrl+click" printed
    there names a key that does nothing."""
    return "Cmd" if sys.platform == "darwin" else "Ctrl"


def home_folder():
    """The home folder of whoever runs the program, or "" when it cannot be
    told apart from nothing: a home that is a drive root or a bare ~ would
    turn every path into one inside it."""
    home = os.path.expanduser("~")
    if not home or home == "~":
        return ""
    full = os.path.abspath(home)
    return "" if os.path.dirname(full) == full else home


def home_rest(path):
    """What follows the home folder in a path that lies in it, with forward
    slashes ("" for the home folder itself); None for a path anywhere else,
    or on another drive."""
    home = home_folder()
    if not home or not path:
        return None
    try:
        full = os.path.abspath(path)
        base = os.path.abspath(home)
        if os.path.commonpath([os.path.normcase(full),
                               os.path.normcase(base)]) \
                != os.path.normcase(base):
            return None
        rel = os.path.relpath(full, base)
    except ValueError:
        return None
    return "" if rel == "." else rel.replace(os.sep, "/")


def with_tilde(path):
    """A path under the home folder written from it as ~/maps/a.tif, which
    reads back on any machine and does not say whose it is; any other path as
    it was. A layer name after a bar is kept."""
    head, bar, tail = str(path).partition("|")
    if not head or "://" in head or not os.path.isabs(head):
        return path
    rest = home_rest(head)
    if rest is None:
        return path
    return "~" + ("/" + rest if rest else "") + bar + tail


# What QGIS and GDAL write into the text of a source that is not a file: the
# secrets are keys of a key=value list (PostGIS, ODBC), of a query (a tile
# server, a WMS) or of the link itself (user:password@host). authcfg is the id
# of a stored configuration and says nothing; it is kept. The = is written
# bare, as these sources have it: a line of code in a traceback that reads
# signature = (what, err) is not a login.
_LOGIN_KEYS = (r"password|passwd|pwd|user|username|uid|login|token|"
               r"access_token|auth_token|api_key|api-key|apikey|secret|"
               r"client_secret|signature|sig")
_LOGIN_PAIR = re.compile(
    r"(?P<lead>^|[\s&?;,|]|%26|%3F)(?P<key>" + _LOGIN_KEYS + r")"
    r"(?:=|%3D)"
    r"(?:'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.)*\"|(?:(?!%26)[^\s&'\"])*)",
    re.IGNORECASE)
_LOGIN_LINK = re.compile(
    r"(://)[^/\s'\"?#@]+@|(%3A%2F%2F)(?:(?!%2F)[^\s'\"&@])+%40",
    re.IGNORECASE)
# a file read through GDAL's virtual file systems: /vsizip/ and the path
_VSI_NAME = re.compile(r"((?:/vsi[a-z0-9_]+/)+)(.*)$",
                       re.IGNORECASE | re.DOTALL)


def clean_source(text):
    """The text of a layer source that is not a file, or any text that may
    quote one, without what logs a person in: password=, user=, username=,
    token= and the like, and user:password@ in a link. For a source written
    into a manifest or a dataset that is shared. A file inside a /vsi... name
    under the home folder is written from ~ as a file is."""
    if not isinstance(text, str) or not text:
        return text
    found = _VSI_NAME.match(text)
    if found and "://" not in found.group(2):
        inner = found.group(2).split("|")[0]
        rest = home_rest(inner) if os.path.isabs(inner) else None
        if rest is not None:
            text = found.group(1) + "~" + ("/" + rest if rest else "") \
                + found.group(2)[len(inner):]
    if "=" not in text and "@" not in text and "%3D" not in text.upper() \
            and "%40" not in text:
        return text

    def drop(m):
        # the separator goes with its pair, except a line break and the ? that
        # opens a query
        lead = m.group("lead")
        return lead if lead in ("\n", "\r", "?", "%3F", "%3f") else ""

    cleaned = _LOGIN_PAIR.sub(drop, text)
    cleaned = _LOGIN_LINK.sub(lambda m: m.group(1) or m.group(2), cleaned)
    if cleaned != text:
        cleaned = re.sub(r"\?&+", "?", cleaned)
    return cleaned


def inside_folder(path, folder):
    """The path relative to the folder, with forward slashes, when it lies
    inside the folder; elsewhere under the home folder it is written from ~
    (~/maps/a.tif); the path as it was when it is neither (or when it is not
    a path, or the two are on different drives).

    This is what a manifest stores for a file that lives in its own folder,
    so the folder can be moved, zipped or shared whole without the name of
    the person who made it in every line."""
    if not path or not folder:
        return path
    head, bar, tail = str(path).partition("|")
    if "://" in head or not os.path.isabs(head):
        return clean_source(path)   # a service, a table, a name: not a file here
    try:
        full = os.path.normcase(os.path.abspath(head))
        base = os.path.normcase(os.path.abspath(folder))
        if full == base or os.path.commonpath([full, base]) != base:
            return with_tilde(path)
        rel = os.path.relpath(os.path.abspath(head), os.path.abspath(folder))
    except ValueError:
        return with_tilde(path)
    if home_rest(folder) is None and home_rest(head) is not None:
        return with_tilde(path)     # the way down would spell the home folder
    return rel.replace(os.sep, "/") + bar + tail


def beside_folder(path, folder):
    """The way from the folder to the path, with forward slashes, for a file
    inside the folder or elsewhere on the same drive (../../maps/a.tif); the
    path as it was when it is not a file here, or the two share no drive.

    This is what a manifest stores for the map it was made from, which is
    usually not in its folder. The way up and down does not carry the name of
    the person who made the campaign only while it stays inside their home
    folder, so it is not written when it would leave it: a file under the home
    folder, seen from a folder outside it, is written from ~ (~/maps/a.tif);
    a file outside the home folder, seen from a folder inside it, keeps its
    whole path, which has no home in it. A source that is not a file loses
    its passwords and user names (clean_source)."""
    if not path or not folder:
        return path
    head, bar, tail = str(path).partition("|")
    if "://" in head or head.startswith("/vsi") or not os.path.isabs(head):
        return clean_source(path)
    mine, there = home_rest(head), home_rest(folder)
    if mine is not None and there is None:
        return with_tilde(path)
    if mine is None and there is not None:
        return path
    try:
        rel = os.path.relpath(os.path.abspath(head), os.path.abspath(folder))
    except ValueError:
        return path                 # another drive: there is no way from here
    return rel.replace(os.sep, "/") + bar + tail


def relative_or_name(path, folder):
    """Where path is, as seen from folder, with forward slashes; its own name
    alone when the two share no drive, or when the way would climb out of the
    home folder; from ~ when the path is under the home folder and folder is
    not. For a manifest that must say which folder something came from
    without saying where the person who made it keeps their files."""
    mine, there = home_rest(path), home_rest(folder)
    if mine is not None and there is None:
        return with_tilde(path)
    if mine is None and there is not None:
        return os.path.basename(os.path.normpath(str(path)))
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(folder))
    except ValueError:
        return os.path.basename(os.path.normpath(str(path)))
    return rel.replace(os.sep, "/")


def from_folder(path, folder):
    """The path a manifest holds, made usable: a relative one is read from the
    folder of the manifest, one from ~ from the home folder of whoever opens
    it, an absolute one (every manifest written before paths were kept
    relative) is returned as it is.

    A reference raster is not always a file: a service, a database table, a
    basemap are written as the text QGIS gave. Such a text is not joined to
    the folder; neither is a name the folder does not hold, which stays what
    the manifest said so that whoever reports it missing quotes it."""
    if not path or not folder:
        return path
    head, bar, tail = str(path).partition("|")
    if head == "~" or head.startswith(("~/", "~\\")):
        return os.path.normpath(os.path.expanduser(head)) + bar + tail
    found = _VSI_NAME.match(head)
    if found and found.group(2)[:1] == "~" \
            and found.group(2)[1:2] in ("", "/", "\\"):
        return found.group(1) + os.path.normpath(
            os.path.expanduser(found.group(2))) + bar + tail
    if os.path.isabs(head) or "://" in head or head.startswith("\\\\"):
        return path
    joined = os.path.normpath(os.path.join(folder, head))
    if not os.path.exists(long_path(joined)):
        return path
    return joined + bar + tail


def without_home(text):
    """The text with the home folder of whoever is running the program
    written as ~, and the passwords and user names of a source taken out
    (clean_source), for the reports that are pasted into public places."""
    text = str(text)
    home = os.path.expanduser("~")
    if not home or home in ("~", os.sep) or len(home) < 3:
        return clean_source(text)
    for form in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
        # not the start of the name of another folder
        text = re.sub(re.escape(form) + r"(?![\w.-])", lambda m: "~", text,
                      flags=re.IGNORECASE if os.name == "nt" else 0)
    return clean_source(text)
