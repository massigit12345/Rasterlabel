"""Run every suite.

    python3 tests/run.py                 # everything
    python3 tests/run.py vertices lines  # only the suites whose name matches
    python3 tests/run.py --require-gdal  # a missing GDAL fails the run
    python3 tests/run.py --require-qgis  # a missing QGIS fails the run
    python3 tests/run.py --require-pyflakes  # and a missing pyflakes
    python3 tests/run.py --require-scipy     # and a missing scipy

What it needs: PyQt5 or PyQt6, pyflakes, numpy, shapely, and the GDAL Python
bindings. Not QGIS. Every suite fakes the parts of QGIS it needs, which is the
whole reason they can run on a machine that has none, and therefore on a build
server.

    pip install PyQt5 pyflakes numpy shapely

The program runs on QGIS 3 (Qt 5) and QGIS 4 (Qt 6), and the suites run on
either binding: PyQt5 when it is installed, PyQt6 otherwise, or the one asked
for with --qt 5, --qt 6 or RL_QT in the environment. tests/qtbinding.py is
where that is decided, and the first line of the run says which one it was.

The GDAL bindings must match the GDAL on the machine, so they come from the system
package rather than from pip: on Debian and Ubuntu that is python3-gdal. The
suites in NEEDS_GDAL below use real GDAL, real PROJ and real GeoPackages and
are skipped, loudly, when it is missing; those in NEEDS_QGIS run only under a
Python that has QGIS, because they hand values to the real QGIS classes: the
message levels to a real message bar, corrected maps opened as real layers,
pictures and odd grids walked through Correct and New campaign, the whole
raster held up against a real map render, a session killed in the middle of a
save, a campaign and a correction copied or moved under a saved project, the
Processing algorithm, the time report, Import frames and the uncertainty of a
map as real layers. The others need neither. One more, test_cross_qgis, needs
two QGIS installs on the machine, and saves a project in each and opens it in
every other: it runs under any Python, starting each QGIS's own, and is
skipped where fewer than two are found, --require-qgis or not, because a
build server has one. A name in a set with no file beside it is not run and
not counted. Skipped is right on a desk and
wrong on the build server: there a run that skipped them was green all the same,
and that is how the build server kept passing without having run, even once,
the suites that read and write real rasters. So --require-gdal, or
RL_REQUIRE_GDAL=1 in the environment, which is how the workflow asks for it,
turns each of those skips into a failure. --require-qgis, or RL_REQUIRE_QGIS=1,
does the same for those that need QGIS, and the QGIS 4 job asks for it.
pyflakes is the same again: without it, or with one too new for the Python it
is under, test_static_checks skips its pyflakes part and runs the rest, and
--require-pyflakes, or RL_REQUIRE_PYFLAKES=1, which both jobs set, makes that
a failure.

scipy is optional. test_reference_values holds the numbers of the reports to
independent implementations written in the suite, and, where scipy is
installed, to scipy.stats (wilcoxon, mannwhitneyu, bootstrap). Without it
those checks print SKIP, loudly, and the suite ends by listing them, which a
build server without scipy will show; --require-scipy, or RL_REQUIRE_SCIPY=1,
makes the skip a failure.

The single file is built first, from the package, and the suites read that. It is
deliberate: the suites test what is shipped, not what is written.
"""
import argparse
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Every child is run in Python's UTF-8 mode and every pipe is read as UTF-8.
# Without it a suite that prints a non-ASCII character, the arrows on the
# panel's buttons for one, passed on a machine whose shell happened to set
# PYTHONUTF8 and failed on a plain Windows console, where a pipe is written in
# cp1252. errors="replace" because a byte that is not UTF-8 in a failing
# suite's output should show up as a mark in the report, not as a second
# traceback on top of the first.
UTF8 = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
TEXT = {"encoding": "utf-8", "errors": "replace"}

# These read real rasters and real GeoPackages through the GDAL bindings.
NEEDS_GDAL = {"test_scaling.py", "test_cutouts.py", "test_export.py",
              "test_export_precision.py", "test_whole_raster.py", "test_mixed.py", "test_correct_saves.py",
              "test_boundcrs_gdal.py", "test_cutouts_free.py",
              "test_cutouts_layers.py", "test_cutouts_grids.py",
              "test_correct_thematic.py", "test_correct_crash.py",
              "test_correct_typical.py", "test_readings.py",
              "test_correct_big.py", "test_cutouts_nodata.py",
              # the measuring suites
              "test_agreement_run.py", "test_model_vs_corrected_gdal.py",
              "test_dataset_card.py", "test_card_exports.py",
              "test_export_arrange.py",
              "test_ignore_index.py", "test_design_package.py",
              # a consensus voted by the readings that covered the frame
              "test_consensus_cover.py",
              "test_uncertainty_correct.py", "test_uncertainty_big.py",
              "test_reports.py",
              "test_campaign_helpers.py",
              # the maps of the reports, written and read back for real
              "test_report_rasters.py",
              # the reports QGIS could not open, refused before they are
              # written
              "test_report_paths.py",
              # the example dataset, made again and read back
              "test_example_dataset.py",
              # Whole: the legend of the mask, strips that tie like one pass,
              # the memory driver GDAL still has; the books of a cutouts folder
              "test_whole_legend.py", "test_strip_ties.py",
              "test_memory_driver.py", "test_cutouts_books.py",
              # layers.json, written without the home folder
              "test_layers_private.py"}
