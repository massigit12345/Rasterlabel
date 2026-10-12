"""rasterlabel.ui_compare

Measure ▸ Compare two readings…: the window that sets it up, the run with
its progress and its Cancel, the layers, and the report window.

What happens, in order, and why:

- the work is saved first, and the comparison is refused while something
  could not be: the package is what is compared, and a report that quietly
  missed the last ten minutes would look right and be wrong;
- the readings the reader in hand may not see are not offered, and the
  comparison is refused outright when that leaves fewer than two, with the
  words of the blind gate (measure.measure_blind_gate): a blind reader shown
  the other reading's map is a blind reading no more;
- the setup window: which readings (the kind of comparison narrows the two
  lists), which frames (closed by both, or touched by both, with how many
  each and which are left out, live), whether the points count, the
  resamples and the seed, and where;
- an unfinished reading is said, with its frames, and asked about;
- the run, frame by frame, with a Cancel that leaves nothing behind;
- the report is recorded in the manifest (Campaign.save), its maps loaded
  in a group of their own and veiled for a reader who may not see them,
  and the numbers shown.

Check asks compare_findings for the agreement reports whose files are gone
or older than the package.
"""
import importlib
import os
import uuid

from datetime import datetime, timezone

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QApplication, QButtonGroup, QComboBox,
                                 QDialog, QDialogButtonBox,
                                 QGridLayout, QLabel, QMessageBox,
                                 QProgressDialog, QSpinBox)
from qgis.core import (QgsCategorizedSymbolRenderer, QgsFillSymbol,
                       QgsRasterLayer, QgsRendererCategory, QgsVectorLayer)

from .constants import (BOOTSTRAP_N, BOOTSTRAP_SEED, CLOSED_SHARE, NAME,
                        REPORTS_FOLDER)
from .compat import run_dialog
from .errors import log, shielded
from .theme import hold_shape, keep_shape, short_combo, short_spin, titled
from .widgets import narrow_radio, narrow_tick
from .project import rgba
from .campaign import comparison_kind, reading_label, reading_shares
from .layers import add_report_layer
from .reports import (report_entry, report_newest, report_read,
                      report_register, report_stale, report_stamp,
                      report_utc)
from .dialogs import (ReportWindow, report_group, report_part,
                      report_where_rows)
from .compare import (CMP_KIND, CMP_KIND_WORDS, CMP_KAPPA_NOTE, CmpCancelled,
                      cmp_compare, cmp_frames, cmp_label, cmp_left_out_words,
                      cmp_marks, cmp_path_problem, cmp_plan, cmp_readings)
from .agreement import cm_name

COMPARE_NOTES = {
    "inter": "inter-observer: the same ground read by two people in the "
             "same pass.",
    "intra": "intra-observer: only meaningful if the later pass re-read the "
             "ground from scratch, with blind on. Passes can also be layers "
             "of one piece of work (see the pass tooltip).",
    "other": "neither inter- nor intra-observer: two people in two passes, "
             "or any two readings put side by side.",
}
COMPARE_STYLE = {"disagree": "#d6357a", "only_A": "#2a78d6",
                 "only_B": "#eda100"}
# frames by their overall agreement, worst first
COMPARE_RAMP = [(0.0, 0.5, "#b2182b"), (0.5, 0.7, "#ef8a62"),
                (0.7, 0.8, "#fddbc7"), (0.8, 0.9, "#a6dba0"),
                (0.9, 1.000001, "#1b7837")]


def compare_hidden(panel, readings):
    """The readings the reader in hand may not see, asked of the panel's
    one blind gate (measure.measure_blind_gate) one reading at a time, so
    that this module and Annotate's filter can never disagree."""
    gate = getattr(panel, "blind_gate", None)
    if not callable(gate):
        return []
    return [r for r in readings if gate([r])]


