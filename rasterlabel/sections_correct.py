"""rasterlabel.sections_correct

Correct: mending a map an algorithm produced.
"""
import csv
import numpy as np
import os

from datetime import datetime
from html import escape
from osgeo import gdal
from qgis.PyQt.QtCore import QEventLoop, QPointF, QRectF, QSize, Qt
from qgis.PyQt.QtGui import (QColor, QFont, QFontMetrics, QIcon, QPainter,
                             QPen, QPixmap)
from qgis.PyQt.QtWidgets import (QApplication, QButtonGroup,
                                 QDockWidget, QDoubleSpinBox, QGridLayout,
                                 QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                                 QLineEdit, QMessageBox, QPushButton,
                                 QSizePolicy, QSlider, QSpinBox, QToolButton,
                                 QVBoxLayout, QWidget)
from qgis.core import (QgsCoordinateReferenceSystem,
                       QgsPalettedRasterRenderer, QgsProject, QgsRasterLayer)
from qgis.gui import QgsMapCanvas

from .constants import (BRUSH_RADIUS_PX, FIELD_W,
                        FLAG_BAND_NAME, LABEL_W, LEVEL_INFO, LEVEL_WARNING,
                        MAX_WINDOW_PX, NAME, OPACITY_PERCENT, REPORTS_FOLDER,
                        SETTINGS_ROOT, UNDO_DEPTH)
from .compat import iface, read_setting, run_dialog, write_setting
from .naming import csv_text, ctrl_name, long_path, now, tidy
from .project import canvas, crs_from_text, crs_label
from .errors import LOG_NAME, log, log_to, shielded
from .layout import Deck, SliderRow
from .widgets import WrapTick
from .theme import (banner_height, bold_metrics, chip_height, fit_field,
                    follows_width, heading, ink_on, palette_colours, plain,
                    primary, spread, text_width)
from .geometry import (Geometry, fit_spin, ground_rows, snap, spin_suffix,
                       window_transform)
from .campaign import release_file
from .layers import add_layer, drop_stale, find_mine, group_node
from .rasters import (BandPlane, build_changes, burn, class_counts,
                      codes_present, is_rotated, name_classes, open_raster,
                      pixel_grid, rotated_refusal, thematic_classes,
                      thematic_colour, write_window)
from .correction import (CorrectionCampaign, beside_the_copy,
                         bring_up_to_date, changes_path_of, dress_copy,
                         forget_correction, has_flag_band,
                         set_aside_leftovers, undone_of)
from .tools import BrushTool
from .dialogs import ConfirmClasses
from .ui_uncertainty import UncertaintyCard
from .sections_annotate import AnnotationSection, legend_columns

# The banner reads "crops ➜ forest": what the brush changes, then what it
# becomes. "any class" is the FROM that changes everything but nodata.
ARROW = "➜"
ANY_CLASS = "any class"
ANY_COLOUR = "#5a5a5a"
# The TO chip in hand carries a tick before its name, this wide.
TICK_PX = 12


def ink_of(colour):
    """The colour that reads on a chip of this colour: near black on a light
    one, white on a dark one, whichever reads further from the fill. The same
    rule as the chips' own lettering, so the ring, the tick and the name are
    always the one ink."""
    return ink_on(colour)


def tick_icon(ink, size=TICK_PX):
    """A tick drawn in the ink of the chip, not a character of the font: a
    font without one shows an empty box, and a box says nothing."""
    ratio = 2
    pix = QPixmap(size * ratio, size * ratio)
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(ink))
    pen.setWidthF(2.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPolyline(QPointF(size * 0.14, size * 0.55),
                   QPointF(size * 0.40, size * 0.80),
                   QPointF(size * 0.88, size * 0.22))
    p.end()
    return QIcon(pix)


class ToChip(QPushButton):
    """A chip that can draw a dark rim round its own edge, over the outer
    half of its stylesheet border. A white ring alone round a dark chip
    meets a pale panel with nothing between them, and reads as a chip a
    little smaller than its neighbours rather than as the one in hand. With
    the rim it is a white ring inside a dark one, which stands out from the
    panel and from the chip alike."""
    rim = None

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.rim:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(self.rim))
        pen.setWidthF(2.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)
        p.end()


