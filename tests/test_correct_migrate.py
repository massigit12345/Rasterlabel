"""A correction kept inside an old annotation campaign still opens, and loses
nothing on the way to a campaign of its own.

Before corrections had a campaign of their own, each was a record in
campaign.json and a folder of the campaign's, <campaign>/corrections/<name>,
with the working copy and operations.csv in it. People have those. So this
suite makes one exactly as that build made it, an hour of strokes in the copy
and in the log, opens the campaign, presses Correct and picks it, and asks:

  it is offered, and says it opens as a correction campaign of its own;
  a correction.json is written beside the copy, carrying the record's
  classes, count, areas and pairs, and where it came from;
  the copy of that build, with its "corrected" band, is given the bands of
  the map it corrects: the band moves out to <copy>_changes.tif, every pixel
  it marked still marked, the classes pixel for pixel what they were, and
  the .qml the corrected map opens with is written beside it;
  operations.csv is byte for byte what it was, and nothing is deleted;
  the record stays in campaign.json, with a pointer to the new manifest,
  and that is the only thing written into it;
  the campaign reconciles quietly afterwards;
  next time the correction is offered from the recent list, not twice;
  a record that never had classes shows the classes window once;
  closing the annotation campaign leaves Correct open, its layer and its log;
  Check reports the correction, and a moved record whose folder has gone.

Needs PyQt5 or PyQt6, and numpy. Not GDAL: see correctkit.py.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correctkit as K                                             # noqa: E402
import numpy as np                                                 # noqa: E402

g, check = K.g, K.check

root = tempfile.mkdtemp(prefix="rl_correct_migrate_")
K.HOME[0] = root
camp_folder = os.path.join(root, "aragona_2025")
os.makedirs(camp_folder)
open(os.path.join(camp_folder, "annotation.gpkg"), "wb").close()

MAP = np.array([[1, 1, 3, 3], [1, 2, 2, 3], [2, 2, 3, 3]], np.uint8)
source = os.path.join(root, "data", "mask_2025.tif")
K.write_map(source, MAP, 0, gt=(400000.0, 0.5, 0.0, 4100000.0, 0.0, -0.5))
layer = K.add_layer(K.Layer(source, "mask_2025"))


def legacy(name, classes):
    """A correction as the build before this one left it on disk."""
    where = os.path.join(camp_folder, "corrections", name)
    copy = os.path.join(where, "mask_2025_corrected.tif")
    painted = MAP.copy()
    painted[0, 0] = 3
    K.write_map(copy, painted, 0, gt=(400000.0, 0.5, 0.0, 4100000.0, 0.0, -0.5),
                flagged=True)
    K.DISK[K.key(copy)]["bands"][1].array[0, 0] = 1     # the pixel it moved
    with open(os.path.join(where, "operations.csv"), "w", encoding="utf-8",
              newline="") as f:
        f.write("n,when,operator,into,only,pixels,swept_m2,changed_m2,x,y,col,"
                "row,width,height\n1,2026-03-01T10:00:00,MG,water,crust,1,"
                "0.250,0.250,400000.25,4099999.75,0,0,1,1\n")
    record = {"name": name, "source": source, "band": 1, "files": [copy],
              "operations": 1, "changed_m2": 0.25, "swept_m2": 0.25,
              "pairs": {"crust -> water": [1, 0.25]},
              "created": "2026-03-01T09:00:00",
              "last_opened": "2026-03-01T10:00:00"}
    if classes:
        record["classes"] = classes
    return record, copy


def bytes_of(path):
    with open(path, "rb") as f:
        return f.read()


CLASSES = [{"code": 1, "name": "crust", "colour": "#b0651f"},
           {"code": 2, "name": "mud", "colour": "#7c5b3f"},
           {"code": 3, "name": "water", "colour": "#2f6f9f"}]
first, first_copy = legacy("correction_1", CLASSES)
second, second_copy = legacy("old_build", None)

camp = g["Campaign"](camp_folder)
camp.data = {"program": "RasterLabel", "version": "1.0", "id": "abc123",
             "name": "aragona_2025", "with_tiles": False, "operator": "mg",
             "operators": ["mg"],
             "classes": [{"code": 1, "name": "legend one", "colour": "#000000"}],
             "grid": {"reference_raster": source, "crs": "EPSG:32633",
                      "origin": [400000.0, 4100000.0], "pixel_crs": [0.5, 0.5],
                      "pixel_m": [0.5, 0.5]},
             "layers": [], "tiles": [], "cutouts": [],
             "corrections": [first, second]}
camp.save()
before = {p: bytes_of(p) for p in (
    os.path.join(os.path.dirname(first_copy), "operations.csv"),
    os.path.join(os.path.dirname(second_copy), "operations.csv"))}
classes_before = {p: K.read_map(p) for p in (first_copy, second_copy)}
listing = K.everything_under(camp_folder)

panel = g["Panel"]()
panel.campaign = camp
panel.update_enabled()
SEEN = {}

try:
    print("the old correction is offered, and opens as a campaign of its own")

    def pick(name):
        def answer(d):
            SEEN["offered"] = [(d.existing.itemText(i), d.existing.itemData(i))
                               for i in range(d.existing.count())]
            d.existing.setCurrentIndex(d.existing.findData("legacy:" + name))
            d.refresh()
            SEEN["note"] = d.note.text()
            return 1
        return answer

    K.ANSWERS["OpenCorrection"] = pick("correction_1")
    panel.toggle_module(1)
    section = panel.section
    check("Correct opened on it", type(section).__name__ == "CorrectionSection",
          K.BOXES[-1:])
    check("both old records were offered",
          [d for _, d in SEEN["offered"] if d.startswith("legacy:")] ==
          ["legacy:correction_1", "legacy:old_build"],
          SEEN["offered"])
    check("saying they open as a correction campaign of their own",
          all("opens as its own correction campaign" in t
              for t, d in SEEN["offered"] if d.startswith("legacy:")))
    check("and the window said nothing is moved", "nothing is moved" in SEEN["note"])

    print()
    print("nothing lost on the way")
    manifest = os.path.join(os.path.dirname(first_copy), "correction.json")
    check("correction.json is written beside the copy", os.path.exists(manifest))
    book = json.load(open(manifest, encoding="utf-8"))
    check("it carries the classes of the record", book["classes"] == CLASSES,
          book["classes"])
    check("and its count, areas and pairs",
          book["operations"] == 1 and book["changed_m2"] == 0.25
          and book["swept_m2"] == 0.25
          and book["pairs"] == {"crust -> water": [1, 0.25]}, book)
    check("and when it was made", book["created"] == "2026-03-01T09:00:00")
    check("the copy is named relative to its folder",
          book["working_copy"] == "mask_2025_corrected.tif")
    check("the grid is read from the copy: half a metre",
          book["grid"]["pixel_m"] == [0.5, 0.5], book["grid"])
    check("the operator is the campaign's, in capitals", book["operator"] == "MG")
    check("and it says where it came from",
          book["migrated_from"]["campaign_id"] == "abc123"
          and book["migrated_from"]["correction"] == "correction_1")
    check("operations.csv is byte for byte what it was",
          all(bytes_of(p) == b for p, b in before.items()))
    here = os.path.join("corrections", "correction_1")
    check("nothing was deleted, and only the manifest, the record of changes "
          "and the style were added beside the copy",
          sorted(set(K.everything_under(camp_folder)) - set(listing)) ==
          [os.path.join(here, "correction.json"),
           os.path.join(here, "mask_2025_corrected.qml"),
           os.path.join(here, "mask_2025_corrected_changes.tif"),
           os.path.join(here, "rasterlabel.log")]
          and not set(listing) - set(K.everything_under(camp_folder)),
          sorted(set(K.everything_under(camp_folder)) ^ set(listing)))

    print()
    print("the copy of the old build is given the bands of the map it corrects")
    copy_bands = K.DISK[K.key(first_copy)]["bands"]
    check("its 'corrected' band is gone from it: one band, as the map has",
          [b.GetDescription() for b in copy_bands] == ["classes"],
          [b.GetDescription() for b in copy_bands])
    check("its classes are pixel for pixel what they were",
          (K.read_map(first_copy) == classes_before[first_copy]).all())
    changes = os.path.join(os.path.dirname(first_copy),
                           "mask_2025_corrected_changes.tif")
    marks = K.read_map(changes)
    check("and the pixel a person moved is still marked, in the file beside it",
          int(marks.sum()) == 1 and marks[0, 0] == 1, marks)
    check("the manifest names that file and says when it moved out",
          book.get("changes") == "mask_2025_corrected_changes.tif"
          and book.get("changes_moved_out", {}).get("pixels") == 1
          and book["changes_moved_out"].get("from_band") == 2, book)
    log_text = open(os.path.join(os.path.dirname(first_copy),
                                 "rasterlabel.log"), encoding="utf-8").read()
    check("and one line of the log says it",
          log_text.count("brought to the bands of the map it corrects") == 1,
          [l for l in log_text.splitlines() if "brought" in l])
    style = os.path.join(os.path.dirname(first_copy), "mask_2025_corrected.qml")
    text = open(style, encoding="utf-8").read()
    check("the .qml beside it draws band 1 in the record's classes",
          'type="paletted"' in text and 'band="1"' in text
          and all('value="%d" color="%s"' % (c["code"], c["colour"]) in text
                  and 'label="%s"' % c["name"] in text for c in CLASSES), text)
    check("the section paints with the record's classes",
          [c["name"] for c in section.classes()] == ["crust", "mud", "water"])
    check("and counts on from where it was", section.operations == 1)

    print()
    print("the annotation manifest keeps the record, with a pointer")
    on_disk = json.load(open(os.path.join(camp_folder, "campaign.json"),
                             encoding="utf-8"))
    rec = [r for r in on_disk["corrections"] if r["name"] == "correction_1"][0]
    check("the record is still there, every key of it",
          all(rec[k] == first[k] for k in first if k != "moved_to"), rec)
    # kept relative to the campaign when it lies inside it, so the folder can
    # be moved; a record written before holds the whole path, and is read the
    # same way
    check("with moved_to pointing at the new manifest",
          os.path.normcase(os.path.normpath(os.path.join(
              camp_folder, rec.get("moved_to") or ""))) ==
          os.path.normcase(os.path.normpath(manifest)), rec.get("moved_to"))
    check("and written relative to the campaign",
          not os.path.isabs(rec.get("moved_to") or "/"), rec.get("moved_to"))
    check("the other record is untouched", "moved_to" not in
          [r for r in on_disk["corrections"] if r["name"] == "old_build"][0])
    check("the campaign reconciles quietly", camp.reconcile() == [],
          camp.reconcile())
    # and a moved record whose files have since gone is not a disagreement:
    # the correction answers for them from its own folder
    saved_files = rec["files"]
    camp.data["corrections"][0]["files"] = ["/nowhere/gone.tif"]
    check("not even when the old path is gone", camp.reconcile() == [],
          camp.reconcile())
    camp.data["corrections"][0]["files"] = saved_files

    print()
    print("closing the annotation campaign leaves Correct alone")
    log_file = os.path.join(os.path.dirname(first_copy), "rasterlabel.log")
    check("while Correct is open the log is beside the correction",
          g["_LOG"]["path"] == log_file, g["_LOG"]["path"])
    panel.close_campaign()
    check("the campaign is closed", panel.campaign is None)
    check("Correct is still open, on the same correction",
          panel.section is section and panel.correction is not None)
    check("and the log still goes beside it", g["_LOG"]["path"] == log_file)
    check("Annotate and Objects are off again, Correct and Cutouts on",
          [b.isEnabled() for b in panel.modules] == [False, True, False, True],
          [b.isEnabled() for b in panel.modules])

    print()
    print("Check reports the correction")
    text, bad, notes = g["report"](None, panel.correction)
    check("a section of its own", "THE CORRECTION" in text)
    check("it finds the manifest whole", "the manifest has no" not in text, text)
    check("every code of the copy has a class", "every code in the copy has a "
          "class" in text, [l for l in text.splitlines() if "code" in l])
    check("and says where it is", "correction  %s" % os.path.dirname(first_copy)
          in text)
    check("with no campaign open that is a note, not an alarm",
          "no annotation campaign is open" in text and "Correct and Cutouts do "
          "not" in text)
    text, bad, notes = g["report"](None, panel.correction, campaign_too=False)
    check("Check in CORRECTION reports the correction alone",
          "THE CORRECTION" in text and "THE CAMPAIGN" not in text
          and "no annotation campaign is open" not in text, text)
    # The correction lives as long as Correct: closing the module closes it.
    panel.close_module()
    check("closing the module closes the correction with it",
          panel.section is None and panel.correction is None)

    print()
    print("next time it comes from the recent list, once")
    panel.campaign = camp
    K.ANSWERS["OpenCorrection"] = pick("old_build")
    def look(d):
        SEEN["rows"] = [r["value"].value() for r in d.rows]
        SEEN["open"] = [r["value"].isEnabled() for r in d.rows]
        return 1

    K.ANSWERS["ConfirmClasses"] = look
    panel.toggle_module(1)
    offered = SEEN["offered"]
    check("correction_1 is offered as a correction campaign",
          "open:" + manifest in [d for _, d in offered], offered)
    check("and no longer as a record of the campaign",
          "legacy:correction_1" not in [d for _, d in offered], offered)
    check("a record with no classes shows the classes window once",
          SEEN.get("rows") == [1, 2, 3], SEEN.get("rows"))
    # Its copy already holds an hour of strokes: a value renumbered there
    # would leave those pixels under a number with no class.
    check("with the values the copy holds locked: names and colours only",
          SEEN.get("open") == [False, False, False], SEEN.get("open"))
    second_book = json.load(open(os.path.join(os.path.dirname(second_copy),
                                              "correction.json"),
                                 encoding="utf-8"))
    check("and the confirmed classes go into its manifest",
          [c["code"] for c in second_book["classes"]] == [1, 2, 3]
          and second_book.get("classes_confirmed"), second_book["classes"])
    check("its classes are untouched",
          (K.read_map(second_copy) == classes_before[second_copy]).all())
    check("and it too lost its 'corrected' band to the file beside it",
          len(K.DISK[K.key(second_copy)]["bands"]) == 1
          and second_book.get("changes") == "mask_2025_corrected_changes.tif",
          second_book)
    panel.close_correction()

    print()
    print("a moved record whose folder has gone is noted by Check")
    shutil.move(os.path.dirname(second_copy), os.path.join(root, "elsewhere"))
    text, _, _ = g["report"](camp)
    check("it is noted", "correction 'old_build' was moved to its own campaign"
          in text, [l for l in text.splitlines() if "moved" in l])
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
