"""rasterlabel.dialogs

The windows that ask before anything happens.
"""
import math
import os

from qgis.PyQt.QtCore import QSize, Qt, QUrl
from qgis.PyQt.QtGui import QColor, QDesktopServices, QFont, QFontMetrics
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication,
                                 QButtonGroup, QCheckBox, QColorDialog,
                                 QComboBox, QDialog, QDialogButtonBox,
                                 QFileDialog, QGridLayout, QHBoxLayout,
                                 QHeaderView, QLabel, QLineEdit,
                                 QMessageBox, QPushButton, QRadioButton,
                                 QScrollArea, QSizePolicy, QSpinBox, QStyle,
                                 QTableWidget, QTableWidgetItem, QToolButton,
                                 QVBoxLayout, QWidget)
from qgis.core import QgsProject

from .constants import (BIG_RASTER_PX, BLIND_TIP, BLIND_WORDS,
                        CORRECTION_MANIFEST, FIELD_W,
                        FIRST_CLASS, FORMATS, IGNORE_CODE, MAX_CLASS_CODE,
                        NAME, PALETTE, SETTINGS_ROOT, TABLES, TILE_SIDE_PX,
                        WHOLE_FORMATS)
from .compat import read_setting, run_dialog, write_setting
from .naming import from_folder, guess_role, source_of, tidy, tidy_tag
from .project import (crs_from_text, crs_label, pixel_on_the_ground,
                      project_rasters, reopen_rasters_of)
from .layers import is_report_layer
from .errors import log, shielded
from .campaign import (MAX_PASS, Campaign, describe_existing,
                       frames_closed_for,
                       ignore_refusal, majority, no_room_for_class,
                       operator_sets, reading_choices, reading_shares,
                       readings_in, zip_name)
from .rasters import (class_band_of, count_rows, crs_not_in_file,
                      raster_notes, renderer_bands, thematic_colour,
                      write_crs_beside)
from .correction import doubts_about, peek_correction, undone_of
from .theme import (browse, column_head, follows_width, hold_shape, intro,
                    keep_shape, key_least, key_need, palette_colours, rule,
                    short_combo, swatch_style, text_width, titled)
from .layout import KeyRow
from .widgets import PassBox, narrow_tick


def _path_key(path):
    """A path in the form two paths to one file share: normcase, as
    everywhere a path is compared."""
    try:
        return os.path.normcase(os.path.abspath(str(path).split("|")[0]))
    except Exception:
        return str(path)


#  The legend editor
# =====================================================================
class ClassEditor(QDialog):
    """How many classes, what they are called, what colour they are.

    The code of a class never changes once assigned, because it is already
    inside the exported rasters. Removing a class retires it instead of reusing
    its number."""

    def __init__(self, parent, classes, next_code):
        super().__init__(parent)
        self.setWindowTitle(titled("Classes"))
        self.next_code = next_code
        self.rows = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        outer.addWidget(intro(
            "Classes of the campaign",
            "One row per class. The colour is used on the map, on the chips "
            "and in the legend. Renaming a class renames it in everything "
            "already drawn; its number never changes."))
        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setContentsMargins(8, 6, 8, 6)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(6)
        self.grid.setColumnStretch(1, 1)
        self.grid.addWidget(column_head("no."), 0, 0)
        self.grid.addWidget(column_head("name"), 0, 1)
        self.grid.addWidget(column_head("colour"), 0, 2)
        self.grid.setRowStretch(999, 1)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(holder)
        area.setMinimumHeight(220)
        # Not a stop of its own: Tab goes from the window straight to the
        # first name.
        area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        outer.addWidget(area, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        add = QPushButton("Add class")
        add.setToolTip("One more class, with the next colour of the palette.")
        add.clicked.connect(shielded(self.add_blank, "Add class"))
        row.addWidget(add)
        retire = QPushButton("Retire last")
        retire.setToolTip("Take the last class out of the legend, after asking.\n"
                          "Its number and everything drawn in it are kept.")
        retire.clicked.connect(shielded(self.retire, "Retire class"))
        row.addWidget(retire)
        row.addStretch(1)
        outer.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)
        # What Tab reaches after the last row: the rows are made after the
        # buttons, and were reached after them.
        self.after_rows = [add, retire,
                           bb.button(QDialogButtonBox.StandardButton.Ok),
                           bb.button(QDialogButtonBox.StandardButton.Cancel)]

        for c in classes:
            self.add_row(c["name"], c["colour"], c["code"])
        if not self.rows:
            self.add_blank()
        self.resize(440, 460)
        hold_shape(self, 400)

    def next_colour(self):
        return PALETTE[len(self.rows) % len(PALETTE)]

    def add_blank(self):
        code = self.next_code + sum(1 for r in self.rows if r[3] is None)
        if code > MAX_CLASS_CODE:
            QMessageBox.warning(self, NAME, no_room_for_class())
            return
        self.add_row("class %d" % code, self.next_colour(), None)

    def add_row(self, name, colour, code):
        k = len(self.rows) + 1          # row 0 holds the column names
        number = QLabel(str(code) if code else "new")
        number.setObjectName("quiet")
        number.setAlignment(Qt.AlignmentFlag.AlignRight
                            | Qt.AlignmentFlag.AlignVCenter)
        number.setMinimumWidth(24)
        edit = QLineEdit(name)
        swatch = QPushButton()
        swatch.setFixedWidth(48)
        swatch.setFixedHeight(edit.sizeHint().height())
        swatch.setToolTip("Choose the colour of this class.")
        swatch.setStyleSheet(swatch_style(colour))
        swatch.setProperty("colour", colour)
        swatch.clicked.connect(shielded(
            lambda _, b=swatch: self.pick_colour(b), "Colour"))
        self.grid.addWidget(number, k, 0)
        self.grid.addWidget(edit, k, 1)
        self.grid.addWidget(swatch, k, 2)
        # the rows in order, then the buttons under them
        chain = ([self.rows[-1][2]] if self.rows else []) + [edit, swatch] \
            + getattr(self, "after_rows", [])
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)
        self.rows.append((number, edit, swatch, code))

    def retire(self):
        """Take the last class out of the legend, after asking.

        It must not go without a word, because what it does is not obvious: the
        number is kept and the polygons are kept, but the map paints by name
        from the active classes only, so everything drawn in that class vanishes
        from the screen the moment Ok is pressed. Somebody who pressed this to
        see what it did would watch an afternoon disappear and have no way to
        know it was still there.
        """
        if len(self.rows) <= 1:
            return
        name = ""
        try:
            name = self.rows[-1][1].text().strip()
        except Exception:
            name = ""
        # The button says what it does, as Save, Discard and Cancel do when
        # a campaign is closed: a Yes had to be read back against the
        # question to know what it agreed to.
        ask = QMessageBox(self)
        ask.setIcon(QMessageBox.Icon.Question)
        ask.setWindowTitle(NAME)
        ask.setText("Retire '%s'?" % (name or "this class"))
        ask.setInformativeText(
            "Its number stays reserved and everything drawn in it stays in "
            "the file, but the class leaves the legend, so those marks "
            "stop being drawn on the map and stop being offered as a class "
            "to paint with.\n\nAdding a class with the same name again is "
            "refused, for the same reason.")
        go = ask.addButton("Retire", QMessageBox.ButtonRole.DestructiveRole)
        ask.setDefaultButton(ask.addButton(QMessageBox.StandardButton.Cancel))
        run_dialog(ask)     # one place in the program knows how Qt spells exec
        if ask.clickedButton() is not go:
            return
        for w in self.rows.pop()[:3]:
            self.grid.removeWidget(w)
            w.deleteLater()

    def pick_colour(self, button):
        chosen = QColorDialog.getColor(QColor(button.property("colour")), self)
        if chosen.isValid():
            button.setProperty("colour", chosen.name())
            button.setStyleSheet(swatch_style(chosen.name()))

    def complaints(self):
        """What is wrong with the rows as they stand.

        result() cannot drop a nameless or repeated row without a word:
        Panel.edit_classes would read the shorter list as "this class was
        removed" and retire it. Everything already drawn in that class would
        vanish from the map, because the renderer only builds categories for
        the classes that are still active. One empty box, one afternoon gone.
        So the dialog refuses to close instead."""
        out, seen = [], set()
        for i, (_, edit, _, _) in enumerate(self.rows):
            name = edit.text().strip()
            if not name:
                out.append("row %d has no name" % (i + 1))
            elif name in seen:
                out.append("'%s' is used twice" % name)
            else:
                seen.add(name)
        # Add class refuses the code past the last, so this is the guard for
        # whatever else can put a row here without asking it.
        fresh = sum(1 for r in self.rows if r[3] is None)
        if fresh and self.next_code + fresh - 1 > MAX_CLASS_CODE:
            out.append("a new class would need code %d, and the codes stop "
                       "at %d" % (self.next_code + fresh - 1, MAX_CLASS_CODE))
        return out

    def accept(self):
        wrong = self.complaints()
        if wrong:
            QMessageBox.warning(
                self, NAME,
                "The legend cannot be saved like this:\n\n- "
                + "\n- ".join(wrong)
                + "\n\nThe map is painted by name, so every class needs one "
                  "and no two can share it. To remove a class use Retire "
                  "last, which keeps its number and its polygons.")
            return
        super().accept()

    def result(self):
        out, seen = [], set()
        following = self.next_code
        for _, edit, swatch, code in self.rows:
            name = edit.text().strip()
            if not name or name in seen:
                continue
            seen.add(name)
            if code is None:
                code = following
                following += 1
            out.append({"name": name, "colour": swatch.property("colour"),
                        "code": code})
        return out


