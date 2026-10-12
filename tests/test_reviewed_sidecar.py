"""The record of the ground the strokes of Correct swept, kept beside the copy.

Correct with QGIS faked (correctkit), through the panel's own doors:

- a new correction has its record from the start, <map>_corrected_reviewed.
  tif, empty, and its manifest names it with reviewed_since 0;
- a stroke with FROM and TO over a 2 x 2 window marks the four pixels of its
  footprint as swept and only the ones it changed as changed; its undo puts
  both records back; a stroke refused by "ask before each change", and a
  stroke with nothing to change, leave the record as it was;
- a correction of an earlier build, with no record and seven strokes, opens
  without one and with its manifest as it was (but for the time it was
  last opened, which the panel always writes); its first
  stroke starts the record, empty but for that stroke, and the manifest
  then says reviewed_since 7; Check says so, and so does the setup of
  Model vs corrected, through the swept count;
- the record is the correction's own: own_files names it, the reports/
  folder too, so a folder holding them is not taken for a shared one; the
  record chosen as a map to correct is refused; reconcile says a record the
  manifest names that is gone; the newest report gives the quiet line
  under the tally.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import correctkit as K                                             # noqa: E402
import numpy as np                                                 # noqa: E402

g, check = K.g, K.check

OLIVE, CROP, MUD, NODATA = 1, 2, 3, 255
MAP = np.array([
    [OLIVE, CROP, CROP, MUD],
    [OLIVE, OLIVE, CROP, MUD],
    [MUD, MUD, CROP, CROP],
    [MUD, MUD, MUD, NODATA],
], dtype=np.uint8)

root = tempfile.mkdtemp(prefix="rl_reviewed_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
source = os.path.join(root, "data", "model.tif")
K.write_map(source, MAP, NODATA)
styled = K.Paletted(None, 1, [
    K.Paletted.Class(OLIVE, "#6b8e23", "olive"),
    K.Paletted.Class(CROP, "#e6c229", "crop"),
    K.Paletted.Class(MUD, "#8b5a2b", "mud")])
thematic = K.add_layer(K.Layer(source, "model", styled))
panel = g["Panel"]()


def new_correction(folder):
    def answer(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText(os.path.basename(folder))
        d.raster.setCurrentIndex(d.raster.findData(thematic.id()))
        d.fill_bands()
        d.folder.setText(folder)
        d.operator.setText("ann")
        return 1
    K.ANSWERS["OpenCorrection"] = answer
    K.ANSWERS["ConfirmClasses"] = lambda d: 1
    panel.toggle_module(1)
    return panel.section


def open_existing(manifest):
    def answer(d):
        d.existing.setCurrentIndex(d.existing.findData("open:" + manifest))
        return 1
    K.ANSWERS["OpenCorrection"] = answer
    panel.open_correction_campaign()
    return panel.section


def stroke(section, rows, cols, from_code, into):
    inside = np.ones((rows[1] - rows[0], cols[1] - cols[0]), bool)
    section.mask_of = lambda geom: (cols[0], rows[0], inside)
    if from_code is None:
        section.choose_from(None)
    else:
        section.choose_from(from_code)
    section.choose_class(into)
    section.paint(K.Stroke())


def hook_of(section):
    found = [h for h in section.stroke_hooks
             if type(h).__name__ == "ReviewedHook"]
    return found[0] if found else None


try:
    print("a new correction has the record from the start")
    folder = os.path.join(root, "fix")
    section = new_correction(folder)
    check("Correct opened", type(section).__name__ == "CorrectionSection",
          K.BOXES[-1:])
    copy = section.path
    reviewed = os.path.join(folder, "model_corrected_reviewed.tif")
    changes = os.path.join(folder, "model_corrected_changes.tif")
    check("the record is beside the copy, named after it",
          os.path.exists(reviewed) and K.key(reviewed) in K.DISK,
          sorted(os.listdir(folder)))
    check("one band, 'reviewed', all zero",
          [b.GetDescription() for b in K.DISK[K.key(reviewed)]["bands"]]
          == ["reviewed"] and not K.read_map(reviewed).any())
    manifest = os.path.join(folder, "correction.json")
    data = json.load(open(manifest, encoding="utf-8"))
    check("the manifest names it, complete from the first stroke",
          data.get("reviewed") == "model_corrected_reviewed.tif"
          and data.get("reviewed_since") == 0,
          {k: data.get(k) for k in ("reviewed", "reviewed_since")})
    hook = hook_of(section)
    check("the hook of the record is one of Correct's", hook is not None,
          [type(h).__name__ for h in section.stroke_hooks])

    print()
    print("a stroke: its footprint is swept, its changes are marked")
    # rows 0-1, cols 1-2: CROP CROP / OLIVE CROP; FROM crop TO olive
    stroke(section, (0, 2), (1, 3), CROP, OLIVE)
    seen = K.read_map(reviewed)
    marks = K.read_map(changes)
    want_seen = np.zeros(MAP.shape, np.uint8)
    want_seen[0:2, 1:3] = 1
    want_marks = np.zeros(MAP.shape, np.uint8)
    want_marks[0, 1] = want_marks[0, 2] = want_marks[1, 2] = 1
    check("the four pixels of the footprint are swept",
          np.array_equal(seen, want_seen), seen)
    check("only the three it changed are marked as changed",
          np.array_equal(marks, want_marks), marks)
    check("and the copy holds the change",
          (K.read_map(copy)[0:2, 1:3] == OLIVE).all(), K.read_map(copy))
    section.undo()
    check("undo puts the swept record back",
          not K.read_map(reviewed).any(), K.read_map(reviewed))
    check("and the changes", not K.read_map(changes).any(),
          K.read_map(changes))
    check("and the copy", np.array_equal(K.read_map(copy), MAP))

    print()
    print("a stroke that is not applied leaves no footprint")
    section.confirm.setChecked(True)
    asked = K.QtWidgets.QMessageBox.question
    K.QtWidgets.QMessageBox.question = staticmethod(
        lambda *a, **k: K.QtWidgets.QMessageBox.StandardButton.No)
    try:
        stroke(section, (0, 2), (1, 3), CROP, OLIVE)
    finally:
        K.QtWidgets.QMessageBox.question = asked
        section.confirm.setChecked(False)
    check("refused at 'ask before each change': nothing swept",
          not K.read_map(reviewed).any(), K.read_map(reviewed))
    check("and nothing changed", np.array_equal(K.read_map(copy), MAP))
    stroke(section, (0, 2), (0, 2), MUD, CROP)
    check("nothing of FROM under it: nothing swept",
          not K.read_map(reviewed).any(), K.read_map(reviewed))
    stroke(section, (2, 4), (0, 2), MUD, CROP)
    check("a stroke that changes all of its window sweeps it",
          K.read_map(reviewed)[2:4, 0:2].all()
          and int(K.read_map(reviewed).sum()) == 4, K.read_map(reviewed))
    stroke(section, (2, 4), (0, 3), None, OLIVE)
    check("a second stroke over it adds only its own ground",
          int(K.read_map(reviewed).sum()) == 6, K.read_map(reviewed))
    section.undo()
    check("and its undo takes only that back",
          int(K.read_map(reviewed).sum()) == 4
          and K.read_map(reviewed)[2:4, 0:2].all(), K.read_map(reviewed))

    print()
    print("the record is the correction's own")
    names = section.own_files()
    check("own_files names the record and its .aux.xml",
          "model_corrected_reviewed.tif" in names
          and "model_corrected_reviewed.tif.aux.xml" in names, names)
    check("and the reports folder", "reports" in names, names)
    os.makedirs(os.path.join(folder, "reports", "model_vs_corrected",
                             "whole_20261009-120000"))
    check("so a folder holding them is not taken for a shared one",
          not section.shares_folder(folder), sorted(os.listdir(folder)))
    check("beside_the_copy lists it, to be set aside with the copy",
          "model_corrected_reviewed.tif" in g["beside_the_copy"](copy))
    check("the record chosen as a map to correct is refused",
          "strokes of Correct went over" in
          (g["why_a_working_copy"](reviewed) or ""),
          g["why_a_working_copy"](reviewed))
    section.record.setdefault("reports", []).append({
        "kind": "model_vs_corrected", "id": "x", "label": "swept",
        "created_utc": "2026-10-09T10:00:00Z",
        "folder": "reports/model_vs_corrected/swept_20261009-120000",
        "headline": {"scope": "swept", "pixels": 9, "oa": 7 / 9.0}})
    section.show_tally()
    tally = section.tally.text()
    check("the newest report gives the quiet line under the tally",
          "last measured, ground swept: the model agrees on 77.8 % of 9 px"
          in tally, tally)
    found = g["reviewed_findings"](panel.correction)
    check("Check says how much the strokes swept",
          found and found[0].level == "ok" and "4 px swept" in found[0].what,
          [str(f) for f in found])
    section.record["reports"] = []
    panel.close_correction()

    print()
    print("a correction of an earlier build: no record until its next stroke")
    data = json.load(open(manifest, encoding="utf-8"))
    for k in ("reviewed", "reviewed_since"):
        data.pop(k, None)
    data["operations"] = 7
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.remove(reviewed)
    K.DISK.pop(K.key(reviewed), None)
    before = open(manifest, "rb").read()
    book = g["CorrectionCampaign"].open(folder)
    check("reconcile says nothing of a record it never had",
          not [t for t in book.reconcile() if "reviewed" in t],
          book.reconcile())
    section = open_existing(manifest)
    check("it opens", type(section).__name__ == "CorrectionSection",
          K.BOXES[-1:])
    check("with no record made", not os.path.exists(reviewed),
          sorted(os.listdir(folder)))
    after = json.load(open(manifest, encoding="utf-8"))
    check("and nothing of one in its manifest",
          "reviewed" not in after and "reviewed_since" not in after,
          {k: after.get(k) for k in ("reviewed", "reviewed_since")})
    old = json.loads(before.decode("utf-8"))
    # the panel writes when a correction was last opened, as it always did;
    # nothing else of the manifest may change
    moved = {k: (old.get(k), after.get(k)) for k in set(old) | set(after)
             if old.get(k) != after.get(k)
             and k not in ("last_opened", "modified")}
    check("the manifest is what it was, but for when it was opened",
          not moved and set(old) == set(after), moved)
    found = g["reviewed_findings"](panel.correction)
    check("Check says the record starts at the next stroke",
          found and found[0].level == "ok"
          and "next stroke" in found[0].what, [str(f) for f in found])
    counts = g["mvc_counts"](section.path, section.band_no,
                             section.changes_path, reviewed)
    check("Model vs corrected counts the changed pixels alone as swept",
          counts["reviewed"] is False
          and counts["swept_px"] == int(K.read_map(changes).sum()) == 4,
          counts)
    stroke(section, (0, 1), (0, 4), None, MUD)
    check("its next stroke starts the record",
          os.path.exists(reviewed) and K.key(reviewed) in K.DISK)
    seen = K.read_map(reviewed)
    check("holding that stroke alone", int(seen.sum()) == 4
          and seen[0].all(), seen)
    after = json.load(open(manifest, encoding="utf-8"))
    check("and the manifest says the seven strokes before left no footprint",
          after.get("reviewed") == "model_corrected_reviewed.tif"
          and after.get("reviewed_since") == 7 and after["operations"] == 8,
          {k: after.get(k) for k in ("reviewed", "reviewed_since",
                                     "operations")})
    found = g["reviewed_findings"](panel.correction)
    check("Check says from which stroke on it is complete",
          found and "from stroke 8 on" in found[0].what,
          [str(f) for f in found])
    panel.close_correction()

    print()
    print("a record the manifest names that is gone is said")
    os.remove(reviewed)
    K.DISK.pop(K.key(reviewed), None)
    book = g["CorrectionCampaign"].open(folder)
    said = [t for t in book.reconcile() if "reviewed" in t]
    check("reconcile says it, and what happens next",
          said and "not beside the working copy" in said[0]
          and "next stroke" in said[0], book.reconcile())
    found = g["reviewed_findings"](book)
    check("and Check says it as a note",
          found and found[0].level == "note", [str(f) for f in found])
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