def compare_finding(level, what, detail=""):
    """A line of Check, of the kind doctor.py makes. doctor comes after
    this module, so its class is looked up when a line is made."""
    package = globals().get("__package__") or ""
    if package:
        doctor = importlib.import_module(".doctor", package)
        make, levels = doctor.Finding, {"note": doctor.NOTE}
    else:
        make, levels = globals()["Finding"], {"note": globals()["NOTE"]}
    return make(levels.get(level, level), what, detail)


def compare_words(readings):
    names = [reading_label(r) for r in readings]
    if len(names) < 2:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def compare_folder(campaign_folder, a, b):
    """The report folder Compare will make, as the window shows it."""
    return os.path.join(campaign_folder, REPORTS_FOLDER, CMP_KIND,
                        "%s_%s" % (cmp_label(a, b), report_stamp()))


#  The setup window
# =====================================================================
class CompareSetup(QDialog):
    """Which two readings, on which frames, with what, and where."""

    def __init__(self, parent, data, folder, package, readings, marks,
                 shares, frames):
        super().__init__(parent)
        self.setWindowTitle(titled("Compare two readings"))
        self.data = data
        self.campaign_folder = folder
        self.package = package
        self.readings = list(readings)
        self.marks = marks
        self.shares = shares
        self.frames = frames
        self.untiled = not bool(data.get("with_tiles", True))
        self.plan = None
        self.why = ""
        self.folder_edited = False
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        row = 0

        grid.addWidget(report_part("Which readings"), row, 0, 1, 3)
        row += 1
        grid.addWidget(QLabel("Kind"), row, 0)
        self.kind = QComboBox()
        for key in ("inter", "intra", "other"):
            self.kind.addItem(CMP_KIND_WORDS[key], key)
        self.kind.setToolTip(
            "Narrows the two lists: two operators in one pass, one operator "
            "in two passes, or any two readings.")
        grid.addWidget(short_combo(self.kind), row, 1, 1, 2)
        row += 1
        grid.addWidget(QLabel("A"), row, 0)
        self.a = QComboBox()
        grid.addWidget(short_combo(self.a), row, 1, 1, 2)
        row += 1
        grid.addWidget(QLabel("B"), row, 0)
        self.b = QComboBox()
        grid.addWidget(short_combo(self.b), row, 1, 1, 2)
        row += 1
        self.kind_note = self._quiet()
        grid.addWidget(self.kind_note, row, 0, 1, 3)
        row += 1

        grid.addWidget(report_part("Which frames"), row, 0, 1, 3)
        row += 1
        self.rule_group = QButtonGroup(self)
        self.closed = narrow_radio("closed by both readings")
        self.closed.setToolTip(
            "A frame is closed when one reading covers more than %g %% of "
            "its area,\nthe rule of Annotate and Check. Only frames both "
            "readings finished." % (CLOSED_SHARE * 100))
        self.touched = narrow_radio("touched by both readings")
        self.touched.setToolTip(
            "Every frame both readings drew in, finished or not. What a "
            "reading\nleft empty counts as unlabelled.")
        self.closed.setChecked(True)
        for r_, button in ((0, self.closed), (1, self.touched)):
            self.rule_group.addButton(button, r_)
            grid.addWidget(button, row, 0, 1, 3)
            row += 1
        self.left_out = self._quiet()
        grid.addWidget(self.left_out, row, 0, 1, 3)
        row += 1

        grid.addWidget(report_part("What counts"), row, 0, 1, 3)
        row += 1
        self.points = narrow_tick("the points, as in the mask")
        self.points.setChecked(False)
        self.points.setToolTip(
            "Off, the masks compared hold what the areas claim, the masks "
            "Whole raster\nwrites by default. On, every point burns its "
            "footprint over the areas.")
        grid.addWidget(self.points, row, 0, 1, 3)
        row += 1

        grid.addWidget(report_part("Uncertainty"), row, 0, 1, 3)
        row += 1
        grid.addWidget(QLabel("Resamples"), row, 0)
        self.resamples = QSpinBox()
        self.resamples.setRange(0, 100000)
        self.resamples.setSingleStep(500)
        self.resamples.setValue(BOOTSTRAP_N)
        self.resamples.setToolTip(
            "Bootstrap over frames: whole frames are drawn again with "
            "replacement,\nnever pixels. 0 gives no interval; fewer than 5 "
            "frames give none either.")
        grid.addWidget(short_spin(self.resamples), row, 1, 1, 2)
        row += 1
        grid.addWidget(QLabel("Seed"), row, 0)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2 ** 31 - 1)
        self.seed.setValue(BOOTSTRAP_SEED)
        self.seed.setToolTip("Written into the report: the same seed gives "
                             "the same interval.")
        grid.addWidget(short_spin(self.seed), row, 1, 1, 2)
        row += 1

        row, self.where, self.maps = report_where_rows(grid, row, "")
        self.where.textEdited.connect(self._edited)
        # why the report cannot go where it is asked to, when it cannot
        self.path_note = self._quiet()
        self.path_note.setObjectName("warning")
        self.path_note.setVisible(False)
        grid.addWidget(self.path_note, row, 0, 1, 3)
        row += 1
        grid.setRowStretch(row, 1)
        row += 1
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.go = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.go.setText("Compare")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        grid.addWidget(self.buttons, row, 0, 1, 3)

        if self.untiled:
            self.touched.setChecked(True)
            for button in (self.closed, self.touched):
                button.setEnabled(False)
        # the kind that has a pair to offer, first in the list order
        for i in range(self.kind.count()):
            if self._pairs(self.kind.itemData(i)):
                self.kind.setCurrentIndex(i)
                break
        self.kind.currentIndexChanged.connect(
            shielded(self.kind_changed, "Compare"))
        self.a.currentIndexChanged.connect(shielded(self.a_changed,
                                                    "Compare"))
        self.b.currentIndexChanged.connect(shielded(self.refresh, "Compare"))
        self.rule_group.buttonClicked.connect(shielded(self.refresh,
                                                       "Compare"))
        self.points.toggled.connect(shielded(self.refresh, "Compare"))
        self.kind_changed()
        self.resize(max(self.sizeHint().width(), 360),
                    self.sizeHint().height())
        keep_shape(self, 300)

    def _quiet(self):
        label = QLabel("")
        label.setObjectName("quiet")
        label.setWordWrap(True)
        return label

    def _edited(self, *args):
        self.folder_edited = True
        self.gate()

    # ------------------------------------------------------------ lists
    def _fits(self, kind, a, b):
        if a == b:
            return False
        return kind == "other" or comparison_kind(a, b) == kind

    def _pairs(self, kind):
        return [(a, b) for a in self.readings for b in self.readings
                if self._fits(kind, a, b)]

    def _frames_of(self, r):
        held = self.marks.get(r) or {}
        tables = ("polygons", "points") if self.points.isChecked() \
            else ("polygons",)
        found = set()
        for t in tables:
            found |= set(((held.get(t) or {}).get("frames") or {}))
        return len(found)

    def _item(self, r):
        n = self._frames_of(r)
        return "%s · %d frame%s" % (reading_label(r), n, "" if n == 1 else "s")

    def chosen(self, box):
        r = box.currentData()
        return tuple(r) if r else None

    def kind_changed(self, *args):
        kind = self.kind.currentData()
        was = self.chosen(self.a)
        firsts = []
        for a, _ in self._pairs(kind):
            if a not in firsts:
                firsts.append(a)
        self.a.blockSignals(True)
        self.a.clear()
        for r in firsts:
            self.a.addItem(self._item(r), list(r))
        if was in firsts:
            self.a.setCurrentIndex(firsts.index(was))
        self.a.blockSignals(False)
        self.kind_note.setText(COMPARE_NOTES.get(kind, ""))
        self.a_changed()

    def a_changed(self, *args):
        kind = self.kind.currentData()
        a = self.chosen(self.a)
        was = self.chosen(self.b)
        seconds = [b for x, b in self._pairs(kind) if x == a]
        self.b.blockSignals(True)
        self.b.clear()
        for r in seconds:
            self.b.addItem(self._item(r), list(r))
        if was in seconds:
            self.b.setCurrentIndex(seconds.index(was))
        self.b.blockSignals(False)
        self.refresh()

    def rule(self):
        return "touched" if self.touched.isChecked() else "closed"

    # ------------------------------------------------------------ plan
    def refresh(self, *args):
        a, b = self.chosen(self.a), self.chosen(self.b)
        why = ""
        if a is None or b is None:
            self.plan = None
            why = "There is no pair of readings of this kind."
            self.closed.setText("closed by both readings")
            self.touched.setText("touched by both readings")
            self.left_out.setText(why)
        else:
            self.plan = cmp_plan(self.data, self.package, a, b, self.rule(),
                                 self.points.isChecked(), self.marks,
                                 self.shares, self.frames)
            counts = self.plan["counts"]
            if self.untiled:
                self.touched.setText("the campaign, as one region")
                self.closed.setText("closed by both (no frames)")
            else:
                self.closed.setText("closed by both readings (%d)"
                                    % counts["closed"])
                self.touched.setText("touched by both readings (%d)"
                                     % counts["touched"])
            gone = cmp_left_out_words(self.plan)
            said = []
            if gone:
                said.append("left out: " + gone)
            said += self.plan["notes"][:2] if not self.untiled else []
            self.left_out.setText("\n".join(said))
            if self.plan["refusal"]:
                why = self.plan["refusal"]
            elif not self.plan["used"]:
                why = ("No frame qualifies: no frame was %s by both %s and "
                       "%s." % ("closed" if self.rule() == "closed"
                                else "touched", reading_label(a),
                                reading_label(b)))
            if not self.folder_edited:
                self.where.setText(compare_folder(self.campaign_folder, a, b))
        self.left_out.setVisible(bool(self.left_out.text()))
        self.why = why
        self.gate()

    def gate(self):
        """Compare can be pressed when the plan holds and QGIS will be able
        to open what is written where it is asked to go."""
        why = self.why
        a, b = self.chosen(self.a), self.chosen(self.b)
        problem = "" if why or a is None or b is None else cmp_path_problem(
            self.data, self.campaign_folder, a, b,
            self.where.text().strip() or None)
        self.path_note.setText(problem)
        self.path_note.setVisible(bool(problem))
        why = why or problem
        self.go.setEnabled(not why)
        self.go.setToolTip(why or "Changes nothing in the campaign: the "
                           "report goes in a folder of its own.")
        if self.layout() is not None:
            hold_shape(self, 300)

    def result(self):
        return {"A": self.chosen(self.a), "B": self.chosen(self.b),
                "frame_rule": self.rule(),
                "points_in": self.points.isChecked(),
                "n_boot": self.resamples.value(), "seed": self.seed.value(),
                "folder": self.where.text().strip(),
                "maps": self.maps.isChecked()}