# These read the package as a package instead of the built single file.
# These hand values to the real QGIS classes, which no fake can stand in for:
# the fakes take anything, and that is how a level PyQt6 refuses passed, and
# how a style QGIS would not read could have passed too, and a picture that
# was not what the screen showed. All but the first also need GDAL, which
# every QGIS brings.
NEEDS_QGIS = {"test_message_levels.py", "test_correct_qgis_style.py",
              "test_correct_typical_qgis.py", "test_input_grids_qgis.py",
              "test_whole_export_qgis.py", "test_correct_inputs_qgis.py",
              "test_recovery_qgis.py", "test_moved_campaign_qgis.py",
              "test_processing_agreement.py", "test_time_report_run.py",
              "test_import_frames_qgis.py", "test_uncertainty_qgis.py",
              "test_processing_measures.py",
              "test_correct_ground_qgis.py", "test_card_ground_qgis.py",
              "test_annotate_safety_qgis.py", "test_readings_qgis.py",
              # the net after a frame is deleted, moved, noted, imported
              "test_frame_net_qgis.py",
              # Whole with work pending, Objects saving, a project written
              "test_data_fixes_qgis.py",
              "test_stac_qgis.py",
              # the boxes of Objects as COCO and YOLO, from Cutouts
              "test_cutouts_boxes_qgis.py",
              # the launcher, the paths in the manifests, the set-aside files
              "test_project_qgis.py",
              # the strip of a line, burned by GDAL from the real polygon
              "test_lines_qgis.py",
              # the tutorial, walked step by step
              "test_tutorial_walk.py",
              # what QGIS opens past 260 characters on Windows, asked of
              # QGIS; and the windows of the measures at 300 px in two fonts
              "test_report_paths_qgis.py", "test_dialogs_narrow.py",
              # merging same-class neighbours, burned before and after
              "test_merge_pixels_qgis.py",
              # and every file it writes, searched for the home folder
              "test_home_stays_out.py"}
# This one starts the QGIS installs of the machine itself, one after the
# other, and needs two of them; the suite says which it finds.
ACROSS_QGIS = {"test_cross_qgis.py"}
NEEDS_PACKAGE = {"test_package.py", "test_safety_net.py",
                 "test_plugin_install.py"}


def qgis_installs(name):
    """How many QGIS installs the suite that goes across them finds."""
    try:
        out = subprocess.run([sys.executable, os.path.join(HERE, name),
                              "--list"], capture_output=True, cwd=HERE,
                             env=dict(os.environ, **UTF8), **TEXT)
    except OSError:
        return 0
    if out.returncode:
        return 0
    return len([l for l in out.stdout.splitlines() if l.strip()])


def have(module, python=None):
    try:
        out = subprocess.run([python or sys.executable, "-c", "import " + module],
                             capture_output=True)
    except OSError:
        return False
    return out.returncode == 0


