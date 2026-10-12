"""The windows of the measures, opened at 300 pixels with two sets of fonts.

Compare, Time, Model vs corrected, Import frames, the source of the
Uncertainty, Whole raster and the report window are used in a dock that may
be 300 pixels wide. A width written for Segoe UI is not one for DejaVu Sans,
the font Ubuntu draws with, which is wider: a tick box or a radio button that
does not wrap held a window at 460 to 550 pixels there while it was
comfortable on a Windows desk, and nobody who wrote it ever saw it.

So each window is built and drawn twice, once with the fonts of the machine
(the Windows ones where this is Windows) and once with DejaVu, from the
folder in RL_DEJAVU_DIR, or --fonts DIR, or the one Ubuntu keeps them in.
Where there is no DejaVu the second half is skipped, and says so in capital
letters, because a run that skipped it proved nothing about Linux. On Windows
the folder comes from the qgis/qgis docker image:

    docker run --rm -v <folder>:/out qgis/qgis:4.2.3-trixie \\
        cp -r /usr/share/fonts/truetype/dejavu /out/

At 300 pixels, in each:

- the window can be made that narrow: nothing in it asks for more;
- it is drawn at that width, and nothing ends past its right edge;
- a tick box, a radio button or a key shows all of its words, and a label
  that wraps is as tall as its words need;
- the list of rasters offered for the uncertainty holds no map of a report.

With RL_SHOTS set to a folder, each drawing is saved there as a PNG.

Needs QGIS, which builds the windows from the program's own code: tests/run.py
skips it where QGIS is missing and, with RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
CHILD = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
TEXT = {"encoding": "utf-8", "errors": "replace"}
WIDTH = 300
# where Debian and Ubuntu keep DejaVu Sans
LINUX_DEJAVU = "/usr/share/fonts/truetype/dejavu"


def dejavu_folder():
    """The folder holding DejaVuSans.ttf: RL_DEJAVU_DIR, --fonts DIR, or the
    one of Debian and Ubuntu; None when there is none."""
    asked = os.environ.get("RL_DEJAVU_DIR", "")
    if "--fonts" in sys.argv:
        k = sys.argv.index("--fonts")
        asked = sys.argv[k + 1] if k + 1 < len(sys.argv) else asked
    for folder in (asked, LINUX_DEJAVU):
        if folder and os.path.isfile(os.path.join(folder, "DejaVuSans.ttf")):
            return folder
    return None


def own_fonts():
    """The fonts of this machine: on Windows the offscreen platform needs the
    folder told to it, elsewhere fontconfig finds them."""
    if os.name == "nt":
        return os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    return None


# ----------------------------------------------------------------- the child
def child():
    import shutil
    import tempfile
    from types import SimpleNamespace
    import numpy as np
    import qgiskit as K
    from osgeo import gdal
    from qgis.core import QgsProject, QgsRasterLayer
    from qgis.PyQt.QtWidgets import (QAbstractButton, QCheckBox, QComboBox,
                                     QDoubleSpinBox,
                                     QLabel, QLineEdit, QPushButton,
                                     QRadioButton, QSpinBox, QWidget)
    g, check = K.g, K.check
    root = tempfile.mkdtemp(prefix="rl_dialogs_narrow_")
    which = sys.argv[sys.argv.index("--child") + 1]
    print("the %s fonts" % which, flush=True)

    raster = K.write_classes(os.path.join(root, "data", "a_map_of_the_"
                                          "classes.tif"), 80, 60)
    base = K.layer_of(raster)
    # a map a report loaded: the disagreement map of Compare, say
    report = K.write_classes(os.path.join(root, "data", "aragona_agreement_"
                                          "ANNA_p1_vs_BRUNO_p1_disagreement"
                                          ".tif"), 80, 60)
    lyr = QgsRasterLayer(report, "aragona_agreement_ANNA_p1_vs_BRUNO_p1"
                         "_disagreement")
    lyr.setCustomProperty(g["REPORT_KEY"], "agreement")
    QgsProject.instance().addMapLayer(lyr)
    panel = K.new_panel()
    campaign = K.new_campaign(panel, os.path.join(root, "camp"), base,
                              tiled=True,
                              name="an annotation campaign with a long name")
    # a map with its uncertainty beside the classes, for the Uncertainty
    unc = os.path.join(root, "data", "a_map_with_its_uncertainty.tif")
    ds = gdal.GetDriverByName("GTiff").Create(unc, 80, 60, 3, gdal.GDT_Byte)
    for b, name in enumerate(("classes", "probabilita", "entropy")):
        ds.GetRasterBand(b + 1).SetDescription(name)
        ds.GetRasterBand(b + 1).WriteArray(np.full((60, 80), b + 1, np.uint8))
    ds = None

    def make_report_window():
        return g["ReportWindow"](
            panel, "Compare ANNA p1 and BRUNO p1",
            "11 frames · 440 000 px labelled by both · closed by both",
            [("Overall agreement", 0.8123), ("Kappa", 0.7012),
             ("Quantity + allocation disagreement", "0.0412 + 0.1465")],
            [{"title": "Per class", "columns": ["class", "IoU", "F1", "px A",
                                                 "px B", "same", "m2"],
              "rows": [["water", 0.9, 0.95, 10000, 11000, 9000, 900.0],
                       ["a class with a very long name", 0.5, 0.6, 5, 6, 3,
                        0.3]], "colours": ["#0055ff", "#aa5500"]}],
            ["frames are seldom a random sample: the interval describes how "
             "much the result varies across these frames, not over a "
             "population"], os.path.join(root, "camp", "reports"))

    def make_whole():
        return g["WholeRaster"](panel, campaign, os.path.join(root, "out"))

    def make_export():
        return g["ExportVectors"](panel, campaign, "F1")

    def make_import():
        origin, pixel = (500000.0, 4200000.0), (0.5, 0.5)
        extent = (500000.0, 4199500.0, 500500.0, 4200000.0)
        rows = [{"fid": i + 1, "kind": "point", "bbox": (x, y, x, y),
                 "transform_ok": True, "attrs": {"id": i + 1}, "parts": 1}
                for i, (x, y) in enumerate(
                    (500012.0 + (i % 12) * 40.0, 4199985.0 - (i // 12) * 40.0)
                    for i in range(120))]

        def planner(choice):
            return g["design_plan"](
                rows, [], inside=g["design_inside_box"](extent),
                settings_side_px=20, own_side=choice["own_side"],
                origin=origin, pixel=pixel, mapping=choice["mapping"],
                design_typed=choice["design_text"])
        d = g["ImportFrames"](
            panel, {"name": "draws_2024.gpkg", "what": "120 points, "
                    "EPSG:32633", "note": ""},
            ["fid", "id", "a_column_with_a_very_long_name_indeed"],
            [("a_map_of_the_classes", "layer_1")], 1250.0, 25000, False,
            planner, can_own_side=False)
        d.typed.setText("stratified random, AcATaMa, n=120")
        d.refresh()
        return d

    def make_compare():
        readings = [("ALESSANDRO_BIANCHI", 1), ("BRUNO", 1), ("BRUNO", 2)]
        marks = {r: {"polygons": {"frames": {"t001": (1, "", "")},
                                  "codes": [1, 2]}} for r in readings}
        return g["CompareSetup"](panel, campaign.data, campaign.folder,
                                 campaign.package_path, readings, marks, {},
                                 [])

    def make_time():
        # two readings, one with a long operator's name, and a correction
        # named at length: the lists of the window are as long as that
        g["time_scratch_readings"] = lambda folder, data: {
            ("ALESSANDRO_BIANCHI", 1): 12, ("BRUNO", 2): 1}
        g["time_correction_choices"] = lambda panel, campaign: [(
            os.path.join(root, "corr", "correction.json"),
            "a correction of the model with a long name · ALESSANDRO")]
        return g["TimeSetup"](panel, campaign, correction=None,
                              owner="campaign",
                              reading={"operator": "ANNA", "pass": 1})

    def make_mvc():
        book = SimpleNamespace(folder=os.path.join(root, "corr"),
                               data={"reviewed_since": 0, "name": "c"})
        section = SimpleNamespace(path=raster, band_no=1, wkt="",
                                  changes_path=None)
        counts = {"map_px": 4800, "swept_px": 900, "reviewed": True}

        class Poly:
            def id(self):
                return "p1"
        d = g["ModelVsCorrectedSetup"](
            panel, book, section, counts,
            [("frames_reviewed_in_the_second_pass", Poly())],
            [("a correction of the same map · BRUNO",
              {"path": raster, "operator": "BRUNO"})], True)
        return d

    def make_uncertainty():
        section = SimpleNamespace(
            path=unc, band_no=1, record={"places": {}, "name": "a map"},
            book=SimpleNamespace(data={"id": "x"}), nx=80, ny=60,
            classes=lambda: [1, 2], geometry=None)
        hook = SimpleNamespace(spec=None, suggested=None)
        return g["UncertaintySource"](panel, section, hook)

    windows = [("Report window", make_report_window),
               ("Whole raster", make_whole),
               ("Export", make_export),
               ("Import frames", make_import),
               ("Compare", make_compare),
               ("Time", make_time),
               ("Model vs corrected", make_mvc),
               ("Uncertainty source", make_uncertainty)]
    seen = {}

    def widest_rows(d, most=3):
        """The rows of a grid window that ask for most, with what is in each:
        the width of a row is the sum of what its items ask for."""
        grid = d.layout()
        if not hasattr(grid, "getItemPosition"):
            return []
        rows = {}
        for i in range(grid.count()):
            item = grid.itemAt(i)
            r, c, rs, cs = grid.getItemPosition(i)
            w = item.widget()
            name = ("%s %r" % (type(w).__name__, (w.text()[:14] if hasattr(
                w, "text") and callable(w.text) else ""))) if w else "layout"
            rows.setdefault(r, []).append((c, item.minimumSize().width(), name))
        out = []
        # a grid is as wide as its columns, each as wide as its widest item
        cols = {}
        for i in range(grid.count()):
            item = grid.itemAt(i)
            r, c, rs, cs = grid.getItemPosition(i)
            if cs == 1:
                w = item.widget()
                cols.setdefault(c, []).append((
                    item.minimumSize().width(),
                    "%s %r" % (type(w).__name__, (w.text()[:14] if hasattr(
                        w, "text") and callable(w.text) else ""))
                    if w else "layout"))
        out.append((sum(max(v)[0] for v in cols.values())
                    + grid.horizontalSpacing() * (len(cols) - 1),
                    "columns " + " + ".join("%d (%s)" % max(v)
                                            for _, v in sorted(cols.items()))))
        for r, items in rows.items():
            total = sum(n for _, n, _ in items) + grid.horizontalSpacing() * (
                len(items) - 1)
            out.append((total, "row %d [%s]" % (r, " | ".join(
                "%s %d" % (name, n) for _, n, name in sorted(items)))))
        return sorted(out, reverse=True)[:most]

    def wide(d):
        """What is wrong with the window d when it is 300 px wide."""
        bad = []
        if d.minimumWidth() > WIDTH:
            # and who asks for the room, widest first, to be found at once
            asks = sorted(((w.minimumSizeHint().width(), type(w).__name__,
                            (w.text() if hasattr(w, "text")
                             and callable(w.text) else "")[:30])
                           for w in d.findChildren(QWidget)
                           if w.minimumSizeHint().width() > WIDTH // 3),
                          reverse=True)[:4]
            bad.append("it cannot be made narrower than %d px (%s)"
                       % (d.minimumWidth(), ", ".join(
                           "%s %r %d" % (k, t, n) for n, k, t in asks)))
            bad.append("the widest rows: " + ", ".join(
                "%d: %s" % row for row in widest_rows(d)))
        d.show()
        K.app.processEvents()
        d.resize(WIDTH, max(d.height(), d.minimumHeight(), 100))
        K.app.processEvents()
        if d.layout().hasHeightForWidth():
            d.resize(WIDTH, max(d.height(), d.minimumHeight(),
                                d.layout().totalHeightForWidth(WIDTH)))
            K.app.processEvents()
        if d.width() != WIDTH:
            bad.append("asked for %d px, it is %d" % (WIDTH, d.width()))
            return bad
        shots = os.environ.get("RL_SHOTS")
        if shots:
            d.grab().save(os.path.join(shots, "%s_%s.png" % (
                type(d).__name__, which)))
        kinds = (QCheckBox, QRadioButton, QPushButton, QLabel, QComboBox,
                 QLineEdit, QSpinBox, QDoubleSpinBox)
        for w in d.findChildren(kinds):
            if not w.isVisible() or w.width() < 2:
                continue
            what = "%s %r" % (type(w).__name__,
                              w.text()[:24] if hasattr(w, "text")
                              and callable(w.text) else "")
            right = w.mapTo(d, w.rect().topRight()).x()
            if right > d.width():
                bad.append("%s ends at %d" % (what, right))
            if isinstance(w, (QCheckBox, QRadioButton, QPushButton)) \
                    and w.text():
                # the words as drawn (a WrapTick breaks them over lines),
                # and the room a box or a key keeps around them
                fm = w.fontMetrics()
                shown = QAbstractButton.text(w).replace("&", "")
                room = max(fm.horizontalAdvance(line)
                           for line in shown.splitlines() or [""]) + (
                    fm.height() if isinstance(w, (QCheckBox, QRadioButton))
                    else 6)
                if w.width() < room:
                    bad.append("%s is cut: %d of %d px" % (what, w.width(),
                                                           room))
                # and a box that wrapped is as tall as its lines
                if isinstance(w, (QCheckBox, QRadioButton)) \
                        and w.height() < w.sizeHint().height() - 1:
                    bad.append("%s is %d px tall, its lines need %d"
                               % (what, w.height(), w.sizeHint().height()))
            if isinstance(w, QLabel) and w.text() and w.wordWrap() \
                    and w.heightForWidth(w.width()) > w.height() + 1:
                bad.append("%s is cut: %d of %d px" % (
                    what, w.height(), w.heightForWidth(w.width())))
        # nothing is drawn over anything else it shares a parent with
        leaves = [w for w in d.findChildren(kinds) if w.isVisible()
                  and w.width() > 1 and w.height() > 1
                  and not w.findChildren(kinds)]
        for i, a in enumerate(leaves):
            ga = a.geometry()
            for b in leaves[i + 1:]:
                if a.parent() is not b.parent():
                    continue
                gb = b.geometry()
                ox = min(ga.right(), gb.right()) - max(ga.left(), gb.left())
                oy = min(ga.bottom(), gb.bottom()) - max(ga.top(), gb.top())
                if ox > 2 and oy > 2:
                    bad.append("%s %r over %s %r" % (
                        type(a).__name__, a.text()[:18] if hasattr(a, "text")
                        and callable(a.text) else "", type(b).__name__,
                        b.text()[:18] if hasattr(b, "text")
                        and callable(b.text) else ""))
        return bad

    for name, make in windows:
        d = make()
        seen[name] = d
        bad = wide(d)
        check("%s holds %d px with the %s fonts" % (name, WIDTH, which),
              not bad, "; ".join(bad))
    d = seen["Uncertainty source"]
    listed = [d.raster.itemText(i) for i in range(d.raster.count())]
    check("the rasters offered for the uncertainty hold no map of a report",
          not any("disagreement" in t for t in listed), listed)
    check("but the others are there",
          any("a_map_of_the_classes" in t for t in listed), listed)
    shutil.rmtree(root, ignore_errors=True)
    K.finish()


# ---------------------------------------------------------------- the parent
def run_half(which, fonts):
    env = dict(CHILD)
    if fonts:
        env["QT_QPA_FONTDIR"] = fonts
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    out = subprocess.run([sys.executable, os.path.abspath(__file__),
                          "--child", which], capture_output=True, cwd=HERE,
                         env=env, **TEXT)
    text = out.stdout + out.stderr
    print(text.rstrip())
    return out.returncode == 0 and "all pass" in text


def main():
    halves = [("system", own_fonts())]
    dejavu = dejavu_folder()
    fails = []
    for which, fonts in halves + ([("dejavu", dejavu)] if dejavu else []):
        print("== %s fonts%s" % (which, " from " + fonts if fonts else ""))
        if not run_half(which, fonts):
            fails.append(which)
    if not dejavu:
        print()
        print("SKIPPED: THE DEJAVU HALF. NO DejaVuSans.ttf WAS FOUND, so "
              "nothing here says how these windows look on Ubuntu. Give the "
              "folder with RL_DEJAVU_DIR or --fonts DIR.")
    print()
    print("FAILED: %s" % ", ".join(fails) if fails else "all pass")
    sys.exit(1 if fails else 0)


if "--child" in sys.argv:
    child()
else:
    main()
