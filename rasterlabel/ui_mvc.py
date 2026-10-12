"""rasterlabel.ui_mvc

Measure ▸ Model vs corrected…: the window that sets it up, the run with its
progress and its Cancel, the map of pairs in QGIS, and the report window.

What happens, in order, and why:

- what Correct keeps is written first (its hooks are flushed): every stroke
  is on disk already, and the comparison reads the files;
- the setup window: on which ground (the whole map, the ground the strokes
  swept, or inside the polygons of a layer, each with what it is biased
  towards), beside it people against people (nobody, another person's
  correction of the same map, or the agreement report of an annotation
  campaign), the map of pairs, and where;
- another person's correction is asked about once: comparing with it shows
  how far their map is from this one, which ends the blindness of whichever
  of the two is still being corrected. Only numbers are shown of it, never
  a layer;
- the run, a strip at a time, with a Cancel that leaves nothing behind;
- the report is recorded in the correction's manifest
  (CorrectionCampaign.save), its map loaded in a group of its own under the
  correction's when asked, the numbers shown, and the quiet line under the
  tally of Correct says the newest one.
"""
import os
import uuid

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QApplication, QButtonGroup, QComboBox,
                                 QDialog, QDialogButtonBox,
                                 QFileDialog, QGridLayout, QLabel,
                                 QMessageBox, QProgressDialog)
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsGeometry, QgsProject, QgsRasterLayer,
                       QgsVectorLayer)

from .constants import (CORRECTION_MANIFEST, GEOM_POLYGON, NAME,
                        REPORTS_FOLDER)
from .compat import run_dialog
from .errors import log, shielded
from .theme import hold_shape, keep_shape, short_combo, titled
from .widgets import narrow_radio, narrow_tick
from .campaign import operator_word
from .layers import add_report_layer
from .reports import (report_entry, report_register, report_stamp,
                      report_utc)
from .correction import (changes_path_of, copy_of_manifest, corrections_of,
                         peek_correction, reviewed_path_of, same_file)
from .dialogs import (ReportWindow, report_group, report_number,
                      report_part, report_where_rows)
from .agreement import cm_name
from .model_vs_corrected import (MVC_KAPPA_NOTE, MVC_KIND, MVC_NOTES,
                                 MVC_SCOPE_WORDS, MvcCancelled, mvc_counts,
                                 mvc_grid_refusal, mvc_people_word,
                                 mvc_percent, mvc_read_people, mvc_report,
                                 mvc_source_changed)

MVC_NOBODY = "nobody"
MVC_A_REPORT = "an agreement report…"
MVC_PA_TIP = ("PA, producer's accuracy of the model: of the pixels the "
              "corrected map gives\nthis class, the share the model gave it "
              "too (1 - omission).\nUA, user's accuracy: of the pixels the "
              "model gave this class, the share\nthe corrected map keeps "
              "(1 - commission). The corrected map is the reference.")
MVC_BLIND_TEXT = ("Comparing with %s tells you how far that map is from "
                  "yours. If either of you is still correcting, that ends the "
                  "blindness of the second correction. Only the numbers are "
                  "shown of it, never the map.\n\nCompare anyway?")


def _mvc_px(n):
    return report_group("%d" % int(n or 0))


def mvc_section(panel):
    """Correct on the open correction, or None: a correction is open only
    while Correct is."""
    book = getattr(panel, "correction", None)
    section = getattr(panel, "section", None)
    if book is None or section is None:
        return None
    if getattr(section, "book", None) is not book or \
            not getattr(section, "path", ""):
        return None
    return section


def mvc_source_trouble(book):
    """The reconcile text about the map the model made when it is not where
    it was, or ""."""
    source = str((book.data or {}).get("source") or "")
    if not source:
        return "The correction does not say which map it started from."
    if os.path.exists(source.split("|")[0]):
        return ""
    try:
        said = [t for t in book.reconcile()
                if t.startswith("the map it started from")]
    except Exception:
        said = []
    text = said[0] if said else ("the map it started from is no longer "
                                 "where it was:\n   %s" % source)
    return (text[0].upper() + text[1:] + "\nModel vs corrected compares the "
            "corrected map with it: put it back where it was, then measure.")