#  Creating a campaign
# =====================================================================
class NewCampaign(QDialog):

    def __init__(self, parent, rasters, preferred=None):
        super().__init__(parent)
        self.setWindowTitle(titled("New campaign"))
        # One class to begin with, so that Ok can be pressed and something can
        # be drawn in the first minute. A legend invented before the first
        # stroke is a legend invented too early; this one is renamed in
        # Classes as soon as the ground says what it should be called.
        self.classes = [dict(FIRST_CLASS)]
        self.overwrite = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel("Name"), 0, 0)
        self.name = QLineEdit("campaign")
        grid.addWidget(self.name, 0, 1, 1, 2)

        grid.addWidget(QLabel("Operator"), 1, 0)
        self.operator = QLineEdit("OPERATOR 1")
        # capitals here as well, so the campaign is not born with the one name
        # written in a case that the panel would then fold anyway
        self.operator.textEdited.connect(
            lambda t: (self.operator.text() != t.upper()) and
            self.operator.setText(t.upper()))
        self.operator.setToolTip(
            "Who makes this campaign. Kept in capitals: the same person\n"
            "written two ways would otherwise be two operators, and each\n"
            "operator sees only their own polygons.")
        grid.addWidget(self.operator, 1, 1, 1, 2)

        grid.addWidget(QLabel("Folder"), 2, 0)
        self.folder = QLineEdit("")
        self.folder.setToolTip(
            "Where the campaign is written: a folder holding campaign.json\n"
            "and annotation.gpkg.\n\n"
            "It is filled in for you from the QGIS project, and follows the\n"
            "name until you change it by hand.")
        # Whether the user has taken the folder into their own hands. Until
        # they do, it follows the name: a campaign renamed before Ok should not
        # be written into a folder named after what it was called a minute ago.
        self.folder_by_hand = False
        self.folder.textEdited.connect(self.folder_touched)
        grid.addWidget(self.folder, 2, 1)
        b = browse("Choose the folder of the campaign.")
        b.clicked.connect(shielded(self.choose_folder, "Folder"))
        grid.addWidget(b, 2, 2)
        self.name.textEdited.connect(self.suggest_folder)

        grid.addWidget(QLabel("Reference raster"), 3, 0)
        self.raster = QComboBox()
        for l in rasters:
            self.raster.addItem(l.name(), l.id())
        # the raster the person has in hand, not the first by name: Ok
        # pressed straight away makes the grid of the campaign for good
        if preferred:
            i = self.raster.findData(preferred)
            if i >= 0:
                self.raster.setCurrentIndex(i)
        grid.addWidget(self.raster, 3, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        self.raster.currentIndexChanged.connect(self.show_grid)
        outer.addLayout(grid)

        self.info = QLabel("")
        self.info.setObjectName("quiet")
        self.info.setWordWrap(True)
        outer.addWidget(self.info)

        outer.addWidget(rule())
        how = QLabel("How this campaign is annotated")
        f = how.font()
        f.setBold(True)
        how.setFont(f)
        outer.addWidget(how)
        # The choice in two words, and what it means under it in quiet words
        # that wrap with the window: a radio button does not wrap, and the
        # sentences were broken by hand where the source code broke them.
        self.tiled = QRadioButton("In tiles")
        self.free = QRadioButton("Free")
        self.tiled.setChecked(True)
        self.mode_by_hand = False
        self.tiled.clicked.connect(self.mode_touched)
        self.free.clicked.connect(self.mode_touched)
        g = QButtonGroup(self)
        g.addButton(self.tiled)
        g.addButton(self.free)
        for button, words in (
                (self.tiled, "The partition is closed inside each tile, and "
                             "the edge of the tile is a ready-made contour, "
                             "so a stroke can overshoot and be clipped."),
                (self.free, "Drawn anywhere on the raster. No area is "
                            "guaranteed covered, so the result is a set of "
                            "areas and not a dense partition.")):
            outer.addWidget(button)
            said = QLabel(words)
            said.setObjectName("quiet")
            said.setWordWrap(True)
            said.setContentsMargins(22, 0, 0, 2)
            outer.addWidget(said)

        outer.addWidget(rule())
        row = QHBoxLayout()
        self.summary = QLabel("no class defined")
        self.summary.setWordWrap(True)
        row.addWidget(self.summary, 1)
        b = QPushButton("Classes…")
        b.clicked.connect(shielded(self.edit_classes, "Classes"))
        row.addWidget(b)
        outer.addLayout(row)

        # The slack of a taller window goes here, under the last choice,
        # and not between every row of it.
        outer.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.check)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

        self.update_summary()
        self.show_grid()
        self.resize(540, self.sizeHint().height())

    def folder_touched(self, _text):
        self.folder_by_hand = True

    def mode_touched(self, *args):
        self.mode_by_hand = True

    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Folder of the campaign",
                                             self.folder.text().strip())
        if d:
            self.folder.setText(d)
            self.folder_by_hand = True

    def home_folder(self):
        """Where a campaign should be born.

        The QGIS project first, because that is where the person already
        decided this piece of work lives, and a campaign beside its project is
        a campaign you find again. An unsaved project has no folder at all, and
        then the raster's own folder is the next best guess: the image is on
        disk somewhere, and that somewhere is almost always the right place."""
        try:
            home = QgsProject.instance().homePath()
        except Exception:
            home = ""
        if home and os.path.isdir(home):
            return home
        layer = self.chosen_raster()
        if layer is not None:
            path = source_of(layer)
            folder = os.path.dirname(path)
            if folder and os.path.isdir(folder):
                return folder
        return os.path.expanduser("~")

    def suggest_folder(self, *args):
        """Fill the folder in, unless the user has taken it over.

        A sub folder per campaign, never the project folder bare: two
        campaigns in one project would then land on the same manifest, and the
        second would offer to replace the first, which is not what anybody
        means by making a second campaign."""
        if self.folder_by_hand:
            return
        name = tidy(self.name.text().strip() or "campaign", "campaign")
        # normpath: QGIS spells the folder of a project with slashes, and
        # joined to a backslash that made a path with both in it on Windows
        self.folder.setText(os.path.normpath(
            os.path.join(self.home_folder(), name)))

    def chosen_raster(self):
        return QgsProject.instance().mapLayer(self.raster.currentData())

    def wants_frames(self, layer):
        """Whether this raster asks to be worked in frames.

        Two things say yes. A coordinate system, because frames are pieces of
        ground and a picture with no ground has none; and size, because the
        point of a frame is that a scene too big to finish is cut into pieces
        that can be finished. An orthomosaic at five centimetres is both. A
        screenshot, a photograph, a small clipping is neither, and asking it
        for a frame before a single stroke is asking for nothing."""
        try:
            if not layer.crs().isValid():
                return False, "no coordinate system"
            big = max(layer.width(), layer.height())
            if big >= BIG_RASTER_PX:
                return True, "%d x %d pixels" % (layer.width(), layer.height())
            return False, "%d x %d pixels, small enough to work in one go" \
                % (layer.width(), layer.height())
        except Exception:
            return False, "cannot tell how big it is"

    def show_grid(self):
        l = self.chosen_raster()
        if l is None:
            self.info.setText("")
            return
        px, py = pixel_on_the_ground(l)
        frames, why = self.wants_frames(l)
        # With no system the pixel is in the raster's own units: one to the
        # pixel for a picture, those of its world file for one placed by a
        # world file. The window said "pixel 0.100 x 0.100 m" and, in the
        # same line, that sizes would be in pixels, which was neither.
        if l.crs().isValid():
            first = "pixel %.3f x %.3f m, system %s" % (px, py,
                                                         crs_label(l.crs()))
        elif abs(px - 1.0) < 1e-9 and abs(py - 1.0) < 1e-9:
            first = ("pixel 1 x 1, no coordinate system: sizes are in "
                     "pixels, not metres")
        else:
            first = ("pixel %.3f x %.3f in the units of its world file, no "
                     "coordinate system: sizes are in those units, not "
                     "metres" % (px, py))
        lines = [first,
                 "this is the grid of the campaign and it never changes",
                 "%s, so %s is proposed below"
                 % (why, "in tiles" if frames else "free")]
        if px and abs(px - py) > 0.01 * px:
            lines.append(
                "its pixels are not square on the ground: a frame is square "
                "in pixels, which is what a chip for training needs, so the "
                "%d px frame is %.2f x %.2f%s" % (
                    TILE_SIDE_PX, TILE_SIDE_PX * px, TILE_SIDE_PX * py,
                    " m" if l.crs().isValid() else ""))
        try:
            lines.extend(raster_notes(l))
        except Exception as err:
            log("cannot look further at %s: %s" % (l.name(), err))
        self.info.setText("\n".join(lines))
        # The mode follows the raster until the user touches it: it is a
        # proposal, not a decision, and the two buttons are right there.
        if not self.mode_by_hand:
            self.tiled.setChecked(frames)
            self.free.setChecked(not frames)
        self.suggest_folder()

    def edit_classes(self):
        following = max([c["code"] for c in self.classes] or [0]) + 1
        d = ClassEditor(self, self.classes, following)
        if run_dialog(d):
            self.classes = d.result()
            self.update_summary()

    def update_summary(self):
        if not self.classes:
            self.summary.setText("no class defined")
        elif self.classes == [dict(FIRST_CLASS)]:
            self.summary.setText("one class to start with, %s: rename it in "
                                 "Classes" % FIRST_CLASS["name"])
        else:
            self.summary.setText("%d class%s: %s"
                                 % (len(self.classes),
                                    "" if len(self.classes) == 1 else "es",
                                    ", ".join(c["name"] for c in self.classes)))

    def check(self):
        if not self.folder.text().strip():
            QMessageBox.warning(self, NAME, "Choose a folder for the campaign.")
            return
        if not self.classes:
            QMessageBox.warning(self, NAME, "Define at least one class.")
            return
        if self.chosen_raster() is None:
            QMessageBox.warning(self, NAME, "A reference raster is needed.")
            return
        folder = self.folder.text().strip()
        if os.path.exists(os.path.join(folder, Campaign.MANIFEST)):
            name, counts = describe_existing(folder)
            what = ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items())) \
                or "no readable content"
            ask = QMessageBox(self)
            ask.setIcon(QMessageBox.Icon.Warning)
            ask.setWindowTitle(NAME)
            ask.setText("That folder already holds the campaign '%s' (%s)."
                        % (name, what))
            ask.setInformativeText(
                "Creating a new one here REPLACES it: its legend, its tiles "
                "and everything drawn in it stop being used.\n\n"
                "The old files are not deleted, they are renamed with a "
                "'.replaced-<date>' suffix and stay in the folder.\n\n"
                "To keep working on it instead, cancel and use Open.")
            go = ask.addButton("Replace", QMessageBox.ButtonRole.DestructiveRole)
            ask.setDefaultButton(
                ask.addButton(QMessageBox.StandardButton.Cancel))
            run_dialog(ask)
            if ask.clickedButton() is not go:
                return
            self.overwrite = True
        if not self.offer_system():
            return
        self.accept()

    def offer_system(self):
        """A coordinate system the raster's file does not carry, offered to
        be written beside it before the campaign is made: a .prj beside a
        picture, which GDAL does not read for its format, or a system set on
        the layer in QGIS. The manifest freezes the system when the campaign
        is made, and the masks and cutouts are written through GDAL, which
        knows neither. False when the person cancels."""
        layer = self.chosen_raster()
        try:
            missing = crs_not_in_file(layer) if layer is not None else None
        except Exception as err:
            log("cannot tell whether the file carries its system: %s" % err)
            missing = None
        if missing is None:
            return True
        wkt, label, where = missing
        path = source_of(layer)
        name = os.path.basename(path)
        if where == "prj":
            text = ("A .prj beside '%s' names %s, which QGIS did not apply."
                    % (name, label))
            detail = ("Yes: the layer is set to %s and the system is written "
                      "beside the file, in %s.aux.xml, where GDAL reads it, so "
                      "the campaign, the masks and the cutouts carry it. The "
                      "picture itself is not touched.\n\nNo: the campaign "
                      "is made with no coordinate system, its sizes in the "
                      "units of the world file." % (label, name))
        else:
            text = ("'%s' is in %s in QGIS, but the file itself names no "
                    "coordinate system." % (name, label))
            detail = ("Yes: the system is written beside the file, in "
                      "%s.aux.xml, where GDAL reads it, so the masks and the "
                      "cutouts made from it carry it as the campaign does. "
                      "The picture itself is not touched.\n\nNo: the "
                      "campaign is in %s, and what is written from the raster "
                      "may name no system." % (name, label))
        # Yes first for a .prj, which names the system the picture was made
        # in; No first for a system the layer has in QGIS, which may be the
        # project's, given to any layer that arrives with none.
        q = QMessageBox.question(
            self, NAME, text + "\n\n" + detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes if where == "prj"
            else QMessageBox.StandardButton.No)
        if q == QMessageBox.StandardButton.Cancel:
            return False
        if q != QMessageBox.StandardButton.Yes:
            log("%s: its system was left out of the file, as asked" % name)
            return True
        # QGIS writes back the .aux.xml it holds when it lets go of the file,
        # over whatever was written there meanwhile: so it lets go first, and
        # opens the file again once the system is in it.
        reopen_rasters_of(path)
        written = write_crs_beside(path, wkt)
        reopen_rasters_of(path)
        # On the layer too, which read the file before the system was in it:
        # the campaign takes its system from the layer.
        crs = crs_from_text(wkt)
        if crs.isValid() and not layer.crs().isValid():
            layer.setCrs(crs)
            # The map was drawn in the picture's own numbers, under whatever
            # system the project had. With no other layer placed on the
            # ground, the project takes the picture's system too: otherwise
            # the picture would jump to where its numbers fall in that
            # system, degrees for most, and the next click on it would be
            # refused as a coordinate that cannot be transformed.
            project = QgsProject.instance()
            placed = [other for other in project.mapLayers().values()
                      if other.id() != layer.id() and other.crs().isValid()]
            if not placed and project.crs() != crs:
                project.setCrs(crs)
        layer.triggerRepaint()
        if written:
            log("%s: %s written beside it, in %s.aux.xml" % (name, label, name))
        else:
            QMessageBox.warning(
                self, NAME,
                "%s could not be written beside '%s': the folder may be read "
                "only. The campaign is made with the system the layer has in "
                "QGIS; the masks and cutouts written from the raster may name "
                "none." % (label, name))
        return True