#  Measure ▸ Compare two readings…
# =====================================================================
def compare_enabled(panel):
    """(True, "") with two readings or more to compare; else why not."""
    campaign = getattr(panel, "campaign", None)
    if campaign is None:
        return False, "Open a campaign first."
    readings = cmp_readings(cmp_marks(compare_package(campaign)),
                            points_in=True)
    if len(readings) < 2:
        return False, ("Compare needs two readings. This campaign holds %s."
                       % ("one: " + reading_label(readings[0]) if readings
                          else "none yet"))
    return True, ""


def compare_package(campaign):
    return getattr(campaign, "package_path", None) or os.path.join(
        campaign.folder, "annotation.gpkg")


def compare_saved(panel):
    """Save what the modules hold; True when everything is on disk."""
    for m in (getattr(panel, "section", None),
              getattr(panel, "annotation", None)):
        if m is not None and m.unsaved():
            try:
                m.save()
            except Exception as err:
                log("could not save before comparing: %s" % err)
    try:
        if panel.pending_layers():
            panel.flush_layers()
    except Exception as err:
        log("could not write the layers before comparing: %s" % err)
    still = [m for m in (getattr(panel, "section", None),
                         getattr(panel, "annotation", None))
             if m is not None and m.unsaved()]
    return not still and not panel.pending_layers()