class CorrectionSection(QGroupBox):
    """Repairs a class map that an algorithm produced.

    It works on a copy and nothing else. The map that came out of the model
    stays on disk exactly as it was, so the two can always be compared. The
    copy is a thematic map like the original, band for band, and opens like
    it; which pixels a person moved is kept beside it, in a raster of its own
    (correction.py).

    No tiles here. A correction follows the mistakes wherever they are, and a
    grid of squares would only get in the way.

    Its classes are the map's own, not the campaign legend. The legend is what
    people draw with in Annotate and Objects; the map being corrected came out
    of a model with a numbering of its own, and a brush holding the legend's
    codes would write numbers into it that it never had. So the chips are
    read from the map when the correction is made, confirmed by the user,
    kept in its manifest, and nothing done to the legend reaches them.

    And it needs no annotation campaign. Its book is a correction campaign of
    its own (correction.py), whose data is the record handed in here. A record
    handed in with no book is one still kept inside an annotation campaign,
    which is how the suites built before the change still open it."""

    def __init__(self, panel, record, layer=None, book=None):
        super().__init__("")
        self.panel = panel
        self.book = book or getattr(panel, "correction", None) or panel.campaign
        self.record = record
        self.history = []
        self.brush = None
        self.class_code = None        # TO: what the stroke writes
        self.from_code = None         # FROM: what it changes, None for any
        self._buttons = []
        self._from_buttons = []
        self.operations = record.get("operations", 0)
        self.changed_m2 = record.get("changed_m2", 0.0)
        self.swept_m2 = record.get("swept_m2", 0.0)
        self.pairs = dict(record.get("pairs", {}))
        # What was undone, in the same terms as the three above, which count
        # every stroke written, as operations.csv does: the net is the
        # difference (net_operations, net_m2, net_pairs).
        self.undone = undone_of(record)
        self.on_ground_px = None  # pixels the record marks, once each
        self.on_ground_m2 = None
        self.operator_choice = ""     # who corrects, when somebody said
        self.saving = False       # listening for the project being saved
        self.following_crs = False
        self.hidden = []          # the layers put aside to see the ground
        self.mirror = None        # the canvas showing the map as it arrived
        self.mirror_dock = None
        self.before = None
        self.syncing = False
        self.closed = False       # close_dataset has dressed the copy

        self.source = record["source"]
        self.path = getattr(self.book, "working_path", "") or record["files"][0]
        if self.own_book():
            # what was typed in the box of Correct and kept, else the name
            # typed in the window that has just made this correction
            self.operator_choice = (
                read_setting(self.operator_key(), "")
                or getattr(self.book, "operator_said", "") or "").strip().upper()
            self.say_who_strikes()

        # A copy written by RasterLabel 1.0 carries one band more than the map
        # it corrects, "corrected", and opens in QGIS as a picture of its
        # first three bands. It is brought to the shape of the original here,
        # before it is opened for writing, the band moved out to the record
        # beside it. Every way a correction opens comes through here, so no
        # copy is corrected in the old shape.
        self.bring_up_to_date(record)
        self.band_no = record["band"]
        self.changes_path = changes_path_of(record, self.path)

        # Opened for writing here only to know at once that it can be; then
        # closed. No handle is held between strokes: each stroke opens the
        # copy, writes its window and closes it again (write_stroke), so the
        # file on disk is whole for QGIS and for anybody else between any two
        # strokes. The pixels are not read into memory either: self.values is
        # the band in its file (BandPlane), read a window or a strip at a
        # time, so a map of hundreds of millions of pixels opens in the
        # memory a small one does.
        ds = open_raster(self.path, gdal.GA_Update)
        if ds is None:
            raise IOError("cannot open the working copy:\n%s" % self.path)
        band = None
        try:
            # The grid QGIS draws the copy on, which for a picture with no
            # georeference is not the one GDAL answers (pixel_grid).
            self.gt = pixel_grid(ds)
            if is_rotated(self.gt):
                # Every way a correction opens comes through here: one made
                # before Correct refused rotated maps is refused as well,
                # rather than corrected on the wrong pixels.
                raise IOError(rotated_refusal(self.path))
            self.wkt = ds.GetProjection()
            self.nx, self.ny = ds.RasterXSize, ds.RasterYSize
            band = ds.GetRasterBand(self.band_no)
            self.nodata = band.GetNoDataValue()
        finally:
            band = None
            ds = None
        self.values = BandPlane(self.path, self.band_no)
        self.marks = None         # the record of changed pixels, None if none
        self.open_changes()

        crs = QgsCoordinateReferenceSystem()
        crs.createFromWkt(self.wkt)
        # The grid of the book: for a correction campaign that is the map's
        # own, read from it when the campaign was made. The grid of the
        # annotation campaign would do for a map whose pixel is that of the
        # campaign's reference raster and no other: every area would be wrong
        # by the ratio.
        self.geometry = Geometry(self.book, crs if crs.isValid() else None)
        self.pixel_area = abs(self.gt[1] * self.gt[5])
        self.pixel_area_m2 = self.geometry.pixel_m[0] * self.geometry.pixel_m[1]
        # The pixel is not the same ground in every row of a map in degrees
        # or in Web Mercator (ground_rows); None where one value serves.
        self.row_m2 = ground_rows(getattr(self.geometry, "measure", None),
                                  self.gt, self.nx, self.ny,
                                  self.pixel_area_m2)
        self.recount_ground()

        self.load_classes(layer)
        # What the measuring modules keep of the strokes, one hook each
        # (measure.CORRECT_HOOKS, through the panel): none until a module
        # registers one, and then nothing here changes but that they are
        # told. Built before the module, so a hook can add to it.
        hooks = getattr(panel, "correct_hooks", None)
        try:
            self.stroke_hooks = list(hooks(self)) if callable(hooks) else []
        except Exception as err:
            log("the hooks of Correct could not be set up: %s" % err)
            self.stroke_hooks = []
        # The .qml and the colour table, from the classes as they are now,
        # before the layer is made: it opens with them.
        self.dress(say=True)
        self.build()
        self.ensure_layer()
        self.report_codes()

    def bring_up_to_date(self, record):
        """correction.bring_up_to_date, with the user told. The rewrite reads
        and writes the whole copy, which on a map of gigabytes takes a minute
        or more on the thread that draws QGIS: without an hourglass and a line
        on the message bar, a QGIS that stops answering for that long looks
        dead, and is killed. And a layer of the old copy the user had in the
        project has to leave it so the file can be replaced, which they are
        told too, instead of finding it gone."""
        if not has_flag_band(self.path):
            # Still called: a rewrite stopped half way has an .aux.xml to
            # settle even when the copy has not the band.
            bring_up_to_date(self.path, record.get("band", 1), record,
                             self.book)
            return
        name = os.path.basename(self.path)
        iface.messageBar().pushMessage(
            NAME, "converting %s to the bands of the map it corrects, once: "
                  "on a large map this takes a minute or two" % name,
            level=LEVEL_INFO, duration=8)
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents(
                QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        except Exception:
            pass
        try:
            done = bring_up_to_date(self.path, record.get("band", 1), record,
                                    self.book)
        except Exception as err:
            raise IOError(
                "The working copy still has the '%s' band an earlier build "
                "gave it, and it could not be moved to the file beside it:"
                "\n\n%s\n\nNothing was changed. If another program has the "
                "file open, close it and open the correction again."
                % (FLAG_BAND_NAME, err))
        finally:
            try:
                QApplication.restoreOverrideCursor()
            except Exception:
                pass
        if not done:
            return
        words = ("%s converted: its '%s' band, %d pixel%s a person changed, "
                 "is now in %s, and the copy has the %d bands of the map it "
                 "corrects" % (name, FLAG_BAND_NAME, done["pixels"],
                               "" if done["pixels"] == 1 else "s",
                               os.path.basename(changes_path_of(record,
                                                                self.path)),
                               done["bands"]))
        if done.get("released"):
            words += (". Your layer of the old copy was taken out of the "
                      "project so the file could be converted; the corrected "
                      "map is back on the map in its classes")
        iface.messageBar().pushMessage(NAME, words, level=LEVEL_INFO,
                                       duration=12)

    def open_changes(self):
        """The record of which pixels a person changed, read into self.marks
        once it is known it can be written; then closed, like the copy, and
        written a stroke at a time (write_stroke).

        It sits beside the copy, <copy>_changes.tif. One that is not there,
        lost or never made, is started empty and said; one that cannot be
        made or is not on the grid of the copy leaves the strokes working
        and nothing remembered of which pixels they changed, which is said
        too."""
        path = self.changes_path
        name = os.path.basename(path)
        if not os.path.exists(long_path(path)):
            try:
                build_changes(self.path, path)
            except Exception as err:
                log("cannot start %s: %s. The strokes still work; which pixels "
                    "a person changed is not remembered." % (name, err),
                    loud=True)
                return
            if self.operations:
                log("%s was not beside the working copy, so a new one starts "
                    "empty: the %d operations made before are in the copy and "
                    "in operations.csv, but which pixels they changed is not "
                    "known" % (name, self.operations), loud=True)
            else:
                log("which pixels a person changes is recorded in %s" % name)
        try:
            ds = gdal.Open(path, gdal.GA_Update)
        except Exception:
            ds = None               # a GDAL that raises instead of answering
        if ds is None:
            log("cannot open %s for writing. The strokes still work; which "
                "pixels a person changed is not remembered." % name, loud=True)
            return
        if (ds.RasterXSize, ds.RasterYSize) != (self.nx, self.ny):
            log("%s is %d x %d pixels and the copy %d x %d: it is not the "
                "record of this copy and is not used. The strokes still work."
                % (name, ds.RasterXSize, ds.RasterYSize, self.nx, self.ny),
                loud=True)
            ds = None
            return
        if pixel_grid(ds) != tuple(self.gt):
            # RasterLabel 1.0 wrote GDAL's default grid into the record of a
            # picture that has none, and QGIS drew the record beside the
            # copy instead of on it. Put on the grid of the copy.
            try:
                ds.SetGeoTransform(self.gt)
                log("%s was not on the grid of the copy and was put on it"
                    % name)
            except Exception as err:
                log("%s is not on the grid of the copy and cannot be put on "
                    "it: %s" % (name, err))
        ds = None
        try:
            self.marks = BandPlane(path, 1)
        except Exception as err:
            log("cannot read %s: %s. The strokes still work; which pixels a "
                "person changed is not remembered." % (name, err), loud=True)
            return
        if self.record.get("changes") != name:
            self.record["changes"] = name
            try:
                self.book.save()
            except Exception as err:
                log("cannot update the manifest: %s" % err)

    def dress(self, say=False):
        """The classes written beside and into the corrected map: its .qml
        and the colour table of its class band (correction.dress_copy),
        through a handle of its own: Correct holds none between strokes, so
        nothing else is writing into the file while it does."""
        dress_copy(self.path, self.band_no, self.classes(), self.source,
                   say=say)

    def classes_changed(self):
        """The classes changed: the layer, the .qml and the colour table
        follow at once."""
        layer = find_mine(self.book.data["id"], self.layer_role())
        if layer is not None:
            self.style(layer)
        self.dress()

    # ----------------------------------------------------------- the classes
    def classes(self):
        """The classes of this correction, in the order the chips show them."""
        return self.record.setdefault("classes", [])

    def class_of(self, code):
        for c in self.classes():
            if c["code"] == code:
                return c
        return None

    @property
    def class_name(self):
        """The name of the class in hand. The code is what is held, because
        two values of a map can carry the same label and a code cannot."""
        c = self.class_of(self.class_code)
        return c["name"] if c is not None else None

    def current_colour(self):
        c = self.class_of(self.class_code)
        return c["colour"] if c is not None else "#888888"

    def current_code(self):
        return self.class_code

    def load_classes(self, layer=None):
        """The classes kept in the record, or read from the map once.

        A correction made by RasterLabel 1.0 has none in its record: it was
        painted with the legend of the campaign. They are read from the map
        the first time it is opened and written into the manifest, so that
        from then on names and colours are the same at every opening, and a
        renamed style or a new legend does not reshuffle them."""
        kept = self.record.get("classes")
        if isinstance(kept, list) and kept:
            clean = []
            for c in kept:
                try:
                    code = int(c["code"])
                    colour = QColor(str(c.get("colour") or ""))
                except (KeyError, TypeError, ValueError, AttributeError):
                    continue
                clean.append({"code": code, "name": str(c.get("name") or ""),
                              "colour": colour.name() if colour.isValid()
                              else thematic_colour(len(clean))})
            self.record["classes"] = name_classes(clean)
            return
        if layer is None:
            layer = self.source_layer()
        notes = []
        self.record["classes"] = [
            {"code": c["code"], "name": c["name"], "colour": c["colour"]}
            for c in thematic_classes(self.values, self.nodata, layer,
                                      self.band_no, self.source, notes)]
        for line in notes:
            log(line)
        log("correction '%s' has %d classes of its own, from the map it "
            "corrects; the campaign legend is not used here. Written into the "
            "manifest." % (self.record["name"], len(self.record["classes"])))
        try:
            self.book.save()
        except Exception as err:
            log("cannot update the manifest: %s" % err)

    def source_layer(self):
        """The map the correction started from, if it is loaded, for its
        style. None when it is not: the values alone still give the classes."""
        target = os.path.normcase(os.path.abspath(self.source))
        try:
            layers = QgsProject.instance().mapLayers().values()
        except Exception:
            return None
        for layer in layers:
            try:
                here = os.path.normcase(os.path.abspath(
                    layer.source().split("|")[0]))
            except Exception:
                continue
            if here == target and hasattr(layer, "renderer"):
                return layer
        return None

    def adopt(self, codes, why):
        """Codes met in the map that the record does not name are given a
        class of their own, said once in the log, and the chips are rebuilt.
        A value nobody listed is a fact about the map, not an error."""
        fresh = [int(v) for v in codes
                 if self.class_of(int(v)) is None
                 and not (self.nodata is not None and v == self.nodata)]
        if not fresh:
            return []
        for v in sorted(set(fresh)):
            self.classes().append({"code": v, "name": "",
                                   "colour": thematic_colour(len(self.classes()))})
        name_classes(self.classes())
        log("correction '%s': %s %s, not among its classes, given a class "
            "each" % (self.record["name"], why,
                      ", ".join(str(v) for v in sorted(set(fresh)))))
        try:
            self.book.save()
        except Exception as err:
            log("cannot update the manifest: %s" % err)
        if getattr(self, "class_grid", None) is not None:
            self.rebuild_class_buttons()
            self.classes_changed()
        return sorted(set(fresh))

    def code_range(self):
        """The codes the class band can hold, from its type."""
        try:
            info = np.iinfo(self.values.dtype)
            return int(max(info.min, -2 ** 31)), int(min(info.max, 2 ** 31 - 1))
        except Exception:
            return -2 ** 31, 2 ** 31 - 1

    def add_class(self):
        """A class the map does not hold yet: the model may have missed one
        entirely, and the correction is where it goes in. Asked for by number,
        because the number is what is written into the map."""
        low, high = self.code_range()
        start = max([c["code"] for c in self.classes()] or [low - 1]) + 1
        start = min(max(start, low), high)
        code, ok = QInputDialog.getInt(
            self, NAME, "Code of the new class, as written into the map:",
            start, low, high, 1)
        if not ok:
            return
        if self.nodata is not None and code == self.nodata:
            QMessageBox.warning(self, NAME,
                                "%d is the nodata value of this map: painting it "
                                "would erase the pixels, not correct them." % code)
            return
        if self.class_of(code) is not None:
            self.choose_class(code)
            return
        name, ok = QInputDialog.getText(
            self, NAME, "Name of class %d (optional):" % code)
        if not ok:
            return
        self.classes().append({"code": code, "name": (name or "").strip(),
                               "colour": thematic_colour(len(self.classes()))})
        name_classes(self.classes())
        try:
            self.book.save()
        except Exception as err:
            log("cannot update the manifest: %s" % err)
        log("correction '%s': class %d added, '%s'"
            % (self.record["name"], code, self.class_of(code)["name"]))
        self.classes_changed()
        self.choose_class(code)

    # ----------------------------------------------------------- the panel
    def build(self):
        follows_width(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(7)

        self.deck = Deck()
        self.deck.after = self.reflow

        # Its name is in the line of CORRECTION, right above: here only what
        # kind of correction it is and what it is a copy of.
        head = QLabel("%s, on a copy of %s"
                      % ("A correction campaign" if self.own_book()
                         else "A correction kept in the annotation campaign",
                         escape(os.path.basename(self.source))))
        head.setWordWrap(True)
        head.setObjectName("quiet")
        head.setToolTip(self.describe())
        self.head = head
        outer.addWidget(head)

        # A correction is always "this class becomes that one", so the banner
        # says both halves, each in its own colour, with the arrow between
        # them. The class written alone would leave the class being replaced
        # as a list further down that nobody connects with it.
        self.banner = QWidget()
        row = QHBoxLayout(self.banner)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        f = self.banner.font()
        f.setPointSize(max(f.pointSize() + 1, 11))
        f.setBold(True)
        self.from_pill = QLabel("")
        self.into_pill = QLabel("")
        self.arrow = QLabel(ARROW)
        for pill in (self.from_pill, self.arrow, self.into_pill):
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pill.setFont(f)
        for pill in (self.from_pill, self.into_pill):
            # Ignored, so a long name is cut to the room there is instead of
            # making the panel wider; the text is elided to fit in banner().
            pill.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            pill.setMinimumWidth(1)
            row.addWidget(pill, 1)
        row.insertWidget(1, self.arrow)
        # two lines in each half, a small word over the class, as tall as
        # the font QGIS was given needs
        self.banner.setFixedHeight(banner_height(self.from_pill, lines=2))
        self.arrow.setFixedWidth(text_width(self.arrow.fontMetrics(), ARROW) + 8)
        self.from_pill.setToolTip(
            "FROM: the class the brush changes.\n"
            "Pick it in the FROM chips, or %s+click the map." % ctrl_name())
        self.into_pill.setToolTip(
            "TO: the class it becomes.\n"
            "Pick it in the TO chips, or Shift+click the map.")

        self.same_note = QLabel(
            "FROM and TO are the same class: there is nothing to change. "
            "Pick another one.")
        self.same_note.setWordWrap(True)
        self.same_note.setObjectName("quiet")
        self.same_note.setVisible(False)

        # The chips live in nested layouts rather than inside a widget of
        # their own: a widget keeps the size it was given when the classes
        # change, and the last row ends up drawn over whatever comes next.
        self.from_grid = QGridLayout()
        self.from_grid.setContentsMargins(0, 0, 0, 0)
        self.from_grid.setSpacing(5)
        self.class_grid = QGridLayout()
        self.class_grid.setContentsMargins(0, 0, 0, 0)
        self.class_grid.setSpacing(5)

        from_head = QLabel("<b>FROM</b> — what the brush changes")
        from_head.setWordWrap(True)
        into_head = QLabel("<b>TO</b> — what it becomes")
        into_head.setWordWrap(True)
        hint = QLabel("On the map: %s+click picks FROM, Shift+click picks TO."
                      % ctrl_name())
        hint.setWordWrap(True)
        hint.setObjectName("quiet")

        legend = QVBoxLayout()
        legend.setSpacing(5)
        legend.addWidget(self.banner)
        legend.addWidget(self.same_note)
        legend.addSpacing(2)
        legend.addWidget(from_head)
        legend.addLayout(self.from_grid)
        legend.addSpacing(2)
        legend.addWidget(into_head)
        legend.addLayout(self.class_grid)
        legend.addWidget(hint)
        legend.addSpacing(6)
        self.deck.add(legend, 3)

        # how much of the image shows through the copy, and what else is on
        # the map: the things that are set while looking at it
        seeing = QVBoxLayout()
        seeing.setSpacing(6)

        # The copy sits on the image and you look through it. Anything but a
        # readable amount of transparency and you are correcting a class map
        # against nothing, which is how a wrong boundary stays wrong.
        label = QLabel("see through")
        label.setFixedWidth(max(LABEL_W, text_width(label.fontMetrics(),
                                                    "see through") + 6))
        # The slider is worth having from the width of its own word; short
        # of that room it goes onto a row of its own, under the word and the
        # box, instead of shrinking to a stub.
        row = SliderRow(lambda: text_width(label.fontMetrics(),
                                           "see through"))
        self.through = QSlider(Qt.Orientation.Horizontal)
        self.through.setRange(0, 100)
        self.through.setValue(OPACITY_PERCENT)
        self.through.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.through.setToolTip(
            "How much of the image below shows through the mask you are\n"
            "correcting. The mask itself is never changed by this.")
        self.through_box = QSpinBox()
        self.through_box.setRange(0, 100)
        self.through_box.setSuffix(" %")
        self.through_box.setValue(OPACITY_PERCENT)
        fit_field(self.through_box, 64)
        self.through_box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        row.add(label, self.through, self.through_box)
        self.through.valueChanged.connect(self.through_box.setValue)
        self.through_box.valueChanged.connect(self.through.setValue)
        self.through.valueChanged.connect(self.set_opacity)
        seeing.addLayout(row)

        self.tuck = WrapTick("hide the source map")
        self.tuck.setChecked(True)
        self.tuck.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.tuck.setToolTip(
            "The map the correction started from is opaque and sits over the\n"
            "image. While this is on it is unticked in the layers panel so the\n"
            "image shows through the copy. Its file is never touched either way.")
        self.tuck.toggled.connect(self.tuck_changed)
        seeing.addWidget(self.tuck)

        self.compare = WrapTick("show the original beside it")
        self.compare.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.compare.setToolTip(
            "Opens a second view with the map as the algorithm produced it,\n"
            "at the same transparency and over the same image, following this\n"
            "one wherever you move. Nothing can be drawn in there: it is the\n"
            "thing you are comparing against.")
        self.compare.toggled.connect(self.show_beside)
        seeing.addWidget(self.compare)
        self.deck.add(seeing, 3)

        self.b_brush = self._tool(
            "Polygon", "Draw a polygon.\nClick by click or freehand, the outline "
                       "closes on itself.\n%s+click: FROM is the class under "
                       "the cursor.\nShift+click: TO is the class under the "
                       "cursor." % ctrl_name())
        self.b_brush.clicked.connect(
            shielded(lambda: self.use_brush(False), "Polygon"))
        self.b_round = self._tool(
            "Round", "Round brush.\nFor small repairs. Its radius is under "
                     "Settings.\n%s+click and Shift+click pick FROM and TO, "
                     "as with the polygon." % ctrl_name())
        self.b_round.clicked.connect(
            shielded(lambda: self.use_brush(True), "Round"))
        self.round_brush = self.b_round
        self.tools = QButtonGroup(self)
        self.tools.setExclusive(True)
        for b in (self.b_brush, self.b_round):
            self.tools.addButton(b)

        # Classes is not here: it is in CORRECTION, beside the buttons that
        # open and close the correction, and it opens the same window.
        # The words Annotate uses: the shapes, what mends, and Save under
        # them. Set aside last, where the hand slows down.
        tools = QVBoxLayout()
        tools.setSpacing(8)
        tools.addWidget(heading("SHAPE", plain(spread(
            [self.b_brush, self.b_round], gap=4))))
        tools.addWidget(heading("EDIT", plain(spread([
            self._act("Undo", "Undo the last change.\noperations.csv keeps "
                      "its row, and the count is net of it.", self.undo),
            self._act("Set aside",
                      "Close this correction and move its folder aside.\n"
                      "Nothing is erased; the map it started from is "
                      "untouched.", self.delete, danger=True)], gap=4))))
        tools.addSpacing(4)
        tools.addLayout(spread([primary(self._act(
            "Save", "Flush the copy to disk.", self.save))]))
        self.deck.add(tools, 2)

        # Room after Save for what a measuring module shows while Correct
        # is in hand: empty, and taking no room, until one puts a card in it.
        self.measure_slot = QVBoxLayout()
        self.measure_slot.setContentsMargins(0, 0, 0, 0)
        self.measure_slot.setSpacing(6)
        self.deck.add(self.measure_slot, 1)
        UncertaintyCard.place_in(self)

        self.settings_box = QVBoxLayout()
        self.settings_box.setSpacing(5)
        self.fold = QToolButton()
        self.fold.setText(" Settings")
        self.fold.setCheckable(True)
        self.fold.setArrowType(Qt.ArrowType.RightArrow)
        self.fold.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.fold.setAutoRaise(True)
        self.fold.setObjectName("fold")
        self.fold.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.fold.toggled.connect(self.show_settings)
        self.settings_box.addWidget(self.fold, 0, Qt.AlignmentFlag.AlignLeft)

        self.settings = follows_width(QWidget())
        inner = QVBoxLayout(self.settings)
        inner.setContentsMargins(8, 0, 0, 2)
        inner.setSpacing(5)
        self.radius = QDoubleSpinBox()
        self.radius.setFixedWidth(FIELD_W)
        # in whole pixels of the map, as in Annotate (fit_spin)
        fit_spin(self.radius, self.geometry.pixel_m[0], 1, 500, 200.0,
                 BRUSH_RADIUS_PX, spin_suffix(self.geometry))
        self.radius.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.radius.valueChanged.connect(self.radius_changed)
        self.radius_px = QLabel("")
        self.radius_px.setObjectName("quiet")
        inner.addLayout(self._field("radius", self.radius, self.radius_px))
        self.confirm = WrapTick("ask before each change")
        self.confirm.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        inner.addWidget(self.confirm)
        # Who corrects. Only a correction with a campaign of its own has an
        # operator to speak of: one still kept inside an annotation campaign
        # is stamped with the panel's reading, as ever.
        self.who = QLineEdit(self.operator_choice)
        # room for a name of eleven capitals in the font it is shown in
        self.who.setFixedWidth(max(FIELD_W, text_width(
            self.who.fontMetrics(), "M" * 11) + 16))
        self.who.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.who.editingFinished.connect(shielded(self.operator_edited,
                                                  "Operator"))
        if self.own_book():
            inner.addLayout(self._field("operator", self.who))
            self.show_operator()
        else:
            self.who.setVisible(False)
        self.settings.setVisible(False)
        self.settings_box.addWidget(self.settings)
        self.deck.add(self.settings_box, 2)

        self.tally = QLabel("")
        self.tally.setWordWrap(True)
        self.tally.setObjectName("quiet")
        self.deck.add(self.tally, 2)

        self.deck.deal(force=True)
        outer.addWidget(self.deck)

        self.rebuild_class_buttons()
        self.radius_changed()
        self.show_tally()

    _tool = AnnotationSection.__dict__["_tool"]
    _act = AnnotationSection.__dict__["_act"]
    _field = AnnotationSection.__dict__["_field"]
    show_settings = AnnotationSection.__dict__["show_settings"]
    chip_room = AnnotationSection.__dict__["chip_room"]
    _chip_columns = AnnotationSection.__dict__["natural_columns"]

    def chip_columns(self, classes, tick=False):
        """As in Annotate, but a long list is never left in one column.

        Correct shows every class twice, under FROM and under TO, and a map
        can have forty of them. One long name would put each list in a single
        column, two metres of chips in a narrow panel. From four classes
        there are at least two columns when each can still be 70 pixels wide,
        as in Annotate, so one class list is laid out alike in both:
        a name that does not fit is cut, and its chip's tooltip and the
        banner still say it whole.

        With tick, for the TO grid, the room is counted with the tick the
        chip in hand carries before its name: without it the longest name
        fitted its chip until it was chosen, and was cut the moment it was."""
        columns = self._chip_columns(classes)
        if tick and columns > 1:
            metrics = bold_metrics(self)
            widest = max([text_width(metrics, c["name"]) for c in classes]
                         or [40])
            tick_room = TICK_PX + 4
            def cell(n):
                return (self.chip_room() - 5 * (n - 1)) // n
            while columns > 1 and cell(columns) - 12 - tick_room < widest:
                columns -= 1
        return legend_columns(columns, len(classes), self.chip_room(), gap=5)
    resizeEvent = AnnotationSection.__dict__["resizeEvent"]
    _style = AnnotationSection.__dict__["_style"]
    _settle = AnnotationSection.__dict__["settle"]

    def settle(self):
        """As in Annotate, with the FROM grid told as well as the TO one."""
        self.from_grid.invalidate()
        self._settle()

    def from_choices(self):
        """What the FROM chips offer: any class, then the classes."""
        return [{"code": None, "name": ANY_CLASS}] + list(self.classes())

    def both_columns(self):
        """The columns of FROM and of TO: the same for both, the fewer of
        the two, so a class stands in the same column in either grid. With
        three classes FROM took three and TO two, and nothing lined up."""
        both = min(self.chip_columns(self.from_choices(), tick=True),
                   self.chip_columns(self.classes() + [{"name": "+"}],
                                     tick=True))
        return (both, both)

    def reflow(self):
        """As in Annotate, on this correction's own classes: the borrowed one
        counts the columns of the campaign legend, which is not what the chips
        here are. Two grids, and either one changing its number of columns is
        reason enough to build both again. The banner is cut to the new width
        either way."""
        if getattr(self, "_reflowing", False):
            return
        if self.classes() and self.both_columns() != getattr(self, "_columns", None):
            self._reflowing = True
            try:
                self.rebuild_class_buttons()
            finally:
                self._reflowing = False
        else:
            self.fit_chip_names()
            self.show_banner()

    def fit_chip_names(self):
        """Cut each chip's name to the width its column has now.

        The chips are built again only when a grid changes its number of
        columns. Past eight classes the columns stay at two over a wide range
        of widths, and the names cut for the width the panel had when the
        chips were built would overflow both ends of their chips once the
        panel was made narrower: "ial surfaces and bui", with no sign of
        where the rest went."""
        if not getattr(self, "_columns", None):
            return
        metrics = bold_metrics(self)
        room = self.chip_room()
        for buttons, columns in ((self._from_buttons, self._columns[0]),
                                 (self._buttons, self._columns[1])):
            cell = (room - 5 * (columns - 1)) // columns
            for b in buttons:
                name = b.property("full_name")
                if name:
                    b.setText(metrics.elidedText(
                        name, Qt.TextElideMode.ElideRight, cell - 12 - self._mark_room(b)))

    def _from_style(self, colour, chosen):
        """A FROM chip is neutral with the colour of its class as a thick
        edge on the left, chosen or not, so the row reads as a choice of
        what to look for and not as a second row of paint. A filled chip
        would look like a block of paint when the class is a pale yellow, and
        unlike its neighbours whatever it is. The one chosen is marked
        another way: a thick outline in the ink of the text, bold lettering
        and a tick before its name, as TO has (the rim and the tick are
        added in rebuild_class_buttons). Any class has no colour of its
        own: dashed while it is not chosen, dark grey when it is."""
        if colour is None:
            if chosen:
                return ("QPushButton{background-color:%s; color:#ffffff;"
                        " font-weight:bold; border:2px solid #101010;"
                        " border-radius:3px; padding:0px 3px;}"
                        "QPushButton:focus{border:2px dashed #ffffff;}"
                        % ANY_COLOUR)
            return ("QPushButton{background-color:palette(base);"
                    " color:palette(text); border:2px dashed palette(mid);"
                    " border-radius:3px; padding:0px 3px;}"
                    "QPushButton:hover{border:2px solid palette(text);}"
                    "QPushButton:focus{border:2px dashed palette(highlight);}")
        if chosen:
            return ("QPushButton{background-color:palette(base);"
                    " color:palette(text); font-weight:bold;"
                    " border:3px solid palette(text);"
                    " border-left:7px solid %s;"
                    " border-radius:3px; padding:0px 2px 0px 1px;}"
                    "QPushButton:focus{border:3px dashed palette(highlight);"
                    " border-left:7px solid %s;}" % (colour, colour))
        # An outline in the class colour alone vanished twice over: a pale
        # class on a light field, a dark one on a dark field. A neutral rim
        # holds the chip, and a thick edge on the left carries the colour.
        return ("QPushButton{background-color:palette(base); color:palette(text);"
                " border:1px solid %s; border-left:6px solid %s;"
                " border-radius:3px; padding:1px 3px 1px 2px;}"
                "QPushButton:hover{border:1px solid %s; border-left:6px solid %s;}"
                "QPushButton:focus{border:2px dashed %s; border-left:6px solid %s;}"
                % (palette_colours()["dim"], colour, colour, colour,
                   palette_colours()["text"], colour))

    def _to_style(self, colour, chosen):
        """A TO chip is filled in the colour of its class, like the legend in
        Annotate, and on a page of forty filled chips the one in hand has to
        be found at a glance. Bold lettering and a thin ring are not enough:
        on a navy or a dark brown chip the white ring of two pixels reads as
        the edge of every other chip. So the one in hand is ringed thick in
        the ink of its own chip, which reads on that chip by construction,
        a dark one with a dark rim outside the white (ToChip) so that it also
        reads on the panel, and it carries a tick before its name. The
        others keep the thin, half-transparent edge they had, so the ring is
        the only heavy line in the grid. Annotate's chips are not touched:
        this is Correct's own."""
        ink = ink_of(colour)
        if not chosen:
            return self._style(colour, False)
        if ink == "#ffffff":
            # Four pixels of white, the outer two of which ToChip covers with
            # its dark rim: a white ring inside a dark one.
            return ("QPushButton{background-color:%s; color:%s;"
                    " font-weight:bold; border:4px solid %s;"
                    " border-radius:4px; padding:0px 1px;}"
                    "QPushButton:focus{border-style:dashed;}"
                    % (colour, ink, ink))
        return ("QPushButton{background-color:%s; color:%s;"
                " font-weight:bold; border:3px solid %s;"
                " border-radius:4px; padding:0px 2px;}"
                "QPushButton:focus{border-style:dashed;}"
                % (colour, ink, ink))

    @staticmethod
    def _mark_room(button):
        """The width the tick takes from the name on a chip that has it."""
        return TICK_PX + 4 if button.property("ticked") else 0

    def _chip(self, text, tip, style, chosen, cell, metrics, slot,
              tick=None, rim=None):
        b = ToChip()
        if rim is not None:
            b.rim = rim
        if tick is not None:
            if tick == "#ffffff" and rim is None:
                b.rim = "#101010"
            b.setProperty("ticked", True)
            b.setIcon(tick_icon(tick))
            b.setIconSize(QSize(TICK_PX, TICK_PX))
        b.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                     cell - 12 - self._mark_room(b)))
        b.setProperty("full_name", text)
        b.setCheckable(True)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setFixedHeight(chip_height(b))
        b.setToolTip(tip)
        b.setChecked(chosen)
        b.setStyleSheet(style)
        b.clicked.connect(shielded(slot, "Class"))
        return b

    def rebuild_class_buttons(self):
        for b in self._buttons + self._from_buttons:
            self.class_grid.removeWidget(b)
            self.from_grid.removeWidget(b)
            b.setParent(None)
            b.deleteLater()
        self._buttons = []
        self._from_buttons = []
        classes = self.classes()
        if self.class_of(self.class_code) is None:
            self.class_code = classes[0]["code"] if classes else None
        if self.from_code is not None and self.class_of(self.from_code) is None:
            self.from_code = None
        metrics = bold_metrics(self)
        room = self.chip_room()
        self._columns = self.both_columns()
        from_columns, columns = self._columns

        # FROM: any class first, then one chip per class
        cell = (room - 5 * (from_columns - 1)) // from_columns
        for i, c in enumerate(self.from_choices()):
            code = c["code"]
            chosen = code == self.from_code
            if code is None:
                tip = ("FROM any class: whatever the stroke covers becomes "
                       "the TO class.\nOnly nodata is left alone.")
            else:
                tip = ("FROM %s, code %d in the map: the stroke changes only "
                       "its pixels\nand leaves every other class alone."
                       % (c["name"], code))
            # the chosen one of a class: the ink of the text for the tick and
            # for a rim round the whole chip, the colour edge included, so a
            # pale edge or a dark one is held on any panel
            marked = chosen and c.get("colour") is not None
            ink = self.palette().text().color().name()
            b = self._chip(c["name"], tip,
                           self._from_style(c.get("colour"), chosen), chosen,
                           cell, metrics,
                           lambda _=False, k=code: self.choose_from(k),
                           tick=ink if marked else None,
                           rim=ink if marked else None)
            self.from_grid.addWidget(b, i // from_columns, i % from_columns)
            self._from_buttons.append(b)

        # TO: one chip per class, then "+"
        cell = (room - 5 * (columns - 1)) // columns
        for i, c in enumerate(classes):
            chosen = c["code"] == self.class_code
            b = self._chip(c["name"],
                           "TO %s, code %d in the map: what the stroke writes."
                           % (c["name"], c["code"]),
                           self._to_style(c["colour"], chosen), chosen, cell,
                           metrics,
                           lambda _=False, k=c["code"]: self.choose_class(k),
                           tick=ink_of(c["colour"]) if chosen else None)
            self.class_grid.addWidget(b, i // columns, i % columns)
            self._buttons.append(b)

        # A class the map does not hold yet, by its code. After the last chip,
        # as in Annotate, so the classes end where they can be made longer.
        # Only under TO: a class the map does not hold has no pixels to change.
        i = len(classes)
        plus = QPushButton("+")
        plus.setFixedHeight(chip_height(plus))
        plus.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        plus.setToolTip(
            "A class the map does not hold yet.\n\nAsked for by its code, the "
            "number written into the map,\nand a name if you want one. It "
            "belongs to this correction\nonly: the campaign legend is not "
            "touched.")
        plus.clicked.connect(shielded(self.add_class, "Add class"))
        self.class_grid.addWidget(plus, i // columns, i % columns)
        self._buttons.append(plus)
        self.show_banner(settle=False)
        # The grids are rebuilt in place and their box does not always ask for
        # the room the new number of rows needs, which clips the last chip.
        self.settle()

    def show_banner(self, settle=True):
        """FROM on the left, TO on the right, each in its class colour, and a
        line under them when the two are the same and a stroke would change
        nothing."""
        into = self.class_of(self.class_code)
        source = None if self.from_code is None else self.class_of(self.from_code)
        room = max(self.banner.width(), 140) if self.banner.width() > 60 \
            else self.chip_room()
        half = max((room - self.arrow.width() - 8) // 2 - 10, 30)
        metrics = self.from_pill.fontMetrics()
        size = self.from_pill.font().pointSize()
        small = max(size - 3, 7)
        plain = QFont(self.from_pill.font())
        plain.setPointSize(max(size - 2, 8))
        plain_metrics = QFontMetrics(plain)
        for pill, c, word, empty in ((self.from_pill, source, "FROM", ANY_CLASS),
                                     (self.into_pill, into, "TO", "no class")):
            # Two lines: which half this is, small, and the class, large. A
            # name too long for the large size is written a little smaller
            # before it is cut: in a narrow panel "Mediterranean maq…" says
            # more than "Mediterr…".
            name = empty if c is None else c["name"]
            if text_width(metrics, name) <= half:
                shown = escape(name)
            else:
                shown = "<span style='font-size:%dpt'>%s</span>" % (
                    plain.pointSize(),
                    escape(plain_metrics.elidedText(name, Qt.TextElideMode.ElideRight, half)))
            pill.setText("<span style='font-size:%dpt; font-weight:normal'>"
                         "%s</span><br>%s" % (small, word, shown))
            if c is None and pill is self.from_pill:
                pill.setStyleSheet(
                    "background-color:%s; color:#ffffff;"
                    " border:1px solid rgba(0,0,0,0.3); border-radius:4px;"
                    % ANY_COLOUR)
            elif c is None:
                pill.setStyleSheet(
                    "background-color:palette(button); color:palette(mid);"
                    " border:1px dashed palette(mid); border-radius:4px;")
            else:
                ink = ink_on(c["colour"])
                pill.setStyleSheet(
                    "background-color:%s; color:%s;"
                    " border:1px solid rgba(0,0,0,0.3); border-radius:4px;"
                    % (c["colour"], ink))
        same = into is not None and self.from_code == self.class_code
        self.arrow.setText("=" if same else ARROW)
        self.banner.setToolTip("%s %s %s" % (self.from_name(), ARROW,
                                             self.class_name or "no class"))
        if self.same_note.isHidden() == same:
            self.same_note.setVisible(same)
            if settle:
                self.settle()

    def from_name(self):
        """The FROM half in words, as the banner and the log write it."""
        c = None if self.from_code is None else self.class_of(self.from_code)
        return c["name"] if c is not None else ANY_CLASS

    def choose_class(self, code):
        """TO: the class the stroke writes."""
        self.class_code = code
        self.rebuild_class_buttons()
        if self.brush is not None:
            self.brush.refresh_colour()
        # the journal of working time, when there is one (journal.py's
        # CorrectJournalHook gives the section its note); Shift and click
        # (pick_into_at) comes through here too
        note = getattr(self, "note", None)
        if callable(note):
            note("class", class_code=code)

    def choose_from(self, code):
        """FROM: the class the stroke changes, None for any class."""
        self.from_code = code
        self.rebuild_class_buttons()

    def radius_changed(self, *args):
        px = self.geometry.pixel_m[0]
        self.radius_px.setText("%d px" % (int(round(self.radius.value() / px))
                                          if px else 0))
        if self.brush is not None:
            self.brush.refresh_colour()

    # ----------------------------------------------------------- the layer
    def ensure_layer(self):
        # A layer a saved project kept of a copied or moved correction reads
        # the old working copy, or nothing: not this one (layers.drop_stale).
        drop_stale(self.book.data["id"], self.path, (self.layer_role(),),
                   "correction")
        existing = find_mine(self.book.data["id"], self.layer_role())
        if existing is None:
            self.drop_strays()
            layer = QgsRasterLayer(self.path, self.layer_title())
            if not layer.isValid():
                log("the working copy will not load as a layer: %s" % self.path)
                return None
            existing = add_layer(layer, self.book, self.layer_role())
            self.lift(existing)
            if self.tuck.isChecked():
                self.put_source_aside()
        self.style(existing)
        self.set_opacity(self.through.value())
        return existing

    def lift(self, layer):
        """The copy goes on top, because it is what you are working on and
        what you must see."""
        try:
            group = group_node(self.book.group_name)
            node = group.findLayer(layer.id())
            if node is not None:
                clone = node.clone()
                group.insertChildNode(0, clone)
                group.removeChildNode(node)
        except Exception as err:
            log("cannot lift the copy to the top: %s" % err)

    def put_source_aside(self):
        """The mask the correction started from is opaque and sits in the way.

        It is only unticked, never touched: the file stays exactly as the
        algorithm wrote it, and the tick comes back when the module closes."""
        target = os.path.normcase(os.path.abspath(self.source))
        root = QgsProject.instance().layerTreeRoot()
        for layer in QgsProject.instance().mapLayers().values():
            try:
                here = os.path.normcase(os.path.abspath(
                    layer.source().split("|")[0]))
            except Exception:
                continue
            if here != target:
                continue
            node = root.findLayer(layer.id())
            if node is not None and node.isVisible():
                node.setItemVisibilityChecked(False)
                self.hidden.append(layer.id())
                self.listen_for_saves()
                log("'%s' was unticked in the layers panel so the image shows "
                    "through the copy. Its file was not touched. Untick 'hide "
                    "the map it started from' to put it back." % layer.name())
                iface.messageBar().pushMessage(
                    NAME, "'%s' is unticked while you correct: the copy is on "
                          "top of it. Nothing was written to it."
                    % layer.name(), level=LEVEL_INFO, duration=6)

    def tuck_changed(self, wanted):
        if wanted:
            self.put_source_aside()
        else:
            self.bring_source_back()

    def bring_source_back(self):
        root = QgsProject.instance().layerTreeRoot()
        for layer_id in self.hidden:
            node = root.findLayer(layer_id)
            if node is not None:
                node.setItemVisibilityChecked(True)
        self.hidden = []
        self.stop_listening()

    def listen_for_saves(self):
        """Told when the project is written, so that the map put aside is
        not written unticked (project_writing)."""
        if self.saving:
            return
        try:
            QgsProject.instance().writeProject.connect(self.project_writing)
            self.saving = True
        except Exception as err:
            log("cannot listen for the project being saved, so a project saved "
                "while Correct is open keeps the map it started from "
                "unticked: %s" % err)

    def stop_listening(self):
        if not self.saving:
            return
        self.saving = False
        try:
            QgsProject.instance().writeProject.disconnect(self.project_writing)
        except Exception:
            pass

    def project_writing(self, doc):
        """The project is being written, with the map the correction started
        from unticked in the layers panel to let the image show through. Saved
        like that it comes back unticked for good, long after the correction
        is closed and the reason for it forgotten. Ticked in the file, and
        left as it is on the screen: the correction goes on over it."""
        if not self.hidden:
            return
        try:
            nodes = doc.elementsByTagName("layer-tree-layer")
            for i in range(nodes.count()):
                element = nodes.at(i).toElement()
                if element.attribute("id") in self.hidden:
                    element.setAttribute("checked", "Qt::Checked")
        except Exception as err:
            log("cannot tick the map it started from in the project being "
                "saved: %s" % err)

    def set_opacity(self, percent=None):
        """Solid at 100, gone at 0. Two ways of setting it, because the API
        moved between QGIS versions."""
        layer = find_mine(self.book.data["id"], self.layer_role())
        if layer is None:
            return
        share = (self.through.value() if percent is None else percent) / 100.0
        done = False
        try:
            layer.setOpacity(share)
            done = True
        except Exception:
            pass
        if not done:
            try:
                layer.renderer().setOpacity(share)
                done = True
            except Exception as err:
                log("cannot set the transparency: %s" % err)
        layer.triggerRepaint()
        if self.before is not None:
            # The same amount on both, or the two are not comparable.
            try:
                self.before.setOpacity(share)
            except Exception:
                try:
                    self.before.renderer().setOpacity(share)
                except Exception:
                    pass
            if self.mirror is not None:
                self.mirror.refresh()

    def layer_role(self):
        return "correction:%s" % self.record["name"]

    def own_book(self):
        """True when the correction has a campaign of its own, False for a
        record still kept inside an annotation campaign."""
        return isinstance(self.book, CorrectionCampaign)

    def layer_title(self):
        if self.own_book():
            return "%s_corrected" % self.book.stem
        return "%s_%s_corrected" % (self.book.stem,
                                    tidy(self.record["name"], "mask"))

    def drop_strays(self):
        """Layers the project brought back that read this working copy.

        A QGIS project saves its layers, the copy among them, marked with
        whatever campaign it belonged to then: before corrections had a
        campaign of their own that was the annotation campaign, whose Close
        would take it away. They are taken out of the project here, which
        touches no file, and the copy is loaded again once, in the group of
        this correction, so there is one layer of it and it is this one."""
        target = os.path.normcase(os.path.abspath(self.path))
        stray = []
        try:
            layers = list(QgsProject.instance().mapLayers().values())
        except Exception:
            return 0
        for layer in layers:
            try:
                here = os.path.normcase(os.path.abspath(
                    layer.source().split("|")[0]))
            except Exception:
                continue
            if here == target:
                stray.append(layer.id())
        if stray:
            QgsProject.instance().removeMapLayers(stray)
            log("%d layer%s the project had kept of this working copy "
                "replaced by one in the group of the correction"
                % (len(stray), "" if len(stray) == 1 else "s"))
        return len(stray)

    def creator_name(self):
        """The operator the correction campaign was made with, in capitals."""
        return ((self.book.data.get("operator") or "").strip().upper()
                or "UNNAMED")

    def said_before(self):
        """The name typed in the window that made this correction earlier in
        this QGIS session, or "" (Panel.operator_said). The panel keeps it
        so that closing the correction and opening it again does not hand
        the strokes to a reading that was already there, picked for another
        campaign, and was never meant for this one."""
        said = getattr(self.panel, "operator_said", None)
        try:
            said = said(self.book.data.get("id", "")) if callable(said) \
                else ""
        except Exception:
            said = ""
        return said if isinstance(said, str) else ""

    def say_who_strikes(self):
        """When a correction opens with the strokes going to somebody other
        than the person who made it, because of the reading picked in this
        session, the log says so: the box only shows it as a placeholder."""
        if self.operator_choice:
            return
        who, made = self.default_operator(), self.creator_name()
        if who != made:
            log("correction '%s' was made by %s, and its strokes are filed "
                "under %s, the operator picked in this session; type a name "
                "in the operator box under Settings to change it"
                % (self.book.data.get("name", ""), made, who))

    def default_operator(self):
        """Who corrects when nobody has said in this box: the name typed in
        the window that made the correction, while this session is still on
        the reading it was on then, else the operator picked in the panel in
        this QGIS session (the reading, see Panel.operator_in_hand), else
        the one the correction was made with."""
        held = getattr(self.panel, "operator_in_hand", None)
        try:
            held = held() if callable(held) else None
        except Exception:
            held = None
        return (self.said_before() or held or "").strip().upper() \
            or self.creator_name()

    def operator_name(self):
        """Who is correcting, as operations.csv writes it, in capitals: what
        was typed in the operator box, else the operator picked in the panel
        (the reading a second reader keeps), else the one who made the
        correction. The one it was made with must not stay for ever, or every
        row of operations.csv would go to them whoever held the brush. A
        record still inside an annotation campaign asks the panel."""
        if self.own_book():
            return self.operator_choice or self.default_operator()
        return self.panel.who_is_drawing()

    def operator_key(self):
        """Where the operator typed for this correction is remembered on
        this machine, so that opening it again is not a question again."""
        return "%s/correct_operator/%s" % (SETTINGS_ROOT,
                                           self.book.data.get("id", ""))

    def operator_edited(self):
        """The operator box was left: in capitals, kept for this correction
        on this machine, and from the next stroke on the one every row is
        filed under. Empty goes back to the default."""
        text = self.who.text().strip().upper()
        if self.who.text() != text:
            self.who.setText(text)
        if text == self.operator_choice:
            return
        self.operator_choice = text
        write_setting(self.operator_key(), text)
        self.show_operator()
        log("correction '%s': the strokes are filed under %s"
            % (self.record["name"], self.operator_name()))

    def show_operator(self):
        self.who.setPlaceholderText(self.default_operator())
        self.who.setToolTip(
            "Who corrects: written on every row of operations.csv and in the\n"
            "journal, in capitals. Left empty it is the operator picked in the\n"
            "panel in this session, else %s, who made the correction."
            % self.creator_name())

    def list_operator(self, who):
        """A person who struck is one of the operators of the correction:
        added to its list the first time, and only then, so a correction
        made and corrected by one person keeps the manifest it had."""
        if not self.own_book() or not who:
            return
        people = self.record.get("operators")
        if not isinstance(people, list) or not people:
            people = [self.creator_name()]
        if who not in people:
            self.record["operators"] = people + [who]

    def style(self, layer):
        """The class palette on the class band. Without it QGIS reads class,
        probability and entropy as red, green and blue.

        The palette is the correction's own, so the copy is painted in the
        colours the map was styled with, not in those of the legend."""
        try:
            entries = [QgsPalettedRasterRenderer.Class(
                c["code"], QColor(c["colour"]), c["name"])
                for c in self.classes()]
            layer.setRenderer(QgsPalettedRasterRenderer(
                layer.dataProvider(), self.band_no, entries))
            layer.triggerRepaint()
            try:
                iface.layerTreeView().refreshLayerSymbology(layer.id())
            except Exception:
                pass
        except Exception as err:
            log("cannot apply the class palette: %s" % err)

    # ----------------------------------------------------------- the pair
    def show_beside(self, wanted):
        if wanted:
            self.open_mirror()
        else:
            self.close_mirror()

    def open_mirror(self):
        """A second view of the map as it arrived, beside the one you change.

        The layer it shows is opened straight from the file and is never put
        in the project: whatever happens here, the map the algorithm produced
        is only ever read."""
        if self.mirror is not None:
            return
        raster = self.panel.active_raster()
        self.before = QgsRasterLayer(self.source, "before")
        if not self.before.isValid():
            QMessageBox.warning(self, NAME,
                                "The map it started from cannot be read:\n%s"
                                % self.source)
            self.before = None
            self.compare.setChecked(False)
            return
        self.style(self.before)

        self.mirror = QgsMapCanvas()
        self.mirror.setCanvasColor(canvas().canvasColor())
        self.mirror.setDestinationCrs(canvas().mapSettings().destinationCrs())
        self.mirror.setLayers([self.before] + ([raster] if raster else []))
        self.mirror.setExtent(canvas().extent())
        self.mirror.refresh()

        self.mirror_dock = QDockWidget("%s: before" % NAME)
        self.mirror_dock.setWidget(self.mirror)
        self.mirror_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable |
                                     QDockWidget.DockWidgetFeature.DockWidgetFloatable |
                                     QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.mirror_dock.visibilityChanged.connect(self.mirror_closed)
        iface.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.mirror_dock)

        canvas().extentsChanged.connect(self.follow_main)
        self.mirror.extentsChanged.connect(self.follow_mirror)
        # and in the system of the main view whenever that changes, not only
        # in the one it had when this view was opened
        try:
            canvas().destinationCrsChanged.connect(self.follow_crs)
            self.following_crs = True
        except Exception as err:
            log("the view of the original cannot follow a change of "
                "coordinate system: %s" % err)
        self.set_opacity()
        log("the map as it arrived is on the left, the copy you change on the "
            "right. The brush only ever touches the copy.")

    def mirror_closed(self, visible):
        """Closing the second view from its own corner means the same as
        unticking the box."""
        if not visible and self.compare.isChecked():
            self.compare.setChecked(False)

    def close_mirror(self):
        if self.mirror is None:
            return
        for signal, slot in ((canvas().extentsChanged, self.follow_main),
                             (self.mirror.extentsChanged, self.follow_mirror)):
            try:
                signal.disconnect(slot)
            except Exception:
                pass
        if self.following_crs:
            self.following_crs = False
            try:
                canvas().destinationCrsChanged.disconnect(self.follow_crs)
            except Exception:
                pass
        try:
            self.mirror_dock.visibilityChanged.disconnect(self.mirror_closed)
        except Exception:
            pass
        try:
            iface.removeDockWidget(self.mirror_dock)
            self.mirror_dock.deleteLater()
        except Exception:
            pass
        self.mirror = None
        self.mirror_dock = None
        self.before = None

    def follow_main(self):
        """The two views are kept on the same ground. The guard is what stops
        each one answering the other for ever."""
        if self.mirror is None or self.syncing:
            return
        self.syncing = True
        try:
            self.mirror.setExtent(canvas().extent())
            self.mirror.refresh()
        finally:
            self.syncing = False

    def follow_crs(self):
        """The main view changed its coordinate system: so does the view of
        the original, on the same ground. It kept the one it was born with,
        and after the change the two showed different places."""
        if self.mirror is None:
            return
        self.syncing = True
        try:
            self.mirror.setDestinationCrs(
                canvas().mapSettings().destinationCrs())
            self.mirror.setExtent(canvas().extent())
            self.mirror.refresh()
        finally:
            self.syncing = False

    def follow_mirror(self):
        if self.mirror is None or self.syncing:
            return
        self.syncing = True
        try:
            canvas().setExtent(self.mirror.extent())
            canvas().refresh()
        finally:
            self.syncing = False

    def refresh_map(self):
        layer = self.ensure_layer()
        if layer is None:
            return
        layer.dataProvider().reloadData()
        layer.triggerRepaint()

    def report_codes(self):
        """Which codes the mask actually holds, against its own classes.

        Read from the whole band, whatever its type: the codes of a class map
        are not bound to one byte. A code the classes do not name, which a map
        changed outside the program can come to hold, is given a class here
        rather than left without a chip."""
        try:
            present = set(codes_present(self.values, self.nodata))
        except Exception as err:
            log("cannot read the codes of the mask: %s" % err)
            return
        known = {c["code"] for c in self.classes()}
        log("the mask holds the codes %s" % (sorted(present) or "none"))
        self.adopt(sorted(present - known), "codes found in the mask")
        missing = sorted(known - present)
        if missing:
            log("classes of this correction not present in the mask: %s"
                % missing)

    # ----------------------------------------------------------- the brush
    def use_brush(self, round_=None):
        if self.brush is None:
            self.brush = BrushTool(canvas(), self)
        if round_ is True:
            self.b_round.setChecked(True)
        elif round_ is False:
            self.b_brush.setChecked(True)
        elif not (self.b_brush.isChecked() or self.b_round.isChecked()):
            self.b_brush.setChecked(True)
        self.brush.refresh_colour()
        canvas().setMapTool(self.brush)

    def release_tools(self):
        if self.brush is not None and canvas().mapTool() is self.brush:
            canvas().unsetMapTool(self.brush)

    def under_mode(self):
        return False

    # ----------------------------------------------------------- picking
    def pixel_under(self, point):
        """The column and row of the pixel holding a point of the map.

        Rounded down, not toward zero: int() gave the first column or row
        to a point up to one pixel off the map on the side the grid starts
        from, on a north-down map as on any other, and a click just outside
        the map picked the class of the pixel at its edge."""
        col = int(np.floor((point.x() - self.gt[0]) / self.gt[1]))
        row = int(np.floor((point.y() - self.gt[3]) / self.gt[5]))
        return col, row

    def code_at(self, point, nodata_says):
        """The class code of the pixel under the cursor, or None with the
        reason on the message bar. A code the classes do not name is given a
        class first, so it can be picked like any other."""
        col, row = self.pixel_under(point)
        if not (0 <= col < self.nx and 0 <= row < self.ny):
            return None
        raw = self.values[row, col]
        if (self.nodata is not None and raw == self.nodata) \
                or not np.isfinite(raw):
            iface.messageBar().pushMessage(
                NAME, "nodata under the cursor: %s" % nodata_says,
                level=LEVEL_INFO, duration=3)
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if value != raw:
            iface.messageBar().pushMessage(
                NAME, "%s under the cursor is not a class code" % raw,
                level=LEVEL_WARNING, duration=3)
            return None
        if self.class_of(value) is None:
            self.adopt([value], "the code under the cursor,")
        return value if self.class_of(value) is not None else None

    def reclassify_at(self, point):
        """Ctrl and click: the class under the cursor becomes FROM, the one
        the stroke will change. True when the click was used, so the brush
        does not also start an outline there."""
        col, row = self.pixel_under(point)
        if not (0 <= col < self.nx and 0 <= row < self.ny):
            return False
        value = self.code_at(point, "there is no class there to change")
        if value is None:
            return True
        self.choose_from(value)
        iface.messageBar().pushMessage(
            NAME, "FROM %s: the brush now changes %s into %s"
            % (self.from_name(), self.from_name(), self.class_name),
            level=LEVEL_INFO, duration=2)
        return True

    def pick_into_at(self, point):
        """Shift and click: the class under the cursor becomes TO, the one the
        stroke will write. Only Correct has this: in Annotate, Shift held
        while drawing means "paints over", and the brush asks for this method
        by name before it lets Shift pick anything."""
        col, row = self.pixel_under(point)
        if not (0 <= col < self.nx and 0 <= row < self.ny):
            return False
        value = self.code_at(point, "nodata cannot be painted")
        if value is None:
            return True
        self.choose_class(value)
        iface.messageBar().pushMessage(
            NAME, "TO %s: the brush now changes %s into %s"
            % (self.class_name, self.from_name(), self.class_name),
            level=LEVEL_INFO, duration=2)
        return True

    # ----------------------------------------------------------- the write
    def mask_of(self, geom):
        """The pixels a polygon covers, computed only inside its own window."""
        box = geom.boundingBox()
        col, row, w, h = snap(self.gt, (self.nx, self.ny), box)
        if w <= 0 or h <= 0:
            return None
        if w * h > MAX_WINDOW_PX:
            raise ValueError("that stroke covers %d million pixels: draw a "
                             "smaller one" % (w * h // 1000000))
        gt = window_transform(self.gt, col, row)
        return col, row, burn([(geom, 1)], gt, w, h, self.wkt).astype(bool)

    def ground_of(self, picked, row):
        """The ground, in m2, of the pixels picked in a window whose first
        row is row of the map: row by row where the pixel is not the same
        ground all down the map (ground_rows), else their number times the
        one pixel."""
        if self.row_m2 is None:
            return int(picked.sum()) * self.pixel_area_m2
        per_row = picked.sum(axis=1)
        return float(np.dot(per_row, self.row_m2[row:row + len(per_row)]))

    def recount_ground(self):
        """How much ground the record of changes marks, once each pixel: the
        pixels a person changed, counted down the record a strip at a time,
        so that the panel can say it next to the strokes, which count a pixel
        painted over twice as twice. None when there is no record."""
        self.on_ground_px = self.on_ground_m2 = None
        if self.marks is None:
            return
        px, m2 = 0, 0.0
        try:
            for row, strip in self.marks.strips():
                per_row = (strip != 0).sum(axis=1)
                px += int(per_row.sum())
                m2 += float(np.dot(per_row, self.row_m2[row:row + len(per_row)])
                            if self.row_m2 is not None
                            else per_row.sum() * self.pixel_area_m2)
        except Exception as err:
            log("cannot count the pixels recorded as changed: %s" % err)
            return
        self.on_ground_px, self.on_ground_m2 = px, m2

    def take_back(self, made):
        """What an undone stroke counted for, put on the side of the undone:
        operations.csv and the three counters keep it, as the log of what was
        written, and the net is what is left (net_operations, net_m2,
        net_pairs)."""
        mine = self.undone
        mine["operations"] += 1
        mine["changed_m2"] += made["changed_m2"]
        mine["swept_m2"] += made["swept_m2"]
        counted = mine["pairs"].get(made["pair"], [0, 0.0])
        mine["pairs"][made["pair"]] = [
            counted[0] + 1, round(counted[1] + made["changed_m2"], 3)]
        if made.get("fresh_px") is not None and self.on_ground_px is not None:
            self.on_ground_px -= made["fresh_px"]
            self.on_ground_m2 -= made["fresh_m2"]

    @property
    def net_operations(self):
        return max(0, self.operations - self.undone["operations"])

    @property
    def net_m2(self):
        return max(0.0, self.changed_m2 - self.undone["changed_m2"])

    @property
    def net_swept_m2(self):
        return max(0.0, self.swept_m2 - self.undone["swept_m2"])

    def net_pairs(self):
        """The pairs of the tally with the undone strokes taken off; a pair
        nothing is left of is not there."""
        out = {}
        for pair, (n, area) in self.pairs.items():
            gone_n, gone_area = self.undone["pairs"].get(pair, [0, 0.0])
            if n - gone_n > 0:
                out[pair] = [n - gone_n, max(0.0, area - gone_area)]
        return out

    def paint(self, geom, **kwargs):
        if self.class_name is None:
            return
        try:
            got = self.mask_of(geom.makeValid())
        except ValueError as err:
            iface.messageBar().pushMessage(NAME, str(err), level=LEVEL_WARNING, duration=5)
            return
        if got is None:
            iface.messageBar().pushMessage(
                NAME, "the stroke falls outside the map", level=LEVEL_WARNING, duration=3)
            return
        col, row, inside = got
        h, w = inside.shape
        # What the file holds under the stroke, a copy of just that window
        window = self.values[row:row + h, col:col + w]
        into = self.current_code()
        wanted = self.from_code
        if wanted is None:
            # Any class, and zero is one of them: only nodata is spared. A
            # map whose zero means "nothing" says so with its nodata value.
            # NaN is never equal to anything, the nodata value included: a
            # float map whose nodata is NaN, or that marks holes with it,
            # would have them painted over by a comparison alone.
            valid = np.ones(window.shape, dtype=bool)
            if window.dtype.kind == "f":
                valid &= np.isfinite(window)
            if self.nodata is not None:
                valid &= window != self.nodata
            change = inside & valid & (window != into)
        else:
            if wanted == into:
                iface.messageBar().pushMessage(
                    NAME, "FROM and TO are the same class: nothing to change",
                    level=LEVEL_WARNING, duration=3)
                return
            change = inside & (window == wanted)

        pixels = int(change.sum())
        if pixels == 0:
            iface.messageBar().pushMessage(
                NAME, "nothing of %s inside the stroke" % self.from_name(),
                level=LEVEL_INFO, duration=2)
            return
        swept = self.geometry.area(geom)
        moved = self.ground_of(change, row)
        if self.confirm.isChecked():
            q = QMessageBox.question(
                self, "Correct",
                "%d pixels, %.2f m2, from %s into %s.\nApply?"
                % (pixels, moved, self.from_name(), self.class_name))
            if q != QMessageBox.StandardButton.Yes:
                return
        self.adopt(codes_present(window[change], self.nodata),
                   "a stroke went over codes")

        marks = self.marks[row:row + h, col:col + w] if self.marks is not None else None
        after = window.copy()
        after[change] = into
        marks_after = None
        fresh = None
        if marks is not None:
            marks_after = marks.copy()
            marks_after[change] = 1
            fresh = change & (marks == 0)       # first time a person changes them
        # Kept as "every class" in the manifest and the log, the words they
        # were written with before the panel said "any class": a record or a
        # log read back by a script finds the same text in every row.
        names = {c["code"]: c["name"] for c in self.classes()}
        pair = "%s -> %s" % (names.get(wanted, "every class"), self.class_name)

        if not self.write_stroke(after, marks_after, col, row, window):
            # Not on disk, so nowhere: the file holds what it held, and the
            # count, the log and the history do not know of the stroke.
            return
        if self.marks is None:
            fresh = None            # the record was given up by that write
        # (col, row, the pixels before, the marks before, what each hook
        # kept of the stroke to undo it, what the stroke counted for: to take
        # it back, Undo), the last two filled once it is made
        self.history.append((col, row, window,
                             None if marks is None else marks, [],
                             {"changed_m2": moved, "swept_m2": swept,
                              "pair": pair, "pixels": pixels,
                              "fresh_px": None if fresh is None
                              else int(fresh.sum()),
                              "fresh_m2": None if fresh is None
                              else self.ground_of(fresh, row)}))
        if len(self.history) > UNDO_DEPTH:
            self.history.pop(0)
        if fresh is not None and self.on_ground_px is not None:
            self.on_ground_px += self.history[-1][5]["fresh_px"]
            self.on_ground_m2 += self.history[-1][5]["fresh_m2"]
        self.refresh_map()

        self.operations += 1
        self.changed_m2 += moved
        self.swept_m2 += swept
        counted = self.pairs.get(pair, [0, 0.0])
        self.pairs[pair] = [counted[0] + 1, round(counted[1] + moved, 3)]
        self.write_log(geom, pixels, swept, moved, col, row, w, h)
        self.list_operator(self.operator_name())
        self.remember()
        centre = geom.centroid().asPoint()
        self.history[-1][4][:] = self.hooks_stroke({
            "col": col, "row": row, "width": w, "height": h,
            "inside": inside, "change": change, "from_code": wanted,
            "into": into, "pixels": pixels, "changed_m2": moved,
            "swept_m2": swept, "n": self.operations,
            "x": centre.x(), "y": centre.y(), "place": None})
        self.show_tally("%d px, %.2f m2, %s %s %s"
                        % (pixels, moved, self.from_name(), ARROW,
                           self.class_name))

    def undo(self):
        if not self.history:
            iface.messageBar().pushMessage(NAME, "nothing to undo", level=LEVEL_INFO,
                                           duration=2)
            return
        col, row, before, before_marks, states, made = self.history[-1]
        if self.marks is None:
            before_marks = None
        if not self.write_stroke(before, before_marks, col, row):
            return              # kept, to be undone once the file can be
        self.history.pop()
        self.hooks_undo(states)
        self.take_back(made)
        self.refresh_map()
        self.remember()
        self.show_tally("last change undone. operations.csv keeps its row, "
                        "the journal notes the undo, and the count above is "
                        "net of it.")

    # ----------------------------------------------------------- the hooks
    def _hook_call(self, hook, method, *args):
        """One method of one hook, if it has it; what it answers, or None
        when it has not or it failed, which is said and never stops a
        stroke that is already on disk."""
        fn = getattr(hook, method, None)
        if not callable(fn):
            return None
        try:
            return fn(self, *args)
        except Exception as err:
            log("%s of %s failed: %s"
                % (method, type(hook).__name__, err))
            return None

    def hooks_stroke(self, ctx):
        """Each hook told of a stroke that is written: the window it touched
        (col, row, width, height), which pixels were inside it and which it
        changed, from what into what, how much, its number and its middle.
        The hooks are told in their order and share ctx, so one can leave a
        word in it for the next (the place of the uncertainty walk, for the
        journal). Returns what each kept to undo it, in the hooks' order."""
        return [self._hook_call(hook, "stroke", ctx)
                for hook in getattr(self, "stroke_hooks", [])]

    def hooks_undo(self, states):
        """The stroke undone: each hook given back what it kept of it."""
        hooks = getattr(self, "stroke_hooks", [])
        for hook, state in zip(hooks, states or []):
            if state is not None:
                self._hook_call(hook, "undo", state)

    def hooks_flush(self):
        for hook in getattr(self, "stroke_hooks", []):
            self._hook_call(hook, "flush")

    def hooks_closing(self):
        for hook in getattr(self, "stroke_hooks", []):
            self._hook_call(hook, "closing")

    def write_stroke(self, values, marks, col, row, before=None):
        """values written into the copy at col, row, and marks, when given,
        into the record of changes beside it: each file opened for this
        stroke alone and closed again before QGIS reads it
        (rasters.write_window says why). False, and said, when the copy
        could not be written: the stroke is then not made at all. A record
        of changes that cannot be written is said and not kept for the rest
        of this correction, rather than kept wrong.

        before is what the copy held under values. A write that fails may
        have reached the disk in part, a flush that was refused after the
        blocks were handed over, so the stroke that is refused puts it back,
        as far as the disk lets it, and the copy is not left holding a
        stroke that was never counted."""
        try:
            write_window(self.path, self.band_no, values, col, row)
        except Exception as err:
            log("nothing was changed: %s. If another program has the "
                "corrected map open for writing, close it and try again."
                % err, loud=True)
            # Put back only what may have reached the disk: a copy that could
            # not be opened for writing was never touched, and saying that it
            # may hold part of the stroke would be a false alarm.
            if before is not None and getattr(err, "touched", True):
                try:
                    write_window(self.path, self.band_no, before, col, row)
                except Exception as again:
                    log("and the copy may hold part of that stroke, which "
                        "could not be taken back: %s" % again, loud=True)
            return False
        if marks is not None and self.marks is not None:
            try:
                write_window(self.changes_path, 1, marks, col, row)
            except Exception as err:
                self.marks = None
                self.on_ground_px = self.on_ground_m2 = None
                log("%s. The strokes still work; which pixels a person "
                    "changes from now on is not remembered." % err,
                    loud=True)
        return True

    # ----------------------------------------------------------- the books
    @property
    def log_path(self):
        return os.path.join(os.path.dirname(self.path), "operations.csv")

    LOG_COLUMNS = ["n", "when", "operator", "into", "only", "pixels",
                   "swept_m2", "changed_m2", "x", "y", "col", "row",
                   "width", "height"]

    def write_log(self, geom, pixels, swept, moved, col, row, w, h):
        centre = geom.centroid().asPoint()
        only = self.from_code
        names = {c["code"]: c["name"] for c in self.classes()}
        line = [self.operations, now(), self.operator_name(),
                self.class_name, names.get(only, "every class"), pixels,
                "%.3f" % swept, "%.3f" % moved,
                "%.6f" % centre.x(), "%.6f" % centre.y(), col, row, w, h]
        fresh = not os.path.exists(self.log_path)
        try:
            with open(self.log_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if fresh:
                    writer.writerow(self.LOG_COLUMNS)
                writer.writerow([csv_text(c) for c in line])
        except OSError as err:
            log("cannot write the log: %s" % err)

    def remember(self):
        self.record["operations"] = self.operations
        self.record["changed_m2"] = round(self.changed_m2, 3)
        self.record["swept_m2"] = round(self.swept_m2, 3)
        self.record["pairs"] = self.pairs
        if self.undone["operations"]:
            # only once something was undone, so a manifest that never had
            # an Undo is written as it always was
            self.record["undone"] = {
                "operations": self.undone["operations"],
                "changed_m2": round(self.undone["changed_m2"], 3),
                "swept_m2": round(self.undone["swept_m2"], 3),
                "pairs": self.undone["pairs"]}
        self.record["last_opened"] = now()
        try:
            self.book.save()
        except Exception as err:
            log("cannot update the manifest: %s" % err)

    def show_tally(self, last=None):
        """How much was moved, and from what into what.

        The ratio between the ground the brush swept and the ground that
        actually changed says how surgical the correction was: close to one
        means every stroke was aimed, far above one means a lot of sweeping
        for little effect.

        The figures are net of Undo: operations.csv keeps the row of a stroke
        that was undone, because it was written, and this does not count it.
        Strokes that painted over the same pixels count each time; the line
        under the first says how much ground that comes to once each, when
        the record of changes is there to say it."""
        gone = self.undone["operations"]
        rows = ["<table cellspacing=3><tr><td><b>%d</b> operations%s</td>"
                "<td align=right><b>%.2f m2</b></td></tr>"
                % (self.net_operations,
                   " (%d undone)" % gone if gone else "", self.net_m2)]
        if (self.on_ground_m2 is not None and self.on_ground_px
                and abs(self.on_ground_m2 - self.net_m2) > 0.005):
            rows.append("<tr><td>on the ground, once each</td>"
                        "<td align=right>%.2f m2</td></tr>"
                        % self.on_ground_m2)
        if self.net_m2 > 0 and self.net_swept_m2 > 0:
            rows.append("<tr><td>swept over changed</td><td align=right>"
                        "%.1f</td></tr>" % (self.net_swept_m2 / self.net_m2))
        net = self.net_pairs()
        for pair in sorted(net, key=lambda k: -net[k][1])[:6]:
            n, area = net[pair]
            shown = pair.replace("every class -> ", ANY_CLASS + " -> ")
            # the strokes in words: "3, 597.73 m2" read as 3,597.73 m2
            rows.append("<tr><td>%s</td><td align=right>%.2f m2 in %d "
                        "%s</td></tr>"
                        % (shown.replace(" -> ", " %s " % ARROW), area, n,
                           "stroke" if n == 1 else "strokes"))
        rows.append("</table>")
        if last:
            rows.append("<span style='color:#666'>%s</span>" % last)
        # and what the measuring modules say under it, two quiet lines at
        # the most whatever they have to say
        said = []
        for hook in getattr(self, "stroke_hooks", []):
            said.extend(str(l) for l in
                        (self._hook_call(hook, "tally_lines") or []) if l)
        for line in said[:2]:
            rows.append("<br><span style='color:#666'>%s</span>"
                        % escape(line))
        self.tally.setText("".join(rows))

    def save(self):
        """Every stroke is already in the copy and in the record of changes,
        each closed after it (write_stroke): Save writes the classes and the
        manifest. The measuring modules write what they keep too."""
        self.dress()
        self.remember()
        self.hooks_flush()
        iface.messageBar().pushMessage(
            NAME, "correction '%s' saved, %d operations"
            % (self.record["name"], self.net_operations), level=LEVEL_INFO,
            duration=3)

    def unsaved(self):
        return False            # the copy is written at every stroke

    def close_dataset(self):
        """Before anyone renames or removes the files. Correct holds no
        handle on them between strokes, so there is nothing to flush; the
        last word on the style is written once, the classes as they are
        when the correction closes."""
        self.close_mirror()
        self.bring_source_back()
        if not self.closed:
            self.closed = True
            self.dress()
            # the hooks write what they keep and let go of their files, once
            self.hooks_flush()
            self.hooks_closing()

    def describe(self):
        """The tooltip of the head: where the correction lives, its pixel and
        who corrects, in the words the campaign line of the panel uses."""
        grid = (self.book.data or {}).get("grid") or {}
        if not isinstance(grid, dict):
            grid = {}
        pixel = grid.get("pixel_m") or []
        where = getattr(self.book, "folder", "") or os.path.dirname(self.path)
        return ("%s\npixel %s, %s\noperator %s"
                % (where, ("%.3f m" % pixel[0]) if pixel else "unknown",
                   crs_label(crs_from_text(grid.get("crs"))),
                   self.operator_name()))

    def edit_classes(self):
        """The window the classes were confirmed in, again.

        The values the copy holds are locked: corrections have already been
        written under them, and renumbering a class there would leave its
        pixels under a number with no name. A class added later and not yet
        painted can still change its value; any class its colour and name."""
        present = class_counts(self.values, self.nodata)
        d = ConfirmClasses(self, [dict(c, origin="confirmed")
                                  for c in self.classes()], present,
                           os.path.basename(self.source), self.band_no,
                           self.nodata, self.code_range(),
                           locked=sorted(present), again=True)
        if not run_dialog(d):
            return
        self.record["classes"] = d.result()
        try:
            self.book.save()
        except Exception as err:
            log("cannot update the manifest: %s" % err, loud=True)
        self.classes_changed()
        self.rebuild_class_buttons()
        log("correction '%s': classes confirmed again, %d"
            % (self.record["name"], len(self.classes())))

    def delete(self):
        """Set the correction aside: nothing erased.

        A correction campaign is usually its own folder, and then the whole
        of it goes, manifest, copy, its record of changes, its style and
        operations.csv together, renamed <folder>.removed-<time>. A folder
        the correction shares with other work, an annotation campaign's
        campaign.json, its GeoPackage and its image beside correction.json,
        is not renamed: only the correction's own files (own_files) move,
        into a set_aside_<time> folder inside it, and everything else stays
        where it is. Renaming it took the annotation campaign away from its
        path along with the correction. The annotation campaign, if one is
        open, is not written to. A correction still kept inside an
        annotation campaign leaves that campaign's manifest, as it always
        did."""
        folder = self.book.folder if self.own_book() \
            else os.path.dirname(self.path)
        shared = self.shares_folder(folder)
        if shared:
            where = ("Its own files are set aside, not erased, in a folder "
                     "set_aside_ and the time, inside:\n%s\n\nThe other files "
                     "of that folder, which are not the correction's, stay "
                     "where they are." % folder)
        else:
            where = "Its folder is set aside, not erased:\n%s" % folder
        q = QMessageBox.question(
            self, "Set the correction aside",
            "'%s' holds %d operations.\n\n%s\n\nThe map it started from is "
            "untouched either way.\n\nProceed?"
            % (self.record["name"], self.net_operations, where))
        if q != QMessageBox.StandardButton.Yes:
            return
        self.release_tools()
        self.close_dataset()
        layer = find_mine(self.book.data["id"], self.layer_role())
        if layer is not None:
            QgsProject.instance().removeMapLayers([layer.id()])
        release_file(self.path)
        release_file(self.changes_path)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        spare = "%s.removed-%s" % (folder, stamp)
        if self.own_book():
            # The log is written inside this folder while Correct is open, so
            # it is let go of before the folder moves. The next line would
            # otherwise look for a folder that is not there any more, and the
            # log would give up with a warning in the QGIS log. Closing the
            # module below closes the correction with it and sends the log
            # back beside the campaign, if one is open.
            log("setting the correction '%s' aside" % self.record["name"])
            log_to(None)
        failed = None
        try:
            if shared:
                # The log stays: in a folder shared with an annotation
                # campaign it is that campaign's log too.
                spare = set_aside_leftovers(
                    folder, [n for n in self.own_files() if n != LOG_NAME]) \
                    or folder
            else:
                os.replace(folder, spare)
        except OSError as err:
            failed = err
            spare = folder
        if self.own_book():
            forget_correction(self.book.manifest_path)
        else:
            self.book.data["corrections"] = [
                c for c in self.book.data.get("corrections", [])
                if c.get("name") != self.record["name"]]
            self.book.save()
        self.panel.close_module()
        if failed is None:
            log("correction set aside as %s" % spare)
            QMessageBox.information(
                self, NAME, "The correction is set aside.\nIts files are "
                            "here if you want them back:\n%s%s"
                % (spare, "\n\nThe other files of %s are where they were."
                   % folder if shared else ""))
            return
        # Said as it is: a folder another program holds open stays where it
        # was, and announcing it as set aside sent the user looking for a
        # folder that was never made.
        log("cannot set the %s aside: %s"
            % ("files" if shared else "folder", failed), loud=True)
        QMessageBox.warning(
            self, NAME, "The correction is closed, but its %s could not be "
                        "moved aside:\n%s\n\nIts files are where they were:"
                        "\n%s" % ("files" if shared else "folder", failed,
                                  folder))

    def own_files(self):
        """The names of the files in the correction's folder that are the
        correction's own: the copy and everything beside it (its .aux.xml,
        its style, its record of changes), the manifest, operations.csv and
        the log."""
        names = beside_the_copy(self.path)
        changes = os.path.basename(self.changes_path)
        for n in (changes, changes + ".aux.xml",
                  CorrectionCampaign.MANIFEST,
                  CorrectionCampaign.MANIFEST + ".tmp",
                  "operations.csv", LOG_NAME, REPORTS_FOLDER):
            if n not in names:
                names.append(n)
        # and the files the measuring modules keep beside the copy
        here = os.path.normcase(os.path.abspath(os.path.dirname(self.path)))
        for hook in getattr(self, "stroke_hooks", []):
            for path in self._hook_call(hook, "files") or []:
                path = str(path)
                if os.path.dirname(path) and os.path.normcase(os.path.abspath(
                        os.path.dirname(path))) != here:
                    continue
                n = os.path.basename(path)
                if n and n not in names:
                    names.append(n)
        return names

    def shares_folder(self, folder):
        """True when the folder of a correction campaign holds anything that
        is not the correction's: an annotation campaign made in the same
        folder, an image, files of the user's. The folders set aside by
        fresh copies made before are the correction's."""
        if not self.own_book():
            return False
        mine = set(self.own_files())
        try:
            entries = os.listdir(folder)
        except OSError:
            return False
        return any(n not in mine and not n.startswith("set_aside_")
                   for n in entries)
