"""A new correction, when something is already there.

New correction used to look at what was already on disk in three ways and get
two of them wrong. A map was taken for a working copy when a correction.json
sat beside it, so a correction made in the map's own folder made the ORIGINAL
look like a copy, and it could never be corrected again. The flag band, the
one sign a working copy then carried inside it, was not looked at. A copy refused
was refused with a message and nothing else, not even the way to its owner.
A map that already had a correction got a second one without a word. And a
folder that already held <map>_corrected.tif with no correction.json had that
copy reused in silence: a new correction began on somebody's old work.

So this suite starts from a panel with no campaign and walks each case:

  a map with a correction.json beside it that names another file as its
  copy is not a working copy: the false positive of the map's own folder;
  the map's own folder is allowed, after a warning that can be cancelled;
  a map that is a working copy is told by the "corrected" band a copy of
  an earlier build carries, then by the record of changed pixels every copy
  now has beside it (<copy>_changes.tif), then by its name, then by a
  manifest that names it; the record itself is no map either; its owner is
  offered, found beside it, in the recent list or in the annotation
  campaign, and opened;
  with no owner found the user is told how to open it by hand;
  a map that already has a correction offers Open that one, Make a new
  correction, Cancel, and each does what it says;
  a folder holding the copy of this map and no manifest offers Resume it,
  Start from a fresh copy, Cancel: resuming keeps every corrected pixel,
  shows the classes with the copy's values locked and reads the counters
  back from operations.csv; starting afresh sets the old copy, its record
  of changes and its log aside, never deletes them; a copy with neither a
  record of changes nor the band of an earlier build, or of another size,
  cannot be resumed and only a fresh copy is offered; Cancel writes nothing.

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

MAP = np.array([[0, 0, 3, 3, 7, 7],
                [0, 3, 3, 3, 7, 7],
                [3, 3, 7, 7, 7, 12],
                [3, 3, 7, 12, 12, 12]], dtype=np.uint8)

root = tempfile.mkdtemp(prefix="rl_correct_existing_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
panel = g["Panel"]()

# ------------------------------------------------------------ answering
ASKS = []           # (text, detail, buttons) of every question asked
PRESS = []          # the labels to press, one per question, in order


def answer_box(d):
    """A QMessageBox from ask_among: record it and press the next label."""
    labels = [b.text().replace("&", "") for b in d.buttons()]
    ASKS.append((d.text(), d.informativeText(), labels))
    want = PRESS.pop(0) if PRESS else "Cancel"
    for b in d.buttons():
        if b.text().replace("&", "") == want:
            b.click()
            break
    else:
        ASKS.append(("no button called %s" % want, "", labels))
    # The next question, if any, is answered the same way.
    K.ANSWERS["QMessageBox"] = answer_box
    return 0


def new_on(layer, folder, name="fix"):
    def fill(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText(name)
        d.raster.setCurrentIndex(d.raster.findData(layer.id()))
        d.fill_bands()
        d.folder.setText(folder)
        d.operator.setText("ann")
        SEEN["note"] = d.note.text()
        return 1
    return fill


SEEN = {}


def accept_classes(d):
    SEEN["locked"] = {r["value"].value(): not r["value"].isEnabled()
                      for r in d.rows}
    return 1


def press(*labels, classes=True):
    """Open Correct for a new correction, answering the questions with these
    labels in order, and the classes window with Ok when it comes."""
    del ASKS[:]
    PRESS[:] = list(labels)
    K.ANSWERS["QMessageBox"] = answer_box
    if classes:
        K.ANSWERS["ConfirmClasses"] = accept_classes
    K.BOXES.clear()
    SEEN.pop("locked", None)
    panel.toggle_module(1)
    K.ANSWERS.pop("QMessageBox", None)
    K.ANSWERS.pop("ConfirmClasses", None)
    return panel.section


def close():
    # Closing Correct closes the correction with it.
    if panel.section is not None:
        panel.close_module()
    assert panel.correction is None


def a_map(name):
    path = os.path.join(root, "maps_" + name, name + ".tif")
    K.write_map(path, MAP, 255)
    return path, K.add_layer(K.Layer(path, name, lid="layer_" + name))


def manifest_of(folder):
    with open(os.path.join(folder, "correction.json"), encoding="utf-8") as f:
        return json.load(f)


def opened():
    return panel.correction.manifest_path if panel.correction else None


try:
    print("the map's own folder: allowed after a warning, and no false copy")
    src, lay = a_map("landcover")
    own = os.path.dirname(src)
    K.ANSWERS["OpenCorrection"] = new_on(lay, own)
    press("Cancel", classes=False)
    check("the warning names the map's own folder",
          ASKS and "folder of the map itself" in ASKS[0][0], ASKS)
    check("the window had said so already, before Ok",
          "the map's own" in SEEN["note"], SEEN["note"])
    check("Cancel writes nothing",
          panel.section is None
          and not os.path.exists(os.path.join(own, "correction.json"))
          and not os.path.exists(os.path.join(own, "landcover_corrected.tif")))

    K.ANSWERS["OpenCorrection"] = new_on(lay, own)
    press("Use this folder anyway")
    check("Use this folder anyway makes the correction there",
          opened() == os.path.join(own, "correction.json"), opened())
    close()
    check("with correction.json now beside the original, the original is "
          "not a working copy", g["why_a_working_copy"](src) is None,
          g["why_a_working_copy"](src))
    check("its copy is, by the record of changed pixels beside it",
          "landcover_corrected_changes.tif beside it records which pixels"
          in (g["why_a_working_copy"](
              os.path.join(own, "landcover_corrected.tif")) or ""),
          g["why_a_working_copy"](os.path.join(own, "landcover_corrected.tif")))
    check("and that record is no map to correct either",
          "record of which pixels a person changed" in (g["why_a_working_copy"](
              os.path.join(own, "landcover_corrected_changes.tif")) or ""),
          g["why_a_working_copy"](
              os.path.join(own, "landcover_corrected_changes.tif")))

    print()
    print("a map that already has a correction")
    second = os.path.join(root, "second")
    K.ANSWERS["OpenCorrection"] = new_on(lay, second, "second")
    press("Cancel", classes=False)
    check("the map is no longer refused as a copy: it asks about the "
          "correction it has", ASKS and "already has the correction 'fix'"
          in ASKS[0][0], ASKS)
    check("offering Open that one, Make a new correction, Cancel",
          ASKS and ASKS[0][2] == ["Open that one", "Make a new correction",
                                  "Cancel"], ASKS)
    check("Cancel writes nothing", panel.section is None
          and not os.path.exists(second))

    K.ANSWERS["OpenCorrection"] = new_on(lay, second, "second")
    press("Open that one", classes=False)
    check("Open that one opens it, with no classes window",
          opened() == os.path.join(own, "correction.json")
          and "ConfirmClasses" not in K.ASKED[-1:], (opened(), K.ASKED[-2:]))
    check("and makes nothing new", not os.path.exists(second))
    close()

    K.ANSWERS["OpenCorrection"] = new_on(lay, second, "second")
    press("Make a new correction")
    check("Make a new correction makes a second one, in its own folder",
          opened() == os.path.join(second, "correction.json"), opened())
    close()
    check("both are offered next time",
          len(g["corrections_of"](src)) == 2, g["corrections_of"](src))

    print()
    print("a working copy chosen as the map: its owner is offered")
    copy = os.path.join(second, "landcover_corrected.tif")
    copy_layer = K.add_layer(K.Layer(copy, "the copy", lid="layer_copy"))
    elsewhere = os.path.join(root, "third")
    K.ANSWERS["OpenCorrection"] = new_on(copy_layer, elsewhere, "third")
    press("Cancel", classes=False)
    check("it is said to be a working copy, and why",
          ASKS and "already the working copy" in ASKS[0][0]
          and "records which pixels a person changed" in ASKS[0][0], ASKS)
    check("its owner is named", ASKS and "'second'" in ASKS[0][1], ASKS)
    check("with Open the correction that owns it and Cancel",
          ASKS and ASKS[0][2] == ["Open the correction that owns it",
                                  "Cancel"], ASKS)
    check("Cancel writes nothing", panel.section is None
          and not os.path.exists(elsewhere))
    K.ANSWERS["OpenCorrection"] = new_on(copy_layer, elsewhere, "third")
    press("Open the correction that owns it", classes=False)
    check("and that button opens the owner",
          opened() == os.path.join(second, "correction.json"), opened())
    close()
    K.LOADED.pop(copy_layer.id(), None)

    # A copy renamed and carried off with its record of changes, renamed
    # alike: the record says so, and nothing beside them says whose it is.
    carried = os.path.join(root, "carried_new", "renamed.tif")
    K.write_map(carried, MAP, 255)
    K.write_changes(os.path.join(root, "carried_new", "renamed_changes.tif"),
                    MAP.shape, (500000.0, 2.0, 0.0, 4100000.0, 0.0, -2.0))
    check("a copy renamed with its record is told by the record",
          "renamed_changes.tif beside it" in (
              g["why_a_working_copy"](carried) or ""),
          g["why_a_working_copy"](carried))

    # A copy of an earlier build renamed and carried off on its own: only its
    # band says so, and nothing beside it says whose it is.
    stray = os.path.join(root, "carried", "renamed.tif")
    K.write_map(stray, MAP, 255, flagged=True)
    stray_layer = K.add_layer(K.Layer(stray, "renamed", lid="layer_stray"))
    K.ANSWERS["OpenCorrection"] = new_on(stray_layer, elsewhere, "third")
    press(classes=False)
    check("a copy of an earlier build renamed is still told by its band, with "
          "no owner found: the user is told how to open it",
          not ASKS and any("'corrected' band" in t
                           and "Open a correction.json" in t
                           for _, t in K.BOXES), (ASKS, K.BOXES))
    check("and nothing is written", not os.path.exists(elsewhere))

    # The same copy, now named by a manifest elsewhere that was opened lately.
    keeper = os.path.join(root, "keeper")
    os.makedirs(keeper)
    with open(os.path.join(keeper, "correction.json"), "w",
              encoding="utf-8") as f:
        json.dump({"program": "RasterLabel", "kind": "correction",
                   "name": "kept by hand", "files": [stray], "band": 1,
                   "source": src}, f)
    g["remember_correction"](os.path.join(keeper, "correction.json"))
    owner = g["owner_of_copy"](stray)
    check("its owner is found in the recent list",
          owner and owner[1] == os.path.join(keeper, "correction.json")
          and owner[2] == "kept by hand", owner)
    g["forget_correction"](os.path.join(keeper, "correction.json"))
    K.LOADED.pop(stray_layer.id(), None)

    class Campaign(object):
        folder = os.path.join(root, "campaign")
        data = {"corrections": [{"name": "old one", "files": [stray]}]}

    check("and in the records of the annotation campaign",
          g["owner_of_copy"](stray, Campaign()) == ("legacy", "old one",
                                                    "old one"),
          g["owner_of_copy"](stray, Campaign()))
    named = os.path.join(root, "named", "other_corrected.tif")
    K.write_map(named, MAP, 255)
    check("a copy with no band is told by its name",
          "_corrected" in (g["why_a_working_copy"](named) or ""))
    pointed = os.path.join(root, "pointed")
    K.write_map(os.path.join(pointed, "plain.tif"), MAP, 255)
    with open(os.path.join(pointed, "correction.json"), "w",
              encoding="utf-8") as f:
        json.dump({"working_copy": "plain.tif", "source": "x.tif"}, f)
    check("and by a manifest beside it that names that very file",
          "names it as its working copy" in (g["why_a_working_copy"](
              os.path.join(pointed, "plain.tif")) or ""))

    print()
    print("a folder holding the copy of this map with no correction.json")
    rsrc, rlay = a_map("roads")
    left = os.path.join(root, "leftover")
    leftover = os.path.join(left, "roads_corrected.tif")
    g["build_copy"](rsrc, leftover)
    g["build_changes"](leftover, os.path.join(left,
                                              "roads_corrected_changes.tif"))
    K.DISK[K.key(leftover)]["bands"][0].array[0, 0:2] = 12   # two pixels a
    K.DISK[K.key(os.path.join(left, "roads_corrected_changes.tif"))][
        "bands"][0].array[0, 0:2] = 1                        # person corrected
    columns = ",".join(g["CorrectionSection"].LOG_COLUMNS)
    with open(os.path.join(left, "operations.csv"), "w",
              encoding="utf-8") as f:
        f.write(columns + "\n"
                "1,2026-10-07 10:00:00,ANN,forest,every class,2,8.000,8.000,"
                "0,0,0,0,2,1\n"
                "2,2026-10-07 10:01:00,ANN,forest,water,1,4.000,0.000,"
                "0,0,0,0,1,1\n")
    corrected = K.read_map(leftover)
    K.ANSWERS["OpenCorrection"] = new_on(rlay, left, "roads fix")
    press("Cancel", classes=False)
    check("it is asked about, never reused in silence",
          ASKS and "roads_corrected.tif" in ASKS[0][0]
          and ASKS[0][2] == ["Resume it", "Start from a fresh copy", "Cancel"],
          ASKS)
    check("Cancel writes nothing and touches nothing",
          not os.path.exists(os.path.join(left, "correction.json"))
          and np.array_equal(K.read_map(leftover), corrected)
          and sorted(os.listdir(left)) == ["operations.csv",
                                           "roads_corrected.tif",
                                           "roads_corrected_changes.tif"],
          os.listdir(left))

    K.ANSWERS["OpenCorrection"] = new_on(rlay, left, "roads fix")
    press("Resume it")
    check("Resume it opens a correction on that copy",
          opened() == os.path.join(left, "correction.json"), opened())
    check("the corrected pixels are still there",
          np.array_equal(K.read_map(leftover), corrected))
    check("and so is the record of which ones a person changed",
          int(K.read_map(os.path.join(left, "roads_corrected_changes.tif"))
              .sum()) == 2)
    check("the classes were shown with the copy's values locked",
          SEEN.get("locked") and all(SEEN["locked"].values()), SEEN)
    book = manifest_of(left)
    check("the counters are read back from operations.csv",
          book["operations"] == 2 and abs(book["changed_m2"] - 8.0) < 1e-9
          and abs(book["swept_m2"] - 12.0) < 1e-9
          and book["pairs"] == {"every class -> forest": [1, 8.0],
                                "water -> forest": [1, 0.0]}, book)
    check("and the manifest says it was resumed", bool(book.get("resumed")))
    check("the section counts them too", panel.section.operations == 2,
          panel.section.operations)
    close()

    fsrc, flay = a_map("fields")
    left2 = os.path.join(root, "leftover2")
    old = os.path.join(left2, "fields_corrected.tif")
    g["build_copy"](fsrc, old)
    g["build_changes"](old, os.path.join(left2, "fields_corrected_changes.tif"))
    K.DISK[K.key(old)]["bands"][0].array[:] = 7
    with open(os.path.join(left2, "operations.csv"), "w",
              encoding="utf-8") as f:
        f.write(columns + "\n")
    K.ANSWERS["OpenCorrection"] = new_on(flay, left2, "fields fix")
    press("Start from a fresh copy")
    check("Start from a fresh copy opens a new correction",
          opened() == os.path.join(left2, "correction.json"), opened())
    spare = [f for f in os.listdir(left2) if f.startswith("set_aside_")]
    check("the old copy, its record of changes and its log are set aside, "
          "not deleted",
          len(spare) == 1 and sorted(os.listdir(os.path.join(left2, spare[0])))
          == ["fields_corrected.tif", "fields_corrected_changes.tif",
              "operations.csv"],
          (os.listdir(left2), spare))
    check("and the new copy has a new, empty record of its own",
          int(K.read_map(os.path.join(left2, "fields_corrected_changes.tif"))
              .sum()) == 0)
    check("and the new copy is the map itself",
          np.array_equal(K.read_map(old), MAP))
    check("with a manifest of a fresh correction",
          manifest_of(left2)["operations"] == 0
          and "resumed" not in manifest_of(left2))
    close()

    # Windows refuses to move a file another program holds open. The copy is
    # moved first and the log after it: the log refusing must put the copy
    # back, not leave the folder half set aside.
    hsrc, hlay = a_map("held")
    held = os.path.join(root, "held")
    g["build_copy"](hsrc, os.path.join(held, "held_corrected.tif"))
    K.DISK[K.key(os.path.join(held, "held_corrected.tif"))][
        "bands"][0].array[:] = 7
    with open(os.path.join(held, "operations.csv"), "w",
              encoding="utf-8") as f:
        f.write(columns + "\n")
    real_replace = os.replace

    def refuse_the_log(a, b):
        if os.path.basename(a) == "operations.csv" and "set_aside_" in b:
            raise PermissionError(32, "the file is in use", a)
        return real_replace(a, b)

    os.replace = refuse_the_log
    K.BOXES.clear()
    try:
        K.ANSWERS["OpenCorrection"] = new_on(hlay, held, "held fix")
        press("Start from a fresh copy")
    finally:
        os.replace = real_replace
    check("a file that cannot be moved stops the correction",
          opened() is None and any("Nothing was moved" in t
                                   for _, t in K.BOXES), (opened(), K.BOXES))
    check("and whatever had been moved is put back",
          sorted(os.listdir(held)) == ["held_corrected.tif", "operations.csv"]
          and (K.read_map(os.path.join(held, "held_corrected.tif")) == 7).all(),
          os.listdir(held))
    close()

    print()
    print("a leftover that cannot be resumed")
    for label, write in (
            ("with no record of changes", lambda p: K.write_map(p, MAP, 255)),
            ("of another size", lambda p: K.write_map(
                p, MAP[:2, :3], 255, flagged=True))):
        msrc, mlay = a_map("m_" + label.split()[-1])
        mleft = os.path.join(root, "mleft_" + label.split()[-1])
        write(os.path.join(mleft, os.path.basename(msrc)[:-4]
                           + "_corrected.tif"))
        K.ANSWERS["OpenCorrection"] = new_on(mlay, mleft, "m")
        press("Cancel", classes=False)
        check("a copy %s offers only a fresh copy, and says why" % label,
              ASKS and ASKS[0][2] == ["Start from a fresh copy", "Cancel"]
              and "cannot be resumed" in ASKS[0][1], ASKS)
        check("and Cancel leaves it there",
              os.listdir(mleft) == [os.path.basename(msrc)[:-4]
                                    + "_corrected.tif"], os.listdir(mleft))

    print()
    print("Open and the recent list are as they were")

    def recent(d):
        d.existing.setCurrentIndex(d.existing.findData(
            "open:" + os.path.join(left, "correction.json")))
        return 1

    K.ANSWERS["OpenCorrection"] = recent
    press(classes=False)
    check("a correction in the recent list opens with no question",
          opened() == os.path.join(left, "correction.json") and not ASKS,
          (opened(), ASKS))
    close()

    print()
    print("a manifest cannot send the working copy out of its folder")
    where = os.path.join(root, "owned")
    book = K.g["CorrectionCampaign"](where)
    for written, name in (("map_corrected.tif", "map_corrected.tif"),
                          ("..\..\other\stolen.tif", "stolen.tif"),
                          ("../elsewhere/stolen.tif", "stolen.tif"),
                          ("C:\data\stolen.tif", "stolen.tif"),
                          ("/etc/stolen.tif", "stolen.tif")):
        book.data = {"working_copy": written}
        check("%s is looked for as %s in its own folder" % (written, name),
              book.working_path == os.path.join(where, name),
              book.working_path)
    book.data = {"files": [os.path.join(root, "hand", "written.tif")]}
    check("a record written by hand keeps the path in files",
          book.working_path == os.path.join(root, "hand", "written.tif"),
          book.working_path)
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
