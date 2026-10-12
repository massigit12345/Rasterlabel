"""A campaign folder copied, or moved, and opened at its new place from a
saved QGIS project, in a real QGIS.

Nothing unusual is done here: a campaign and a correction are made and
worked on, the QGIS project is saved with them open, the folders are copied
(or moved), the project is opened again and Open is pressed on the new
place. The project brings its layers back with their marks, the campaign's
id among them, and the program found its layers by that id alone:

  copied, the layers read the original, and every stroke drawn on the copy
  went into the original GeoPackage, and the correction showed the original
  working copy;
  moved, the layers read a file that is not there: invalid, every stroke
  lost, and a save that said "0 layers written".

A layer is the campaign's now only while it is valid and reads the
campaign's own file; any other is taken out of the project and the right one
loaded. The same for the layer of a correction's working copy.

Needs QGIS; tests/run.py skips it where QGIS is missing and, with
RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgiskit as K  # noqa: E402
from qgis.core import QgsProject  # noqa: E402

print("QGIS %s" % K.QGIS_VERSION)
TABLES = [t for t, _, _ in K.g["TABLES"]]
root = tempfile.mkdtemp(prefix="rl_moved_")


def pixel_rect(col0, row0, col1, row1):
    """Pixels [col0, col1) x [row0, row1) of the classes map, 1 m pixels."""
    from qgis.core import QgsGeometry, QgsRectangle
    return QgsGeometry.fromRect(QgsRectangle(
        K.X0 + col0 + 0.01, K.Y0 - row1 + 0.01,
        K.X0 + col1 - 0.01, K.Y0 - row0 - 0.01))


def make(where):
    """A campaign with two polygons and a correction with one stroke, in
    where; the QGIS project saved beside it with both open."""
    image = K.layer_of(os.path.join(root, "data", "image.tif"))
    classes = K.layer_of(os.path.join(root, "data", "classes.tif"),
                         show=False)
    panel = K.new_panel()
    campaign = K.new_campaign(panel, os.path.join(where, "camp"), image)
    section = K.annotate(panel)
    section.choose_class("mud")
    section.autosave.setValue(0)
    section.paint(K.square(K.X0 + 2, K.Y0 - 18, 1.0))
    section.paint(K.square(K.X0 + 5, K.Y0 - 18, 1.0))
    section.save()

    def opened(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText("fix classes")
        d.raster.setCurrentIndex(d.raster.findData(classes.id()))
        d.fill_bands()
        d.band.setCurrentIndex(d.band.findData(1))
        d.folder.setText(os.path.join(where, "corr"))
        d.operator.setText("ann")
        return 1

    def confirm(d):
        d.accept()
        return 1
    K.ANSWERS["OpenCorrection"] = opened
    K.ANSWERS["ConfirmClasses"] = confirm
    panel.new_correction_campaign()
    fix = panel.section
    K.check("the correction is open in Correct",
            type(fix).__name__ == "CorrectionSection",
            (type(fix).__name__, K.BOXES[-3:], K.UNEXPECTED))
    fix.choose_from(None)
    fix.choose_class(1)
    fix.paint(pixel_rect(25, 5, 30, 10))
    fix.save()
    project = os.path.join(root, "project", "work.qgz")
    os.makedirs(os.path.dirname(project), exist_ok=True)
    K.check("the QGIS project is saved", QgsProject.instance().write(project))
    out = (campaign.data["id"], panel.correction.data["id"], fix.layer_role(),
           os.path.relpath(fix.path, where), project)
    K.close_panel(panel)
    QgsProject.instance().clear()
    K.app.processEvents()
    return out


def reopen(case, project, folder, old, ids, copy_rel):
    """The project opened again, and the campaign and the correction opened
    at their new place, folder; old is where they were."""
    cid, bid, role = ids
    print()
    print(case)
    K.check("%s: the project opens" % case, QgsProject.instance().read(project))
    marked = [lyr for lyr in K.g["my_layers"](cid)]
    K.check("%s: the project brought the campaign's layers back" % case,
            len(marked) == len(TABLES), [l.name() for l in marked])
    panel = K.new_panel()
    package = os.path.join(folder, "camp", "annotation.gpkg")
    old_package = os.path.join(old, "camp", "annotation.gpkg")
    before_old = K.counts(old_package) if os.path.exists(old_package) else None
    del K.SAID[:]
    campaign = K.open_campaign(panel, os.path.join(folder, "camp"))
    K.check("%s: the campaign opens at the new place" % case,
            campaign is not None and K.same_file(campaign.folder,
                                                 os.path.join(folder, "camp")))
    for table in TABLES:
        lyr = K.find_mine(cid, table)
        K.check("%s: %s reads the new package, and is valid" % (case, table),
                K.reads(lyr, package),
                lyr.source() if lyr is not None else None)
    wrong = [l.source() for l in K.g["my_layers"](cid)
             if not K.reads(l, package)]
    K.check("%s: no layer of the campaign reads anything else" % case,
            not wrong, wrong)
    K.check("%s: one layer per table" % case,
            len(K.g["my_layers"](cid)) == len(TABLES),
            [l.source() for l in K.g["my_layers"](cid)])
    section = K.annotate(panel)
    section.choose_class("water")
    section.paint(K.square(K.X0 + 9, K.Y0 - 18, 1.0))
    del K.SAID[:]
    section.save()
    K.check("%s: the stroke is saved into the new package" % case,
            K.counts(package)["polygons"] == 3, K.counts(package))
    K.check("%s: and the save says so" % case,
            any("1 layer written" in s or "layers written" in s
                and "0 layers" not in s for s in K.SAID), K.SAID)
    if before_old is not None:
        K.check("%s: the original package is not touched" % case,
                K.counts(old_package) == before_old,
                (before_old, K.counts(old_package)))
    text, problems, notes = K.check_report(panel.campaign)
    K.check("%s: Check finds nothing wrong" % case, problems == 0,
            [line for line in text.splitlines() if "PROBLEM" in line])

    # the correction, at its new place
    copy = os.path.join(folder, copy_rel)
    old_copy = os.path.join(old, copy_rel)
    old_pixels = K.array_of(old_copy) if os.path.exists(old_copy) else None
    book = panel.read_correction(os.path.join(folder, "corr",
                                              "correction.json"))
    K.check("%s: the correction reads" % case, book is not None, K.BOXES[-2:])
    if book is not None:
        panel.start_correction(book)
        panel.show_correction()
    fix = panel.section
    if K.check("%s: and opens in Correct" % case,
               type(fix).__name__ == "CorrectionSection",
               (type(fix).__name__, K.BOXES[-2:])):
        lyr = K.find_mine(bid, role)
        K.check("%s: its layer shows the new working copy" % case,
                K.reads(lyr, copy), lyr.source() if lyr is not None else None)
        wrong = [l.source() for l in K.g["my_layers"](bid)
                 if not K.reads(l, copy)]
        K.check("%s: and no other" % case, not wrong, wrong)
        before = K.array_of(copy)
        fix.choose_from(None)
        fix.choose_class(1)
        fix.paint(pixel_rect(45, 5, 50, 10))
        fix.save()
        after = K.array_of(copy)
        K.check("%s: a stroke changes the new working copy" % case,
                (after[5:10, 45:50] == 1).all()
                and (before[5:10, 45:50] != 1).all())
        if old_pixels is not None:
            K.check("%s: and not the original" % case,
                    (K.array_of(old_copy) == old_pixels).all())
    K.close_panel(panel)
    QgsProject.instance().clear()
    K.app.processEvents()


try:
    K.write_image(os.path.join(root, "data", "image.tif"))
    K.write_classes(os.path.join(root, "data", "classes.tif"))
    orig = os.path.join(root, "orig")
    print("made, and the project saved, in %s" % orig)
    cid, bid, role, copy_rel, project = make(orig)
    copied = os.path.join(root, "copied")
    shutil.copytree(orig, copied)
    reopen("copied", project, copied, orig, (cid, bid, role), copy_rel)
    moved = os.path.join(root, "moved")
    shutil.move(orig, moved)
    reopen("moved", project, moved, orig, (cid, bid, role), copy_rel)
finally:
    QgsProject.instance().clear()
    shutil.rmtree(root, ignore_errors=True)
K.finish()