def qt_binding(python=None):
    """Which Qt binding the suites will get, as one line, or None."""
    try:
        out = subprocess.run(
            [python or sys.executable, "-c",
             "import sys; sys.path.insert(0, sys.argv[1]); import qtbinding; "
             "print(qtbinding.describe())", HERE],
            capture_output=True, env=dict(os.environ, **UTF8), **TEXT)
    except OSError:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def gdal_python():
    """The interpreter that has the GDAL bindings, which is not always this one.

    The bindings are compiled against one Python version. A machine can easily
    have GDAL for 3.12 and be running 3.11, and the nine suites that need it then
    fail for a reason that has nothing to do with the program.
    """
    if have("osgeo.gdal"):
        return sys.executable
    # shutil.which, not the which command: Windows has none of its own, and the
    # one Git Bash brings answers /c/... paths that Windows cannot start.
    for guess in ("python3.12", "python3.11", "python3.10", "python3"):
        path = shutil.which(guess)
        if path and have("osgeo.gdal", path):
            return path
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("only", nargs="*", help="run only the suites matching these")
    ap.add_argument("--no-build", action="store_true",
                    help="do not rebuild dist/rasterlabel.py first")
    ap.add_argument("--qt", choices=("5", "6"),
                    help="run on PyQt5 or on PyQt6 (also RL_QT=5 or 6); by "
                         "default PyQt5 when it is installed, else PyQt6")
    ap.add_argument("--require-gdal", action="store_true",
                    help="fail, instead of skipping, the suites that need "
                         "GDAL when the bindings are missing (also "
                         "RL_REQUIRE_GDAL=1)")
    ap.add_argument("--require-qgis", action="store_true",
                    help="fail, instead of skipping, the suites that need "
                         "QGIS when this Python has none (also "
                         "RL_REQUIRE_QGIS=1)")
    ap.add_argument("--require-pyflakes", action="store_true",
                    help="fail, instead of skipping, the pyflakes part of "
                         "test_static_checks when pyflakes is missing or "
                         "cannot run on this Python (also "
                         "RL_REQUIRE_PYFLAKES=1)")
    ap.add_argument("--require-scipy", action="store_true",
                    help="fail, instead of skipping, the scipy cross-checks "
                         "of test_reference_values when scipy is missing "
                         "(also RL_REQUIRE_SCIPY=1)")
    args = ap.parse_args()
    if args.require_scipy:
        os.environ["RL_REQUIRE_SCIPY"] = "1"
    if args.qt:
        os.environ["RL_QT"] = args.qt
    require_gdal = (args.require_gdal
                    or os.environ.get("RL_REQUIRE_GDAL", "") not in ("", "0"))
    require_qgis = (args.require_qgis
                    or os.environ.get("RL_REQUIRE_QGIS", "") not in ("", "0"))
    require_pyflakes = (args.require_pyflakes
                        or os.environ.get("RL_REQUIRE_PYFLAKES", "")
                        not in ("", "0"))

    # This process prints lines taken from the suites' output, so it must not
    # die on a character its own console cannot show either.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    if not args.no_build:
        out = subprocess.run([sys.executable,
                              os.path.join(ROOT, "tools", "bundle.py")],
                             capture_output=True, cwd=ROOT,
                             env=dict(os.environ, **UTF8), **TEXT)
        print(out.stdout.strip() or out.stderr.strip())
        if out.returncode:
            return 1
        # And the zip, because one suite installs it the way QGIS does. It is
        # not in the repository (.gitignore keeps built things out), so on a
        # fresh clone there is nothing for that suite to open and the whole run
        # went red for a reason that had nothing to do with the program. The
        # placeholder guard is lifted here: the point is that a zip can be
        # built, not that this one is fit to publish.
        out = subprocess.run([sys.executable,
                              os.path.join(ROOT, "tools", "package_plugin.py")],
                             capture_output=True, cwd=ROOT,
                             env=dict(os.environ, RL_ALLOW_PLACEHOLDERS="1",
                                      **UTF8), **TEXT)
        print(out.stdout.strip() or out.stderr.strip())
        if out.returncode:
            return 1

    binding = qt_binding()
    if binding is None:
        wanted = os.environ.get("RL_QT", "")
        print("cannot run: %s. pip install %s"
              % ("PyQt%s is not installed" % wanted if wanted
                 else "neither PyQt5 nor PyQt6 is installed",
                 "PyQt" + (wanted or "5")))
        return 2
    print("Qt: %s" % binding)
    if not have("numpy"):
        print("cannot run: numpy is not installed. pip install numpy")
        return 2
    # pyflakes is one part of one suite. The Python inside a QGIS installer
    # has none, and refusing to start there kept every other suite from
    # running where it matters most: test_static_checks skips that part,
    # loudly, and runs the rest. --require-pyflakes makes the skip a failure.
    if require_pyflakes:
        os.environ["RL_REQUIRE_PYFLAKES"] = "1"
    if not have("pyflakes"):
        print("%s: pyflakes is not installed, so test_static_checks %s its "
              "pyflakes part. pip install pyflakes"
              % (("error", "fails") if require_pyflakes
                 else ("note", "skips")))
    if not have("scipy"):
        print("%s: scipy is not installed, so test_reference_values %s its "
              "scipy cross-checks (it says which)"
              % (("error", "fails") if os.environ.get("RL_REQUIRE_SCIPY", "")
                 not in ("", "0") else ("note", "skips")))
    if not have("shapely"):
        print("note: shapely is missing, so two suites will say so and stop")

    # A name in a set with no file beside it is not run; a count says how
    # many of them are here.
    present = set(f for f in os.listdir(HERE)
                  if f.startswith("test_") and f.endswith(".py"))
    with_gdal = gdal_python()
    if with_gdal is None and require_gdal:
        print("error: the GDAL bindings are not available and they are "
              "required here, so the %d suites that need them fail"
              % len(NEEDS_GDAL & present))
    elif with_gdal is None:
        print("note: the GDAL bindings are not available, so %d suites are "
              "skipped" % len(NEEDS_GDAL & present))
    elif with_gdal != sys.executable:
        print("note: the GDAL suites will run under %s, which has the bindings"
              % with_gdal)
        print("      and Qt there: %s"
              % (qt_binding(with_gdal) or "none, so they will fail"))

    with_qgis = have("qgis.core")
    if not with_qgis and require_qgis:
        print("error: QGIS is not importable from this Python and it is "
              "required here, so the %d suites that need it fail"
              % len(NEEDS_QGIS & present))
    elif not with_qgis:
        print("note: QGIS is not importable from this Python, so %d suites "
              "are skipped" % len(NEEDS_QGIS & present))

    env = dict(os.environ, **UTF8)
    env["RL_ROOT"] = ROOT
    env["RL_SRC"] = os.path.join(ROOT, "dist", "rasterlabel.py")
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    # On Windows the offscreen platform looks for fonts only in Qt's own
    # lib/fonts folder, which a pip install of PyQt leaves empty. With no
    # font at all every word is measured at a made-up width, a checkbox of
    # twenty letters asks for four hundred pixels, and the layout suites
    # report overlaps no real screen would show. Linux finds its fonts
    # through fontconfig and needs none of this.
    if os.name == "nt" and env["QT_QPA_PLATFORM"] == "offscreen":
        env.setdefault("QT_QPA_FONTDIR", os.path.join(
            os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    env["PYTHONPATH"] = os.pathsep.join(
        [ROOT, HERE] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    # A home of their own for the suites. Cutouts writes its log into its
    # default folder, ~/RasterLabel/cutouts, whenever that folder is there,
    # and a suite that opens Cutouts without choosing a folder of its own
    # appended its lines to the log of whoever ran the suites, on their own
    # machine. The QGIS profile is a separate matter: each suite that needs
    # one makes its own.
    home = tempfile.mkdtemp(prefix="rl_suites_home_")
    atexit.register(shutil.rmtree, home, True)
    # git reads its global settings from the home, and on a build server the
    # safe.directory that lets it read a checkout owned by another user is
    # one of them: without it the suite that packages a commit was refused.
    gitconfig = os.path.join(os.path.expanduser("~"), ".gitconfig")
    if "GIT_CONFIG_GLOBAL" not in env and os.path.isfile(gitconfig):
        env["GIT_CONFIG_GLOBAL"] = gitconfig
    env["HOME"] = env["USERPROFILE"] = env["RL_SUITE_HOME"] = home

    names = sorted(f for f in os.listdir(HERE)
                   if f.startswith("test_") and f.endswith(".py"))
    if args.only:
        names = [n for n in names
                 if any(word.lower() in n.lower() for word in args.only)]
        if not names:
            print("no suite matches %s" % " ".join(args.only))
            return 2

    started = time.time()
    passed, failed, skipped = [], [], []
    for name in names:
        python = sys.executable
        if name in NEEDS_GDAL:
            if with_gdal is None and require_gdal:
                print("  FAIL  %-24s needs the GDAL bindings, which are "
                      "missing" % name)
                failed.append(name)
                continue
            if with_gdal is None:
                print("  SKIP  %-24s needs the GDAL bindings" % name)
                skipped.append(name)
                continue
            python = with_gdal
        if name in ACROSS_QGIS:
            found = qgis_installs(name)
            if found < 2:
                print("  SKIP  %-24s needs two QGIS installs, %d found"
                      % (name, found))
                skipped.append(name)
                continue
        if name in NEEDS_QGIS and not with_qgis:
            if require_qgis:
                print("  FAIL  %-24s needs QGIS, which is missing" % name)
                failed.append(name)
            else:
                print("  SKIP  %-24s needs QGIS" % name)
                skipped.append(name)
            continue
        out = subprocess.run([python, os.path.join(HERE, name)],
                             capture_output=True, cwd=HERE, env=env, **TEXT)
        if out.returncode == 0:
            print("  ok    %s" % name)
            passed.append(name)
        else:
            print("  FAIL  %s" % name)
            for line in ((out.stdout or "") + (out.stderr or "")).splitlines():
                if "FAIL" in line or "Error" in line or "Traceback" in line:
                    print("          " + line.strip()[:140])
            failed.append(name)

    print()
    print("%d passed, %d failed%s, in %.0f seconds"
          % (len(passed), len(failed),
             ", %d skipped" % len(skipped) if skipped else "",
             time.time() - started))
    if failed:
        print("to see one in full:  python3 tests/%s" % failed[0])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