def compare_unfinished_text(plan, n_used):
    """The question for readings with frames touched and not closed, or ""
    when both are finished."""
    parts = []
    total = 0
    for side in ("A", "B"):
        gone = plan["unfinished"][side]
        if not gone:
            continue
        total += len(gone)
        frames = ", ".join("%s %d %%" % (t, int(round(100 * s)))
                           for t, s in gone[:3])
        if len(gone) > 3:
            frames += ", +%d more" % (len(gone) - 3)
        parts.append("%s has %d frame%s touched but not closed (%s)"
                     % (reading_label(plan[side]), len(gone),
                        "" if len(gone) == 1 else "s", frames))
    if not parts:
        return ""
    fate = ("They are left out." if plan["frame_rule"] == "closed"
            else "They are compared as they stand.")
    which = "closed " if plan["frame_rule"] == "closed" else ""
    return ("%s. %s Whoever is still reading must not see this map. Compare "
            "the %d %sframe%s?" % ("; ".join(parts), fate, n_used, which,
                                   "" if n_used == 1 else "s"))


def compare_ask(panel, text):
    """[Compare] [Cancel], Cancel the default: True on Compare."""
    box = QMessageBox(QMessageBox.Icon.Question, NAME, text,
                      QMessageBox.StandardButton.Cancel, panel)
    go = box.addButton("Compare", QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    run_dialog(box)
    return box.clickedButton() is go


def compare_start(panel):
    """Measure ▸ Compare two readings…, from the press to the report."""
    campaign = getattr(panel, "campaign", None)
    if campaign is None:
        return None
    if not compare_saved(panel):
        QMessageBox.warning(
            panel, NAME,
            "There is work that could not be written to the package.\n\n"
            "Comparing now would read the file as it stands on disk, without "
            "it. Save by hand first, and look at the log for why it refused.")
        return None
    package = compare_package(campaign)
    marks = cmp_marks(package)
    readings = cmp_readings(marks, points_in=True)
    if len(readings) < 2:
        QMessageBox.information(panel, NAME, compare_enabled(panel)[1])
        return None
    hidden = compare_hidden(panel, readings)
    visible = [r for r in readings if r not in hidden]
    if len(visible) < 2:
        QMessageBox.warning(panel, NAME, panel.blind_gate(hidden))
        log("compare refused: %s hidden from the reader"
            % compare_words(hidden))
        return None
    data = campaign.data
    tiled = bool(data.get("with_tiles", True))
    shares = reading_shares(package) if tiled else {}
    frames = cmp_frames(package) if tiled else []
    dialog = CompareSetup(panel, data, campaign.folder, package, visible,
                          marks, shares, frames)
    if not run_dialog(dialog):
        return None
    asked = dialog.result()
    a, b = asked["A"], asked["B"]
    if not a or not b:
        return None
    refusal = panel.blind_gate([a, b])
    if refusal:
        QMessageBox.warning(panel, NAME, refusal)
        return None
    plan = cmp_plan(data, package, a, b, asked["frame_rule"],
                    asked["points_in"], marks, shares, frames)
    if plan["refusal"]:
        QMessageBox.warning(panel, NAME, plan["refusal"])
        return None
    if not plan["used"]:
        QMessageBox.information(panel, NAME, "No frame qualifies, so there "
                                "is nothing to compare.")
        return None
    question = compare_unfinished_text(plan, len(plan["used"]))
    if question and not compare_ask(panel, question):
        log("compare not run: a reading is unfinished")
        return None
    target = asked["folder"] or None
    if target and os.path.normcase(os.path.normpath(target)) == \
            os.path.normcase(os.path.normpath(compare_folder(
                campaign.folder, a, b))):
        target = None          # the folder offered: reports/ chooses the name
    recipe = {"data": data, "folder": campaign.folder, "package": package,
              "plan": plan, "n_boot": asked["n_boot"], "seed": asked["seed"],
              "target": target}
    result = compare_run(panel, recipe)
    if result is None:
        return None
    compare_register(campaign, result)
    compare_layers(panel, campaign, result, asked["maps"])
    window = compare_window(panel, result)
    run_dialog(window)
    return result


def compare_run(panel, recipe):
    """The run, in a progress window with Cancel. The result, or None."""
    n = len(recipe["plan"]["used"])
    progress = QProgressDialog("Comparing %s and %s…"
                               % (reading_label(recipe["plan"]["A"]),
                                  reading_label(recipe["plan"]["B"])),
                               "Cancel", 0, n, panel)
    progress.setWindowTitle(titled("Compare two readings"))
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    def tick(done, total):
        progress.setValue(done)
        QApplication.processEvents()

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    said = None
    try:
        return cmp_compare(recipe, tick, progress.wasCanceled)
    except CmpCancelled:
        said = (QMessageBox.information, "Stopped. Nothing was written.")
        log("compare stopped from its progress window: nothing written")
        return None
    except Exception as err:
        said = (QMessageBox.critical, "Nothing was written:\n\n%s" % err)
        log("compare failed: %s" % err)
        return None
    finally:
        QApplication.restoreOverrideCursor()
        progress.close()
        progress.deleteLater()
        if said is not None:
            said[0](panel, NAME, said[1])


def compare_register(campaign, result):
    """The report, remembered by the manifest (data["reports"])."""
    try:
        rel = os.path.relpath(result["folder"], campaign.folder)
    except ValueError:
        rel = result["folder"]          # another drive: kept whole
    summary = result.get("summary_json") or {}
    entry = report_entry(CMP_KIND, uuid.uuid4().hex[:12], result["label"],
                         result.get("created_utc") or report_utc(), rel,
                         summary.get("headline") or {})
    report_register(campaign.data, entry)
    try:
        campaign.save()
    except Exception as err:
        log("the report is written, but the manifest could not be told: %s"
            % err, loud=True)
    return entry


def compare_style_layer(layer, part):
    """The look of the two vector layers: the polygons by kind, the
    frames by their overall agreement."""
    if part == "disagreement":
        cats = []
        for kind, colour in COMPARE_STYLE.items():
            sym = QgsFillSymbol.createSimple({
                "color": rgba(colour, 180), "outline_color": rgba(colour),
                "outline_width": "0.3"})
            cats.append(QgsRendererCategory(kind, sym,
                                            kind.replace("_", " ")))
        layer.setRenderer(QgsCategorizedSymbolRenderer("kind", cats))
        return
    from qgis.core import QgsGraduatedSymbolRenderer, QgsRendererRange
    ranges = []
    for low, high, colour in COMPARE_RAMP:
        sym = QgsFillSymbol.createSimple({
            "color": rgba(colour, 120), "outline_color": rgba("#303030"),
            "outline_width": "0.4"})
        ranges.append(QgsRendererRange(low, high, sym, "%.1f – %.1f"
                                       % (low, min(high, 1.0))))
    layer.setRenderer(QgsGraduatedSymbolRenderer("overall", ranges))


def compare_vector_styles(gpkg):
    """The .qml of the two layers of the report's GeoPackage, written
    beside it (<stem>_polygons.qml, <stem>_frames.qml: the disagreement
    map has <stem>_disagreement.qml already). Returns them by layer. Needs
    QGIS, on its main thread."""
    out = {}
    stem = os.path.splitext(gpkg)[0]
    for part, name in (("disagreement", "polygons"), ("frames", "frames")):
        try:
            layer = QgsVectorLayer("%s|layername=%s" % (gpkg, part), part,
                                   "ogr")
            if not layer.isValid():
                continue
            compare_style_layer(layer, part)
            qml = "%s_%s.qml" % (stem, name)
            layer.saveNamedStyle(qml)
            out[part] = qml
        except Exception as err:
            log("no style for the %s of the report: %s" % (part, err))
        finally:
            layer = None
    return out


def compare_layers(panel, owner, result, maps=True):
    """The styles of the vectors, and the maps in QGIS when asked: in the
    group "agreement <label>" under the campaign's, the disagreement map
    and its polygons on, the pairs and the frames off. Then veiled for a
    reader who may not see them."""
    folder = result["folder"]
    files = result["files"]
    gpkg = os.path.join(folder, files["vectors"])
    styles = compare_vector_styles(gpkg)
    if not maps:
        return []
    plan = result["plan"]
    readings = [plan["A"], plan["B"]]
    label = result["label"]
    base = os.path.splitext(files["vectors"])[0]
    loaded = []
    for part, path, visible in (
            ("disagreement", os.path.join(folder, files["disagreement"]),
             True),
            ("pairs", os.path.join(folder, files["pairs"]), False)):
        layer = QgsRasterLayer(path, "%s_%s" % (base, part))
        if not layer.isValid():
            log("the %s map could not be loaded: %s" % (part, path))
            continue
        loaded.append(add_report_layer(layer, owner, CMP_KIND, label, part,
                                       readings, visible))
    for part, name, visible in (("disagreement", "polygons", True),
                                ("frames", "frames", False)):
        layer = QgsVectorLayer("%s|layername=%s" % (gpkg, part),
                               "%s_%s" % (base, name), "ogr")
        if not layer.isValid():
            log("the %s of the report could not be loaded" % part)
            continue
        if part in styles:
            layer.loadNamedStyle(styles[part])
        else:
            compare_style_layer(layer, part)
        loaded.append(add_report_layer(layer, owner, CMP_KIND, label, name,
                                       readings, visible))
    try:
        panel.veil_reports()
    except Exception as err:
        log("cannot veil the maps of the report: %s" % err)
    return loaded


#  The report window
# =====================================================================
def _compare_num(v, digits=3):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return "%.*f" % (digits, f) if f == f and abs(f) != float("inf") \
        else "—"


def _compare_ci(value, ci):
    if ci and ci[0] is not None and ci[1] is not None:
        return "%s   CI %s–%s" % (_compare_num(value), _compare_num(ci[0]), _compare_num(ci[1]))
    return _compare_num(value)


def compare_window(panel, result):
    """The report window of one run: ReportWindow, filled."""
    s = result["summary"]
    plan = result["plan"]
    o = s["pooled"]["overall"]
    counts = s["pooled"]["counts"]
    boot = s["bootstrap"]
    ci = boot.get("ci") or {}
    spread = s.get("spread") or {}
    n_frames = len(result["ids"])
    scope = "%d frame%s · %s px labelled by both" % (
        n_frames, "" if n_frames == 1 else "s",
        report_group("%d" % counts["both"]))
    if plan["untiled"]:
        scope = "the whole campaign, one region · %s px labelled by both" % (
            report_group("%d" % counts["both"]))
    total = float(counts.get("total") or 0) or 1.0
    headline = [("Agreement", _compare_ci(o["po"], ci.get("po")))]
    sp = spread.get("po")
    if sp and sp.get("n"):
        headline.append(("  per frame", "median %s   IQR %s–%s   (%d)"
                         % (_compare_num(sp["median"]), _compare_num(sp["q1"]),
                            _compare_num(sp["q3"]), sp["n"])))
    headline += [
        ("Kappa*", _compare_ci(o.get("kappa"), ci.get("kappa"))),
        ("Quantity / allocation", "%s / %s" % (_compare_num(o["quantity"]),
                                               _compare_num(o["allocation"]))),
        ("Mean IoU", _compare_ci(o["mean_iou"], ci.get("mean_iou"))),
        ("Only A / only B / neither", "%.1f %% / %.1f %% / %.1f %%"
         % (100 * counts["only_A"] / total, 100 * counts["only_B"] / total,
            100 * counts["neither"] / total))]
    delay = (result.get("summary_json") or {}).get("delay_h") or {}
    if delay.get("median") is not None:
        headline.append(("B drawn after A", "%.0f h (median over frames)"
                         % delay["median"]))
    names, colours = result["names"], result["colours"]
    rows, swatches = [], []
    for c in s["pooled"]["per_class"]:
        if not (c["n_A"] or c["n_B"]):
            continue
        lo, hi = (ci.get("iou:%d" % c["code"]) or [None, None])[:2]
        rows.append([cm_name(c["code"], names), c["iou"],
                     "%s–%s" % (_compare_num(lo), _compare_num(hi)) if lo is not None
                     else None, c["f1"], c["rate_A"], c["rate_B"]])
        swatches.append(colours.get(c["code"], ""))
    tables = [{"title": "Per class", "columns": ["class", "IoU", "IoU CI",
                                                 "F1 (Dice)", "from A",
                                                 "from B"],
               "rows": rows, "colours": swatches,
               "align": [None, None, "r"],
               "tips": ["", "Intersection over union of the class: the "
                        "pixels both gave it over the pixels either gave it.",
                        "The interval of the IoU over the frames.",
                        "The Dice coefficient: twice the pixels both gave "
                        "the class over the pixels A and B gave it together.",
                        "Of what A gave the class, the share B gave it too.",
                        "Of what B gave the class, the share A gave it too."]}]
    notes = ["* " + CMP_KAPPA_NOTE + ".",
             "from A: of what A gave a class, the share B gave it too; "
             "from B, the other way round."]
    if boot.get("reason"):
        notes.append("No interval: %s." % boot["reason"])
    gone = cmp_left_out_words(plan, most=5)
    if gone:
        notes.append("Left out: %s." % gone)
    notes += [n[0].upper() + n[1:] + "." for n in result["notes"][:3]]
    return ReportWindow(panel, "%s vs %s" % (reading_label(plan["A"]),
                                             reading_label(plan["B"])),
                        scope, headline, tables, notes, result["folder"])


#  Check
# =====================================================================
def compare_findings(campaign):
    """What Check says of the agreement reports: files listed by a report
    that are gone, and the newest report older than the package."""
    data = getattr(campaign, "data", None) or {}
    folder = getattr(campaign, "folder", None)
    entries = [e for e in data.get("reports") or []
               if e.get("kind") == CMP_KIND]
    if not folder or not entries:
        return []
    out = []
    missing = []
    for e in entries:
        where = os.path.join(folder, *str(e.get("folder") or "").split("/"))
        if not os.path.isdir(where):
            continue                    # reports_findings says so already
        summary = report_read(os.path.join(where, "summary.json")) or {}
        for f in summary.get("files") or []:
            if not os.path.exists(os.path.join(where, f)):
                missing.append("%s/%s" % (e.get("folder"), f))
    if missing:
        out.append(compare_finding("note", "%d file%s of the agreement reports %s not "
                           "there" % (len(missing),
                                      "" if len(missing) == 1 else "s",
                                      "is" if len(missing) == 1 else "are"),
                           ", ".join(missing[:4])
                           + (", ..." if len(missing) > 4 else "")))
    newest = report_newest(data, CMP_KIND)
    package = os.path.join(folder, "annotation.gpkg")
    if newest is not None and os.path.isfile(package):
        where = os.path.join(folder,
                             *str(newest.get("folder") or "").split("/"))
        summary = report_read(os.path.join(where, "summary.json"))
        if summary:
            try:
                mtime = os.path.getmtime(package)
                from_disk = [{"path": package, "sha256": None,
                              "mtime_utc": report_utc(datetime.fromtimestamp(
                                  mtime, timezone.utc))}]
                stale, why = report_stale(summary, from_disk)
            except OSError:
                stale, why = False, ""
            if stale:
                out.append(compare_finding("note", "the newest agreement report was "
                                   "made before the last change to the "
                                   "annotation", "%s: %s" % (
                                       newest.get("folder"), why)))
    return out