#  Measure ▸ Model vs corrected…
# =====================================================================
def mvc_enabled(panel):
    """(True, "") when the open correction can be measured; else why not."""
    book = getattr(panel, "correction", None)
    if book is None:
        return False, "Open a correction first."
    trouble = mvc_source_trouble(book)
    if trouble:
        return False, trouble
    copy = getattr(book, "working_path", "") or ""
    if not copy or not os.path.exists(copy):
        return False, "The working copy of this correction is missing."
    why = mvc_grid_refusal(str(book.data.get("source")).split("|")[0], copy,
                           "the map it started from", empty_ok=True)
    if why:
        return False, why[0].upper() + why[1:] + "."
    return True, ""


def mvc_other_corrections(book):
    """The other corrections of the same map, that can be read: [(label,
    {kind, manifest, path, band, operator, name})], newest first."""
    out = []
    mine = os.path.join(book.folder, CORRECTION_MANIFEST)
    source = str(book.data.get("source") or "")
    try:
        found = corrections_of(source)
    except Exception as err:
        log("cannot list the other corrections of the map: %s" % err)
        found = []
    for kind, manifest, name in found:
        if kind != "open" or same_file(manifest, mine):
            continue
        data = peek_correction(manifest) or {}
        copy = copy_of_manifest(manifest, data)
        if not copy or not os.path.exists(copy):
            continue
        who = operator_word(data.get("operator")) or "?"
        out.append(("%s's correction %s" % (who, name),
                    {"kind": "correction", "manifest": manifest,
                     "path": copy, "band": int(data.get("band", 1) or 1),
                     "operator": who, "name": name}))
    return out


def mvc_polygon_layers():
    """The polygon layers of the project, by name: [(name, layer)]."""
    out = []
    try:
        layers = list(QgsProject.instance().mapLayers().values())
    except Exception:
        layers = []
    for lyr in layers:
        try:
            if isinstance(lyr, QgsVectorLayer) and lyr.isValid() and \
                    lyr.geometryType() == GEOM_POLYGON:
                out.append((lyr.name(), lyr))
        except Exception:
            continue
    out.sort(key=lambda t: t[0].lower())
    return out


def mvc_layer_polygons(layer, wkt, selected_only):
    """The polygons of a layer in the system of the copy, as WKB: [{fid,
    wkb}]. Transformed here, on the side that has QGIS."""
    target = QgsCoordinateReferenceSystem()
    target.createFromWkt(wkt or "")
    transform = None
    if target.isValid() and layer.crs().isValid() and layer.crs() != target:
        transform = QgsCoordinateTransform(layer.crs(), target,
                                           QgsProject.instance())
    features = layer.selectedFeatures() if selected_only \
        else layer.getFeatures()
    out = []
    for f in features:
        geom = QgsGeometry(f.geometry())
        if geom is None or geom.isEmpty():
            continue
        if transform is not None:
            geom.transform(transform)
        out.append({"fid": int(f.id()), "wkb": bytes(geom.asWkb())})
    return out


def mvc_folder(book, scope):
    """The report folder Model vs corrected will make, as the window shows
    it."""
    return os.path.join(book.folder, REPORTS_FOLDER, MVC_KIND,
                        "%s_%s" % (scope, report_stamp()))