#  Correct: which correction campaign, and its classes
# =====================================================================
class OpenCorrection(QDialog):
    """Which correction: one opened lately, one kept inside the annotation
    campaign that is open, a correction.json chosen by hand, or a new one on
    a thematic map chosen now. None of them needs an annotation campaign.

    start says which of them it opens on: "new" for New in CORRECTION, "open"
    for Open there, nothing for Correct pressed with no correction open. The
    others stay in the list, so a press on the wrong button costs one pick
    and not a second window."""

    def __init__(self, parent, rasters, campaign=None, recent=(),
                 operator="", start=None):
        super().__init__(parent)
        self.setWindowTitle(titled({"new": "New correction",
                                    "open": "Open a correction"}.get(
                                        start, "Correction")))
        self.campaign = campaign
        self.rasters = rasters
        self.picked = None              # a correction.json chosen by hand
        self.folder_by_hand = False
        self.doubts = {}                # map -> what is said about it
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        # Which window this is, whatever the list below is set to, and only
        # what decides: the rest of a long sentence would be a third of the
        # window and the same every time.

        intro = QLabel(
            "A correction never touches the map it starts from. It copies it "
            "once into the folder you choose, band for band, works on the "
            "copy, and keeps beside it which pixels a person changed. It needs "
            "no annotation campaign.")
        intro.setWordWrap(True)
        intro.setObjectName("quiet")
        outer.addWidget(intro)

        top = QGridLayout()
        top.setHorizontalSpacing(8)
        top.addWidget(QLabel("Correction"), 0, 0)
        self.existing = QComboBox()
        # The legacy entries are long: they are cut in the list instead of
        # setting the width of the whole window.
        self.existing.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.existing.setMinimumContentsLength(32)
        self.known = []                 # names already used, for suggest()
        self.made_on = {}               # map -> a correction already made on it
        for path in recent:
            data = peek_correction(path) or {}
            name = data.get("name") or os.path.basename(os.path.dirname(path))
            self.known.append(name)
            if data.get("source"):
                self.made_on.setdefault(_path_key(data["source"]), name)
            made = max(0, int(data.get("operations", 0) or 0)
                       - undone_of(data)["operations"])
            self.existing.addItem(
                "%s   (%s, %d operation%s)"
                % (name, os.path.basename(str(data.get("source") or "?")),
                   made, "" if made == 1 else "s"), "open:" + path)
        if campaign is not None:
            for item in campaign.data.get("corrections", []):
                if item.get("moved_to"):
                    continue
                self.known.append(item.get("name", ""))
                self.existing.addItem(
                    "%s   (kept in campaign %s: opens as its own correction "
                    "campaign)" % (item.get("name", "?"),
                                   campaign.data.get("name", "?")),
                    "legacy:" + str(item.get("name", "")))
        self.existing.addItem("Open a correction.json...", "file:")
        self.existing.addItem("+ new correction campaign", "new:")
        listed = self.existing.count() - 2
        if start == "new":
            first = self.existing.count() - 1
        elif start == "open":
            first = 0
        else:
            first = 0 if listed else self.existing.count() - 1
        self.existing.setCurrentIndex(first)
        self.existing.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.existing, 0, 1)
        top.setColumnStretch(1, 1)
        outer.addLayout(top)

        # The recipe of a new correction, in a box of its own that is shown
        # only when a new correction is what the list says. Six fields greyed
        # out, filled in with a name and a map nobody is going to use, would
        # say that something new will be made when an old one is being opened.
        self.recipe = QWidget()
        grid = QGridLayout(self.recipe)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel("Name"), 1, 0)
        self.name = QLineEdit("")
        self.name.textEdited.connect(self.suggest_folder)
        grid.addWidget(self.name, 1, 1, 1, 2)

        grid.addWidget(QLabel("Thematic map"), 2, 0)
        self.raster = QComboBox()
        for l in rasters:
            self.raster.addItem("%s   [%d band%s]"
                                % (l.name(), l.dataProvider().bandCount(),
                                   "" if l.dataProvider().bandCount() == 1 else "s"),
                                l.id())
        self.raster.setToolTip(
            "The map to correct: a land cover, a mask, the output of a model,\n"
            "made with any program. It is only ever read.")
        self.raster.currentIndexChanged.connect(
            shielded(self.fill_bands, "Raster"))
        self.raster.currentIndexChanged.connect(self.refresh)
        grid.addWidget(self.raster, 2, 1, 1, 2)

        grid.addWidget(QLabel("Class band"), 3, 0)
        self.band = QComboBox()
        grid.addWidget(self.band, 3, 1, 1, 2)

        grid.addWidget(QLabel("Folder"), 4, 0)
        self.folder = QLineEdit("")
        self.folder.setToolTip(
            "Where the correction campaign is written: correction.json, the\n"
            "working copy, operations.csv and the log. Filled in from the QGIS\n"
            "project and the name until you change it by hand.")
        self.folder.textEdited.connect(self.folder_touched)
        self.folder.textChanged.connect(self.refresh)
        grid.addWidget(self.folder, 4, 1)
        self.b_folder = browse("Choose the folder of the correction.")
        self.b_folder.clicked.connect(shielded(self.choose_folder, "Folder"))
        grid.addWidget(self.b_folder, 4, 2)

        grid.addWidget(QLabel("Operator"), 5, 0)
        self.operator = QLineEdit((operator or "").upper())
        self.operator.textEdited.connect(
            lambda t: (self.operator.text() != t.upper()) and
            self.operator.setText(t.upper()))
        self.operator.setToolTip(
            "Who corrects. Written on every row of operations.csv, in capitals\n"
            "like everywhere else in the program.")
        grid.addWidget(self.operator, 5, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        outer.addWidget(self.recipe)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setObjectName("quiet")
        outer.addWidget(self.note)
        outer.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        outer.addWidget(buttons)
        self.name.setText(self.suggest())
        self.fill_bands()
        self.suggest_folder()
        self.refresh()
        self.resize(560, self.sizeHint().height())

    def home_folder(self):
        """Where a correction campaign should be born: beside the QGIS
        project, as a campaign is, and failing that the home folder."""
        try:
            home = QgsProject.instance().homePath()
        except Exception:
            home = ""
        if home and os.path.isdir(home):
            return home
        return os.path.expanduser("~")

    def suggest(self):
        """The first name not already taken.

        Compared in the form the name is STORED in. result() puts it through
        tidy(), so what is on disk is "correction_1" and what this compared was
        "correction 1": the loop never matched, the suggestion was always
        "correction 1", and the panel then refused it as already taken. The
        dialog offered a name and the program rejected it. Taken means a
        correction listed here, or a folder of that name already beside the
        project, where the new one would be born.
        """
        taken = {tidy(n or "", "correction") for n in self.known}
        home = self.home_folder()
        n = 1
        while tidy("correction %d" % n, "correction") in taken \
                or os.path.exists(os.path.join(
                    home, tidy("correction %d" % n, "correction"))):
            n += 1
        return "correction %d" % n

    def folder_touched(self, _text):
        self.folder_by_hand = True

    def suggest_folder(self, *args):
        """The folder follows the name until it is changed by hand, and is
        never one that already holds something: a correction gets a folder
        of its own."""
        if self.folder_by_hand:
            return
        base = os.path.join(self.home_folder(),
                            tidy(self.name.text().strip() or "correction",
                                 "correction"))
        folder, k = base, 2
        while os.path.exists(folder) and (not os.path.isdir(folder)
                                          or os.listdir(folder)):
            folder = "%s_%d" % (base, k)
            k += 1
        self.folder.setText(folder)

    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, "Folder of the correction campaign",
            self.folder.text().strip() or self.home_folder())
        if d:
            self.folder.setText(d)
            self.folder_by_hand = True

    def choice(self):
        """What the top line says, as (kind, path or name). Kept in the combo
        as one string, "kind:value": a tuple put there comes back as another
        object and findData() can then never find it."""
        kind, _, value = str(self.existing.currentData() or "new:").partition(":")
        return kind, value or None

    def warnings(self):
        """What is worth knowing about the map and the folder chosen for a new
        correction before Ok is pressed. The panel asks again, with buttons,
        when Ok is: this only says it early."""
        layer = self.chosen_raster()
        if layer is None:
            return []
        source = source_of(layer)
        # what the map itself is: on a rotated grid, a picture in colour,
        # or stored with a compression that does not keep values exactly.
        # Read once per map: this runs on every key typed in the folder.
        if source not in self.doubts:
            self.doubts[source] = list(doubts_about(source))
        out = list(self.doubts[source])
        name = self.made_on.get(_path_key(source))
        if name:
            out.append("This map already has the correction '%s': choose it in "
                       "the list above to go on with it." % name)
        folder = self.folder.text().strip()
        if folder and _path_key(folder) == _path_key(os.path.dirname(source)):
            out.append("That folder is the map's own: the correction's files "
                       "would sit beside the original. A folder of its own is "
                       "better.")
        return out

    def refresh(self, *args):
        if not hasattr(self, "note"):
            return              # a signal while the window is still being built
        kind, _ = self.choice()
        fresh = kind == "new"
        for w in (self.name, self.raster, self.band, self.folder,
                  self.b_folder, self.operator):
            w.setEnabled(fresh)
        self.recipe.setVisible(fresh)
        # OK says what it does in this window: open, choose, or make
        self.ok.setText({"open": "Open", "legacy": "Open",
                         "file": "Choose file…", "new": "Create"}[kind])
        # A warning is not a hint: in the colour of one, after the hint.
        said = self.warnings() if fresh else []
        self.note.setText({
            "open": "The correction opens as it was left.",
            "legacy": "This correction was kept inside the annotation campaign. "
                      "It opens where it is, as a correction campaign of its "
                      "own: a correction.json is written beside its working "
                      "copy, nothing is moved, and the campaign keeps a "
                      "pointer to it.",
            "file": "Choose the correction.json of a correction campaign.",
            "new": "The classes are read from the map and shown to you before "
                   "the copy is made."}[kind]
            + "".join("<br><br><span style='color:%s'>%s</span>"
                      % (palette_colours()["danger"], w) for w in said))
        self.adjustSize()
        self.resize(max(self.width(), 560), self.sizeHint().height())
        # never smaller than its words need: in Open, without the fields of
        # a new correction to hold it up, the intro was cut in half
        hold_shape(self, 440)

    def fill_bands(self, *args):
        self.band.clear()
        layer = self.chosen_raster()
        if layer is None:
            return
        provider = layer.dataProvider()
        for b in range(1, provider.bandCount() + 1):
            self.band.addItem("band %d   %s" % (b, provider.generateBandName(b)), b)
        self.band.setCurrentIndex(max(0, class_band_of(layer) - 1))

    def chosen_raster(self):
        return QgsProject.instance().mapLayer(self.raster.currentData())

    def accept(self):
        kind, _ = self.choice()
        if kind == "file":
            chosen, _ = QFileDialog.getOpenFileName(
                self, "Open a correction: choose its %s" % CORRECTION_MANIFEST,
                self.home_folder(),
                "%s correction (%s);;All files (*)" % (NAME, CORRECTION_MANIFEST))
            if not chosen:
                return
            self.picked = chosen
        elif kind == "new":
            if not self.folder.text().strip():
                QMessageBox.warning(self, NAME,
                                    "Choose a folder for the correction.")
                return
            if self.chosen_raster() is None:
                QMessageBox.warning(self, NAME, "Choose the map to correct.")
                return
        super().accept()

    def result(self):
        """("open", path to a correction.json), ("legacy", the name of a
        record in the annotation campaign), or ("new", the recipe)."""
        kind, value = self.choice()
        if kind == "file":
            return "open", self.picked
        if kind in ("open", "legacy"):
            return kind, value
        return "new", {"name": tidy(self.name.text().strip(), "correction"),
                       "layer": self.chosen_raster(),
                       "band": self.band.currentData() or 1,
                       "folder": self.folder.text().strip(),
                       "operator": self.operator.text().strip().upper()}


