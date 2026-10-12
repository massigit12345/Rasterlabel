"""Export: how the readings are arranged, the .zip, and work hidden from the
reader.

- One set of files per operator holds every pass of that operator (the pass
  stays an attribute) and is named after the operator; everything in one is
  as it always was. One per operator is for all the readings together only.
- The .zip packs every file the export wrote, the card and what goes beside
  a file, with names relative to the folder, and is written under a temporary
  name and renamed: a failure leaves no half archive and no loose temporary.
- A reader kept from some readings' work by the Annotate filter is asked
  once, before anything is written, whether the files that hold it may go
  out: Cancel writes nothing, Yes writes everything, the card included.
  Nothing hidden, no question.

Real GDAL, real GeoPackages, the program read from the built single file
with QGIS faked (correctkit with RL_KIT_REAL_GDAL); the windows are answered
as a user would.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import shutil
import sys
import tempfile
import zipfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import correctkit as K                                             # noqa: E402
import impact as F                                                 # noqa: E402
from osgeo import ogr                                              # noqa: E402

g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_export_arrange_")
GRID = F.GRID_CARD
OX, OY = 500000.0, 4140000.0
CLASSES = [{"code": 1, "name": "class 1", "colour": "#d95f02"},
           {"code": 2, "name": "class 2", "colour": "#1b9e77"}]


def box(x0, y0, x1, y1):
    return (OX + x0, OY + y0, OX + x1, OY + y1)


MARKS = [("polygons", ("ANNA", 1), 1, box(0, 0, 6, 10)),
         ("polygons", ("ANNA", 2), 2, box(6, 0, 10, 10)),
         ("polygons", ("BRUNO", 1), 1, box(0, 0, 5, 10)),
         ("points", ("ANNA", 2), 2, box(7, 5, 8, 6))]
folder = os.path.join(root, "aragona")
package = F.make_campaign(folder, GRID, [("F1", box(0, 0, 10, 10), True)],
                          MARKS, classes=CLASSES, name="aragona",
                          campaign_id="aragona_arrange")
with open(os.path.join(folder, "campaign.json"), encoding="utf-8") as fh:
    DATA = json.load(fh)


class Book:
    def __init__(self):
        self.folder, self.package_path, self.data = folder, package, DATA
        self.stem = "aragona"

    def active_classes(self):
        return [c for c in self.data["classes"] if not c.get("retired")]


class Opener:
    def openUrl(self, *a, **k):
        return True


g["QDesktopServices"] = Opener()
HIDDEN = {"operators": ()}


class Panel(K.QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.campaign = Book()
        self.section = None
        self.annotation = None

    def blind_gate(self, readings, what="agreement map", verb="compare"):
        return "hidden" if any(r[0] in HIDDEN["operators"]
                               for r in readings) else None

    def reading(self):
        return {"operator": "ANNA", "pass": 1}

    def pending_layers(self):
        return []

    def flush_layers(self):
        return []


panel = Panel()
QMB = K.QtWidgets.QMessageBox


def answering(button):
    """What every QMessageBox.question is answered with from now on."""
    def f(*a, **k):
        K.BOXES.append(("question", str(a[2] if len(a) > 2 else "")))
        return button
    QMB.question = staticmethod(f)


YES, CANCEL = QMB.StandardButton.Yes, QMB.StandardButton.Cancel


def export(where, arrange=None, zipped=False, card=False, reading=0,
           driver=0, tables=("polygons", "points")):
    """Press Export, choose in the window, press OK; the boxes it put up."""
    def answer(dialog):
        for name, b in dialog.tables:
            b.setChecked(name in tables)
        dialog.card.setChecked(card)
        dialog.reading.setCurrentIndex(reading)
        if arrange is not None:
            dialog.arrange.setCurrentIndex(arrange)
        dialog.shape.setCurrentIndex(driver)
        dialog.zip.setChecked(zipped)
        dialog.where.setText(where)
        dialog.accept()
        return K.QtWidgets.QDialog.DialogCode.Accepted
    K.ANSWERS["ExportVectors"] = answer
    shown = len(K.BOXES)
    g["Panel"].export_vectors(panel)
    return K.BOXES[shown:]


def note(d):
    """The note under the folder, without the breaks allowed in names."""
    return d.note.text().replace("&#8203;", "")


def shape_index(label):
    return [f[0] for f in g["FORMATS"]].index(label)


def rows(path, table):
    ds = ogr.Open(path)
    lyr = ds.GetLayerByName(table)
    out = [(f.GetField("operator"), f.GetField("pass_no")) for f in lyr]
    ds = None
    return sorted(out)


GPKG = [f[0] for f in g["FORMATS"] if f[1] == "GPKG"][0]
CSV = [f[0] for f in g["FORMATS"] if f[1] == "CSV"][0]
SHP = [f[0] for f in g["FORMATS"] if f[1] == "ESRI Shapefile"][0]

try:
    print("the window")
    d = g["ExportVectors"](panel, panel.campaign)
    check("it offers the two arrangements",
          [d.arrange.itemText(i) for i in range(d.arrange.count())]
          == ["everything in one", "one per operator"])
    check("everything in one to begin with", d.result()["arrange"] == "one")
    d.arrange.setCurrentIndex(1)
    check("one per operator is in the recipe",
          d.result()["arrange"] == "operator")
    check("and the note names a set of files for each operator",
          "one set per operator" in note(d)
          and "aragona_ANNA.gpkg" in note(d)
          and "aragona_BRUNO.gpkg" in note(d), note(d))
    d.zip.setChecked(True)
    check("the zip is in the recipe and in the note",
          d.result()["zip"] is True and "aragona_export.zip" in note(d),
          note(d))
    d.reading.setCurrentIndex(1)       # one reading
    check("with one reading chosen it goes back to one set and is greyed",
          not d.arrange.isEnabled() and d.arrange.currentIndex() == 0
          and d.result()["arrange"] == "one")
    d.reading.setCurrentIndex(0)
    check("and comes back with all the readings together",
          d.arrange.isEnabled())

    print()
    print("everything in one: as it was")
    one = os.path.join(root, "one")
    answering(YES)
    said = export(one, tables=("polygons", "points"), driver=shape_index(GPKG))
    check("one file holds every reading, operator and pass as attributes",
          sorted(os.listdir(one)) == ["aragona.gpkg"]
          and rows(os.path.join(one, "aragona.gpkg"), "polygons")
          == [("ANNA", 1), ("ANNA", 2), ("BRUNO", 1)],
          (sorted(os.listdir(one)) if os.path.isdir(one) else said))

    print()
    print("one per operator")
    per = os.path.join(root, "per")
    said = export(per, arrange=1, tables=("polygons", "points"),
                  driver=shape_index(GPKG))
    names = sorted(os.listdir(per))
    check("a set for each operator, named after them (no path in the name)",
          names == ["aragona_ANNA.gpkg", "aragona_BRUNO.gpkg"], names)
    anna = os.path.join(per, "aragona_ANNA.gpkg")
    bruno = os.path.join(per, "aragona_BRUNO.gpkg")
    check("ANNA's file holds both her passes",
          rows(anna, "polygons") == [("ANNA", 1), ("ANNA", 2)])
    check("BRUNO's holds his one, and none of ANNA's",
          rows(bruno, "polygons") == [("BRUNO", 1)])
    check("the points follow the operator too",
          rows(anna, "points") == [("ANNA", 2)] and rows(bruno, "points") == [])
    check("the box counts the files",
          said and "2 files written" in said[-1][1], said[-1:])
    tabs = os.path.join(root, "per_tables")
    export(tabs, arrange=1, driver=shape_index(CSV))
    check("a format that writes a file a table: one per operator and table",
          sorted(n for n in os.listdir(tabs) if n.endswith(".csv"))
          == ["aragona_ANNA_points.csv", "aragona_ANNA_polygons.csv",
              "aragona_BRUNO_points.csv", "aragona_BRUNO_polygons.csv"],
          os.listdir(tabs))

    print()
    print("the zip")
    zdir = os.path.join(root, "zipped")
    said = export(zdir, arrange=1, zipped=True, card=True, tables=("polygons",),
                  driver=shape_index(SHP))
    archive = os.path.join(zdir, "aragona_export.zip")
    check("the archive is there beside the files, and no temporary is left",
          os.path.isfile(archive) and not any(
              n.endswith(".tmp") for n in os.listdir(zdir)),
          sorted(os.listdir(zdir)))
    with zipfile.ZipFile(archive) as z:
        inside = sorted(z.namelist())
        bad = z.testzip()
        data = {n: z.read(n) for n in inside}
    loose = sorted(n for n in os.listdir(zdir) if n != "aragona_export.zip")
    check("it holds every file the export wrote, sidecars and card included",
          inside == loose and "aragona_ANNA_polygons.dbf" in inside
          and "aragona_ANNA_polygons.shp" in inside
          and "aragona_card.json" in inside and "aragona_card.md" in inside,
          (inside, loose))
    check("the files are whole", bad is None and all(
        data[n] == open(os.path.join(zdir, n), "rb").read() for n in inside))
    check("the names are relative, and say nothing of where they were made",
          all(not os.path.isabs(n) and ":" not in n and "\\" not in n
              and not n.startswith("..") for n in inside), inside)
    check("the box says it", said and "aragona_export.zip holds" in said[-1][1]
          and "5 files written" in said[-1][1]
          and "holds %d files" % len(inside) in said[-1][1], said[-1:])
    csvdir = os.path.join(root, "csvzip")
    export(csvdir, zipped=True, tables=("polygons",), driver=shape_index(CSV))
    with zipfile.ZipFile(os.path.join(csvdir, "aragona_export.zip")) as z:
        check("a CSV's .csvt and .prj go in with it",
              {"aragona_polygons.csv", "aragona_polygons.csvt"}
              <= set(z.namelist()), z.namelist())

    print()
    print("atomic: a failure on the way leaves the old archive, not half of one")
    from_dir = os.path.join(root, "atomic")
    os.makedirs(from_dir)
    f1 = os.path.join(from_dir, "a.txt")
    open(f1, "w").write("a")
    pack = g["pack_zip"]
    target, n = pack(from_dir, [f1], "x.zip")
    before = open(target, "rb").read()
    open(f1, "w").write("changed")
    real = os.replace

    def broken(*a, **k):
        raise OSError("disk full")
    g["os"].replace = broken
    try:
        try:
            pack(from_dir, [f1], "x.zip")
            failed = False
        except OSError:
            failed = True
    finally:
        g["os"].replace = real
    check("it says so", failed)
    check("the old archive is as it was",
          open(target, "rb").read() == before)
    check("and no temporary file is left",
          sorted(os.listdir(from_dir)) == ["a.txt", "x.zip"],
          os.listdir(from_dir))
    check("it holds one file, named without a path", n == 1 and zipfile.ZipFile(
        target).namelist() == ["a.txt"])

    print()
    print("work hidden from the reader: one question, before anything is written")
    HIDDEN["operators"] = ("BRUNO",)
    cancelled = os.path.join(root, "cancelled")
    answering(CANCEL)
    said = export(cancelled, card=True, zipped=True, arrange=1,
                  tables=("polygons",))
    asked = [t for k, t in said if k == "question"]
    check("it asks once", len(asked) == 1, said)
    check("in the author's words, with the reading named",
          asked and asked[0] == "These files contain work hidden from ANNA "
          "(BRUNO pass 1). Write them anyway?", asked)
    check("Cancel writes nothing at all",
          not os.path.exists(cancelled), os.listdir(root))
    check("and nothing more is said", len(said) == 1, said)
    yes = os.path.join(root, "yes")
    answering(YES)
    said = export(yes, card=True, zipped=True, tables=("polygons",))
    asked = [t for k, t in said if k == "question"]
    check("Yes: asked once, then everything is written, card and zip too",
          len(asked) == 1 and os.path.isfile(os.path.join(yes,
                                                          "aragona_card.json"))
          and os.path.isfile(os.path.join(yes, "aragona.gpkg"))
          and os.path.isfile(os.path.join(yes, "aragona_export.zip")),
          (asked, sorted(os.listdir(yes)) if os.path.isdir(yes) else said))
    check("and the box does not say the card was refused",
          not any("was not written" in t for _, t in said), said)
    # a reading chosen that the reader may see, with no card: nothing hidden
    mine = os.path.join(root, "mine")
    answering(CANCEL)
    said = export(mine, tables=("polygons",), reading=1,
                  driver=shape_index(GPKG))
    check("one reading the reader may see, no card: no question",
          not any(k == "question" for k, _ in said)
          and os.path.isfile(os.path.join(mine, "aragona_ANNA_p1.gpkg")),
          said)
    withcard = os.path.join(root, "withcard")
    said = export(withcard, tables=("polygons",), reading=1, card=True)
    check("the same with the card, which holds every reading: the question",
          any(k == "question" for k, _ in said)
          and not os.path.exists(withcard), said)
    HIDDEN["operators"] = ()
    nothing = os.path.join(root, "nothing_hidden")
    answering(CANCEL)
    said = export(nothing, card=True, tables=("polygons",))
    check("nothing hidden: no question, and the card is written",
          not any(k == "question" for k, _ in said)
          and os.path.isfile(os.path.join(nothing, "aragona_card.json")), said)
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