#  The setup window
# =====================================================================
class ModelVsCorrectedSetup(QDialog):
    """On which ground, beside whom, and where."""

    def __init__(self, parent, book, section, counts, layers=(), others=(),
                 source_changed=False):
        super().__init__(parent)
        self.setWindowTitle(titled("Model vs corrected"))
        self.book = book
        self.section = section
        self.counts = dict(counts or {})
        self.layers = list(layers)
        self.others = list(others)
        self.report_path = None
        self.people_refusal = ""
        self.folder_edited = False
        self.poly_counts = None
        record = book.data or {}
        self.since = int(record.get("reviewed_since") or 0) \
            if self.counts.get("reviewed") else None
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        row = 0
        intro = self._quiet("The map the model made against the map as "
                            "corrected, pixel by pixel. The corrected map "
                            "is the reference.")
        grid.addWidget(intro, row, 0, 1, 3)
        row += 1
        if source_changed:
            warn = self._quiet("The map the model made was changed after "
                               "this correction copied it: what is compared "
                               "is that map as it is now.")
            warn.setObjectName("warning")
            grid.addWidget(warn, row, 0, 1, 3)
            row += 1

        grid.addWidget(report_part("Which ground"), row, 0, 1, 3)
        row += 1
        self.scope_group = QButtonGroup(self)
        self.whole = narrow_radio("the whole map")
        self.whole_note = self._quiet("")
        self.swept = narrow_radio("the ground the strokes swept")
        self.swept_note = self._quiet("")
        self.inside = narrow_radio("inside the polygons of a layer")
        self.layer = short_combo(QComboBox())
        self.layer.setToolTip("A polygon layer of the project: frames "
                              "reviewed whole, a sample drawn at random...")
        for name, lyr in self.layers:
            self.layer.addItem(name, lyr.id())
        self.selected = narrow_tick("selected polygons only")
        self.inside_note = self._quiet("")
        for i, (button, note) in enumerate(((self.whole, self.whole_note),
                                            (self.swept, self.swept_note))):
            self.scope_group.addButton(button, i)
            grid.addWidget(button, row, 0, 1, 3)
            row += 1
            grid.addWidget(note, row, 0, 1, 3)
            row += 1
        self.scope_group.addButton(self.inside, 2)
        grid.addWidget(self.inside, row, 0, 1, 3)
        row += 1
        grid.addWidget(self.layer, row, 0, 1, 3)
        row += 1
        grid.addWidget(self.selected, row, 0, 1, 3)
        row += 1
        grid.addWidget(self.inside_note, row, 0, 1, 3)
        row += 1
        self.whole.setChecked(True)

        grid.addWidget(report_part("Beside it: people against people"), row,
                       0, 1, 3)
        row += 1
        self.people = short_combo(QComboBox())
        self.people.addItem(MVC_NOBODY, None)
        for label, entry in self.others:
            self.people.addItem(label, entry)
        self.people.addItem(MVC_A_REPORT, "report")
        self.people.setToolTip(
            "Another person's correction of this same map, compared on the "
            "same pixels,\nor the agreement report of an annotation campaign "
            "(its summary.json),\nwhich is on other pixels and is matched "
            "class by class by name.")
        grid.addWidget(self.people, row, 0, 1, 3)
        row += 1
        self.people_note = self._quiet("")
        grid.addWidget(self.people_note, row, 0, 1, 3)
        row += 1

        grid.addWidget(report_part("What to write"), row, 0, 1, 3)
        row += 1
        tables = narrow_tick("the tables (CSV and JSON)")
        tables.setChecked(True)
        tables.setEnabled(False)
        tables.setToolTip("Always written: they are the report.")
        grid.addWidget(tables, row, 0, 1, 3)
        row += 1
        self.write_map = narrow_tick("the map of what changed, styled for QGIS")
        self.write_map.setChecked(True)
        self.write_map.setToolTip(
            "A map of pairs on the grid of the copy: which class of the model "
            "met\nwhich class of the corrected map at each pixel, 0 outside.")
        grid.addWidget(self.write_map, row, 0, 1, 3)
        row += 1
        row, self.where, self.maps = report_where_rows(grid, row, "")
        self.where.textEdited.connect(self._edited)
        self.maps.setText("put the map in QGIS")
        grid.setRowStretch(row, 1)
        row += 1
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.go = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.go.setText("Compare")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        grid.addWidget(self.buttons, row, 0, 1, 3)

        # Toggled, not clicked: a scope chosen any other way than by a click
        # (the keyboard, or the program) left the folder named for the scope
        # before, and a report of the ground swept was written as whole_...
        self.scope_group.buttonToggled.connect(shielded(
            lambda button, on: on and self.refresh(), "Model vs corrected"))
        self.layer.currentIndexChanged.connect(
            shielded(self.polygons_changed, "Model vs corrected"))
        self.selected.toggled.connect(
            shielded(self.polygons_changed, "Model vs corrected"))
        self.people.currentIndexChanged.connect(
            shielded(self.people_changed, "Model vs corrected"))
        self.write_map.toggled.connect(self.maps.setEnabled)
        self.fill_notes()
        self.refresh()
        self.resize(max(self.sizeHint().width(), 360),
                    self.sizeHint().height())
        keep_shape(self, 300)

    def _quiet(self, text):
        label = QLabel(text)
        label.setObjectName("quiet")
        label.setWordWrap(True)
        return label

    def _edited(self, *args):
        self.folder_edited = True

    # ------------------------------------------------------------ notes
    def fill_notes(self):
        c = self.counts
        total = c.get("map_px") or 0
        self.whole_note.setText("%s px; ground nobody looked at counts as "
                                "right: an upper bound" % _mvc_px(total))
        swept = c.get("swept_px") or 0
        if swept:
            words = ("%s px, %.1f %% of the map; chosen where the model was "
                     "wrong: a lower bound" % (_mvc_px(swept),
                                               100.0 * swept / total
                                               if total else 0.0))
            if not c.get("reviewed"):
                words += (". The ground swept is not recorded for this "
                          "correction: only the pixels its strokes changed "
                          "count")
            elif self.since:
                words += (". The first %d stroke%s left no footprint: only "
                          "the pixels %s changed count"
                          % (self.since, "" if self.since == 1 else "s",
                             "it" if self.since == 1 else "they"))
            self.swept_note.setText(words)
        else:
            self.swept_note.setText("nothing has been swept yet")
        self.swept.setEnabled(bool(swept))
        if not self.layers:
            self.inside.setEnabled(False)
            self.layer.setEnabled(False)
            self.selected.setEnabled(False)
            self.inside_note.setText("there is no polygon layer in the "
                                     "project")

    def chosen_layer(self):
        lid = self.layer.currentData()
        for _, lyr in self.layers:
            if lyr.id() == lid:
                return lyr
        return None

    def polygons(self):
        """The chosen polygons, in the copy's system, as WKB."""
        lyr = self.chosen_layer()
        if lyr is None:
            return []
        return mvc_layer_polygons(lyr, self.section.wkt,
                                  self.selected.isChecked())

    def polygons_changed(self, *args):
        self.poly_counts = None
        self.refresh()

    def scope(self):
        if self.inside.isChecked():
            return "polygons"
        if self.swept.isChecked():
            return "swept"
        return "whole"

    # ------------------------------------------------------------ people
    def people_changed(self, *args):
        entry = self.people.currentData()
        self.people_refusal = ""
        self.report_path = None
        if entry == "report":
            got, _ = QFileDialog.getOpenFileName(
                self, "The agreement report to put beside it",
                os.path.join(self.book.folder), "summary.json (summary.json)")
            if got:
                self.set_report(got)
            else:
                self.people.blockSignals(True)
                self.people.setCurrentIndex(0)
                self.people.blockSignals(False)
        elif isinstance(entry, dict):
            why = mvc_grid_refusal(entry["path"], self.section.path,
                                   entry["operator"] + "'s correction")
            if why:
                self.people_refusal = why[0].upper() + why[1:] + "."
        self.refresh()

    def set_report(self, path):
        """An agreement report chosen, read at once so a wrong file is said
        here and not after the run."""
        try:
            people = mvc_read_people(path)
        except IOError as err:
            self.report_path = None
            self.people_refusal = str(err)
            return
        self.report_path = path
        self.people.setToolTip(path)
        self.people_note.setText(
            "%s: other pixels, classes matched by name, side by side and "
            "not a paired comparison" % mvc_people_word(people))

    # ------------------------------------------------------------ state
    def refresh(self, *args):
        scope = self.scope()
        why = ""
        if scope == "polygons":
            if self.poly_counts is None:
                try:
                    polys = self.polygons()
                    self.poly_counts = mvc_counts(
                        self.section.path, self.section.band_no,
                        self.section.changes_path,
                        reviewed_path_of(self.book.data, self.section.path),
                        polys) if polys else {"poly_px": 0,
                                              "poly_swept_px": 0}
                    self.poly_counts["polygons"] = len(polys)
                except Exception as err:
                    self.poly_counts = {"poly_px": 0, "poly_swept_px": 0,
                                        "polygons": 0, "error": str(err)}
            pc = self.poly_counts
            if pc.get("error"):
                why = "The polygons cannot be read: %s" % pc["error"]
                self.inside_note.setText(why)
            elif not pc.get("poly_px"):
                why = "No pixel of the map is inside these polygons."
                self.inside_note.setText("%d polygon%s, no pixel of the map "
                                         "inside" % (pc.get("polygons", 0),
                                                     "" if pc.get(
                                                         "polygons") == 1
                                                     else "s"))
            else:
                self.inside_note.setText(
                    "%d polygon%s, %s px; swept inside them: %.1f %%. %s"
                    % (pc["polygons"], "" if pc["polygons"] == 1 else "s",
                       _mvc_px(pc["poly_px"]),
                       100.0 * pc["poly_swept_px"] / pc["poly_px"],
                       MVC_NOTES["polygons"][0].upper()
                       + MVC_NOTES["polygons"][1:] + "."))
        elif scope == "swept" and not self.counts.get("swept_px"):
            why = "Nothing has been swept yet."
        elif not self.counts.get("map_px"):
            why = "The corrected map holds no pixel with a class."
        if self.people_refusal:
            why = why or self.people_refusal
            self.people_note.setText(self.people_refusal)
        elif not isinstance(self.people.currentData(), str):
            entry = self.people.currentData()
            self.people_note.setText(
                "" if entry is None else "compared on the same pixels: only "
                "the numbers are shown of it, never its map")
        self.layer.setEnabled(bool(self.layers) and scope == "polygons")
        self.selected.setEnabled(bool(self.layers) and scope == "polygons")
        if not self.folder_edited:
            self.where.setText(mvc_folder(self.book, scope))
        self.go.setEnabled(not why)
        self.go.setToolTip(why or "Changes nothing in the correction: the "
                           "report goes in a folder of its own.")
        if self.layout() is not None:
            hold_shape(self, 300)

    def result(self):
        entry = self.people.currentData()
        people = None
        if entry == "report" and self.report_path:
            people = {"kind": "agreement_report", "path": self.report_path}
        elif isinstance(entry, dict):
            people = dict(entry)
        lyr = self.chosen_layer() if self.scope() == "polygons" else None
        return {"scope": self.scope(),
                "polygons": self.polygons() if lyr is not None else None,
                "layer": lyr.name() if lyr is not None else None,
                "selected_only": self.selected.isChecked()
                if lyr is not None else None,
                "people": people, "write_map": self.write_map.isChecked(),
                "load": self.maps.isChecked() and self.write_map.isChecked(),
                "folder": self.where.text().strip()}


