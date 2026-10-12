"""Uncertainty-guided correction, through the panel, on real files.

The map is laid out like the Aragona land cover maps Correct is used on
(test_correct_thematic): five bands of bytes, the class, the probability
and the entropy scaled to 255, a validity mask and the class before
sieving, nodata 0 on every band and ten rows of nodata at the top. QGIS is
faked (correctkit), GDAL is real.

  Correct opens with the card's suggestion: band 2 "probabilita x255" looks
  like the probability of the class; Use it reads it into
  <copy>_uncertainty.tif, 1 - p on 254 levels and 255 on the nodata rows,
  and the manifest holds what was read;
  the Source window cuts the map into places of 16 px; two strokes in two
  places, Done three times and Skip once: uncertainty_places.csv says 3
  done and 1 skipped, the pixels changed in each done place are the marks
  of its window, and journal.csv names the place of each stroke;
  operations.csv keeps its 14 columns; bands 2 to 5 of the copy are the
  map's;
  the report writes its folder under reports/uncertainty, with a
  calibration whose whole map counts every pixel with a value and every
  pixel changed; the manifest remembers it, and the panel's tooltip, Check
  and the Measure menu say the uncertainty;
  the entropy, band 3, reads no nodata of 0 as a value here, and one
  pixel set to 0 is read as one;
  a raster half a pixel off the grid is read nearest neighbour once the
  window has warned and Use has asked; one in another coordinate system is
  refused;
  the votes of a consensus, 1 - votes / readings: 0 where both readings
  agree, 127 where one of two does;
  with no uncertainty, nothing changes: a map of one band says it has none,
  no file is written, the manifest of a correction opened again is the one
  it had but for the time it was opened, and operations.csv keeps its 14
  columns; a manifest whose uncertainty is gone opens, says so, and Check
  calls it a problem;
  every uncertainty file is the correction's own, and Set aside moves it.

Needs the GDAL Python bindings.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import json
import os
import shutil
import sys
import tempfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                                 # noqa: E402
from osgeo import gdal, osr                                        # noqa: E402
import correctkit as K                                             # noqa: E402

gdal.UseExceptions()
g, check = K.g, K.check

root = tempfile.mkdtemp(prefix="rl_unc_correct_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
data = os.path.join(root, "output")
os.makedirs(data)

NX, NY = 150, 100
GT = (13.597001325635429, 5.6448e-07, 0.0, 37.377110918744194, 0.0,
      -4.50488e-07)
NAMES = ["classe", "probabilita x255", "entropia x255", "validita",
         "classe senza setaccio"]
CLASSES = [(1, "#2b3a4a", "fango fresco"), (2, "#e8e2d5", "fango secco"),
           (3, "#d9a441", "suolo"), (4, "#2f7b5f", "vegetazione")]
srs = osr.SpatialReference()
srs.ImportFromEPSG(4326)
WKT = srs.ExportToWkt()

rng = np.random.default_rng(11)
CLASS = rng.integers(1, 5, (NY, NX)).astype(np.uint8)
CLASS[:10, :] = 0
BANDS = [CLASS,
         np.where(CLASS > 0, rng.integers(66, 256, (NY, NX)), 0).astype(np.uint8),
         np.where(CLASS > 0, rng.integers(1, 255, (NY, NX)), 0).astype(np.uint8),
         (CLASS > 0).astype(np.uint8),
         np.where(CLASS > 0, rng.integers(1, 5, (NY, NX)), 0).astype(np.uint8)]


def write_tif(path, bands, names, gt=GT, wkt=WKT, nodata=0,
              kind=gdal.GDT_Byte):
    ds = gdal.GetDriverByName("GTiff").Create(path, bands[0].shape[1],
                                              bands[0].shape[0], len(bands),
                                              kind)
    ds.SetGeoTransform(gt)
    ds.SetProjection(wkt)
    for i, a in enumerate(bands):
        b = ds.GetRasterBand(i + 1)
        b.WriteArray(a)
        if nodata is not None:
            b.SetNoDataValue(nodata)
        b.SetDescription(names[i])
    ds = None


def pixels(path, band=1):
    ds = gdal.Open(path)
    out = ds.GetRasterBand(band).ReadAsArray()
    ds = None
    return out


def styled(path, name, lid):
    style = K.Paletted(None, 1, [K.Paletted.Class(v, c, n)
                                 for v, c, n in CLASSES])
    return K.add_layer(K.Layer(path, name, renderer=style, lid=lid))


source = os.path.join(data, "72_mappa_fold.tif")
write_tif(source, BANDS, NAMES)
layer = styled(source, "72_mappa_fold", "layer_map")
panel = g["Panel"]()


def new_on(lay, folder, name):
    def fill(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText(name)
        d.raster.setCurrentIndex(d.raster.findData(lay.id()))
        d.fill_bands()
        d.folder.setText(folder)
        d.operator.setText("ann")
        return 1
    return fill


def open_correct(lay, folder, name):
    K.ANSWERS["OpenCorrection"] = new_on(lay, folder, name)
    K.ANSWERS["ConfirmClasses"] = lambda d: 1
    panel.toggle_module(1)
    K.ANSWERS.pop("OpenCorrection", None)
    K.ANSWERS.pop("ConfirmClasses", None)
    return panel.section


def reopen(folder):
    def fill(d):
        d.existing.setCurrentIndex(d.existing.findData(
            "open:" + os.path.join(folder, "correction.json")))
        return 1
    K.ANSWERS["OpenCorrection"] = fill
    K.ANSWERS["ConfirmClasses"] = lambda d: 1
    panel.toggle_module(1)
    K.ANSWERS.pop("OpenCorrection", None)
    K.ANSWERS.pop("ConfirmClasses", None)
    return panel.section


def hook_of(section):
    return g["unc_hook_of"](section)


def stroke_in(section, place, into=1):
    """A stroke over the middle of a place, changing any class into one."""
    h = max(1, place["height"] // 2)
    w = max(1, place["width"] // 2)
    inside = np.ones((h, w), bool)
    col = place["col"] + place["width"] // 4
    row = place["row"] + place["height"] // 4
    section.mask_of = lambda geom: (col, row, inside)
    section.choose_from(None)
    section.choose_class(into)
    section.paint(K.Stroke())


def manifest(folder):
    return json.load(open(os.path.join(folder, "correction.json"),
                          encoding="utf-8"))


def source_dialog(fill):
    def answer(d):
        SEEN["dialog"] = d
        fill(d)
        d.refresh()
        d.accept()
        return 1
    K.ANSWERS["UncertaintySource"] = answer


SEEN = {}

try:
    print("Correct opens with a suggestion, and nothing more")
    folder = os.path.join(root, "fix")
    section = open_correct(layer, folder, "fix")
    check("Correct opened", type(section).__name__ == "CorrectionSection",
          (K.BOXES, K.UNEXPECTED))
    hook = hook_of(section)
    card = hook.card if hook is not None else None
    check("the uncertainty hook is there, before the journal's",
          hook is not None and [type(h).__name__ for h in
                                section.stroke_hooks].index(
              "UncertaintyHook") < [type(h).__name__ for h in
                                    section.stroke_hooks].index(
              "CorrectJournalHook"),
          [type(h).__name__ for h in section.stroke_hooks])
    check("the card is in the slot after Save",
          card is not None and section.measure_slot.count() == 1)
    check('it says band 2 "probabilita x255" looks like the probability',
          card.line.text() == 'band 2 "probabilita x255" looks like the '
          'probability of the class.', card.line.text())
    check("and offers Use it", not card.use_box.isHidden())
    copy = section.path
    derived = os.path.join(folder, "72_mappa_fold_corrected_uncertainty.tif")
    check("no uncertainty file and no manifest block yet",
          not os.path.exists(derived) and "uncertainty" not in
          manifest(folder) and "places" not in manifest(folder))

    print()
    print("Use it")
    card.use_it()
    book = manifest(folder)
    spec = book.get("uncertainty") or {}
    check("the manifest holds a band of the copy, band 2, a probability on "
          "255", (spec.get("source"), spec.get("band"), spec.get("kind"),
                  spec.get("scale")) == ("copy", 2, "probability", 255.0),
          spec)
    check("and what was read: 13 500 pixels with a value, nothing clipped",
          spec.get("valid_px") == 13500 and spec.get("clipped_px") == 0
          and spec.get("grid") == "same", spec)
    u8 = pixels(derived)
    p = BANDS[1].astype(np.float64)
    want = np.where((BANDS[1] > 0) & (CLASS > 0),
                    np.floor((1 - np.clip(p / 255.0, 0, 1)) * 254 + 0.5),
                    255).astype(np.uint8)
    check("<copy>_uncertainty.tif is 1 - p on 254 levels",
          np.array_equal(u8, want), int((u8 != want).sum()))
    check("and 255 on the ten rows of nodata", (u8[:10] == 255).all())
    ds = gdal.Open(derived)
    meta = ds.GetMetadata()
    band = ds.GetRasterBand(1)
    check("its metadata says a probability, read from band 2 of the copy",
          meta.get("RASTERLABEL_UNCERTAINTY_KIND") == "probability"
          and meta.get("RASTERLABEL_UNCERTAINTY_SOURCE", "").startswith(
              "copy band 2") and meta.get("RASTERLABEL_VERSION") == "1.1",
          meta)
    check("one band, 'uncertainty', nodata 255, on the copy's grid",
          ds.RasterCount == 1 and band.GetDescription() == "uncertainty"
          and band.GetNoDataValue() == 255 and ds.GetGeoTransform() == GT)
    band = ds = None
    check("the card now holds the walk",
          card.walk.isVisibleTo(card) and card.use_box.isHidden()
          and "probabilita x255, read as 1 - p" in card.line.text(),
          card.line.text())
    check("the places are in the manifest and beside the copy",
          (book.get("places") or {}).get("file") == "uncertainty_places.csv"
          and os.path.exists(os.path.join(folder, "uncertainty_places.csv")))

    print()
    print("places of 16 pixels, from the Source window")

    def sixteen(d):
        d.in_copy.setChecked(True)
        d.select(d.band, 2)
        d.side.setValue(16)
    source_dialog(sixteen)
    card.choose()
    places = hook.places
    check("the window was asked", "dialog" in SEEN)
    check("16 px places, the first row too empty to be one: 60 places",
          places.side == 16 and places.N == 60, (places.side, places.N))
    check("blind by default", places.blind and "blind" in card.line.text())

    print()
    print("the walk: two strokes, Done three times, Skip once")
    card.next()                                  # Start
    first = places.current()
    check("Start offers the most uncertain place",
          first is not None and first["purposive_rank"] == 1, first)
    stroke_in(section, first)
    card.next()                                  # Done, next
    second = places.current()
    stroke_in(section, second, into=2)
    card.next()
    third = places.current()
    card.next()
    fourth = places.current()
    card.skip()
    rows = list(csv.DictReader(open(os.path.join(
        folder, "uncertainty_places.csv"), encoding="utf-8")))
    status = [r["status"] for r in rows]
    check("uncertainty_places.csv: 3 done and 1 skipped",
          status.count("done") == 3 and status.count("skipped") == 1
          and status.count("current") == 1, status.count("done"))
    marks = pixels(section.changes_path)
    for r in rows:
        if r["status"] != "done":
            continue
        c, w_, rr, h_ = (int(r["col"]), int(r["width"]), int(r["row"]),
                         int(r["height"]))
        check("place %s: changed_px is the marks of its window"
              % r["place_id"], int(r["changed_px"])
              == int(marks[rr:rr + h_, c:c + w_].sum()), r["changed_px"])
    check("the strokes changed something", int(marks.sum()) > 0)
    check("the place in hand is said blind: no u, no selection",
          "u " not in card.place.text() and "purposive" not in
          card.place.text(), card.place.text())
    with open(section.log_path, encoding="utf-8") as fh:
        log_rows = list(csv.reader(fh))
    check("operations.csv keeps 14 columns",
          all(len(r) == 14 for r in log_rows) and log_rows[0] ==
          list(g["CorrectionSection"].LOG_COLUMNS), log_rows[0])
    journal = os.path.join(folder, "journal.csv")
    if os.path.exists(journal):
        jrows = [r for r in csv.DictReader(open(journal, encoding="utf-8"))
                 if r.get("action") == "correct"]
        check("journal.csv names the place of each stroke",
              [r["place"] for r in jrows] == [first["place_id"],
                                              second["place_id"]],
              [r.get("place") for r in jrows])
        done_rows = [r for r in csv.DictReader(open(journal,
                                                    encoding="utf-8"))
                     if r.get("action") in ("place_done", "place_skip")]
        check("and each Done and Skip", len(done_rows) == 4, len(done_rows))
    else:
        check("journal.csv is there", False, os.listdir(folder))
    check("bands 2 to 5 of the copy are the map's",
          all(np.array_equal(pixels(copy, b), BANDS[b - 1])
              for b in (2, 3, 4, 5)))
    check("the file of u was only read",
          np.array_equal(pixels(derived), want))
    check("◀ goes back to the place before, marking nothing",
          (card.back() or True) and hook.view["place_id"]
          == fourth["place_id"] and places.current()["place_id"]
          not in (first["place_id"], fourth["place_id"]))
    check("and the middle key says it goes back to the current one",
          card.b_next.text() == "Current ▶", card.b_next.text())
    card.next()
    check("which it does, marking nothing",
          hook.view is places.current()
          and card.b_next.text() == "Done, next ▶")

    print()
    print("the report")
    by = {}
    menu = K.QtWidgets.QMenu()
    for a in g["measure_fill"](menu, "correction", panel):
        by[a.text()] = a
    check("Measure ▸ Uncertainty report… can be pressed",
          by.get("Uncertainty report…") is not None
          and by["Uncertainty report…"].isEnabled())
    SHOWN = []
    K.ANSWERS["ReportWindow"] = lambda d: SHOWN.append(d) or 1
    result = g["unc_report_start"](panel)
    check("the report window was shown", len(SHOWN) == 1, K.BOXES)
    check("in reports/uncertainty/<stamp>",
          result is not None and os.path.dirname(result["folder"])
          == os.path.join(folder, "reports", "uncertainty"),
          result and result["folder"])
    there = sorted(os.listdir(result["folder"]))
    check("with its files", there == sorted(
        ["calibration.csv", "capture.csv", "places.csv", "strokes.csv",
         "summary.json", "calibration.png"]), there)
    cal = list(csv.DictReader(open(os.path.join(result["folder"],
                                                "calibration.csv"),
                                   encoding="utf-8")))
    whole = [r for r in cal if r["scope"] == "whole_map"
             and r["binning"] == "decile"]
    check("the whole map counts every pixel with a value: 150 x 90",
          sum(int(r["n_px"]) for r in whole) == 13500,
          sum(int(r["n_px"]) for r in whole))
    check("and every pixel changed",
          sum(int(r["changed_px"]) for r in whole) == int(marks.sum()))
    check("the purposive places are labelled as such",
          all(r["note"] == "between-place spread, not design-based"
              for r in cal if r["scope"] == "purposive_places"))
    summary = json.load(open(os.path.join(result["folder"], "summary.json"),
                             encoding="utf-8"))
    check("the summary: 3 done, 1 skipped, the record of changes consistent",
          summary["places"]["purposive_done"]
          + summary["places"]["random_done"] == 3
          and summary["changes_record"]["consistent"] is True,
          (summary["places"], summary["changes_record"]))
    strokes = list(csv.DictReader(open(os.path.join(result["folder"],
                                                    "strokes.csv"),
                                       encoding="utf-8")))
    check("strokes.csv: u over each stroke, from its window, and its place",
          len(strokes) == 2 and all(0.0 <= float(s["u_mean"]) <= 1.0
                                    for s in strokes)
          and [s["place"] for s in strokes] == [first["place_id"],
                                                second["place_id"]],
          strokes)
    book = manifest(folder)
    check("the manifest remembers it",
          [e["kind"] for e in book.get("reports", [])] == ["uncertainty"])
    feeds = g["card_feed"](folder, "uncertainty", book["id"], [])
    check("and the dataset card finds it", feeds is not None
          and feeds["headline"]["kind"] == "probability", feeds)
    panel.describe_correction()
    check("the panel's tooltip says the uncertainty",
          "uncertainty: probabilita x255, read as 1 - p"
          in panel.correction_state.toolTip(),
          panel.correction_state.toolTip())
    said = g["report"](None, panel.correction, campaign_too=False,
                       more=panel.more_checks())[0]
    check("and Check", "uncertainty: probabilita x255, read as 1 - p"
          in said, said[-600:])

    print()
    print("the entropy, band 3")

    def entropy(d):
        d.in_copy.setChecked(True)
        d.select(d.band, 3)
        d.guess()
    source_dialog(entropy)
    card.choose()
    spec = manifest(folder)["uncertainty"]
    check("read as an entropy on 255", (spec["kind"], spec["band"],
                                        spec["scale"])
          == ("entropy", 3, 255.0), spec)
    check("no nodata of 0 read as a value here: entropy is 1 or more "
          "where there is a class", spec["zero_read_as_value"] == 0, spec)
    check("the places done stay done", hook.places.counts()["done"] == 3)
    ds = gdal.Open(copy, gdal.GA_Update)
    ds.GetRasterBand(3).WriteArray(np.zeros((1, 1), np.uint8), 50, 50)
    ds = None
    source_dialog(entropy)
    card.choose()
    spec = manifest(folder)["uncertainty"]
    check("one pixel of 0 under a class: read as 0, and counted",
          spec["zero_read_as_value"] == 1 and pixels(derived)[50, 50] == 0,
          spec)

    print()
    print("another raster, half a pixel off")
    shifted = os.path.join(data, "probabilities_shifted.tif")
    write_tif(shifted, [BANDS[1]], ["probability"],
              gt=(GT[0] + GT[1] / 2, GT[1], 0.0, GT[3], 0.0, GT[5]))

    def other(d):
        d.in_file.setChecked(True)
        d.set_file(shifted)
        SEEN["note"] = d.grid_note.text()
    source_dialog(other)
    card.choose()
    check("the window warns it is not on the grid",
          SEEN.get("note") == "not on the grid of the map: it will be "
          "read nearest-neighbour", SEEN.get("note"))
    spec = manifest(folder)["uncertainty"]
    check("Use asked, and the grid is recorded as resampled",
          spec.get("source") == "file" and spec.get("grid") == "resampled",
          spec)
    utm = os.path.join(data, "probabilities_utm.tif")
    other_srs = osr.SpatialReference()
    other_srs.ImportFromEPSG(32633)
    write_tif(utm, [BANDS[1]], ["probability"], gt=(500000, 1, 0, 4100000,
                                                    0, -1),
              wkt=other_srs.ExportToWkt())
    d = g["UncertaintySource"](section, section, hook)
    d.in_file.setChecked(True)
    d.set_file(utm)
    d.refresh()
    check("one in another coordinate system is refused",
          not d.go.isEnabled() and "another coordinate system"
          in d.grid_note.text(), d.grid_note.text())
    print()
    print("every uncertainty file is the correction's own")
    names = section.own_files()
    check("own_files names them", all(n in names for n in (
        "72_mappa_fold_corrected_uncertainty.tif", "uncertainty_places.csv",
        "uncertainty_places.geojson")), names)
    check("so the folder is not shared with anything else",
          not section.shares_folder(folder))
    section.delete()
    spare = [f for f in os.listdir(root) if f.startswith("fix.removed-")]
    moved = os.listdir(os.path.join(root, spare[0])) if spare else []
    check("Set aside moves every uncertainty_* file with it",
          spare and all(n in moved for n in (
              "72_mappa_fold_corrected_uncertainty.tif",
              "uncertainty_places.csv", "uncertainty_places.geojson")),
          moved)

    print()
    print("the votes of a consensus")
    mask = os.path.join(data, "consensus_mask.tif")
    votes = os.path.join(data, "consensus_votes.tif")
    m = np.where(CLASS > 0, (CLASS % 3) + 1, 0).astype(np.uint8)
    write_tif(mask, [m], ["classes"])
    v_lab = np.where(CLASS > 0, 2, 0).astype(np.uint8)
    v_vot = np.where(CLASS > 0, np.where(CLASS % 2 == 0, 2, 1), 0) \
        .astype(np.uint8)
    write_tif(votes, [v_vot, v_lab], ["votes", "readings_labelled"],
              nodata=None)
    lay2 = styled(mask, "consensus_mask", "layer_mask")
    vfolder = os.path.join(root, "votes_fix")
    section = open_correct(lay2, vfolder, "votes_fix")
    hook = hook_of(section)
    card = hook.card

    def take_votes(d):
        d.in_file.setChecked(True)
        d.set_file(votes)
        d.select(d.file_band, 1)
        d.guess()
        SEEN["kinds"] = d.kind.currentData()
    check("a map of one band: no suggestion",
          card.line.text() == g["UNC_NONE"], card.line.text())
    source_dialog(take_votes)
    card.choose()
    check("votes are offered for a raster of votes and labelled readings",
          SEEN.get("kinds") == "votes", SEEN.get("kinds"))
    vspec = manifest(vfolder).get("uncertainty") or {}
    vu8 = pixels(os.path.join(vfolder,
                              "consensus_mask_corrected_uncertainty.tif"))
    valid = CLASS > 0
    check("kind votes, both bands read",
          vspec.get("kind") == "votes" and vspec.get("labelled_band") == 2,
          vspec)
    check("0 where both readings agree, 127 where one of two does",
          (vu8[valid & (v_vot == 2)] == 0).all()
          and (vu8[valid & (v_vot == 1)] == 127).all()
          and (vu8[~valid] == 255).all())
    panel.close_correction()

    print()
    print("with no uncertainty, nothing changes")
    one = os.path.join(data, "one_band.tif")
    write_tif(one, [CLASS], ["classes"])
    lay3 = styled(one, "one_band", "layer_one")
    ofolder = os.path.join(root, "one_fix")
    section = open_correct(lay3, ofolder, "one_fix")
    card = hook_of(section).card
    check("a map of one band: the card says it has no uncertainty",
          card.line.text() == g["UNC_NONE"] and card.use_box.isHidden()
          and not card.walk.isVisibleTo(card), card.line.text())
    stroke_in(section, {"col": 20, "row": 20, "width": 40, "height": 40})
    panel.close_correction()
    check("no uncertainty file is written",
          not [f for f in os.listdir(ofolder) if "uncertainty" in f],
          os.listdir(ofolder))
    before = manifest(ofolder)
    check("and the manifest has no word of it",
          "uncertainty" not in before and "places" not in before)
    with open(os.path.join(ofolder, "operations.csv"),
              encoding="utf-8") as fh:
        head = next(csv.reader(fh))
    check("operations.csv keeps the 14 columns", len(head) == 14, head)
    section = reopen(ofolder)
    check("opened again", section is not None and section.path.startswith(
        ofolder))
    panel.close_correction()
    after = manifest(ofolder)
    quiet = ("last_opened", "modified")
    check("the manifest is the one it had, but for when it was opened",
          {k: v for k, v in after.items() if k not in quiet}
          == {k: v for k, v in before.items() if k not in quiet},
          sorted(set(after) ^ set(before)))

    print()
    print("a manifest whose uncertainty is gone")
    gone = manifest(ofolder)
    gone["uncertainty"] = {"source": "file", "path": "nowhere.tif",
                           "band": 1, "kind": "probability", "scale": 255.0,
                           "derived": "one_band_corrected_uncertainty.tif"}
    json.dump(gone, open(os.path.join(ofolder, "correction.json"), "w",
                         encoding="utf-8"))
    section = reopen(ofolder)
    card = hook_of(section).card
    check("Correct opens, and the card says it is not there",
          card.line.text() == "the uncertainty named in the manifest is not "
          "there: choose it again.", card.line.text())
    said = g["report"](None, panel.correction, campaign_too=False,
                       more=panel.more_checks())[0]
    check("Check calls it a problem",
          "the uncertainty named in the manifest is not there" in said
          and "problem" in said.split("\n")[0], said[:300])
    panel.close_correction()
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
