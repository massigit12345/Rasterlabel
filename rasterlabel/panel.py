"""rasterlabel.panel

The shell: the campaign, the legend, the modules.
"""
import json
import numpy as np
import os
import re
from html import escape, unescape

from osgeo import gdal
from qgis.PyQt.QtCore import QSize, Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QFont
from qgis.PyQt.QtWidgets import (QApplication, QBoxLayout, QCheckBox,
                                 QComboBox, QDialog, QFileDialog, QFrame,
                                 QGridLayout,
                                 QHBoxLayout, QLabel, QMessageBox,
                                 QPushButton, QSizePolicy, QSpinBox,
                                 QToolButton, QVBoxLayout, QWidget)
from qgis.core import (QgsCoordinateTransform, QgsFeature, QgsGeometry,
                       QgsProject, QgsRasterLayer, QgsVectorLayer)

from .constants import (BAR_MAX, CARD_MIN, CARD_W, COLUMN_MAX, COLUMNS_MAX,
                        EDITABLE_TABLES, FLAG_BAND_NAME, LONG_STEP, NAME,
                        NAV_H, NAV_W, ONE_COLUMN, PANEL_MIN, PLANS,
                        SETTINGS_ROOT, STEP_PERCENT, TABLES)
from .compat import read_setting, run_dialog, write_setting
from .naming import from_folder, long_path, now, source_of
from .project import (canvas, crs_from_text, crs_label, is_vertex_tool,
                      pixel_on_the_ground, project_rasters, proposed_raster)
from .errors import (by_own_hands, hook, log, log_to, own_hands, shielded,
                     trouble, unhook)
from .recovery import (DISCARDED_SUFFIX, Recovery, describe_snapshot,
                       keep_snapshot, snapshots_waiting)
from .doctor import check
from .view import step, zoom
from .layout import FlowLayout
from .theme import (arrow_icon, bar, dress, fit_field, follows_width, keypad,
                    label_sheet, plain, primary, stylesheet)
from .widgets import OneLine
from .campaign import (READING_TABLES, Campaign, passes_of, readings_in,
                       set_aside, write_pass, zip_name)
from .layers import (add_layer, drop_layers, drop_stale, find_mine, mark,
                     passes_found, restyle, tidy_layers, veil_report_layers)
from .tools import clear_bands
from .rasters import (BandPlane, class_counts, lossy_codec, rotated_file,
                      rotated_refusal, style_classes, thematic_classes,
                      values_in)
from .correction import (CorrectionCampaign, beside_the_copy, changes_name,
                         changes_of, colour_picture, colour_text, copy_name,
                         corrections_of, dress_copy, has_flag_band,
                         lossy_text, owner_of_copy, peek_correction,
                         recent_corrections, remember_correction,
                         same_file,
                         set_aside_leftovers, why_a_working_copy)
from .dialogs import (ClassEditor, ConfirmClasses, ExportVectors, NewCampaign,
                      OpenCorrection, WhoIsDrawing)
from .sections_annotate import AnnotationSection
from .sections_correct import CorrectionSection
from .sections_cutouts import (CutoutsSection, ask_hidden,
                               hidden_readings, write_card_beside)
from .sections_objects import ObjectsSection, ReadingFilter
from .export import pack_zip, write_vectors
from .measure import (CORRECT_HOOKS, CORRECTION_TOOLTIP_LINES,
                      DOCTOR_CAMPAIGN, DOCTOR_CORRECTION, FRAME_LISTENERS,
                      measure_all, measure_blind_gate, measure_menu,
                      measure_tooltip)


# What each block says while it holds nothing. One line each, under the
# buttons it speaks for: a single line for the whole panel would be cut off
# at the width of a bar.
NO_CAMPAIGN = "no annotation campaign open"
NO_CORRECTION = "no correction open"
NO_CUTOUTS = "saves no campaign"
# The first two, folded beside the name of their block, which already says
# what it is that is not open.
NONE_OPEN = "none open"
# What keeps a line from breaking after a colon or a slash, where Qt breaks
# one of its own accord and a space that does not break has no say: a word
# joiner, written a pixel high, because the fonts QGIS uses do not have it
# and the one that stands in for them made the line half as tall again.
JOIN = "<span style='font-size:1px'>&#8288;</span>"
# Why the buttons that need a raster are grey, in their tooltips: Qt shows the
# tooltip of a disabled button, and a grey New that does not say why is a
# question with nobody to ask.
LOAD_RASTER = ("Load a raster first: add it to the QGIS project (Layer > Add "
               "Layer > Add\nRaster Layer, or drag the file onto the map) and "
               "it shows beside RASTER.")
# The two keypads are written row by row (theme.keypad), the same rows at
# every width. New, Open and Close first in both, so that those of the one
# stand over those of the other; then what is done to what is open; and
# Measure always just before Check, with Check ending the keypad. The
# campaign's seven keys are three, two and two, the correction's six three
# and three: a row of two is in halves, never a row of three with a hole.
OPERATOR_KEY = SETTINGS_ROOT + "/operator"
# The reading somebody is drawing, campaign by campaign: followed by the
# campaign's id, it holds the operator, the pass and the blind switch last
# used on it on this machine.
READING_KEY = SETTINGS_ROOT + "/reading/"
# Who last drew in this QGIS session, in any campaign. A reading remembered
# from another day, by somebody else, is not taken on without asking.
SESSION = {"operator": None}
# The block each module opens from, by the index of the module (Annotate,
# Correct, Objects, Cutouts) and of the card (the annotation campaign is 1,
# the correction 2, cutouts 3). The open module is dealt right under it.
OWNER = {0: 1, 1: 2, 2: 1, 3: 3}


class HeadRow(QWidget):
    """The line of a block's name. While the block can fold, a click
    anywhere on it does what its arrow does, as on QGIS's own folding
    groups: the arrow alone was a target of twenty pixels at the far end."""
    toggle = None

    def _live(self):
        return self.toggle is not None and self.toggle.isVisible()

    def mousePressEvent(self, ev):
        if self._live() and ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            return
        QWidget.mousePressEvent(self, ev)

    def mouseReleaseEvent(self, ev):
        if self._live() and ev.button() == Qt.MouseButton.LeftButton:
            ev.accept()
            self.toggle.click()
            return
        QWidget.mouseReleaseEvent(self, ev)


