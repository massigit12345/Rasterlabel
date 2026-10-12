"""A report that QGIS could not open is refused before it is written.

On Windows, QGIS opens a GeoPackage through SQLite, and SQLite cannot open a
path of 260 characters or more. GDAL could write one (through the \\\\?\\ form
of the path, long_path), so Compare wrote its GeoPackage into a folder deep
enough, and the layers of the report then did not load, with nothing to say
why. This suite holds the rule that stops it:

- only a SQLite file (.gpkg, .sqlite) is held to a length, and only on
  Windows; a GeoTIFF, a GeoJSON, a table or a style is not, because GDAL and
  Qt open those at any length (tests/test_report_paths_qgis.py asks QGIS);
- the limit is 259 characters less the eight of a -journal file and the three of a
  -99 on the folder's name, 248, and the words say how long the path would be,
  what the longest is, how many characters too many, and to choose a shorter
  folder;
- the path asked about is the one the report will have: the folder the person
  named, or reports/<kind>/<label>_<stamp> in the owner's, with the name of
  the file its kind gives it;
- Compare refuses before it makes a folder, at the default place and at one
  typed in the window, and leaves nothing behind; the setup window of Compare
  says it and keeps Compare grey; Time and Model vs corrected ask the same
  question (Time's own run is in tests/test_time_report_run.py).

The suite asks as Windows answers on any machine (windows=True), so it means
the same on Linux.

Real GDAL, QGIS faked (correctkit with RL_KIT_REAL_GDAL).
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import io
import json
import os
import shutil
import sys
import tempfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import correctkit as K                                             # noqa: E402
import impact as F                                                 # noqa: E402

g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_report_paths_")
ANNA, BRUNO = F.ANNA, F.BRUNO
real_problem = g["report_open_problem"]


def windows_answers():
    g["report_open_problem"] = lambda folder, names, windows=None: \
        real_problem(folder, names, True)


def own_answers():
    g["report_open_problem"] = real_problem


ROOM = g["WINDOWS_PATH_MAX"] - g["SQLITE_SIDE_FILES"] - g["REPORT_RENUMBER"]
BASE = os.path.abspath(os.sep)


def folder_for(n, name):
    """A folder (that need not exist) whose path with this file in it is
    n characters long."""
    k = n - len(BASE) - 1 - len(name)
    return BASE + "d" * k


print("the rule")
check("the room is 248: 259, less -journal and -99", ROOM == 248, ROOM)
for n, held in ((200, True), (ROOM, True), (ROOM + 1, False),
                (259, False), (260, False), (334, False)):
    folder = folder_for(n, "report.gpkg")
    got = real_problem(folder, ["report.gpkg"], True)
    check("a GeoPackage on %d characters is %s" % (n, "let be" if held
                                                  else "refused"),
          (got == "") == held, got)
folder = folder_for(400, "report.gpkg")
for name in ("map_pairs.tif", "places.geojson", "per_class.csv",
             "summary.json", "style.qml", "calibration.png"):
    check("%s on 400 characters is not held to the length" % name,
          real_problem(folder, [name], True) == "")
check("nor is anything, anywhere but Windows",
      real_problem(folder, ["report.gpkg"], False) == "")
check("a report with no file for QGIS has nothing to say",
      real_problem(folder, [], True) == ""
      and real_problem(folder, None, True) == "")
check(".sqlite is held as .gpkg is, whatever the case of the extension",
      real_problem(folder, ["a.SQLITE"], True) != ""
      and real_problem(folder, ["a.GPKG"], True) != "")
text = real_problem(folder_for(281, "report.gpkg"), ["report.gpkg"], True)
check("the words give the length, the most, and how much to take away",
      "281 characters" in text and "248" in text and "33 characters shorter"
      in text, text)
check("and say where to go and what to do",
      "shorter folder" in text and "root of the drive" in text
      and "report.gpkg" in text, text)
two = real_problem(folder_for(300, "bb.gpkg"), ["a.gpkg", "bb.gpkg"], True)
check("with two files it is the longer one it names", "bb.gpkg" in two
      and "300 characters" in two, two)

print()
print("where the report is going")
check("the folder the person named is the one asked about",
      g["report_folder_guess"]("C:/owner", "agreement", "L", "C:/named")
      == "C:/named")
guess = g["report_folder_guess"]("owner", "agreement", "ANNA_p1_vs_BRUNO_p1")
check("else reports/<kind>/<label>_<stamp> in the owner's",
      guess.startswith(os.path.join("owner", "reports", "agreement",
                                    "ANNA_p1_vs_BRUNO_p1_"))
      and len(os.path.basename(guess)) == len("ANNA_p1_vs_BRUNO_p1_")
      + len(g["report_stamp"]()), guess)
tmp, final = g["report_folder"](root, "agreement", "ANNA_p1_vs_BRUNO_p1")
check("the same length as the one report_folder makes",
      len(os.path.basename(final)) == len(os.path.basename(
          g["report_folder_guess"](root, "agreement",
                                   "ANNA_p1_vs_BRUNO_p1"))), final)
shutil.rmtree(tmp, ignore_errors=True)

print()
print("Compare")
folder = os.path.join(root, "camp")
package = F.make_campaign(folder, F.GRID_AGREEMENT, F.SHARED_FRAMES,
                          F.SHARED_MARKS, name="camp")
with io.open(os.path.join(folder, "campaign.json"), encoding="utf-8") as fh:
    data = json.load(fh)
vectors = g["cmp_files"](g["tidy"](data.get("name") or "campaign",
                                   "campaign"),
                         g["cmp_label"](ANNA, BRUNO))["vectors"]
deep = os.path.join(root, "t" * 120, "u" * 120)
n_deep = len(os.path.join(deep, vectors))
check("the folder asked for is long enough to be refused", n_deep > ROOM,
      n_deep)
check("cmp_path_problem says so, with the length of the path",
      "%d characters" % n_deep in real_problem(deep, [vectors], True))
own = g["cmp_path_problem"](data, folder, ANNA, BRUNO, None, True)
check("where the campaign keeps its reports it is let be (the path is short)",
      own == "", own)
check("and a folder typed in the window is asked about as it is",
      "%d characters" % n_deep in g["cmp_path_problem"](
          data, folder, ANNA, BRUNO, deep, True))
plan = g["cmp_plan"](data, package, ANNA, BRUNO, "closed", False)


def recipe(**more):
    return dict({"data": data, "folder": folder, "package": package,
                 "plan": plan, "n_boot": 50, "seed": 1}, **more)


windows_answers()
try:
    for where, kwargs, made in (
            ("a folder typed in the window", {"target": deep}, deep),
            ("the campaign's own reports folder, too deep",
             {"folder": os.path.join(root, "w" * 130, "v" * 130)},
             os.path.join(root, "w" * 130))):
        try:
            g["cmp_compare"](recipe(**kwargs))
            said = None
        except ValueError as err:
            said = str(err)
        check("Compare refuses %s, in plain words" % where,
              said is not None and "characters" in said
              and "shorter folder" in said, said)
        check("and made nothing: no folder, no .tmp",
              not os.path.exists(g["long_path"](made))
              and not os.path.exists(g["long_path"](made + ".tmp")))
    check("the campaign's own folder has no reports folder",
          not os.path.exists(os.path.join(folder, "reports")),
          os.listdir(folder))
    result = g["cmp_compare"](recipe())
    check("a report that fits is written as it always was",
          os.path.isdir(result["folder"])
          and os.path.isfile(os.path.join(result["folder"], vectors)),
          result.get("folder"))
finally:
    own_answers()

print()
print("the window of Compare")
windows_answers()
try:
    marks = g["cmp_marks"](package)
    readings = g["cmp_readings"](marks, points_in=True)
    setup = g["CompareSetup"](None, data, folder, package, readings, marks,
                              g["reading_shares"](package),
                              g["cmp_frames"](package))
    check("Compare can be pressed where the report fits",
          setup.go.isEnabled() and not setup.path_note.isVisibleTo(setup),
          (setup.go.toolTip(), setup.path_note.text()))
    setup.where.setText(deep)
    setup.where.textEdited.emit(deep)
    check("a folder too deep greys it", not setup.go.isEnabled())
    check("and the note under the folder says how long and what to do",
          setup.path_note.isVisibleTo(setup)
          and "%d characters" % n_deep in setup.path_note.text()
          and "shorter folder" in setup.path_note.text(),
          setup.path_note.text())
    setup.where.setText(os.path.join(root, "short"))
    setup.where.textEdited.emit("short")
    check("a shorter one frees it again", setup.go.isEnabled()
          and not setup.path_note.isVisibleTo(setup))
    # the Browse button writes the folder with setText, which is silent
    dialog = g["QFileDialog"]
    real_dialog = dialog.getExistingDirectory
    browse = [b for b in setup.findChildren(g["QPushButton"])
              if b.toolTip().startswith("Choose the folder the report")][0]
    try:
        dialog.getExistingDirectory = staticmethod(lambda *a, **k: deep)
        browse.click()
        check("a too deep folder chosen with Browse greys it as well",
              not setup.go.isEnabled() and setup.path_note.isVisibleTo(setup)
              and setup.where.text().startswith(deep), setup.where.text())
        check("and counts as the person's own choice, kept when the "
              "readings change", setup.folder_edited)
        dialog.getExistingDirectory = staticmethod(
            lambda *a, **k: os.path.join(root, "short"))
        browse.click()
        check("a shorter one chosen with Browse frees it again",
              setup.go.isEnabled() and not setup.path_note.isVisibleTo(setup),
              setup.path_note.text())
    finally:
        dialog.getExistingDirectory = real_dialog
finally:
    own_answers()

print()
print("Time and Model vs corrected ask the same")
owner = os.path.join(root, "w" * 130, "v" * 130)
check("Time: the map of the frames is held to the length",
      g["time_path_problem"](owner, None, True) != ""
      and "time_frames.gpkg" in g["time_path_problem"](owner, None, True))
check("and a folder typed for it is the one asked about",
      g["time_path_problem"](folder, deep, True) != ""
      and g["time_path_problem"](folder, None, True) == "")
src = open(K.SRC, encoding="utf-8").read()
write = src[src.index("def time_write(plan"):]
check("time_write asks before it makes the report folder",
      write.index("time_path_problem(") < write.index("time_target("))
mvc = src[src.index("def mvc_report("):]
check("mvc_report asks before it makes the report folder",
      mvc.index("report_open_problem(") < mvc.index("cmp_target(target)"))
check("the map of pairs is a GeoTIFF, which is let be at any length",
      real_problem(deep, [g["mvc_files"]("map", "whole")["pairs"]], True)
      == "")

shutil.rmtree(g["long_path"](root), ignore_errors=True)
sys.exit(K.finish())