#  From the press to the report
# =====================================================================
def mvc_ask(panel, text):
    """[Compare] [Cancel], Cancel the default: True on Compare."""
    box = QMessageBox(QMessageBox.Icon.Question, NAME, text,
                      QMessageBox.StandardButton.Cancel, panel)
    go = box.addButton("Compare", QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    run_dialog(box)
    return box.clickedButton() is go


def mvc_recipe(book, section, asked):
    """What the engine is handed, from the correction and the window."""
    record = book.data or {}
    classes = record.get("classes") or []
    source = str(record.get("source") or "").split("|")[0]
    recipe = {"model": {"path": source, "band": int(record.get("band", 1))},
              "corrected": {"path": section.path,
                            "band": int(section.band_no)},
              "scope": asked["scope"],
              "changes": changes_path_of(record, section.path),
              "reviewed": reviewed_path_of(record, section.path),
              "polygons": asked.get("polygons"),
              "layer": asked.get("layer"),
              "selected_only": asked.get("selected_only"),
              "codes": [int(c["code"]) for c in classes],
              "names": {int(c["code"]): str(c.get("name") or "")
                        for c in classes},
              "colours": {int(c["code"]): str(c.get("colour") or "")
                          for c in classes},
              "pixel_m2": float(getattr(section, "pixel_area_m2", 0.0)
                                or 0.0) or None,
              # the pixel's ground row by row, where it is not one value
              "row_m2": getattr(section, "row_m2", None),
              "write_map": asked.get("write_map", True),
              "source_changed_after_copy": mvc_source_changed(record,
                                                              source)}
    people = asked.get("people")
    if people and people.get("kind") == "correction":
        recipe["other"] = {"path": people["path"],
                           "band": int(people.get("band", 1))}
    return recipe


def mvc_start(panel):
    """Measure ▸ Model vs corrected…, from the press to the report."""
    book = getattr(panel, "correction", None)
    section = mvc_section(panel)
    if book is None or section is None:
        return None
    on, why = mvc_enabled(panel)
    if not on:
        QMessageBox.warning(panel, NAME, why)
        return None
    section.hooks_flush()
    record = book.data or {}
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        counts = mvc_counts(section.path, section.band_no,
                            changes_path_of(record, section.path),
                            reviewed_path_of(record, section.path))
    except Exception as err:
        counts = None
        failed = err
    finally:
        QApplication.restoreOverrideCursor()
    if counts is None:
        QMessageBox.critical(panel, NAME, "The corrected map cannot be "
                             "read:\n\n%s" % failed)
        return None
    source = str(record.get("source") or "").split("|")[0]
    dialog = ModelVsCorrectedSetup(panel, book, section, counts,
                                   mvc_polygon_layers(),
                                   mvc_other_corrections(book),
                                   bool(mvc_source_changed(record, source)))
    if not run_dialog(dialog):
        return None
    asked = dialog.result()
    people = asked.get("people")
    if people and people.get("kind") == "correction":
        if not mvc_ask(panel, MVC_BLIND_TEXT % (
                "%s's correction" % people.get("operator"))):
            log("model vs corrected not run: the other correction was not "
                "to be seen")
            return None
    elif people and people.get("kind") == "agreement_report":
        try:
            people = mvc_read_people(people["path"])
        except IOError as err:
            QMessageBox.warning(panel, NAME, str(err))
            return None
    recipe = mvc_recipe(book, section, asked)
    target = asked.get("folder") or None
    if target and os.path.normcase(os.path.normpath(target)) == \
            os.path.normcase(os.path.normpath(mvc_folder(book,
                                                         asked["scope"]))):
        target = None          # the folder offered: reports/ chooses the name
    result = mvc_run(panel, recipe, record, book.folder, people, target)
    if result is None:
        return None
    mvc_register(book, result)
    if asked.get("load") and result.get("map"):
        mvc_layers(panel, book, result)
    try:
        section.show_tally()
    except Exception as err:
        log("the tally could not say the new report: %s" % err)
    run_dialog(mvc_window(panel, result))
    return result


def mvc_run(panel, recipe, record, folder, people, target):
    """The run, in a progress window with Cancel. The result, or None."""
    progress = QProgressDialog("Comparing the model with the corrected "
                               "map…", "Cancel", 0, 100, panel)
    progress.setWindowTitle(titled("Model vs corrected"))
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    def tick(done, total):
        progress.setValue(int(100 * done / max(1, total)))
        QApplication.processEvents()
        return not progress.wasCanceled()

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    said = None
    try:
        return mvc_report(recipe, record, folder, people, target, tick)
    except MvcCancelled:
        said = (QMessageBox.information, "Stopped. Nothing was written.")
        log("model vs corrected stopped from its progress window: nothing "
            "written")
        return None
    except Exception as err:
        said = (QMessageBox.critical, "Nothing was written:\n\n%s" % err)
        log("model vs corrected failed: %s" % err)
        return None
    finally:
        QApplication.restoreOverrideCursor()
        progress.close()
        progress.deleteLater()
        if said is not None:
            said[0](panel, NAME, said[1])


def mvc_register(book, result):
    """The report, remembered by the correction's manifest (data["reports"],
    the newest of which the quiet line under the tally says)."""
    try:
        rel = os.path.relpath(result["folder"], book.folder)
    except ValueError:
        rel = result["folder"]          # another drive: kept whole
    summary = result.get("summary_json") or {}
    entry = report_entry(MVC_KIND, uuid.uuid4().hex[:12], result["scope"],
                         result.get("created_utc") or report_utc(), rel,
                         summary.get("headline") or {})
    report_register(book.data, entry)
    try:
        book.save()
    except Exception as err:
        log("the report is written, but the manifest could not be told: %s"
            % err, loud=True)
    return entry


def mvc_layers(panel, book, result):
    """The map of pairs in QGIS, in the group "model vs corrected <scope>"
    under the correction's, styled by the .qml beside it."""
    path = result["map"]["path"]
    name = "%s: model vs corrected (%s)" % (book.data.get("name", ""),
                                            MVC_SCOPE_WORDS[result["scope"]])
    layer = QgsRasterLayer(path, name)
    if not layer.isValid():
        log("the map of pairs could not be loaded: %s" % path)
        return None
    return add_report_layer(layer, book, MVC_KIND, result["scope"], "pairs",
                            None, True)


#  The report window
# =====================================================================
def mvc_window(panel, result):
    """The report window of one run: ReportWindow, filled."""
    s = result["summarized"]
    o = s["metrics"]["overall"]
    counts = result["counts"]
    names = s["names"]
    colours = {int(k): v for k, v in
               (result["recipe"].get("colours") or {}).items()}
    share = s["n"] / float(counts["map_px"]) if counts["map_px"] else None
    scope = "%s px, %s m²%s" % (_mvc_px(s["n"]),
                                report_number(s["scope_m2"], "f2"),
                                ", %.1f %% of the map" % (100 * share)
                                if share is not None else "")
    headline = [("Model agrees on", mvc_percent(o["po"])),
                ("Disagreement", mvc_percent(o["disagreement"])),
                ("  quantity + allocation", "%s + %s"
                 % (mvc_percent(o["quantity"]),
                    mvc_percent(o["allocation"])))]
    boot = s.get("bootstrap") or {}
    ci = (boot.get("ci") or {}).get("po")
    if ci and ci[0] is not None:
        headline.append(("  over polygons", "CI %s – %s"
                         % (mvc_percent(ci[0]), mvc_percent(ci[1]))))
    people = s.get("people")
    if people and people.get("overall"):
        po = people["overall"]
        headline.append(("People agree on", mvc_percent(po.get("oa"))))
        if po.get("kappa") is not None:
            headline.append(("  kappa*", "%.3f" % po["kappa"]))
    changed = result["counts"]["changed_px"]
    headline.append(("Changed, net", "%s px, %s m²"
                     % (_mvc_px(changed),
                        report_number(s["changed_m2"], "f2"))))
    by_code = {r["code"]: r for r in s.get("side_by_side") or []}
    rows, swatches = [], []
    for c in s["metrics"]["per_class"]:
        if not (c["n_A"] or c["n_B"]):
            continue
        row = [cm_name(c["code"], names, None), c["iou"], c["rate_B"],
               c["rate_A"], c["f1"]]
        if people:
            p = by_code.get(c["code"])
            row.append(p["people_iou"] if p else None)
        rows.append(row)
        swatches.append(colours.get(c["code"], ""))
    columns = ["class", "IoU", "PA", "UA", "F1"] + (["people IoU"]
                                                    if people else [])
    tables = [{"title": "Per class", "columns": columns, "rows": rows,
               "colours": swatches}]
    top = s.get("transitions") or []
    if top:
        tables.append({"title": "Changed most", "columns": [
            "from → to", "m²", "px"], "formats": [
            None, "f2", "int"], "rows": [
            ["%s → %s" % (r["a_name"], r["b_name"]),
             round(r["area_m2"], 2), r["pixels"]] for r in top[:5]],
            "colours": [colours.get(r["b"], "") for r in top[:5]]})
    notes = [MVC_NOTES[result["scope"]][0].upper()
             + MVC_NOTES[result["scope"]][1:] + "."]
    since = (result.get("summary_json") or {}).get("reviewed") or {}
    if result["scope"] == "swept":
        if not since.get("recorded"):
            notes.append("The ground swept is not recorded for this "
                         "correction: the swept ground is the changed "
                         "pixels alone.")
        elif since.get("reviewed_since"):
            notes.append("The first %d strokes left no footprint: only the "
                         "pixels they changed count."
                         % since["reviewed_since"])
    if people:
        notes.append("* " + MVC_KAPPA_NOTE[0].upper() + MVC_KAPPA_NOTE[1:]
                     + ".")
        notes.append("People: %s." % mvc_people_word(people))
        if people.get("unmatched"):
            notes.append("Not matched by name: %s."
                         % ", ".join(people["unmatched"]))
    else:
        notes.append("No kappa for the model (Pontius and Millones 2011; "
                     "Foody 2020).")
    if counts.get("marked_but_unchanged"):
        notes.append("%s px were changed and changed back: they count as "
                     "agreeing." % _mvc_px(counts["marked_but_unchanged"]))
    if boot.get("reason"):
        notes.append("No interval: %s." % boot["reason"])
    window = ReportWindow(panel, "Model vs corrected: %s"
                          % MVC_SCOPE_WORDS[result["scope"]], scope,
                          headline, tables, notes, result["folder"])
    try:
        view = window.views[0]
        for i in range(view.columnCount()):
            item = view.horizontalHeaderItem(i)
            if item is not None and item.text() in ("PA", "UA"):
                item.setToolTip(MVC_PA_TIP)
    except Exception:
        pass
    return window