class Panel(QWidget):

    def __init__(self):
        super().__init__()
        self.campaign = None
        # The correction campaign, opened in CORRECTION and worked on in
        # Correct. It needs no annotation campaign, and it lives as long as
        # Correct is open: leaving Correct for another module closes it, as
        # Close in CORRECTION does.
        self.correction = None
        self._log_folder = None
        # What each button says while it can be pressed. When it cannot, the
        # reason goes in front of it: see allow().
        self.tips = {}
        self.dock = None
        # The net under the edit buffers. There is one as soon as a campaign is
        # open, and until then there is nothing to lose.
        self.recovery = None
        follows_width(self)
        self.setMinimumWidth(PANEL_MIN)
        if ONE_COLUMN:
            # Dragged wider than this the dock shows grey to the right, which
            # says "stop" more clearly than cards stretched to nine hundred
            # pixels with their words lost in the middle.
            self.setMaximumWidth(BAR_MAX)
        # Two sheets. The labels' rules on the panel, where the dialogs it
        # opens inherit them and their quiet lines stay quiet; the controls'
        # rules on the body inside it, which holds every control of the
        # panel and none of its windows. See theme.stylesheet().
        self.setStyleSheet(label_sheet())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.content = follows_width(QWidget())
        self.content.setObjectName("rlBody")
        self.content.setStyleSheet(stylesheet())
        outer.addWidget(self.content)
        # Which blocks the user unfolded by hand while a module is open.
        self._unfolded = set()
        self.folds = {}

        # The panel is a handful of cards, and the cards are dealt into as many
        # columns as the width can hold. A dock at the side of the map is one
        # tall column; the same dock dragged to the top of the window is a low
        # strip and becomes three columns of the same width. Nothing is ever
        # stretched past the width at which a row of buttons stops being
        # readable: past that the space is simply left empty.
        self.strip = QHBoxLayout(self.content)
        self.strip.setContentsMargins(8, 8, 8, 8)
        self.strip.setSpacing(16)
        self.columns = []
        for _ in range(COLUMNS_MAX):
            column = QVBoxLayout()
            column.setSpacing(16)
            column.addStretch(1)
            self.strip.addLayout(column, 0)
            self.columns.append(column)
        self.strip.addStretch(0)
        self._columns = None

        # ---- the raster everything is measured on. Its name and its list
        # on one line: a block of one control needs no line for its title.
        card = follows_width(QWidget())
        box = QVBoxLayout(card)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._header("RASTER"))
        self.rasters = QComboBox()
        # Taken by a click, as it always was, and reached by Tab as well.
        self.rasters.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # A long layer name is cut in the list instead of widening the panel.
        self.rasters.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.rasters.setMinimumContentsLength(8)
        self.rasters.setSizePolicy(QSizePolicy.Policy.Expanding,
                                   QSizePolicy.Policy.Fixed)
        self.rasters.currentIndexChanged.connect(
            shielded(self.describe_raster, "Raster"))
        row.addWidget(self.rasters, 1)
        box.addLayout(row)
        # what the panel measures with: the pixel on the ground and the system
        self.raster_state = self._quiet("")
        box.addWidget(self.raster_state)
        # The first thing to do, in the strip the modules use for it, while
        # nothing is open: an empty panel of grey buttons said nothing.
        self.hint = QLabel("")
        self.hint.setObjectName("step")
        self.hint.setWordWrap(True)
        box.addSpacing(4)
        box.addWidget(self.hint)
        card_raster = card

        # ---- the annotation campaign: what is open, what you do to it, and
        # the two modules that draw into it, right under the buttons that open
        # and close it. Set beside Correct and Cutouts in one row of four, a
        # reader could not tell which of the four the campaign buttons spoke
        # for.
        card, box = self._card(1, "ANNOTATION CAMPAIGN")
        self.b_new = self._word("New", "Create a new annotation campaign.",
                                self.new_campaign)
        self.b_open = self._word("Open",
                                 "Open an annotation campaign: choose its "
                                 "campaign.json.",
                                 self.open_campaign)
        self.b_close = self._word(
            "Close",
            "Close the campaign and take its layers out of the project.\n"
            "No file is touched.", self.close_campaign)
        self.b_classes = self._word(
            "Classes",
            "Classes and colours: add, rename, recolour, retire.",
            self.edit_classes)
        self.b_export = self._word(
            "Export",
            "Write the frames, the polygons, the points and the boxes out in\n"
            "another format: shapefile, GeoJSON, KML, or a table with the\n"
            "geometry written as text. The campaign itself is not touched.",
            self.export_vectors)
        self.b_check = self._word(
            "Check",
            "Look everything over and say what it finds: which QGIS, Qt, GDAL\n"
            "and numpy are running, which formats this GDAL has, and whether\n"
            "the campaign still agrees with itself. Changes nothing, and the\n"
            "report can be copied in one press for a bug report.",
            self.check_everything)
        self.b_measure = self._measure_key("campaign")
        # What is open, right under the name of the block. Then the keys in
        # their rows at every width, so New, Open and Close stand exactly
        # over the correction's own: one row of six at a wide dock put them
        # out of line with the block underneath.
        self.campaign_state = self._quiet(NO_CAMPAIGN)
        box.addWidget(self.campaign_state)
        keys = plain(keypad([[self.b_new, self.b_open, self.b_close],
                             [self.b_classes, self.b_export],
                             [self.b_measure, self.b_check]]))
        box.addWidget(keys)

        # ---- the modules, pressed like tools so you see where you are. The
        # list keeps the order the rest of the program knows them by, 0 to 3,
        # whichever block each one is shown in.
        self.modules = []
        self.module_tips = []
        for label, tip in (
                ("Annotate", "Draw the class areas on the raster."),
                ("Correct",
                 "Correct a thematic map made by any tool, on a copy of it.\n"
                 "Works on the correction open in CORRECTION, and offers to\n"
                 "start or open one when none is. Leaving Correct closes the\n"
                 "correction, and touches no file. No annotation campaign is\n"
                 "needed."),
                ("Objects", "Draw boxes with a class on them, for detection."),
                ("Cutouts",
                 "Cut windows out of the raster layers you choose, on one\n"
                 "pixel grid. Needs no campaign and saves none.")):
            self.module_tips.append(tip)
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setToolTip(tip)
            dress(primary(b), label)
            b.clicked.connect(shielded(
                lambda _=False, i=len(self.modules): self.toggle_module(i),
                label))
            self.modules.append(b)
        pair = plain(bar([[self.modules[0], self.modules[2]]], counts=(1, 2)))
        box.addSpacing(4)
        box.addWidget(pair)
        self._folding(1, card, [self.campaign_state, keys, pair])
        card_campaign = card

        # ---- the correction campaign: a book of its own, with its own
        # buttons. The window that asks for a correction is behind New and
        # Open here, so Correct does not ask again each time it is opened. The
        # correction is open while Correct is: going to another module closes
        # it, its layer leaves the project and its working copy is let go of,
        # as Close here does.
        card, box = self._card(2, "CORRECTION")
        self.c_new = self._word(
            "New", "Start a new correction campaign on a thematic map:\n"
                   "the map, its class band, its classes and a folder.",
            self.new_correction_campaign)
        self.c_open = self._word(
            "Open", "Open a correction campaign: one opened lately, or its\n"
                    "correction.json.", self.open_correction_campaign)
        self.c_close = self._word(
            "Close", "Close the correction and Correct with it, and take its\n"
                     "layer out of the project. No file is touched. Going to\n"
                     "another module does the same.", self.close_correction)
        self.c_classes = self._word(
            "Classes",
            "The value, colour and name of every class of the correction, as\n"
            "they were confirmed when it was made. Values the copy holds\n"
            "cannot be renumbered; names and colours can always change.",
            self.correction_classes)
        self.c_check = self._word(
            "Check",
            "Look the correction over: its manifest, its working copy and its\n"
            "operations.csv, with which QGIS, Qt and GDAL are running.\n"
            "Changes nothing.", self.check_correction)
        self.c_measure = self._measure_key("correction")
        # Six keys in two rows of three: New, Open and Close under the
        # campaign's own, then Classes, Measure and Check. Measure fills the
        # cell that was empty once, and read as a button missing.
        self.correction_state = self._quiet(NO_CORRECTION)
        box.addWidget(self.correction_state)
        keys = plain(keypad([[self.c_new, self.c_open, self.c_close],
                             [self.c_classes, self.c_measure, self.c_check]]))
        box.addWidget(keys)
        one = plain(bar([[self.modules[1]]], counts=(1,)))
        box.addSpacing(4)
        box.addWidget(one)
        self._folding(2, card, [self.correction_state, keys, one])
        card_correction = card

        # ---- cutouts: no campaign at all, and its line says so
        card, box = self._card(3, "CUTOUTS")
        self.cutouts_state = self._quiet(NO_CUTOUTS)
        box.addWidget(self.cutouts_state)
        one = plain(bar([[self.modules[3]]], counts=(1,)))
        box.addWidget(one)
        self._folding(3, card, [self.cutouts_state, one])
        self.say(3, NO_CUTOUTS)
        # and the campaign's line, folded too when Cutouts or Correct is
        # the first module opened: otherwise it stays empty until a campaign
        # has been opened and closed once
        self.describe_campaign()
        card_cutouts = card

        # ---- the module that is open, a card of its own
        self.annotation = None          # the annotation module, when it is open
        self.section = None             # whichever module is open
        self.open_index = None
        self.body = follows_width(QWidget())
        self.annotation_slot = QVBoxLayout(self.body)
        self.annotation_slot.setContentsMargins(0, 0, 0, 0)
        self.annotation_slot.setSpacing(0)
        self.body.setVisible(False)

        # ---- moving about, and where the panel lives: one low row
        #
        # The cross moves the view without changing what you see of the
        # ground, with the way back to the whole raster in its middle; the
        # two zooms beside it change the scale. Then, in a column of their
        # own, how far a step goes, whether the keyboard moves the view too,
        # and the button that takes the panel out of the frame. A block of
        # its own for that one button would be a tall keypad with the step
        # and the keyboard under it and PANEL under that, a third of the
        # height of a panel with nothing open.
        card, box = self._card(5, "VIEW")
        cross = QGridLayout()
        cross.setContentsMargins(0, 0, 0, 0)
        cross.setSpacing(3)
        cross.addWidget(self._arrow("up", 0, 1), 0, 1)
        cross.addWidget(self._arrow("left", -1, 0), 1, 0)
        cross.addWidget(self._nav("fit", "Back to the whole raster.\n\n"
                                         "The middle of the pad is where you "
                                         "came from.",
                                  self.zoom_to_raster), 1, 1)
        cross.addWidget(self._arrow("right", 1, 0), 1, 2)
        cross.addWidget(self._arrow("down", 0, -1), 2, 1)
        cross.addWidget(self._nav("+", "Zoom in.\nKeyboard: PageUp.",
                                  lambda: zoom(True)), 0, 3)
        cross.addWidget(self._nav("−", "Zoom out.\nKeyboard: PageDown.",
                                  lambda: zoom(False)), 2, 3)
        cross.setColumnMinimumWidth(3, NAV_W + 4)
        pad = QWidget()
        pad.setLayout(cross)
        pad.setFixedSize(pad.sizeHint())

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(4)
        # The step's name beside its box, or over it when the dock is too
        # narrow for the pad and the column side by side: a Linux desktop's
        # larger font made the column too wide at two hundred and sixty
        # pixels, and the flow put it under the pad (fit_view).
        row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(QLabel("step"))
        self.step_row = row
        self.step = QSpinBox()
        self.step.setRange(5, 90)
        self.step.setSuffix(" %")
        self.step.setValue(STEP_PERCENT)
        fit_field(self.step, 66)
        # Clicked into and typed in, as it always was, and reached by Tab
        # too. A click anywhere else leaves the arrow keys to the map.
        self.step.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.step.setToolTip(
            "How far one arrow moves the view, as a share of what you see.\n"
            "Shift on the keyboard makes the step %d times longer." % LONG_STEP)
        row.addWidget(self.step)
        row.addStretch(1)
        side.addLayout(row)
        self.keyboard = QCheckBox("keyboard")
        self.keyboard.setChecked(True)
        self.keyboard.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.keyboard.setToolTip(
            "Arrows move the view, Shift and arrows move it further,\n"
            "PageUp and PageDown zoom.")
        side.addWidget(self.keyboard)
        self.b_float = self._word(
            "Detach", "Take the panel out of the QGIS frame, so it floats as a\n"
                      "window you can put anywhere. Press again to dock it back.",
            self.toggle_floating)
        side.addWidget(self.b_float, 0, Qt.AlignmentFlag.AlignLeft)
        column = QWidget()
        column.setLayout(side)
        self.view_pad, self.view_column = pad, column
        self.fit_column()
        # A flow and not a row: a dock narrower than both puts the column
        # under the pad instead of cutting it off.
        flow = FlowLayout(6, 8)
        self.view_flow = flow
        flow.add(pad)
        flow.add(column)
        box.addWidget(plain(flow))
        # What the keyboard does, written where the eye looks for it and not
        # only in a tooltip: the keys are the fastest way to move and the
        # least discoverable. Gone with the keyboard ticked off.
        self.keys_hint = self._quiet(
            "Arrows pan (Shift: %d× further), PgUp/%sPgDn&nbsp;zoom."
            % (LONG_STEP, JOIN))
        self.keyboard.toggled.connect(self.keys_hint.setVisible)
        box.addWidget(self.keys_hint)
        card_view = card

        # The order they are dealt in. The module that is open follows the
        # buttons that opened it, wherever the cards end up.
        self.cards = [card_raster, card_campaign, card_correction,
                      card_cutouts, self.body, card_view]
        self.arrange()

        # Written down, so that a second launch can undo them. Without that
        # the old panel keeps listening from beyond the grave.
        hook(self, QgsProject.instance().layersAdded,
             shielded(self.refresh_rasters, "Layers"))
        hook(self, QgsProject.instance().layersRemoved,
             shielded(self.refresh_rasters, "Layers"))
        hook(self, QgsProject.instance().layersAdded,
             shielded(self.layers_arrived, "Layers"))
        # Every change of map tool, for the one moment that matters: QGIS's
        # vertex tool being put down. See vertex_tool_put_down.
        try:
            hook(self, canvas().mapToolSet,
                 shielded(self.vertex_tool_put_down, "Vertex tool"))
        except Exception as err:
            log("cannot follow the changes of map tool: %s" % err)
        # A buffer emptied by somebody else, without a save: see
        # buffer_let_go. Layers leaving the project are heard here, a rollback
        # on each table as soon as it holds work (see watch).
        try:
            hook(self, QgsProject.instance().layersWillBeRemoved,
                 self.layers_leaving)
        except Exception as err:
            log("cannot follow the layers leaving the project: %s" % err)
        self.describe_correction()
        self.refresh_rasters()

    # ------------------------------------------------------------- shape
    def _card(self, block, title):
        """One block of the panel: a name and what belongs under it.

        The name is the header QGIS's own panels use: a bold word and a
        hairline running to the edge, so the blocks are told apart without
        a frame round each of them. While a module that is not theirs is
        open, the block folds to this one line: the name, what is open in
        it, and a small arrow at the end that unfolds it again."""
        card = follows_width(QWidget())
        box = QVBoxLayout(card)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        head = HeadRow()
        row = QHBoxLayout(head)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._header(title))
        aside = OneLine()
        aside.setObjectName("quiet")
        aside.setVisible(False)
        row.addWidget(aside, 1)
        line = self._rule()
        line.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)
        row.addWidget(line, 1, Qt.AlignmentFlag.AlignVCenter)
        toggle = QToolButton()
        toggle.setObjectName("unfold")
        toggle.setAutoRaise(True)
        toggle.setArrowType(Qt.ArrowType.RightArrow)
        toggle.setFixedSize(20, 18)
        toggle.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        toggle.setVisible(False)
        row.addWidget(toggle)
        head.toggle = toggle
        card.aside, card.line, card.toggle = aside, line, toggle
        card.head, card.title = head, title
        box.addWidget(head)
        return card, box

    def _folding(self, block, card, parts):
        """What a block hides while it is folded: its line, its keys and its
        module buttons. The line moves up beside the name instead, cut to
        the room there is, so what is open stays in sight."""
        self.folds[block] = (card, parts)
        card.toggle.clicked.connect(
            shielded(lambda _=False, b=block: self.unfold(b), "Unfold"))

    def say(self, block, words, tip="", brief=None):
        """What a block holds, in its line and, folded, beside its name.

        Folded, the words its name already says are left out, brief: the
        line beside ANNOTATION CAMPAIGN read 'no annotati…' at 260 pixels,
        the part cut off being the only part that said anything."""
        state = {1: self.campaign_state, 2: self.correction_state,
                 3: self.cutouts_state}[block]
        state.setText(words)
        state.setToolTip(tip)
        card = self.folds[block][0]
        flat = unescape(re.sub(r"<[^>]*>", "", words))
        card.aside.set_text(brief or flat, tip or flat)

    def unfold(self, block):
        if block in self._unfolded:
            self._unfolded.discard(block)
        else:
            self._unfolded.add(block)
        self.fold_blocks()

    def fold_blocks(self):
        """Fold the blocks that do not own the open module to one line."""
        owner = None if self.open_index is None or self.section is None \
            else OWNER[self.open_index]
        if owner is None:
            self._unfolded = set()
        for block, (card, parts) in self.folds.items():
            foreign = owner is not None and owner != block
            folded = foreign and block not in self._unfolded
            for part in parts:
                part.setVisible(not folded)
            card.aside.setVisible(folded)
            card.line.setVisible(not folded)
            card.toggle.setVisible(foreign)
            card.toggle.setArrowType(Qt.ArrowType.RightArrow if folded
                                     else Qt.ArrowType.DownArrow)
            card.toggle.setToolTip(
                "Show this block again. The module stays open." if folded
                else "Fold this block to one line.")
            card.toggle.setAccessibleName(
                ("Unfold %s" if folded else "Fold %s") % card.title.lower())
            card.head.setCursor(Qt.CursorShape.PointingHandCursor if foreign
                                else Qt.CursorShape.ArrowCursor)

    def columns_for(self, width):
        """How many columns the width can hold, one at the very least.

        A column is only worth opening if it can hold a card at a width where
        the card does not have to fold its own words, so the count is the room
        divided by that width."""
        if ONE_COLUMN:
            return 1
        room = int(width) - 20
        return max(1, min(COLUMNS_MAX, room // CARD_MIN))

    def arrange(self, force=False):
        """Deal the cards into columns of the same width.

        Vertical, at the side of the map, that is one column and the cards
        stack in order. Horizontal, along the top, it is two or three columns
        of the same width, and which card goes where is decided once and for
        all rather than by measuring: the module that is open always follows
        the buttons that opened it, and moving about always ends up on the
        right. A panel whose pieces jump around when it is resized is worse
        than one that wastes a little room."""
        wanted = self.columns_for(self.width())
        if wanted == self._columns and not force:
            return
        self._columns = wanted

        for column in self.columns:
            for i in reversed(range(column.count())):
                item = column.itemAt(i)
                if item is not None and item.widget() is not None:
                    column.takeAt(i)
                    item.widget().setParent(None)

        # In one column a card may be as narrow as the dock; in two or more
        # there is room to give every card the width at which it stops folding
        # its own words onto a second line. Moving about is the exception: it
        # holds a handful of small keys and nothing that can fold, so it keeps
        # the narrow floor and leaves what it does not need to the module.
        def floor_for(index):
            if wanted == 1:
                return CARD_W
            return CARD_W if index >= 5 else CARD_MIN

        host = 0
        plan = [list(cards) for cards in PLANS[wanted]]
        if wanted == 1 and self.open_index is not None:
            # The module that is open goes straight under the block that
            # owns it: Annotate and Objects under the annotation campaign,
            # Correct under the correction, Cutouts under its own. After all
            # three, its tools would begin four hundred pixels below the
            # button that opened them.
            owner = OWNER[self.open_index]
            order = [i for i in plan[0] if i != 4]
            order.insert(order.index(owner) + 1, 4)
            plan = [order]
        for column, cards in enumerate(plan):
            for index in cards:
                card = self.cards[index]
                # The shell cards are small and fixed things, and stretching a
                # row of four buttons across half a screen only makes it harder
                # to read. The module that is open is the opposite: it is the
                # work, and it takes all the width the others leave, spreading
                # its own pieces sideways inside it.
                if card is self.body:
                    host = column
                    card.setMaximumWidth(16777215)
                    card.setMinimumWidth(floor_for(index))
                else:
                    # In one column every card takes the whole bar. The cap
                    # exists to stop a row of four buttons being stretched
                    # across half a screen when the panel is dealt sideways;
                    # applied to a bar it does the opposite, leaving the cards
                    # at two hundred and twenty pixels with the checkbox
                    # labels cut off and grey air to their right.
                    card.setMaximumWidth(16777215 if wanted == 1
                                         else COLUMN_MAX)
                    # and never squeezed below the width its own contents
                    # need, however much the module beside it wants
                    card.setMinimumWidth(floor_for(index))
                self.columns[column].insertWidget(
                    self.columns[column].count() - 1, card)

        open_module = self.section is not None
        for i in range(COLUMNS_MAX):
            if i >= wanted:
                self.strip.setStretch(i, 0)
            else:
                self.strip.setStretch(i, 4 if (i == host and open_module) else 1)
        self.collect_spare()
        log("panel laid out as a vertical bar" if ONE_COLUMN else
            "panel in %d column%s" % (wanted, "" if wanted == 1 else "s"))

    def collect_spare(self):
        """Whether the width left over gathers at one side.

        With no module open there is nothing that wants the extra width, so
        the room left over collects on one side instead of being shared out as
        air between cards that cannot use it.

        It has to be decided at every resize and not only when the number of
        columns changes. Widen the panel once and the collector is switched
        on; narrow it again and arrange() returns early, because the column
        count has not changed, so the collector would keep a hundred and
        twenty pixels of a three hundred and sixty pixel bar and every card
        would sit at its minimum with its words cut off."""
        if ONE_COLUMN:
            # One column takes the width there is; there is nothing to collect
            # and the panel does not grow past BAR_MAX anyway.
            self.strip.setStretch(COLUMNS_MAX, 0)
            return
        wanted = max(1, self._columns or 1)
        room = self.width() - 20 - 18 * (wanted - 1)
        spare = 0 if self.section is not None else \
            (1 if room > wanted * COLUMN_MAX else 0)
        self.strip.setStretch(COLUMNS_MAX, spare)

    def resizeEvent(self, ev):
        QWidget.resizeEvent(self, ev)
        self.fit_view()
        self.arrange()
        self.collect_spare()

    def fit_column(self, slack=24):
        """The column beside the pad, as large as what is in it needs, and
        some air beside Detach when there is room for it."""
        column, side = self.view_column, self.view_column.layout()
        side.invalidate()
        column.setMinimumSize(0, 0)
        column.setMaximumSize(16777215, 16777215)
        side.activate()
        column.setFixedSize(side.sizeHint().expandedTo(
            side.minimumSize()).expandedTo(
            QSize(self.b_float.width() + slack, 0)))

    def fit_view(self):
        """The column beside the pad in the first shape that fits there: the
        step's name beside its box with air beside Detach, as it always was;
        then without the air; then the name over the box. A dock too narrow
        for any of them puts the column under the pad, as before.

        Each shape is tried on the column itself and its real width read
        back. Reckoned from the words it comes out a few pixels short of
        what the column then takes: with DejaVu at 300 pixels the shape said
        to fit would not, the flow would put the column under the pad, and
        the panel would have asked for the height of the shape beside it."""
        row = getattr(self, "step_row", None)
        if row is None:
            return
        room = self.width() - 16
        across = QBoxLayout.Direction.LeftToRight
        down = QBoxLayout.Direction.TopToBottom
        shapes = [(across, 24), (across, 0), (down, 24), (down, 0)]
        before = getattr(self, "_view_shape", None)

        def take(shape):
            row.setDirection(shape[0])
            # Four lines in the column instead of three, packed closer, so
            # VIEW stays the low row it is meant to be.
            row.setSpacing(4 if shape[0] == across else 0)
            self.view_column.layout().setSpacing(
                4 if shape[0] == across else 2)
            self.fit_column(shape[1])

        for chosen in shapes:
            take(chosen)
            if self.view_pad.width() + 6 + self.view_column.width() <= room:
                break
        else:
            # none fits: the first, and the flow puts it under the pad
            chosen = shapes[0]
            take(chosen)
        self._view_shape = chosen
        if before != chosen:
            self.view_flow.invalidate()
            self.view_changed_height()

    def view_changed_height(self):
        """Tell every layout between VIEW and the panel that its height has
        changed. The column beside the pad changes shape inside a resize,
        and the layouts above keep the height they worked out for the shape
        before: with DejaVu and Night Mapping at 300 pixels the panel would
        ask for the old height, the dock would give it that, and the chips of
        Correct would be drawn over each other and Detach would fall off the
        bottom."""
        w = self.view_column.parentWidget()
        while w is not None:
            if w.layout() is not None:
                w.layout().invalidate()
            w.updateGeometry()
            if w is self:
                break
            w = w.parentWidget()
        for column in getattr(self, "columns", []):
            column.invalidate()
        strip = getattr(self, "strip", None)
        if strip is not None:
            strip.invalidate()

    # ------------------------------------------------------------- widgets
    def _rule(self):
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setFrameShadow(QFrame.Shadow.Plain)
        f.setProperty("rule", True)
        f.setFixedHeight(1)
        return f

    def _header(self, word):
        """A small name over each block. A handful of them are enough to give
        the eye somewhere to land without turning the panel into a form.

        Allowed to fold: ANNOTATION CAMPAIGN is the longest word on the
        panel, and a name that cannot fold sets the narrowest the whole bar
        can be."""
        label = QLabel(word)
        label.setObjectName("section")
        f = label.font()
        f.setPointSize(max(f.pointSize() - 1, 7))
        label.setFont(f)
        return label

    def _quiet(self, words):
        label = QLabel(words)
        label.setObjectName("quiet")
        label.setWordWrap(True)
        return label

    # ------------------------------------------------------------- floating
    def toggle_floating(self):
        """A dock is already draggable out of the frame. This is the same move
        under a button, because the drag is not obvious to everybody."""
        if self.dock is None:
            return
        if self.dock.isFloating():
            self.dock.setWindowFlags(Qt.WindowType.Widget)
            self.dock.setFloating(False)
            self.dock.show()
            self.b_float.setText("Detach")
            log("panel docked back into the QGIS frame")
        else:
            self.dock.setFloating(True)
            self.as_window()
            # A bar when it floats too: as wide as it was, as tall as the
            # screen will allow. A square window is the one shape this panel
            # has no layout for.
            tall = 900
            try:
                screen = QApplication.primaryScreen().availableGeometry()
                tall = max(600, int(screen.height() * 0.92))
            except Exception:
                pass
            self.dock.resize(min(max(self.dock.width(), 320), BAR_MAX), tall)
            self.b_float.setText("Dock")
            log("panel floating as a window of its own")
        dress(self.b_float, self.b_float.text())

    def as_window(self):
        """Give the floating panel a proper window frame.

        The panel floats as an ordinary tool window and has no "Stay on top"
        tick beside Detach: one fewer thing to read in a card that is three
        words long. Changing the flags hides the widget,
        so it is shown again with the place it had.

        The flag can only be set on a window, so this means nothing while the
        panel is docked, and says so by leaving at once."""
        if self.dock is None or not self.dock.isFloating():
            return
        where = self.dock.geometry()
        self.dock.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowTitleHint |
                                 Qt.WindowType.WindowCloseButtonHint)
        self.dock.setGeometry(where)
        self.dock.show()

    def _button(self, text, slot, width=0):
        b = QPushButton(text)
        if width:
            b.setFixedWidth(width)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(shielded(slot, text))
        return b

    def _word(self, word, tip, slot):
        b = QPushButton()
        # Reached by Tab, never taken by a click: the canvas keeps the
        # keyboard for its arrows, and the panel can still be worked
        # without a mouse.
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setToolTip(tip)
        self.tips[b] = tip
        b.clicked.connect(shielded(slot, word))
        return dress(b, word)

    def _measure_key(self, owner):
        """Measure, a key with a menu behind it: pressed, it opens the list
        of what can be measured on what this block holds. A push button with
        a menu, as QGIS's own Style button is, so it is drawn, greyed and
        reached by Tab like every key beside it, with the style's arrow after
        its word."""
        b = QPushButton()
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setObjectName("measure")
        measure_menu(b, owner, self)
        self.tips[b] = measure_tooltip(owner)
        b.setToolTip(self.tips[b])
        return dress(b, "Measure")

    # ------------------------------------------------------------- measuring
    def correct_hooks(self, section):
        """The hooks of the measuring modules for one Correct, built anew
        for it: none at all until a module registers one (measure.py). A hook
        that cannot be built is left out and said, never let to stop Correct
        from opening."""
        hooks = []
        for make in measure_all(CORRECT_HOOKS):
            try:
                hooks.append(make(section))
            except Exception as err:
                log("a hook of Correct could not be set up: %s" % err)
        return hooks

    def frame_listeners(self):
        """What hears of a frame placed, moved, deleted or imported, once
        the change is committed (measure.FRAME_LISTENERS)."""
        return measure_all(FRAME_LISTENERS)

    def blind_gate(self, readings, what="agreement map", verb="compare"):
        """None when the reading in hand may see these readings, else why
        not and the way out (measure.measure_blind_gate)."""
        return measure_blind_gate(self, readings, what, verb)

    def veil_reports(self, reader=None, one_operator=None, blind=None):
        """Switch off the report layers of the open campaign that show a
        reading hidden from the reader. By default the reader is the one
        the panel holds, under its switches; Annotate passes its own, which
        are the same ones as it is set. Returns how many layers are veiled,
        the ones already off included, so the amber strip can say so."""
        if self.campaign is None:
            return 0
        held = self.reading() or {}
        if reader is None:
            reader = (held.get("operator"), held.get("pass") or 1)
        if one_operator is None:
            one_operator = held.get("by_operator", True)
        if blind is None:
            blind = held.get("blind", True)
        try:
            return veil_report_layers(self.campaign.data.get("id", ""),
                                      reader, bool(one_operator), bool(blind))
        except Exception as err:
            log("cannot switch off the measures hidden from the reader: %s"
                % err)
            return 0

    def layers_arrived(self, *args):
        """A report layer loaded by somebody else, Processing say, is
        veiled as one the panel loads itself."""
        if self.campaign is not None:
            self.veil_reports()

    def _nav(self, word, tip, slot):
        """The navigation keys are the one place where a sign beats a word:
        an arrow is already the name of the thing it does.

        Small and square, the cross and the zooms in one low block beside
        the step: a third of the panel's height went to them before."""
        b = self._word(word, tip, slot)
        if word != "fit":
            # A sign, not a word: larger and in bold, so the plus and the
            # minus are as easy to tell apart as the arrows drawn beside them.
            f = QFont(b.font())
            f.setPointSizeF(f.pointSizeF() * 1.2)
            f.setBold(True)
            b.setFont(f)
        b.setFixedSize(NAV_W, max(NAV_H, b.fontMetrics().height() + 4))
        return b

    def _arrow(self, where, dx, dy):
        b = self._nav({"up": "↑", "down": "↓",
                       "left": "←", "right": "→"}[where],
                      "Move the view %s by one step." % where,
                      lambda: step(dx, dy, self.step_percent()))
        # the sign drawn, and the word kept for whoever reads the button
        # rather than looking at it
        b.setAccessibleName("Move the view %s" % where)
        b.setIcon(arrow_icon(where))
        b.setIconSize(QSize(12, 12))
        b.setText("")
        return b

    def step_percent(self):
        return self.step.value()

    def zoom_to_raster(self):
        """The same move the annotation module offers, available even when no
        module is open: it is the way back when the view has drifted off."""
        if self.annotation is not None:
            self.annotation.zoom_to_raster()
            return
        raster = self.active_raster()
        if raster is None:
            log("no raster selected")
            return
        box = raster.extent()
        view = canvas().mapSettings().destinationCrs()
        if raster.crs() != view:
            box = QgsCoordinateTransform(
                raster.crs(), view, QgsProject.instance()).transformBoundingBox(box)
        canvas().setExtent(box)
        canvas().refresh()
        log("view brought back onto %s" % raster.name())

    def active_raster(self):
        return QgsProject.instance().mapLayer(self.rasters.currentData())

    # ------------------------------------------------------------- state
    def refresh_rasters(self, *args):
        current = self.rasters.currentData()
        self.rasters.blockSignals(True)
        self.rasters.clear()
        # need_crs=False. A photograph, a scan, a frame grab: QGIS gives it a
        # pixel grid and nothing else, and there is no reason annotating one
        # should be harder than annotating an orthomosaic. Asking for a CRS here
        # kept every one of them out of the list, which made the first sentence
        # of the README untrue through the only door a user has.
        available = project_rasters(need_crs=False)
        for l in available:
            self.rasters.addItem(l.name(), l.id())
        if current:
            i = self.rasters.findData(current)
            if i >= 0:
                self.rasters.setCurrentIndex(i)
        self.rasters.blockSignals(False)
        self.describe_raster()
        self.update_enabled()

    def describe_raster(self, *args):
        available = self.rasters.count() > 0
        self.raster_state.setVisible(True)
        if not available:
            how_many = sum(1 for l in QgsProject.instance().mapLayers().values()
                           if isinstance(l, QgsRasterLayer))
            if how_many:
                self.raster_state.setText(
                    "There %s %d raster%s but none carries a usable "
                    "coordinate system. Without one, areas and radii in "
                    "metres would be wrong without showing it."
                    % ("is" if how_many == 1 else "are", how_many,
                       "" if how_many == 1 else "s"))
            else:
                self.raster_state.setText("no raster in the project")
            return
        l = self.active_raster()
        if l is None:
            self.raster_state.setText("")
            self.raster_state.setVisible(False)
            return
        px, py = pixel_on_the_ground(l)
        # Two parts that never break inside: at 260 pixels the line broke
        # after 'EPSG:' and left the number alone under it.
        self.raster_state.setText(
            "pixel&nbsp;%.3f&nbsp;x&nbsp;%.3f&nbsp;m, system&nbsp;%s"
            % (px, py, escape(crs_label(l.crs())).replace(":", ":" + JOIN)))

    def export_vectors(self):
        """Write a copy of the tables out in some other format.

        Saved first, because what goes out has to be what is on the screen: an
        export that quietly misses the last ten minutes of work is worse than
        no export, since nothing about it looks wrong."""
        if self.campaign is None:
            return
        if self.section is not None and self.section.unsaved() \
                or self.pending_layers():
            try:
                if self.section is not None:
                    self.section.save()
            except Exception as err:
                log("could not save before exporting: %s" % err)
            # And checked, because save() reports a failed commit in the message
            # bar and returns normally. An export that quietly misses the last
            # ten minutes is the thing this block exists to prevent, and it was
            # prevented only when the save happened to work.
            left = self.flush_layers()
            if left or self.pending_layers():
                q = QMessageBox.warning(
                    self, NAME,
                    "Not everything could be saved, so what goes out will not "
                    "be what is on the screen:\n\n%s\n\nExport anyway?"
                    % ("\n".join(left) if left else
                       "some work is still waiting to be written."),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if q != QMessageBox.StandardButton.Yes:
                    return
        tile_id = None
        if self.annotation is not None:
            try:
                tile_id = self.annotation.current_tile_id()
            except Exception:
                tile_id = None
        dialog = ExportVectors(self, self.campaign, tile_id)
        if run_dialog(dialog) != QDialog.DialogCode.Accepted:
            return
        recipe = dialog.result()
        card = bool(recipe.get("card"))
        if not recipe["tables"] and not card:
            QMessageBox.information(self, NAME, "Nothing was chosen.")
            return
        if not recipe["folder"]:
            QMessageBox.warning(self, NAME, "Say where to write it.")
            return
        # Work hidden from the reader in hand is asked about once, before
        # anything is written: the tables hold the readings they were asked
        # for, and the card holds the counts of every one.
        shown = []
        if recipe["tables"] and any(t in READING_TABLES
                                    for t in recipe["tables"]):
            shown += (recipe.get("reading") or {}).get("readings") or []
        if card:
            shown += readings_in(self.campaign.package_path)
        hidden = hidden_readings(self, sorted(
            {tuple(r) for r in shown}, key=lambda r: (r[1], r[0])))
        if hidden and not ask_hidden(self, hidden):
            return
        # The same stem the layers are named with, so a table on disk and
        # the layer it came from answer to the same word, and the reading
        # after it when it is not every reading together.
        stem = self.campaign.stem
        if (recipe.get("reading") or {}).get("tag"):
            stem += "_" + recipe["reading"]["tag"]
        written, failed, notes = [], [], []
        if recipe["tables"]:
            try:
                written, failed, notes = write_vectors(
                    self.campaign.package_path, recipe, stem)
            except OSError as err:
                QMessageBox.critical(self, NAME,
                                     "Nothing could be written:\n\n%s" % err)
                return
            if not written:
                QMessageBox.warning(self, NAME,
                                    "Nothing was written. The log says why.")
                return
        # The card after the vectors, so it can give each file its SHA-256.
        carded, card_said = [], ""
        if card:
            carded, card_said, _ = write_card_beside(
                self, recipe["folder"], self.campaign.stem,
                exports=[{"path": f, "role": "vectors",
                          "reading": recipe.get("reading")} for f in written])
        # Everything this export wrote in one archive, last, so it holds
        # the card too. The files stay where they are.
        packed, pack_said = None, ""
        if recipe.get("zip") and (written or carded):
            try:
                packed, inside = pack_zip(recipe["folder"], written + carded,
                                          zip_name(stem))
                pack_said = "%s holds %d file%s." % (
                    os.path.basename(packed), inside,
                    "" if inside == 1 else "s")
            except OSError as err:
                log("could not pack the export: %s" % err, loud=True)
                pack_said = "The .zip could not be written: %s" % err
        count = len(written) + len(carded) + (1 if packed else 0)
        message = "%d file%s written in\n%s" % (
            count, "" if count == 1 else "s", recipe["folder"])
        if failed:
            message += "\n\n%s could not be written in this format." \
                       % ", ".join(failed)
        if notes:
            message += ("\n\nRead back, not everything came out as it is in "
                        "the campaign:\n- " + "\n- ".join(notes))
        if card_said:
            message += "\n\n" + card_said
        if pack_said:
            message += "\n\n" + pack_said
        if not written and not carded:
            QMessageBox.warning(self, NAME, message)
            return
        QMessageBox.information(self, NAME, message)
        log("exported %s" % ", ".join(os.path.basename(f)
                                      for f in written + carded))
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(recipe["folder"]))
        except Exception:
            pass

    # ------------------------------------------------------- the reading
    # Who is drawing, in which pass, and whether the earlier passes are
    # hidden. The Annotate module cannot hold it: it is built anew every
    # time it is opened and thrown away when it is closed, and it would start
    # from the campaign's creator, pass 1, every time. A blind second reader
    # who looked at Objects, or closed Annotate and opened it again, would
    # become the first reader without a word: their strokes would be filed as
    # the first reading and cut its polygons, and Objects would stamp every
    # box with the creator and pass 1 whoever drew it. The panel lives as
    # long as QGIS does, so it holds the reading for the session, and
    # remembers it campaign by campaign for the next one.
    def creator(self):
        """The name the campaign was made with, in its written form."""
        if self.campaign is None:
            return AnnotationSection.OPERATOR_BLANK
        return AnnotationSection.tidy_operator(
            self.campaign.data.get("operator")) or "OPERATOR 1"

    def reading(self):
        """The reading in hand for the open campaign, as {"operator",
        "pass", "blind", "by_operator"}, or None with no campaign open."""
        if self.campaign is None:
            return None
        held = getattr(self, "_reading", None)
        if held is None or held.get("campaign") != \
                self.campaign.data.get("id", ""):
            held = self.restore_reading()
        return held

    def restore_reading(self):
        """The reading last used on this campaign on this machine, or the
        creator in pass 1 for a campaign nobody has drawn in here yet.

        A remembered reading that is not the creator's first pass, taken up
        by a session that has not drawn as that person yet, is asked about
        before the first stroke (reading_settled): it may be what somebody
        else was doing yesterday on this machine."""
        cid = self.campaign.data.get("id", "")
        # the first reading of a campaign; a name, not a bare number beside
        # the key "pass", which a source scanner reads as a password
        first = 1
        held = {"campaign": cid, "operator": self.creator(), "pass": first,
                "blind": True, "by_operator": True}
        stored = {}
        if cid:
            try:
                stored = json.loads(read_setting(READING_KEY + cid, "")
                                    or "{}")
            except (TypeError, ValueError):
                stored = {}
        if isinstance(stored, dict):
            who = AnnotationSection.tidy_operator(stored.get("operator"))
            if who:
                held["operator"] = who
            try:
                p = int(stored.get("pass") or 1)
            except (TypeError, ValueError):
                p = 1
            held["pass"] = min(max(p, 1), 9)
            for key in ("blind", "by_operator"):
                if isinstance(stored.get(key), bool):
                    held[key] = stored[key]
        self._reading = held
        several = self.several_readers()
        self._reading_check = bool(several and
                                   held["operator"] != SESSION["operator"])
        if several:
            log("reading in hand: %s%s"
                % (self.reading_words(held),
                   ", to be confirmed before the first stroke"
                   if self._reading_check else ""))
        return held

    def several_readers(self):
        """Whether this campaign is read by more than one person or in more
        than one pass. A campaign with only its creator in pass 1 is never
        asked about anything."""
        held = getattr(self, "_reading", None)
        if self.campaign is None or held is None:
            return False
        creator = self.creator()
        names = {AnnotationSection.tidy_operator(w)
                 for w in (self.campaign.data.get("operators") or [])}
        names.discard("")
        names.add(creator)
        return bool(held["operator"] != creator or held["pass"] != 1
                    or len(names) > 1)

    def reading_words(self, reading=None):
        """'BRUNO, pass 2, blind': the reading as the panel says it."""
        r = reading or self.reading() or {}
        p = int(r.get("pass") or 1)
        return "%s, pass %d%s" % (
            r.get("operator") or AnnotationSection.OPERATOR_BLANK, p,
            ", blind" if r.get("blind") else "")

    def passes_for(self, operator):
        """The passes that exist for an operator of the open campaign: the
        manifest's list, the passes in the tables, and the one in hand if it
        is this operator's (campaign.passes_of)."""
        if self.campaign is None:
            return [1]
        held = self.reading() or {}
        who = AnnotationSection.tidy_operator(operator) \
            or AnnotationSection.OPERATOR_BLANK
        found = passes_found(self.campaign.data.get("id", "")).get(who, ())
        mine = [held.get("pass") or 1] if held.get("operator") == who else []
        return passes_of(self.campaign.data, who, found, mine)

    def register_pass(self, operator, number):
        """Write a pass into the campaign's list for an operator, so it is
        there tomorrow and on any machine that opens the folder. True when it
        was written; a manifest that cannot be written is said and the pass
        is still usable for the session."""
        if self.campaign is None:
            return False
        who = AnnotationSection.tidy_operator(operator)
        if not who or not write_pass(self.campaign.data, who, number):
            return False
        try:
            self.campaign.save()
        except Exception as err:
            QMessageBox.warning(
                self, NAME,
                "The pass could not be written into the campaign:\n\n%s\n\n"
                "You can still use it now, but it will not be there next "
                "time." % err)
            log("cannot write the pass into the manifest: %s" % err)
            return False
        return True

    def hold_reading(self, operator=None, pass_no=None, blind=None,
                     by_operator=None):
        """Take a change of reading from whoever made it, keep it for the
        session and write it down for the campaign."""
        held = self.reading()
        if held is None:
            return
        before = (held["operator"], held["pass"], held["blind"])
        if operator is not None:
            held["operator"] = AnnotationSection.tidy_operator(operator) \
                or AnnotationSection.OPERATOR_BLANK
        if pass_no is not None:
            held["pass"] = min(max(int(pass_no), 1), 9)
        if blind is not None:
            held["blind"] = bool(blind)
        if by_operator is not None:
            held["by_operator"] = bool(by_operator)
        SESSION["operator"] = held["operator"]
        self._reading_check = False
        if held["campaign"]:
            write_setting(READING_KEY + held["campaign"], json.dumps(
                {"operator": held["operator"], "pass": held["pass"],
                 "blind": held["blind"],
                 "by_operator": held["by_operator"]}))
        if (held["operator"], held["pass"], held["blind"]) != before:
            log("reading in hand: %s" % self.reading_words(held))

    def keep_reading(self, section):
        """What an Annotate module about to close was set to, kept. Its own
        signals already said so; this catches a name typed into the box and
        never confirmed with Enter."""
        try:
            self.hold_reading(section.operator_name(),
                              int(section.pass_no.value()),
                              section.blind.isChecked(),
                              section.by_operator.isChecked())
        except Exception as err:
            log("cannot keep the reading of the module: %s" % err)

    def reading_settled(self):
        """True when it is clear who is drawing. A remembered reading that is
        not this session's is shown and confirmed first; a campaign with only
        its creator in pass 1 goes straight through."""
        if self.campaign is None:
            return True
        self.reading()
        if not getattr(self, "_reading_check", False):
            return True
        chosen = self.ask_reading(
            "This campaign was last drawn on this computer as %s.\n\nEvery "
            "mark you draw is filed under the reading below and kept apart "
            "from the others. Check that it is yours before the first stroke."
            % self.reading_words())
        if chosen is None:
            log("the module was not opened: who is drawing was not confirmed")
            return False
        self.hold_reading(**chosen)
        return True

    def ask_reading(self, why):
        """The window that says who is drawing, filled with the reading in
        hand: {"operator", "pass_no", "blind"} on OK, None on Cancel."""
        held = self.reading()
        names = [AnnotationSection.tidy_operator(w)
                 for w in (self.campaign.data.get("operators") or [])]
        names += [self.creator(), held["operator"], SESSION["operator"]]
        d = WhoIsDrawing(self, why, [w for w in names if w], held,
                         self.passes_for)
        if not run_dialog(d):
            return None
        chosen = d.chosen()
        # a pass made with the + of the window is the campaign's from now on
        self.register_pass(chosen["operator"], chosen["pass_no"])
        return chosen

    def change_reading(self):
        """Who is drawing, changed from Objects, which has no box of its own
        for it. True when it changed."""
        if self.campaign is None:
            return False
        chosen = self.ask_reading(
            "Every box you draw is filed under this reading. The boxes of "
            "the other readings stay as they are.")
        if chosen is None:
            return False
        self.hold_reading(**chosen)
        return True

    def who_is_drawing(self):
        """The operator every table has to be stamped with.

        There has to be one answer. If the polygons took the name from the
        panel, tidied and upper cased, and the points and the boxes took the
        raw string the manifest was created with, months earlier, whatever its
        case, a filter written for one would return nothing on the other, and
        a second operator's points would be filed under the first one's name
        without anything looking wrong. So: the box in Annotate while it is
        open, the reading the panel holds otherwise."""
        if self.annotation is not None:
            try:
                return self.annotation.operator_name()
            except Exception:
                pass
        held = self.reading()
        if held is None:
            return AnnotationSection.OPERATOR_BLANK
        return held["operator"] or AnnotationSection.OPERATOR_BLANK

    def operator_said(self, correction_id):
        """The name typed in the window that made this correction, in this
        QGIS session, or None. Kept in memory only, so a later session is
        the reading's to say (CorrectionSection.operator_name), and only
        while the reading of the session is the one it was when the name was
        typed: somebody who picks another since has meant to take over."""
        name, held = ((SESSION.get("said") or {}).get(correction_id)
                      or (None, None))
        return name if name and SESSION["operator"] == held else None

    def operator_in_hand(self):
        """The operator somebody picked in this QGIS session, in the box of
        Annotate or in the window that asks who is drawing (hold_reading),
        or None when nobody did. Correct files its strokes under it: with
        only the operator a correction was made with, every row of its
        operations.csv would go to them whoever held the brush."""
        return SESSION["operator"] or None

    def which_pass(self):
        """The pass every table has to be stamped with.

        It has to reach the points and the boxes as well as the polygons.
        Otherwise a second, independent reading duplicates every point and
        every box into every export with nothing to tell the two readings
        apart, which is the very number the second reading exists to produce.
        And it is not 1 when Annotate is closed, or the boxes of a second pass
        would be filed under the first."""
        if self.annotation is not None:
            try:
                return int(self.annotation.pass_no.value())
            except Exception:
                pass
        held = self.reading()
        return held["pass"] if held is not None else 1

    def allow(self, button, on, why):
        """The button on, with what it does in its tooltip, or grey, with why
        in front of that: what is missing and where to get it."""
        button.setEnabled(on)
        tip = self.tips.get(button, "")
        button.setToolTip(tip if on else why + ("\n\n" + tip if tip else ""))

    def update_enabled(self):
        has_raster = self.rasters.count() > 0
        open_campaign = self.campaign is not None
        open_correction = self.correction is not None
        idle = not open_campaign and not open_correction \
            and getattr(self, "section", None) is None
        self.hint.setVisible(idle)
        self.hint.setText(
            "Next: <b>New</b> or <b>Open</b> an annotation campaign to "
            "draw classes, or go straight to <b>Correct</b> or "
            "<b>Cutouts</b>." if has_raster else
            "Load a raster to begin: <b>Layer &gt; Add Layer &gt; Add "
            "Raster Layer</b>, or drag the file onto the map. <b>Open</b> "
            "works without one.")
        self.rasters.setEnabled(has_raster)
        self.rasters.setToolTip(
            "The raster everything is measured on." if has_raster
            else LOAD_RASTER)
        one_campaign = ("One annotation campaign at a time: Close the one "
                        "that is open first.")
        no_campaign = ("No annotation campaign is open: press New or Open in "
                       "ANNOTATION CAMPAIGN.")
        self.allow(self.b_new, has_raster and not open_campaign,
                   one_campaign if open_campaign else LOAD_RASTER +
                   "\nOpen needs none: it opens a campaign already made.")
        self.allow(self.b_open, not open_campaign, one_campaign)
        for b in (self.b_close, self.b_classes, self.b_export):
            self.allow(b, open_campaign, no_campaign)
        # Measure reads what the campaign holds: grey until one is open,
        # saying so, like every key here that needs it.
        self.tips[self.b_measure] = measure_tooltip("campaign")
        self.allow(self.b_measure, open_campaign, no_campaign)
        self.allow(self.b_check, True, "")
        # The correction's own buttons, on the same rule as the campaign's:
        # one correction at a time, so New and Open wait for it to close.
        # Open needs no raster on the map, a correction carries its own copy.
        one_correction = ("One correction at a time: Close the one that is "
                          "open first,\nor go to another module, which "
                          "closes it.")
        no_correction = (
            "No correction is open: press New or Open here, or Correct."
            if has_raster else
            "No correction is open: press Open here for one already made,\n"
            "which brings its own copy of the map. New and Correct need the\n"
            "map to correct loaded first.")
        load_map = (LOAD_RASTER + "\nThe raster for %s is the thematic map "
                    "to correct. Open needs none:\na correction already made "
                    "brings its own copy.")
        self.allow(self.c_new, has_raster and not open_correction,
                   one_correction if open_correction else load_map % "New")
        self.allow(self.c_open, not open_correction, one_correction)
        self.tips[self.c_measure] = measure_tooltip("correction")
        for b in (self.c_close, self.c_classes, self.c_measure, self.c_check):
            self.allow(b, open_correction, no_correction)
        # Annotate and Objects draw into the annotation campaign and need one.
        # Correct keeps a campaign of its own and Cutouts keeps none, so they
        # need only a raster to work on. Tying all four to the annotation
        # campaign would make the two free tools unreachable until a campaign
        # nobody wanted had been made.
        for i, b in enumerate(self.modules):
            self.tips[b] = self.module_tips[i]
            if i in (0, 2):
                why = ("%s works inside an annotation campaign: press New or "
                       "Open in\nANNOTATION CAMPAIGN." % b.text())
                if not has_raster:
                    why = ("%s works inside an annotation campaign, which "
                           "New makes on a raster.\n%s\nThen press New in "
                           "ANNOTATION CAMPAIGN, or Open there for a\n"
                           "campaign already made."
                           % (b.text(), LOAD_RASTER))
                self.allow(b, open_campaign, why)
            elif i == 1:
                # Open, Correct is what holds the correction, whatever else
                # is loaded: it brings its own map.
                self.allow(b, has_raster or open_correction,
                           load_map % "Correct")
            else:
                self.allow(b, has_raster,
                           LOAD_RASTER + "\nCutouts cuts windows out of the "
                           "raster layers of the project.")

    def describe_campaign(self):
        """Two lines: the folder is long and belongs in the tooltip."""
        if self.campaign is None:
            self.say(1, NO_CAMPAIGN,
                     "Annotate and Objects draw into an annotation campaign:\n"
                     "press New or Open.", brief=NONE_OPEN)
            return
        # Read with defaults throughout. open_campaign opens a window about
        # a manifest that does not agree with the disk and then calls this,
        # which read the grid with a bare subscript: the warning was followed
        # one line later by a traceback about the very thing it described.
        d = self.campaign.data or {}
        g = d.get("grid") or {}
        if not isinstance(g, dict):
            g = {}
        pixel = g.get("pixel_m") or []
        count = len(self.campaign.active_classes())
        self.say(1, "<b>%s</b> &middot; %s &middot; %d class%s"
                 % (d.get("name", "unnamed"),
                    "tiled" if d.get("with_tiles") else "free", count,
                    "" if count == 1 else "es"),
                 "%s\npixel %s, %s\noperator %s"
                 % (self.campaign.folder,
                    ("%.3f m" % pixel[0]) if pixel else "unknown",
                    crs_label(crs_from_text(g.get("crs"))),
                    d.get("operator", "?")),
                 brief="%s · %d class%s" % (d.get("name", "unnamed"), count,
                                            "" if count == 1 else "es"))

    def describe_correction(self):
        """The line under CORRECTION, in the words of the campaign line:
        what it is called and how many classes it has, with where it lives
        and what it corrects in the tooltip."""
        book = self.correction
        if book is None:
            self.say(2, NO_CORRECTION,
                     "A correction keeps a campaign of its own, made on a "
                     "thematic\nmap by any program: press New or Open, or "
                     "Correct. It is\nopen while Correct is.",
                     brief=NONE_OPEN)
            return
        d = book.data or {}
        classes = d.get("classes") or []
        # and what a measuring module has to add about it, a line each
        extra = []
        for line_of in measure_all(CORRECTION_TOOLTIP_LINES):
            try:
                line = line_of(book)
            except Exception as err:
                log("a line of the correction's tooltip failed: %s" % err)
                line = ""
            if line:
                extra.append(str(line))
        self.say(2, "correction <b>%s</b> &middot; %d class%s"
                 % (escape(str(d.get("name", "unnamed"))), len(classes),
                    "" if len(classes) == 1 else "es"),
                 "%s\non a copy of %s\noperator %s%s"
                 % (book.folder, os.path.basename(str(d.get("source") or "?")),
                    d.get("operator") or "?",
                    "".join("\n" + line for line in extra)),
                 brief="%s · %d class%s" % (
                     d.get("name", "unnamed"), len(classes),
                     "" if len(classes) == 1 else "es"))

    # ------------------------------------------------------------- actions
    def new_campaign(self):
        # Same here, and for the same reason: the New dialog already knows what
        # to do with a raster that has no coordinate system, down to saying so
        # and proposing to work free of frames. It was never reached.
        rasters = project_rasters(need_crs=False)
        if not rasters:
            QMessageBox.warning(
                self, NAME,
                "Load a raster first.\n\nAny raster QGIS can open will do, "
                "georeferenced or not.")
            return
        hand = proposed_raster(rasters, self.rasters.currentData())
        d = NewCampaign(self, rasters, hand.id() if hand is not None else None)
        if not run_dialog(d):
            return
        try:
            if d.overwrite:
                moved = set_aside(d.folder.text().strip())
                if moved:
                    log("previous campaign set aside as: %s" % ", ".join(moved))
            self.campaign = Campaign.create(
                d.folder.text().strip(), d.name.text().strip() or "campaign",
                d.tiled.isChecked(), d.chosen_raster(), d.classes,
                d.operator.text().strip().upper() or "OPERATOR 1")
        except Exception as err:
            QMessageBox.critical(self, NAME, "Cannot create the campaign:\n%s" % err)
            return
        log("campaign created in %s" % self.campaign.folder)
        self.open_the_net()
        self.load_layers()
        self.describe_campaign()
        self.update_enabled()
        self.campaign_changed()

    def open_campaign(self):
        # A folder chooser hides files, so the campaign folder looks empty even
        # when it is not. Pick the manifest itself: it is what a campaign is.
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Open a campaign: choose its %s" % Campaign.MANIFEST, "",
            "%s campaign (%s);;All files (*)" % (NAME, Campaign.MANIFEST))
        if not chosen:
            return
        folder = os.path.dirname(chosen)
        if os.path.basename(chosen) != Campaign.MANIFEST:
            if not os.path.exists(os.path.join(folder, Campaign.MANIFEST)):
                QMessageBox.warning(
                    self, NAME,
                    "That is not a campaign.\n\nA campaign is a folder holding a "
                    "%s: choose that file." % Campaign.MANIFEST)
                return
        try:
            self.campaign = Campaign.open(folder)
        except Exception as err:
            QMessageBox.critical(self, NAME, "Unreadable manifest:\n%s" % err)
            return
        trouble = self.campaign.reconcile()
        if trouble:
            QMessageBox.warning(self, NAME,
                                "The campaign opens, but manifest and disk do not "
                                "agree:\n\n- " + "\n- ".join(trouble))
            for t in trouble:
                log("disagreement: " + t.replace("\n", " "))
        self.open_the_net()
        self.load_layers()
        self.describe_campaign()
        self.update_enabled()
        log("campaign '%s' open" % self.campaign.data["name"])
        # Who drew here last time, said in the log of this opening, and
        # confirmed when Annotate or Objects is first opened if it has to be.
        self.restore_reading()
        self.campaign_changed()
        # Only now, with the layers in the project, is there anywhere to put
        # recovered work back into.
        self.offer_recovery()

    # --------------------------------------------------------------- the net
    def open_the_net(self):
        """Start the log file and the recovery snapshots for this campaign.

        Both live beside the manifest, which is the only folder this program can
        be sure it may write into, and the only one a user will think to look in.
        """
        if self.campaign is None:
            return
        self.route_log()
        self.recovery = Recovery(self.campaign.folder,
                                 self.campaign.data.get("id", ""))
        log("recovery snapshots will be written to %s" % self.recovery.folder)

    def route_log(self):
        """Point the log file at the work that is open.

        The log is one file at a time. Beside the correction while Correct is
        open, because that is the folder somebody looking for what Correct did
        will open; beside the annotation campaign otherwise; in the folder
        of the program, in the home, while Cutouts is open with no campaign,
        which has no log of its own (never in the cutouts folder: it is
        a dataset); nowhere when none of them is open. Only once the cutouts
        folder exists: opening the module writes nothing. Every switch
        is said in both files, so a reader of either knows where the rest
        went."""
        cutouts = getattr(self.section, "folder", None) \
            if isinstance(self.section, CutoutsSection) else None
        if self.correction is not None:
            folder = self.correction.folder
            what = "beside the correction '%s'" % self.correction.data.get(
                "name", "")
        elif self.campaign is not None:
            folder = self.campaign.folder
            what = "beside the campaign '%s'" % self.campaign.data.get(
                "name", "")
        elif cutouts and os.path.isdir(cutouts):
            # The cutouts folder is a dataset: it is zipped, published and
            # cited, and a log in it goes with it. The log of a session with
            # no campaign is kept in the folder of the program, in the home.
            folder = os.path.join(os.path.expanduser("~"), NAME)
            try:
                os.makedirs(folder, exist_ok=True)
            except OSError as err:
                log("the log has no folder of its own to go in: %s" % err)
                folder = None
            what = ("into the folder of the program (the cutouts folder "
                    "'%s' is a dataset and holds none)"
                    % os.path.basename(os.path.normpath(cutouts)))
        else:
            folder, what = None, None
        if folder == self._log_folder:
            return
        if folder is None:
            log("the log file is closed: no campaign, no correction and no "
                "cutouts folder is open")
            log_to(None)
        else:
            if self._log_folder is not None:
                log("the log now goes %s: %s" % (what, folder))
            log_to(folder)
            log("the log now goes %s: %s" % (what, folder))
        self._log_folder = folder

    def campaign_changed(self):
        """An annotation campaign was opened or closed. Cutouts reads it, for
        its frames and its drawing, so an open Cutouts is built again; Correct
        does not, and is left as it is."""
        if self.open_index == 3:
            self.reopen_module(3)

    def reopen_module(self, index):
        self.close_module()
        self.toggle_module(index)

    def keep_safe(self):
        """Write down what is drawn but not yet committed.

        Called after every stroke. It is cheap because what is pending is
        bounded by the autosave threshold, and when nothing is pending it removes
        the file rather than leaving a stale one to frighten somebody at the next
        open.
        """
        if self.recovery is None or self.campaign is None:
            return
        try:
            pending = self.pending_layers()
            self.recovery.note(pending)
        except Exception as err:
            log("the recovery snapshot failed: %s" % err)
            return
        try:
            for _, lyr in pending:
                self.watch(lyr)
        except Exception as err:
            log("cannot follow the edits of a table: %s" % err)

    def watch(self, lyr):
        """Hear it when this table's buffer is rolled back. Once per table,
        from the first time it holds work the net writes down."""
        # The table itself, not its id: a project read again brings a table
        # with the same id that is another object, and nobody listens to that
        # one yet. Held here, so that asking the project for it hands back this
        # very object.
        watched = self.__dict__.setdefault("_watched", {})
        try:
            lid = lyr.id()
            if watched.get(lid) is lyr:
                return
            watched[lid] = lyr
            hook(self, lyr.beforeRollBack,
                 lambda lyr=lyr: self.buffer_let_go(
                     [lyr], "its edits were discarded, as QGIS does when it "
                     "asks whether to save them and is told Discard"))
            # A save that is not ours, QGIS's own Save Layer Edits, empties
            # the buffer all the same: the net has to hear of it, or it keeps
            # strokes that are already in the package and a crash then draws
            # them a second time.
            hook(self, lyr.afterCommitChanges,
                 shielded(lambda *a: self.keep_safe(), "Recovery"))
        except Exception as err:
            log("cannot follow the edits of a table: %s" % err)

    def layers_leaving(self, leaving=None, *rest):
        """Layers are about to leave the project: closing QGIS, closing the
        project, Remove Layer. QGIS throws away the edit buffer of a layer it
        removes, so a table still holding work is the net's to keep."""
        if by_own_hands() or self.campaign is None:
            return
        try:
            if leaving is None or isinstance(leaving, str) \
                    or not hasattr(leaving, "__iter__"):
                leaving = [leaving]
            ids = set()
            for x in leaving:
                if x is not None:
                    ids.add(x if isinstance(x, str) else x.id())
            going = [lyr for _, lyr in self.pending_layers() if lyr.id() in ids]
        except Exception as err:
            log("cannot tell which layers are leaving: %s" % err)
            return
        if going:
            self.buffer_let_go(going, "taken out of the project with its "
                               "edits in it, as QGIS does when it closes the "
                               "project")

    def buffer_let_go(self, layers, how):
        """Work that was never saved is being thrown away by somebody else.

        On the way out QGIS asks, for every table with edits, whether to save
        them, and only after that unloads the plugins: by the time this
        program closes its module and looks at the buffers, a Discard has
        emptied them, or the project has gone with them. Seeing nothing
        pending, the net would delete its file, which is the one copy of
        that work left anywhere, and the log would say nothing was lost.

        So the moment a buffer is emptied without a save, its work is written
        down one last time and that file is set aside, to be offered at the
        next Open campaign, where it may be declined. Rolling back or removing
        on purpose, which this program does when it is asked to close without
        saving, is done under own_hands and is not this."""
        if by_own_hands() or self.recovery is None or self.campaign is None:
            return
        try:
            ids = set(lyr.id() for lyr in layers)
            pending = self.pending_layers()
            going = [(r, l) for r, l in pending if l.id() in ids]
            if not going:
                return
            rest = [(r, l) for r, l in pending if l.id() not in ids]
            self.recovery.note(going)
            kept = self.recovery.set_aside(how)
            # The tables still being worked on go on with a net of their own.
            self.recovery.note(rest)
        except Exception as err:
            log("the work being let go of could not be kept: %s" % err,
                loud=True)
            return
        if kept:
            log("%s, never saved: %s. It is kept in %s, and the next Open "
                "campaign offers it back." % (
                    ", ".join(r for r, _ in going), how, kept), loud=True)

    def offer_recovery(self):
        """Work from a session that ended without saving, offered back.

        A snapshot still on disk can only mean one thing: the run that wrote it
        never got as far as a save. Asking is the whole of the mechanism, because
        the alternative, putting the features back silently, would mean a crash in
        the middle of something the user had decided to abandon comes back to life
        without being asked for.
        """
        if self.campaign is None:
            return
        mine = self.recovery.session if self.recovery is not None else ""
        left = snapshots_waiting(self.campaign.folder, mine,
                                 self.campaign.data.get("id", ""))
        if not left:
            return
        # What was drawn and when, in words: the build it was drawn with is
        # for the log, where it is written, and means nothing to the person
        # deciding.
        what = "\n".join("- " + describe_snapshot(head, rows).rsplit(
            ", build ", 1)[0] for _, head, rows in left)
        for _, head, rows in left:
            log("recovery offered: %s" % describe_snapshot(head, rows))
        let_go = [head.get("let_go") for _, head, _ in left
                  if head.get("let_go")]
        if let_go:
            why = "QGIS let go of them before they were saved: %s." % let_go[0]
        else:
            why = ("That session ended without a save, which usually means "
                   "QGIS closed unexpectedly.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("%s: unsaved work found" % NAME)
        box.setText("Work from an earlier session was never saved:\n%s" % what)
        box.setInformativeText(
            "%s\n\nPut them back? Not now leaves them where they are, and "
            "you are asked again the next time the campaign is opened. "
            "Discard does not ask again, and still deletes nothing: the file "
            "stays on disk, renamed with .discarded on the end, as plain text "
            "that can be read." % why)
        back = box.addButton("Put them back", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
        drop = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(back)
        run_dialog(box)     # one place in the program knows how Qt spells exec
        # "Not now" must not rename the file: a renamed file is never offered
        # again, so the button would say later and mean never, and Check
        # would go on saying everything was on disk. Only Discard retires a
        # file, and closing the window is the same as Not now.
        if box.clickedButton() is drop:
            for path, _, _ in left:
                kept = keep_snapshot(path, DISCARDED_SUFFIX)
                log("recovery discarded; the file is kept as %s" % kept,
                    loud=True)
            return
        if box.clickedButton() is not back:
            log("recovery not now: %s left as %s, offered again at the next "
                "open" % ("the file is" if len(left) == 1 else
                          "%d files are" % len(left),
                          ", ".join(p for p, _, _ in left)))
            return
        put, failed, stuck = 0, [], []
        for path, _, rows in left:
            done, bad = self.put_back(rows)
            put += done
            failed.extend(bad)
            if keep_snapshot(path) is None:
                # It could not be renamed, so it is still armed and the next
                # open will offer the same work again. Putting it back twice is
                # how a restore turns into a duplicate, so this has to be said.
                stuck.append(path)
        trouble_left = self.flush_layers()
        if trouble_left:
            QMessageBox.warning(
                self, NAME,
                "%d thing%s put back, but they are not on disk yet:\n\n%s\n\n"
                "Press Save." % (put, "" if put == 1 else "s",
                                 "\n".join(trouble_left)))
        else:
            QMessageBox.information(
                self, NAME,
                "%d thing%s put back and saved.%s%s"
                % (put, "" if put == 1 else "s",
                   "\n\n%d could not be read and were left in the file."
                   % len(failed) if failed else "",
                   "\n\n%d recovery file%s could not be renamed, so you will "
                   "be asked about the same work again at the next open. Move "
                   "or delete %s by hand:\n%s"
                   % (len(stuck), "" if len(stuck) == 1 else "s",
                      "it" if len(stuck) == 1 else "them",
                      "\n".join(stuck)) if stuck else ""))
        log("recovery: %d features restored, %d refused" % (put, len(failed)))
        if self.section is not None and hasattr(self.section, "refresh_coverage"):
            try:
                self.section.refresh_coverage()
            except Exception:
                pass

    def put_back(self, rows):
        """Replay the snapshot into the layers. Returns (done, refused).

        In the order the session made them, which is not the order they are
        written: removals first, then the changes to what was already there,
        then the new marks. Putting the new marks down first and the removals
        afterwards would be the same set of operations and a different result,
        because a removal names a feature by the id it had on disk and a new mark
        can be given that id in between.
        """
        order = {"deleted": 0, "attrs": 1, "moved": 2, "added": 3}
        rows = sorted(rows, key=lambda r: order.get(r.get("what"), 3))
        done, refused, skipped = 0, [], 0
        for row in rows:
            role = row.get("role")
            lyr = find_mine(self.campaign.data["id"], role)
            if lyr is None:
                refused.append(row)
                continue
            if not lyr.isEditable():
                lyr.startEditing()

            what = row.get("what")
            if what in ("deleted", "attrs") and not self.still_there(
                    lyr, row.get("fid")):
                # Already gone is the right answer, not a failure: the feature
                # may have been removed by a save that did reach the disk, the
                # crash coming after the removals of a commit and before its
                # additions. Deleting it again would be taken by the buffer,
                # and the commit would then refuse the whole table,
                # "1 feature(s) not deleted", at every save from then on.
                skipped += 1
                continue
            if what == "deleted":
                fid = row.get("fid")
                try:
                    if lyr.deleteFeature(int(fid)):
                        done += 1
                except Exception:
                    refused.append(row)
                continue

            if what == "attrs":
                fid = row.get("fid")
                wrote = 0
                for key, value in (row.get("fields") or {}).items():
                    at = lyr.fields().indexOf(key)
                    if at < 0:
                        continue
                    try:
                        if lyr.changeAttributeValue(int(fid), at, value):
                            wrote += 1
                    except Exception:
                        pass
                if wrote:
                    done += 1
                else:
                    refused.append(row)
                continue

            geom = QgsGeometry.fromWkt(row.get("wkt") or "")
            if geom is None or geom.isNull() or geom.isEmpty():
                refused.append(row)
                continue
            if what == "moved":
                # A moved vertex is put back only if the feature it belonged to
                # is still there. Guessing which one it was would be worse than
                # leaving the edit out.
                fid = row.get("fid")
                try:
                    f = lyr.getFeature(int(fid))
                except Exception:
                    f = None
                if f is None or not f.isValid():
                    refused.append(row)
                    continue
                if lyr.changeGeometry(int(fid), geom):
                    done += 1
                else:
                    refused.append(row)
                continue
            f = QgsFeature(lyr.fields())
            f.setGeometry(geom)
            for key, value in (row.get("fields") or {}).items():
                at = lyr.fields().indexOf(key)
                if at >= 0:
                    try:
                        f.setAttribute(at, value)
                    except Exception:
                        pass
            if lyr.addFeature(f):
                done += 1
            else:
                refused.append(row)
        if skipped:
            log("recovery: %d removal%s or change%s left out, the feature%s "
                "being no longer in the package" % (
                    skipped, "" if skipped == 1 else "s",
                    "" if skipped == 1 else "s", "" if skipped == 1 else "s"))
        return done, refused

    @staticmethod
    def still_there(lyr, fid):
        """Whether the feature a recovery entry names is in the table now,
        buffer included."""
        try:
            f = lyr.getFeature(int(fid))
            return f is not None and f.isValid()
        except Exception:
            return False

    def check_everything(self):
        """Look everything over, say what it finds, change nothing."""
        check(self, self.campaign, self.correction, more=self.more_checks())

    def check_correction(self):
        """The same look over, on the correction alone: CORRECTION has a
        Check of its own, and a report that opened on the annotation
        campaign, or on the absence of one, was not what it was asked."""
        if self.correction is None:
            return
        check(self, None, self.correction, campaign_too=False,
              more=self.more_checks())

    def more_checks(self):
        """What the measuring modules add to Check (measure.py)."""
        return {"campaign": measure_all(DOCTOR_CAMPAIGN),
                "correction": measure_all(DOCTOR_CORRECTION)}

    def pending_layers(self):
        """The campaign's layers that are holding work not yet on disk.

        Asked of the layers themselves and not of the module, because the
        module may well be closed while its buffers are still full: that is
        exactly the state in which work is lost."""
        out = []
        if self.campaign is None:
            return out
        for role in EDITABLE_TABLES:
            lyr = find_mine(self.campaign.data["id"], role)
            if lyr is not None and lyr.isEditable() and lyr.isModified():
                out.append((role, lyr))
        return out

    def flush_layers(self):
        """Commit every buffer that is still full. Returns what would not go."""
        trouble = []
        for role, lyr in self.pending_layers():
            if not lyr.commitChanges():
                trouble.append("%s: %s" % (role, "; ".join(lyr.commitErrors()[:2])))
            else:
                # Table by table: a crash before the next commit must not
                # find this table's work still in the net, or a restore puts
                # it in the package a second time.
                self.keep_safe()
        self.keep_safe()
        return trouble

    def vertex_tool_put_down(self, new_tool=None, old_tool=None):
        """QGIS's vertex tool was put down: make it forget the campaign.

        The vertex tool keeps every table it has hovered over in a cache of its
        own, and the cache stays connected to the table after the tool is put
        down. From then on every geometry the program changes in that table,
        a frame moved with its contents, a neighbour trimmed by the brush, is
        checked by a tool nobody is holding, and each fault the check finds,
        two edges of an outline crossing, is pinned to the map as a green X.
        Only that tool deletes those marks, and only when it is put down
        again, so they would stay on the map, over polygons that had moved
        somewhere else, with nothing in the panel that could clear them.

        A table that says its data changed makes the tool drop its cache of
        it and let go of its signals, which is what QGIS does itself when a
        file is reloaded under it. Done for every campaign table the moment
        the tool is put down, and never while it is in hand: there its marks
        are the ones a person dragging a vertex is meant to see, and putting
        it down deletes them."""
        if old_tool is None or self.campaign is None:
            return 0
        if not is_vertex_tool(old_tool) or is_vertex_tool(new_tool):
            return 0
        return self.vertex_tool_let_go()

    def vertex_tool_let_go(self):
        """Every campaign table says its data changed, so that QGIS's vertex
        tool, wherever it is, stops following it. See vertex_tool_put_down.

        Returns how many tables were told."""
        if self.campaign is None:
            return 0
        told = 0
        for table, _, _ in TABLES:
            lyr = find_mine(self.campaign.data["id"], table)
            if lyr is None:
                continue
            try:
                lyr.dataChanged.emit()
                told += 1
            except Exception as err:
                log("%s: cannot tell the vertex tool to let go: %s"
                    % (table, err))
        return told

    def leave_layers(self):
        """The plugin is going away and the campaign's layers stay behind.

        Unloading the plugin, which is also what the Plugin Manager does
        before an upgrade, cannot ask anything: there may be no window left
        to ask from. The layers stay in the project, because they are the
        user's view of the work and a campaign opened again adopts them. What
        must not stay is their edit sessions. A table left in edit mode by a
        program that is no longer there has nobody to save it, the pencil in
        the Layers panel says somebody is drawing, and the next Open campaign
        finds a buffer it never filled.

        So every table still in edit mode is committed and its session ended.
        Committed and not rolled back: by now the module has saved what it
        held, and anything still in a buffer, a rename that could not be
        written, a recovery put back, is work, and rolling it back is the one
        thing this program never does without being asked. A table whose
        commit fails is left exactly as it is, still in edit mode with its
        buffer whole, so QGIS asks about it when the project is closed, and
        the recovery snapshot is brought up to date to hold it too.

        Returns (ended, kept): the number of sessions ended, and the tables
        left editing with the reason."""
        if self.campaign is None:
            return 0, []
        ended, kept = 0, []
        for table, _, _ in TABLES:
            lyr = find_mine(self.campaign.data["id"], table)
            if lyr is None or not lyr.isEditable():
                continue
            try:
                done = lyr.commitChanges()
            except Exception as err:
                kept.append("%s: %s" % (table, err))
                continue
            if done and not lyr.isEditable():
                ended += 1
            else:
                kept.append("%s: %s"
                            % (table, "; ".join(lyr.commitErrors()[:2])
                               or "still in edit mode"))
        self.keep_safe()
        if kept:
            log("on the way out, %d table%s could not be saved and %s left in "
                "edit mode with the work in it, so QGIS will ask about %s when "
                "the project is closed: %s"
                % (len(kept), "" if len(kept) == 1 else "s",
                   "is" if len(kept) == 1 else "are",
                   "it" if len(kept) == 1 else "them", "; ".join(kept)),
                loud=True)
        if ended:
            log("on the way out, %d table%s saved and out of edit mode"
                % (ended, "" if ended == 1 else "s"))
        return ended, kept

    def close_campaign(self):
        if self.campaign is None:
            return
        # One question, asked of the layers as well as of the module.
        # Asking only the module is a hole: Correct and Cutouts answer
        # "nothing pending" by construction, because neither of them owns a
        # brush, so a buffer filled by a class rename or by the module before
        # them would be dropped without a word. The layers always know.
        discard = False
        if self.section is not None and self.section.unsaved() \
                or self.pending_layers():
            # Save, Discard and Cancel, the words every program uses for
            # this question, with Save the default: Yes and No made the one
            # answer that throws work away read as harmless as the others.
            q = QMessageBox.question(
                self, NAME,
                "There is work in this campaign that is not on disk yet.\n\n"
                "Save it before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
            if q == QMessageBox.StandardButton.Cancel:
                return
            discard = (q == QMessageBox.StandardButton.Discard)
            if q == QMessageBox.StandardButton.Save:
                # And checked. A save that failed must not be followed
                # straight by close_module and drop_layers, which take the
                # layers out of the project and the buffers with them: the one
                # answer that means "keep my work" would throw it away.
                if self.section is not None:
                    try:
                        self.section.save()
                    except Exception as err:
                        trouble(err, "Save")
                left = self.flush_layers()
                if left or (self.section is not None
                            and self.section.unsaved()) \
                        or self.pending_layers():
                    QMessageBox.critical(
                        self, NAME,
                        "Not everything could be saved, so nothing was "
                        "closed:\n\n"
                        + ("\n".join(left) if left else
                           "the module still reports work in hand."))
                    return
        if self.section is not None and self.open_index in (0, 2):
            # close_module saves whatever the module is holding, which is right
            # when a module is being swapped for another and wrong here: the
            # user has just been asked and has just said no. Without this the
            # one answer that meant "do not write this to disk" wrote it to
            # disk, and the only way to find out was to look.
            #
            # Only Annotate and Objects: they draw into this campaign. Correct
            # has a campaign of its own and stays open; Cutouts is built again
            # below, without the campaign it was reading.
            self.close_module(save_first=not discard)
        if discard:
            # And the buffers go, because that is what was asked for. This is
            # the one place in the program where rolling a buffer back is the
            # right thing: everywhere else it throws away work nobody asked to
            # lose, here it is the request.
            dropped = 0
            for role, lyr in self.pending_layers():
                try:
                    with own_hands():
                        lyr.rollBack()
                    dropped += 1
                except Exception as err:
                    log("%s would not let go of its buffer: %s" % (role, err))
            if self.recovery is not None:
                # Otherwise the next open offers back exactly the work that was
                # just refused.
                self.recovery.clear()
            log("closed without saving, as asked: %d table%s rolled back"
                % (dropped, "" if dropped == 1 else "s"), loud=True)
        how_many = drop_layers(self.campaign.data["id"], self.campaign.group_name)
        log("campaign closed, %d layers removed from the project, no file touched"
            % how_many)
        # Nothing got this far unless everything is on disk, so the net has
        # nothing left to hold. Leaving the file behind would mean being asked
        # about work that was saved an hour ago at the next open.
        if self.recovery is not None:
            self.recovery.clear()
            self.recovery = None
        self.campaign = None
        self.route_log()
        self.describe_campaign()
        self.update_enabled()
        self.campaign_changed()

    def strays_of(self, table):
        """Layers already in the project that read this very table.

        A QGIS project saves its layers, this program's included. Reopen the
        project and they come back, pointing at the same GeoPackage; press
        Open campaign and, unless they are recognised, a second set is added
        on top of them. Two layers, one table, two styles: the map shows the
        drawing twice, and the copy that is not being restyled is the one that
        looks like an old shape refusing to be cut. Nothing is wrong in the
        file; what is wrong is that it is being drawn twice.

        Recognised how: by what they read, not by what they are called or by
        any property they may have lost. A layer whose source is this package
        and this table is this campaign's layer, whoever made it."""
        want = os.path.normcase(os.path.abspath(self.campaign.package_path))
        out = []
        for lyr in QgsProject.instance().mapLayers().values():
            try:
                source = lyr.source()
            except Exception:
                continue
            if "|layername=" not in source:
                continue
            path, _, rest = source.partition("|layername=")
            if rest.split("|")[0] != table:
                continue
            if os.path.normcase(os.path.abspath(path)) != want:
                continue
            out.append(lyr)
        return out

    def claim_strays(self):
        """Take over the layers the project brought back, and drop the extras.

        The first one is adopted: given the campaign's marks so that every
        other part of the program can find it, and kept, because the user may
        well have styled or positioned it. Any further copy of the same table
        is removed from the project, which touches no file at all."""
        adopted, dropped = 0, 0
        for table, _, _ in TABLES:
            found = self.strays_of(table)
            if not found:
                continue
            mine = find_mine(self.campaign.data["id"], table)
            keep = mine if mine in found else found[0]
            if keep is not mine:
                mark(keep, self.campaign.data["id"], table)
                adopted += 1
            extra = [l.id() for l in found if l is not keep]
            if extra:
                with own_hands():
                    QgsProject.instance().removeMapLayers(extra)
                dropped += len(extra)
        if adopted or dropped:
            log("layers the project had kept: %d adopted, %d duplicate%s removed"
                % (adopted, dropped, "" if dropped == 1 else "s"),
                loud=bool(dropped))
        return adopted, dropped

    def load_layers(self):
        """Load the tables of the campaign, never twice.

        The name is set on the way past every time, not only when the layer is
        made: a campaign started by an older version has layers called plain
        polygons and points, and reopening it here is what puts the campaign's
        name back in front of them. Renaming touches nothing but the label:
        the program finds its own layers by a custom property, never by what
        they are called, so the name is free to change under it."""
        if self.campaign is None:
            return
        # The layers a saved project brought back for this campaign id but
        # reading another file, the original of a copied folder or the old
        # place of a moved one, go first: they are not this campaign's.
        drop_stale(self.campaign.data["id"], self.campaign.package_path,
                   [t for t, _, _ in TABLES])
        # First what is already there, then what is missing. The other way
        # round adds the second copy and then adopts the first.
        self.claim_strays()
        for table, _, _ in TABLES:
            wanted = self.campaign.layer_name(table)
            source = "%s|layername=%s" % (self.campaign.package_path, table)
            lyr = QgsVectorLayer(source, wanted, "ogr")
            if not lyr.isValid():
                log("cannot load the table %s" % table)
                continue
            live = add_layer(lyr, self.campaign, table)
            if live.name() != wanted:
                live.setName(wanted)
        tidy_layers(self.campaign)
        restyle(self.campaign)
        # A table adopted from the project may still be followed by QGIS's
        # vertex tool from before this panel existed. A plugin upgraded or
        # reloaded without closing QGIS leaves the tool where it was, and the
        # tables in the project, and the panel that was watching for the tool
        # to be put down goes with the old plugin. Nobody would put it down
        # again, and the first frame moved would bring the green X back. Let
        # go of it now, unless it is in hand.
        try:
            if not is_vertex_tool(canvas().mapTool()):
                self.vertex_tool_let_go()
        except Exception as err:
            log("cannot tell the vertex tool to let go: %s" % err)
        # restyle() replaces the renderer, and the renderer is where the filter
        # lives. Loading the tables again while a module is open would
        # otherwise leave every operator and every pass on screen in front of a
        # brush that still sees one of each.
        self.filter_for_reading()

    def filter_for_reading(self):
        """The filter of the reading in hand on the tables, from the module
        that is open or, with none, from the panel (ReadingFilter): the map
        of a campaign just opened is the one Annotate would show."""
        section = getattr(self, "section", None)
        if section is not None and hasattr(section, "apply_filter"):
            section.apply_filter()
            return
        if self.campaign is None:
            return
        try:
            ReadingFilter(self).apply_filter()
        except Exception as err:
            log("cannot filter the tables by the reading in hand: %s" % err)

    def edit_classes(self):
        if self.campaign is None:
            return
        d = ClassEditor(self, self.campaign.active_classes(),
                        self.campaign.next_code())
        if not run_dialog(d):
            return
        fresh = d.result()
        # code_of() looks the brush's class up by name across the whole legend,
        # retired classes included, and returns the first code that matches.
        # Give a new class the name of a retired one and every polygon drawn
        # with it is stamped with the retired code, while the points and the
        # lines take the new one: the same mark, two codes, and the exported
        # mask carries a number the legend does not show. finish_rename
        # refuses this on the inline path; the dialog cannot see it.
        retired = {c["name"]: c["code"] for c in self.campaign.data["classes"]
                   if c.get("retired")}
        clash = [c["name"] for c in fresh
                 if c["name"] in retired and c["code"] != retired[c["name"]]]
        if clash:
            QMessageBox.warning(
                self, NAME,
                "%s belongs to a class that was retired, and its number is "
                "still inside everything drawn with it and inside every mask "
                "already exported.\n\nThe map is painted by name, so the two "
                "would be confused. Choose another name.\n\nNothing was "
                "changed."
                % (", ".join("'%s'" % c for c in clash)
                   + (" each" if len(clash) > 1 else "")))
            log("legend not changed: retired names reused: %s"
                % ", ".join(clash))
            return
        kept = {c["code"] for c in fresh}
        merged = list(fresh)
        for c in self.campaign.data["classes"]:
            if c["code"] not in kept:
                c = dict(c)
                c["retired"] = True
                merged.append(c)
        self.campaign.data["classes"] = sorted(merged, key=lambda c: c["code"])
        self.campaign.save()
        renamed = self.rename_features()
        restyle(self.campaign)
        if self.section is not None and hasattr(self.section, "rebuild_class_buttons"):
            self.section.rebuild_class_buttons()
        self.filter_for_reading()
        self.describe_campaign()
        log("legend updated: %d active, %d retired%s"
            % (len(self.campaign.active_classes()),
               len(self.campaign.data["classes"]) - len(self.campaign.active_classes()),
               ", %d features renamed" % renamed if renamed else ""))

    def rename_features(self):
        """A renamed class has to reach the work already done.

        Everything drawn carries the class name as well as its code, and the
        renderer paints by name. Renaming a class in the legend and leaving the
        old name on the features makes that work disappear from the map without
        a word, although it is all still there.

        And it is the program's own edit, not a mark being moved, which the
        marks lock has to be told here and not by each caller. With the marks
        locked, the lock follows the undo stacks: the command this pushes on
        every table looks like an edit, and when the commit after it fails,
        which leaves the command on the stack, the lock walks it back. The
        legend would say the new name, the features the old one, and the map,
        which paints by name, would stop drawing them. Said once here, every
        way of renaming is covered, and the
        lock is then held from where the rename left the tables."""
        names = {c["code"]: c["name"] for c in self.campaign.data["classes"]}
        total = 0
        section = getattr(self, "section", None)
        if section is not None and not hasattr(section, "rebase_lock"):
            section = None          # only Annotate holds the marks still
        settling = getattr(section, "_settling", False)
        if section is not None:
            section._settling = True
        try:
            for role in ("polygons", "lines", "points", "boxes"):
                lyr = find_mine(self.campaign.data["id"], role)
                if lyr is None:
                    continue
                index = lyr.fields().indexOf("class_name")
                code_at = lyr.fields().indexOf("class_code")
                if index < 0 or code_at < 0:
                    continue
                wrong = {}
                for f in lyr.getFeatures():
                    right = names.get(f["class_code"])
                    if right is not None and f["class_name"] != right:
                        wrong[f.id()] = {index: right}
                if not wrong:
                    continue
                if not lyr.isEditable():
                    lyr.startEditing()
                lyr.beginEditCommand("rename classes")
                for fid, values in wrong.items():
                    for at, value in values.items():
                        lyr.changeAttributeValue(fid, at, value)
                lyr.endEditCommand()
                # Committed here, and not left for whatever saves next. The
                # manifest has already been written with the new name, and
                # the map is painted by name: a rename that stays in a buffer
                # and is then thrown away leaves a campaign whose legend says
                # one thing and whose polygons say another, and they vanish
                # from the map.
                if not lyr.commitChanges():
                    # The rename stays in the buffer. rollBack here discarded
                    # everything else pending in the table as well, which on
                    # a locked package turned a failed rename into a lost
                    # afternoon.
                    log("%s: the new class name could not be written and is "
                        "still waiting to be saved: %s"
                        % (role, "; ".join(lyr.commitErrors()[:2])),
                        loud=True)
                if not lyr.isEditable():
                    lyr.startEditing()
                # Written, or still waiting: either way the net says what the
                # table holds now, not what it held before the rename.
                self.keep_safe()
                lyr.triggerRepaint()
                total += len(wrong)
        finally:
            if section is not None:
                section._settling = settling
                try:
                    section.rebase_lock()
                except Exception as err:
                    log("the marks lock could not be moved past the rename: %s"
                        % err)
        return total

    # ------------------------------------------------------------- modules
    def toggle_module(self, index):
        """One module at a time. They share the canvas and the map tool, and
        two of them holding the brush at once is a way to lose work.

        Annotate and Objects need an annotation campaign; Correct and Cutouts
        do not, and open on an empty panel."""
        if index in (0, 2) and self.campaign is None:
            self.modules[index].setChecked(False)
            return
        if self.open_index == index:
            self.close_module()
            return
        # Leaving Correct closes the correction with it. A correction opened
        # in CORRECTION while another module was in use is open already, and
        # that module is closed here without touching it.
        self.close_module()
        try:
            section = self.make_module(index)
        except Exception as err:
            QMessageBox.critical(self, NAME,
                                 "The module will not open:\n\n%s" % err)
            log("cannot open the module: %s" % err)
            section = None
        if section is None:
            self.route_log()
            self.modules[index].setChecked(False)
            return
        self.section = section
        self.open_index = index
        self.annotation = section if isinstance(section, AnnotationSection) else None
        self.annotation_slot.addWidget(section)
        self.modules[index].setChecked(True)
        self.route_log()
        self.redeal()

    def make_module(self, index):
        if index in (0, 2) and not self.reading_settled():
            return None
        if index == 0:
            section = AnnotationSection(self)
            section.settle_view()
            section.use_brush()
            log("annotation open, %s"
                % ("tiled campaign" if self.campaign.data["with_tiles"]
                   else "free campaign: no tiles, so no Fill Gap"))
            return section
        if index == 1:
            # The correction open in CORRECTION, or, when there is none, the
            # window that starts or opens one: Correct is never a dead button.
            if self.correction is None and self.open_correction() is None:
                return None
            return self.correction_section()
        if index == 2:
            section = ObjectsSection(self)
            section.use_tool()
            log("objects open, %d boxes in the campaign" % len(section.all_boxes()))
            return section
        section = CutoutsSection(self)
        log("cutouts open, writing into %s%s"
            % (section.folder, "" if self.campaign is not None else
               "; no campaign is open and none is needed"))
        return section

    def let_go(self):
        """Give back everything that outlives this panel.

        Called before a second launch takes its place, and it is the whole
        cure for the ghost: signals that belong to the project go on living
        after the window is destroyed, and whoever holds them keeps being
        called."""
        gone = unhook(self)
        try:
            if self.section is not None:
                gone += unhook(self.section)
        except Exception:
            pass
        return gone

    def close_module(self, save_first=True):
        for b in self.modules:
            b.setChecked(False)
        self.open_index = None
        if self.section is None:
            return
        correcting = isinstance(self.section, CorrectionSection)
        # The reading outlives the module: the next Annotate, or Objects,
        # draws as the same person in the same pass.
        if self.annotation is not None:
            self.keep_reading(self.annotation)
        # Written down before anything is taken apart. Closing a module used
        # to leave the strokes in the layer's edit buffer and the buffer in
        # the layer; closing the campaign then removed the layers from the
        # project, and QGIS throws an uncommitted buffer away without a word.
        # An hour of drawing could go that way in two clicks, and the log said
        # "no file touched", which was true and was the problem.
        try:
            if save_first and self.section.unsaved():
                self.section.save()
                log("saved on the way out of the module")
            elif not save_first:
                log("the module was closed without saving, as asked")
        except Exception as err:
            log("could not save while closing the module: %s" % err)
        try:
            self.section.release_tools()
        except Exception:
            pass
        # and what the tools drew on the canvas goes with them: a band left
        # over from a stroke still being drawn stays on the map otherwise
        clear_bands(*[getattr(self.section, name, None) for name in
                      ("brush", "tile_tool", "point_tool", "line_tool",
                       "tool")])
        unhook(self.section)
        if hasattr(self.section, "close_dataset"):
            self.section.close_dataset()
        self.annotation_slot.removeWidget(self.section)
        self.section.setParent(None)
        self.section.deleteLater()
        self.section = None
        self.annotation = None
        if correcting:
            # The correction lives as long as its module. One left open
            # behind another module kept its layer in the project, and with
            # the layer the working copy, which Windows would then not let
            # anybody move or rename until Close was found.
            self.drop_correction()
        self.route_log()
        self.redeal()

    def redeal(self):
        """The open module is a card like the others and its height decides
        how the cards are shared out, so opening or closing one deals again."""
        self._columns = None
        self.describe_correction()
        # an empty body is no card: shown, it cost the column two gaps
        self.body.setVisible(self.section is not None)
        self.fold_blocks()
        self.update_enabled()
        self.arrange()
        self.body.setVisible(self.section is not None)

    # ----------------------------------------------------------- correction
    def new_correction_campaign(self):
        """New in CORRECTION: the window opens on a new correction, and the
        correction made is opened in Correct."""
        if self.correction is None and self.open_correction("new") is not None:
            self.show_correction()

    def open_correction_campaign(self):
        """Open in CORRECTION: the window opens on the corrections opened
        lately, and the one chosen is opened in Correct."""
        if self.correction is None and self.open_correction("open") is not None:
            self.show_correction()

    def show_correction(self):
        """Correct, on the correction just opened, unless it is open
        already."""
        if self.correction is not None and self.open_index != 1:
            self.toggle_module(1)

    def correction_section(self):
        """The module, on the correction that is open. A correction whose
        module cannot be built is closed again rather than left open with
        nothing to work on it with."""
        book = self.correction
        try:
            return CorrectionSection(self, book.data, book=book)
        except Exception:
            self.close_correction()
            raise

    def correction_classes(self):
        """Classes in CORRECTION: the window the classes were confirmed in.

        It counts the pixels of the copy and restyles its layer and its
        chips, all of which Correct holds. A correction is open only while
        Correct is, and with none open the button is grey."""
        if isinstance(self.section, CorrectionSection):
            self.section.edit_classes()
            self.describe_correction()

    def close_correction(self):
        """Close in CORRECTION: Correct is closed, and the correction with
        it. Opening the correction again, one click in the list of recent
        ones, brings it back as it was."""
        if self.correction is None:
            return
        if isinstance(self.section, CorrectionSection):
            self.close_module()
        else:
            # a correction whose module could not be built
            self.drop_correction()

    def drop_correction(self):
        """The correction closed: its layer leaves the project, which touches
        no file, and the log goes back to whatever else is open."""
        book = self.correction
        if book is None:
            return
        gone = drop_layers(book.data.get("id", ""), book.group_name)
        # Once no layer holds the copy any more, its style once again, from
        # the classes it closes with: a layer QGIS still held could have
        # written an older colour table back into the .aux.xml on its way
        # out.
        try:
            if os.path.exists(book.working_path):
                dress_copy(book.working_path, int(book.data.get("band", 1)),
                           book.data.get("classes") or [],
                           str(book.data.get("source") or ""))
        except Exception as err:
            log("cannot write the style of the corrected map: %s" % err)
        log("correction '%s' closed, %d layer%s removed from the project, "
            "no pixel touched" % (book.data.get("name", ""), gone,
                                  "" if gone == 1 else "s"))
        self.correction = None
        self.route_log()
        self.describe_correction()
        self.update_enabled()

    def open_correction(self, start=None):
        """Open a correction campaign, or start one, and make it the one
        that is open, for Correct to open on: the correction, or None. None
        of this needs an annotation campaign: a correction is a folder of its
        own, made on a thematic map that any program may have produced. One
        kept inside the annotation campaign that is open, the way
        RasterLabel 1.0 kept them, is offered too, and opens where it is as
        a campaign of its own.

        start is where the window opens: on a new correction ("new"), on the
        ones opened lately ("open"), or, from Correct, on whichever there is.
        Every choice stays in its list either way."""
        # A class map with no coordinate system is still a class map, and
        # Correct measures in pixels when it has to. Opening one already made
        # needs no map on the screen at all: it brings its own copy.
        rasters = project_rasters(need_crs=False)
        if not rasters and start != "open":
            QMessageBox.warning(self, NAME, "Load the map to correct first.")
            return None
        if self.campaign is not None:
            operator = self.who_is_drawing()
        else:
            operator = read_setting(OPERATOR_KEY, "") or ""
        dialog = OpenCorrection(self, rasters, campaign=self.campaign,
                                recent=recent_corrections(),
                                operator=operator, start=start)
        if not run_dialog(dialog):
            return None
        kind, value = dialog.result()
        if kind == "new":
            return self.new_correction(value)
        return self.open_existing(kind, value)

    def read_correction(self, path):
        """The correction campaign at path, a correction.json or its folder,
        or None with the reason said."""
        if not path:
            return None
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        manifest = os.path.join(folder, CorrectionCampaign.MANIFEST)
        if not os.path.exists(manifest):
            QMessageBox.warning(
                self, NAME,
                "That is not a correction.\n\nA correction campaign is a folder "
                "holding a %s: choose that file." % CorrectionCampaign.MANIFEST)
            return None
        try:
            book = CorrectionCampaign.open(folder)
        except Exception as err:
            QMessageBox.critical(self, NAME, "Unreadable manifest:\n%s" % err)
            return None
        disagree = book.reconcile()
        if not os.path.exists(book.working_path):
            QMessageBox.warning(
                self, NAME, "The working copy of '%s' is no longer on disk:\n%s"
                % (book.data.get("name", "?"), book.working_path))
            return None
        if disagree:
            QMessageBox.warning(self, NAME,
                                "The correction opens, but manifest and disk do "
                                "not agree:\n\n- " + "\n- ".join(disagree))
            for t in disagree:
                log("disagreement: " + t.replace("\n", " "))
        return book

    def migrate_correction(self, name):
        """A correction kept inside the annotation campaign, given a campaign
        of its own in its own folder. Nothing is copied, moved or deleted:
        see CorrectionCampaign.adopt."""
        if self.campaign is None:
            return None
        for record in self.campaign.data.get("corrections", []):
            if record.get("name") != name:
                continue
            # a record the campaign has adopted keeps its paths from the
            # campaign's folder
            files = [from_folder(f, self.campaign.folder)
                     for f in record.get("files") or [""]]
            if not os.path.exists(files[0]):
                QMessageBox.warning(
                    self, NAME,
                    "The working copy of '%s' is no longer on disk:\n%s"
                    % (name, files[0]))
                return None
            try:
                return CorrectionCampaign.adopt(record, self.campaign)
            except Exception as err:
                QMessageBox.critical(self, NAME,
                                     "The correction cannot be opened:\n\n%s"
                                     % err)
                return None
        return None

    def open_existing(self, kind, value):
        """A correction already on disk, opened as Open would open it:
        ("open", its correction.json) or ("legacy", a record of the
        annotation campaign). The correction, or None with the reason
        said."""
        if kind == "legacy":
            book = self.migrate_correction(value)
        else:
            book = self.read_correction(value)
        if book is None:
            return None
        return self.start_correction(book)

    def new_correction(self, recipe):
        """A new correction campaign. Every refusal comes before anything is
        written: the folder, the map, the classes, and only then the copy.

        What is found already there is asked about, never used in silence:
        a map that is itself a working copy, a map that already has a
        correction, a folder that already holds the working copy of this map
        without its manifest, and the map's own folder."""
        if not recipe.get("name") or recipe.get("layer") is None:
            return None
        folder = recipe["folder"]
        there = os.path.join(folder, CorrectionCampaign.MANIFEST)
        if os.path.exists(there):
            name = (peek_correction(there) or {}).get("name", "?")
            QMessageBox.warning(
                self, NAME,
                "That folder already holds the correction '%s'. Open it "
                "instead, or choose another folder." % name)
            return None
        layer, band = recipe["layer"], int(recipe["band"])
        source = source_of(layer)

        # A map on a rotated grid: a stroke would be burned on a grid that is
        # not the map's, and the wrong pixels changed with the log saying
        # they were right. Refused before anything is written.
        if rotated_file(source):
            log("new correction refused: %s has a rotated pixel grid"
                % os.path.basename(source))
            QMessageBox.warning(self, NAME, rotated_refusal(source))
            return None

        # A working copy chosen as the map to correct: correcting it would
        # split the history of its correction in two. Its owner is offered.
        why = why_a_working_copy(source, self.campaign)
        if why is not None:
            owner = owner_of_copy(source, self.campaign)
            log("new correction refused: %s is a working copy, %s"
                % (os.path.basename(source), why))
            text = ("'%s' is already the working copy of a correction: %s."
                    % (os.path.basename(source), why))
            if owner is None:
                QMessageBox.warning(
                    self, NAME,
                    text + "\n\nCorrecting a correction would split its history "
                    "in two. Open the correction that owns it instead: choose "
                    "'Open a correction.json...' and pick its %s.\n\nIf that "
                    "file is lost, choose the original map instead, and as "
                    "the folder the one that holds this copy under the name "
                    "<map>_corrected.tif: the copy is then offered to be "
                    "resumed, corrections and all."
                    % CorrectionCampaign.MANIFEST)
                return None
            kind, value, name = owner
            chosen = ask_among(
                self, "Correction", text,
                "Correcting a correction would split its history in two. It "
                "belongs to the correction '%s'." % name,
                [("owner", "Open the correction that owns it")])
            if chosen != "owner":
                return None
            return self.open_existing(kind, value)

        # A map that already has a correction. A second one is allowed, on
        # purpose: a different operator, another try. By mistake it is two
        # histories of one map, so the first one is offered.
        known = corrections_of(source, self.campaign)
        if known:
            kind, value, name = known[0]
            others = ""
            if len(known) > 1:
                others = ("\n\nIt has %d other%s: %s." % (
                    len(known) - 1, "" if len(known) == 2 else "s",
                    ", ".join("'%s'" % n for _, _, n in known[1:])))
            chosen = ask_among(
                self, "Correction",
                "'%s' already has the correction '%s'."
                % (os.path.basename(source), name),
                "Open that one to go on where it was left, or make a new "
                "correction beside it, with a history of its own." + others,
                [("open", "Open that one"), ("new", "Make a new correction")])
            if chosen == "open":
                return self.open_existing(kind, value)
            if chosen != "new":
                return None
            log("a new correction of %s, beside the correction '%s' it "
                "already has" % (os.path.basename(source), name))

        # The map's own folder. Allowed, but the manifest then sits beside the
        # original, every file of the correction mixes with the map's, and a
        # second correction of the same map has nowhere to go.
        if same_file(folder, os.path.dirname(source)):
            chosen = ask_among(
                self, "Correction",
                "That folder is the folder of the map itself.",
                "The correction's files, %s, the working copy, "
                "operations.csv and the log, would sit beside the original, "
                "and a second correction of this map could not use the same "
                "folder. A folder of its own is better."
                % CorrectionCampaign.MANIFEST,
                [("here", "Use this folder anyway")])
            if chosen != "here":
                return None
            log("the correction is made in the folder of the map itself: %s"
                % folder)

        # The working copy of this map already in the folder, with no
        # manifest: a creation stopped half way, or a correction.json lost.
        # It may hold hours of work, so it is never reused in silence and
        # never deleted: resumed, or set aside.
        leftover = os.path.join(folder, copy_name(source))
        resume = False
        fresh = False
        if os.path.exists(leftover):
            fit = self.resumable(leftover, layer)
            if fit is None:
                choices = [("resume", "Resume it"),
                           ("fresh", "Start from a fresh copy")]
                detail = ("Resume it: it is kept as it is, corrections and "
                          "all, a new %s is written beside it, and its classes "
                          "are shown to you first.\n\nStart from a fresh copy: "
                          "the old copy, its %s and its operations.csv are "
                          "set aside in a folder of their own, never deleted, "
                          "and a new copy is made from the map."
                          % (CorrectionCampaign.MANIFEST,
                             changes_name(leftover)))
            else:
                choices = [("fresh", "Start from a fresh copy")]
                detail = ("It cannot be resumed: %s.\n\nStart from a fresh "
                          "copy: the old copy and its operations.csv are set "
                          "aside in a folder of their own, never deleted, and "
                          "a new copy is made from the map." % fit)
            chosen = ask_among(
                self, "Correction",
                "That folder already holds %s, a working copy of this map, "
                "but no %s." % (os.path.basename(leftover),
                                CorrectionCampaign.MANIFEST),
                detail, choices)
            if chosen == "resume":
                resume = True
            elif chosen == "fresh":
                fresh = True
            else:
                return None

        # A class map holds a handful of numbers, and a correction takes its
        # classes from them: from the style of the layer when the style names
        # them, from the values themselves when it does not. The campaign
        # legend has nothing to say here; it numbers what is drawn in Annotate
        # and Objects, and a model's map has a numbering of its own. What is
        # still worth a word is an orthophoto chosen by mistake: hundreds of
        # values, each of which would become a class. Two maps are worth a
        # word before that, whatever their values: a map of classes saved as
        # a picture in colour, whose classes are colours and not codes, and
        # one saved in a compression that does not keep values exactly.
        found = values_in(source, band)
        named = style_classes(layer, band)
        spared = set()
        try:
            provider = layer.dataProvider()
            if provider.sourceHasNoDataValue(band):
                spared = {int(provider.sourceNoDataValue(band))}
        except Exception:
            spared = set()
        distinct = None if found is None else len(found - spared)
        codec = lossy_codec(source)
        if not named and colour_picture(source):
            log("new correction on %s: a picture in colour, %s"
                % (os.path.basename(source),
                   "stored as %s" % codec if codec else "stored without loss"))
            if not self.ask_anyway(colour_text(os.path.basename(source), band,
                                               distinct, codec)):
                return None
            # asked about, its values and its compression with it
            found = codec = None
        if codec:
            log("new correction on %s: stored as %s, which does not keep "
                "values exactly" % (os.path.basename(source), codec))
            if not self.ask_anyway(lossy_text(os.path.basename(source),
                                              codec)):
                return None
        if found is not None and not named:
            if distinct > 64:
                q = QMessageBox.warning(
                    self, NAME,
                    "Band %d of '%s' holds %d different values and its style "
                    "names no classes.\n\nThis does not look like the map of "
                    "an algorithm: a correction takes its classes from the "
                    "values of the map, and every one of them would become a "
                    "class.\n\nStart it anyway?"
                    % (band, os.path.basename(source), distinct),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel)
                if q != QMessageBox.StandardButton.Yes:
                    return None

        # A copy resumed may hold corrections already: its classes are read
        # from it, with the values it holds locked, as when a manifest with
        # no classes is opened.
        notes = []
        reading = leftover if resume else source
        try:
            values, nodata = read_band(reading, band)
        except Exception as err:
            QMessageBox.critical(self, NAME, "The map cannot be read:\n\n%s" % err)
            return None
        classes = thematic_classes(values, nodata, layer, band, source, notes)
        counts = class_counts(values, nodata)
        confirmed = self.confirm_classes(classes, counts,
                                         os.path.basename(source), band, nodata,
                                         code_range_of(values),
                                         locked=sorted(counts) if resume else ())
        values = None
        if confirmed is None:
            log("no correction made: the classes were not confirmed")
            return None
        if fresh:
            try:
                set_aside_leftovers(folder, beside_the_copy(leftover)
                                    + ["operations.csv"])
            except Exception as err:
                QMessageBox.critical(self, NAME,
                                     "The old copy cannot be set aside, so no "
                                     "correction was made:\n\n%s" % err)
                return None
        try:
            book = CorrectionCampaign.create(
                folder, recipe["name"], layer, band, confirmed,
                recipe.get("operator") or "", notes, resume=resume)
        except Exception as err:
            QMessageBox.critical(self, NAME,
                                 "Cannot create the correction:\n%s" % err)
            return None
        for line in notes:
            log(line)
        write_setting(OPERATOR_KEY, book.data["operator"])
        # Who typed their name in the window that made it is who corrects it
        # now, whatever reading the session holds for another campaign; not
        # written anywhere, so a later session is the panel's to say
        # (CorrectionSection.operator_name).
        book.operator_said = book.data["operator"]
        SESSION.setdefault("said", {})[book.data.get("id", "")] = (
            book.operator_said, SESSION["operator"])
        log("correction campaign '%s' %s in %s, %d classes confirmed"
            % (book.data["name"],
               "resumed from the copy already there" if resume else "created",
               book.folder, len(confirmed)))
        # The layer is handed over for its style: the chips of the correction
        # are the classes it is drawn with, confirmed and kept in the manifest.
        return self.start_correction(book, layer)

    @staticmethod
    def resumable(copy, layer):
        """None when the copy already in the folder can be resumed as the
        working copy of this layer's map, or why it cannot: one with neither
        its record of changed pixels beside it nor the "corrected" band of
        a copy written by RasterLabel 1.0 cannot say which pixels a person
        changed, and one of another size is the copy of another map that
        happens to share the name."""
        if not (has_flag_band(copy)
                or os.path.exists(long_path(changes_of(copy)))):
            return ("%s is not beside it, nor has it the '%s' band of an "
                    "earlier build, so which pixels a person changed is not "
                    "known" % (changes_name(copy), FLAG_BAND_NAME))
        ds = None
        try:
            ds = gdal.Open(copy)
            if ds is None:
                return "it cannot be read"
            size = (ds.RasterXSize, ds.RasterYSize)
        except Exception:
            return "it cannot be read"
        finally:
            ds = None
        try:
            mine = (int(layer.width()), int(layer.height()))
        except Exception:
            mine = size
        if size != mine:
            return ("it is %d x %d pixels and the map is %d x %d: it is the "
                    "copy of another map" % (size + mine))
        return None

    def ask_anyway(self, text):
        """A warning that asks whether to go on, Cancel the default: True
        only for Yes."""
        q = QMessageBox.warning(
            self, NAME, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return q == QMessageBox.StandardButton.Yes

    def confirm_classes(self, classes, counts, source_name, band, nodata,
                        code_range, locked=()):
        """The classes, shown to the user before they are used. None when
        the window is cancelled."""
        d = ConfirmClasses(self, classes, counts, source_name, band, nodata,
                           code_range, locked=locked)
        if not run_dialog(d):
            return None
        return d.result()

    def start_correction(self, book, layer=None):
        """A correction campaign that is ready, made the one open.

        A manifest with no classes, migrated from a record that never had
        them or written by hand, gets them read from the copy and shown to
        the user once, as a new correction does.

        A working copy on a rotated grid, made before such maps were refused,
        is not opened: every stroke would change other pixels than the ones
        painted over. It stays on disk as it is."""
        if rotated_file(book.working_path):
            log("correction '%s' not opened: its working copy has a rotated "
                "pixel grid" % book.data.get("name", ""))
            QMessageBox.warning(
                self, NAME, "The correction '%s' is not opened, and nothing "
                "of it is changed.\n\n%s"
                % (book.data.get("name", "?"),
                   rotated_refusal(book.working_path)))
            return None
        if not book.data.get("classes"):
            try:
                values, nodata = read_band(book.working_path,
                                           int(book.data.get("band", 1)))
            except Exception as err:
                QMessageBox.critical(self, NAME,
                                     "The working copy cannot be read:\n\n%s"
                                     % err)
                return None
            source = str(book.data.get("source") or "")
            notes = []
            # The style of the map it started from, if that map is loaded,
            # names the classes better than the bare values of the copy.
            if layer is None:
                layer = layer_reading(source)
            counts = class_counts(values, nodata)
            classes = thematic_classes(
                values, nodata, layer, int(book.data.get("band", 1)),
                source if os.path.exists(source) else book.working_path, notes)
            # The copy exists and may hold corrections already: its values
            # are what they are, so only names and colours are offered.
            confirmed = self.confirm_classes(
                classes, counts, os.path.basename(source or book.working_path),
                int(book.data.get("band", 1)), nodata, code_range_of(values),
                locked=sorted(counts))
            values = None
            if confirmed is None:
                return None
            book.data["classes"] = confirmed
            book.data["classes_confirmed"] = now()
        book.data["last_opened"] = now()
        try:
            book.save()
        except Exception as err:
            log("cannot update the correction manifest: %s" % err, loud=True)
        remember_correction(book.manifest_path)
        self.correction = book
        self.route_log()
        self.describe_correction()
        self.update_enabled()
        return book


def ask_among(parent, title, text, detail, choices):
    """A question with buttons of its own and Cancel, the default: the key of
    the button pressed among choices, a list of (key, label), or None for
    Cancel and for the window closed."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    box.setInformativeText(detail)
    buttons = [(key, box.addButton(label, QMessageBox.ButtonRole.AcceptRole))
               for key, label in choices]
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    run_dialog(box)     # one place in the program knows how Qt spells exec
    pressed = box.clickedButton()
    for key, button in buttons:
        if pressed is button:
            return key
    return None


def layer_reading(path):
    """A raster layer of the project that reads this file, or None."""
    if not path:
        return None
    target = os.path.normcase(os.path.abspath(path.split("|")[0]))
    for layer in QgsProject.instance().mapLayers().values():
        try:
            here = os.path.normcase(os.path.abspath(source_of(layer)))
        except Exception:
            continue
        if here == target and isinstance(layer, QgsRasterLayer):
            return layer
    return None


def read_band(path, band_no):
    """A band, in its file, and its nodata value: read a strip at a time by
    what counts its classes (BandPlane), not held. The whole band in memory,
    and its codes turned into 64 bit integers to count them, was several
    gigabytes more than the map for a map of hundreds of millions of
    pixels."""
    plane = BandPlane(path, band_no)
    return plane, plane.nodata


def code_range_of(values):
    """The codes a band of this type can hold."""
    try:
        info = np.iinfo(values.dtype)
        return int(max(info.min, -2 ** 31)), int(min(info.max, 2 ** 31 - 1))
    except Exception:
        return -2 ** 31, 2 ** 31 - 1
