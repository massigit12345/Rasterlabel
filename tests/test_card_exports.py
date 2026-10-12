"""The dataset card written beside the files: Whole raster and Export.

The card counts the pixels of a campaign with the very code that writes the
masks; this suite is the other half, the files it is written beside. Card
fixture C, through the buttons a user presses: the Whole raster writes a
consensus mask of card fixture A and its card in one step, and the card
holds the counts the mask was written with (paint_whole's tally), says the
mask is verified, gives every file its SHA-256, and a STAC item goes beside
the GeoTIFF mask; the mask carries the build, the campaign and the pixel
rule in its GeoTIFF tags, and the name of its card. At 1:2 the mask is not
on the campaign's pixels and the card says so. With the ignore value the
card says which value it is, and still verifies the mask. A reader the
Annotate filter keeps from another reading's work is asked once, before
anything is written; Cancel writes nothing, Yes writes the card too. From Whole the card starts unticked on a first use, since it counts
every reading at full size, and is remembered once ticked. From Export,
the card is ticked by default, can be written on its own with every table
unticked, and lists the vector files with their
SHA-256 when there are some.

Nothing in the campaign changes: the package and the manifest are the same
bytes after every step.

Real GDAL, real GeoPackages, the program read from the built single file
with QGIS faked (correctkit with RL_KIT_REAL_GDAL); the windows are
answered as a user would.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import hashlib
import json
import os
import shutil
import sys
import tempfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fixtures"))
sys.path.insert(0, os.path.join(HERE, "fixtures", "stac"))
import correctkit as K                                             # noqa: E402
import impact as F                                                 # noqa: E402
import minischema                                                  # noqa: E402
import numpy as np                                                 # noqa: E402
from osgeo import gdal                                             # noqa: E402

g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_card_exports_")
GRID = F.GRID_CARD
OX, OY = 500000.0, 4140000.0
CLASSES = [{"code": 1, "name": "class 1", "colour": "#d95f02"},
           {"code": 2, "name": "class 2", "colour": "#1b9e77"}]
ANNA, BRUNO = ("ANNA", 1), ("BRUNO", 1)


def box(x0, y0, x1, y1):
    return (OX + x0, OY + y0, OX + x1, OY + y1)


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# Card fixture A: ANNA 60 / 40, BRUNO 50 / 40, their consensus 50 / 32.
MARKS_A = [("polygons", ANNA, 1, box(0, 0, 6, 10)),
           ("polygons", ANNA, 2, box(6, 0, 10, 10)),
           ("polygons", BRUNO, 1, box(0, 0, 5, 10)),
           ("polygons", BRUNO, 2, box(5, 2, 10, 10)),
           ("points", ANNA, 2, box(7, 5, 8, 6))]
folder = os.path.join(root, "aragona")
package = F.make_campaign(folder, GRID, [("F1", box(0, 0, 10, 10), True)],
                          MARKS_A, classes=CLASSES, name="aragona",
                          campaign_id="aragona_card1")
ortho = os.path.join(folder, "ortho.tif")
ds = gdal.GetDriverByName("GTiff").Create(ortho, 10, 10, 3, gdal.GDT_Byte)
ds.SetGeoTransform((OX, 1.0, 0.0, OY + 10, 0.0, -1.0))
ds.SetProjection(F._srs(GRID).ExportToWkt())
for b in range(3):
    ds.GetRasterBand(b + 1).Fill(60 + 40 * b)
ds = None
with open(os.path.join(folder, "campaign.json"), encoding="utf-8") as fh:
    DATA = json.load(fh)
SHA_PACKAGE = sha(package)
SHA_MANIFEST = sha(os.path.join(folder, "campaign.json"))


class Book:
    """The campaign as the panel holds it, as far as these windows ask."""
    def __init__(self):
        self.folder, self.package_path, self.data = folder, package, DATA
        self.stem = "aragona"

    def active_classes(self):
        return [c for c in self.data["classes"] if not c.get("retired")]


class Opener:
    def openUrl(self, *a, **k):
        return True


# No window of the system is opened by these suites: the folder written is
# not shown in a file browser here.
g["QDesktopServices"] = Opener()
K.Bar.createMessage = lambda self, *a, **k: None
K.Bar.pushWidget = lambda self, *a, **k: None
K.Bar.popWidget = lambda self, *a, **k: None

HIDDEN = {"why": None}


class Panel(K.QtWidgets.QWidget):
    """The panel, as far as Whole and Export ask of it."""
    def __init__(self):
        super().__init__()
        self.campaign = Book()
        self.section = None
        self.annotation = None

    def blind_gate(self, readings, what="agreement map", verb="compare"):
        return HIDDEN["why"] if readings else None

    def pending_layers(self):
        return []

    def flush_layers(self):
        return []


Section = g["CutoutsSection"]


class Cutouts(K.QtWidgets.QWidget):
    """The Cutouts module, as far as Whole asks of it."""
    export_whole = Section.export_whole
    whole_card = Section.whole_card
    guess_limits = Section.guess_limits

    def __init__(self, panel):
        super().__init__()
        self.panel, self.campaign = panel, panel.campaign
        self.kept = {}

    def setting(self, key, default, kind=str):
        return self.kept.get(key, default)

    def keep_setting(self, key, value):
        self.kept[key] = value

    def tick_whole(self, done, total):
        pass


K.LOADED.clear()
K.add_layer(K.Layer(ortho, "ortho"))
panel = Panel()
cutouts = Cutouts(panel)
CONSENSUS = "consensus of pass 1: ANNA, BRUNO"
# whether the card row was ticked when each Whole window opened
CARD_SHOWN = []


def whole(where, reading=CONSENSUS, scale=1, mode=0, ignore=255, card=True,
          kinds=("mask",)):
    """Press Whole, choose in the window, press OK."""
    def answer(dialog):
        CARD_SHOWN.append(dialog.want["card"].isChecked())
        dialog.reading.setCurrentIndex(
            [c["label"] for c in dialog.choices].index(reading))
        for key, b in dialog.want.items():
            b.setChecked(key in kinds or (key == "card" and card))
        dialog.scale.setCurrentIndex(dialog.scale.findData(scale))
        dialog.unlabelled.setCurrentIndex(mode)
        dialog.ignore_value.setValue(ignore)
        dialog.folder.setText(where)
        dialog.accept()
        return K.QtWidgets.QDialog.DialogCode.Accepted
    K.ANSWERS["WholeRaster"] = answer
    shown = len(K.BOXES)
    cutouts.export_whole()
    return K.BOXES[shown:]


def tags(path):
    ds = gdal.Open(path)
    out = ds.GetMetadata() or {}
    ds = None
    return out


try:
    print("fixture C: the consensus mask and its card, from Whole")
    out = os.path.join(root, "whole")
    said = whole(out)
    check("on a first use the card row starts unticked",
          CARD_SHOWN[:1] == [False], CARD_SHOWN)
    check("ticked once, it is remembered on this machine",
          cutouts.kept.get("whole_card") is True, cutouts.kept)
    stem = "aragona_ortho_consensus_p1"
    mask = os.path.join(out, stem + "_mask.tif")
    votes = os.path.join(out, stem + "_votes.tif")
    card_md = os.path.join(out, stem + "_card.md")
    card_js = os.path.join(out, stem + "_card.json")
    item_path = os.path.join(out, stem + "_mask.stac.json")
    check("the mask, the votes, the card and the STAC item are written",
          all(os.path.isfile(p) for p in (mask, votes, card_md, card_js,
                                          item_path)),
          sorted(os.listdir(out)) if os.path.isdir(out) else said)
    check("the information box says so",
          said and said[-1][0] == "information"
          and "Dataset card: %s_card.md" % stem in said[-1][1]
          and "Unlabelled: 0 where nobody painted" in said[-1][1]
          and "STAC item" in said[-1][1], said)
    card = json.load(open(card_js, encoding="utf-8"))
    exports = {e["role"]: e for e in card["exports"]}
    m = exports.get("mask") or {}
    check("the mask is in the card with its SHA-256 and size",
          m.get("path") == os.path.basename(mask)
          and m.get("sha256") == sha(mask)
          and m.get("bytes") == os.path.getsize(mask), m)
    check("its counts are those it was written with: 50 and 32",
          {int(k): v for k, v in (m.get("counts_in_file") or {}).items()}
          == {1: 50, 2: 32}, m.get("counts_in_file"))
    product = [p for p in card["products"] if p["label"] == CONSENSUS][0]
    check("and those of the consensus the card counts",
          {int(k): v for k, v in product["counts"].items()} == {1: 50, 2: 32},
          product["counts"])
    check("verified", m.get("verified") is True, m.get("verified_reason"))
    check("the votes are there too, with their SHA-256, not verified",
          exports.get("votes", {}).get("sha256") == sha(votes)
          and exports["votes"].get("verified") is None)
    check("the card describes the consensus that was written",
          card["stac"]["describes"] == CONSENSUS)
    check("and says 0 is unlabelled, no ignore value",
          card["rules"]["ignore_index"] is None)

    print()
    print("the tags of the mask")
    t = tags(mask)
    check("the pixel rule, the build, the campaign",
          t.get("RASTERLABEL_PIXEL_RULE", "").startswith("centre")
          and t.get("RASTERLABEL_BUILD") == g["BUILD"]
          and t.get("RASTERLABEL_CAMPAIGN_ID") == DATA["id"], t)
    check("still the four reading tags",
          all(k in t for k in ("RASTERLABEL_VERSION",
                               "RASTERLABEL_READING_MODE",
                               "RASTERLABEL_READINGS",
                               "RASTERLABEL_READING_RULE")), sorted(t))
    check("and the name of its card", t.get("RASTERLABEL_CARD")
          == os.path.basename(card_js), t.get("RASTERLABEL_CARD"))
    check("the mask says what it holds where nobody painted",
          t.get("RASTERLABEL_UNLABELLED") == "zero"
          and "RASTERLABEL_IGNORE_INDEX" not in t)
    tv = tags(votes)
    check("the votes carry the provenance too",
          tv.get("RASTERLABEL_BUILD") == g["BUILD"]
          and tv.get("RASTERLABEL_CARD") == os.path.basename(card_js), tv)

    print()
    print("the STAC item beside the mask")
    print("  (read with %s)" % minischema.reader())
    item = json.load(open(item_path, encoding="utf-8"))
    label_errors = minischema.validate(item, "label")
    proj_errors = minischema.validate(item, "projection")
    check("it holds against label v1.0.1", not label_errors, label_errors)
    check("and against projection v1.1.0", not proj_errors, proj_errors)
    check("the mask is its labels, the votes its metadata",
          item["assets"]["labels"]["href"] == "./" + os.path.basename(mask)
          and item["assets"]["votes"]["href"] == "./"
          + os.path.basename(votes))
    check("it links to the card", any(
        l.get("href") == "./" + os.path.basename(card_js)
        for l in item.get("links", [])), item.get("links"))
    check("its overview is the card's counts",
          item["properties"]["label:overviews"][0]["counts"]
          == [{"name": "class 1", "count": 50},
              {"name": "class 2", "count": 32}],
          item["properties"]["label:overviews"])
    check("nothing in the campaign changed",
          sha(package) == SHA_PACKAGE
          and sha(os.path.join(folder, "campaign.json")) == SHA_MANIFEST)

    print()
    print("at 1:2 the mask is not on the campaign's pixels")
    half = os.path.join(root, "half")
    whole(half, scale=2)
    card2 = json.load(open(os.path.join(
        half, stem + "_1of2_card.json"), encoding="utf-8"))
    m2 = [e for e in card2["exports"] if e["role"] == "mask"][0]
    check("not verified, saying 1:2", m2["verified"] is False
          and "1:2" in m2["verified_reason"], m2)

    print()
    print("with the ignore value")
    ign = os.path.join(root, "ignore")
    said = whole(ign, mode=1, ignore=255)
    istem = stem + "_ign255"
    imask = os.path.join(ign, istem + "_mask.tif")
    icard = json.load(open(os.path.join(ign, istem + "_card.json"),
                           encoding="utf-8"))
    im = [e for e in icard["exports"] if e["role"] == "mask"][0]
    check("the file is named after it", os.path.isfile(imask),
          sorted(os.listdir(ign)) if os.path.isdir(ign) else said)
    check("the card says 255", icard["rules"]["ignore_index"] == 255
          and icard["stac"]["properties"]["rasterlabel:ignore_index"] == 255)
    check("and still verifies the mask: 255 is not a class",
          im["verified"] is True and {int(k): v for k, v in
                                      im["counts_in_file"].items()}
          == {1: 50, 2: 32}, im)
    a = gdal.Open(imask).ReadAsArray()
    check("the mask holds 255 where nobody painted and where the readings "
          "do not agree", int((a == 255).sum()) == 18
          and int((a == 0).sum()) == 0, np.unique(a, return_counts=True))
    check("the box says the rule", said and "Unlabelled: 255 where nobody "
          "painted, and where the readings do not agree" in said[-1][1],
          said[-1:])
    t = tags(imask)
    check("the mask's tags: ignore, 255, over the card's 0",
          t.get("RASTERLABEL_UNLABELLED") == "ignore"
          and t.get("RASTERLABEL_IGNORE_INDEX") == "255", t)

    print()
    print("a reader kept from another reading's work: asked once, before the files")
    blind = os.path.join(root, "blind")
    QMB = K.QtWidgets.QMessageBox
    HIDDEN["why"] = "BRUNO is drawing pass 1 with one operator at a time on"

    def answering(button):
        def f(*a, **k):
            K.BOXES.append(("question", str(a[2] if len(a) > 2 else "")))
            return button
        QMB.question = staticmethod(f)
    answering(QMB.StandardButton.Cancel)
    said = whole(blind)
    check("Cancel: the question is asked and nothing is written",
          said and said[-1][0] == "question"
          and "The dataset card holds work hidden from the reader" in said[-1][1]
          and not os.path.exists(os.path.join(blind, stem + "_mask.tif")),
          (said, os.listdir(blind) if os.path.isdir(blind) else None))
    answering(QMB.StandardButton.Yes)
    said = whole(blind)
    HIDDEN["why"] = None
    check("Yes: the mask is written", os.path.isfile(os.path.join(
        blind, stem + "_mask.tif")))
    check("and so is the card, with no word of a refusal",
          os.path.isfile(os.path.join(blind, stem + "_card.json"))
          and not any("was not written" in t for _, t in said), said[-1:])
    check("and the mask names its card",
          "RASTERLABEL_CARD" in tags(os.path.join(blind,
                                                  stem + "_mask.tif")))

    print()
    print("the card on its own, from Whole")
    alone = os.path.join(root, "alone")
    whole(alone, kinds=())
    check("only the card", sorted(os.listdir(alone)) == sorted(
        [stem + "_card.json", stem + "_card.md"]), os.listdir(alone))
    check("the next window opened with the card ticked",
          len(CARD_SHOWN) > 1 and all(CARD_SHOWN[1:]), CARD_SHOWN)
    check("the choices are remembered on this machine",
          cutouts.kept.get("whole_card") is True
          and cutouts.kept.get("whole_unlabelled") == "zero", cutouts.kept)

    print()
    print("Export: the card checkbox")

    def export(where, tables=None, card=True):
        def answer(dialog):
            for name, b in dialog.tables:
                b.setChecked(tables is None and b.isEnabled()
                             or name in (tables or ()))
            dialog.card.setChecked(card)
            dialog.where.setText(where)
            dialog.accept()
            return K.QtWidgets.QDialog.DialogCode.Accepted
        K.ANSWERS["ExportVectors"] = answer
        shown = len(K.BOXES)
        g["Panel"].export_vectors(panel)
        return K.BOXES[shown:]

    dialog = g["ExportVectors"](panel, panel.campaign)
    check("ticked by default, after the tables",
          dialog.card.isChecked() and dialog.layout().indexOf(dialog.card)
          > max(dialog.layout().indexOf(b) for _, b in dialog.tables))
    check("its tip says what it holds, and that nothing changes",
          "pixels" in dialog.card.toolTip()
          and "Nothing in the campaign changes" in dialog.card.toolTip())
    for _, b in dialog.tables:
        b.setChecked(False)
    check("with every table unticked the note says the card goes alone",
          "only the dataset card" in dialog.note.text()
          and "aragona_card.md" in dialog.note.text().replace("&#8203;", ""), dialog.note.text())
    check("and the result says the card", dialog.result()["card"] is True
          and dialog.result()["tables"] == [])
    only = os.path.join(root, "export_only")
    said = export(only, tables=())
    check("written on its own", sorted(os.listdir(only)) == [
        "aragona_card.json", "aragona_card.md"], os.listdir(only)
          if os.path.isdir(only) else said)
    check("and said", said and said[-1][0] == "information"
          and "2 files written" in said[-1][1]
          and "Dataset card: aragona_card.md" in said[-1][1], said[-1:])
    both = os.path.join(root, "export_both")
    said = export(both, tables=("polygons",))
    vec = [n for n in os.listdir(both) if not n.startswith("aragona_card")]
    ecard = json.load(open(os.path.join(both, "aragona_card.json"),
                           encoding="utf-8"))
    listed = {e["path"]: e for e in ecard["exports"]}
    check("after the vectors, which it lists with their SHA-256",
          vec and all(listed.get(n, {}).get("sha256")
                      == sha(os.path.join(both, n)) for n in vec)
          and all(e["role"] == "vectors" for e in ecard["exports"]),
          (vec, list(listed)))
    none = os.path.join(root, "export_none")
    said = export(none, tables=(), card=False)
    check("with nothing ticked, nothing is written",
          not os.path.exists(none) and said
          and "Nothing was chosen" in said[-1][1], said[-1:])
    check("the card choice is remembered on this machine",
          g["read_setting"](g["ExportVectors"].CARD_KEY, True, bool)
          is False)
    check("and after all of it the campaign is as it was",
          sha(package) == SHA_PACKAGE
          and sha(os.path.join(folder, "campaign.json")) == SHA_MANIFEST)
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
