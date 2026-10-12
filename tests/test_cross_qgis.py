"""A QGIS project saved in one QGIS and opened in another, 3 and 4 both ways.

The program runs on QGIS 3 (Qt 5) and QGIS 4 (Qt 6), and the same people
use both: a project saved with an annotation campaign and a correction open
in QGIS 4 is opened again tomorrow in QGIS 3.44 on another computer, and the
other way round. Each QGIS on this machine, in turn, makes a campaign with a
frame, polygons in two readings, a line, a point and a box, and a correction
with a stroke, and saves the QGIS project with both open. Every QGIS then
opens a copy of each of those projects and checks: every layer valid, the
campaign's and the correction's recognised as the program's, the campaign
and the correction open again with nothing asked and nothing lost, a new
stroke saves, an export writes its files, a correction stroke saves, and
Check finds nothing wrong.

It needs at least two QGIS installs. On Windows they are looked for in
Program Files (QGIS */bin/python-qgis*.bat); anywhere, RL_QGIS_PYTHONS can
name the launchers, separated by the path separator. With fewer than two,
tests/run.py skips it, whatever --require-qgis says: the build server has one
QGIS. Each step is a fresh run of a QGIS Python, with no window, on a scratch
folder that is removed at the end.

    python tests/test_cross_qgis.py           # the whole matrix
    python tests/test_cross_qgis.py --list    # the launchers it would use
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
ME = os.path.basename(os.path.abspath(__file__))


# ----------------------------------------------------------- the launchers
def launchers():
    """One launcher per QGIS install: (label, path)."""
    named = os.environ.get("RL_QGIS_PYTHONS", "").strip()
    if named:
        found = [p for p in named.split(os.pathsep) if p.strip()]
    elif os.name == "nt":
        found = []
        base = os.environ.get("ProgramFiles", r"C:\Program Files")
        for install in sorted(glob.glob(os.path.join(base, "QGIS *"))):
            bats = sorted(glob.glob(os.path.join(install, "bin",
                                                 "python-qgis*.bat")))
            # python-qgis.bat where there is one, the -ltr one otherwise
            plain = [b for b in bats if os.path.basename(b).lower()
                     == "python-qgis.bat"]
            if plain or bats:
                found.append((plain or bats)[0])
    else:
        found = []
    out = []
    for path in found:
        label = os.path.basename(os.path.dirname(os.path.dirname(path))) \
            if path.lower().endswith(".bat") else path
        out.append((label.replace("QGIS ", "") or path, path))
    return out


# Names the QGIS a launcher brings sets for itself, which must not leak from
# one QGIS into another when this is run from inside one of them.
LEAKS = ("PYTHONHOME", "PYTHONPATH", "PYTHONEXECUTABLE", "QGIS_PREFIX_PATH",
         "QT_PLUGIN_PATH", "GDAL_DATA", "GDAL_DRIVER_PATH", "PROJ_LIB",
         "PROJ_DATA", "OSGEO4W_ROOT", "GDAL_FILENAME_IS_UTF8", "VSI_CACHE",
         "VSI_CACHE_SIZE", "QGIS_CUSTOM_CONFIG_PATH", "PYTHONUTF8",
         "PYTHONIOENCODING")


def run_in(launcher, phase, folder, timeout=600):
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in LEAKS and not k.upper().startswith("O4W_")}
    if os.name == "nt":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        env["PATH"] = os.pathsep.join([os.path.join(windir, "system32"),
                                       windir])
    env.update({
        "RL_CROSS_PHASE": phase, "RL_CROSS_DIR": folder,
        "RL_ROOT": ROOT,
        "RL_SRC": os.environ.get("RL_SRC")
        or os.path.join(ROOT, "dist", "rasterlabel.py"),
        "PYTHONPATH": os.pathsep.join([ROOT, HERE]),
        "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "offscreen"})
    if os.name == "nt":
        env.setdefault("QT_QPA_FONTDIR", os.path.join(
            os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    # The script by its bare name, from its own folder, and everything else
    # through the environment: a .bat started with two quoted arguments is
    # where cmd.exe gets its quotes wrong.
    out = subprocess.run([launcher, ME], cwd=HERE, env=env,
                         capture_output=True, encoding="utf-8",
                         errors="replace", timeout=timeout)
    return out.returncode, (out.stdout or "") + (out.stderr or "")


def emitted(text):
    out = {}
    for line in text.splitlines():
        if line.startswith("@@"):
            tag, _, rest = line[2:].partition(" ")
            try:
                out[tag] = json.loads(rest)
            except ValueError:
                out[tag] = rest
    return out


def orchestrate():
    found = launchers()
    print("QGIS installs: %s" % (", ".join(l for l, _ in found) or "none"))
    if len(found) < 2:
        print("skipped: two QGIS installs are needed, %d found" % len(found))
        return 0
    root = tempfile.mkdtemp(prefix="rl_cross_")
    bad, matrix, versions = [], {}, {}
    started = time.time()
    try:
        made = {}
        for label, launcher in found:
            folder = os.path.join(root, "made_in_" + label)
            os.makedirs(folder)
            rc, text = run_in(launcher, "make", folder)
            said = emitted(text)
            versions[label] = said.get("qgis", "?")
            fails = [l for l in text.splitlines() if l.startswith("  FAIL")]
            print("made in %s (%s): %s" % (label, versions[label],
                                           "ok" if rc == 0 else "FAILED"))
            for line in fails:
                print("  " + line)
            if rc != 0:
                if not fails:
                    print(text[-3000:])
                bad.append("made in %s" % label)
                continue
            made[label] = folder
        for label, folder in sorted(made.items()):
            for other, launcher in found:
                copy = os.path.join(root, "%s_in_%s" % (label, other))
                # the folder as a person would carry it: project, campaign,
                # correction and rasters together, so the project's relative
                # paths find them
                shutil.copytree(folder, copy)
                rc, text = run_in(launcher, "reopen", copy)
                fails = [l for l in text.splitlines()
                         if l.startswith("  FAIL")]
                matrix[(label, other)] = "ok" if rc == 0 else \
                    "FAILED (%d)" % max(len(fails), 1)
                print("saved in %s, reopened in %s: %s"
                      % (label, other, matrix[(label, other)]))
                for line in fails:
                    print("  " + line)
                if rc != 0:
                    if not fails:
                        print(text[-3000:])
                    bad.append("saved in %s, reopened in %s" % (label, other))
                shutil.rmtree(copy, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print()
    print("saved in (rows), reopened in (columns):")
    labels = [l for l, _ in found]
    print("  %-10s" % "" + "".join("%-12s" % l for l in labels))
    for a in labels:
        print("  %-10s" % a + "".join("%-12s" % matrix.get((a, b), "-")
                                      for b in labels))
    print("in %.0f seconds" % (time.time() - started))
    print()
    print("FAILED: %d" % len(bad) if bad else "all pass")
    for b in bad:
        print("   " + b)
    return 1 if bad else 0


# ------------------------------------------------------------ in one QGIS
def classes_rect(col0, row0, col1, row1):
    from qgis.core import QgsGeometry, QgsRectangle
    import qgiskit as K
    return QgsGeometry.fromRect(QgsRectangle(
        K.X0 + col0 + 0.01, K.Y0 - row1 + 0.01,
        K.X0 + col1 - 0.01, K.Y0 - row0 - 0.01))


def make(folder):
    import qgiskit as K
    from qgis.core import QgsPointXY, QgsProject, QgsRectangle
    K.emit("qgis", K.QGIS_VERSION)
    print("QGIS %s" % K.QGIS_VERSION)
    image = K.layer_of(K.write_image(os.path.join(folder, "data",
                                                  "image.tif")))
    classes = K.layer_of(K.write_classes(os.path.join(folder, "data",
                                                      "classes.tif")),
                         show=False)
    panel = K.new_panel()
    campaign = K.new_campaign(panel, os.path.join(folder, "camp"), image,
                              tiled=True, name="cross")
    section = K.annotate(panel)
    section.autosave.setValue(0)
    section.create_tile(QgsPointXY(K.X0 + 10, K.Y0 - 10))
    tid = section.current_tile_id()
    K.check("a frame is placed", bool(tid), K.SAID[-3:])
    section.choose_class("mud")
    section.paint(K.square(K.X0 + 2, K.Y0 - 18, 1.0))
    section.paint(K.square(K.X0 + 5, K.Y0 - 18, 1.0))
    section.choose_class("water")
    section.draw_line([QgsPointXY(K.X0 + 2, K.Y0 - 5),
                       QgsPointXY(K.X0 + 9, K.Y0 - 5)])
    section.drop_point(QgsPointXY(K.X0 + 12, K.Y0 - 12))
    section.save()
    # a second reading of the same frame: pass 2
    section.pass_no.setValue(2)
    section.choose_class("water")
    section.paint(K.square(K.X0 + 14, K.Y0 - 18, 1.0))
    section.save()
    # saved once with Annotate open on the second, blind, pass: the filter
    # on the readings is in the renderers the project keeps
    K.check("the QGIS project is saved with Annotate open",
            QgsProject.instance().write(os.path.join(folder,
                                                     "annotating.qgz")))
    panel.toggle_module(2)
    boxes = panel.section
    K.check("Objects opens", type(boxes).__name__ == "ObjectsSection",
            type(boxes).__name__)
    boxes.choose_class("mud")
    boxes.create_box(QgsRectangle(K.X0 + 3, K.Y0 - 15, K.X0 + 6, K.Y0 - 12))
    boxes.save()
    package = campaign.package_path
    got = K.counts(package)
    K.check("two readings of the frame", K.readings(package)
            == [["ANNA", 1], ["ANNA", 2]], K.readings(package))
    K.check("everything drawn is in the package",
            got["tiles"] == 1 and got["polygons"] >= 4 and got["lines"] == 1
            and got["points"] == 1 and got["boxes"] == 1, got)

    def opened(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText("cross fix")
        d.raster.setCurrentIndex(d.raster.findData(classes.id()))
        d.fill_bands()
        d.band.setCurrentIndex(d.band.findData(1))
        d.folder.setText(os.path.join(folder, "corr"))
        d.operator.setText("ann")
        return 1

    def confirm(d):
        d.accept()
        return 1
    K.ANSWERS["OpenCorrection"] = opened
    K.ANSWERS["ConfirmClasses"] = confirm
    panel.new_correction_campaign()
    fix = panel.section
    if K.check("Correct opens on a new correction",
               type(fix).__name__ == "CorrectionSection",
               (type(fix).__name__, K.BOXES[-3:], K.UNEXPECTED)):
        fix.choose_from(None)
        fix.choose_class(1)
        fix.paint(classes_rect(25, 5, 30, 10))
        fix.save()
        K.check("the stroke is in the working copy",
                (K.array_of(fix.path)[5:10, 25:30] == 1).all())
    K.check("the campaign is still open", panel.campaign is not None)
    project = os.path.join(folder, "work.qgz")
    K.check("the QGIS project is saved with both open",
            QgsProject.instance().write(project))
    with open(os.path.join(folder, "made.json"), "w") as fh:
        json.dump({"campaign": campaign.data["id"],
                   "correction": panel.correction.data["id"],
                   "role": fix.layer_role(),
                   "copy": os.path.relpath(fix.path, folder),
                   "counts": got, "readings": K.readings(package),
                   "qgis": K.QGIS_VERSION}, fh)
    # and QGIS closed, as a person closes it
    K.close_panel(panel)
    QgsProject.instance().clear()
    K.finish()


def reopen(folder):
    import qgiskit as K
    from qgis.core import QgsProject
    print("QGIS %s" % K.QGIS_VERSION)
    with open(os.path.join(folder, "made.json")) as fh:
        made = json.load(fh)
    print("made in QGIS %s" % made["qgis"])
    cid, bid, role = made["campaign"], made["correction"], made["role"]
    package = os.path.join(folder, "camp", "annotation.gpkg")
    copy = os.path.join(folder, made["copy"])
    tables = [t for t, _, _ in K.g["TABLES"]]
    # The panel first, as in QGIS: the plugin is running when the project
    # is opened.
    panel = K.new_panel()

    # the project saved while Annotate was open
    K.check("the project saved in Annotate opens", QgsProject.instance().read(
        os.path.join(folder, "annotating.qgz")))
    invalid = [l.name() for l in QgsProject.instance().mapLayers().values()
               if not l.isValid()]
    K.check("every layer of it is valid", not invalid, invalid)
    K.check("and the campaign's are the program's",
            sorted(l.customProperty("rasterlabel/role")
                   for l in K.g["my_layers"](cid)) == sorted(tables))
    campaign = K.open_campaign(panel, os.path.join(folder, "camp"))
    if K.check("the campaign opens from it", campaign is not None,
               K.BOXES[-3:]):
        section = K.annotate(panel)
        K.check("Annotate opens on it",
                type(section).__name__ == "AnnotationSection")
        K.check("nothing lost from it", K.counts(package) == made["counts"]
                and K.readings(package) == made["readings"],
                (made["counts"], K.counts(package)))
        text, problems, notes = K.check_report(panel.campaign)
        K.check("and Check finds nothing wrong", problems == 0,
                [l for l in text.splitlines() if "PROBLEM" in l])
        panel.close_campaign()
    QgsProject.instance().clear()
    K.app.processEvents()

    # the project saved with Correct open
    K.check("the project opens", QgsProject.instance().read(
        os.path.join(folder, "work.qgz")))
    layers = list(QgsProject.instance().mapLayers().values())
    invalid = [l.name() for l in layers if not l.isValid()]
    K.check("every layer of the project is valid", layers and not invalid,
            invalid)
    mine = K.g["my_layers"](cid)
    K.check("the campaign's layers are recognised as the program's",
            sorted(l.customProperty("rasterlabel/role") for l in mine)
            == sorted(tables), [l.name() for l in mine])
    K.check("and read the campaign's package",
            all(K.reads(l, package) for l in mine),
            [l.source() for l in mine])
    theirs = K.g["my_layers"](bid)
    K.check("the correction's layer is recognised as the program's",
            len(theirs) == 1 and theirs[0].customProperty("rasterlabel/role")
            == role, [(l.name(), l.customProperty("rasterlabel/role"))
                      for l in theirs])
    K.check("and reads the working copy",
            all(K.reads(l, copy) for l in theirs),
            [l.source() for l in theirs])

    campaign = K.open_campaign(panel, os.path.join(folder, "camp"))
    K.check("the campaign opens", campaign is not None, K.BOXES[-3:])
    if campaign is None:
        K.finish()
    K.check("with nothing to recover and nothing to complain about",
            not K.ASKED and not [b for b in K.BOXES
                                 if b[0] in ("warning", "critical")],
            (K.ASKED, K.BOXES))
    K.check("nothing lost", K.counts(package) == made["counts"],
            (made["counts"], K.counts(package)))
    K.check("both readings are there", K.readings(package) == made["readings"],
            (made["readings"], K.readings(package)))
    for table in tables:
        lyr = K.find_mine(cid, table)
        K.check("%s: one valid layer of the package" % table,
                K.reads(lyr, package) and len([
                    l for l in K.g["my_layers"](cid)
                    if l.customProperty("rasterlabel/role") == table]) == 1,
                lyr.source() if lyr is not None else None)
    section = K.annotate(panel)
    K.check("Annotate opens", type(section).__name__ == "AnnotationSection",
            type(section).__name__)
    section.autosave.setValue(0)
    tid = section.tile_ids()[0] if section.tile_ids() else None
    section.select_tile(tid)
    section.choose_class("mud")
    section.paint(K.square(K.X0 + 8, K.Y0 - 18, 1.0))
    del K.SAID[:]
    section.save()
    now = K.counts(package)
    K.check("a new stroke saves", now["polygons"]
            == made["counts"]["polygons"] + 1, (made["counts"], now, K.SAID))

    def export(d):
        return d.DialogCode.Accepted
    K.ANSWERS["ExportVectors"] = export
    del K.BOXES[:]
    panel.export_vectors()
    written = [t for k, t in K.BOXES if k == "information"
               and "written in" in t]
    out = os.path.join(campaign.folder, "export")
    files = sorted(os.listdir(out)) if os.path.isdir(out) else []
    K.check("an export writes its files", written and files,
            (K.BOXES, files, K.UNEXPECTED))

    text, problems, notes = K.check_report(panel.campaign)
    K.check("Check finds nothing wrong with the campaign", problems == 0,
            [l for l in text.splitlines() if "PROBLEM" in l])
    for line in text.splitlines():
        if line.startswith("  note"):
            print("  Check: " + line.strip())

    book = panel.read_correction(os.path.join(folder, "corr",
                                              "correction.json"))
    K.check("the correction reads", book is not None, K.BOXES[-2:])
    if book is not None:
        panel.start_correction(book)
        panel.show_correction()
    fix = panel.section
    if K.check("and opens in Correct",
               type(fix).__name__ == "CorrectionSection",
               (type(fix).__name__, K.BOXES[-3:])):
        lyr = K.find_mine(bid, role)
        K.check("its layer is the working copy, valid", K.reads(lyr, copy),
                lyr.source() if lyr is not None else None)
        K.check("one layer of it", len(K.g["my_layers"](bid)) == 1,
                [l.source() for l in K.g["my_layers"](bid)])
        before = K.array_of(copy)
        K.check("the stroke made before is there",
                (before[5:10, 25:30] == 1).all())
        fix.choose_from(None)
        fix.choose_class(1)
        fix.paint(classes_rect(45, 5, 50, 10))
        fix.save()
        after = K.array_of(copy)
        K.check("a new correction stroke saves",
                (after[5:10, 45:50] == 1).all()
                and (before[5:10, 45:50] != 1).all())
        text, problems, notes = K.check_report(panel.campaign,
                                               panel.correction)
        K.check("Check finds nothing wrong with the correction either",
                problems == 0,
                [l for l in text.splitlines() if "PROBLEM" in l])
    K.close_panel(panel)
    QgsProject.instance().clear()
    K.finish()


if __name__ == "__main__":
    phase = os.environ.get("RL_CROSS_PHASE", "")
    if "--list" in sys.argv[1:]:
        for label, path in launchers():
            print("%s\t%s" % (label, path))
        sys.exit(0)
    if phase == "make":
        make(os.environ["RL_CROSS_DIR"])
    elif phase == "reopen":
        reopen(os.environ["RL_CROSS_DIR"])
    else:
        sys.exit(orchestrate())
