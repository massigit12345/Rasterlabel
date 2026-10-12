"""rasterlabel.sections_cutouts

Cutouts: writing a dataset out.
"""
import csv
import json
import math
import numpy as np
import os
import re
from html import escape

from datetime import datetime, timezone
from osgeo import gdal, ogr, osr
from qgis.PyQt.QtCore import Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QColor, QDesktopServices, QImage
from qgis.PyQt.QtWidgets import (QApplication, QComboBox, QDialog,
                                 QDoubleSpinBox, QFileDialog, QGroupBox,
                                 QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                                 QPushButton, QSpinBox, QToolButton,
                                 QVBoxLayout, QWidget)
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsDistanceArea, QgsPointXY, QgsProject, QgsRectangle)

from .constants import (CLASSIFICATION_EXT, FIELD_W, IGNORE_CODE, LABEL_W,
                        LEVEL_INFO, LEVEL_WARNING, MAX_WINDOW_PX, NAME,
                        PROJ_EXT, RASTER_EXT, SETTINGS_ROOT, STAC_VERSION,
                        TILE_SIDE_PX, VERSION, WHOLE_FORMATS)
from .compat import iface, read_setting, run_dialog, write_setting
from .naming import (beside_folder, clean_source, csv_text, csv_untext,
                     csv_untext_row, from_folder, glob_like, guess_role,
                     long_path, now, source_of, tidy, tidy_tag)
from .project import (canvas, crs_label, crs_to_text, ground_measure,
                      in_tree_order, lonlat_footprint, named_crs,
                      pixel_on_the_ground, project_ellipsoid,
                      project_rasters, projection_of, same_ground)
from .errors import log, shielded
from .layout import Deck
from .widgets import WrapTick
from .theme import (bar, follows_width, palette_colours, short_combo,
                    text_width)
from .geometry import (Geometry, north_up_of, read_on_grid, snap,
                       window_transform)
from .campaign import (ignore_refusal, operator_word, pass_number,
                       reading_choices, reading_rule, readings_in,
                       unlabelled_rule, unlabelled_tag)
from .detection import (DET_CLASSES_NAME, DET_COCO_NAME, DET_LABELS_FOLDER,
                        det_boxes, det_coco_text, det_frames, det_merge,
                        det_plan, det_remove)
from .card import (card_gather_campaign, card_names, card_provenance_metadata,
                   card_stale_lines, card_summary, card_write,
                   card_write_mask_item)
from .ui_card import card_progress, card_say
from .layers import find_mine, is_report_layer
from .rasters import (ROTATED_ADVICE, class_array, class_band_of,
                      class_band_type, class_nodata, colour_table,
                      display_limits, dress_class_band, is_class_code,
                      is_rotated, landed, lossy_codec, open_raster,
                      paint_whole, pixel_grid, put_raster, renderer_bands,
                      shape_of,
                      style_classes, style_of, thematic_colour, write_png,
                      write_tif)
from .tools import CutoutTool
from .dialogs import CutoutSetup, WholeRaster
from .sections_annotate import AnnotationSection


def hidden_readings(panel, readings):
    """The readings, out of these, that the reader in hand is kept from by the
    Annotate filter (the panel's blind gate, one reading at a time)."""
    gate = getattr(panel, "blind_gate", None)
    if not callable(gate):
        return []
    try:
        return [r for r in readings if gate([r])]
    except Exception as err:
        log("cannot ask whether the readings may be shown: %s" % err)
        return []


def ask_hidden(panel, hidden, subject="These files contain"):
    """True when the files may be written although they hold work hidden from
    the reader in hand: asked once, before anything is written, with Cancel as
    the default. Writing the tables with that work in them and refusing only
    the card would not do: the card is the same work in counts."""
    held = panel.reading() if callable(getattr(panel, "reading", None))         else None
    who = (held or {}).get("operator") or "the reader"
    names = ", ".join("%s pass %d" % (operator_word(r[0]), pass_number(r[1]))
                      for r in hidden)
    answer = QMessageBox.question(
        panel, NAME,
        "%s work hidden from %s (%s). Write %s anyway?"
        % (subject, who, names,
           "them" if subject.startswith("These") else "it"),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel)
    if answer != QMessageBox.StandardButton.Yes:
        log("not written: %s hidden from the reader" % names)
        return False
    return True


def write_card_beside(panel, folder, stem, exports=None, describe=None,
                      ignore_index=None, points_in_mask=False, dot_px=1):
    """The dataset card of the open campaign, written beside the files an
    export or the Whole raster has just made: <stem>_card.md and .json,
    with the SHA-256 of each of those files. The package is read only and
    the manifest is not told. Returns (files, the sentence for the
    information box, the card or None). Never raises: the files it
    describes are written, and a card that could not be is said so. A reader
    kept from some reading's work is asked before the files go out
    (ask_hidden), not here."""
    campaign = panel.campaign
    package = campaign.package_path
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        card = card_gather_campaign(
            campaign.data, campaign.folder, package, progress=card_progress,
            exports=exports, ignore_index=ignore_index,
            points_in_mask=points_in_mask, describe=describe, dot_px=dot_px,
            where=folder)
        # a card written on its own may be the first file of its folder
        os.makedirs(long_path(folder), exist_ok=True)
        files = card_write(card, folder, stem)
    except Exception as err:
        log("the dataset card could not be written: %s" % err, loud=True)
        return [], "The dataset card could not be written: %s" % err, None
    finally:
        QApplication.restoreOverrideCursor()
        card_say("")
    text = "Dataset card: %s and .json. %s" % (card_names(stem)[0],
                                               card_summary(card))
    stale = card_stale_lines(card)
    if stale:
        text += "\n" + "\n".join(stale)
    log("dataset card written: %s" % ", ".join(files))
    return files, text, card


def cut_ignore_rule(own, readings, want):
    """What a layer cut as classes holds where it holds nothing:
    (ignore value or None, whether its 0 means "nobody painted", where the
    value comes from), by the first of these that holds.

    1. The file carries an ignore value of its own (RASTERLABEL_IGNORE_INDEX,
       written by Whole or by an earlier cutout of the folder): that one,
       whatever the dock says. Its 0, if any, is a class ("none of these" in
       a frame).
    2. The dock is off: nothing, which is how RasterLabel 1.0 cut it, bit
       for bit.
    3. A mask of a campaign written by Whole with 0 where nobody painted
       (it says which readings it holds): the dock's value, and its 0 is
       "nobody painted".
    4. Any other map: the dock's value for the padding and the map's own
       nodata only; its 0 may be a class and is kept."""
    if own not in (None, ""):
        try:
            return int(float(own)), False, "file"
        except (TypeError, ValueError):
            pass
    if want is None:
        return None, False, None
    if readings:
        return int(want), True, "campaign mask"
    return int(want), False, "map"


def cut_class_entries(classes, ignore):
    """The classification:classes of a STAC asset (classification extension
    v2.0.0): every class the style names, its name made fit for the
    extension's pattern and its own words kept as the title, and the ignore
    value marked as nodata, which is what the extension says it is."""
    out = []
    for c in classes or []:
        code = int(c["code"])
        if ignore is not None and code == int(ignore):
            continue
        words = c.get("name") or "code %d" % code
        out.append({"value": code, "name": tidy(words, "class_%d" % code),
                    "title": words})
    if ignore is not None:
        out.append({"value": int(ignore), "name": "ignore",
                    "description": "nobody labelled it; leave it out of "
                                   "training", "nodata": True})
    return out