class ConfirmClasses(QDialog):
    """The classes read from a thematic map, shown before anything is made.

    Correct reads them by itself: from the style of the layer when it names
    them, from the colour table of the file, from the values when nothing
    else does. A reading is a guess, and a wrong guess was only found out
    after the copy existed, as chips with the wrong names. So the user sees
    every value with its colour and its name first, and changes what is
    wrong.

    Changing a value points a name and a colour at another number. It never
    recodes a pixel: the values are what is written in the map, and every
    value the map holds needs a row. Values in locked are those the copy
    already holds corrections in, and cannot be changed at all."""

    def __init__(self, parent, classes, counts, source_name, band, nodata,
                 code_range, locked=(), again=False):
        super().__init__(parent)
        self.setWindowTitle(titled("Classes of the correction" if again
                                   else "Classes of the map"))
        self.reading = [dict(c) for c in classes]
        self.counts = dict(counts or {})
        self.total = max(1, sum(self.counts.values()))
        self.nodata = nodata
        self.low, self.high = code_range
        self.locked = set(int(v) for v in locked)
        self.rows = []
        outer = QVBoxLayout(self)
        if again:
            text = ("These are the classes of this correction, as they were "
                    "confirmed. The value is what is written in the copy of "
                    "band %d of %s; the colour and the name are what the chips "
                    "and the copy are drawn with. Values the copy already "
                    "holds are locked: only a class added later can be "
                    "renumbered." % (band, source_name))
        else:
            text = ("These are the classes read from band %d of %s: from its "
                    "style where it names them, from its colour table, or from "
                    "the values themselves. The value is what is written in "
                    "the map; the colour and the name are what the chips and "
                    "the copy are drawn with. Look them over and change what "
                    "is wrong %s. The campaign legend is not used."
                    % (band, source_name,
                       "before the copy is made" if not self.locked else
                       "before correcting: the copy exists already, so its "
                       "values are locked and only names and colours change"))
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        outer.addWidget(intro(
            "Check the classes of the correction" if again
            else "Check the classes read from the map",
            text + " Changing a value gives the name and the colour to "
                   "another number: no pixel is recoded."))
        if nodata is not None:
            nd = QLabel("nodata: %s, not a class" % _shown(nodata))
            nd.setObjectName("quiet")
            outer.addWidget(nd)

        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(8, 6, 8, 6)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(6)
        self.grid.setColumnStretch(2, 1)
        column.addLayout(self.grid)
        column.addStretch(1)
        for i, head in enumerate(("value", "colour", "name", "pixels", "from",
                                  "")):
            self.grid.addWidget(column_head(head), 0, i)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(holder)
        area.setMinimumHeight(240)
        outer.addWidget(area, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        b = QPushButton("Add class")
        b.setToolTip("A class the map does not hold yet, at the next free value.")
        b.clicked.connect(shielded(self.add_blank, "Add class"))
        row.addWidget(b)
        b = QPushButton("Read again")
        b.setToolTip("Throw the changes away and go back to what was read.")
        b.clicked.connect(shielded(self.read_again, "Read again"))
        row.addWidget(b)
        row.addStretch(1)
        outer.addLayout(row)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Use these classes")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)
        self.fill(self.reading)
        self.resize(640, 480)
        hold_shape(self, 600)

    # ------------------------------------------------------------- rows
    def fill(self, classes):
        for r in self.rows:
            for w in r["widgets"]:
                self.grid.removeWidget(w)
                w.setParent(None)
                w.deleteLater()
        self.rows = []
        for c in classes:
            self.add_row(int(c["code"]), c.get("colour") or "#888888",
                         c.get("name") or "", c.get("origin") or "value")

    def add_row(self, code, colour, name, origin):
        k = len(self.rows) + 1
        value = QSpinBox()
        value.setRange(max(self.low, -2 ** 31), min(self.high, 2 ** 31 - 1))
        value.setValue(code)
        value.setFixedWidth(84)
        value.setAlignment(Qt.AlignmentFlag.AlignRight)
        value.setEnabled(code not in self.locked)
        if code in self.locked:
            value.setToolTip("The copy already holds corrections in this "
                             "class: its value cannot change.")
        swatch = QPushButton()
        swatch.setFixedWidth(48)
        swatch.setToolTip("Choose the colour of this class.")
        swatch.setStyleSheet(swatch_style(colour))
        swatch.setProperty("colour", colour)
        swatch.clicked.connect(shielded(
            lambda _=False, b=swatch: self.pick_colour(b), "Colour"))
        edit = QLineEdit(name)
        pixels = QLabel("")
        pixels.setObjectName("quiet")
        source = QLabel(origin)
        source.setObjectName("quiet")
        remove = QPushButton("Remove")
        remove.setToolTip("Remove this class. Only a class the map does not "
                          "hold can go.")
        entry = {"value": value, "swatch": swatch, "name": edit,
                 "pixels": pixels, "origin": source, "remove": remove,
                 "widgets": [value, swatch, edit, pixels, source, remove]}
        remove.clicked.connect(shielded(
            lambda _=False, e=entry: self.remove_row(e), "Remove"))
        value.valueChanged.connect(lambda _v, e=entry: self.show_count(e))
        for i, w in enumerate(entry["widgets"]):
            self.grid.addWidget(w, k, i)
        self.rows.append(entry)
        self.show_count(entry)
        return entry

    def show_count(self, entry):
        code = entry["value"].value()
        n = self.counts.get(code, 0)
        if n:
            share = 100.0 * n / self.total
            # A class that is there is never written as nought per cent.
            entry["pixels"].setText("{:,}  ({})".format(
                n, "<0.1%" if share < 0.05 else "%.1f%%" % share).replace(
                ",", "\u2009"))
        else:
            entry["pixels"].setText("not in the map")
        entry["remove"].setEnabled(n == 0 and code not in self.locked)

    def pick_colour(self, button):
        chosen = QColorDialog.getColor(QColor(button.property("colour")), self)
        if chosen.isValid():
            button.setProperty("colour", chosen.name())
            button.setStyleSheet(swatch_style(chosen.name()))

    def add_blank(self):
        used = {r["value"].value() for r in self.rows}
        code = max(list(used) + [self.low - 1]) + 1
        while code in used or (self.nodata is not None and code == self.nodata):
            code += 1
        code = min(code, self.high)
        entry = self.add_row(code, thematic_colour(len(self.rows)),
                             "class %d" % code, "added")
        entry["name"].setFocus()

    def remove_row(self, entry):
        if entry not in self.rows:
            return
        if self.counts.get(entry["value"].value(), 0):
            return
        self.rows.remove(entry)
        for w in entry["widgets"]:
            self.grid.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        for k, r in enumerate(self.rows, start=1):
            for i, w in enumerate(r["widgets"]):
                self.grid.addWidget(w, k, i)

    def read_again(self):
        self.fill(self.reading)

    # ------------------------------------------------------------- answer
    def complaints(self):
        """What is wrong with the rows as they stand, the way ClassEditor
        says it: the dialog refuses to close rather than fix things
        quietly. name_classes() would have renamed a repeated name without
        a word, and the user would have met it later on a chip."""
        out, seen_codes, seen_names = [], set(), set()
        for i, r in enumerate(self.rows):
            code = r["value"].value()
            name = r["name"].text().strip()
            if code in seen_codes:
                out.append("value %d is used twice" % code)
            seen_codes.add(code)
            if self.nodata is not None and code == self.nodata:
                out.append("%d is the nodata value of this map: painting it "
                           "would erase the pixels, not correct them." % code)
            if not name:
                out.append("row %d has no name" % (i + 1))
            elif name in seen_names:
                out.append("'%s' is used twice" % name)
            seen_names.add(name)
        for code in sorted(self.counts):
            if code not in seen_codes:
                out.append("value %d is in the map and has no class: every "
                           "value it holds needs one" % code)
        return out

    def accept(self):
        wrong = self.complaints()
        if wrong:
            QMessageBox.warning(
                self, NAME,
                "The classes cannot be used like this:\n\n- "
                + "\n- ".join(wrong))
            return
        super().accept()

    def result(self):
        return [{"code": r["value"].value(),
                 "name": r["name"].text().strip(),
                 "colour": r["swatch"].property("colour")} for r in self.rows]


def _shown(value):
    try:
        return "%d" % value if float(value) == int(value) else str(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)


#  Which reading goes out
# =====================================================================
def reading_box(package):
    """A list of the readings the package holds, to choose what goes out:
    all of them together, one, or a consensus. Returns the box and the
    choices behind its rows."""
    choices = reading_choices(readings_in(package))
    box = QComboBox()
    for c in choices:
        box.addItem(c["label"])
    box.setToolTip(
        "A reading is one operator's work in one pass.\n\n"
        "All readings together paints them one on top of the other, the\n"
        "last drawn on top: right when the passes are layers of one piece\n"
        "of work, wrong when two people read the same ground, because the\n"
        "second one then erases the first wherever they differ.\n\n"
        "One reading is that operator in that pass, and nobody else.\n\n"
        "A consensus gives each pixel the class more than half of the\n"
        "readings gave it: of two readings, the class both gave it.")
    return box, choices


def _listed(names):
    """ANNA, BRUNO and CARLO."""
    names = list(names)
    if len(names) < 2:
        return "".join(names)
    return "%s and %s" % (", ".join(names[:-1]), names[-1])


def reading_note(choice, whole):
    """The line under the list, for the reading chosen."""
    readings = [tuple(r) for r in choice.get("readings") or []]
    if choice["mode"] == "one":
        return ("Only what %s drew in pass %d. The files are named after it."
                % readings[0])
    if choice["mode"] == "consensus":
        n, need = len(readings), majority(len(readings))
        # "at least 2 of the 2 readings" is "both"
        who = ("both readings" if n == 2 else
               "at least %d of the %d readings" % (need, n))
        if whole:
            return ("Each pixel takes the class %s gave it, and 0 where %s. "
                    "Beside the mask, a _votes.tif counts, pixel by pixel, "
                    "the readings that gave it that class and those that "
                    "painted it at all. A frame that only some of them "
                    "read is voted by those: the majority is of the "
                    "readings that covered the frame."
                    % (who, "they do not agree" if n == 2
                       else "no class has that many"))
        return ("The polygons are the ground %s give the same class, with "
                "how many did in 'votes', out of the readings that covered "
                "the frame in 'readings'. Lines, points and boxes go out for "
                "the readings that took part, each with its own operator and "
                "pass." % who)
    crowded = {}
    for op, p in readings:
        crowded.setdefault(p, []).append(op)
    shared = [(p, ops) for p, ops in sorted(crowded.items()) if len(ops) > 1]
    if shared:
        # every pass read by more than one operator, not only the first
        said = ["%s read pass %d" % (_listed(shared[0][1]), shared[0][0])]
        said += ["%s, pass %d" % (_listed(ops), p) for p, ops in shared[1:]]
        return ("%s. One on top of the other, the reading drawn last wins "
                "wherever they differ, so what comes out is nobody's "
                "reading: choose one reading, or a consensus."
                % "; ".join(said))
    if len(readings) > 1:
        return ("The passes go in one on top of the other, the last drawn on "
                "top: right when they are layers of one piece of work.")
    return ""


#  The cutouts module
# =====================================================================
class CutoutSetup(QDialog):
    """Which layers go into the cutouts, and as what, and which one sets the
    grid.

    The rows come in the order they are given, which is the order of the
    Layers panel. Which layer sets the pixel grid is chosen here, in so many
    words: "the first one not ignored" would leave no way to choose it, and
    the first one would be the first by name."""

    def __init__(self, parent, rasters, remembered, grid_id=None):
        super().__init__(parent)
        self.setWindowTitle(titled("Layers to cut"))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        # Two sentences that wrap with the window; what 'classes' and 'image'
        # do is on the list of each row, where the choice is made.
        words = QLabel(
            "The layers are listed as in the Layers panel, top first. The one "
            "chosen below sets the pixel grid and the coordinate system: every "
            "other layer is read onto that same grid, reprojected when it is "
            "in another system, so the pieces come out the same size and can "
            "be stacked.")
        words.setWordWrap(True)
        words.setObjectName("quiet")
        outer.addWidget(words)

        line = QHBoxLayout()
        line.setSpacing(6)
        line.addWidget(QLabel("Pixel grid from"))
        self.grid_from = QComboBox()
        for layer in rasters:
            self.grid_from.addItem(layer.name(), layer.id())
        ids = [layer.id() for layer in rasters]
        if grid_id in ids:
            self.grid_from.setCurrentIndex(ids.index(grid_id))
        else:
            for k, layer in enumerate(rasters):
                saved = remembered.get(layer.id(), {})
                if (saved.get("role") or guess_role(layer)) != "ignore":
                    self.grid_from.setCurrentIndex(k)
                    break
        self.grid_from.setToolTip(
            "The layer whose pixels the cutouts are taken on. Its pixel size\n"
            "turns the side in metres into pixels, its coordinate system is\n"
            "the one every file is written in, and the other layers are read\n"
            "onto its grid, reprojected from their own system if it is\n"
            "another. A layer stored bottom row first can set it too: its\n"
            "cutouts come out top row first, like every other. A layer set to\n"
            "'ignore' cannot set it: then the first layer that is cut does.")
        line.addWidget(self.grid_from, 1)
        self.grid_note = QLabel("")
        self.grid_note.setObjectName("quiet")
        line.addWidget(self.grid_note)
        outer.addLayout(line)

        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setSpacing(6)
        for i, head in enumerate(("cut as", "layer", "class band",
                                  "R G B", "format", "name in the files")):
            label = QLabel("<b>%s</b>" % head)
            grid.addWidget(label, 0, i)

        self.rows = []
        self.made = {}
        taken = set()
        for r, layer in enumerate(rasters, start=1):
            saved = remembered.get(layer.id(), {})
            role = QComboBox()
            for word in ("ignore", "image", "classes"):
                role.addItem(word)
            role.setCurrentText(saved.get("role") or guess_role(layer))
            role.setToolTip(
                "image: written as it is, every band in its own data type, and\n"
                "its PNG is a picture of it as QGIS shows it.\n"
                "classes: for a layer of class codes, read band by band without\n"
                "stretching and never written as JPEG.\n"
                "ignore: left out.")
            grid.addWidget(role, r, 0)

            # A long layer name is cut, whole in its tooltip, so it cannot
            # push the column that names the files out of the window.
            name = QLabel()
            title = "%s   [%d]" % (layer.name(), layer.dataProvider().bandCount())
            name.setText(name.fontMetrics().elidedText(
                title, Qt.TextElideMode.ElideMiddle, 190))
            name.setToolTip(title)
            grid.addWidget(name, r, 1)

            band = QComboBox()
            for b in range(1, layer.dataProvider().bandCount() + 1):
                band.addItem("%d  %s" % (b, layer.dataProvider().generateBandName(b)), b)
            band.setCurrentIndex(max(0, (saved.get("band")
                                         or class_band_of(layer)) - 1))
            band.setMaximumWidth(160)
            grid.addWidget(band, r, 2)

            rgb_holder = QWidget()
            rgb_row = QHBoxLayout(rgb_holder)
            rgb_row.setContentsMargins(0, 0, 0, 0)
            rgb_row.setSpacing(3)
            rgb = []
            guess = saved.get("rgb") or renderer_bands(layer)
            for k in range(3):
                box = QComboBox()
                box.setMaximumWidth(64)
                for b in range(1, layer.dataProvider().bandCount() + 1):
                    box.addItem(str(b), b)
                box.setCurrentIndex(max(0, min(guess[k],
                                               layer.dataProvider().bandCount()) - 1))
                rgb.append(box)
                rgb_row.addWidget(box)
            grid.addWidget(rgb_holder, r, 3)

            shape = QComboBox()
            for word, driver, extension, exact, _ in WHOLE_FORMATS:
                shape.addItem("%s  %s" % (word, extension), driver)
            want = saved.get("driver") or "GTiff"
            k = shape.findData(want)
            shape.setCurrentIndex(k if k >= 0 else 0)
            shape.setMaximumWidth(120)
            shape.setToolTip(
                "The file this layer comes out as.\n\n"
                "A layer cut as 'classes' is never written as JPEG whatever is\n"
                "picked here: the numbers in it are meaning, not brightness,\n"
                "and a lossy codec would hand back 4.2 where 4 was stored.")
            grid.addWidget(shape, r, 4)

            # a long name loses its middle, never its ending (see tidy_tag);
            # a tag the folder kept comes back as it was
            tag = QLineEdit(
                tidy_tag(saved["tag"], room=255) if saved.get("tag")
                else tidy_tag(layer.name()))
            base, k = tag.text(), 2
            while tag.text().lower() in taken:
                tag.setText("%s_%d" % (base, k))
                k += 1
            taken.add(tag.text().lower())
            self.made[tag] = tag.text()
            tag.setMinimumWidth(130)
            grid.addWidget(tag, r, 5)

            self.rows.append((layer, role, band, rgb, tag, rgb_holder, shape))
            role.currentIndexChanged.connect(self.refresh)
        # The slack of the scroll area goes below the rows. Without a row to
        # take it, Qt gave it to the header, whose labels are the only things
        # in the grid allowed to grow in height: a band of empty space a
        # hundred pixels tall opened between the title of each column and the
        # rows under it.
        grid.setRowStretch(len(rasters) + 1, 1)
        self.grid_from.currentIndexChanged.connect(self.refresh)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self.refresh()
        # Wide enough to show every column, the name of the files included,
        # which would otherwise open behind a scroll bar; never wider than
        # the screen.
        # Tall enough for three rows at least.
        want = holder.sizeHint().width() + 48
        try:
            room = QApplication.primaryScreen().availableGeometry()
            want = min(want, int(room.width() * 0.9))
        except Exception:
            pass
        rows = min(len(rasters), 6)
        self.setMinimumHeight(min(260 + 34 * min(rows, 3), 480))
        self.resize(max(want, 560), min(240 + 34 * max(rows, 3), 560))

    def refresh(self, *args):
        for layer, role, band, rgb, tag, rgb_holder, shape in self.rows:
            word = role.currentText()
            band.setEnabled(word == "classes")
            rgb_holder.setEnabled(word == "image")
            tag.setEnabled(word != "ignore")
            shape.setEnabled(word != "ignore")
        chosen = self.grid_layer()
        self.grid_note.setText(
            "" if chosen is None or chosen.id() == self.grid_from.currentData()
            else "ignored: %s sets it" % chosen.name())

    def grid_layer(self):
        """The layer that will set the grid: the one chosen, or, when that one
        is ignored, the first that is cut."""
        cut = [row[0] for row in self.rows if row[1].currentText() != "ignore"]
        for layer in cut:
            if layer.id() == self.grid_from.currentData():
                return layer
        return cut[0] if cut else None

    def result(self):
        out = []
        taken = set()
        for layer, role, band, rgb, tag, _, shape in self.rows:
            word = role.currentText()
            if word == "ignore":
                continue
            driver = shape.currentData() or "GTiff"
            # a layer of class codes never goes out as JPEG, whatever the row
            # says: the codes are meaning, and a lossy codec reshuffles them
            if word == "classes" and driver == "JPEG":
                driver = "GTiff"
            # the names are made unique AFTER tidy(), not before. Two layers
            # called "Aragona 2025" and "Aragona-2025" both tidy down to
            # "Aragona_2025", and with the old order both kept that stem and
            # the second one wrote over the first without a word.
            # A tag left as the window made it is read back whole, a "_2"
            # included. One the person typed is held to the usual length,
            # because it becomes part of a file name.
            stem = tidy_tag(tag.text().strip(), "layer",
                            room=255 if tag.text() == self.made.get(tag)
                            else 48)
            # And compared without case, because these become file names. On
            # Windows "RGB" and "rgb" are one file, so two rows that differed
            # only in case passed this loop and then the second one wrote over
            # the first, silently, in the middle of a dataset.
            base, k = stem, 2
            while stem.lower() in taken:
                stem = "%s_%d" % (base, k)
                k += 1
            taken.add(stem.lower())
            out.append({"id": layer.id(), "layer": layer, "role": word,
                        "band": band.currentData(),
                        "rgb": [b.currentData() for b in rgb],
                        "driver": driver, "tag": stem})
        # the layer that sets the grid goes first, the others keep the order
        # of the Layers panel
        chosen = self.grid_layer()
        if chosen is not None:
            out.sort(key=lambda s: 0 if s["id"] == chosen.id() else 1)
        return out


WHOLE_LEAST_W = 300


class WholeRaster(QDialog):
    """What to write when the whole raster goes out, annotation and all."""

    def __init__(self, parent, campaign, folder):
        super().__init__(parent)
        self.setWindowTitle(titled("Whole raster"))
        self.campaign = campaign
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        row = 0

        def part(words):
            label = QLabel(words)
            label.setWordWrap(True)
            f = label.font()
            f.setBold(True)
            label.setFont(f)
            return label

        grid.addWidget(QLabel("Raster"), row, 0)
        self.raster = QComboBox()
        # The campaign's own raster first, then any but the maps of a report:
        # the list is by name, and the first in it would be the one offered,
        # which after Compare is the map of the disagreement.
        # the manifest holds it by its way from the campaign's folder
        reference = os.path.normcase(os.path.abspath(str(from_folder(
            (campaign.data.get("grid") or {}).get("reference_raster") or "",
            campaign.folder))))
        own, plain = None, None
        for lyr in project_rasters(need_crs=False):
            self.raster.addItem(lyr.name(), lyr.id())
            i = self.raster.count() - 1
            if own is None and os.path.normcase(os.path.abspath(
                    lyr.source().split("|")[0])) == reference:
                own = i
            if plain is None and not is_report_layer(lyr):
                plain = i
        if own is not None or plain is not None:
            self.raster.setCurrentIndex(own if own is not None else plain)
        short_combo(self.raster)
        grid.addWidget(self.raster, row, 1, 1, 2)
        row += 1

        self.size_note = QLabel("")
        self.size_note.setObjectName("quiet")
        self.size_note.setWordWrap(True)
        grid.addWidget(self.size_note, row, 1, 1, 2)
        row += 1

        grid.addWidget(part("What to write"), row, 0, 1, 3)
        row += 1
        self.want = {}
        for key, words, tip, on in (
                ("painted", "the image with the annotation on it",
                 "The raster as QGIS shows it, in the colours of its style,\n"
                 "with the polygons, lines, points and boxes painted over it.",
                 True),
                ("mask", "the mask of class codes",
                 "One band, the class code of every pixel, and zero, or the\n"
                 "ignore value chosen below, where nobody annotated. For\n"
                 "training and for counting, not for looking at.",
                 True),
                ("plain", "the visible image, nothing on it",
                 "The raster as QGIS shows it, with no annotation: its style,\n"
                 "and an alpha band where it shows anything see-through.\n"
                 "Pixel for pixel it lines up with the mask.", False),
                ("figure", "a picture for a figure",
                 "The painted image again, in the picture format chosen below,\n"
                 "to drop into a paper or a talk.", False),
                ("card", "the dataset card, with the pixel counts of this "
                         "mask",
                 "Writes <mask>_card.md and <mask>_card.json beside the files:\n"
                 "the classes and how many pixels each holds in every reading,\n"
                 "in all readings together and in their consensus, the frames\n"
                 "and which reading completes them, who drew what, the rules\n"
                 "that made the pixels, the grid and the build of RasterLabel,\n"
                 "with the SHA-256 of every file written and whether the mask\n"
                 "holds the counts the card gives. Beside a GeoTIFF mask with a\n"
                 "coordinate system, a STAC item too. Nothing in the campaign\n"
                 "changes. It counts every reading at full size, which takes a\n"
                 "while on a large campaign, so it starts unticked.",
                 # Off on a first use, so that Whole is as quick as it was
                 # before the card; once chosen, the choice is remembered.
                 self.remembered("whole_card", False, bool))):
            # a tick box that wraps: "the dataset card, with the pixel counts
            # of this mask" is one line wider than a window of 300 pixels
            box = narrow_tick(words)
            box.setChecked(on)
            box.setToolTip(tip)
            grid.addWidget(box, row, 0, 1, 3)
            self.want[key] = box
            row += 1

        # Whose work: with two operators on one frame, every reading painted
        # on top of every other would be the one mask this could write, and it
        # would be neither reading.
        grid.addWidget(part("Which reading"), row, 0, 1, 3)
        row += 1
        grid.addWidget(QLabel("Readings"), row, 0)
        self.reading, self.choices = reading_box(campaign.package_path)
        short_combo(self.reading)
        grid.addWidget(self.reading, row, 1, 1, 2)
        row += 1
        self.reading_note = QLabel("")
        self.reading_note.setObjectName("quiet")
        self.reading_note.setWordWrap(True)
        grid.addWidget(self.reading_note, row, 1, 1, 2)
        row += 1

        # What the mask holds where nobody painted. 0, as always, until it
        # is chosen otherwise on this machine: a training script that skips
        # unlabelled pixels has to be told which value they are, and 0 is
        # also what a frame nobody painted holds, "none of these".
        self.unlabelled_part = []
        head = part("Where nobody painted")
        grid.addWidget(head, row, 0, 1, 3)
        self.unlabelled_part.append(head)
        row += 1
        words = QLabel("Pixels")
        grid.addWidget(words, row, 0)
        self.unlabelled_part.append(words)
        self.unlabelled = QComboBox()
        for label, data in (("0, as before", "zero"),
                            ("the ignore value everywhere", "ignore"),
                            ("0 in the frames, the ignore value outside",
                             "frames")):
            self.unlabelled.addItem(label, data)
        self.unlabelled.setToolTip(
            "0, as before: what every mask has held where nobody painted.\n\n"
            "The ignore value everywhere: that value instead, declared as\n"
            "the nodata of the mask, for a loss told ignore_index.\n\n"
            "0 in the frames, the ignore value outside: inside a frame the\n"
            "ground nobody painted is 0, a class meaning 'none of these';\n"
            "outside every frame nobody looked, and it is the ignore value.")
        self.has_frames = count_rows(campaign.package_path, "tiles") > 0
        if not self.has_frames:
            # greyed with the reason, the way Qt greys an item of a list
            item = self.unlabelled.model().item(2)
            if item is not None:
                item.setEnabled(False)
                item.setToolTip("the campaign has no frames")
        short_combo(self.unlabelled)
        grid.addWidget(self.unlabelled, row, 1, 1, 2)
        self.unlabelled_part.append(self.unlabelled)
        row += 1
        words = QLabel("Ignore value")
        grid.addWidget(words, row, 0)
        self.unlabelled_part.append(words)
        self.ignore_value = QSpinBox()
        self.ignore_value.setRange(-32768, 65535)
        self.ignore_value.setFixedWidth(FIELD_W)
        self.ignore_value.setToolTip(
            "255 by default: past every class code a campaign hands out\n"
            "(1 to %d), and still one byte. 0 and the class codes are\n"
            "refused. Not a foreground: samgeo and Deepness write 255 for\n"
            "the foreground of a binary mask, the opposite meaning."
            % MAX_CLASS_CODE)
        grid.addWidget(self.ignore_value, row, 1)
        self.unlabelled_part.append(self.ignore_value)
        row += 1
        self.unlabelled_note = QLabel("")
        self.unlabelled_note.setObjectName("quiet")
        self.unlabelled_note.setWordWrap(True)
        grid.addWidget(self.unlabelled_note, row, 1, 1, 2)
        self.unlabelled_part.append(self.unlabelled_note)
        row += 1
        self.shares = None              # measured only when frames is chosen
        kept = self.remembered("whole_unlabelled", "zero", str)
        at = self.unlabelled.findData(kept)
        if at < 0 or (kept == "frames" and not self.has_frames):
            at = 0
        self.unlabelled.setCurrentIndex(at)
        self.ignore_value.setValue(
            self.remembered("whole_ignore", IGNORE_CODE, int))

        grid.addWidget(part("How"), row, 0, 1, 3)
        row += 1
        grid.addWidget(QLabel("Format"), row, 0)
        self.shape = QComboBox()
        for label, _, extension, exact, _ in WHOLE_FORMATS:
            self.shape.addItem("%s (%s)" % (label, extension))
        short_combo(self.shape)
        grid.addWidget(self.shape, row, 1, 1, 2)
        row += 1
        # Under the format, across the window: in a column of its own the
        # note widened that column and stretched the folder's button into a
        # bar the moment JPEG was picked.
        self.shape_note = QLabel("")
        self.shape_note.setObjectName("quiet")
        self.shape_note.setWordWrap(True)
        grid.addWidget(self.shape_note, row, 1, 1, 2)
        row += 1

        grid.addWidget(QLabel("Scale"), row, 0)
        self.scale = QComboBox()
        for n in (1, 2, 4, 8, 16):
            self.scale.addItem("full size" if n == 1 else
                               "1:%d (%s)" % (n, {2: "half size",
                                                  4: "a quarter",
                                                  8: "an eighth",
                                                  16: "a sixteenth"}[n]), n)
        short_combo(self.scale)
        grid.addWidget(self.scale, row, 1, 1, 2)
        row += 1

        grid.addWidget(QLabel("Paint"), row, 0)
        self.alpha = QSpinBox()
        self.alpha.setRange(10, 100)
        self.alpha.setValue(45)
        self.alpha.setSuffix(" %")
        self.alpha.setToolTip(
            "How solid the areas are painted. The thin things, lines, points\n"
            "and box outlines, are always drawn solid: a trace blended into a\n"
            "busy image is a trace nobody can follow.")
        grid.addWidget(self.alpha, row, 1)
        row += 1

        grid.addWidget(part("Drawn on it"), row, 0, 1, 3)
        row += 1
        self.extras = {}
        for key, words, on in (("want_lines", "draw the traces of the lines", True),
                               ("want_points", "draw the points", True),
                               ("want_boxes", "draw the outlines of the boxes", True),
                               ("points_in_mask", "let the points into the mask too",
                                False)):
            box = narrow_tick(words)
            box.setChecked(on)
            grid.addWidget(box, row, 0, 1, 3)
            self.extras[key] = box
            row += 1
        self.extras["points_in_mask"].setToolTip(
            "Off, the mask holds only what the areas claim, which is what the\n"
            "cutouts have always written. On, every point burns its own pixel\n"
            "over the top.")

        # headed as in Export, its sibling: otherwise the last row is a folder
        # under the tick boxes with nothing to say it is not one of them
        grid.addWidget(part("Where"), row, 0, 1, 3)
        row += 1
        grid.addWidget(QLabel("Folder"), row, 0)
        self.folder = QLineEdit(folder)
        grid.addWidget(self.folder, row, 1)
        pick = browse("Choose where to write.")
        pick.clicked.connect(shielded(self.choose_folder, "Folder"))
        grid.addWidget(pick, row, 2)
        row += 1
        grid.setRowStretch(row, 1)
        row += 1

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        grid.addWidget(buttons, row, 0, 1, 3)

        self.raster.currentIndexChanged.connect(self.describe)
        self.scale.currentIndexChanged.connect(self.describe)
        self.shape.currentIndexChanged.connect(self.describe)
        self.reading.currentIndexChanged.connect(self.describe)
        self.unlabelled.currentIndexChanged.connect(self.describe)
        self.ignore_value.valueChanged.connect(self.describe)
        # only the mask has unlabelled pixels: without it the block says
        # nothing about anything that is written
        self.want["mask"].toggled.connect(self.describe)
        self.describe()
        # opens as wide as Export, so a path in the folder field can be read,
        # and can be made as narrow as the other windows of the measures
        self.resize(max(self.sizeHint().width(), 460), self.sizeHint().height())
        keep_shape(self, WHOLE_LEAST_W)

    def note_room(self):
        """How wide a note under a list is at the narrowest the window can be:
        the window, less its margins and the column of names beside it. A grid
        does not ask a wrapped label how tall it is, so the note is told."""
        grid = self.layout()
        margins = grid.contentsMargins()
        names = text_width(self.fontMetrics(), "Ignore value")
        return max(1, WHOLE_LEAST_W - margins.left() - margins.right()
                   - grid.horizontalSpacing() - names)

    def choose_folder(self):
        got = QFileDialog.getExistingDirectory(self, "Where to write",
                                               self.folder.text())
        if got:
            self.folder.setText(got)

    def chosen_raster(self):
        return QgsProject.instance().mapLayer(self.raster.currentData())

    def describe(self, *args):
        lyr = self.chosen_raster()
        n = self.scale.currentData() or 1
        if lyr is None:
            self.size_note.setText("no raster loaded")
        else:
            w = max(1, lyr.width() // n)
            h = max(1, lyr.height() // n)
            self.size_note.setText(
                "%d x %d pixels out%s"
                % (w, h, "" if lyr.crs().isValid()
                   else "  ·  no coordinate system: it goes out as a picture"))
        label, driver, extension, exact, _ = WHOLE_FORMATS[
            max(0, self.shape.currentIndex())]
        self.shape_note.setText(
            "" if exact else
            "JPEG changes the values it stores, so the mask is written as a "
            "GeoTIFF anyway: a class code that came back as 4.2 would be a "
            "different class. A JPEG holds no transparency either: what QGIS "
            "shows see-through comes out white.")
        self.shape_note.setVisible(not exact)
        # A grid does not ask a wrapped label how tall it is at its width,
        # so the note is told, for the narrowest the window can be.
        room = self.note_room()
        self.shape_note.setMinimumHeight(
            self.shape_note.heightForWidth(room) if not exact else 0)
        said = reading_note(self.chosen_reading(), True)
        self.reading_note.setText(said)
        self.reading_note.setVisible(bool(said))
        self.reading_note.setMinimumHeight(
            self.reading_note.heightForWidth(room) if said else 0)
        masked = self.want["mask"].isChecked()
        for w in self.unlabelled_part:
            w.setEnabled(masked)
        mode = self.chosen_unlabelled()
        self.ignore_value.setEnabled(masked and mode != "zero")
        told = self.unlabelled_said(driver)
        self.unlabelled_note.setText(told)
        self.unlabelled_note.setMinimumHeight(
            self.unlabelled_note.heightForWidth(room) if told else 0)
        # and the window grows with the note, never cuts it
        if self.layout() is not None:
            hold_shape(self, WHOLE_LEAST_W)

    def remembered(self, key, default, kind=str):
        """A choice kept on this machine by the Cutouts module that opened
        the window, or the default when there is none."""
        ask = getattr(self.parent(), "setting", None)
        if not callable(ask):
            return default
        try:
            return ask(key, default, kind)
        except Exception:
            return default

    def remember(self, key, value):
        keep = getattr(self.parent(), "keep_setting", None)
        if callable(keep):
            try:
                keep(key, value)
            except Exception as err:
                log("cannot remember %s: %s" % (key, err))

    def chosen_unlabelled(self):
        mode = self.unlabelled.currentData() or "zero"
        if mode == "frames" and not self.has_frames:
            return "zero"
        return mode

    def frames_counted(self):
        """(frames, closed) for the reading chosen, measured once."""
        if self.shares is None:
            try:
                self.shares = reading_shares(self.campaign.package_path)
            except Exception as err:
                log("cannot measure the frames: %s" % err)
                self.shares = {}
        return frames_closed_for(self.shares, self.chosen_reading())

    def unlabelled_said(self, driver=None):
        """The line under the ignore value: what the mask will hold."""
        mode = self.chosen_unlabelled()
        v = self.ignore_value.value()
        consensus = self.chosen_reading().get("mode") == "consensus"
        if mode == "zero":
            return ("0 where nobody painted, as always. TorchGeo, ArcGIS and "
                    "EasySegment can be told ignore_index=0; Segmentation "
                    "Gym and MMSegmentation train 0 as a class.")
        why = ignore_refusal(v, self.class_codes())
        if why:
            return "This value cannot be used: %s." % why
        if mode == "ignore":
            out = ("%d where nobody painted, declared as nodata: a training "
                   "script reads it as ignore_index=%d. It is not a "
                   "foreground: samgeo and Deepness write 255 for that."
                   % (v, v))
        else:
            n, closed = self.frames_counted()
            how = {"one": "", "consensus": " by the readings that read it"
                   }.get(self.chosen_reading().get("mode"),
                         " by every reading chosen")
            out = ("Inside a frame, ground nobody painted is 0, a class "
                   "meaning 'none of these'. Outside every frame it is %d. "
                   "%d frame%s, %d of them closed%s."
                   % (v, n, "" if n == 1 else "s", closed, how))
            if closed < n:
                out += (" %d frame%s not closed: %s unpainted ground goes "
                        "out as 0, a claim nobody made. Close them, or "
                        "choose the ignore value everywhere."
                        % (n - closed, " is" if n - closed == 1 else "s are",
                           "its" if n - closed == 1 else "their"))
        if consensus:
            out += (" Where the readings do not agree is %d too; the "
                    "_votes.tif says where." % v)
        if v < 0 and driver == "PNG":
            out += (" A negative value needs 16 signed bits, so the mask is "
                    "written as a GeoTIFF.")
        return out

    def class_codes(self):
        """Every code of the legend, retired ones included."""
        out = set()
        for c in self.campaign.data.get("classes") or []:
            try:
                out.add(int(c["code"]))
            except (KeyError, TypeError, ValueError):
                pass
        return out

    def accept(self):
        mode = self.chosen_unlabelled()
        if self.want["mask"].isChecked() and mode != "zero":
            why = ignore_refusal(self.ignore_value.value(), self.class_codes())
            if why:
                QMessageBox.warning(self, titled("Whole raster"),
                                    "The ignore value cannot be used: %s."
                                    % why)
                return
        if self.want["mask"].isChecked():
            self.remember("whole_unlabelled", mode)
            self.remember("whole_ignore", int(self.ignore_value.value()))
        self.remember("whole_card", bool(self.want["card"].isChecked()))
        super().accept()

    def chosen_reading(self):
        return self.choices[max(0, self.reading.currentIndex())]

    def result(self):
        label, driver, extension, exact, _ = WHOLE_FORMATS[
            max(0, self.shape.currentIndex())]
        mode = self.chosen_unlabelled() if self.want["mask"].isChecked() \
            else "zero"
        return {"layer": self.chosen_raster(),
                "reading": self.chosen_reading(),
                "kinds": [k for k, b in self.want.items() if b.isChecked()],
                "driver": driver, "extension": extension, "exact": exact,
                "scale": self.scale.currentData() or 1,
                "alpha": self.alpha.value(),
                "folder": self.folder.text().strip(),
                "unlabelled": mode,
                "ignore": None if mode == "zero"
                else int(self.ignore_value.value()),
                "extras": {k: b.isChecked() for k, b in self.extras.items()}}


class ExportVectors(QDialog):
    """What to take out, in what shape, and where to put it."""

    def __init__(self, parent, campaign, tile_id=None):
        super().__init__(parent)
        self.setWindowTitle(titled("Export"))
        self.campaign = campaign
        self.tile_id = tile_id
        self.source = campaign.package_path
        # Decided by the manifest, which is where the campaign keeps its
        # system: "" for a picture, or a world file with no system. The
        # tables cannot say it on every GDAL (export.tables_have_system).
        self.system = bool((campaign.data.get("grid") or {}).get("crs"))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(6)

        outer.addWidget(QLabel("<b>What to write</b>"))
        self.tables = []
        for name, _, _ in TABLES:
            rows = count_rows(self.source, name)
            box = QCheckBox("%s (%d)" % (name, rows))
            box.setChecked(rows > 0)
            box.setEnabled(rows > 0)
            # the line under the folder says which files: it follows the boxes
            box.toggled.connect(self.describe)
            outer.addWidget(box)
            self.tables.append((name, box))
        # The card belongs to the files it describes, so it is written with
        # them; it can be written on its own too, with every table unticked.
        self.card = narrow_tick("dataset card (Markdown + JSON)")
        self.card.setChecked(read_setting(self.CARD_KEY, True, bool))
        self.card.setToolTip(
            "Writes <campaign>_card.md and <campaign>_card.json beside the\n"
            "files: the classes and how many pixels each holds in every\n"
            "reading, in all readings together and in their consensus, the\n"
            "frames and which reading completes them, who drew what, the\n"
            "rules that made the pixels, the grid, and the build of\n"
            "RasterLabel. It covers the whole campaign, every reading,\n"
            "whatever is chosen below; it says what this export held.\n"
            "Nothing in the campaign changes.")
        self.card.toggled.connect(self.describe)
        outer.addWidget(self.card)

        if tile_id:
            self.only_tile = narrow_tick("only what belongs to frame %s" % tile_id)
            self.only_tile.setToolTip(
                "Every chosen table is narrowed down to this one frame, the\n"
                "frames table included: a frame carries its own name in\n"
                "tile_id, so what comes out is that frame and the polygons,\n"
                "lines, points and boxes drawn inside it, and nothing else.\n"
                "Leave it unticked to write the whole campaign.")
            self.only_tile.toggled.connect(self.describe)
            outer.addSpacing(4)
            outer.addWidget(self.only_tile)
        else:
            self.only_tile = None

        outer.addSpacing(6)
        outer.addWidget(QLabel("<b>Which reading</b>"))
        self.reading, self.choices = reading_box(self.source)
        short_combo(self.reading, 12)
        self.reading.currentIndexChanged.connect(self.describe)
        outer.addWidget(self.reading)
        self.reading_note = QLabel("")
        self.reading_note.setWordWrap(True)
        self.reading_note.setObjectName("quiet")
        outer.addWidget(self.reading_note)

        # How the readings are laid out in the files. One per operator holds
        # every pass of each operator, so it only makes sense for all the
        # readings together: a single reading or a consensus is one set.
        outer.addSpacing(6)
        outer.addWidget(QLabel("<b>How the readings are arranged</b>"))
        self.arrange = QComboBox()
        self.arrange.addItem("everything in one")
        self.arrange.addItem("one per operator")
        short_combo(self.arrange, 12)
        self.arrange.setToolTip(
            "Everything in one: a single set of files holding every reading,\n"
            "with the operator and the pass as attributes of each mark.\n\n"
            "One per operator: a set of files for each operator, named after\n"
            "them, holding all the passes of that operator (the pass is an\n"
            "attribute). Offered with 'all readings together'.")
        self.arrange.currentIndexChanged.connect(self.describe)
        outer.addWidget(self.arrange)

        outer.addSpacing(6)
        outer.addWidget(QLabel("<b>In what shape</b>"))
        self.shape = QComboBox()
        for label, _, _, _, _ in FORMATS:
            self.shape.addItem(label)
        short_combo(self.shape, 12)
        self.shape.currentIndexChanged.connect(self.describe)
        outer.addWidget(self.shape)

        self.degrees = narrow_tick("in longitude and latitude")
        self.degrees.setToolTip(
            "Off, the coordinates come out as they were drawn, in the system of\n"
            "the raster. On, they are turned into degrees. GeoJSON and KML are\n"
            "always written in degrees: that is what those two formats mean by\n"
            "a coordinate.")
        outer.addWidget(self.degrees)

        outer.addSpacing(6)
        outer.addWidget(QLabel("<b>Where</b>"))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.where = QLineEdit(os.path.join(campaign.folder, "export"))
        row.addWidget(self.where, 1)
        pick = browse("Choose the folder to write into.")
        pick.clicked.connect(shielded(self.choose, "Choose"))
        row.addWidget(pick)
        outer.addLayout(row)

        self.zip = narrow_tick("also pack it all in one .zip")
        self.zip.setToolTip(
            "Besides the files, writes one .zip in the same folder holding\n"
            "all of them: every format chosen, the dataset card and what\n"
            "goes beside a file (the .prj of a CSV, the parts of a\n"
            "shapefile). The names inside are relative to the folder.")
        self.zip.toggled.connect(self.describe)
        outer.addWidget(self.zip)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setObjectName("quiet")
        outer.addWidget(self.note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        outer.addStretch(1)
        outer.addWidget(buttons)
        self.describe()
        # opened comfortable, but free to be made as narrow as a dock: the
        # words wrap and the lists keep to the room they are given
        self.resize(max(self.sizeHint().width(), 460),
                    self.sizeHint().height())

    def choose(self):
        folder = QFileDialog.getExistingDirectory(self, "Where to write",
                                                  self.where.text())
        if folder:
            self.where.setText(folder)

    def chosen_format(self):
        return FORMATS[max(0, self.shape.currentIndex())]

    def chosen_reading(self):
        return self.choices[max(0, self.reading.currentIndex())]

    def by_operator(self):
        """Whether the files are written one set per operator: asked for, and
        offered for every reading together only."""
        return self.arrange.currentIndex() == 1 and self.arrange.isEnabled()

    def refused(self):
        """Why the chosen format cannot be written, or "" when it can."""
        label, driver, extension, one_file, forced = self.chosen_format()
        if driver == "KML" and not self.system:
            return ("KML holds longitude and latitude only, and this campaign "
                    "has no coordinate system: its coordinates are pixels, or "
                    "the units of a world file. Pick another format: they "
                    "write the coordinates as they were drawn.")
        return ""

    def say(self, text):
        """The note under the folder. A file name is one long word, and a
        label cannot be narrower than its longest word: a break is allowed
        after each underscore (a zero-width space), so the note wraps at 300
        pixels whatever the campaign is called."""
        self.note.setText(text.replace("_", "_&#8203;"))

    def describe(self, *args):
        label, driver, extension, one_file, forced = self.chosen_format()
        if not self.system:
            # nothing to turn into degrees: the box would only promise it
            self.degrees.setChecked(False)
            self.degrees.setEnabled(False)
            self.degrees.setToolTip(
                "This campaign has no coordinate system, so there is nothing\n"
                "to turn into longitude and latitude: the coordinates come\n"
                "out as they were drawn, in pixels or in the units of the\n"
                "world file.")
        else:
            self.degrees.setEnabled(forced is None)
            if forced is not None:
                self.degrees.setChecked(True)
        # one per operator is for all the readings together; with one reading
        # or a consensus the choice goes back to one set and is greyed
        whole = self.chosen_reading().get("mode", "all") == "all"
        if not whole and self.arrange.currentIndex() != 0:
            self.arrange.blockSignals(True)
            self.arrange.setCurrentIndex(0)
            self.arrange.blockSignals(False)
        self.arrange.setEnabled(whole)
        said = reading_note(self.chosen_reading(), False)
        self.reading_note.setText(said)
        self.reading_note.setVisible(bool(said))
        why = self.refused()
        if getattr(self, "ok", None) is not None:
            self.ok.setEnabled(not why)
        if why:
            self.say(why)
            return
        names = [n for n, box in self.tables if box.isChecked()]
        card = ("<b>%s_card.md</b> / .json" % self.campaign.stem
                if self.card.isChecked() else "")
        if not names:
            self.say("only the dataset card: %s" % card if card
                              else "nothing chosen")
            return
        plain_card = ("; and %s" % card) if card else ""
        # The same stem the layers are named with, so a table on disk and
        # the layer it came from answer to the same word, and the reading
        # after it when it is not every reading together.
        stem = self.campaign.stem
        if self.chosen_reading().get("tag"):
            stem += "_" + self.chosen_reading()["tag"]
        listed = names[0] if len(names) == 1 else \
            "%s and %s" % (", ".join(names[:-1]), names[-1])
        only = ""
        if self.only_tile is not None and self.only_tile.isChecked():
            only = ", only what belongs to frame %s" % self.tile_id
        # GeoJSON means degrees; with no system it can only be pixels, and a
        # reader that takes them for degrees is told nothing else by the file
        plain = "" if self.system or forced is None else (
            "<br>no coordinate system: written in pixels, or the units of "
            "the world file, not in longitude and latitude")
        packed = ("<br>and all of it in <b>%s</b>" % zip_name(stem)
                  if self.zip.isChecked() else "")
        stems = [stem]
        if self.by_operator():
            stems = ["%s_%s" % (stem, one["tag"]) for one in operator_sets(
                self.chosen_reading().get("readings") or [])] or [stem]
        if one_file:
            made = ["<b>%s%s</b>" % (s, extension) for s in stems]
        else:
            made = ["<b>%s_%s%s</b>" % (s, n, extension)
                    for s in stems for n in names]
        shown = ", ".join(made[:4]) + (
            ", and %d more" % (len(made) - 4) if len(made) > 4 else "")
        if len(stems) > 1:
            self.say("%d files, one set per operator: %s%s%s%s%s" % (
                len(made), shown, only, plain_card, plain, packed))
        elif one_file:
            self.say("one file: %s, with %s inside it%s%s%s%s"
                              % (shown, listed, only, plain_card, plain,
                                 packed))
        else:
            self.say("%d file%s: %s%s%s%s%s" % (
                len(names), "" if len(names) == 1 else "s", shown, only,
                plain_card, plain, packed))

    CARD_KEY = SETTINGS_ROOT + "/export/card"

    def accept(self):
        if self.refused():
            # the button is greyed out for it already; this is for Enter
            return
        try:
            write_setting(self.CARD_KEY, bool(self.card.isChecked()))
        except Exception as err:
            log("cannot remember the card choice: %s" % err)
        super().accept()

    def result(self):
        label, driver, extension, one_file, forced = self.chosen_format()
        return {"tables": [n for n, box in self.tables if box.isChecked()],
                "driver": driver, "extension": extension,
                "one_file": one_file,
                "crs": "EPSG:4326" if self.system and (
                    forced or self.degrees.isChecked()) else None,
                "system": self.system,
                "tile_id": self.tile_id if (self.only_tile is not None
                                            and self.only_tile.isChecked())
                           else None,
                "reading": self.chosen_reading(),
                "arrange": "operator" if self.by_operator() else "one",
                "zip": bool(self.zip.isChecked()),
                "card": bool(self.card.isChecked()),
                "folder": self.where.text().strip()}


class WhoIsDrawing(QDialog):
    """Who is drawing, in which pass, and whether only that pass is shown:
    the reading every mark is filed under.

    Shown before the first stroke when the reading remembered for a campaign
    was not this session's, and from Objects, which has no box of its own for
    it. A reading taken on without being seen is how a blind second reader
    ended up drawing as the first one."""

    def __init__(self, parent, why, names, reading, passes=None):
        super().__init__(parent)
        # which passes an operator has: asked of the panel, which knows the
        # campaign; a window made without one offers the pass in hand
        self.passes = passes or (lambda who: [1])
        self.setWindowTitle(titled("Who is drawing"))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        outer.addWidget(intro("Who is drawing, in which pass", why))
        grid = QGridLayout()
        grid.setSpacing(6)
        self.operator = QComboBox()
        self.operator.setEditable(True)
        for who in names:
            if self.operator.findText(who) < 0:
                self.operator.addItem(who)
        self.operator.setCurrentText(reading.get("operator") or "")
        self.operator.setToolTip(
            "The name every mark is written with. Kept in capitals, so one\n"
            "person written two ways cannot become two operators.")
        edit = self.operator.lineEdit()
        if edit is not None:
            edit.textEdited.connect(self.upper_as_typed)
        grid.addWidget(QLabel("operator"), 0, 0)
        grid.addWidget(self.operator, 0, 1)
        self.pass_no = PassBox()
        self.pass_no.setToolTip(
            "The passes this operator has. A second, independent reading of\n"
            "the same ground is pass 2: the + makes the next one.")
        self.fill_passes(int(reading.get("pass") or 1))
        self.operator.currentTextChanged.connect(self.fill_passes)
        self.add_pass_button = QToolButton()
        self.add_pass_button.setText("+")
        self.add_pass_button.setAutoRaise(True)
        self.add_pass_button.setToolTip("Add the next pass for this operator.")
        self.add_pass_button.clicked.connect(self.add_pass)
        row = QHBoxLayout()
        row.addWidget(self.pass_no, 1)
        row.addWidget(self.add_pass_button)
        grid.addWidget(QLabel("pass"), 1, 0)
        grid.addLayout(row, 1, 1)
        outer.addLayout(grid)
        self.blind = QCheckBox(BLIND_WORDS)
        self.blind.setChecked(bool(reading.get("blind", True)))
        self.blind.setToolTip(BLIND_TIP)
        outer.addWidget(self.blind)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Draw as this reading")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def fill_passes(self, keep=None):
        """The passes of the operator in the box, standing on keep when the
        operator has it and on pass 1 when not: a new operator starts at pass
        1 whatever pass the last one was in."""
        who = self.operator.currentText().strip().upper()
        have = list(self.passes(who) or [1])
        if not isinstance(keep, int):
            keep = self.pass_no.value()
        if getattr(self, "_new", None) and self._new[0] == who:
            have += self._new[1]
        self.pass_no.fill(have, keep)

    def add_pass(self):
        who = self.operator.currentText().strip().upper()
        have = self.pass_no.values()
        if max(have) >= MAX_PASS:
            return
        self._new = (who, list(getattr(self, "_new", (None, []))[1])
                     + [max(have) + 1])
        self.fill_passes(max(have) + 1)

    def upper_as_typed(self, text):
        up = (text or "").upper()
        edit = self.operator.lineEdit()
        if up == text or edit is None:
            return
        at = edit.cursorPosition()
        edit.blockSignals(True)
        edit.setText(up)
        edit.setCursorPosition(at)
        edit.blockSignals(False)

    def accept(self):
        # a reading needs somebody: an empty name would file every mark
        # under nobody, where no filter can find it again
        if not self.operator.currentText().strip():
            self.operator.setFocus()
            return
        super().accept()

    def chosen(self):
        return {"operator": self.operator.currentText().strip().upper(),
                "pass_no": self.pass_no.value(),
                "blind": self.blind.isChecked()}


#  Reports: where they go, and the window that shows one
# =====================================================================
# Every measure has the same three windows: a setup, a progress with Cancel,
# and this report. The setup windows share their last part, Where, and the
# report window is one for all of them, so a number reads the same way
# whichever measure wrote it. An undefined value, a rate over nothing, is a
# dash and never a zero.
REPORT_NONE = "—"


def report_part(words):
    """A bold heading of a setup window, as in Whole raster."""
    label = QLabel(words)
    label.setWordWrap(True)
    f = label.font()
    f.setBold(True)
    label.setFont(f)
    return label


def report_where_rows(grid, row, folder, maps=True, columns=3):
    """The Where part of a setup window, from row on in grid: the folder
    the report will be written in, which shows the reports/<kind>/<label>_
    <stamp> folder to be made and can be changed to another, and "put the
    maps in QGIS". Returns (next row, the folder field, the tick box)."""
    grid.addWidget(report_part("Where"), row, 0, 1, columns)
    row += 1
    grid.addWidget(QLabel("Folder"), row, 0)
    field = QLineEdit(str(folder or ""))
    field.setToolTip("The report goes in a new folder of its own, never over "
                     "an older one.\nChange it to write the report elsewhere.")
    grid.addWidget(field, row, 1, 1, max(1, columns - 2))
    pick = browse("Choose the folder the report is written in.")

    def choose():
        start = field.text().strip()
        got = QFileDialog.getExistingDirectory(
            grid.parentWidget(), "Where to write the report",
            os.path.dirname(start) if start else "")
        if got:
            field.setText(os.path.join(got, os.path.basename(start))
                          if start else got)
            # setText() is silent where typing is not, and a window that
            # listens to textEdited (to keep a folder the person chose, to
            # check its length) has to hear a folder picked here as well
            field.textEdited.emit(field.text())

    pick.clicked.connect(shielded(choose, "Folder"))
    grid.addWidget(pick, row, columns - 1)
    row += 1
    box = narrow_tick("put the maps in QGIS")
    box.setChecked(bool(maps))
    box.setToolTip("Load the maps of the report into the project, in a group "
                   "of their own\nunder this one's. They are in the folder "
                   "either way.")
    grid.addWidget(box, row, 0, 1, columns)
    return row + 1, field, box


def report_shown(value, digits=4):
    """A value as Copy writes it: a dash for nothing and for a number that
    is not one, a number to four figures, anything else as it is. Plain,
    with no grouping, so a spreadsheet reads it back as a number."""
    if value is None:
        return REPORT_NONE
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return REPORT_NONE
        return "%.*g" % (digits, value)
    return str(value)


# What the window draws. A narrow no-break space sets the thousands apart: a
# comma is a decimal point in half the world, and a plain space lets a number
# break over two lines.
REPORT_THIN = " "


def report_group(text):
    """The digits of an integer part with the thousands set apart."""
    sign = "-" if text.startswith("-") else ""
    digits = text.lstrip("-")
    out = []
    while len(digits) > 3:
        out.insert(0, digits[-3:])
        digits = digits[:-3]
    out.insert(0, digits)
    return sign + REPORT_THIN.join(out)


def report_number(value, fmt):
    """A number as the window draws it. fmt is "int", "f1" to "f4" (that
    many decimals) or "pct" (a share, to one decimal): a column has one
    format, so its figures stand on the same digits."""
    if value is None or isinstance(value, bool):
        return report_shown(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return REPORT_NONE
    if fmt == "pct":
        return report_number(100.0 * value, "f1") + " %"
    if fmt == "int":
        return report_group("%d" % round(value))
    decimals = int(fmt[1:]) if fmt and fmt[0] == "f" else 3
    whole, _, rest = ("%.*f" % (decimals, value)).partition(".")
    return report_group(whole) + ("." + rest if rest else "")


def report_screen(value):
    """A value of the headline as the window draws it: integers grouped,
    decimals fixed (three for a ratio, two for an amount), tiny values in powers of
    ten rather than as a row of zeros, anything else as it is."""
    if isinstance(value, float) and not isinstance(value, bool) \
            and not (math.isnan(value) or math.isinf(value)):
        if value != 0 and abs(value) < 0.0005:
            return "%.1e" % value
        return report_number(value, "f3" if abs(value) <= 1 else "f2")
    if isinstance(value, int) and not isinstance(value, bool):
        return report_number(value, "int")
    return report_shown(value)


def report_is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def report_column_formats(rows, columns, given=()):
    """One format per column: the one the table asked for, or by what the
    column holds. All integers: "int". Numbers with a fraction: three
    decimals while they are ratios (none above one), two once they are
    amounts. Anything else is text, None."""
    out = []
    for c in range(columns):
        asked = given[c] if c < len(given) else None
        if asked:
            out.append(asked)
            continue
        values = [row[c] for row in rows if c < len(row)]
        shown = [v for v in values if v is not None]
        numbers = [v for v in shown if report_is_number(v)
                   and not (isinstance(v, float)
                            and (math.isnan(v) or math.isinf(v)))]
        odd = [v for v in shown if not report_is_number(v)]
        if not numbers or odd:
            out.append(None)
        elif all(isinstance(v, int) for v in numbers):
            out.append("int")
        else:
            out.append("f3" if max(abs(v) for v in numbers) <= 1.0 else "f2")
    return out


class ReportTable(QTableWidget):
    """A table as tall as its rows. It scrolls only past SHOWN of them, and
    sideways only when the window is narrower than its columns; the column
    of names takes up the slack, or gives way to it, and elides."""
    SHOWN = 12

    def __init__(self, rows, columns, grow=None):
        super().__init__(rows, columns)
        self.grow = grow
        self.needs = []
        self.least = 0
        self.bar_said = False
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)
        self.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)

    def widths(self, needs, least):
        """The width each column asks for, and the least the column that
        takes the slack may be given."""
        self.needs = list(needs)
        self.least = least
        for c, w in enumerate(self.needs):
            self.setColumnWidth(c, w)

    def total(self, grown):
        return sum(w if c != self.grow else grown
                   for c, w in enumerate(self.needs))

    def bar(self):
        """The scroll bar along the foot, wanted when the columns do not fit
        even with the column of names at its least."""
        return bool(self.needs) and self.width() < \
            self.total(self.least) + 2 * self.frameWidth() + self.vbar()

    def vbar(self):
        if self.rowCount() <= self.SHOWN:
            return 0
        return self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)

    def high(self):
        shown = min(self.rowCount(), self.SHOWN)
        h = self.horizontalHeader().sizeHint().height() + 2 * self.frameWidth()
        h += sum(self.rowHeight(r) for r in range(shown))
        if self.bar():
            h += self.style().pixelMetric(
                QStyle.PixelMetric.PM_ScrollBarExtent)
        return h

    def sizeHint(self):
        return QSize(self.total(self.needs[self.grow]
                                if self.grow is not None and self.needs else 0)
                     + 2 * self.frameWidth() + self.vbar(), self.high())

    def minimumSizeHint(self):
        return QSize(self.fontMetrics().height() * 8, self.high())

    def fit(self):
        if self.grow is None or not self.needs:
            return
        others = self.total(0) + 2 * self.frameWidth() + self.vbar()
        room = self.width() - others
        want = self.needs[self.grow]
        self.setColumnWidth(self.grow, room if room >= want
                            else max(self.least, room))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.fit()
        if self.bar() != self.bar_said:
            self.bar_said = self.bar()
            self.updateGeometry()


class ReportWindow(QDialog):
    """What a measure found, shared by every report.

    A quiet line first, saying over what and how much ("11 frames ·
    440 000 px labelled by both"); then the headline numbers; then a table
    per part, each row with its colour when it is a class; then the notes
    that qualify the numbers. Copy puts the whole of it on the clipboard as
    tab separated text, for a spreadsheet or a message; Open folder shows
    the files.

    headline is [(name, value)], tables is [{"title", "columns", "rows",
    "colours"}] with colours one per row or none, notes is [sentence]. A
    table may also say "formats" ("int", "f1" to "f4", "pct" or None, a
    column each), "align" ("r" for a text that is a figure, as an interval
    is) and "tips" (the words of a column's tooltip). Left alone, a column
    of numbers is right aligned with one number of decimals, or none."""

    def __init__(self, parent, what, scope="", headline=(), tables=(),
                 notes=(), folder=None):
        super().__init__(parent)
        self.setWindowTitle(titled(what))
        self.what = what
        self.scope = scope or ""
        self.headline = [(str(k), v) for k, v in (headline or [])]
        self.tables = list(tables or [])
        self.notes = [str(n) for n in (notes or []) if n]
        self.folder = folder
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        if self.scope:
            line = QLabel(self.scope)
            line.setObjectName("quiet")
            line.setWordWrap(True)
            outer.addWidget(line)
        if self.headline:
            numbers = QGridLayout()
            numbers.setHorizontalSpacing(12)
            numbers.setVerticalSpacing(4)
            numbers.setColumnStretch(1, 1)
            for i, (name, value) in enumerate(self.headline):
                # both wrap: a name such as "Quantity + allocation
                # disagreement" or a sentence for a value held the window at
                # 358 px in DejaVu, and the window is made for 300
                said = QLabel(name)
                said.setWordWrap(True)
                numbers.addWidget(said, i, 0)
                shown = QLabel(report_screen(value))
                shown.setWordWrap(True)
                f = shown.font()
                f.setBold(True)
                shown.setFont(f)
                shown.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse)
                numbers.addWidget(shown, i, 1)
            outer.addLayout(numbers)
        self.views = []
        for table in self.tables:
            if table.get("title"):
                outer.addWidget(report_part(str(table["title"])))
            view = self.table_view(table)
            self.views.append(view)
            outer.addWidget(view)
        if self.notes:
            outer.addWidget(rule())
        for note in self.notes:
            words = QLabel(note)
            words.setWordWrap(True)
            words.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            outer.addWidget(words)
        # what is left over goes under the notes, not between the parts
        outer.addStretch(1)
        # a row of keys that shares the width it has and wraps when it must:
        # three side by side held the window at 303 px with the wider fonts
        keys = KeyRow(key_need, 6, least=key_least)
        self.b_copy = QPushButton("Copy")
        self.b_copy.setToolTip("The headline and the tables, tab separated, "
                               "onto the clipboard.")
        self.b_copy.clicked.connect(shielded(self.copy, "Copy"))
        keys.add(self.b_copy)
        self.b_folder = QPushButton("Open folder")
        self.b_folder.setToolTip(str(folder or ""))
        self.b_folder.setEnabled(bool(folder))
        self.b_folder.clicked.connect(shielded(self.open_folder,
                                               "Open folder"))
        keys.add(self.b_folder)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        keys.add(close)
        row_of_keys = follows_width(QWidget())
        row_of_keys.setLayout(keys)
        outer.addWidget(row_of_keys)
        keep_shape(self, 300)
        self.open_wide()

    def open_wide(self):
        """Opens as wide as its tables ask, within the screen, and as tall
        as that width needs: it can still be made as narrow as 300 px."""
        asked = max([v.sizeHint().width() for v in self.views] or [0])
        asked += 24
        room = 900
        try:
            screen = self.screen() or QApplication.primaryScreen()
            room = int(screen.availableGeometry().width() * 0.9)
        except Exception:
            pass
        wide = max(300, min(max(asked, 24 * self.fontMetrics().height()),
                            room))
        self.resize(wide, 100)
        layout = self.layout()
        layout.activate()
        need = layout.totalMinimumSize().height()
        try:
            need = max(need, layout.minimumHeightForWidth(wide))
        except Exception:
            pass
        self.resize(wide, max(need, self.minimumHeight()))

    @staticmethod
    def table_view(table):
        columns = [str(c) for c in table.get("columns") or []]
        rows = list(table.get("rows") or [])
        colours = list(table.get("colours") or [])
        tips = list(table.get("tips") or [])
        right = list(table.get("align") or [])
        swatch = bool(colours)
        lead = 1 if swatch else 0
        formats = report_column_formats(rows, len(columns),
                                        table.get("formats") or [])
        # the column of names takes the slack: the first one that is text
        grow = next((c + lead for c, f in enumerate(formats) if f is None),
                    None)
        view = ReportTable(len(rows), len(columns) + lead, grow)
        fm = view.fontMetrics()
        bold = QFont(view.font())
        bold.setBold(True)
        head_fm = QFontMetrics(bold)
        pad = fm.averageCharWidth() * 2
        at_right = int(Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter)
        at_left = int(Qt.AlignmentFlag.AlignLeft
                      | Qt.AlignmentFlag.AlignVCenter)
        view.verticalHeader().setVisible(False)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setSelectionMode(
            QAbstractItemView.SelectionMode.ContiguousSelection)
        needs = [0] * (len(columns) + lead)
        if swatch:
            # a bar of the class's colour, not a column of its own weight
            needs[0] = fm.height() // 2 + 4
            view.setHorizontalHeaderItem(0, QTableWidgetItem(""))
        for c, name in enumerate(columns):
            numeric = formats[c] is not None or \
                (c < len(right) and right[c] == "r")
            head = QTableWidgetItem(name)
            head.setTextAlignment(at_right if numeric else at_left)
            if c < len(tips) and tips[c]:
                head.setToolTip(str(tips[c]))
            view.setHorizontalHeaderItem(c + lead, head)
            needs[c + lead] = text_width(head_fm, name) + pad
        for r, values in enumerate(rows):
            if swatch:
                cell = QTableWidgetItem("")
                colour = QColor(str(colours[r] if r < len(colours) else ""))
                if colour.isValid():
                    cell.setBackground(colour)
                view.setItem(r, 0, cell)
            for c, value in enumerate(values):
                if c >= len(columns):
                    break
                shown = report_number(value, formats[c]) \
                    if formats[c] is not None else report_shown(value)
                item = QTableWidgetItem(shown)
                numeric = formats[c] is not None or \
                    (c < len(right) and right[c] == "r")
                item.setTextAlignment(at_right if numeric else at_left)
                if formats[c] is None and not numeric:
                    item.setToolTip(shown)
                view.setItem(r, c + lead, item)
                needs[c + lead] = max(needs[c + lead],
                                      text_width(fm, shown) + pad)
        # a name too long for the room is cut with "…", its tooltip whole
        most = fm.averageCharWidth() * 24
        least = fm.averageCharWidth() * 8
        header = view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(1)
        if grow is not None:
            needs[grow] = min(needs[grow], most)
        view.widths(needs, min(least, needs[grow]) if grow is not None
                    else 0)
        view.setCurrentCell(-1, -1)
        return view

    def text(self):
        """The report as tab separated text: the scope, the headline, then
        each table with its header, and the notes last."""
        lines = [self.what]
        if self.scope:
            lines.append(self.scope)
        for name, value in self.headline:
            lines.append("%s\t%s" % (name, report_shown(value)))
        for table in self.tables:
            lines.append("")
            if table.get("title"):
                lines.append(str(table["title"]))
            lines.append("\t".join(str(c) for c in table.get("columns")
                                   or []))
            for values in table.get("rows") or []:
                lines.append("\t".join(report_shown(v) for v in values))
        if self.notes:
            lines.append("")
            lines.extend(self.notes)
        return "\n".join(lines) + "\n"

    def copy(self):
        QApplication.clipboard().setText(self.text())

    def open_folder(self):
        if self.folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder)))