def write_atomic(path, text):
    """text at path whole or not at all: written under a temporary name,
    flushed to the disk, then renamed over the old file. A crash, or a full
    disk, in the middle leaves the old file as it was, not the first half of
    a new one. Raises OSError, with the temporary file taken away."""
    spare = long_path(path + ".tmp")
    try:
        with open(spare, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass            # a file system that cannot is no reason to fail
        os.replace(spare, long_path(path))
    except OSError:
        try:
            os.remove(spare)
        except OSError:
            pass
        raise


# Two small files that describe the cutouts folder itself, beside cutouts.csv:
# the layers the cutouts were cut from, so the next session cuts the same
# ones, and a note that a cutout is being written, so a crash in the middle of
# one can be found and cleaned.
LAYERS_FILE = "layers.json"
PENDING_FILE = "cutting.pending"


def layer_key(source):
    """A layer's file spelled so that two spellings of one file are equal,
    which is what the folder remembers a layer by: the id of a layer is made
    up again every time a project is opened, and its name is whatever it was
    called."""
    source = clean_source(str(source or "").split("|")[0].strip())
    if not source or "://" in source:
        return source
    return os.path.normcase(os.path.normpath(source))


def source_moment(ds):
    """When the image of a raster was taken, as STAC writes it
    (2025-03-14T10:22:31Z), if the file says so; "" when it does not.

    Read from what a GeoTIFF of a camera or a sensor keeps: the TIFF date
    tag, which has no time zone and is taken as UTC, and the acquisition
    time some producers write. A file that says nothing says nothing: the
    moment a cutout was cut is not the moment the ground was seen."""
    try:
        items = ds.GetMetadata() or {}
    except Exception:
        return ""
    for key, shapes in (
            ("TIFFTAG_DATETIME", ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S")),
            ("ACQUISITIONDATETIME", ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                                     "%Y:%m:%d %H:%M:%S")),
            ("ACQUISITION_DATE", ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"))):
        text = str(items.get(key) or "").strip()
        for shape in shapes:
            try:
                return datetime.strptime(text, shape).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                continue
    return ""


class CutoutsSection(QGroupBox):
    """Cuts windows out of the layers you already have, and writes a dataset.

    This is the other job, not the annotating one. You have a map of ground
    truth and some imagery of the same place, in whatever mixture of bands and
    resolutions; you pick a window, and out comes one file per layer, on one
    common pixel grid so that they stack.

    What is drawn by hand does not come through here. The annotation of a
    campaign is written from Annotate, where it lives and where the operator
    and pass filters apply; burning it here as well would have produced the
    same reading out of two places under two different sets of rules. The
    ground truth of a cutout is a LAYER somebody marked "classes". The one
    exception is the boxes of Objects, which no layer carries: they are
    written from the campaign as detection labels in the pixels of each image
    (boxes_coco.json and labels/), when there are any.

    It needs no campaign and writes none. What it cuts is the raster layers
    of the project, on a window you choose, and what it writes is the folder
    of cutouts and the files that describe them. How it was last set up is
    remembered by QGIS on this machine. An annotation campaign that happens
    to be open is only ever read: for its frames (All tiles), for its drawing
    (Whole), and once for the folder an earlier build kept its cutouts in."""

    def __init__(self, panel):
        super().__init__("")
        self.panel = panel
        self.campaign = panel.campaign          # read, never written
        self.geometry = None
        if self.campaign is not None:
            reference = find_mine(self.campaign.data["id"], "tiles") \
                or find_mine(self.campaign.data["id"], "polygons")
            self.geometry = Geometry(
                self.campaign, reference.crs() if reference is not None else None)
        self.tiled = bool(self.campaign is not None
                          and self.campaign.data.get("with_tiles"))
        self.sources = []
        self.ignored = {}         # layers unticked in the Layers panel
        self.tool = None
        self.written = []
        self.skipped = {}         # tag -> why the last cutout left it out
        self.gone = []            # cutouts listed in the books, not on disk
        self.folder = self.remembered_folder()
        self.settle_interrupted()
        self.count = self.count_existing()
        self.measure = QgsDistanceArea()
        self.aim_measure()
        self.build()
        self.pick_layers(silent=True)
        # Once the panel holds this module, which is just after it is made:
        # the log then goes to the folder of the program if there is a
        # cutouts folder already.
        panel_ = self.panel
        QTimer.singleShot(0, lambda: CutoutsSection.reroute(panel_))

    # ----------------------------------------------------------- the panel
    SETTINGS = SETTINGS_ROOT + "/cutouts/"

    def setting(self, key, default, kind=str):
        return read_setting(self.SETTINGS + key, default, kind)

    def keep_setting(self, key, value):
        write_setting(self.SETTINGS + key, value)

    def default_folder(self):
        """A "cutouts" folder beside the QGIS project, and one in the home
        folder when the project has never been saved. Not beside the campaign
        manifest, which there may not be."""
        try:
            home = QgsProject.instance().homePath()
        except Exception:
            home = ""
        # normpath: QGIS spells its folders with slashes, and joined to a
        # backslash that is a path with both in it on Windows
        if home and os.path.isdir(home):
            return os.path.normpath(os.path.join(home, "cutouts"))
        return os.path.join(os.path.expanduser("~"), NAME, "cutouts")

    def remembered_folder(self):
        """Where the cutouts go: the folder chosen last time, on this machine.

        It is not kept in the campaign manifest, which would tie the module to
        a campaign it has no other use for: QGIS remembers it. The one
        thing still read from a campaign is the folder RasterLabel 1.0 kept
        there, once, when QGIS has nothing yet: so a dataset that was being
        written goes on in the same place. The manifest is never written."""
        want = (self.setting("folder", "") or "").strip()
        if not want and self.campaign is not None:
            want = (self.campaign.data.get("cutouts_folder") or "").strip()
        return want or self.default_folder()

    def remember_folder(self, folder):
        """Keep the choice in QGIS, so it is the same tomorrow.

        Written even when it is the default, because "no answer" and "the
        default, chosen on purpose" are not the same thing."""
        folder = (folder or "").strip() or self.default_folder()
        self.keep_setting("folder", folder)
        return folder

    def folder_changed(self, *args):
        """A new folder means a new set of names already taken.

        free_name() asks the folder, so nothing can be overwritten either way,
        but the count on the panel has to be the one of the new folder.

        It is connected to editingFinished, which Qt sends every time the box
        merely loses focus. Every click from the box to the map would come
        here, forget what this session had cut and leave Undo saying "nothing
        cut in this session" about the cutout still on the screen. Only a
        folder that is really another one starts afresh."""
        folder = self.remember_folder(self.folder_box.text())
        if self.folder_box.text() != folder:
            self.folder_box.setText(folder)
        if self.same_folder(folder, self.folder):
            return
        self.folder = folder
        # undo cannot reach into a folder we have left behind
        self.written = []
        self.settle_interrupted()
        self.count = self.count_existing()
        # A folder that has been cut before says which layers it was cut
        # from and as what: the same ones, the same grid, the same names.
        # Nothing else changes the layers of a session behind its back.
        self.restore_layers()
        self.show_state()
        self.route_log()
        log("cutouts go to %s (%d already there)" % (folder, self.count))

    @staticmethod
    def same_folder(a, b):
        """Two spellings of one folder: a slash at the end, the other slash,
        another case on Windows."""
        if not a or not b:
            return False
        return (os.path.normcase(os.path.abspath(a))
                == os.path.normcase(os.path.abspath(b)))

    def route_log(self):
        """Ask the panel to point the log file at this folder, now that there
        may be one: with no campaign open it is the only folder Cutouts has,
        and the log would go nowhere at all."""
        CutoutsSection.reroute(self.panel)

    @staticmethod
    def reroute(panel):
        try:
            panel.route_log()
        except Exception:
            pass

    def folder_is_usable(self):
        """Can we actually write there? Asked once, before the first file.

        Finding out halfway through a batch means half a dataset and a dialog
        about a GeoTIFF, which is a confusing way to be told that a folder is
        read only or that a drive is not plugged in."""
        folder = self.folder or self.default_folder()
        try:
            os.makedirs(long_path(folder), exist_ok=True)
        except OSError as err:
            QMessageBox.critical(
                self, NAME,
                "The cutouts folder cannot be made:\n\n%s\n\n%s\n\n"
                "Pick another one under Settings." % (folder, err))
            return False
        probe = os.path.join(folder, ".rasterlabel_write_test")
        try:
            with open(long_path(probe), "w") as f:
                f.write("x")
            os.remove(long_path(probe))
        except OSError as err:
            QMessageBox.critical(
                self, NAME,
                "Nothing can be written into the cutouts folder:\n\n%s\n\n%s"
                % (folder, err))
            return False
        # The folder is there now, so the log can go into it.
        self.route_log()
        return True

    def choose_folder(self):
        got = QFileDialog.getExistingDirectory(
            self, "Where the cutouts go", self.folder or self.default_folder())
        if not got:
            return
        self.folder_box.setText(got)
        self.folder_changed()

    def build(self):
        follows_width(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(7)

        self.state = QLabel("")
        self.state.setWordWrap(True)
        self.state.setObjectName("quiet")
        outer.addWidget(self.state)

        groups = [[self._act("Layers", "Choose which layers are cut and as what.",
                             self.pick_layers)],
                  [self._act("Cut", "Click on the map for a square, drag for a\n"
                                    "free rectangle. Right click undoes the last\n"
                                    "one, Esc stops cutting.", self.start_cutting)]]
        # Both read the annotation campaign: its frames, its drawing. Without
        # one there is nothing for them to read, so they are not shown.
        if self.tiled:
            groups.append([self._act(
                "All tiles", "Cut one subset for every tile of the campaign.",
                self.export_all_tiles)])
        if self.campaign is not None:
            groups.append([self._act(
                "Whole",
                "The whole raster, in one piece.\n\n"
                "Write a whole raster out, with the annotation of the campaign on\n"
                "it. The one place in this module that does look at the hand\n"
                "drawing, because a river traced across a scene has no frames to\n"
                "cut and its extent is the picture itself.\n\n"
                "For work with no frames: a river traced across the scene, a\n"
                "coastline, anything whose extent is the picture itself. Comes out\n"
                "as the image with the annotation painted over, a mask of class\n"
                "codes, the plain image, or a picture for a figure, at full size or\n"
                "scaled down.",
                self.export_whole)])
        # Folder before Undo: Undo deletes a file, and goes last.
        groups.append([self._act("Folder", "Open the output folder.",
                                 self.show_folder),
                       self._act("Undo", "Delete the last cutout from disk.",
                                 self.undo, danger=True)])
        self.deck = Deck()
        # Rows of equal keys with nothing left alone: four are two and two
        # or one row of four, five and six are rows of three.
        keys = sum(len(g) for g in groups)
        self.deck.add(bar(groups, counts=(2, 4) if keys == 4 else (3,)), 2)

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

        self.side = QDoubleSpinBox()
        self.side.setRange(0.5, 5000.0)
        self.side.setDecimals(2)
        self.side.setSuffix(" m")
        self.side.setFixedWidth(FIELD_W)
        kept = self.setting("side_m", 0.0, float)
        self.side.setValue(round(kept if kept > 0
                                 else TILE_SIDE_PX * self.cutting_pixel()[0], 2))
        self.side.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.side.valueChanged.connect(self.show_state)
        self.side.valueChanged.connect(
            lambda v: self.keep_setting("side_m", float(v)))
        self.side_px = QLabel("")
        self.side_px.setObjectName("quiet")
        inner.addLayout(self._field("side", self.side, self.side_px))

        self.prefix = QLineEdit(self.setting("prefix", "cut") or "cut")
        self.prefix.setFixedWidth(FIELD_W)
        self.prefix.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.prefix.editingFinished.connect(
            lambda: self.keep_setting("prefix", self.prefix.text().strip()))
        inner.addLayout(self._field("prefix", self.prefix))

        row = QHBoxLayout()
        row.setSpacing(6)
        word = QLabel("folder")
        word.setFixedWidth(max(LABEL_W,
                               text_width(word.fontMetrics(), "folder") + 6))
        row.addWidget(word)
        self.folder_box = QLineEdit(self.folder)
        self.folder_box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.folder_box.setToolTip(
            "Where the cutouts are written. Remembered by QGIS on this machine,\n"
            "not in any campaign: Cutouts needs none and saves none. Leave it\n"
            "empty to go back to a 'cutouts' folder beside the QGIS project.\n\n"
            "Changing it starts a fresh count from whatever is already in the\n"
            "new folder, and nothing there is ever overwritten: a name that is\n"
            "taken is skipped.")
        self.folder_box.editingFinished.connect(
            shielded(self.folder_changed, "Folder"))
        row.addWidget(self.folder_box, 1)
        pick = QPushButton("...")
        pick.setFixedWidth(30)
        pick.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        pick.setToolTip("Choose the folder.")
        pick.clicked.connect(shielded(self.choose_folder, "Folder"))
        row.addWidget(pick)
        inner.addLayout(row)

        # The second half: not what a cutout contains but how the folder is
        # written. Its own block, so a wide panel sets them side by side.
        self.written_how = follows_width(QWidget())
        inner = QVBoxLayout(self.written_how)
        inner.setContentsMargins(8, 0, 0, 2)
        inner.setSpacing(5)

        self.png = WrapTick("also write PNG copies")
        self.png.setChecked(self.setting("png", True, bool))
        self.png.toggled.connect(
            lambda on, k="png": self.keep_setting(k, bool(on)))
        self.png.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.png.setToolTip(
            "Pictures for looking at: no coordinates, transparent outside the\n"
            "cutout and where the image has no data. An image comes out as it\n"
            "is shown in QGIS, with the bands and the stretch of its style;\n"
            "classes are painted with the colours of their style. A classes\n"
            "layer written as PNG keeps its codes in the main PNG and gets the\n"
            "coloured picture beside it, as _classes_colour.png.")
        inner.addWidget(self.png)

        self.common = WrapTick("one common pixel grid")
        self.common.setChecked(self.setting("common", True, bool))
        self.common.toggled.connect(
            lambda on, k="common": self.keep_setting(k, bool(on)))
        self.common.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.common.setToolTip(
            "On, every layer is read onto the grid of the layer chosen in\n"
            "Layers to set it, and all the files of a cutout have the same\n"
            "size. A layer that sits elsewhere is resampled: classes by the\n"
            "class most of a larger pixel holds, or the one under the centre\n"
            "of a smaller one, so no code is ever invented; an image averaged\n"
            "onto a larger pixel and interpolated onto a smaller one. Off,\n"
            "each layer keeps its own grid and the sizes can differ by a pixel.\n"
            "A layer in another coordinate system is always reprojected onto\n"
            "the common grid.")
        inner.addWidget(self.common)

        self.same_size = WrapTick("same size for all")
        self.same_size.setChecked(self.setting("same_size", True, bool))
        self.same_size.toggled.connect(
            lambda on, k="same_size": self.keep_setting(k, bool(on)))
        self.same_size.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.same_size.setToolTip(
            "The first cutout of a given side fixes how many pixels that side\n"
            "is, and every later one of the same side comes out exactly that\n"
            "size, padded with nodata where it runs past the edge of the\n"
            "raster. Without this two frames of the same metres can differ by\n"
            "one pixel depending on where they fall, and a loader that stacks\n"
            "the pieces into a batch refuses them. Freehand rectangles are not\n"
            "touched: they were asked for free.")
        inner.addWidget(self.same_size)

        # Where a layer cut as classes holds nothing: off, as RasterLabel 1.0
        # cut it, the padding past the edge is 0 and so is
        # the map's own nodata. On, they are the ignore value, declared as
        # the nodata of the cutout, so a loss told ignore_index leaves them
        # out. A 0 of a map made elsewhere is left alone: it may be a class.
        row_ignore = QWidget()
        self.ignore_on = WrapTick(
            "unlabelled as ignore",
            room=lambda: row_ignore.width() - self.ignore_value.width() - 6)
        self.ignore_on.watch_row(row_ignore)
        self.ignore_on.setChecked(self.setting("ignore_on", False, bool))
        self.ignore_on.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.ignore_value = QSpinBox()
        self.ignore_value.setRange(-32768, 65535)
        self.ignore_value.setFixedWidth(FIELD_W)
        self.ignore_value.setValue(self.setting("ignore_value", IGNORE_CODE,
                                                int))
        self.ignore_value.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        tip = ("Layers cut as classes: the edge padding, the layer's own\n"
               "nodata, and the 0 of a mask written by Whole become this\n"
               "value, declared as nodata. A 0 in any other map is left alone:\n"
               "it may be a class. A mask that already carries an ignore\n"
               "value keeps its own. It is not a foreground: samgeo and\n"
               "Deepness write 255 for that.")
        self.ignore_on.setToolTip(tip)
        self.ignore_value.setToolTip(tip)
        self.ignore_on.toggled.connect(
            lambda on: (self.keep_setting("ignore_on", bool(on)),
                        self.ignore_value.setEnabled(bool(on))))
        self.ignore_value.valueChanged.connect(
            lambda v: self.keep_setting("ignore_value", int(v)))
        self.ignore_value.setEnabled(self.ignore_on.isChecked())
        ignore_line = QHBoxLayout(row_ignore)
        ignore_line.setContentsMargins(0, 0, 0, 0)
        ignore_line.setSpacing(6)
        ignore_line.addWidget(self.ignore_on)
        ignore_line.addWidget(self.ignore_value)
        ignore_line.addStretch(1)
        self.row_ignore = row_ignore
        inner.addWidget(row_ignore)

        self.stac = WrapTick("STAC catalogue")
        self.stac.setChecked(self.setting("stac", True, bool))
        self.stac.toggled.connect(
            lambda on, k="stac": self.keep_setting(k, bool(on)))
        self.stac.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.stac.setToolTip(
            "Writes a stac folder beside the cutouts: one item per cutout,\n"
            "listing the files really written, the roles they were cut as,\n"
            "the projection and the exact transform. It is what makes the\n"
            "folder readable by something that was not told how we name our\n"
            "files. An item whose files are no longer on disk is left out of\n"
            "catalog.json, and kept in the stac folder.")
        inner.addWidget(self.stac)

        # Boxes for detection training: the one thing drawn by hand that has
        # no layer to come through, so it is written from the campaign here,
        # in the pixels of each cutout. Only with a campaign that has boxes.
        self.boxes = WrapTick("boxes for detection")
        self.boxes.setChecked(self.setting("boxes", True, bool))
        self.boxes.toggled.connect(
            lambda on, k="boxes": self.keep_setting(k, bool(on)))
        self.boxes.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.boxes.setToolTip(
            "The boxes of the campaign (Objects), cut to each cutout and\n"
            "written in its pixels: boxes_coco.json for the whole folder\n"
            "(COCO, category_id the class code) and, in labels/, one text\n"
            "file per image in the YOLO form, with classes.txt naming the\n"
            "indices. A cutout keeps the boxes the campaign held when it was\n"
            "cut. Written only when the campaign has boxes, and for images:\n"
            "a layer cut as classes has none.\n"
            "Every image over ground that was read gets its file, empty when\n"
            "no box falls in it, and an empty file reads as a picture with\n"
            "nothing in it. In a campaign with frames, ground outside them\n"
            "was not read: an image the frames do not cover gets no file and\n"
            "is listed under unlabelled_images in the book, to be left out of\n"
            "training.")
        inner.addWidget(self.boxes)
        self.boxes_reading = None
        self.boxes_choices = []
        if self.campaign_package():
            # one reading, or all of them together: two people who read the
            # same ground would otherwise put every object in twice
            self.boxes_reading, self.boxes_choices = \
                self.reading_box_of_boxes()
            inner.addWidget(self.boxes_reading)

        self.settings.setVisible(False)
        self.written_how.setVisible(False)
        self.more_settings = [self.written_how]
        self.settings_box.addWidget(self.settings)
        self.deck.add(self.settings_box, 3)
        self.deck.add(self.written_how, 3)

        self.deck.deal(force=True)
        outer.addWidget(self.deck)

        self.show_state()

    _act = AnnotationSection.__dict__["_act"]
    _field = AnnotationSection.__dict__["_field"]
    show_settings = AnnotationSection.__dict__["show_settings"]

    def campaign_package(self):
        """The GeoPackage of the campaign, or None with no campaign."""
        return getattr(self.campaign, "package_path", None)

    def reading_box_of_boxes(self):
        """The readings the boxes can be taken from: all of them together, or
        one. The consensus the pixel windows offer has no meaning for a box."""
        choices = [c for c in reading_choices(
            readings_in(self.campaign_package()))
            if c["mode"] in ("all", "one")]
        box = QComboBox()
        for c in choices:
            box.addItem("boxes of " + c["label"])
        short_combo(box, 14)    # a reading with a long name is cut, not wide
        box.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        box.setToolTip(
            "Whose boxes go to the detection files. All readings together\n"
            "puts an object in once for every reading that boxed it: for a\n"
            "campaign read by several people, choose one.")
        return box, choices

    def cutting_pixel(self):
        """The pixel the cutouts are actually taken on, and whose it is.

        The first chosen layer, because that is the grid every other one is
        read onto. Until a layer has been chosen the raster selected in the
        panel stands in for it, then the grid of a campaign if one is open,
        then a pixel of one unit: the two are not always the same size, so the
        count is shown with a star until it is the real one."""
        if self.sources:
            # On the ground, like the side it divides. rasterUnitsPerPixelX()
            # is in the units of the layer, and on a layer in degrees a side
            # of ten metres came out as tens of millions of pixels.
            try:
                px = float(pixel_on_the_ground(self.sources[0]["layer"])[0])
                if px > 0:
                    return px, "layer"
            except (TypeError, ValueError, AttributeError):
                pass
        try:
            raster = self.panel.active_raster()
        except Exception:
            raster = None
        if raster is not None:
            try:
                px = float(pixel_on_the_ground(raster)[0])
                if px > 0:
                    return px, "panel"
            except (TypeError, ValueError, AttributeError):
                pass
        if self.geometry is not None:
            return self.geometry.pixel_m[0], "campaign"
        return 1.0, None

    def resizeEvent(self, ev):
        """The folder line is cut to the width, so a new width is a new cut."""
        QGroupBox.resizeEvent(self, ev)
        if getattr(self, "side_px", None) is not None:
            self.show_state()

    def show_state(self, *args):
        px, whose = self.cutting_pixel()
        self.side_px.setText("%d px%s" % (int(round(self.side.value() / px))
                                          if px else 0,
                                          "" if whose == "layer" else " *"))
        if whose == "layer":
            self.side_px.setToolTip(
                "On the grid of %s, the layer that sets the grid: that is the "
                "grid every other layer is read onto." % self.sources[0]["tag"])
        elif whose == "panel":
            self.side_px.setToolTip(
                "On the grid of %s, the raster selected in the panel, marked "
                "with a star because no layer has been chosen yet. The layer "
                "that is cut first may have a pixel of a different size, and "
                "then this count changes." % self.panel.active_raster().name())
        else:
            self.side_px.setToolTip(
                "On the grid of the %s, marked with a star because no layer "
                "has been chosen yet. The layer that is cut first may have a "
                "pixel of a different size, and then this count changes."
                % ("campaign" if whose == "campaign" else "unit pixel"))
        # What is cut, and what the last cutout really wrote. A line made
        # from what was asked for alone would read "aragona as image" through
        # a whole session in which every cutout had left the image out; the
        # reason would be in a warning that the next message covers.
        warn = palette_colours()["danger"]
        roles = ", ".join(
            "%s as %s" % (s["tag"], s["role"])
            + ("" if s["tag"] not in self.skipped else
               " <span style='color:%s'>(left out of the last cutout: %s)"
               "</span>" % (warn, self.skipped[s["tag"]]))
            for s in self.sources)
        gone = ""
        if self.gone:
            gone = ("<br><span style='color:%s'>%d listed in cutouts.csv but "
                    "no longer on disk: %s%s (the log has the rest)</span>"
                    % (warn, len(self.gone), ", ".join(self.gone[:3]),
                       ", ..." if len(self.gone) > 3 else ""))
        # Where they land, always in sight. A dataset written into the wrong
        # folder is not lost, but it is not found either, and the moment to
        # notice is before the first cut and not after the hundredth.
        where = self.folder or self.default_folder()
        # Cut in the middle to the width the line has, so both ends of the
        # path stay in sight: cut at forty-six letters it broke after the
        # drive and ran off the edge of a narrow panel.
        room = self.state.contentsRect().width()
        if room < 60:
            room = 200
        metrics = self.state.fontMetrics()
        short = metrics.elidedText(where, Qt.TextElideMode.ElideMiddle,
                                   max(room - text_width(metrics, "into "), 40))
        self.state.setText(
            "<b>%d</b> cutout%s written<br>%s<br>"
            "<span style='color:%s'>into %s</span>%s%s"
            % (self.count, "" if self.count == 1 else "s",
               roles or "no layer chosen yet: press <b>Layers</b>",
               palette_colours()["dim"], escape(short), gone,
               "" if self.campaign is not None else
               "<br><span style='color:%s'>no campaign needed, none written"
               "</span>" % palette_colours()["dim"]))
        self.state.setToolTip(where)
        if self.campaign is None:
            # Why All tiles and Whole are missing, where it is asked: the
            # status was six lines of grey prose above the buttons.
            self.state.setToolTip("%s\n\nAll tiles and Whole need an "
                                  "annotation campaign." % where)

    # ----------------------------------------------------------- the layers
    def export_whole(self):
        """The whole raster, with everything drawn on it.

        Saved first, always. An export that quietly misses the last ten minutes
        of drawing is worse than no export, because nothing about it looks
        wrong."""
        panel = self.panel
        if panel.section is not None and panel.section.unsaved():
            try:
                panel.section.save()
            except Exception as err:
                log("could not save before exporting the whole raster: %s" % err)
        if panel.annotation is not None and panel.annotation.unsaved():
            try:
                panel.annotation.save()
            except Exception as err:
                log("could not save the annotation: %s" % err, loud=True)
        # Whole is reached from Cutouts, where neither of those two modules is
        # open, so what is still in a table's buffer is asked of the tables
        # themselves, as every other export does (panel.pending_layers). A
        # package that failed to save when Annotate was closed, a rename
        # that could not be written, a recovery put back that did not commit:
        # all of it is missing from the file the mask is burned from, and
        # what is missing is labelled as background.
        left = []
        try:
            if panel.pending_layers():
                left = panel.flush_layers()
        except Exception as err:
            log("could not write the layers before exporting the whole "
                "raster: %s" % err)
        # If anything is still unsaved after that, the export would be made
        # from the package on disk and would quietly miss the last stretch of
        # work. Better to stop and ask than to hand over a dataset that is
        # wrong in a way nothing about it shows.
        still = [m for m in (panel.section, panel.annotation)
                 if m is not None and m.unsaved()]
        try:
            waiting = panel.pending_layers()
        except Exception:
            waiting = []
        if still or left or waiting:
            q = QMessageBox.warning(
                self, NAME,
                "Not everything could be saved, so the raster will be made "
                "from the package as it stands on disk, without it:\n\n%s\n\n"
                "Where nothing is drawn in the file the mask is background. "
                "Export anyway?"
                % ("\n".join(left) if left else
                   "some work is still waiting to be written."),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if q != QMessageBox.StandardButton.Yes:
                return

        if self.campaign is None:
            return
        dialog = WholeRaster(self, self.campaign,
                             os.path.join(self.campaign.folder, "whole"))
        if run_dialog(dialog) != QDialog.DialogCode.Accepted:
            return
        r = dialog.result()
        if r["layer"] is None:
            QMessageBox.warning(self, NAME, "No raster is loaded.")
            return
        # The card is not a raster: it is written after them, beside them.
        want_card = "card" in r["kinds"]
        r["kinds"] = [k for k in r["kinds"] if k != "card"]
        if not r["kinds"] and not want_card:
            QMessageBox.information(self, NAME, "Nothing was chosen.")
            return
        if not r["folder"]:
            QMessageBox.warning(self, NAME, "Say where to write it.")
            return

        layer = r["layer"]
        ds = open_raster(source_of(layer))
        if ds is None:
            QMessageBox.critical(
                self, NAME, "That raster cannot be read." if
                CutoutsSection.is_file_layer(layer) else
                "That raster cannot be read: it is not a file but a web or "
                "database layer.")
            return
        os.makedirs(r["folder"], exist_ok=True)

        bands = renderer_bands(layer)
        limits = display_limits(layer, bands)
        if limits is None:
            limits = self.guess_limits(ds, bands, r["scale"])
        colours = {c["code"]: (QColor(c["colour"]).red(),
                               QColor(c["colour"]).green(),
                               QColor(c["colour"]).blue())
                   for c in self.campaign.active_classes()}

        # The same stem the layers are named with, so a table on disk and
        # the layer it came from answer to the same word.
        stem = self.campaign.stem
        stem = "%s_%s" % (stem, tidy_tag(layer.name(), "raster"))
        choice = r.get("reading") or {"mode": "all"}
        # one reading, or a consensus, is said in the name as well as inside
        # the file: the mask of every reading together keeps the name it
        # always had
        if choice.get("tag"):
            stem += "_" + choice["tag"]
        # and the value where nobody painted, when it is not 0: two masks of
        # the same reading, one with 0 and one with 255, are two files
        unlabelled = r.get("unlabelled") or "zero"
        ignore = r.get("ignore") if unlabelled != "zero" else None
        if ignore is None:
            unlabelled = "zero"
        tag = unlabelled_tag(unlabelled, ignore)
        if tag:
            stem += "_" + tag
        if r["scale"] > 1:
            stem += "_1of%d" % r["scale"]
        ext = r["extension"]
        # a mask never goes out as JPEG, whatever was picked: the codes are
        # meaning, not brightness, and a lossy codec would shuffle them; nor
        # as a PNG with a negative ignore value, which needs 16 signed bits
        # and a PNG has none
        mask_driver, mask_ext = (
            ("GTiff", ".tif") if not r["exact"]
            or (ignore is not None and ignore < 0 and r["driver"] == "PNG")
            else (r["driver"], ext))
        plan = {"painted": (stem + "_annotated" + ext, r["driver"]),
                "mask": (stem + "_mask" + mask_ext, mask_driver),
                "plain": (stem + "_image" + ext, r["driver"]),
                "figure": (stem + "_figure.png", "PNG"),
                "votes": (stem + "_votes.tif", "GTiff")}
        kinds = list(r["kinds"])
        # A consensus mask says which class won; the votes beside it say by
        # how much, and where the readings painted and did not agree.
        if choice.get("mode") == "consensus" and "mask" in kinds:
            kinds.append("votes")
        outputs = [(k, os.path.join(r["folder"], plan[k][0]), plan[k][1])
                   for k in kinds]
        card_stem = stem
        card_files = [os.path.join(r["folder"], n)
                      for n in card_names(card_stem)] if want_card else []
        # A card holds every reading's counts: a reader kept from some of
        # them is asked once, before anything is written.
        if want_card:
            hidden = hidden_readings(self.panel, sorted(
                readings_in(self.campaign.package_path),
                key=lambda x: (x[1], x[0])))
            if hidden and not ask_hidden(self.panel, hidden,
                                         "The dataset card holds"):
                return
        clashing = [p for _, p, _ in outputs if os.path.exists(p)] + [
            p for p in card_files if os.path.exists(p)]
        # the legend written beside a mask is a file of its own, and one
        # that is there already is followed and rewritten
        clashing += [style_of(p) for k, p, _ in outputs
                     if k == "mask" and os.path.exists(style_of(p))]
        if clashing:
            q = QMessageBox.question(
                self, "Whole raster",
                "These are already there and would be replaced:\n\n%s\n\nGo on?"
                % "\n".join(os.path.basename(c) for c in clashing))
            if q != QMessageBox.StandardButton.Yes:
                return

        recipe = dict(r["extras"])
        # the layer too, so the pictures are drawn with its style, as the
        # screen has them; the bands and the limits are for when they cannot be
        recipe.update({"ds": ds, "layer": layer,
                       "scale": r["scale"], "rgb": bands,
                       "limits": limits, "alpha": r["alpha"],
                       "colours": colours, "outputs": outputs,
                       # the legend of the mask: code, name and colour of
                       # every class, written into it and beside it
                       "classes": [dict(c) for c in
                                   self.campaign.active_classes()],
                       "package": self.campaign.package_path,
                       "reading": choice,
                       "unlabelled": unlabelled, "ignore": ignore,
                       # the build, the campaign and the pixel rule inside
                       # every GeoTIFF, and the card's name when one goes
                       # beside it; and the counts as written, for the card
                       "provenance": card_provenance_metadata(
                           self.campaign.data,
                           card_files[1] if card_files else None),
                       "tally": {}})

        written, size = [], None
        if outputs:
            bar = iface.messageBar().createMessage(NAME,
                                                   "writing the whole raster")
            # The level is the enum, never the 0 it is worth: PyQt6 refuses
            # an int here, and on QGIS 4 Whole stopped on a TypeError before
            # writing anything, whatever the raster.
            iface.messageBar().pushWidget(bar, LEVEL_INFO)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                written, size = paint_whole(recipe, progress=self.tick_whole)
            except Exception as err:
                QApplication.restoreOverrideCursor()
                iface.messageBar().popWidget(bar)
                QMessageBox.critical(self, NAME,
                                     "Nothing was written:\n\n%s" % err)
                log("whole raster export failed: %s" % err)
                return
            finally:
                ds = None
            QApplication.restoreOverrideCursor()
            iface.messageBar().popWidget(bar)
        ds = None
        message = ""
        if written:
            message = ("%d file%s of %d x %d pixels written in\n%s\n\n"
                       "Readings: %s."
                       % (len(written), "" if len(written) == 1 else "s",
                          size[0], size[1], r["folder"],
                          reading_rule(choice,
                                       recipe.get("consensus_partial"))))
            if "mask" in kinds:
                message += "\nUnlabelled: %s." % unlabelled_rule(
                    unlabelled, ignore, choice.get("mode") == "consensus")
                legend = [os.path.basename(p)
                          for p in recipe.get("sidecars") or []]
                if legend:
                    inside = any(d == "GTiff" for k, _, d in outputs
                                 if k == "mask")
                    message += (
                        "\nLegend of the classes: %s beside the mask%s."
                        % (", ".join(legend),
                           ", and inside it" if inside else ""))
        if want_card:
            message += "\n\n" if message else ""
            message += self.whole_card(recipe, outputs, written, choice,
                                       card_stem, r)
        QMessageBox.information(self, NAME, message)
        log("whole raster (%s): %s"
            % (choice.get("label", "all readings together"),
               ", ".join(os.path.basename(f) for f in written)
               or "the card only"))
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(r["folder"]))
        except Exception:
            pass

    def whole_card(self, recipe, outputs, written, choice, stem, r):
        """The dataset card beside what Whole wrote, with the counts of the
        mask as they were written, and the STAC item of a GeoTIFF mask that
        has a coordinate system. Returns what the information box says."""
        on_disk = set(written)
        tally = recipe.get("tally") or {}
        exports, mask = [], None
        for what, path, driver in outputs:
            if path not in on_disk or what not in ("mask", "votes"):
                continue
            entry = {"path": path, "role": what, "reading": choice,
                     "scale": r["scale"]}
            if what in tally:
                entry["counts"] = tally[what]
            exports.append(entry)
            if what == "mask":
                mask = (path, driver)
        files, said, card = write_card_beside(
            self.panel, r["folder"], stem, exports=exports, describe=choice,
            ignore_index=recipe.get("ignore"),
            points_in_mask=bool(recipe.get("points_in_mask")
                                and recipe.get("want_points")),
            dot_px=recipe.get("dot_px", 1))
        if card is not None and mask is not None and mask[1] == "GTiff":
            try:
                ds = gdal.Open(long_path(mask[0]))
                gt, w, h = pixel_grid(ds), ds.RasterXSize, ds.RasterYSize
                wkt = ds.GetProjection()
                ds = None
                votes = [p for k, p, _ in outputs
                         if k == "votes" and p in on_disk]
                item = card_write_mask_item(card, mask[0], gt, w, h, wkt,
                                            votes[0] if votes else None,
                                            files[1] if files else None)
                if item:
                    said += "\nSTAC item: %s." % os.path.basename(item)
            except Exception as err:
                log("the STAC item of the mask could not be written: %s"
                    % err, loud=True)
        return said

    def tick_whole(self, done, total):
        """Keep QGIS answering while a big raster goes out, and say how far
        along it is. Without this the window greys over and looks crashed."""
        iface.mainWindow().statusBar().showMessage(
            "%s: whole raster, %d%%" % (NAME, int(100.0 * done / max(total, 1))))
        QApplication.processEvents()

    def guess_limits(self, ds, bands, scale):
        """A stretch decided once, from a cheap look at the whole raster.

        Taken before the strips start, and on a heavily decimated read, because
        a stretch worked out strip by strip would put a visible seam across the
        picture wherever the brightness of the ground changed."""
        step = max(1, ds.RasterXSize // 1200, ds.RasterYSize // 1200)
        out = []
        for b in bands:
            try:
                band = ds.GetRasterBand(min(b, ds.RasterCount))
                small = band.ReadAsArray(
                    0, 0, ds.RasterXSize, ds.RasterYSize,
                    buf_xsize=max(1, ds.RasterXSize // step),
                    buf_ysize=max(1, ds.RasterYSize // step)).astype(np.float32)
                nd = band.GetNoDataValue()
                good = np.isfinite(small)
                if nd is not None:
                    good &= small != nd
                v = small[good]
                out.append((float(np.percentile(v, 2)),
                            float(np.percentile(v, 98))) if v.size else (0.0, 255.0))
            except Exception:
                out.append((0.0, 255.0))
        return out

    def pick_layers(self, silent=False):
        # Cutouts writes a picture rather than a GeoTIFF when there is no
        # coordinate system, which the Whole dialog has said in so many words
        # for a long time; the layer picker was the one place still refusing to
        # list those layers at all.
        #
        # In the order of the Layers panel, top first. They came sorted by
        # name, and the first one sets the grid and the system of every
        # cutout: whatever was on top, a layer whose name sorts first won.
        rasters = in_tree_order(project_rasters(need_crs=False))
        if not rasters:
            if not silent:
                QMessageBox.warning(self, NAME, "No raster is loaded.")
            return
        remembered = dict(self.ignored)
        remembered.update({s["id"]: s for s in self.sources})
        if silent and not self.sources:
            self.sources = self.guess(rasters)
            self.show_state()
            return
        dialog = CutoutSetup(self, rasters, remembered,
                             grid_id=self.sources[0]["id"] if self.sources
                             else None)
        if not run_dialog(dialog):
            return
        self.sources = dialog.result()
        self.skipped = {}
        if self.sources:
            log("cutouts: %s; the grid is %s's"
                % (", ".join("%s as %s" % (s["tag"], s["role"])
                             for s in self.sources), self.sources[0]["tag"]))
        self.show_state()

    def guess(self, rasters):
        """What a first glance says, so the module is usable before anyone
        opens the dialog: every raster that is on the map, in the order of
        the Layers panel, so the one on top sets the grid. A layer unticked
        in the Layers panel starts as "ignore", because what is cut is what
        is shown, and it is one click to put it back in Layers. So does a
        map of a report (the disagreement of two readings, a map of pairs):
        Compare loads it on, on top, and it would otherwise be cut beside the
        image as a layer of classes of the dataset. With a campaign open its
        reference raster goes first.

        A folder that was cut before has the last word over all of that
        (layers.json, see remember_layers): the layers it was cut from keep
        their roles, their bands, their names and their order, the first of
        them the grid, whatever is ticked on the map today."""
        reference = ""
        if self.campaign is not None:
            reference = from_folder(
                (self.campaign.data.get("grid") or {}).get(
                    "reference_raster", ""), self.campaign.folder)
        kept, order = {}, {}
        memory = self.read_layers() or {}
        for i, entry in enumerate(memory.get("layers") or []):
            key = layer_key(entry.get("source"))
            if key and key not in kept:
                kept[key], order[key] = entry, i
        # A record that names no layer of this project says nothing about
        # it: another project, or files that have moved.
        here = {layer_key(source_of(l)) for l in rasters}
        if not set(kept) & here:
            kept, order = {}, {}
        self.ignored = {}
        choices, new, claimed = [], [], set()
        for layer in rasters:
            key = layer_key(source_of(layer))
            entry = kept.get(key)
            # two layers of one file: the first is the folder's
            if key in claimed:
                entry = None
            claimed.add(key)
            # With a record the folder is the whole list: a layer it does
            # not know is not part of this dataset, and is one click away in
            # Layers. A layer more is how the same folder came to hold
            # pieces that did not stack. A map of a report is never offered
            # unless the folder was cut with it.
            if entry is None and (kept or not self.on_the_map(layer)
                                  or is_report_layer(layer)):
                self.ignored[layer.id()] = {"id": layer.id(), "role": "ignore"}
                if kept:
                    new.append(layer.name())
                continue
            choices.append((layer, key, entry))
        if new:
            log("%s: %s %s not among the layers this folder was cut from, "
                "and %s left out. Layers puts %s in."
                % (self.folder, ", ".join(new[:4]) + (", ..." if len(new) > 4
                                                       else ""),
                   "is" if len(new) == 1 else "are",
                   "is" if len(new) == 1 else "are",
                   "it" if len(new) == 1 else "them"))
        # the names the folder gave are kept as they were, whatever order the
        # layers are in today: the ones it does not know come after
        out, taken = [], set()
        for layer, key, entry in choices:
            if entry is not None and entry.get("tag"):
                # as the folder kept it, never cut again: a tag made by
                # RasterLabel 1.0 is at most 48 letters and comes back as it
                # was, and one made since may be a little longer (a "_2")
                tag = tidy_tag(str(entry["tag"]), room=255)
                if tag.lower() not in taken:
                    taken.add(tag.lower())
                    entry["_tag"] = tag
        for layer, key, entry in choices:
            tag = (entry or {}).get("_tag")
            if not tag:
                # a long name loses its middle, never its ending
                tag = tidy_tag(layer.name())
                while tag.lower() in taken:
                    tag += "_2"
                taken.add(tag.lower())
            source = {"id": layer.id(), "layer": layer,
                      "role": guess_role(layer),
                      "band": class_band_of(layer),
                      "rgb": renderer_bands(layer), "tag": tag}
            if entry is not None:
                self.take_remembered(source, entry, layer)
            out.append(source)
        out.sort(key=lambda s: 0 if source_of(s["layer"]) == reference else 1)
        if order:
            out.sort(key=lambda s: order.get(layer_key(source_of(s["layer"])),
                                             len(order)))
        return out

    @staticmethod
    def take_remembered(source, entry, layer):
        """What a folder remembers of a layer, as far as it still fits the
        layer: a role that exists, bands the layer has, a format we write."""
        bands = layer.dataProvider().bandCount()
        if entry.get("role") in ("image", "classes"):
            source["role"] = entry["role"]
        band = entry.get("band")
        if isinstance(band, int) and 1 <= band <= bands:
            source["band"] = band
        rgb = entry.get("rgb")
        if isinstance(rgb, list) and len(rgb) == 3 and all(
                isinstance(b, int) and 1 <= b <= bands for b in rgb):
            source["rgb"] = list(rgb)
        if entry.get("driver") in [row[1] for row in WHOLE_FORMATS]:
            source["driver"] = entry["driver"]

    # ---------------------------------------------- the layers of a folder
    # Which layers were cut, as what and on whose grid is a property of the
    # dataset, not of a session: a folder that gets its cutouts from a
    # different set of layers every other day holds pieces that do not stack.
    # So it is written into the folder, layers.json beside cutouts.csv, and
    # not into the QGIS settings of this machine. It goes with the folder when
    # it is copied or zipped, and it cannot disagree with the folder it
    # describes the way a setting keyed by the path of a folder that has been
    # moved or deleted would. Layers are told apart by the path of the file
    # they come from, so it serves where those files are at the same paths: on
    # another machine, another drive or after the files moved, no layer of the
    # record is found and it is left aside (guess), the layers chosen from the
    # map as for a new folder.
    @property
    def layers_path(self):
        return os.path.join(self.folder, LAYERS_FILE)

    def read_layers(self, as_written=False):
        """layers.json of the folder, or None when there is none or it cannot
        be read as one. The paths in it are made whole from the folder, as the
        manifests are (from_folder): it keeps them from the folder or from ~,
        and a file written before, with whole paths, reads the same. With
        as_written the paths are left as the file has them."""
        path = long_path(self.layers_path)
        if not self.folder or not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                book = json.load(f)
        except (OSError, ValueError) as err:
            log("%s could not be read, the layers are chosen afresh: %s"
                % (LAYERS_FILE, err), loud=True)
            return None
        if not isinstance(book, dict) or not isinstance(
                book.get("layers"), list):
            return None
        book["layers"] = [e for e in book["layers"] if isinstance(e, dict)]
        if not as_written:
            held = [(e, "source") for e in book["layers"]] + [(book, "grid")]
            for entry, key in held:
                if isinstance(entry.get(key), str):
                    entry[key] = from_folder(entry[key], self.folder)
        return book

    def layers_record(self):
        """What this session cuts, as layers.json says it: the layers in
        order, the first the grid, and the ones left out on purpose."""
        layers = []
        for s in self.sources:
            entry = {"source": source_of(s["layer"]),
                     "name": s["layer"].name(), "role": s["role"],
                     "tag": s["tag"]}
            if s["role"] == "classes":
                entry["band"] = s["band"]
            else:
                entry["rgb"] = list(s["rgb"])
            if s.get("driver"):
                entry["driver"] = s["driver"]
            layers.append(entry)
        return {"written_by": "%s %s" % (NAME, VERSION),
                "note": "The layers this folder is cut from, the first one "
                        "setting the pixel grid. Cutouts reads it when the "
                        "folder is chosen, so the next session cuts the same "
                        "layers in the same way, when their files are where "
                        "the paths written here lead: from this folder, or "
                        "from the home folder (~). A layer not listed here "
                        "is not part of this dataset.",
                "grid": layers[0]["source"] if layers else "",
                "layers": layers}

    @staticmethod
    def layers_words(book):
        """The layers of a record in a sentence."""
        layers = (book or {}).get("layers") or []
        if not layers:
            return "no layer"
        return "%s (the grid is %s's)" % (
            ", ".join("%s as %s" % (e.get("tag"), e.get("role"))
                      for e in layers), layers[0].get("tag"))

    @staticmethod
    def layers_match(a, b):
        """True when two records cut the same layers, as the same, on the
        same grid. The order after the first does not matter."""
        def shape(book):
            rows = [(layer_key(e.get("source")), e.get("role"), e.get("tag"),
                     e.get("band") if e.get("role") == "classes"
                     else tuple(e.get("rgb") or ()), e.get("driver") or "")
                    for e in (book or {}).get("layers") or []]
            return rows[:1], sorted(rows[1:], key=str)
        return shape(a) == shape(b)

    def layers_to_write(self, record):
        """The record as the file keeps it: the paths of the layers from the
        folder, or from ~ when they are far from it (beside_folder), and the
        passwords of a layer that is a service taken out. The folder is
        zipped and published, and whole paths carry the name of whoever cut
        it."""
        out = dict(record)
        out["layers"] = [dict(e, source=beside_folder(e.get("source"),
                                                      self.folder))
                         for e in record["layers"]]
        if out.get("grid"):
            out["grid"] = beside_folder(out["grid"], self.folder)
        return out

    def remember_layers(self, record=None):
        """Write layers.json, if it says anything new. Never raises: the
        dataset is whole without it."""
        record = record or self.layers_record()
        if not record["layers"]:
            return
        text = self.layers_to_write(record)
        before = self.read_layers()
        if before is not None and self.layers_match(before, record):
            # a file written with whole paths is written again, once, in the
            # form that does not carry the home folder
            kept = self.read_layers(as_written=True)
            same_paths = (
                sorted(str(e.get("source")) for e in kept["layers"])
                == sorted(str(e["source"]) for e in text["layers"]))
            if same_paths and kept.get("grid") == text["grid"]:
                return
        try:
            os.makedirs(long_path(self.folder), exist_ok=True)
            write_atomic(self.layers_path, json.dumps(text, indent=2))
        except OSError as err:
            log("cannot write %s: %s" % (LAYERS_FILE, err), loud=True)

    def restore_layers(self):
        """The layers a folder says it was cut from, in place of the ones
        chosen so far, when it says: True when it did."""
        if self.read_layers() is None:
            return False
        rasters = in_tree_order(project_rasters(need_crs=False))
        if not rasters:
            return False
        self.sources = self.guess(rasters)
        self.skipped = {}
        log("cutouts: the layers of %s, as it was cut before: %s"
            % (self.folder, self.layers_words(self.layers_record())))
        return True

    def check_layers(self):
        """Before a cut: the layers of the folder, and the layers about to be
        cut. They differ when somebody chose other roles, another grid or
        other layers since the last cutout, and the pieces of one folder
        then no longer line up. It is said, once, on the message bar and in
        the log, and the new choice is kept from now on."""
        record = self.layers_record()
        before = self.read_layers()
        if before is not None and self.count > 0 \
                and not self.layers_match(before, record):
            told = self.__dict__.setdefault("_layers_told", set())
            sentence = (self.layers_words(before), self.layers_words(record))
            if sentence not in told:
                told.add(sentence)
                log("the layers differ from the ones this folder was cut "
                    "from. Before: %s. Now: %s." % sentence, loud=True)
                iface.messageBar().pushMessage(
                    NAME, "this folder was cut from other layers or roles "
                    "(before: %s). The new choice is kept; cutouts of the two "
                    "may not stack." % sentence[0], level=LEVEL_WARNING,
                    duration=10)
        self.remember_layers(record)

    # ------------------------------------------- a cutout in the making
    @property
    def pending_path(self):
        return os.path.join(self.folder, PENDING_FILE)

    def note_pending(self, name):
        """Say, in the folder, that this cutout is being written. If the
        process dies before cutouts.csv has its rows, nothing else would ever
        say that the files with this name belong to nothing."""
        try:
            write_atomic(self.pending_path,
                         json.dumps({"cutout": name, "when": now()}))
        except OSError as err:
            log("cannot note that %s is being written: %s" % (name, err))

    def clear_pending(self):
        try:
            os.remove(long_path(self.pending_path))
        except OSError:
            pass

    def settle_interrupted(self):
        """A cutout that was being written when the process died: its files
        are in the folder and cutouts.csv does not list it. They are taken
        away, so that the name is free again and the folder holds whole
        cutouts only. A cutout the manifest does list is a whole one, whose
        note was left behind, and the note is all that goes. A manifest that
        cannot be read says nothing either way, and then nothing of the
        cutout is removed."""
        path = long_path(self.pending_path)
        if not self.folder or not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                name = str(json.load(f).get("cutout") or "")
        except (OSError, ValueError, AttributeError):
            name = ""
        rows = self.read_manifest()
        if name and rows is None:
            log("%s was being written when the last session ended, but "
                "cutouts.csv cannot be read to say whether it lists it: "
                "its files are left where they are" % name, loud=True)
        elif name and name not in [r.get("cutout") or "" for r in rows]:
            removed = []
            for folder in (self.folder, self.stac_folder()):
                try:
                    entries = os.listdir(long_path(folder))
                except OSError:
                    continue
                for entry in entries:
                    if entry == name or entry.startswith(name + "_") \
                            or entry.startswith(name + "."):
                        try:
                            os.remove(long_path(os.path.join(folder, entry)))
                            removed.append(entry)
                        except OSError as err:
                            log("cannot remove %s: %s" % (entry, err))
            log("%s was being written when the last session ended, and "
                "cutouts.csv does not list it: its %d file%s taken away%s"
                % (name, len(removed),
                   " was" if len(removed) == 1 else "s were",
                   (": " + ", ".join(removed[:4])
                    + (", ..." if len(removed) > 4 else "")) if removed
                   else ""), loud=True)
        self.clear_pending()

    def on_the_map(self, layer):
        """True when the layer is ticked in the Layers panel. A project with
        no tree to ask, or a layer the tree does not hold, counts as shown."""
        try:
            node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        except Exception:
            return True
        if node is None:
            return True
        try:
            return bool(node.isVisible())
        except Exception:
            return True

    @staticmethod
    def is_file_layer(layer):
        """False for a raster that comes from a service or a database, whose
        source is no path."""
        try:
            return layer.dataProvider().name() == "gdal"
        except Exception:
            return True

    def open_sources(self):
        """The layers to cut, opened, with the ones that cannot be put on the
        grid of the first left out and the reason kept in self.skipped."""
        self.skipped = {}
        alive = []
        for s in self.sources:
            layer = QgsProject.instance().mapLayer(s["id"])
            if layer is None:
                log("%s is no longer in the project, skipped" % s["tag"])
                self.skipped[s["tag"]] = "no longer in the project"
                continue
            s["layer"] = layer
            s["ds"] = open_raster(source_of(layer))
            if s["ds"] is None:
                # A web basemap or a database table is a valid layer and no
                # file GDAL opens: said as what it is, not as a broken file.
                log("cannot read %s, skipped" % s["tag"])
                self.skipped[s["tag"]] = "its file cannot be read" \
                    if self.is_file_layer(layer) else \
                    "it is not a raster file (a web or database layer)"
                continue
            s["limits"] = display_limits(layer, s["rgb"]) \
                if s["role"] == "image" else None
            s["moment"] = source_moment(s["ds"])
            s["readings"] = self.readings_of(s["ds"]) \
                if s["role"] == "classes" else None
            s["ignore"] = self.ignore_for(s) if s["role"] == "classes" \
                else (None, False, None)
            s["reproject"] = False
            s["src_wkt"] = None
            if s["role"] == "classes":
                self.warn_if_lossy(s)
            alive.append(s)
        if not alive:
            return []
        # Compared on the ground, not by definition. The orthomosaic that
        # taught this declares WGS 84 with a TOWGS84 of seven zeros, which GDAL
        # reads as a BOUNDCRS; the map of classes beside it is plain EPSG:4326.
        # The two definitions differ and the two systems are one, and a test
        # of the definitions with == left the image out of every cutout, in
        # whichever order the layers came, with a warning that said "is in
        # EPSG:4326 and the first layer is in EPSG:4326" and that the next
        # message covered.
        #
        # A layer whose system really is another is reprojected onto the grid,
        # or a map of classes and an image in two systems, which is a common
        # pair, could not be cut together at all. Only a layer with no system,
        # beside one that has one, is left out: there is nothing to say where
        # it is on the ground.
        first = alive[0]
        out = [first]
        told = self.__dict__.setdefault("_reprojected_told", set())
        for s in alive[1:]:
            if self.same_system(s["layer"], first["layer"]):
                out.append(s)
                continue
            mine = self.system_name(s["layer"].crs())
            theirs = self.system_name(first["layer"].crs())
            if s["layer"].crs().isValid() and first["layer"].crs().isValid():
                s["reproject"] = True
                # the systems as QGIS has them when a file does not say its
                # own, as when it was set in QGIS
                s["src_wkt"] = (None if s["ds"].GetProjection()
                                else s["layer"].crs().toWkt())
                s["dst_wkt"] = (first["ds"].GetProjection()
                                or first["layer"].crs().toWkt())
                out.append(s)
                if s["tag"] not in told:
                    told.add(s["tag"])
                    log("%s is in %s and %s, which sets the grid, is in %s: "
                        "it is reprojected onto that grid" % (
                            s["tag"], mine, first["tag"], theirs), loud=True)
                continue
            self.skipped[s["tag"]] = "it is in %s, the grid in %s" % (mine,
                                                                      theirs)
            log("%s is in %s and %s, which sets the grid, is in %s: with no "
                "system on one side there is no saying where its cutout "
                "would land, so it is left out"
                % (s["tag"], mine, first["tag"], theirs), loud=True)
        return out

    def ignore_wanted(self):
        """The ignore value of the dock, or None while it is off."""
        on = getattr(self, "ignore_on", None)
        if on is None or not on.isChecked():
            return None
        return int(self.ignore_value.value())

    def ignore_refused(self, quiet=False):
        """True, having said why, when the ignore value of the settings is
        one no cutout may hold: 0, a class code a campaign hands out, or
        past what a mask holds. Nothing is cut with it."""
        want = self.ignore_wanted()
        why = ignore_refusal(want) if want is not None else None
        if not why:
            return False
        log("cutouts refused: the ignore value %d: %s" % (want, why))
        if not quiet:
            QMessageBox.warning(
                self, NAME, "The ignore value under Settings cannot be used: "
                "%s.\n\nChange it, or untick 'unlabelled as ignore'." % why)
        return True

    def ignore_for(self, s):
        """(value, zero is unlabelled, why) for one layer cut as classes
        (cut_ignore_rule), said in the log once a session when the file's
        own value overrules the one in the dock."""
        try:
            own = s["ds"].GetMetadataItem("RASTERLABEL_IGNORE_INDEX")
        except Exception:
            own = None
        want = self.ignore_wanted()
        got = cut_ignore_rule(own, s.get("readings"), want)
        told = self.__dict__.setdefault("_ignore_told", set())
        if got[2] == "file" and want is not None and want != got[0] \
                and s["tag"] not in told:
            told.add(s["tag"])
            log("%s carries its own ignore value, %d, and keeps it: the %d "
                "of the settings is not used for it" % (s["tag"], got[0],
                                                        want), loud=True)
        return got

    def warn_if_lossy(self, s):
        """Say it, once a session for each map, when a map of classes is
        stored with a lossy codec. The codec moves the values along every edge
        between two classes, so the map holds codes that are no class, and
        the cutouts copied them as data without a word."""
        told = self.__dict__.setdefault("_lossy_told", set())
        key = os.path.normcase(source_of(s["layer"]) or s["tag"])
        if key in told:
            return
        told.add(key)
        codec = lossy_codec(source_of(s["layer"]) or "")
        if codec:
            log("%s is stored as %s, which is lossy: its class codes carry "
                "compression noise along the edges, values that are no "
                "class, and the cutouts copy them as they are"
                % (s["tag"], codec), loud=True)

    @staticmethod
    def centre_of(layer):
        try:
            c = layer.extent().center()
            return (c.x(), c.y())
        except Exception:
            return None

    def same_system(self, layer, grid_layer):
        """True when two layers are in one coordinate system on the ground:
        the same definition, the same registered name once named_crs has
        looked through a binding that does nothing, or a point that stays
        where it was when it is moved from one to the other."""
        a, b = layer.crs(), grid_layer.crs()
        if a == b:
            return True
        if not a.isValid() or not b.isValid():
            return not a.isValid() and not b.isValid()
        here, there = self.centre_of(layer), self.centre_of(grid_layer)
        try:
            na, nb = named_crs(a, here), named_crs(b, there)
            if na.authid() and na.authid() == nb.authid():
                return True
        except Exception:
            pass
        try:
            return bool(same_ground(a, b, here))
        except Exception:
            return False

    @staticmethod
    def system_name(crs):
        """The system as the log says it, with the description beside the
        code when the code came from named_crs: two layers called EPSG:4326
        in one sentence must not look the same when they are not."""
        label = crs_label(crs)
        try:
            if crs.isValid() and not crs.authid() and crs.description():
                return "%s (%s)" % (label, crs.description())
        except Exception:
            pass
        return label

    def output_wkt(self, source):
        """The system the files of a cutout are written in.

        The grid layer's own, except when it has no code and a registered
        system is the same on the ground: then that one, by its code. Written
        as it came, a BOUNDCRS spread from the orthomosaic into every file of
        the dataset, into the footprints and into the catalogue, all of them
        in a system with no name that the next program has to work out
        again."""
        own = source["ds"].GetProjection() or ""
        crs = source["layer"].crs()
        try:
            if not crs.isValid() or crs.authid():
                return own
            named = named_crs(crs, self.centre_of(source["layer"]))
            code = named.authid()
            if not code:
                return own
            srs = osr.SpatialReference()
            if srs.SetFromUserInput(code) == 0:
                return srs.ExportToWkt() or own
            return named.toWkt() or own
        except Exception:
            return own

    # ----------------------------------------------------------- cutting
    def aim_measure(self):
        """The ruler of square_at, in the system the canvas is in now.

        On the project's ellipsoid only when that system is a real one. Given
        an ellipsoid and no valid system, QGIS takes the coordinates for
        degrees: on a picture with no georeference one unit came out as about
        a hundred kilometres, and past 90 as NaN, which reached the window of
        a click and stopped it with "cannot convert float NaN to integer"."""
        crs = canvas().mapSettings().destinationCrs()
        try:
            self.measure.setSourceCrs(crs,
                                      QgsProject.instance().transformContext())
            self.measure.setEllipsoid(project_ellipsoid() if crs.isValid()
                                      else "NONE")
        except Exception:
            pass

    def first_layer(self):
        """The layer that sets the grid, as the project holds it now."""
        if not self.sources:
            return None
        try:
            return QgsProject.instance().mapLayer(self.sources[0]["id"])
        except Exception:
            return None

    def square_at(self, point):
        """A square of the chosen side in true metres, around a point of the
        canvas, whatever the canvas system is.

        When the layer that sets the grid has no coordinate system, its units
        are pixels or whatever its world file counts in, and the side is in
        those units: one to a metre, which is what the side box counts its
        pixels with. Measured in the system of the canvas it would take the
        units of a picture for degrees."""
        first = self.first_layer()
        wide = tall = 1.0
        try:
            known = first is None or first.crs().isValid()
        except Exception:
            known = True
        if known:
            self.aim_measure()
            try:
                wide = self.measure.measureLine(
                    QgsPointXY(point.x(), point.y()),
                    QgsPointXY(point.x() + 1.0, point.y()))
                tall = self.measure.measureLine(
                    QgsPointXY(point.x(), point.y()),
                    QgsPointXY(point.x(), point.y() + 1.0))
            except Exception:
                wide = tall = 1.0
        # NaN is not caught by "or 1.0", nor is an infinity or a negative
        # length: anything but a finite length above zero is one unit
        if not (isinstance(wide, (int, float)) and math.isfinite(wide)
                and wide > 0):
            wide = 1.0
        if not (isinstance(tall, (int, float)) and math.isfinite(tall)
                and tall > 0):
            tall = 1.0
        hx = self.side.value() / 2.0 / wide
        hy = self.side.value() / 2.0 / tall
        return QgsRectangle(point.x() - hx, point.y() - hy,
                            point.x() + hx, point.y() + hy)

    def save_first(self):
        """Write the campaign down before reading anything off the disk.

        The layers being cut are read with gdal, from the file, not through
        QGIS. Anything still sitting in an open edit session is invisible to
        them. This matters less here than in Annotate, since the ground truth
        of a cutout is usually a layer somebody else made, but a campaign whose
        own package is half committed is a campaign whose next rollback throws
        away what a cutout already copied."""
        panel = self.panel
        for module in (panel.section, panel.annotation):
            if module is None or module is self or not module.unsaved():
                continue
            try:
                module.save()
            except Exception as err:
                log("could not save before cutting: %s" % err, loud=True)

    def start_cutting(self):
        if not self.sources:
            QMessageBox.warning(self, NAME, "Choose the layers first.")
            return
        if self.tool is None:
            self.tool = CutoutTool(canvas(), self)
        canvas().setMapTool(self.tool)
        log("cutting: click for a square of %.2f m, drag for a free rectangle, "
            "right click to undo the last one, Esc to stop." % self.side.value())

    def stop_cutting(self):
        if self.tool is not None and canvas().mapTool() is self.tool:
            canvas().unsetMapTool(self.tool)
        log("stopped cutting, %d cutouts in %s" % (self.count, self.folder))

    def release_tools(self):
        self.stop_cutting()
        # Called while the module is being closed; once it is gone the panel
        # lets the log go from Cutouts.
        panel_ = self.panel
        QTimer.singleShot(0, lambda: CutoutsSection.reroute(panel_))

    def export_all_tiles(self):
        if self.campaign is None:
            return
        tiles = find_mine(self.campaign.data["id"], "tiles")
        if tiles is None:
            return
        features = [f for f in tiles.getFeatures() if f.hasGeometry()]
        if not features:
            QMessageBox.information(self, NAME, "This campaign has no tile yet.")
            return
        q = QMessageBox.question(
            self, "All tiles",
            "Cut one subset for each of the %d tiles?" % len(features))
        if q != QMessageBox.StandardButton.Yes:
            return
        if self.ignore_refused():
            return
        self.save_first()
        if not self.folder_is_usable():
            return
        done, refused, broken = 0, 0, []
        for f in features:
            try:
                side = float(f["side_m"] or 0) or None
            except (TypeError, ValueError):
                side = None
            try:
                if self.export(f.geometry().boundingBox(), quiet=True,
                               tile_id=str(f["tile_id"]), nominal=side):
                    done += 1
                else:
                    refused += 1
            except Exception as err:
                # One frame that cannot be written is one frame, not the whole
                # batch: an exception walking out of the loop would leave the
                # remaining frames untried, with no dialog to say so.
                broken.append(str(f["tile_id"]))
                log("tile %s could not be cut: %s" % (f["tile_id"], err))
            QApplication.processEvents()
        self.show_state()
        message = "%d cutout%s written in\n%s" % (
            done, "" if done == 1 else "s", self.folder)
        if refused:
            message += "\n\n%d frames were refused: too small, outside the " \
                       "first layer, or too large." % refused
        if broken:
            message += "\n\n%d could not be written at all: %s.\nThe log says " \
                       "why for each." % (len(broken), ", ".join(broken[:12]))
        QMessageBox.information(self, NAME, message)

    # ----------------------------------------------------------- the export
    def export(self, rect, quiet=False, tile_id=None, nominal=None):
        """Write one cutout. `nominal` is the side in metres that was asked
        for, when one was: a click of the fixed side or a frame. It is None for
        a rectangle dragged by hand, which is meant to be its own size and is
        left alone by the rule that keeps every piece of a given side the same
        number of pixels."""
        if self.ignore_refused(quiet):
            return False
        if not quiet:
            self.save_first()
            if not self.folder_is_usable():
                return False
        sources = self.open_sources()
        if not sources:
            if not quiet:
                QMessageBox.warning(self, NAME, "No layer can be read.")
            return False
        view = canvas().mapSettings().destinationCrs()
        target = sources[0]["layer"].crs()
        if tile_id is None and view != target:
            rect = QgsCoordinateTransform(
                view, target, QgsProject.instance()).transformBoundingBox(rect)
        elif tile_id is not None and self.geometry is not None \
                and self.geometry.crs != target:
            rect = QgsCoordinateTransform(
                self.geometry.crs, target,
                QgsProject.instance()).transformBoundingBox(rect)

        reference = sources[0]["ds"]
        size = (reference.RasterXSize, reference.RasterYSize)
        # A raster stored bottom row first is cut on the same grid counted
        # from the top, and its cutouts come out north up like every other.
        gt0 = north_up_of(reference)
        if is_rotated(gt0):
            # A window of whole pixels cannot be laid on a rotated grid:
            # snapped as if the grid were north up, the cutout would hold
            # other pixels than the ones under the rectangle, and some clicks
            # would be refused as outside a layer they were on.
            if not quiet:
                QMessageBox.warning(
                    self, NAME, "'%s', which sets the grid of the cutouts, "
                    "has a rotated pixel grid: its rows are not parallel to "
                    "the x axis, and no cutout of whole pixels can be laid on "
                    "it.\n\n%s, and cut that one, or let another layer set "
                    "the grid in Layers." % (sources[0]["layer"].name(),
                                              ROTATED_ADVICE))
            log("cutout refused: %s, which sets the grid, is rotated"
                % sources[0]["tag"])
            return False
        col, row, w, h = snap(gt0, size, rect)
        if w < 2 or h < 2:
            if not quiet:
                iface.messageBar().pushMessage(
                    NAME, "the rectangle falls outside the first layer",
                    level=LEVEL_WARNING, duration=3)
            return False
        if nominal is not None and tile_id is None:
            # A click: the square the side box announces, so many pixels on
            # each side, centred on the click. Not the square measured on the
            # ground and then snapped outwards to whole pixels, which almost
            # never falls on pixel edges and so comes out one pixel larger
            # than the box says, 201 for 200 and 4 for 3, forty metres for
            # thirty; and shapes.json would then hold that size for every
            # later cutout of the side.
            col, row, w, h = self.clicked_window(sources[0]["layer"], gt0,
                                                 rect, nominal)
            if not self.same_size.isChecked():
                c1, r1 = min(col + w, size[0]), min(row + h, size[1])
                col, row = max(col, 0), max(row, 0)
                w, h = c1 - col, r1 - row
                if w < 2 or h < 2:
                    if not quiet:
                        iface.messageBar().pushMessage(
                            NAME, "the rectangle falls outside the first "
                            "layer", level=LEVEL_WARNING, duration=3)
                    return False
        if nominal is not None and self.same_size.isChecked():
            if tile_id is not None:
                col, row, w, h = snap(gt0, size, rect, clip=False)
            w, h = self.hold_shape(nominal, w, h, gt0[1])
        if w * h > MAX_WINDOW_PX:
            if not quiet:
                iface.messageBar().pushMessage(
                    NAME, "that cutout would be %d by %d pixels" % (w, h),
                    level=LEVEL_WARNING, duration=4)
            return False
        gt = window_transform(gt0, col, row)
        wkt = self.output_wkt(sources[0])
        extent = QgsRectangle(gt[0], gt[3] + h * gt[5],
                              gt[0] + w * gt[1], gt[3])

        # The ground truth of a cutout is a LAYER marked "classes", never the
        # annotation of the campaign. This module exists for the other job: you
        # already have a map and some imagery and you want a dataset out of
        # them. What is drawn by hand is written from Annotate, where it lives,
        # and burning it here as well would have made the same reading come out
        # of two places with two different sets of rules.
        os.makedirs(long_path(self.folder), exist_ok=True)
        self.settle_interrupted()
        self.check_layers()
        name = self.free_name()
        files, rows = [], []
        assets = {}
        sizes = set()

        # before the first file: if this process is killed from here to the
        # rows in cutouts.csv, the next session finds the note and the files
        self.note_pending(name)
        try:
            self.cut_layers(sources, name, gt, w, h, wkt, extent, tile_id,
                            files, rows, assets, sizes)
        except Exception as err:
            # Everything this cutout managed to write is taken away again. Half
            # a cutout on disk is worse than none: it is not in cutouts.csv, so
            # undo cannot reach it, and a year later it looks like a piece of
            # the dataset that simply has fewer files than the others.
            # Every path is in the list before its writer is called, so a
            # writer that made its file and then raised is cleaned up too.
            for path in files:
                for gone in (path, path + ".aux.xml"):
                    try:
                        os.remove(long_path(gone))
                    except OSError:
                        pass
            self.clear_pending()
            log("%s was abandoned: %s" % (name, err))
            if not quiet:
                QMessageBox.critical(
                    self, NAME,
                    "%s could not be written, and the pieces of it that had "
                    "already landed have been removed.\n\n%s" % (name, err))
            return False

        if len(sizes) > 1 and not quiet:
            iface.messageBar().pushMessage(
                NAME,
                "%s: the layers came out in %d different sizes (%s). They will "
                "not stack. Turn 'one common pixel grid' on."
                % (name, len(sizes),
                   ", ".join("%dx%d" % t for t in sorted(sizes))),
                level=LEVEL_WARNING, duration=8)
            log("%s: sizes %s" % (name, sorted(sizes)))
        return self.finish_cutout(name, files, rows, assets, extent, gt, w, h,
                                  wkt, tile_id, quiet)

    @staticmethod
    def clicked_window(layer, gt0, rect, nominal):
        """The window of a click: as many pixels a side as the side box says,
        round(side / pixel), centred on the middle of the square clicked.

        The pixel is measured on the ground, by the same pixel_on_the_ground
        the box uses, so a side of 10 m on 5 cm pixels is 200 by 200, and on
        pixels of 5 by 7 cm it is 200 by 143: square in pixels on square
        pixels, the same ground both ways otherwise."""
        try:
            px, py = pixel_on_the_ground(layer)
            px, py = float(px), float(py)
        except (TypeError, ValueError, AttributeError):
            px, py = abs(gt0[1]), abs(gt0[5])
        if not (math.isfinite(px) and px > 0):
            px = abs(gt0[1])
        if not (math.isfinite(py) and py > 0):
            py = abs(gt0[5])
        w = max(2, int(round(nominal / px)))
        h = max(2, int(round(nominal / py)))
        centre = rect.center()
        col = int(np.floor((centre.x() - gt0[0]) / gt0[1] - w / 2.0 + 0.5))
        row = int(np.floor((centre.y() - gt0[3]) / gt0[5] - h / 2.0 + 0.5))
        return col, row, w, h

    def side_of(self, ruler, extent, crs):
        """The side written in cutouts.csv: on the ground in metres, or in the
        units of the layer when it has no system, never NaN. An ellipsoid on a
        layer with no system measured its pixels as degrees and wrote nan."""
        a = QgsPointXY(extent.xMinimum(), extent.yMinimum())
        b = QgsPointXY(extent.xMaximum(), extent.yMinimum())
        side = float("nan")
        try:
            if crs is not None and crs.isValid():
                side = float(ruler.measureLine(a, b))
        except Exception:
            pass
        if not (math.isfinite(side) and side > 0):
            side = abs(extent.xMaximum() - extent.xMinimum())
        return side

    def cut_layers(self, sources, name, gt, w, h, wkt, extent, tile_id,
                   files, rows, assets, sizes):
        """One file per layer, on the grid the first layer set.

        Raises as soon as anything refuses to be written. The caller takes away
        what had already landed, so a cutout is all there or not there at
        all. Every path goes into files BEFORE its writer is called: a writer
        that made its file and then raised would otherwise leave it behind,
        out of every book."""
        # The side is measured in the system of the first layer, whatever
        # the canvas is in: there may be no campaign to lend its ruler.
        system = sources[0]["layer"].crs()
        ruler = ground_measure(system)
        for s in sources:
            # A layer reprojected from another system has no grid of its own
            # in the system of the cutout: it goes on the common one even
            # when each layer keeps its own grid.
            if self.common.isChecked() or s.get("reproject"):
                grid, ww, hh = gt, w, h
            else:
                own = north_up_of(s["ds"])
                v = snap(own, (s["ds"].RasterXSize, s["ds"].RasterYSize), extent)
                if v[2] < 2 or v[3] < 2:
                    log("%s: the cutout falls outside it, skipped" % s["tag"])
                    self.skipped[s["tag"]] = "the cutout falls outside it"
                    continue
                grid, ww, hh = window_transform(own, v[0], v[1]), v[2], v[3]
            stem = os.path.join(self.folder, "%s_%s" % (name, s["tag"]))
            sizes.add((ww, hh))
            driver, extension, kind = shape_of(s.get("driver"), s["role"])
            if (s["role"] == "classes" and driver == "PNG"
                    and self.class_type(s) not in (gdal.GDT_Byte,
                                                   gdal.GDT_UInt16)):
                # A PNG holds bytes and unsigned 16 bit values, nothing else,
                # and GDAL writes anything else into one as bytes, clamped,
                # with a warning on the console only: a map with a nodata of
                # -9999 had its class 300 come out as 255. Such a map goes out
                # as a GeoTIFF, the way a map of classes asked for as JPEG
                # does.
                driver, extension, kind = shape_of("GTiff", s["role"])
                if s["tag"] not in self.__dict__.setdefault("_png_refused",
                                                            set()):
                    self._png_refused.add(s["tag"])
                    log("%s holds values a PNG cannot (negative, or past 16 "
                        "bits): its classes are cut as GeoTIFF" % s["tag"],
                        loud=True)
            before = set(assets)
            if s["role"] == "classes":
                bands, resampled, stretch = self.cut_classes(
                    s, stem, grid, ww, hh, wkt, driver, extension, kind,
                    files, assets)
            else:
                bands, resampled, stretch = self.cut_image(
                    s, stem, grid, ww, hh, wkt, driver, extension, kind,
                    files, assets)
            if (tuple(grid), ww, hh) != (tuple(gt), w, h):
                # A layer on a grid of its own: the item says the grid of
                # the first layer, and this file has another size, another
                # transform, another box. Said on the asset, where the
                # projection extension allows it, instead of being left to
                # read as the item's.
                box = (grid[0], grid[3] + hh * grid[5],
                       grid[0] + ww * grid[1], grid[3])
                own = {k: v for k, v in projection_of(
                    grid, ww, hh, wkt, box).items()
                    if k in ("proj:shape", "proj:transform", "proj:bbox")}
                for key in set(assets) - before:
                    entry = assets[key]
                    if "data" in entry[2]:
                        more = dict(entry[4]) if len(entry) > 4 and entry[4] \
                            else {}
                        more.update(own)
                        assets[key] = tuple(entry[:4]) + (more,)

            ign = (s.get("ignore") or (None,))[0] \
                if s["role"] == "classes" else None
            rows.append({"cutout": name, "tag": s["tag"], "role": s["role"],
                         "layer": s["layer"].name(),
                         "bands": " ".join(str(b) for b in bands),
                         "resampled": int(bool(resampled)),
                         "stretch": stretch,
                         "tile_id": tile_id or "",
                         "xmin": "%.9f" % extent.xMinimum(),
                         "ymin": "%.9f" % extent.yMinimum(),
                         "xmax": "%.9f" % extent.xMaximum(),
                         "ymax": "%.9f" % extent.yMaximum(),
                         # the edges of THIS file: a layer on a grid of its
                         # own can be clipped by its own edge and then is
                         # smaller than the extent above. Not a column of
                         # cutouts.csv; the detection labels read it.
                         "grid_box": (grid[0], grid[3] + hh * grid[5],
                                      grid[0] + ww * grid[1], grid[3]),
                         "width_px": ww, "height_px": hh,
                         "format": driver,
                         # the side this cutout really has, measured on its own
                         # window. The spin box would be a lie for every hand
                         # dragged rectangle and for every frame whose side is
                         # not the current one
                         "side_m": "%.3f" % self.side_of(ruler, extent,
                                                         system),
                         "when": now(),
                         "ignore_index": "" if ign is None else str(ign)})
            if resampled:
                log("%s: %s %s onto the grid by %s" % (
                    name, s["tag"], "reprojected and resampled"
                    if s.get("reproject") else "resampled", resampled))

    @staticmethod
    def read_layer(s, bands, grid, ww, hh, wkt, pad_nan=False):
        """read_on_grid for one layer: by its role, and reprojected into the
        system of the grid when it is in another."""
        target = (s.get("dst_wkt") or wkt) if s.get("reproject") else None
        if pad_nan:
            return read_on_grid(s["ds"], bands, grid, ww, hh, role=s["role"],
                                wkt=target, src_wkt=s.get("src_wkt"),
                                pad_nan=True)
        return read_on_grid(s["ds"], bands, grid, ww, hh, role=s["role"],
                            wkt=target, src_wkt=s.get("src_wkt"))

    def cut_classes(self, s, stem, grid, ww, hh, wkt, driver, extension, kind,
                    files, assets):
        """The class codes as they are, and their coloured picture.

        A layer of classes written as PNG would be one grey PNG of codes one
        to four, nearly black to the eye, if the coloured copy were skipped
        because the main file is a PNG already, whatever "also write PNG
        copies" says. The codes stay in the main file, which is what a loader
        reads, and the picture goes beside it under its own name."""
        bands = [s["band"]]
        ign, zero_unlabelled, whence = s.get("ignore") or (None, False, None)
        array, nodata, resampled = self.read_layer(
            s, bands, grid, ww, hh, wkt, pad_nan=ign is not None)
        # A byte, unless the map holds a value that does not fit in one:
        # decided once per map, so every cutout of it has the same type.
        held = self.class_type(s)
        path = stem + "_classes" + extension
        # The map's own nodata, when it has one a cutout can declare. It is
        # declared as the nodata of the cutout and is no class: no colour,
        # nothing in the picture.
        declared = class_nodata(s["ds"], s["band"], held) \
            if ign is None else None
        if ign is None:
            v = array[0]
            if declared is not None and nodata[0] is not None \
                    and not is_class_code(nodata[0]):
                # a nodata no integer holds: written as the code declared
                # for it, or as 0 where a PNG cannot declare one, and never
                # cast, which gave the smallest 32 bit number
                v = np.where(np.isfinite(v) & (v != nodata[0]), v,
                             declared if driver == "GTiff" else 0)
            codes = np.nan_to_num(v, nan=0.0).astype(class_array(held))
        else:
            # Where the layer holds nothing: past its edge, its own nodata,
            # and the 0 of a campaign mask that means "nobody painted".
            # Any other 0 is left as it is: in a map made elsewhere it may
            # be a class, and in a mask with an ignore value of its own it
            # is "none of these", inside a frame.
            v = array[0]
            unlabelled = ~np.isfinite(v)
            if nodata[0] is not None:
                unlabelled |= v == nodata[0]
            if zero_unlabelled:
                unlabelled |= v == 0
            if np.any(v[~unlabelled] == ign):
                raise ValueError(
                    "%s holds %d inside this cutout, the value chosen for "
                    "ignore: choose another value." % (s["layer"].name(), ign))
            codes = np.where(unlabelled, ign, np.nan_to_num(v, nan=0.0)) \
                .astype(class_array(held))
        # No nodata is declared on a class raster for its 0. Zero here means
        # "no class", which is a value with a meaning, not an absence: a
        # reader honouring a nodata of zero would throw those pixels away
        # and could no longer tell them from outside the image. The ignore
        # value is declared, because it is the absence.
        files.append(path)
        if ign is not None:
            put_raster(driver, path, codes[None], grid, wkt, dtype=held,
                       nodata=ign if driver == "GTiff" else None)
        else:
            put_raster(driver, path, codes[None], grid, wkt, dtype=held,
                       nodata=declared if driver == "GTiff" else None)
        carried = dict(s.get("readings") or {})
        if ign is not None and whence != "file":
            # what this cutout holds where nobody labelled, said inside it,
            # so a cutout of it keeps the value and a reader is told
            consensus = carried.get("RASTERLABEL_READING_MODE") == "consensus"
            carried.update({
                "RASTERLABEL_UNLABELLED": "ignore" if zero_unlabelled
                else "map",
                "RASTERLABEL_UNLABELLED_RULE":
                    unlabelled_rule("ignore", ign, consensus)
                    if zero_unlabelled else
                    "%d past the edge and where the map has no data; its "
                    "own values, 0 included, as they are" % ign,
                "RASTERLABEL_IGNORE_INDEX": str(int(ign))})
        if carried and driver == "GTiff":
            # the mask of a campaign, written by Whole: which readings it
            # holds goes on into every cutout of it
            self.carry_readings(path, carried)
        named = (style_classes(s["layer"], s["band"]) if driver == "GTiff"
                 else None)
        if named:
            # The classes of the layer's style, as the colour table and
            # category names of the GeoTIFF: it opens in QGIS, and in
            # whatever reads GDAL, in the colours of the PNG beside it,
            # instead of grey. The codes are not touched.
            said = dress_class_band(
                path, 1, self.class_colours(s["layer"], s["band"], codes,
                                            ign if declared is None
                                            else declared))
            if said.startswith("no "):
                log(said)
        bands_entry = {"data_type": self.stac_type(held)}
        extra = {"raster:bands": [bands_entry]}
        if ign is not None:
            bands_entry["nodata"] = int(ign)
        elif declared is not None:
            bands_entry["nodata"] = declared
        # The classes of the layer's style, with or without an ignore value:
        # whoever is handed the item cannot tell what a 3 is from the codes.
        listed = style_classes(s["layer"], s["band"]) or []
        if ign is not None or listed:
            extra["classification:classes"] = cut_class_entries(listed, ign)
        assets["%s_classes" % s["tag"]] = (
            path, kind, ["data", "labels"],
            "%s, the class codes as they arrived, in %s"
            % (s["tag"], gdal.GetDataTypeName(held)), extra)
        if self.png.isChecked():
            picture = stem + ("_classes_colour.png" if driver == "PNG"
                              else "_classes.png")
            files.append(picture)
            hole = ign if declared is None else declared
            seen = codes > 0 if ign is None else (codes != 0) & (codes != ign)
            if declared is not None:
                seen &= codes != declared
            write_png(picture, colour_table(
                codes, self.class_colours(s["layer"], s["band"], codes, hole)),
                np.where(seen, 255, 0).astype(np.uint8))
            assets["%s_classes_png" % s["tag"]] = (
                picture, "image/png", ["overview"],
                "%s, coloured for looking at" % s["tag"])
        return bands, resampled, ""

    def cut_image(self, s, stem, grid, ww, hh, wkt, driver, extension, kind,
                  files, assets):
        """An image, by its own rules, and a picture of it as QGIS shows it.

        As a GeoTIFF it is the source itself over the window: every band, in
        its own data type, with its own nodata and its own band names, the
        first three called red, green and blue. Three bands stretched to
        bytes whatever the source is would turn a survey of seven bands of
        sixteen bits into a picture of three, and lose the four bands nobody
        looks at, which are the reason for a survey of seven.

        The picture is made from the style of the layer: its bands and its
        stretch, the way the image is on the screen. It is for looking at,
        not for reading numbers off, and it is transparent where the image
        has no data. A PNG or a JPEG asked for as the main file is that
        picture: neither can hold the image as it is."""
        ds = s["ds"]
        rgb = list(s["rgb"])
        if driver == "GTiff":
            bands = list(range(1, ds.RasterCount + 1))
        else:
            bands = rgb
        array, nodata, resampled = self.read_layer(s, bands, grid, ww, hh, wkt)
        at = {b: i for i, b in enumerate(bands)}
        valid = np.ones((hh, ww), bool)
        for b in rgb:
            i = at.get(b)
            if i is None:
                continue
            if nodata[i] is not None:
                valid &= array[i] != nodata[i]
            valid &= np.isfinite(array[i])

        if driver == "GTiff":
            path = stem + "_image" + extension
            files.append(path)
            self.write_native(ds, path, array, nodata, grid, wkt)
            assets["%s_image" % s["tag"]] = (
                path, kind, ["data"],
                "%s, every band as in the source: %d of %s"
                % (s["tag"], len(bands), gdal.GetDataTypeName(
                    self.native_type(ds))),
                {"raster:bands": [
                    dict({"data_type": self.stac_type(self.native_type(ds))},
                         **({} if nd is None else {"nodata": nd}))
                    for nd in nodata]})
        picture, alpha, stretch = None, None, ""
        if driver != "GTiff" or self.png.isChecked():
            picture, alpha, stretch = self.preview(
                s, grid, ww, hh, [array[at[b]] for b in rgb], valid)
        if driver != "GTiff":
            path = stem + "_image" + extension
            files.append(path)
            if driver == "PNG":
                write_png(path, picture, alpha)
            else:
                put_raster(driver, path, picture, grid, wkt)
            assets["%s_image" % s["tag"]] = (
                path, kind, ["data"],
                "%s, a picture of bands %s as QGIS shows them"
                % (s["tag"], " ".join(str(b) for b in rgb)))
        elif self.png.isChecked():
            q = stem + "_image.png"
            files.append(q)
            write_png(q, picture, alpha)
            assets["%s_image_png" % s["tag"]] = (
                q, "image/png", ["overview"],
                "%s, bands %s as QGIS shows them, without coordinates"
                % (s["tag"], " ".join(str(b) for b in rgb)))
        return bands, resampled, stretch

    def class_type(self, s):
        """class_band_type, kept for the session: it reads the whole band
        once, and a map cut a hundred times is read once. With the ignore
        value it is cut with, which the type has to hold as well."""
        known = self.__dict__.setdefault("_class_types", {})
        ign = (s.get("ignore") or (None,))[0]
        key = (s["ds"].GetDescription(), s["band"], ign)
        if key not in known:
            known[key] = class_band_type(s["ds"], s["band"]) if ign is None \
                else class_band_type(s["ds"], s["band"], ign)
        return known[key]

    @staticmethod
    def readings_of(ds):
        """The RASTERLABEL_ items of a mask written by Whole, or None."""
        try:
            items = ds.GetMetadata() or {}
        except Exception:
            return None
        found = {k: v for k, v in items.items()
                 if k.startswith("RASTERLABEL_")}
        return found if "RASTERLABEL_READING_MODE" in found else None

    @staticmethod
    def carry_readings(path, readings):
        try:
            out = gdal.Open(long_path(path), gdal.GA_Update)
            if out is not None:
                for k, v in readings.items():
                    out.SetMetadataItem(k, v)
                out.FlushCache()
            out = None
        except Exception as err:
            log("cannot write which readings %s holds: %s"
                % (os.path.basename(path), err))

    @staticmethod
    def native_type(ds):
        """One data type that holds every band of the source."""
        kind = ds.GetRasterBand(1).DataType
        for b in range(2, ds.RasterCount + 1):
            other = ds.GetRasterBand(b).DataType
            if other != kind:
                kind = gdal.DataTypeUnion(kind, other)
        return kind

    def write_native(self, ds, path, array, nodata, grid, wkt):
        """The bands as they are, in the data type of the source.

        read_on_grid hands them back as floats, with the nodata of the band
        where the window runs past the edge and NaN where the band has none;
        those pixels become zero, which is what GDAL fills a new band with.
        Filled in place: seven bands of a large rectangle are a lot of
        memory once, and there is no need to hold them twice.

        Zero in an image with no nodata is black, and black is ground too: the
        padding past the edge of the raster could not be told from a black
        roof in the GeoTIFF, only in its PNG. So where a band has no nodata
        and the window was padded, the file gets a mask of its own (a GDAL
        internal mask, which QGIS and rasterio read as transparency): 0 over
        the padding, 255 over the image. The values are not touched.

        A resampled band comes back with fractions, and an integer band is
        given the nearest whole number rather than whatever the cast makes
        of them."""
        mask = None
        if any(nd is None for nd in nodata):
            pad = ~np.isfinite(array).all(axis=0)
            if pad.any():
                mask = np.where(pad, 0, 255).astype(np.uint8)
        kind = self.native_type(ds)
        whole = not gdal.GetDataTypeName(kind).startswith(("Float", "CFloat"))
        for i in range(array.shape[0]):
            bad = ~np.isfinite(array[i])
            if bad.any():
                array[i][bad] = nodata[i] if nodata[i] is not None else 0.0
            if whole:
                np.rint(array[i], out=array[i])
        n = ds.RasterCount
        colours = None
        if n >= 3:
            colours = [gdal.GCI_RedBand, gdal.GCI_GreenBand, gdal.GCI_BlueBand]
            for b in range(4, n + 1):
                own = ds.GetRasterBand(b).GetColorInterpretation()
                colours.append(own if own == gdal.GCI_AlphaBand
                               else gdal.GCI_Undefined)
        names = [ds.GetRasterBand(b).GetDescription() for b in range(1, n + 1)]
        write_tif(path, array, grid, wkt, nodata=list(nodata),
                  dtype=kind, colours=colours, names=names, mask=mask)

    def preview(self, s, grid, ww, hh, rgb, valid):
        """The picture of an image: the style of the layer when QGIS can draw
        it, and when it cannot, the three bands of the style stretched by the
        limits of that style, or by the cutout itself. Gives the bands, the
        alpha and the words the manifest keeps for how it was made."""
        # The renderer draws a layer in its own system: one reprojected onto
        # the grid of another is stretched from its bands instead.
        drawn = (None if s.get("reproject")
                 else self.styled_preview(s["layer"], grid, ww, hh))
        if drawn is not None:
            picture, alpha = drawn
            alpha = np.where(valid, alpha, 0).astype(np.uint8)
            return picture, alpha, "as styled in QGIS"
        limits = s.get("limits")
        stretch = "layer limits"
        if limits is None or len(limits) < len(rgb):
            limits, stretch = [], "per cutout"
            for band in rgb:
                v = band[valid]
                limits.append((float(np.percentile(v, 2)),
                               float(np.percentile(v, 98)))
                              if v.size else (0.0, 1.0))
        picture = np.zeros((3, hh, ww), np.uint8)
        for i, (low, high) in enumerate(limits[:3]):
            scaled = (rgb[i] - low) / max(high - low, 1e-6)
            # a band that is all one value, or all NaN, would put NaN into
            # the cast and a warning into the log for every cutout
            scaled = np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0)
            picture[i] = (255 * np.clip(scaled, 0, 1)).astype(np.uint8)
        picture[:, ~valid] = 0
        return picture, np.where(valid, 255, 0).astype(np.uint8), stretch

    def styled_preview(self, layer, grid, ww, hh):
        """The window drawn by the layer's own renderer, as the screen has it:
        the bands it shows, its stretch, its palette. Returns the three
        bands and the alpha, or None when it cannot be drawn here, which is
        never a reason to lose the cutout."""
        if abs(grid[2]) + abs(grid[4]) > 0 or grid[5] >= 0:
            return None
        try:
            renderer = layer.renderer()
            extent = QgsRectangle(grid[0], grid[3] + hh * grid[5],
                                  grid[0] + ww * grid[1], grid[3])
            block = renderer.block(1, extent, ww, hh)
            if block is None or not block.isValid():
                return None
            image = block.image()
            if image is None or image.isNull() \
                    or (image.width(), image.height()) != (ww, hh):
                return None
            image = image.convertToFormat(QImage.Format.Format_RGBA8888)
            line = image.bytesPerLine()
            bits = image.constBits()
            bits.setsize(line * hh)
            data = np.frombuffer(bits, np.uint8).reshape(hh, line)
            data = data[:, :ww * 4].reshape(hh, ww, 4)
            picture = np.ascontiguousarray(data[:, :, :3].transpose(2, 0, 1))
            alpha = np.ascontiguousarray(data[:, :, 3])
            return picture, alpha
        except Exception as err:
            log("%s could not be drawn with its style, the picture is "
                "stretched from its bands instead: %s" % (layer.name(), err))
            return None

    def finish_cutout(self, name, files, rows, assets, extent, gt, w, h, wkt,
                      tile_id, quiet):
        """The books, once every file of the cutout is safely on disk."""
        if not files:
            self.clear_pending()
            return False
        self.append_csv(rows)
        # Listed now, so whole: the note that it was in the making goes. Had
        # the row not been written (it says so, loudly), the files stay, as
        # they always did, and are not taken away by the next session.
        self.clear_pending()
        self.write_footprint(name, extent, w, h, wkt, tile_id)
        self.write_sampler()
        self.write_detection(name, rows, assets, files, wkt)
        if self.stac.isChecked():
            # the roles of what was written, not of what was asked for: an
            # item would say "classes, image" while it held the classes only
            files += self.write_stac(name, extent, gt, w, h, wkt, tile_id,
                                     assets,
                                     roles=sorted({r["role"] for r in rows}))
        # cutouts.csv, the footprints and the catalogue are the books of the
        # folder. Nothing goes into a campaign: there may be none, and the
        # folder is what describes itself.
        self.written.append((name, files))
        self.count += 1
        cut = ", ".join("%s as %s" % (r["tag"], r["role"]) for r in rows)
        left = "; ".join("%s left out: %s" % (t, why)
                         for t, why in sorted(self.skipped.items()))
        log("%s written, %d by %d pixels: %s%s. Files: %s"
            % (name, w, h, cut, ("; " + left) if left else "",
               ", ".join(os.path.basename(f) for f in files)))
        if not quiet:
            self.show_state()
            iface.messageBar().pushMessage(
                NAME, "%s written, %d by %d pixels: %s%s"
                % (name, w, h, cut, ("; " + left) if left else ""),
                level=LEVEL_WARNING if left else LEVEL_INFO,
                duration=8 if left else 3)
        return True

    def write_footprint(self, name, extent, w, h, wkt, tile_id):
        """Where each cutout was taken from, as a polygon.

        The ones cut from a frame are already traced by the frame itself, but
        the ones cut freehand would exist only as four numbers in a text file,
        and a dataset whose pieces cannot be put back on the map is hard to
        check a year later."""
        path = os.path.join(self.folder, "cutouts.gpkg")
        try:
            driver = ogr.GetDriverByName("GPKG")
            ds = driver.Open(path, 1) if os.path.exists(long_path(path)) \
                else driver.CreateDataSource(path)
            if ds is None:
                return
            layer = ds.GetLayerByName("cutouts")
            if layer is None:
                srs = None
                if wkt:
                    srs = osr.SpatialReference()
                    try:
                        srs.ImportFromWkt(wkt)
                    except Exception:
                        srs = None
                layer = ds.CreateLayer("cutouts", srs, ogr.wkbPolygon,
                                       ["GEOMETRY_NAME=geom"])
                for field, kind in (("cutout", ogr.OFTString),
                                    ("tile_id", ogr.OFTString),
                                    ("width_px", ogr.OFTInteger),
                                    ("height_px", ogr.OFTInteger),
                                    ("created", ogr.OFTString)):
                    d = ogr.FieldDefn(field, kind)
                    if kind == ogr.OFTString:
                        d.SetWidth(80)
                    layer.CreateField(d)
            feature = ogr.Feature(layer.GetLayerDefn())
            ring = ogr.Geometry(ogr.wkbLinearRing)
            for x, y in ((extent.xMinimum(), extent.yMinimum()),
                         (extent.xMinimum(), extent.yMaximum()),
                         (extent.xMaximum(), extent.yMaximum()),
                         (extent.xMaximum(), extent.yMinimum()),
                         (extent.xMinimum(), extent.yMinimum())):
                ring.AddPoint_2D(x, y)
            polygon = ogr.Geometry(ogr.wkbPolygon)
            polygon.AddGeometry(ring)
            feature.SetGeometry(polygon)
            feature.SetField("cutout", name)
            feature.SetField("tile_id", tile_id or "")
            feature.SetField("width_px", int(w))
            feature.SetField("height_px", int(h))
            feature.SetField("created", now())
            layer.CreateFeature(feature)
            feature = None
            layer = None
            ds = None
        except Exception as err:
            log("cannot write the footprint: %s" % err, loud=True)

    # ------------------------------------------------- one size for them all
    def hold_shape(self, nominal, w, h, res=None):
        """How many pixels a side of so many metres is, decided once.

        Two frames of the same side can come out one pixel apart depending on
        where they fall between two pixel edges, and a loader that piles the
        pieces into a batch wants them identical. The first cutout of a given
        side writes the answer into the manifest and every later one of that
        side is made to match, padded with nodata if it now reaches past the
        edge of the raster.

        The answer is remembered against the pixel it was measured on, not
        against the side alone. Ten metres is two hundred pixels at five
        centimetres and fifty at twenty, and a campaign that cuts from two
        rasters of different resolution would otherwise take the count from one
        and impose it on the other, quietly cutting four times the ground.

        The answers live in shapes.json in the cutouts folder, because they
        describe that folder. Manifests written by RasterLabel 1.0 kept them
        instead; the first time a folder with no shapes.json is cut into
        while a campaign that kept them is open, they are taken from there,
        once."""
        key = "%.3f" % float(nominal)
        if res:
            # Six decimals are plenty for a pixel in metres and nothing for one
            # in degrees: 5.64e-07 was written "0.000001", and every pixel
            # between half a millionth and one and a half millionths of a
            # degree shared one answer. Below a thousandth, six significant
            # figures; above it the key is the one older folders have.
            res = abs(float(res))
            key += "@" + ("%.6f" % res if res >= 1e-3 else "%.6g" % res)
        book = self.read_shapes()
        kept = book.get(key)
        if kept and len(kept) == 2:
            fixed = (max(2, int(kept[0])), max(2, int(kept[1])))
            if fixed != (w, h):
                log("side %s m: %d by %d to match the first cutout of that side"
                    % (key, fixed[0], fixed[1]))
            return fixed
        book[key] = [int(w), int(h)]
        self.write_shapes(book)
        return int(w), int(h)

    @property
    def shapes_path(self):
        return os.path.join(self.folder, "shapes.json")

    def read_shapes(self):
        try:
            with open(long_path(self.shapes_path), encoding="utf-8") as f:
                book = json.load(f)
            return book if isinstance(book, dict) else {}
        except FileNotFoundError:
            pass
        except Exception as err:
            log("shapes.json could not be read, the sizes start afresh: %s"
                % err, loud=True)
            return {}
        if self.campaign is not None:
            kept = self.campaign.data.get("cutout_shape")
            if isinstance(kept, dict) and kept:
                # Written into the folder at once, so it holds them from now
                # on whether or not that campaign is ever open again.
                book = dict(kept)
                self.write_shapes(book)
                log("the sizes of the cutouts kept by the campaign were "
                    "written into %s" % self.shapes_path)
                return book
        return {}

    def write_shapes(self, book):
        """Through a temporary file, as every book here is written."""
        try:
            os.makedirs(long_path(self.folder), exist_ok=True)
            write_atomic(self.shapes_path, json.dumps(book, indent=2))
        except OSError as err:
            log("cannot write shapes.json: %s" % err, loud=True)

    def write_sampler(self):
        """A small note saying what one piece of this dataset is.

        Written for whoever has to sample the survey again later with the same
        geometry. TorchGeo asks for a size and a stride and wants to be told
        whether the numbers are pixels or ground units, and getting that pair
        wrong is the usual way a second pass stops lining up with the first.

        It describes the DATASET, read back from the manifest, not the cutout
        that happened to be written last. Rewriting the file each time with
        that one cutout's height and width would make the GridGeoSampler line
        it offers, on a folder of mixed sizes or of freehand rectangles, true
        of one piece and wrong about all the others."""
        shapes = self.shapes_on_disk()
        if not shapes:
            return
        (h, w), same = shapes[0][0], len(shapes) == 1
        res = shapes[0][1]
        crs = QgsCoordinateReferenceSystem()
        wkt = self.reference_wkt()
        if wkt:
            crs.createFromWkt(wkt)
        classes = self.class_order()
        note = {
            "written_by": "%s %s" % (NAME, VERSION),
            "crs": crs_to_text(named_crs(crs)),
            "res": list(res),
            "size_pixels": [int(h), int(w)],
            "size_crs": [round(h * res[1], 6), round(w * res[0], 6)],
            "stride_pixels": [int(h), int(w)],
            "units": "pixels",
            "every_piece_the_same": bool(same),
            "shapes_found": [{"height": int(a), "width": int(b), "n": int(n)}
                             for (a, b), _, n in shapes],
            "all_the_same_size": bool(self.same_size.isChecked()),
            "classes": [{"index": i, "code": int(c["code"]), "name": c["name"]}
                        for i, c in enumerate(classes)],
            "order": ("rows then columns, as the arrays are written: the first "
                      "number of every pair is the height"),
            "torchgeo": ("GridGeoSampler(dataset, size=(%d, %d), "
                         "stride=(%d, %d), units=Units.PIXELS)"
                         % (h, w, h, w)),
            "note": ("size and stride are given in pixels because the pieces "
                     "were cut on the pixel grid of the first layer, not on "
                     "round numbers of metres. The same numbers in ground "
                     "units are size_crs, valid only at this resolution. The "
                     "stride here is the size, which tiles the ground without "
                     "overlap; lower it for overlapping patches."
                     + ("" if same else
                        " WARNING: this folder holds pieces of more than one "
                        "shape, listed under shapes_found. The size above is "
                        "the commonest one and a single sampler will not fit "
                        "them all.")),
        }
        labels = self.labels_note(classes)
        if labels is not None:
            note["labels"] = labels
            if labels.get("warning"):
                note["note"] += " WARNING: " + labels["warning"]
        if self.campaign is not None:
            note["campaign"] = self.campaign.data.get("name", "")
        if not classes:
            note["classes_note"] = (
                "no layer cut as classes has a style that names its classes, "
                "so none are listed: the codes in the files are the values of "
                "that layer as they are.")
        try:
            os.makedirs(long_path(self.folder), exist_ok=True)
            write_atomic(os.path.join(self.folder, "sampler.json"),
                         json.dumps(note, indent=2))
        except OSError as err:
            log("cannot write sampler.json: %s" % err, loud=True)

    def detection_boxes(self, wkt=None):
        """The boxes to write, from the reading chosen, or None when there is
        nothing to write them from: no campaign, the option off, no box. They
        come in the system `wkt` of the cutout, when that differs from the
        campaign's; when they cannot be put there nothing is written, and it
        is said."""
        if not self.campaign_package() or not self.boxes.isChecked():
            return None
        choice = None
        if self.boxes_reading is not None and self.boxes_choices:
            choice = self.boxes_choices[
                max(0, self.boxes_reading.currentIndex())]
        readings = None if choice is None or choice["mode"] == "all" \
            else set(map(tuple, choice["readings"]))
        try:
            boxes = det_boxes(self.campaign_package(), readings, wkt)
        except Exception as err:
            log("the boxes could not be read for the detection files, and "
                "none is written for this cutout: %s" % err, loud=True)
            return None
        return boxes or None

    def detection_book(self):
        """boxes_coco.json as it is, or None."""
        try:
            with open(long_path(os.path.join(self.folder, DET_COCO_NAME)),
                      encoding="utf-8") as f:
                book = json.load(f)
            return book if isinstance(book, dict) else None
        except (OSError, ValueError):
            return None

    def write_detection(self, name, rows, assets, files, wkt=None):
        """The boxes of the campaign in the pixels of the images of a cutout:
        its images are added to boxes_coco.json, and each gets its YOLO file
        in labels/ (put in `files`, so that undo takes it away with the
        rest). In a campaign with frames an image the frames do not cover is
        over ground nobody read: it gets no file, an empty one would say
        there is nothing there, and it is listed in the book as unlabelled.
        A failure is said and does not undo the cutout."""
        boxes = self.detection_boxes(wkt)
        if boxes is None:
            return
        frames = None
        if self.tiled:
            try:
                frames = det_frames(self.campaign_package(), wkt)
            except Exception as err:
                log("the frames could not be read for the detection files, "
                    "and none is written for this cutout: %s" % err,
                    loud=True)
                return
        images = []
        for r in rows:
            if r.get("role") != "image":
                continue
            # the image itself: the asset the cut put down as "_image"
            main = assets.get("%s_image" % r["tag"])
            if not main or not landed(main[0]):
                continue
            images.append({
                "file": os.path.basename(main[0]), "cutout": name,
                "tag": r["tag"],
                "width": int(r["width_px"]), "height": int(r["height_px"]),
                "extent": tuple(float(v) for v in r.get("grid_box") or (
                    r[k] for k in ("xmin", "ymin", "xmax", "ymax")))})
        if not images:
            return
        plan = det_plan(images, boxes, self.campaign.data.get("classes"),
                        frames)
        try:
            book = det_merge(self.detection_book(), plan, name)
            folder = os.path.join(self.folder, DET_LABELS_FOLDER)
            if plan["yolo"]:
                os.makedirs(long_path(folder), exist_ok=True)
            for stem, text in plan["yolo"].items():
                path = os.path.join(folder, stem + ".txt")
                files.append(path)
                write_atomic(path, text)
            if plan["yolo"]:
                write_atomic(os.path.join(folder, DET_CLASSES_NAME),
                             plan["classes_txt"])
            write_atomic(os.path.join(self.folder, DET_COCO_NAME),
                         det_coco_text({"coco": book}))
        except OSError as err:
            log("cannot write the detection files of %s: %s" % (name, err),
                loud=True)
            return
        if plan["unlabelled"]:
            log("%d image%s of %s left without a label file: the ground is "
                "outside the frames of the campaign, nobody read it, and an "
                "empty file would say there is nothing there. Listed under "
                "unlabelled_images in %s; leave them out of training."
                % (len(plan["unlabelled"]),
                   "" if len(plan["unlabelled"]) == 1 else "s", name,
                   DET_COCO_NAME), loud=True)

    def forget_detection(self, name):
        """Take a cutout out of boxes_coco.json (its YOLO files go with the
        rest of its files). Never raises."""
        book = self.detection_book()
        if book is None:
            return
        try:
            write_atomic(os.path.join(self.folder, DET_COCO_NAME),
                         det_coco_text({"coco": det_remove(book, name)}))
        except OSError as err:
            log("boxes_coco.json could not be brought up to date: %s" % err,
                loud=True)

    def labels_note(self, classes):
        """The "labels" block of sampler.json: which value the layers cut as
        classes hold where nobody labelled, and how to tell a loss so.

        Read back from cutouts.csv, like the shapes, so it describes the
        folder and not the last cutout: one value when every piece of
        classes agrees, None and a warning when they do not. What the 0 of
        the files means is said from the layer being cut now. None when no
        layer has been cut as classes into this folder."""
        found, by_layer, pieces = set(), {}, 0
        try:
            with open(long_path(self.csv_path), newline="", encoding="utf-8",
                      errors="replace") as f:
                for row in csv.DictReader(f):
                    if (row.get("role") or "") != "classes":
                        continue
                    pieces += 1
                    held = (row.get("ignore_index") or "").strip()
                    try:
                        value = int(held) if held else None
                    except ValueError:
                        value = None
                    found.add(value)
                    if value is not None:
                        by_layer[csv_untext(row.get("tag") or "")] = value
        except (OSError, csv.Error) as err:
            log("cannot read the manifest for the sampler: %s" % err)
            return None
        if not pieces:
            return None
        value = next(iter(found)) if len(found) == 1 else None
        source = next((s for s in self.sources
                       if s.get("role") == "classes"), None)
        whence = ((source or {}).get("ignore") or (None, False, None))[2]
        own =((source or {}).get("readings") or {}).get(
            "RASTERLABEL_UNLABELLED", "")
        if whence == "file":
            mode = own if own in ("ignore", "frames") else "ignore"
            zero_is = "a class" if mode == "frames" else "not present"
        elif whence == "campaign mask":
            mode, zero_is = "ignore", "not present"
        elif whence == "map":
            mode, zero_is = "map", "a class"
        elif source is not None and source.get("readings"):
            mode, zero_is = "zero", "unlabelled"
        else:
            mode, zero_is = "map", "a class"
        named = [int(c["code"]) for c in classes or []]
        k = (max(named) + 1) if named else None
        out = {"ignore_index": value, "ignore_index_by_layer": by_layer,
               "unlabelled": mode, "zero_is": zero_is}
        if value is not None:
            v = value
            out.update({
                "meaning": ("%d marks pixels nobody labelled; leave them out "
                            "of the loss. It is not a class and not a "
                            "foreground: samgeo and Deepness write 255 for "
                            "the foreground of a binary mask." % v),
                "pytorch": "torch.nn.CrossEntropyLoss(ignore_index=%d)" % v,
                "torchgeo": ("SemanticSegmentationTask(..., num_classes=%s, "
                             "ignore_index=%d)" % (k if k else "K", v)),
                "mmsegmentation": ("decode_head=dict(..., ignore_index=%d), "
                                   "reduce_zero_label=False" % v),
                "targets": ("read the masks as integers and hand them to "
                            "the loss as torch.long; a mask of 16 signed "
                            "bits must be cast first" if v < 0 or v > 255
                            else "read the masks as integers and hand them "
                                 "to the loss as torch.long")})
            if k:
                out["num_classes"] = k
        elif len(found) > 1:
            out["warning"] = (
                "the pieces of classes in this folder do not hold one "
                "ignore value (%s): a single loss cannot leave them all out; "
                "cut them again with one value, or into separate folders"
                % ", ".join("none" if f is None else str(f)
                            for f in sorted(found, key=lambda f: (
                                f is not None, f or 0))))
            out["meaning"] = "the ignore value is not the same in every piece"
        else:
            out["meaning"] = (
                "no ignore value: the files hold 0 where nobody labelled"
                if zero_is == "unlabelled" else
                "no ignore value: the files hold the values of their map, "
                "0 included, and the padding past its edge is 0")
        return out

    def shapes_on_disk(self):
        """The shapes the cutouts in this folder really have, commonest first,
        read back from the manifest rather than remembered. Cutouts are
        counted, not files: a cutout of three layers has three rows in the
        manifest and is one piece."""
        counts, res = {}, {}
        try:
            with open(long_path(self.csv_path), newline="",
                      encoding="utf-8") as f:
                for at, row in enumerate(csv.DictReader(f)):
                    try:
                        key = (int(row["height_px"]), int(row["width_px"]))
                        span = (float(row["xmax"]) - float(row["xmin"]),
                                float(row["ymax"]) - float(row["ymin"]))
                    except (KeyError, TypeError, ValueError):
                        continue
                    # a row with no cutout name is a cutout of its own
                    counts.setdefault(key, set()).add(
                        row.get("cutout") or "row %d" % at)
                    if key not in res and key[0] and key[1]:
                        res[key] = (abs(span[0] / key[1]),
                                    abs(span[1] / key[0]))
        except (OSError, csv.Error) as err:
            log("cannot read the manifest for the sampler: %s" % err)
            return []
        return [(k, res.get(k, (0.0, 0.0)), len(n))
                for k, n in sorted(counts.items(),
                                   key=lambda kv: -len(kv[1]))]

    def reference_wkt(self):
        sources = [s for s in self.sources
                   if QgsProject.instance().mapLayer(s["id"]) is not None]
        if not sources:
            return ""
        layer = QgsProject.instance().mapLayer(sources[0]["id"])
        try:
            return layer.crs().toWkt() if layer.crs().isValid() else ""
        except Exception:
            return ""

    # ------------------------------------------------------- the catalogue
    def lonlat_footprint(self, extent, wkt):
        """The cutout outline in longitude and latitude, which is the only
        geometry a STAC item is allowed to carry, whatever the data is in
        (project.lonlat_footprint)."""
        try:
            return lonlat_footprint((extent.xMinimum(), extent.yMinimum(),
                                     extent.xMaximum(), extent.yMaximum()),
                                    wkt)
        except Exception as err:
            log("cannot put the cutout in degrees: %s" % err)
            return None, None

    def projection_of(self, gt, w, h, wkt, extent):
        return projection_of(gt, w, h, wkt,
                             (extent.xMinimum(), extent.yMinimum(),
                              extent.xMaximum(), extent.yMaximum()))

    def stac_folder(self):
        return os.path.join(self.folder, "stac")

    # The raster extension of STAC (constants.RASTER_EXT), for the data type
    # of every band: a map of classes is cut in bytes or in a wider type
    # depending on the map, and a reader of the catalogue should not have to
    # open the file to know. The classification extension
    # (CLASSIFICATION_EXT) only on an item whose classes carry an ignore
    # value, marked as nodata.

    @staticmethod
    def stac_type(kind):
        """The data_type of the raster extension for a GDAL type."""
        name = gdal.GetDataTypeName(kind) or ""
        return "uint8" if name == "Byte" else (name.lower() or "other")

    def stac_assets(self, book):
        """Asset paths are written relative to the item, so the folder can be
        moved or zipped whole and still be readable. An entry may carry a
        fifth element, fields of its own such as raster:bands."""
        out = {}
        for key, entry in sorted(book.items()):
            path, media, roles, title = entry[:4]
            out[key] = {"href": "../" + os.path.basename(path),
                        "type": media, "roles": list(roles), "title": title}
            if len(entry) > 4 and entry[4]:
                out[key].update(entry[4])
        return out

    def write_stac(self, name, extent, gt, w, h, wkt, tile_id, assets,
                   roles=None):
        """One document per cutout: what was cut, and out of which layers.

        There is no second one, a label item, describing the annotation burned
        onto the cutout. There is no such burn: the ground truth of a cutout
        is a layer somebody marked "classes", not the hand drawing of this
        campaign, and a label item is a claim about hand drawing. Such an item
        would also claim more than it holds. It would list every class of the
        campaign whether or not the tile contained one, invent a count of one
        for each kind of label, and announce an object detection task even
        when the box file it pointed at was empty. A catalogue that overstates
        is worse than none: somebody downstream believes it."""
        folder = self.stac_folder()
        # utcnow() is deprecated from Python 3.12, and says so on every
        # cutout catalogued: the same moment, asked of an aware clock
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        shape, bbox = self.lonlat_footprint(extent, wkt)
        if shape is None:
            log("no usable projection: the cutout is not catalogued")
            return []
        projection = self.projection_of(gt, w, h, wkt, extent)
        try:
            os.makedirs(long_path(folder), exist_ok=True)
        except OSError as err:
            log("cannot make the stac folder: %s" % err)
            return []

        # The roles of the files really written, handed in by the caller. The
        # roles asked for would make every item of a session that had left the
        # image out say "classes, image" over assets of classes only.
        if roles is None:
            roles = sorted({s.get("role") for s in self.sources
                            if s.get("role") in ("image", "classes")})
        # The date of an item is the date of what it shows, when a layer says
        # when it was taken. The moment of the cutting is the date of the
        # cutout, and is "created". With no date in any layer the item has
        # none: datetime is null, which STAC allows when the item has a
        # start and an end, and these are the moment of the cutting, said
        # to be so, because that is all there is.
        moments = sorted({src.get("moment") for src in self.sources
                          if src.get("moment")})
        if len(moments) == 1:
            when = {"datetime": moments[0]}
        elif moments:
            when = {"datetime": None, "start_datetime": moments[0],
                    "end_datetime": moments[-1]}
        else:
            when = {"datetime": None, "start_datetime": stamp,
                    "end_datetime": stamp,
                    "rasterlabel:datetime_is": "the moment of the cutting: "
                                               "no layer says when it was "
                                               "taken"}
        properties = dict(when, created=stamp, title="%s" % name)
        properties.update({"rasterlabel:tile_id": tile_id or None,
                           "rasterlabel:roles": roles,
                           "rasterlabel:version": VERSION})
        # Only when an annotation campaign is open: a cutout needs none, and
        # a field that names no campaign is a claim about nothing.
        if self.campaign is not None:
            properties["rasterlabel:campaign"] = self.campaign.data.get("name", "")
            properties["rasterlabel:campaign_id"] = self.campaign.data.get("id", "")
        # A layer of classes that is the mask of a campaign says which
        # readings it holds, and how they were put together: one reading,
        # all of them, or their consensus. Only for such a layer; a map of
        # classes made anywhere else makes no claim about readings.
        readings = {}
        for src in self.sources:
            if src.get("role") == "classes" and src.get("readings"):
                got = src["readings"]
                readings[src["tag"]] = {
                    "mode": got.get("RASTERLABEL_READING_MODE", ""),
                    "readings": [r for r in got.get(
                        "RASTERLABEL_READINGS", "").split("; ") if r],
                    "rule": got.get("RASTERLABEL_READING_RULE", "")}
        if readings:
            properties["rasterlabel:readings"] = readings
        # The value each layer of classes holds where nobody labelled, when
        # it holds one: the same number as its nodata and its classification
        # entry, said once for the item.
        ignored = {src["tag"]: int(src["ignore"][0]) for src in self.sources
                   if src.get("role") == "classes" and src.get("ignore")
                   and src["ignore"][0] is not None}
        if ignored:
            properties["rasterlabel:ignore_index"] = ignored
        listed = self.stac_assets(assets)
        extensions = [PROJ_EXT]
        if any("raster:bands" in a for a in listed.values()):
            extensions.append(RASTER_EXT)
        if any("classification:classes" in a for a in listed.values()):
            extensions.append(CLASSIFICATION_EXT)
        item = {
            "type": "Feature", "stac_version": STAC_VERSION,
            "geometry": shape, "bbox": bbox,
            "stac_extensions": extensions,
            "id": name,
            "properties": dict(properties, **projection),
            "assets": listed,
            "links": [{"rel": "root", "href": "catalog.json",
                       "type": "application/json"},
                      {"rel": "parent", "href": "catalog.json",
                       "type": "application/json"},
                      {"rel": "self", "href": "%s.json" % name,
                       "type": "application/json"}]}
        written = self.dump_json(os.path.join(folder, "%s.json" % name), item)
        self.refresh_catalog()
        return written

    def dump_json(self, path, payload):
        try:
            write_atomic(path, json.dumps(payload, indent=2))
            return [path]
        except OSError as err:
            log("cannot write %s: %s" % (os.path.basename(path), err))
            return []

    def refresh_catalog(self):
        """The root of the catalogue, rebuilt from what is actually on disk.

        Rebuilt rather than appended to, so that a cutout deleted by hand or
        undone leaves no link behind pointing at a file that is gone.

        Linking every item in the folder would link an item whose files have
        been deleted by hand while its json stayed behind, and a reader of
        the catalogue would be sent to files that are not there. Such an
        item is left out of catalog.json and said in the log, once; its json
        is kept, never deleted: it is the record of what that cutout was."""
        folder = self.stac_folder()
        try:
            names = sorted(f for f in os.listdir(long_path(folder))
                           if f.endswith(".json") and f != "catalog.json")
        except OSError:
            return
        items, left_out = [], []
        for f in names:
            missing = self.missing_assets(os.path.join(folder, f))
            if missing:
                left_out.append((f, missing))
            else:
                items.append(f)
        said = getattr(self, "_left_out", None)
        if said is None:
            said = self._left_out = set()
        fresh = [(f, m) for f, m in left_out if f not in said]
        if fresh:
            log("%d STAC item%s left out of catalog.json because %s files "
                "are no longer on disk (the items are kept in %s): %s"
                % (len(fresh), "" if len(fresh) == 1 else "s",
                   "its" if len(fresh) == 1 else "their", folder,
                   "; ".join("%s (%s)" % (f, ", ".join(m[:3]))
                             for f, m in fresh[:5])))
            said.update(f for f, _ in fresh)
        name = tidy(os.path.basename(os.path.normpath(self.folder)), "cutouts")
        catalog = {
            "type": "Catalog",
            "stac_version": STAC_VERSION,
            "id": name,
            "title": "%s: %s" % (NAME, name),
            "description": (
                "Cutouts, one image item each. Every piece is on the pixel "
                "grid of the first layer that was cut, so the pieces stack. "
                "sampler.json beside this folder says what one piece is."),
            "links": ([{"rel": "root", "href": "catalog.json",
                        "type": "application/json"},
                       {"rel": "self", "href": "catalog.json",
                        "type": "application/json"}]
                      + [{"rel": "item", "href": f, "type": "application/json"}
                         for f in items])}
        self.dump_json(os.path.join(folder, "catalog.json"), catalog)

    @staticmethod
    def missing_assets(item_path):
        """The files an item lists that are not on disk; ["the item itself"]
        when it cannot be read as one."""
        try:
            with open(long_path(item_path), encoding="utf-8") as f:
                item = json.load(f)
            assets = item.get("assets") or {}
        except Exception:
            return ["the item itself cannot be read"]
        here = os.path.dirname(item_path)
        out = []
        for asset in assets.values():
            href = (asset or {}).get("href") or ""
            if not href or "://" in href:
                continue
            where = os.path.normpath(os.path.join(here, href))
            if not os.path.exists(long_path(where)):
                out.append(os.path.basename(where))
        return out

    def class_order(self):
        """YOLO counts its classes from zero, in one fixed order: the codes of
        the first layer cut as classes, as its style names them, so it is the
        same for every cutout and stays the same when a class is added later
        with a higher code. Not the campaign legend, which numbers what is
        drawn by hand and not what that layer holds. The ignore
        value is not a class, whatever the style calls it, and gets no
        index."""
        for s in self.sources:
            if s.get("role") != "classes":
                continue
            named = style_classes(s.get("layer"), s.get("band") or 1) or []
            ign = (s.get("ignore") or (None,))[0]
            return sorted([c for c in named
                           if ign is None or int(c["code"]) != int(ign)],
                          key=lambda c: c["code"])
        return []

    def class_colours(self, layer, band, codes, ignore=None):
        """The colours the classes PNG is painted with: the style of the layer
        cut, and for a code it does not name a colour of its own, the same one
        for that code in every cutout. Not the campaign legend, which says
        nothing about this layer. The ignore value is no class and is given
        none."""
        named = {c["code"]: c for c in (style_classes(layer, band) or [])
                 if ignore is None or c["code"] != ignore}
        out = list(named.values())
        for v in sorted(set(np.unique(codes).tolist()) - set(named)):
            if v and (ignore is None or v != ignore):
                out.append({"code": int(v), "name": "",
                            "colour": thematic_colour(int(v))})
        return out

    # ----------------------------------------------------------- the books
    CSV_COLUMNS = ["cutout", "tag", "role", "layer", "bands", "resampled",
                   "stretch", "tile_id", "xmin", "ymin", "xmax", "ymax",
                   "width_px", "height_px", "format", "side_m", "when",
                   "ignore_index"]

    @property
    def csv_path(self):
        return os.path.join(self.folder, "cutouts.csv")

    def upgrade_csv(self):
        """A manifest written by RasterLabel 1.0, with fewer columns, given
        the columns of this one before a row is added to it: every old row
        kept, the new columns empty. Through a temporary file, as every book
        here is rewritten, so an interruption leaves the old one whole. A
        column is only ever added at the end, so a reader that counts
        columns finds the old ones where they were. Returns the columns the
        file has now: a header that is not one of ours is left alone, and
        the rows are written to it as it is."""
        path = long_path(self.csv_path)
        try:
            with open(path, newline="", encoding="utf-8",
                      errors="replace") as f:
                header = next(csv.reader(f), None)
        except (OSError, csv.Error):
            return self.CSV_COLUMNS
        if not header or header == self.CSV_COLUMNS:
            return self.CSV_COLUMNS
        if header != self.CSV_COLUMNS[:len(header)]:
            return header
        spare = path + ".tmp"
        try:
            with open(path, newline="", encoding="utf-8",
                      errors="replace") as f:
                old = list(csv.DictReader(f))
            with open(spare, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, self.CSV_COLUMNS, restval="",
                                        extrasaction="ignore")
                writer.writeheader()
                for r in old:
                    writer.writerow(r)
            os.replace(spare, path)
            log("cutouts.csv given the column%s %s of this build"
                % ("s" if len(self.CSV_COLUMNS) - len(header) > 1 else "",
                   ", ".join(self.CSV_COLUMNS[len(header):])))
            return self.CSV_COLUMNS
        except (OSError, csv.Error, ValueError) as err:
            log("cannot bring cutouts.csv up to this build: %s" % err,
                loud=True)
            try:
                os.remove(spare)
            except OSError:
                pass
            return header

    def append_csv(self, rows):
        fresh = not os.path.exists(long_path(self.csv_path))
        columns = self.CSV_COLUMNS if fresh else self.upgrade_csv()
        try:
            with open(long_path(self.csv_path), "a", newline="",
                      encoding="utf-8") as f:
                writer = csv.DictWriter(f, columns, restval="",
                                        extrasaction="ignore")
                if fresh:
                    writer.writeheader()
                for r in rows:
                    writer.writerow({k: csv_text(v) for k, v in r.items()})
        except (OSError, ValueError) as err:
            # The manifest is the only thing that knows which files belong to
            # which cutout, and undo reads it. Losing a row in silence means
            # losing the only handle on those files.
            log("cannot write the manifest: %s" % err, loud=True)

    def free_name(self):
        """A name no file in the folder is already using.

        A counter taken from the number of distinct names in cutouts.csv
        would be dangerous, because every writer here truncates what it finds.
        Lose that csv, or have one append fail (it only logs), and the counter
        would rewind onto names that already exist: a previous cutout, its
        mask, its pictures and its STAC item overwritten one after another
        without a word. Counting is fine as a starting guess. The folder has
        the last word, because the folder is where the damage would happen."""
        #
        # The number comes from the highest one in use anywhere in the
        # folder: the files, cutouts.csv, the footprints, and the stac folder.
        # Counting the names in cutouts.csv goes wrong as soon as somebody
        # deletes cutouts by hand: the count falls, the next name is one whose
        # STAC item is still in stac/, and that item is written over and
        # linked again from the catalogue with the files of another cutout.
        stem = tidy(self.prefix.text(), "cut")
        n = self.highest_in_use(stem) + 1
        first = n
        while True:
            name = "%s_%04d" % (stem, n)
            if not self.name_taken(name):
                break
            n += 1
        if n != first:
            log("cutout %s_%04d was taken: writing %s instead"
                % (stem, first, name))
        return name

    def name_taken(self, name):
        """Anything of this name in the folder or in its stac folder."""
        if glob_like(self.folder, name):
            return True
        stac = self.stac_folder()
        return os.path.isdir(long_path(stac)) and glob_like(stac, name)

    def highest_in_use(self, stem):
        """The highest number after stem_ that anything in the folder uses."""
        pattern = re.compile(r"^%s_(\d+)(?:[_.]|$)" % re.escape(stem))
        names = set(self.listed_names()) | set(self.footprint_names())
        for folder in (self.folder, self.stac_folder()):
            try:
                names.update(os.listdir(long_path(folder)))
            except OSError:
                pass
        top = 0
        for entry in names:
            m = pattern.match(entry or "")
            if m:
                top = max(top, int(m.group(1)))
        return top

    def manifest_rows(self):
        """The rows of cutouts.csv, or [] when there is none to read.

        errors="replace", and every exception caught, not only OSError. A
        cutouts.csv whose bytes are not UTF-8, which is what a spreadsheet on
        an Italian Windows writes if somebody opens and saves it, threw
        UnicodeDecodeError out of __init__ and the Cutouts module could never
        be opened again for that campaign. Counting is not worth that."""
        rows = self.read_manifest()
        return [] if rows is None else rows

    def read_manifest(self):
        """The rows of cutouts.csv, [] when the file does not exist, and None
        when it exists and cannot be read (held open by a spreadsheet, no
        permission, damaged). [] and None are different answers: the first
        says nothing is listed, the second says it is not known."""
        path = self.csv_path
        if not os.path.exists(long_path(path)):
            return []
        try:
            with open(long_path(path), newline="", encoding="utf-8",
                      errors="replace") as f:
                # names and tags as they were before csv_text quoted them
                return [csv_untext_row(r) for r in csv.DictReader(f)]
        except Exception as err:
            log("the cutouts manifest could not be read: %s" % err)
            return None

    def listed_names(self):
        return [r.get("cutout") or "" for r in self.manifest_rows()]

    def footprint_names(self):
        """The cutouts cutouts.gpkg has a footprint for."""
        path = os.path.join(self.folder, "cutouts.gpkg")
        if not os.path.exists(long_path(path)):
            return []
        ds = None
        try:
            ds = ogr.Open(path, 0)
            layer = ds.GetLayerByName("cutouts")
            return [f.GetField("cutout") or "" for f in layer]
        except Exception:
            return []
        finally:
            ds = None

    def count_existing(self):
        """How many cutouts the folder holds: those cutouts.csv lists that
        still have their files on disk.

        Files deleted by hand are part of life: somebody clears out a few bad
        pieces in Explorer and leaves the books behind. The count is not the
        names in cutouts.csv whatever is on disk: the ones whose files
        are gone are kept in self.gone, shown on the panel and said in the
        log, together with the footprints and the STAC items of cutouts no
        longer there. Nothing is changed or deleted on the strength of it: a
        row or an item is the record of what was cut."""
        self.gone = []
        try:
            rows = self.manifest_rows()
            if not rows:
                return 0
            try:
                present = set(os.listdir(long_path(self.folder)))
            except OSError:
                present = set()
            order, found = [], {}
            for row in rows:
                name = row.get("cutout") or ""
                if not name:
                    continue
                if name not in found:
                    order.append(name)
                    found[name] = []
                prefix = "%s_%s_%s" % (name, row.get("tag") or "",
                                       row.get("role") or "")
                found[name].append(any(f.startswith(prefix + ".")
                                       for f in present))
            self.gone = [n for n in order if not any(found[n])]
            partly = [n for n in order if any(found[n]) and not all(found[n])]
            self.report_books(present, partly)
            return len(order) - len(self.gone)
        except Exception as err:
            log("the cutouts manifest could not be counted: %s" % err)
            return 0

    def report_books(self, present, partly):
        """Say, in the log, what the books list and the disk no longer has."""
        def some(names):
            return ", ".join(names[:8]) + (", ..." if len(names) > 8 else "")
        if self.gone:
            log("%d cutouts listed in cutouts.csv have no file left on disk: "
                "%s. Their rows are kept; nothing was deleted."
                % (len(self.gone), some(self.gone)))
        if partly:
            log("%d cutouts have lost some of their files: %s"
                % (len(partly), some(partly)))
        loose = [n for n in self.footprint_names()
                 if n and not any(f.startswith(n + "_") for f in present)]
        if loose:
            log("%d footprints in cutouts.gpkg belong to cutouts no longer on "
                "disk: %s" % (len(loose), some(loose)))
        stac = self.stac_folder()
        try:
            items = sorted(f for f in os.listdir(long_path(stac))
                           if f.endswith(".json") and f != "catalog.json")
        except OSError:
            items = []
        orphans = [f for f in items
                   if self.missing_assets(os.path.join(stac, f))]
        if orphans:
            log("%d STAC items describe files no longer on disk, and are left "
                "out of catalog.json from the next cutout on: %s"
                % (len(orphans), some(orphans)))

    def rewrite_csv(self, keep):
        """The manifest rewritten whole, through a temporary file.

        Truncating the real one and writing into it means that an interruption
        anywhere in the middle leaves a manifest that is half of two different
        versions, and the manifest is the only thing that knows which files
        belong to which cutout."""
        path = long_path(self.csv_path)
        spare = path + ".tmp"
        try:
            with open(spare, "w", newline="", encoding="utf-8") as f:
                f.write("".join(keep))
            os.replace(spare, path)
            return True
        except OSError as err:
            log("cannot rewrite %s: %s" % (os.path.basename(path), err))
            try:
                os.remove(spare)
            except OSError:
                pass
            return False

    def undo(self):
        if not self.written:
            iface.messageBar().pushMessage(
                NAME, "nothing cut in this session", level=LEVEL_INFO, duration=2)
            return
        name, files = self.written.pop()
        # The manifest is read BEFORE anything is deleted. Read afterwards, a
        # manifest that could not be read would leave the rasters already gone
        # and the campaign still describing them: do the thing that can fail
        # while nothing has been destroyed yet.
        lines = []
        if os.path.exists(long_path(self.csv_path)):
            try:
                with open(long_path(self.csv_path), newline="",
                          encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception as err:
                log("the cutouts manifest could not be read, so nothing was "
                    "removed: %s" % err, loud=True)
                self.written.append((name, files))
                return
        refused = []
        for path in files:
            main = long_path(path)
            for p in (main, long_path(path + ".aux.xml")):
                try:
                    os.remove(p)
                except FileNotFoundError:
                    pass
                except OSError as err:
                    if p == main:
                        # On Windows a file another program still holds open
                        # cannot be removed. Saying "removed from disk" about it
                        # is the kind of lie that is found out months later.
                        refused.append((p, err))
        # An empty manifest would raise IndexError on lines[0], and AFTER the
        # rasters had already been deleted, so the campaign json and the
        # counter would be left describing files that were gone. A header is
        # kept only if there is one to keep.
        if lines:
            head = lines[:1] if lines[0].startswith("cutout,") else []
            body = lines[len(head):]
            # The name sits in the file as csv_text wrote it, or plainly, as
            # RasterLabel 1.0 wrote it: a folder cut with both has both.
            starts = (csv_text(name) + ",", name + ",")
            keep = head + [l for l in body if not l.startswith(starts)]
            self.rewrite_csv(keep)
        # The footprint and the sampler note go with it. Otherwise Undo would
        # leave the polygon of a cutout that no longer exists in cutouts.gpkg,
        # and sampler.json still counting it among the shapes of the folder.
        self.remove_footprint(name)
        self.forget_detection(name)
        if self.shapes_on_disk():
            self.write_sampler()
        else:
            try:
                os.remove(long_path(os.path.join(self.folder, "sampler.json")))
            except OSError:
                pass
        if os.path.isdir(long_path(self.stac_folder())):
            self.refresh_catalog()
        self.count = max(0, self.count - 1)
        self.show_state()
        if refused:
            log("%s was taken out of the manifest, but %d of its files could "
                "not be removed and are still on disk: %s"
                % (name, len(refused),
                   "; ".join("%s (%s)" % (os.path.basename(p), err)
                             for p, err in refused[:3])), loud=True)
        else:
            log("%s removed from disk" % name)

    def remove_footprint(self, name):
        """Take a cutout's polygon out of cutouts.gpkg. Never raises."""
        path = os.path.join(self.folder, "cutouts.gpkg")
        if not os.path.exists(long_path(path)):
            return 0
        ds = None
        try:
            ds = ogr.Open(path, 1)
            layer = ds.GetLayerByName("cutouts")
            layer.SetAttributeFilter("cutout = '%s'" % name.replace("'", "''"))
            fids = [f.GetFID() for f in layer]
            layer.SetAttributeFilter(None)
            for fid in fids:
                layer.DeleteFeature(fid)
            return len(fids)
        except Exception as err:
            log("the footprint of %s could not be taken out of cutouts.gpkg: "
                "%s" % (name, err), loud=True)
            return 0
        finally:
            ds = None

    def show_folder(self):
        # makedirs first: on a campaign where nothing has been cut yet there is
        # nothing to open, and a button that does nothing looks broken
        try:
            os.makedirs(self.folder or self.default_folder(), exist_ok=True)
        except OSError:
            pass
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder))
        except Exception:
            QMessageBox.information(self, NAME, self.folder)

    def save(self):
        """Nothing to save: every cutout is on disk when it is written, and
        there is no campaign to write to."""
        iface.messageBar().pushMessage(NAME, "%d cutouts in %s"
                                       % (self.count, self.folder),
                                       level=LEVEL_INFO, duration=3)

    def unsaved(self):
        return False
