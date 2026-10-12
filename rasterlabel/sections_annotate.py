"""rasterlabel.sections_annotate

Annotate: where the work happens.
"""
import re
from html import escape

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (QApplication, QButtonGroup, QComboBox,
                                 QDoubleSpinBox, QFileDialog, QGridLayout,
                                 QGroupBox, QHBoxLayout,
                                 QInputDialog, QLabel, QLineEdit, QMessageBox,
                                 QPushButton, QSizePolicy, QSpinBox,
                                 QToolButton, QVBoxLayout, QWidget)
from qgis.core import (Qgis, QgsCoordinateTransform, QgsFeature,
                       QgsFeatureRequest, QgsGeometry, QgsPointXY, QgsProject,
                       QgsRectangle, QgsRuleBasedRenderer, QgsVectorLayer)

from .constants import (AUTOSAVE, BLIND_TIP, BLIND_WORDS, BRUSH_RADIUS_PX,
                        CLOSED_SHARE,
                        EDITABLE_TABLES, FIELD_W,
                        HANDLE_PX, LABEL_W, LEVEL_INFO, LEVEL_CRITICAL, LEVEL_WARNING, LINE_PX,
                        MAX_CLASS_CODE, NAME, OVERLAP_SHARE, PALETTE,
                        DESIGN_FIELDS,
                        PANEL_W, POINT_PX, POINT_SIZES, TILE_SIDE_PX)
from .compat import iface, run_dialog
from .naming import beside_folder, ctrl_name, now, sql_text
from .project import canvas, crs_label
from .errors import alive, hook, log, own_hands, shielded, trouble
from .layout import Deck, FlowLayout, KeyRow
from .theme import (banner_height, bar, bold_metrics, button_pad,
                    chip_height, dress,
                    follows_width, heading, ink_on, key_height, key_least,
                    key_need,
                    padlock_icon,
                    palette_colours, person_icon, plain, primary, spread,
                    text_width, theme_icon)
from .widgets import ClassChip, NameBox, OneLine, PassBox, WrapTick
from .campaign import (next_pass, no_room_for_class, passes_of)
from .geometry import (Geometry, fit_spin, footprint_fits, joint_of,
                       spin_suffix)
from .layers import (find_mine, passes_found, pixel_in_layer_units,
                     restyle, style_by_class)
from .tools import (BrushTool, LineTool, PointTool, TileTool, hand_back_tool,
                    tool_in_hand)
from .journal import JOURNAL_TOOLTIP
from .ui_time import (TIME_SWITCH_TIP, time_centre, time_close, time_mark,
                      time_note, time_open, time_switch, time_take,
                      time_vertices, time_wanted)
from .design import (DESIGN_MANY, design_all_square,
                     design_append_log, design_crs_of, design_done_text,
                     design_feature_values, design_has_polygons,
                     design_import_count, design_import_id,
                     design_log_path, design_log_rows, design_manifest_entry,
                     design_next_tile, design_not_written, design_operator,
                     design_plan, design_say, design_settings_side,
                     design_source_name, design_summary, design_tile_line)
from .ui_import_frames import (IMPORT_TIP, ImportFrames, import_add_columns,
                               import_clash, import_existing, import_inside,
                               import_rasters, import_read_rows,
                               import_source_words, import_stratum_reader)


# How far apart two polygons may lie and still count as touching, as a share of
# one pixel. A border worked out twice, once for each side, can come back a few
# units in the last place apart; a thousandth of a pixel is far above that and
# far below anything a hand could draw.
MERGE_REACH_PX = 1e-3

# How much ground two frames may share and still count as only touching, in
# square pixels. Side by side they share an edge, which has no area; anything
# above a thousandth of a pixel is one frame lying over the other.
FRAME_OVERLAP_PX2 = 1e-3


def merge_reach(geometry, geom):
    """How close another polygon must come to this one to be its neighbour, in
    the units of the campaign system.

    A fixed 1e-9 buffer around the stroke would be a hair on a picture with
    its corner at (0, 0). On a real map it is not: in UTM the
    coordinates run to 500 000 east and 4 100 000 north, where two neighbouring
    doubles are already about 1e-10 and 5e-10 apart, and GEOS asked for a
    buffer of a few units in the last place hands back an EMPTY polygon.
    Nothing intersects an empty polygon, so on a projected campaign a stroke
    never merged with its own class: two strokes that overlap stayed two
    polygons on top of each other, and Check then reported them as overlapping
    work.

    So the reach is measured on the grid, a share of the smaller side of a
    pixel, which keeps its meaning at any coordinate and in any unit. It never
    drops below a millionth of a millionth of how far the stroke lies from the
    origin, so even a campaign with no usable pixel size gets a reach well
    clear of the rounding."""
    px, py = geometry.pixel_crs
    reach = MERGE_REACH_PX * min(px, py) if px > 0 and py > 0 else 0.0
    try:
        bb = geom.boundingBox()
        far = max(abs(bb.xMinimum()), abs(bb.xMaximum()),
                  abs(bb.yMinimum()), abs(bb.yMaximum()), 1.0)
    except Exception:
        far = 1.0
    return max(reach, far * 1e-12)


def within_reach(other, geom, reach):
    """True when two polygons overlap, share a border, or miss each other by no
    more than the reach.

    The exact test comes first and settles almost every case without building
    anything: polygons that overlap or share a border intersect. Only one that
    misses is looked at again, through a buffer of the stroke by the reach.
    That buffer is never the sub-nanometre one that collapsed on projected
    coordinates, and if GEOS hands back nothing all the same, a miss stays a
    miss rather than turning into an error."""
    if other is None or other.isEmpty():
        return False
    if other.intersects(geom):
        return True
    grown = geom.buffer(reach, 1)
    return (grown is not None and not grown.isEmpty()
            and other.intersects(grown))


# The cell after the last class, where one more can be made: a dashed outline
# and no fill, unlike any class chip.
PLUS_STYLE = ("QPushButton{border:1px dashed %(dim)s; border-radius:3px;"
              " background:transparent; color:%(text)s; font-weight:bold;}"
              "QPushButton:hover{border:1px solid %(accent)s;}"
              "QPushButton:focus{border:2px solid %(accent)s;}")
# A legend of this many classes or more takes its columns from the room, at
# least this wide each, and never more than CHIP_COLUMNS of them.
MANY_CLASSES = 12
CHIP_LEAST = 80
CHIP_COLUMNS = 4


def legend_columns(natural, count, room, gap=4):
    """The columns of a legend: the ones its longest name allows, at least
    two from four classes when each can still be 70 pixels wide, and from
    MANY_CLASSES as many as the room holds at CHIP_LEAST each. Annotate,
    Objects and both grids of Correct count theirs here."""
    columns = natural
    if count >= MANY_CLASSES:
        columns = max(columns, min(CHIP_COLUMNS,
                                   (room + gap) // (CHIP_LEAST + gap)))
    if columns == 1 and count >= 4 and (room - gap) // 2 >= 70:
        columns = 2
    return max(1, min(columns, count))


def bbox_of(geometry):
    """A frame's bounding box as (xmin, ymin, xmax, ymax), or None."""
    try:
        box = geometry.boundingBox()
        return (box.xMinimum(), box.yMinimum(), box.xMaximum(),
                box.yMaximum())
    except Exception:
        return None


def pass_words(numbers):
    """'Pass 1 is hidden and stays untouched', 'Passes 1 and 3 are hidden and
    stay untouched': the passes blind keeps out of sight."""
    names = [str(n) for n in numbers]
    one = len(names) == 1
    return "%s %s %s hidden and %s untouched" % (
        "Pass" if one else "Passes",
        names[0] if one else ", ".join(names[:-1]) + " and " + names[-1],
        "is" if one else "are", "stays" if one else "stay")


class AnnotationSection(QGroupBox):
    """Draws class areas on the active raster.

    Every new polygon wins over the ones already there: it is clipped to the
    tile and subtracted from everything underneath, so overlaps are impossible
    and, starting from a background fill, holes are impossible too.

    In a tiled campaign the edge of the tile is a ready-made contour: a stroke
    can start or end outside it and be clipped afterwards. In a free campaign
    there is no tile, so Fill Gap has nothing to act on and is not shown."""

    def __init__(self, panel):
        # No title on the frame: the Annotate button above is already pressed,
        # and saying it twice is the kind of noise that makes a panel tiring.
        super().__init__("")
        self.panel = panel
        self.campaign = panel.campaign
        reference = find_mine(self.campaign.data["id"], "tiles") \
            or find_mine(self.campaign.data["id"], "polygons")
        self.geometry = Geometry(self.campaign,
                                 reference.crs() if reference is not None else None)
        self.tiled = self.campaign.data["with_tiles"]
        log("drawing in %s, measuring in %s, canvas in %s"
            % (crs_label(self.geometry.crs),
               crs_label(self.geometry.metric) if self.geometry.metric
               is not None else "metres from the pixel size",
               crs_label(canvas().mapSettings().destinationCrs())))
        self.class_name = None
        self.brush = None
        self.tile_tool = None
        self.point_tool = None
        self.line_tool = None
        self.since_save = 0
        # the hand edit machinery, set up before anything can fire it
        self._settling = False          # we are the ones changing geometries
        self._to_settle = set()         # features a human moved, to tidy up
        self._shapes = {}               # how they looked before they moved
        self._watching = None           # the layer whose edits we listen to
        self._tool_before = tool_in_hand()   # the map tool to give back
        self._project_kept = None       # the project's settings, as they were
        self._buttons = []

        follows_width(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(7)
        self.deck = Deck()
        self.deck.after = self.reflow

        # ---- the class in hand, then the whole legend under it
        self.current_label = QLabel("")
        self.current_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = self.current_label.font()
        f.setPointSize(max(f.pointSize() + 1, 11))
        f.setBold(True)
        self.current_label.setFont(f)
        self.current_label.setFixedHeight(banner_height(self.current_label))

        # The chips live in a nested layout rather than inside a widget of
        # their own: a widget keeps the size it was given when the legend
        # changes, and the last row ends up drawn over whatever comes next.
        self.class_grid = QGridLayout()
        self.class_grid.setContentsMargins(0, 0, 0, 0)
        self.class_grid.setSpacing(4)

        # What the next click on the map does, in one line under the class
        # it will be given: the tool in hand was only an accent fill five
        # boxes further down. Plain words at the size of the rest, cut to the
        # width rather than folded onto a second line.
        self.tool_caption = OneLine()
        self.tool_caption.setObjectName("quiet")
        self.tool_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)

        legend = QVBoxLayout()
        legend.setSpacing(4)
        legend.addWidget(self.current_label)
        legend.addWidget(self.tool_caption)
        legend.addSpacing(2)
        legend.addLayout(self.class_grid)
        self.deck.add(legend, 3)

        # ---- the bar: what you hold, what you fill with, what you undo.
        # The groups are told apart by a gap, not by a frame.
        self.tools = QButtonGroup(self)
        self.tools.setExclusive(True)

        self.b_brush = self._tool(
            "Polygon",
            "Draw a polygon.\nClick by click or freehand, the outline closes on\n"
            "itself. What it covers becomes the class you are holding. With\n"
            "'paint under the others' on, as it starts, it only fills ground\n"
            "no other class holds yet; Shift, or the switch off, paints over\n"
            "them instead.")
        self.b_brush.clicked.connect(
            shielded(lambda: self.use_brush(False), "Polygon"))
        self.round_brush = self._tool(
            "Round",
            "Round brush.\nFor small rounded things, and for small repairs.\n"
            "Its radius is under Settings.")
        self.round_brush.clicked.connect(
            shielded(lambda: self.use_brush(True), "Round"))
        self.b_line = self._tool(
            "Line",
            "Draw a line.\nFor the long thin things a brush cannot hold: a\n"
            "fissure, a channel, a road, an edge. Click by click or\n"
            "freehand; right click or Enter finishes it.\n\n"
            "Its width is set in pixels under Settings: the ground it claims\n"
            "is that many pixels across, measured at a right angle to the\n"
            "line, whichever way it runs. The trace itself is kept as a\n"
            "line, so its length and its bearing stay measurable.")
        self.b_line.clicked.connect(shielded(self.use_line_tool, "Line"))
        self.b_points = self._tool(
            "Points",
            "Points.\nOne click drops a point of the class you are holding.\n"
            "Right click takes back the point under the cursor, "
            + ctrl_name() + " and\n"
            "click gives it the class you are holding. For sampling and\n"
            "counting, when the extent of the thing does not matter.")
        self.b_points.clicked.connect(shielded(self.use_point_tool, "Points"))
        held = [self.b_brush, self.round_brush, self.b_line, self.b_points]

        self.b_vertices = self._latch(
            "Vertices",
            "Move the corners of what is already drawn, with the vertex tool\n"
            "QGIS itself uses.\n\n"
            "Pressing it picks the right layer for the shape you are holding\n"
            "and hands the map to that tool; pressing it again gives the map\n"
            "back. Everything that tool can do it still does: snapping,\n"
            "adding a vertex on a segment, taking one out.\n\n"
            "A vertex moves on one polygon only. Afterwards the one you\n"
            "edited wins where you pushed into a neighbour, and the ground\n"
            "you pulled away from goes to the neighbour on that border.\n"
            "'A moved vertex wins', under Settings, switches that on and\n"
            "off.",
            self.vertex_mode_changed)

        if self.tiled:
            self.b_move = self._latch(
                "Move",
                "Turn dragging frames on.\n\n"
                "Pressing it takes the map: the shape in hand is put down,\n"
                "the pointer becomes a hand over a frame, and the frame can\n"
                "be dragged where you want it. Taking a shape again puts it\n"
                "back up. With it up a click only picks a frame up, and no\n"
                "amount of dragging moves it.\n\n"
                "Off to begin with, because a frame nudged by half a metre\n"
                "leaves every polygon inside it describing slightly different\n"
                "ground. A frame that holds work asks first, and offers to\n"
                "carry that work with it.\n\n"
                "Frames may touch but never overlap: one dropped on top of\n"
                "another stays where it was, and its outline turns red while\n"
                "it lies over one. Only a frame that is empty, or holds\n"
                "nothing but your own work of this pass, comes off the ground.",
                self.move_mode_changed)
            self.b_tiles = self._tool(
                "Tiles",
                "Place frames.\nClick on empty ground to make one, click inside\n"
                "one to pick it up. To drag one somewhere else, press Move\n"
                "first. One new frame and it hands the map back to the\n"
                "polygon. Esc goes back too.")
            self.b_tiles.clicked.connect(shielded(self.use_tile_tool, "Tiles"))
        for b in held + ([self.b_tiles] if self.tiled else []):
            self.tools.addButton(b)

        # Two boxes, because there are two jobs here. In the first, what leaves
        # a mark on the ground and what settings it reads. In the second, the
        # frame around the work and the work itself: placing, filling, mending,
        # undoing, saving. Nothing in the second box draws anything of its own.
        # Four boxes, one question each: what leaves a mark, what mends what
        # is already there, the frames, and what is held still. Vertices sat
        # among the shapes for a while and did not belong: a shape leaves a
        # new mark, and Vertices moves the corners of one that is already
        # drawn. The two locks keep their short words and get the heading
        # instead, which is where the word "lock" went when the buttons were
        # cut down to fit the columns.
        shapes = [held]
        for b in held + ([self.b_tiles, self.b_move] if self.tiled else []) \
                + [self.b_vertices]:
            b.toggled.connect(lambda *_: self.show_tool_caption())

        fix = [self.b_vertices,
               self._act(
                   "Repair",
                   "Repair the overlaps.\nAfter editing vertices by hand two "
                   "polygons can end up\nsharing ground. The smaller one keeps "
                   "it, because the\nsmall one is the deliberate detail.",
                   self.repair),
               self._act("Undo", "Undo the last stroke.", self.undo_stroke)]
        if self.tiled:
            # One button, not two. Fill replaced the whole frame and Gaps
            # filled what was left: two commands whose difference only
            # mattered on a frame that already had work in it, and the
            # dangerous one was the one with the shorter name. What is left
            # does the safe thing always, and on an empty frame the gap IS the
            # frame, so it fills the lot by itself.
            fix.insert(1, self._act(
                "Fill Gap",
                "Fill what is not painted yet with the current class.\n"
                "Nothing already drawn is touched.\n\n"
                "On a frame with nothing in it the gap is the whole frame,\n"
                "so this is also how you lay a background down before\n"
                "drawing the detail over it.",
                self.close_holes))

        self.lock_frames = self._latch(
            "Frames",
            "The lock on the frames.\n\n"
            "While this is down, the frames cannot be moved, made, or deleted.\n\n"
            "The frame is the ground a reading covers. Nudge one after the\n"
            "drawing is done and every polygon inside it still sits where it\n"
            "was, but now describes a slightly different patch of earth, and\n"
            "nothing about the file will say so.")
        self.lock_marks = self._latch(
            "Marks",
            "The lock on the drawing.\n\n"
            "While this is down, nothing can be drawn, filled, reclassified,\n"
            "rubbed out, nor can a vertex be moved with the QGIS vertex tool:\n"
            "polygons, lines and points are all held still.\n\n"
            "For reading back somebody else's work, or your own, without the\n"
            "risk of a stray click becoming an edit you never notice.")

        # The order is the order of the work, and the frame comes first: on a
        # tiled campaign nothing can be drawn until one is placed and picked
        # up, so the box that places it belongs above the box that draws.
        # Under it the two locks, which are about the frame as much as about
        # the marks, then what leaves a mark, then what mends it, then Save.
        #
        # The boxes of one or two buttons spread across the whole bar instead
        # of being dressed to the width of their own word: with two of them the
        # bar is split in half and the half never moves, which is what lets the
        # hand find Move, or Marks, or Save, without reading them.
        #
        # No frame round each group: the module has one already, and a frame
        # inside a frame was two borders round every row. A small heading and
        # a little air say where a group ends. The groups of four are four
        # equal keys in a row, or two rows of two where four do not fit:
        # never three and one, with the fourth alone under the others.
        two = QVBoxLayout()
        two.setSpacing(8)
        if self.tiled:
            # ---- the frame in hand, under the keys that make and move the
            # frames: the frame is one subject, so its list sits with them
            # and not apart, under Save. A row that cannot wrap, with the list
            # taking what the three keys leave, so nothing spills at any
            # width and Delete stays at the end, where the hand slows down.
            self.tiles = QComboBox()
            self.tiles.setMinimumWidth(48)
            self.tiles.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            self.tiles.setMinimumContentsLength(3)
            self.tiles.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Fixed)
            self.tiles.setFixedHeight(key_height(self.tiles))
            self.tiles.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.tiles.setToolTip("The frame in hand.")
            self.tiles.currentIndexChanged.connect(
                shielded(self.tile_changed, "Frame"))
            go = self._act("Go", "Bring the view onto this tile.",
                           self.go_to)
            note = self._act(
                "Note", "A word on this frame, shown next to its number on the\n"
                        "map: why it is here, what makes it hard.",
                self.edit_note)
            delete = self._act(
                "Delete",
                "Remove this tile and everything drawn inside it. It asks\n"
                "first and says how much.\n\n"
                "Only a frame that is empty, or holds nothing but your own\n"
                "work of this pass, can be deleted. One that holds another\n"
                "operator's work, or an earlier pass, stays where it is, and\n"
                "the message bar says whose work it holds.", self.delete_tile,
                danger=True)
            # Three keys of one width, as every row of keys is, and the
            # width of the longest word. Delete is red without its icon
            # here: three keys as wide as Delete with its icon, and the
            # list, are more than a panel of 260 pixels holds. Where even
            # that is too much, as in a Linux desktop's larger font, each
            # key comes down to its own word and the list to its least
            # (KeyRow); none of them is ever pushed past the edge.
            delete.setIcon(QIcon())
            keys = [go, note, delete]
            same = max(text_width(bold_metrics(k), k.text()) + button_pad(k)
                       for k in keys)
            row = KeyRow(key_need, 4, filler=True, least=key_least)
            row.add(self.tiles)
            for k in keys:
                k.setFixedWidth(same)
                row.add(k)
            frame = QVBoxLayout()
            frame.setContentsMargins(0, 0, 0, 0)
            frame.setSpacing(4)
            frame.addLayout(spread([self.b_tiles, self.b_move], gap=4))
            frame.addLayout(row)
            # the sampling design of the frame in hand, when it has one
            self.design_line = QLabel("")
            self.design_line.setObjectName("quiet")
            self.design_line.setWordWrap(True)
            self.design_line.setVisible(False)
            frame.addWidget(self.design_line)
            self.tiles.currentIndexChanged.connect(
                shielded(self.show_design_line, "Frame"))
            two.addWidget(heading("FRAME", plain(frame)))
        two.addWidget(heading("LOCK", plain(spread(
            [self.lock_frames, self.lock_marks], gap=4))))
        two.addWidget(heading("SHAPE", plain(bar(shapes, counts=(2, 4)))))
        two.addWidget(heading("EDIT", plain(bar(
            [fix], counts=(2, 4) if len(fix) == 4 else (3,)))))
        # No heading over this one: a box called SAVE holding a button called
        # Save says the same word twice and neither time usefully. A size
        # above the keys, with QGIS's icon: it is the one press that makes
        # the work last.
        two.addSpacing(4)
        two.addLayout(spread([primary(self._act(
            "Save", "Write frames, polygons, lines, points and boxes to the "
                    "package.", self.save))]))
        self.deck.add(two, 2)

        # ---- settings: set once, then folded away
        self.settings_box = QVBoxLayout()
        self.settings_box.setSpacing(5)
        self.fold = QToolButton()
        self.fold.setText(" Settings")
        self.fold.setCheckable(True)
        self.fold.setChecked(False)
        self.fold.setArrowType(Qt.ArrowType.RightArrow)
        self.fold.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.fold.setAutoRaise(True)
        self.fold.setObjectName("fold")
        self.fold.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.fold.toggled.connect(self.show_settings)
        self.settings_box.addWidget(self.fold, 0, Qt.AlignmentFlag.AlignLeft)

        # Both blocks of settings hold rows that wrap (_field) and tick boxes
        # that break their words onto a second line (WrapTick): each is as
        # tall as it is at its width, or a wrapped row is drawn over the one
        # under it, as the "+" of the operator was over "one operator at a
        # time" on a Linux desktop.
        self.settings = follows_width(QWidget())
        inner = QVBoxLayout(self.settings)
        inner.setContentsMargins(8, 0, 0, 2)
        inner.setSpacing(5)

        # The reading starts where the panel holds it, not from the creator
        # in pass 1: the module is built anew every time it is opened.
        held = self.held_reading() or {}
        # The passes of the operator, as the operators are a list: the box
        # offers the ones that exist and the + beside it makes the next one.
        # fill_operators fills it once the operator is known.
        self.pass_no = PassBox()
        self.pass_no.fill([int(held.get("pass") or 1)])
        self._pass_owner = None
        self.pass_no.setFixedWidth(FIELD_W)
        self.pass_no.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.pass_no.setToolTip(
            "Which pass this is. A pass is one reading of the ground: a\n"
            "second pass over the same frames, with blind on, reads it again\n"
            "from scratch, and Measure, Compare two readings says how far the\n"
            "two agree. Only the polygons of the current pass take part in\n"
            "the drawing. The box lists the passes this operator has; the +\n"
            "beside it makes the next one.")
        self.pass_no.valueChanged.connect(
            shielded(self.pass_changed, "Pass"))
        self.add_pass_button = QToolButton()
        self.add_pass_button.setText("+")
        self.add_pass_button.setAutoRaise(True)
        self.add_pass_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.add_pass_button.setToolTip(
            "Add the next pass for this operator, and read the ground again\n"
            "from scratch in it.\n\n"
            "The pass goes into the campaign manifest, so it is still there\n"
            "tomorrow and on whatever machine opens the same folder. A new\n"
            "operator starts at pass 1.")
        self.add_pass_button.clicked.connect(
            shielded(self.add_pass, "Add pass"))
        inner.addLayout(self._field("pass", self.pass_no,
                                    self.add_pass_button))

        self.blind = WrapTick(BLIND_WORDS)
        self.blind.setChecked(bool(held.get("blind", True)))
        self.blind.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.blind.setToolTip(BLIND_TIP)
        self.blind.stateChanged.connect(shielded(self.blind_changed, "Blind"))
        inner.addWidget(self.blind)

        # Who is drawing, and what they are allowed to see. The name is more
        # than a label on what is drawn: it decides the view as well, because
        # two people reading the same tile have to read it without each other
        # in front of them.
        self.operator = QComboBox()
        self.operator.setEditable(True)
        self.operator.setFixedWidth(FIELD_W)
        self.operator.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.operator.setToolTip(
            "Who is drawing now. It goes into every polygon, and it also decides\n"
            "what you see: each operator sees only their own work. Names are\n"
            "kept in capitals, so one person written two ways cannot become two\n"
            "operators. A tile another operator has already done opens empty,\n"
            "and that is the point. Two\n"
            "readings of the same tile are comparable only if neither was made\n"
            "with the other one in front of it.")
        self.add_operator_button = QToolButton()
        self.add_operator_button.setIcon(person_icon())
        self.add_operator_button.setText("+")
        self.add_operator_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.add_operator_button.setAutoRaise(True)
        self.add_operator_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.add_operator_button.setToolTip(
            "Add somebody to this campaign.\n\n"
            "The name goes into the campaign manifest, so it is still there\n"
            "tomorrow and on whatever machine opens the same folder. Typing a\n"
            "name straight into the box works too, but only this button writes\n"
            "it down.")
        self.add_operator_button.clicked.connect(
            shielded(self.add_operator, "Add operator"))
        inner.addLayout(self._field("operator", self.operator,
                                    self.add_operator_button))

        self.by_operator = WrapTick("one operator at a time")
        self.by_operator.setChecked(bool(held.get("by_operator", True)))
        self.by_operator.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.by_operator.setToolTip(
            "On, the polygons of the other operators are hidden and the brush\n"
            "ignores them: the tile is empty for whoever opens it.\n"
            "Off, everything comes back, which is what you want in order to read\n"
            "two readings side by side, and never while drawing one of them.")
        self.by_operator.stateChanged.connect(
            shielded(self.operator_changed, "Operator filter"))
        inner.addWidget(self.by_operator)

        if self.tiled:
            self.tile_side = QDoubleSpinBox()
            self.tile_side.setFixedWidth(FIELD_W)
            # in whole pixels of the campaign, from 8 to 4000 of them, or to
            # 5000 m where that is more: see fit_spin for the rasters that
            # a fixed half metre to 5000 m would leave without a usable box
            fit_spin(self.tile_side, self.geometry.pixel_m[0], 8, 4000, 5000.0,
                     TILE_SIDE_PX, spin_suffix(self.geometry))
            self.tile_side.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.tile_side.setToolTip("Side of the next tile you place.")
            self.tile_side.valueChanged.connect(self.show_side_in_pixels)
            self.side_px = QLabel("")
            self.side_px.setObjectName("quiet")
            self.row_tile = self._field_box("tile side", self.tile_side,
                                            self.side_px)
            inner.addWidget(self.row_tile)

        self.radius = QDoubleSpinBox()
        self.radius.setFixedWidth(FIELD_W)
        fit_spin(self.radius, self.geometry.pixel_m[0], 1, 500, 200.0,
                 BRUSH_RADIUS_PX, spin_suffix(self.geometry))
        self.radius.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.radius.setToolTip("Radius of the round brush.")
        self.radius.valueChanged.connect(self.brush_changed)
        self.radius_px = QLabel("")
        self.radius_px.setObjectName("quiet")
        self.row_radius = self._field_box("radius", self.radius, self.radius_px)
        inner.addWidget(self.row_radius)

        self.line_px = QSpinBox()
        self.line_px.setRange(1, 200)
        self.line_px.setValue(LINE_PX)
        self.line_px.setSuffix(" px")
        self.line_px.setFixedWidth(FIELD_W)
        self.line_px.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.line_px.setToolTip(
            "How wide a mark a line leaves, counted in pixels of the raster\n"
            "and measured at a right angle to the line, so it is the same\n"
            "width along a row, along a column and across a diagonal.\n\n"
            "One pixel is the thinnest there is: the trace claims an unbroken\n"
            "chain of pixels with no gaps. Across a diagonal that chain is\n"
            "up to 1.4 pixels wide, because pixels that touch only at a\n"
            "corner would break the line.\n\n"
            "The pixels are the ones whose centre falls inside, as in every\n"
            "mark. An odd width sits centred on the trace. An even one\n"
            "cannot, and leans to one side by half a pixel.\n\n"
            "The two ends of the line are squared off, like a brush: a line\n"
            "3 pixels wide reaches 1.5 pixels past each end. Turns inside the\n"
            "line are rounded, so a line drawn freehand is no wider than a\n"
            "straight one. Inside a frame it is cut at the border like\n"
            "everything else.")
        self.line_m = QLabel("")
        self.line_m.setObjectName("quiet")
        self.line_px.valueChanged.connect(self.show_line_in_metres)
        self.row_line = self._field_box("line width", self.line_px, self.line_m)
        inner.addWidget(self.row_line)

        self.point_px = QComboBox()
        for n in POINT_SIZES:
            self.point_px.addItem(
                "one pixel" if n == 1 else "%d x %d px" % (n, n), n)
        self.point_px.setCurrentIndex(
            max(0, list(POINT_SIZES).index(POINT_PX)
                if POINT_PX in POINT_SIZES else 0))
        # A campaign that already has points goes on with the footprint most
        # of them have, not with one pixel again at every opening: a second
        # session of 9 x 9 points began at 1 and mixed the two without a word.
        try:
            seen = self.sizes_in_use()
            used = max(seen, key=lambda k: (seen[k], -k)) if seen else None
        except Exception as err:
            log("cannot read the footprint of the points already there: %s"
                % err)
            used = None
        if used in POINT_SIZES:
            self.point_px.setCurrentIndex(list(POINT_SIZES).index(used))
        self.point_px.setFixedWidth(FIELD_W + 24)
        self.point_px.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.point_px.setToolTip(
            "How much ground one point speaks for: the pixel it lands on, or an\n"
            "odd square of pixels centred on it.\n\n"
            "Always odd, so the square has a middle pixel to sit on. An even\n"
            "one would have to lean to one side, and a sample that leans is a\n"
            "sample nobody can place twice the same way.\n\n"
            "The point kept in the file is the single spot you clicked. The\n"
            "footprint travels with it as a number, so the same clicks can be\n"
            "read at any size later.")
        self.point_m = QLabel("")
        self.point_m.setObjectName("quiet")
        self.point_px.currentIndexChanged.connect(
            shielded(self.point_size_changed, "Point size"))
        self.row_point = self._field_box("point size", self.point_px,
                                         self.point_m)
        inner.addWidget(self.row_point)

        self.autosave = QSpinBox()
        self.autosave.setRange(0, 200)
        self.autosave.setValue(AUTOSAVE)
        self.autosave.setSuffix(" strokes")
        self.autosave.setFixedWidth(FIELD_W)
        self.autosave.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.autosave.setToolTip(
            "Writes the work to the package by itself every so many strokes.\n"
            "Zero turns it off and nothing is written until you press Save.\n\n"
            "A save, by hand or by itself, closes the undo history: Undo\n"
            "cannot take back a stroke that has been written, so the stroke\n"
            "that triggers an automatic save is written with it. Turn it off,\n"
            "or raise it, to be able to take back more; the recovery file\n"
            "keeps the unsaved strokes safe in the meantime.")
        inner.addLayout(self._field("autosave", self.autosave))

        # The second half of the settings. Everything above is a number you
        # type once; everything below is a way of working you turn on and off
        # while you draw. Two blocks rather than one long column, so a panel
        # along the top puts them side by side instead of leaving the room
        # beside them empty.
        self.habits = follows_width(QWidget())
        inner = QVBoxLayout(self.habits)
        inner.setContentsMargins(8, 0, 0, 2)
        inner.setSpacing(5)

        self.uncertain = WrapTick("points are uncertain")
        self.uncertain.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.uncertain.setToolTip(
            "While this is on, every point dropped is marked uncertain, and\n"
            "the mark travels with it into the exported table. For the places\n"
            "where you would not bet on the class.")
        inner.addWidget(self.uncertain)

        # On from the start, and held on by a lock beside it.
        #
        # This is the setting that decides whether a stroke cuts what is
        # already drawn or yields to it, and yielding is what you want almost
        # always: you overshoot on purpose, across everything sharp you have
        # already placed, and only the free ground is taken. Off by accident,
        # the same overshoot eats an hour of detail and looks, on the map,
        # exactly like a stroke that went well.
        row_under = QWidget()
        self.paint_under = WrapTick(
            "paint under the others",
            room=lambda: row_under.width() - self.under_lock.width() - 4)
        self.paint_under.watch_row(row_under)
        self.paint_under.setChecked(True)
        self.paint_under.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.paint_under.setToolTip(
            "On, the new polygon yields to the polygons of other classes already\n"
            "there and fills only what is still free. Holding Shift inverts it\n"
            "for one stroke.")
        self.under_lock = QToolButton()
        self.under_lock.setCheckable(True)
        self.under_lock.setChecked(True)
        self.under_lock.setAutoRaise(True)
        self.under_lock.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.under_lock.setFixedSize(24, 22)
        self.under_lock.toggled.connect(shielded(self.under_lock_changed,
                                                 "Lock"))
        under_line = QHBoxLayout(row_under)
        under_line.setContentsMargins(0, 0, 0, 0)
        under_line.setSpacing(4)
        under_line.addWidget(self.paint_under)
        under_line.addWidget(self.under_lock)
        under_line.addStretch(1)
        self.row_paint_under = row_under
        self.under_lock_changed(True)
        inner.addWidget(row_under)

        self.line_over = WrapTick("lines cut what they cross")
        self.line_over.setChecked(True)
        self.line_over.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.line_over.setToolTip(
            "Only the line tool reads this, and it decides what happens where a\n"
            "line runs across a polygon of another class.\n\n"
            "On, the line wins: along its whole length the ground becomes the\n"
            "class you are holding, and the polygon is cut where the line\n"
            "passes. For a fissure or a road that really does cut across\n"
            "what it crosses.\n\n"
            "Off, the polygon wins: only the stretches of the line that fall on\n"
            "ground nobody has claimed are kept, and the line comes out in\n"
            "pieces, one on each side. For a trace you want to follow without\n"
            "disturbing what is already mapped.\n\n"
            "Either way nothing ends up overlapping, and the mask that is\n"
            "exported is the one you are looking at.")
        inner.addWidget(self.line_over)

        self.settle_edits_on = WrapTick("a moved vertex wins")
        self.settle_edits_on.setChecked(True)
        self.settle_edits_on.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.settle_edits_on.setToolTip(
            "Dragging a vertex with the QGIS vertex tool moves one polygon only,\n"
            "never the neighbour that happens to share that corner. The two then\n"
            "no longer meet: on one side they overlap, on the other a gap opens.\n\n"
            "On, dragging a vertex drags the border. Where you pushed into a\n"
            "neighbour it is trimmed, exactly as a brush stroke would trim it;\n"
            "where you pulled away, the ground you stopped claiming goes to the\n"
            "neighbour on the other side of that border, so the frame stays a\n"
            "closed partition whichever way you drag. Ground somebody has\n"
            "painted in the meantime is never given away, and a piece that\n"
            "borders nobody, a hole in the middle of a polygon, stays a hole.\n\n"
            "Off, nothing is tidied up and the overlap stays in the file.")
        inner.addWidget(self.settle_edits_on)

        self.keep_journal = WrapTick("keep a journal of working time")
        self.keep_journal.setChecked(time_wanted(self.campaign.data))
        self.keep_journal.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.keep_journal.setToolTip(TIME_SWITCH_TIP)
        self.keep_journal.toggled.connect(shielded(
            lambda on: time_switch(self.panel, on, self), "Journal"))
        inner.addWidget(self.keep_journal)

        if self.tiled:
            self.lock_view = WrapTick("keep the view on the tile")
            self.lock_view.setChecked(True)
            self.lock_view.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            self.lock_view.setToolTip(
                "Selecting or creating a tile brings the view onto it, so the\n"
                "canvas cannot drift off the image while you work.")
            inner.addWidget(self.lock_view)

            self.only_current = WrapTick("only the current tile")
            self.only_current.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            self.only_current.stateChanged.connect(
                shielded(self.apply_filter, "Frame filter"))
            inner.addWidget(self.only_current)

            inner.addWidget(self._act("Import frames", IMPORT_TIP,
                                      self.import_tiles))

        self.settings.setVisible(False)
        self.habits.setVisible(False)
        self.more_settings = [self.habits]
        self.settings_box.addWidget(self.settings)
        self.deck.add(self.settings_box, 3)
        self.deck.add(self.habits, 3)

        self.blind_note = QLabel("")
        self.blind_note.setWordWrap(True)
        self.blind_note.setVisible(False)

        # The one thing to do next, always in view. A panel full of buttons
        # tells you what it can do; it does not tell you what is worth doing
        # now, and on a tile that has to end up a closed partition the order is
        # most of the craft: the small sharp things first, the background last.
        self.step = QLabel("")
        self.step.setWordWrap(True)
        self.step.setObjectName("step")

        self.coverage = QLabel("")
        self.coverage.setWordWrap(True)
        self.coverage.setObjectName("quiet")

        # How long today has been, from the journal, by the rule Time uses
        self.time_line = QLabel("")
        self.time_line.setWordWrap(True)
        self.time_line.setObjectName("quiet")
        self.time_line.setToolTip(JOURNAL_TOOLTIP)
        self.time_line.setVisible(False)

        tail = QVBoxLayout()
        tail.setSpacing(5)
        tail.addWidget(self.blind_note)
        tail.addWidget(self.step)
        tail.addWidget(self.coverage)
        tail.addWidget(self.time_line)
        self.deck.add(tail, 2)

        self.deck.deal(force=True)
        outer.addWidget(self.deck)

        self.fill_operators()
        self.prepare_project()
        self.rebuild_class_buttons()
        self.refresh_tiles()
        if self.tiled:
            self.show_side_in_pixels()
        self.show_line_in_metres()
        n = self.point_size()
        px = self.geometry.pixel_m[0]
        self.point_m.setText("%.2f m across" % (n * px) if px else "")
        self.tool_settings()
        self.brush_changed()
        # The filter, before anything is looked at. Applied only when somebody
        # touched the pass, the operator or a frame, a module that was opened
        # and drawn in straight away would show every operator and every pass
        # while the brush and the coverage already saw one of each. A frame
        # that looked full would be empty to Fill Gap, and the amber strip
        # would say "polygons you cannot see" over polygons in plain sight.
        self.apply_filter()
        self.refresh_coverage()
        time_open(self, "annotate")

    # ----------------------------------------------------------- widgets
    def _tool(self, word, tip):
        """A tool you hold: it stays pressed until you pick another one.

        Reached by Tab and never taken by a click, as every key of the
        module is: a click leaves the arrow keys to the map, and the module
        can still be worked from the keyboard."""
        b = QPushButton()
        b.setCheckable(True)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setToolTip(tip)
        return dress(b, word)

    def _latch(self, word, tip, slot=None):
        """A button that stays down on its own, outside the group of tools.

        Not one of the held tools: a lock does not take the map, it only
        refuses. Putting it in the exclusive group would make picking a lock
        let go of the brush, which is the opposite of what a lock is for."""
        b = QPushButton()
        b.setCheckable(True)
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setToolTip(tip)
        b.toggled.connect(shielded(slot or self.locks_changed, word))
        return dress(b, word)

    def _act(self, word, tip, slot, danger=False):
        """Something that happens once, when you press it. A command that
        destroys work is marked, so the hand slows down before it lands.

        The slot goes in wrapped: whatever it raises comes back out as the
        window that says what was being done and what to try, with the word
        on the button as the name of the thing that did not finish."""
        b = QPushButton()
        b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        b.setToolTip(tip)
        b.clicked.connect(shielded(slot, word))
        if danger:
            b.setProperty("danger", True)
        return dress(b, word)

    def _field_box(self, word, box, suffix=None):
        """A setting inside a widget of its own, so that it can be shown and
        hidden as one thing. Hiding the label and leaving its box behind, or the
        other way round, is how a settings panel starts to look broken."""
        holder = QWidget()
        inner = QVBoxLayout(holder)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        inner.addLayout(self._field(word, box, suffix))
        return follows_width(holder)

    def _field(self, word, box, suffix=None):
        """One setting: its name in a column of fixed width, so every box in
        the section starts at the same place and the eye reads down them.

        It wraps rather than overflows. A row of fixed widths in a box narrower
        than their sum does not shrink, it spills: the name of the setting ends
        up printed across its own combo, which is how the point size read at a
        panel of two hundred and sixty. Given the same flow the buttons use,
        the tail of the row drops to the next line instead and everything stays
        legible, however narrow the dock is dragged."""
        row = FlowLayout(6, 6)
        label = QLabel(word)
        label.setFixedWidth(max(LABEL_W,
                                text_width(label.fontMetrics(), word) + 6))
        row.add(label)
        row.add(box)
        if suffix is not None:
            row.add(suffix)
        return row

    def show_settings(self, opened):
        self.fold.setArrowType(Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow)
        self.settings.setVisible(opened)
        # A module may keep its settings in more than one block, so that a wide
        # panel can put them side by side instead of in one long column.
        for extra in getattr(self, "more_settings", []):
            extra.setVisible(opened)

    def prepare_project(self):
        """Two project settings quietly ruin this kind of drawing.

        Avoid intersections makes QGIS clip a new geometry against the existing
        ones: the brush already decides who wins, and with both at work a stroke
        can come out empty and vanish without a word. Topological editing drags
        the vertices of the neighbours along. Both go off, for as long as this
        module is open, and are put back as they were when it closes.

        The attribute form is suppressed as well: the brush fills the fields
        itself, and a form appearing on every stroke would be unusable."""
        project = QgsProject.instance()
        self.take_project_settings()
        # Turning it off once is not enough. It is a project setting, it comes
        # back when the project is reopened, and one click on the toolbar puts
        # it back without a word. From then on every vertex dragged on a shared
        # border drags the neighbour of the other class along with it, and the
        # two classes stop being separate entities. So we listen and put it
        # back down each time.
        try:
            hook(self, project.topologicalEditingChanged,
                 shielded(self.keep_vertices_free, "Topological editing"))
        except Exception as err:
            log("cannot watch the topological editing setting: %s" % err)
        # A project read, or a new one begun, brings its own settings and its
        # own tables: the settings are taken again, and the tables listened to
        # again (see rewatch_layers).
        for name, slot in (("cleared", self.project_cleared),
                           ("readProject", self.project_read)):
            try:
                hook(self, getattr(project, name), shielded(slot, "Project"))
            except Exception as err:
                log("cannot follow the project (%s): %s" % (name, err))
        try:
            hook(self, project.layersAdded,
                 shielded(self.layers_came, "Layers"))
        except Exception as err:
            log("cannot follow the tables loaded into the project: %s" % err)
        try:
            hook(self, project.writeProject,
                 shielded(self.project_writing, "Project"))
        except Exception as err:
            log("cannot listen for the project being saved, so a project saved "
                "while Annotate is open keeps its editing settings off: %s"
                % err)
        self.watch_geometry_edits()
        self.suppress_forms()

    def suppress_forms(self):
        for role in ("polygons", "lines", "points"):
            lyr = self.layer(role)
            if lyr is None:
                continue
            try:
                cfg = lyr.editFormConfig()
                cfg.setSuppress(cfg.SuppressOn)
                lyr.setEditFormConfig(cfg)
            except Exception:
                pass

    @staticmethod
    def allow_intersections():
        """The avoid intersections mode that avoids nothing, under the name
        this QGIS has for it, or None when it has none."""
        for home in (Qgis, QgsProject):
            kinds = getattr(home, "AvoidIntersectionsMode", None)
            mode = getattr(kinds, "AllowIntersections", None)
            if mode is not None:
                return mode
        return None

    def take_project_settings(self):
        """Remember what the project says about topological editing and about
        avoiding intersections, and turn both off.

        Setting the list of layers to avoid to nothing was all that was done
        about the second, and it does nothing when the mode is the one that
        avoids the layer being edited: the mode itself is what has to be set.
        Neither was ever put back, so a person who had worked with topological
        editing on found it off in every project from then on."""
        project = QgsProject.instance()
        kept = {}
        for key, ask in (("topological", "topologicalEditing"),
                         ("mode", "avoidIntersectionsMode"),
                         ("layers", "avoidIntersectionsLayers")):
            try:
                kept[key] = getattr(project, ask)()
            except Exception as err:
                log("cannot read the project's %s setting: %s" % (key, err))
        self._project_kept = kept
        try:
            allow = self.allow_intersections()
            if allow is not None:
                project.setAvoidIntersectionsMode(allow)
            project.setAvoidIntersectionsLayers([])
            project.setTopologicalEditing(False)
            log("avoid intersections and topological editing turned off: "
                "the polygon tool decides overlaps by itself")
        except Exception as err:
            log("cannot change the project settings: %s" % err)

    def give_back_project_settings(self):
        """The project's settings as they were when this module opened. Once:
        the dock can be closed and the module after it."""
        kept, self._project_kept = self._project_kept, None
        if not kept:
            return
        project = QgsProject.instance()
        # the order of the three does not matter; each is tried by itself
        for key, put in (("mode", "setAvoidIntersectionsMode"),
                         ("layers", "setAvoidIntersectionsLayers"),
                         ("topological", "setTopologicalEditing")):
            if key not in kept:
                continue
            try:
                getattr(project, put)(kept[key])
            except Exception as err:
                log("cannot put the project's %s setting back: %s"
                    % (key, err))
        log("the project's topological editing and avoid intersections "
            "settings are back as they were")

    def project_writing(self, doc):
        """The project is being written while the two settings are off, and a
        file written like that keeps them off for good, long after Annotate
        is closed and the reason forgotten. QGIS writes the project's entries
        after this signal has been sent, so the person's own values are put
        into the entries now, and the file gets them. Topological editing is
        read from its entry, so it is on in the live project for as long as
        the write lasts: it goes down again as soon as the event loop turns
        (project_written), and keep_vertices_free is told to leave it alone
        until then."""
        kept = getattr(self, "_project_kept", None)
        if not kept or getattr(self, "_project_fresh", False) or self.let_go():
            return
        project = QgsProject.instance()
        self._project_writing = True
        QTimer.singleShot(0, self.project_written)
        try:
            if "mode" in kept:
                mode = kept["mode"]
                project.writeEntry("Digitizing", "/AvoidIntersectionsMode",
                                   int(getattr(mode, "value", mode)))
            if "layers" in kept:
                project.writeEntry("Digitizing", "/AvoidIntersectionsList",
                                   [layer.id() for layer in kept["layers"]])
            if "topological" in kept:
                project.writeEntry("Digitizing", "/TopologicalEditing",
                                   1 if kept["topological"] else 0)
        except Exception as err:
            log("cannot write the project's own editing settings into the "
                "project being saved: %s" % err)

    def project_written(self):
        """The write is over: topological editing off again, and the project
        not marked as changed by it."""
        self._project_writing = False
        if getattr(self, "_project_kept", None) is None or self.let_go():
            return              # given back in the meantime
        project = QgsProject.instance()
        try:
            if project.topologicalEditing():
                changed = project.isDirty()
                project.setTopologicalEditing(False)
                project.setDirty(changed)
        except Exception as err:
            log("cannot turn topological editing off again after the project "
                "was saved: %s" % err)

    def project_cleared(self, *args):
        """The project was emptied, to be read again or to begin a new one: the
        settings kept belong to the project that is gone, and are not given
        back to the next."""
        if getattr(self, "_project_kept", None) is not None:
            self._project_kept = {}

    def project_read(self, *args):
        """A project has been read. Its topological editing and its way of
        avoiding intersections are written in only after this signal, one by
        one, so they are taken once the reading is over; until then the
        topological editing it brings is not put down, because what the
        project said is what has to be given back."""
        if getattr(self, "_project_kept", None) is None:
            return
        self._project_fresh = True
        QTimer.singleShot(0, self.project_settled)

    def project_settled(self):
        self._project_fresh = False
        if getattr(self, "_project_kept", None) is None or self.let_go():
            return                      # the module let go in the meantime
        self.take_project_settings()
        self.rewatch_layers()

    def layers_came(self, *args):
        """Tables came into the project. Looked at once the event is over, and
        once for all that arrived together: a project read adds them all."""
        if getattr(self, "_rewatching", False) or self.let_go():
            return
        self._rewatching = True
        QTimer.singleShot(0, self.rewatch_due)

    def rewatch_due(self):
        self._rewatching = False
        if not self.let_go():
            self.rewatch_layers()

    def let_go(self):
        """Whether this module has given the map up, or is gone, so that a
        table arriving later is no business of its own."""
        return bool(getattr(self, "_released", False)) or not alive(self)

    def watched_tables(self):
        return (self._watching, getattr(self, "_watching_points", None),
                tuple(sorted(self.__dict__.get("_stacks_watched", {}).items(),
                             key=lambda kv: kv[0])))

    def rewatch_layers(self):
        """Listen again to a table that is no longer the one listened to.

        Vertex settling and the marks lock hang on signals of the tables, and
        a table that is read again is another object, with the same name and
        the same id: the project read again, a table loaded back. Checking the
        id alone would take the new one for the old and nobody would listen to
        it: a vertex dragged would not be settled and the lock on the marks
        would hold nothing."""
        before = self.watched_tables()
        self.watch_geometry_edits()
        if self.watched_tables() == before:
            return
        self.suppress_forms()
        self.rebase_lock()
        self.remember_shapes()
        log("the tables were loaded again: listening to the new ones")

    def fill_operators(self):
        """The names already in the file, plus the one the campaign was made
        with, and a census printed where it can be read.

        The census is not decoration. Because each operator sees only their
        own, a polygon whose operator field is empty is invisible to everybody:
        it does not leave the file, it leaves the screen, and a tile that was
        finished would open looking untouched. That is the one way this filter
        can cost somebody their work, so it is announced at the start rather
        than discovered later."""
        lyr = self.polygons
        counts, tiles, blank = {}, {}, []
        if lyr is not None:
            for f in lyr.getFeatures():
                raw = None
                try:
                    raw = f["operator"]
                except (KeyError, IndexError):
                    pass
                who = self.tidy_operator(raw)
                if not who:
                    blank.append(f["tile_id"])
                    who = self.OPERATOR_BLANK
                counts[who] = counts.get(who, 0) + 1
                tiles.setdefault(who, set()).add(f["tile_id"])

        mine = self.tidy_operator((self.held_reading() or {}).get("operator")) \
            or self.tidy_operator(self.campaign.data.get("operator")) \
            or "OPERATOR 1"
        self.refill_operator_box(mine, counts)
        self.refill_passes((self.held_reading() or {}).get("pass"))
        self.operator.currentIndexChanged.connect(
            shielded(self.operator_changed, "Operator"))
        # the box can be typed into: currentTextChanged would fire on every
        # keystroke while a new name is being written, and the view would be
        # rebuilt letter by letter. The choice and the end of the typing are
        # the two moments that mean anything.
        edit = self.operator.lineEdit()
        if edit is not None:
            edit.editingFinished.connect(self.operator_changed)
            # Lower case is turned as it is typed, not quietly when the box
            # loses focus. Seeing the letters come out in capitals is what
            # tells you the rule is there; being corrected afterwards, without
            # a word, only makes the box look haunted.
            edit.textEdited.connect(self.upper_as_typed)

        if counts:
            # The order the box shows, then anything counted that is not in
            # the box: UNNAMED above all, which is the row that matters most
            # and is not in the box.
            order = self.known_operators()
            if mine and mine not in order:
                order.append(mine)
            order += sorted(w for w in counts if w not in order)
            log("polygons by operator:")
            for who in order:
                if who in counts:
                    log("   %-16s %4d polygons over %d tile%s"
                        % (who, counts[who], len(tiles[who]),
                           "" if len(tiles[who]) == 1 else "s"))
        if blank:
            where = sorted({str(t) for t in blank if t is not None})
            log("WARNING: %d polygons carry no operator. While 'each operator "
                "sees only their own' is on, nobody sees them. Tiles: %s"
                % (len(blank), ", ".join(where[:20]) or "none recorded"))
            iface.messageBar().pushMessage(
                NAME, "%d polygon%s no operator: nobody sees %s right now"
                % (len(blank), " has" if len(blank) == 1 else "s have",
                   "it" if len(blank) == 1 else "them"),
                level=LEVEL_WARNING, duration=8)

    def known_operators(self):
        """Everyone this campaign knows about, from two sources that have to be
        put together.

        The manifest holds the people who were written down, which is the list
        the + button grows; the package holds the people who actually drew
        something, which may include a name typed into the box and never
        written down. Leaving either one out would make somebody disappear
        from the list while their polygons stayed in the file."""
        names = []
        for who in (self.campaign.data.get("operators") or []):
            who = self.tidy_operator(who)
            if who and who not in names:
                names.append(who)
        first = self.tidy_operator(self.campaign.data.get("operator"))
        if first and first not in names:
            names.append(first)
        lyr = self.polygons
        if lyr is not None:
            for f in lyr.getFeatures():
                who = self.operator_of(f)
                if who != self.OPERATOR_BLANK and who not in names:
                    names.append(who)
        return names or ["OPERATOR 1"]

    def refill_operator_box(self, keep, counts=None):
        """Rebuild the list without letting the rebuild change who is drawing.

        Clearing a combo emits currentIndexChanged on the way through, and that
        would refilter the view mid rebuild and, worse, briefly set the operator
        to whatever landed at index zero. Anything drawn in that instant would
        be written under the wrong name."""
        counts = counts or {}
        names = self.known_operators()
        keep = (keep or "").strip()
        if keep and keep not in names:
            names.append(keep)
        self.operator.blockSignals(True)
        self.operator.clear()
        for who in names:
            n = counts.get(who)
            self.operator.addItem(who)
            if n:
                self.operator.setItemData(
                    self.operator.count() - 1,
                    "%d polygon%s already drawn" % (n, "" if n == 1 else "s"),
                    Qt.ItemDataRole.ToolTipRole)
        if keep:
            self.operator.setCurrentText(keep)
        self.operator.blockSignals(False)

    def known_passes(self, operator=None, extra=()):
        """The passes that exist for an operator (campaign.passes_of): the
        manifest's list and the passes the tables already hold."""
        who = operator or self.operator_name()
        found = passes_found(self.campaign.data.get("id", "")).get(who, ())
        # the pass the panel holds for this operator is theirs even when
        # nothing is drawn in it and nobody wrote it down
        held = self.held_reading() or {}
        mine = [held.get("pass") or 1] if held.get("operator") == who else []
        return passes_of(self.campaign.data, who, found,
                         list(extra) + mine)

    def refill_passes(self, keep=None):
        """Offer the passes of the operator in the box, and stand on keep when
        the operator has it, else on pass 1.

        A new operator therefore starts at pass 1, and the number the last
        operator was on is not theirs. Rebuilt with the signals held, like
        the operator box, so that the rebuild does not refilter the view on
        the way."""
        who = self.operator_name()
        stay = [] if who != self._pass_owner else self.pass_no.values()
        if keep is None:
            keep = self.pass_no.value()
        self.pass_no.fill(self.known_passes(who, stay), int(keep))
        self._pass_owner = who

    def add_pass(self):
        """The + beside the pass: the next pass for this operator, written
        into the campaign and taken up."""
        who = self.operator_name()
        new = next_pass(self.campaign.data, who,
                        self.known_passes(who, self.pass_no.values()))
        if new is None:
            QMessageBox.information(
                self, "Add a pass",
                "%s has the most passes there can be." % who)
            return
        self.panel.register_pass(who, new)
        self.refill_passes(new)
        self.pass_changed()
        log("pass %d added for '%s'" % (new, who))

    def upper_as_typed(self, text):
        """Turn what is being typed into capitals, in place, without losing the
        cursor.

        setText moves the caret to the end, which on a box people type into
        would send every letter after the first to the wrong place. The
        position is taken before and put back after, and the signal is blocked
        so this does not call itself."""
        up = (text or "").upper()
        if up == text:
            return
        edit = self.operator.lineEdit()
        if edit is None:
            return
        at = edit.cursorPosition()
        edit.blockSignals(True)
        edit.setText(up)
        edit.setCursorPosition(at)
        edit.blockSignals(False)

    def add_operator(self):
        """Write somebody into the campaign, from the + beside the box.

        Typing a name straight into the box works and always did, but it lives
        only as long as the panel does. The second person on a campaign is not
        a one off: they will open the project tomorrow, on their own machine,
        and their name has to be waiting for them in the list rather than being
        retyped, because a name retyped slightly differently is a third
        operator as far as the filter is concerned."""
        name, ok = QInputDialog.getText(
            self, "Add an operator",
            "Who else works on this campaign?\n\n"
            "The name is written into every polygon they draw, and it decides\n"
            "what they see: each operator sees only their own work.\n"
            "Names are kept in capitals, so that one person written two ways\n"
            "cannot become two operators.")
        if not ok:
            return
        name = self.tidy_operator(name)
        if not name:
            return
        if name == self.OPERATOR_BLANK:
            QMessageBox.information(
                self, "Add an operator",
                "%s is the name this plugin gives to a polygon that has no "
                "operator written on it. Pick another one, or those polygons "
                "and this person would share a view." % self.OPERATOR_BLANK)
            return
        if name in self.known_operators():
            QMessageBox.information(
                self, "Add an operator",
                "%s is already on this campaign." % name)
            self.refill_operator_box(name)
            self.operator_changed()
            return
        operators = list(self.campaign.data.get("operators") or [])
        if not operators:
            first = (self.campaign.data.get("operator") or "").strip()
            if first:
                operators.append(first)
        operators.append(name)
        self.campaign.data["operators"] = operators
        try:
            self.campaign.save()
        except Exception as err:
            QMessageBox.warning(
                self, "Add an operator",
                "The name could not be written into the campaign:\n\n%s\n\n"
                "You can still use it now, but it will not be there next time."
                % err)
            log("cannot write the operator into the manifest: %s" % err)
        self.refill_operator_box(name)
        self.operator_changed()
        log("operator '%s' added to the campaign" % name)

    # ------------------------------------------- vertices, one polygon at a time
    def keep_vertices_free(self, *args):
        """Topological editing back off, and said out loud.

        With it on, QGIS moves every vertex that sits at the same place, on
        every feature, in one go. On a winner takes all partition that means a
        corner shared by dry mud and live vegetation belongs to both, and
        nudging the vegetation quietly redraws the mud. The two are different
        entities and have to move on their own."""
        if getattr(self, "_project_kept", None) is None \
                or getattr(self, "_project_fresh", False) \
                or getattr(self, "_project_writing", False):
            # let go of the project, just read, or being written (project_writing)
            return
        project = QgsProject.instance()
        try:
            if not project.topologicalEditing():
                return
            project.setTopologicalEditing(False)
        except Exception as err:
            log("cannot turn topological editing off: %s" % err)
            return
        iface.messageBar().pushMessage(
            NAME,
            "topological editing turned back off: with it on, moving a vertex "
            "moves the neighbouring class too", level=LEVEL_WARNING, duration=6)
        log("topological editing was switched on and has been turned off again")

    def watch_geometry_edits(self):
        """Listen for geometries changed by hand, with the QGIS vertex tool.

        The brush goes through paint() and settles its own overlaps. The vertex
        tool does not: it writes straight into the layer, and nothing downstream
        knows that a border has moved."""
        self.watch_stacks()
        self.watch_point_moves()
        lyr = self.polygons
        # The table itself, not its id: a table read again has the same id and
        # is another object, which nobody listens to yet. Held here, so that
        # asking the project for it hands back this very object.
        if lyr is None or self._watching is lyr:
            return
        try:
            hook(self, lyr.geometryChanged,
                 shielded(self.note_geometry_change, "Vertex edit"))
            self._watching = lyr
        except Exception as err:
            log("cannot watch the geometry edits: %s" % err)
            return
        # Whether an edit command is open. The vertex tool, like every QGIS
        # editing tool, wraps its change in one; undo and redo replay a command
        # without opening any. That is the only way to tell them apart from the
        # inside of geometryChanged, and it matters: an undo taken for a hand
        # drag was settled again, which pushed a new command and threw the redo
        # away, so Ctrl+Z went back and forth between two states for ever.
        self._command_open = None           # None: cannot tell, settle all
        try:
            hook(self, lyr.editCommandStarted,
                 shielded(lambda *a: self.command_is(True), "Vertex edit"))
            hook(self, lyr.editCommandEnded,
                 shielded(lambda *a: self.command_is(False), "Vertex edit"))
            hook(self, lyr.editCommandDestroyed,
                 shielded(lambda *a: self.command_is(False), "Vertex edit"))
            self._command_open = False
        except Exception as err:
            log("cannot tell an undo from an edit on this QGIS: %s" % err)

    def command_is(self, open_):
        self._command_open = bool(open_)

    LOCKED_ROLES = ("polygons", "lines", "points")

    def watch_stacks(self):
        """Follow the undo stacks of the tables the marks lock holds.

        Every move of a stack, wherever it comes from, is where the lock has
        to look: QGIS's own Ctrl+Z on a command that only added a polygon, or
        only changed a class, moves no geometry and so never reached the
        geometry signal. And a commit or a rollback empties the stack, which
        is where the lock has to start counting from again."""
        seen = self.__dict__.setdefault("_stacks_watched", {})
        for role in self.LOCKED_ROLES:
            lyr = self.layer(role)
            if lyr is None or seen.get(role) is lyr:
                continue
            try:
                hook(self, lyr.undoStack().indexChanged,
                     shielded(lambda *a, r=role: self.stack_moved(r),
                              "Marks lock"))
            except Exception as err:
                log("cannot follow the undo of %s: %s" % (role, err))
                continue
            for name in ("afterCommitChanges", "afterRollBack"):
                signal = getattr(lyr, name, None)
                if signal is None:
                    continue
                try:
                    hook(self, signal,
                         shielded(lambda *a, r=role: self.rebase_lock(r),
                                  "Marks lock"))
                except Exception as err:
                    log("cannot follow the saves of %s: %s" % (role, err))
            seen[role] = lyr

    def stack_moved(self, role):
        """A stack moved. With the marks locked, it is walked back."""
        if self._settling or not self.marks_locked(say=False):
            return
        if not getattr(self, "_holding", False):
            self._holding = True
            QTimer.singleShot(0, self.hold_marks)

    def rebase_lock(self, role=None):
        """A commit or a rollback started a new stack: the lock holds at its
        bottom, not at an index that is gone."""
        floors = self.__dict__.setdefault("_lock_floor", {})
        if not isinstance(floors, dict):
            floors = self._lock_floor = {}
        if not self.marks_locked(say=False):
            floors.clear()
            return
        for r in ([role] if role else self.LOCKED_ROLES):
            lyr = self.layer(r)
            if lyr is None:
                floors.pop(r, None)
                continue
            try:
                floors[r] = lyr.undoStack().index()
            except Exception:
                floors.pop(r, None)

    def note_geometry_change(self, fid, geom):
        """Remember the feature and come back once the edit has landed.

        Touching other features from inside the signal, while QGIS is still
        inside its own edit command, is a good way to corrupt the undo stack.
        A zero timer puts the work just after it, on the same event loop."""
        if self._settling:
            return
        if getattr(self, "_command_open", None) is False:
            # No command is open, so this is an undo or a redo replaying one,
            # or a script writing without one. Either way not a hand drag: the
            # tidying that followed the drag is its own command and comes back
            # or goes away with it.
            if self.marks_locked(say=False):
                # Except that with the marks locked nothing may move, and
                # QGIS's own Ctrl+Z and Ctrl+Shift+Z know nothing of the lock:
                # a drag put back by the lock came straight back with a redo.
                if not getattr(self, "_holding", False):
                    self._holding = True
                    QTimer.singleShot(0, self.hold_marks)
                return
            # The shapes are brought up to date so the next real drag is
            # measured from what is on screen; once per replay, not once per
            # geometry it touched, because each time reads the whole layer.
            if not getattr(self, "_remember_pending", False):
                self._remember_pending = True
                QTimer.singleShot(0, self.remember_after_replay)
            return
        self._to_settle.add(fid)
        QTimer.singleShot(0, self.settle_edits)

    def remember_after_replay(self):
        self._remember_pending = False
        self.remember_shapes()

    def hold_marks(self):
        """Put the polygons back where they stood when the marks were locked.

        The lock is a place on the undo stack: the index the polygons layer
        had at the moment it was shut. Whatever moves the stack away from it
        while it is shut, a drag, an undo, a redo, is walked back to it."""
        self._holding = False
        if not self.marks_locked(say=False):
            return
        floors = getattr(self, "_lock_floor", None)
        if not isinstance(floors, dict):
            floors = self._lock_floor = {}
        moved = False
        self._settling = True
        try:
            for role in self.LOCKED_ROLES:
                lyr = self.layer(role)
                if lyr is None:
                    continue
                stack = lyr.undoStack()
                if stack is None:
                    continue
                floor = floors.get(role)
                if floor is None:
                    # nothing was recorded for this table: hold it from here
                    floors[role] = stack.index()
                    continue
                touched = False
                while stack.index() > floor and stack.canUndo():
                    stack.undo()
                    touched = True
                while stack.index() < floor and stack.canRedo():
                    stack.redo()
                    touched = True
                if touched:
                    moved = True
                    lyr.triggerRepaint()
        except Exception as err:
            log("could not hold the marks still: %s" % err)
        finally:
            self._settling = False
        if moved:
            iface.messageBar().pushMessage(
                NAME, "the marks are locked: what moved was put back",
                level=LEVEL_WARNING, duration=4)
            log("marks moved while they were locked: put back")
        self.remember_shapes()
        self.refresh_coverage()

    def remember_shapes(self):
        """How the polygons of this frame look right now.

        A vertex edit arrives as "this feature has a new geometry" and nothing
        else: QGIS does not say what the old one was. Without it the program
        can see that a border moved but not which way, and the two directions
        need opposite answers. So the shapes are kept, and kept fresh: before
        the vertex tool is handed the map, after every stroke, and after every
        edit has been settled.

        Every polygon of the layer, not only the frame in the list. Every
        frame is on screen unless "only the current tile" is ticked, the
        vertex tool can grab any of them, and a drag in a frame whose shapes
        were not kept had nothing to be compared with. The copies are cheap:
        a QgsGeometry copy shares its data until one of the two changes, and
        the brush already walks the whole table at every stroke."""
        lyr = self.polygons
        if lyr is None:
            self._shapes = {}
            return
        try:
            self._shapes = {f.id(): QgsGeometry(f.geometry())
                            for f in lyr.getFeatures()
                            if f.geometry() is not None
                            and not f.geometry().isEmpty()}
        except Exception as err:
            self._shapes = {}
            log("cannot remember the shapes before an edit: %s" % err)

    def give_back(self, fid, now, scope, frame=None):
        """Ground a border was pulled off goes to the polygon on the other side.

        Dragging a vertex is dragging the border between two things, and a
        border has two sides. Pushed into the neighbour it is already handled:
        the edited polygon wins and the neighbour is trimmed. Pulled back, a
        hole would be defensible on paper, ground nobody claims, and wrong at
        the hand: half the drags would grow a class and the other half punch a
        hole, the frame would fall off a hundred per cent for no visible
        reason, and which of the two you got would depend on a direction you
        cannot see while you are dragging.

        So the freed ground goes to the polygon that shares the longest stretch
        of border with it, and the partition stays closed whichever way the
        hand goes. Three things are never given away: ground somebody else has
        painted in the meantime, ground outside the frame, and a piece that
        touches no other polygon at all, which is a hole in the middle of
        something and is meant to be one."""
        before = self._shapes.get(fid)
        if before is None or before.isEmpty():
            return 0
        lyr = self.polygons
        freed = self.cut_away(before, now)
        if freed is None or freed.isEmpty():
            return 0
        if self.tiled:
            # the frame the polygon belongs to, which is not always the one
            # selected in the list; and when that frame is gone, nothing.
            # Falling back on the frame in the list would make the same drag
            # give ground away or not depending on what was selected.
            tile = frame
            if tile is None:
                return 0
            freed = freed.intersection(tile)
            if freed is None or freed.isEmpty():
                return 0
        # Read every neighbour back from the layer: by now some of them have
        # been trimmed by the same edit, and a stale copy would hand away
        # ground that has just changed owner.
        neighbours = []
        for other in scope:
            if other.id() == fid:
                continue
            fresh = lyr.getFeature(other.id())
            if fresh is None or not fresh.isValid():
                continue
            og = fresh.geometry()
            if og is not None and not og.isEmpty():
                neighbours.append((other.id(), og))
        if not neighbours:
            return 0
        taken = QgsGeometry.unaryUnion([og for _, og in neighbours])
        if taken is not None and not taken.isEmpty():
            freed = self.cut_away(freed, taken)
            if freed is None or freed.isEmpty():
                return 0
        given = 0
        for part in self.geometry.leftovers(freed):
            best, longest = None, 0.0
            for other_id, og in neighbours:
                along = self.geometry.shared_border(og, part)
                if along is None:
                    continue
                shared = self.geometry.length(along)
                if shared > longest:
                    best, longest = other_id, shared
            if best is None:
                continue                # nobody borders it: an honest hole
            heir = lyr.getFeature(best)
            if heir is None or not heir.isValid():
                continue
            grown = QgsGeometry.unaryUnion([heir.geometry(), part])
            pieces = self.geometry.leftovers(grown) \
                if grown is not None else []
            if not pieces:
                continue
            lyr.changeGeometry(best, pieces[0])
            for extra in pieces[1:]:
                lyr.addFeature(self.piece_of(extra, heir))
            given += 1
        return given

    def settle_edits(self):
        """Make the hand edited polygon win, exactly as a stroke would, and
        give away what it stops claiming.

        A vertex moves on one polygon only. The neighbour that shared it stays
        where it was, so along that border the two now either overlap, where the
        vertex was pushed in, or leave a gap, where it was pulled away.

        An overlap is a lie: the same ground would be counted under two classes,
        and which one won would depend on the order a reader happened to loop
        in. So the polygon that was edited wins and the neighbours are trimmed,
        which is the rule the brush has always followed.

        A gap is not left alone as ground nobody claims. give_back() hands it
        to the neighbour, so that dragging a vertex is dragging a border: one
        side grows, the other gives way, and the frame stays a closed
        partition whichever direction the hand goes."""
        lyr = self.polygons
        if lyr is None or self._settling or not self._to_settle:
            return
        fids, self._to_settle = self._to_settle, set()
        if self.marks_locked(say=False):
            # The lock says nothing can be changed, but it is only enforced
            # in this program's own tools. QGIS's vertex tool knows nothing
            # about it: the vertex moves anyway, and if the repair that keeps
            # the partition honest were the only thing the lock stopped, that
            # would be precisely backwards. So the move is put back: back to
            # where the stack stood when the lock was shut, which is exactly
            # the drag and never a stroke made before the lock.
            self.hold_marks()
            return
        if not self.settle_edits_on.isChecked():
            self.refresh_coverage()
            return
        self._settling = True
        trimmed, split, given, untangled, merged = 0, 0, 0, 0, 0
        elsewhere = set()
        opened = False
        try:
            if not lyr.isEditable():
                lyr.startEditing()
            # One command for the whole tidying, so that Ctrl+Z takes it back
            # in one step and then the drag in the next, instead of one undo
            # per neighbour touched.
            lyr.beginEditCommand("settle vertex move")
            opened = True
            rows = [f for f in lyr.getFeatures()
                    if f.geometry() is not None and not f.geometry().isEmpty()]
            for fid in fids:
                f = lyr.getFeature(fid)
                if f is None or not f.isValid():
                    continue
                # Settled among the polygons of ITS reading: its frame, its
                # pass, and its operator when one operator is shown at a time.
                # Not the reading in hand: a vertex dragged in a frame other
                # than the one in the list, which is on screen and under the
                # vertex tool all the same, would be "left alone" and the
                # overlap it made would stay in the file for Check to find.
                # Other readings are never touched, because two readings that
                # exist to be compared must not depend on each other.
                reading = self.reading_of(f)
                scope = [r for r in rows if self.reading_of(r) == reading]
                if self.tiled and f["tile_id"] != self.current_tile_id():
                    elsewhere.add(str(f["tile_id"]))
                frame = (self.frame_geometry(f["tile_id"]) if self.tiled
                         else None)
                g = f.geometry()
                if g is None or g.isEmpty():
                    continue
                # The whole of what the edited outline encloses, read before it
                # is untangled: a bow tie becomes two polygons, and both lobes
                # have to trim their neighbours, not only the one that keeps
                # this feature's id.
                g = g.makeValid()
                # Then the outline itself. A vertex dragged across its own edge
                # leaves a ring that crosses itself, and repairing it only in
                # this variable would leave the bow tie in the layer for every
                # later cut to fail against.
                if self.untangle(lyr, fid):
                    untangled += 1
                for other in scope:
                    if other.id() == fid:
                        continue
                    # Read the neighbour back from the layer rather than
                    # from the snapshot taken before the loop: with several
                    # vertices moved at once, a neighbour trimmed for the first
                    # fid would otherwise be re-cut from its old geometry and
                    # changeGeometry would write the removed ground back.
                    fresh = lyr.getFeature(other.id())
                    og = fresh.geometry() if (fresh is not None
                                              and fresh.isValid()) else None
                    if og is None or og.isEmpty() or not og.intersects(g):
                        continue
                    shared = og.intersection(g)
                    # Two polygons that merely meet along a border intersect in
                    # a line, which has no area: that is the normal state of a
                    # partition and there is nothing to settle.
                    #
                    # The test is the area, never the type. "Is the shared
                    # ground a polygon" is almost always no in a closed
                    # partition: the edited polygon shared its whole border
                    # with the neighbour before the drag, so what GEOS hands
                    # back afterwards is a collection, the wedge the vertex
                    # pushed in plus the stretches of border the two still
                    # share. A collection is not of type polygon, so the trim
                    # would be skipped in the very case it exists for, a vertex
                    # pushed into a neighbour, and the overlap would stay for
                    # Check to find.
                    if (shared is None or shared.isNull() or shared.isEmpty()
                            or shared.area() <= 0):
                        continue
                    cut = self.cut_away(og, g, other)
                    if cut is None:
                        continue
                    rest = self.geometry.leftovers(cut)
                    if not rest:
                        lyr.deleteFeature(other.id())
                        trimmed += 1
                        continue
                    lyr.changeGeometry(other.id(), rest[0])
                    for extra in rest[1:]:
                        lyr.addFeature(self.piece_of(extra, other))
                        split += 1
                    trimmed += 1
                # And the other side of the same drag: what this polygon has
                # stopped claiming goes to whoever borders it. After the
                # trimming, so that the neighbours are read as they now are.
                given += self.give_back(fid, g, scope, frame)
            # Last, once every border has settled: what the drag brought
            # against a polygon of its own class and reading becomes one with
            # it, in this same command. The ground it left is part of the
            # region too, since a neighbour may have grown into it.
            reached = []
            for fid in fids:
                moved = lyr.getFeature(fid)
                if (moved is not None and moved.isValid()
                        and moved.geometry() is not None
                        and not moved.geometry().isEmpty()):
                    reached.append(moved.geometry())
                before = self._shapes.get(fid)
                if before is not None and not before.isEmpty():
                    reached.append(before)
            if reached:
                merged = self.merge_joined(
                    region=QgsGeometry.unaryUnion(reached))
            if trimmed or given or untangled or merged:
                lyr.endEditCommand()
            else:
                lyr.destroyEditCommand()
            opened = False
        except Exception as err:
            log("error while settling a hand edit: %s" % err)
            if opened:
                # what was half done is taken back: the drag stays as it was
                # made, and Repair can still be pressed. And nothing is
                # announced: the counts describe changes that are undone.
                try:
                    lyr.destroyEditCommand()
                except Exception:
                    pass
                trimmed = split = given = untangled = merged = 0
        finally:
            self._settling = False
        if trimmed or given or untangled or merged:
            lyr.triggerRepaint()
            said = []
            if untangled:
                said.append("%d self-crossing outline%s untangled"
                            % (untangled, "" if untangled == 1 else "s"))
            if trimmed:
                said.append("%d neighbour%s trimmed"
                            % (trimmed, "" if trimmed == 1 else "s"))
            if given:
                said.append("%d gap%s given to the neighbour"
                            % (given, "" if given == 1 else "s"))
            if split:
                said.append("%d piece%s left over"
                            % (split, "" if split == 1 else "s"))
            if merged:
                said.append("%d joined to a neighbour of the same class"
                            % merged)
            where = (" in %s, not the frame in the list"
                     % " and ".join(sorted(elsewhere))) if elsewhere else ""
            iface.messageBar().pushMessage(
                NAME, "vertex moved%s: " % where + ", ".join(said) + ".",
                level=LEVEL_INFO, duration=6)
            log("hand edit settled: %d neighbours trimmed, %d gaps given back, "
                "%d pieces split off, %d joined" % (trimmed, given, split,
                                                   merged))
            time_mark(self, "vertex_edit", tool="", note=", ".join(said))
            self.ticked()
        # The shapes as they are now, so that the next drag of the same border
        # is measured against this one and not against where it started.
        self.remember_shapes()
        self.refresh_coverage()

    # ----------------------------------------------------------- layers
    def layer(self, role):
        return find_mine(self.campaign.data["id"], role)

    def table_back(self, role):
        """A table of the campaign to draw into, loaded again if it has left
        the project.

        Taking the table out of the layer tree is an ordinary thing to do
        with a layers panel, and without this every stroke after it would find
        no table and go nowhere, without a word: the brush moves, nothing is
        drawn, and nothing says why. So the first stroke after it puts the
        table back from the campaign's own file, says so, and is drawn in
        it. What the table held unsaved when it left is in the recovery
        file, which the panel writes the moment a table with edits goes."""
        lyr = self.layer(role)
        if lyr is not None:
            return lyr
        load = getattr(self.panel, "load_layers", None)
        if load is not None:
            try:
                load()
            except Exception as err:
                log("cannot load the %s table again: %s" % (role, err))
        lyr = self.layer(role)
        if lyr is None:
            iface.messageBar().pushMessage(
                NAME, "the %s table is not in the project and could not be "
                      "loaded again, so nothing was drawn: close the campaign "
                      "and open it again" % role,
                level=LEVEL_CRITICAL, duration=10)
            log("the %s table is not in the project and was not loaded again"
                % role, loud=True)
            return None
        iface.messageBar().pushMessage(
            NAME, "the %s table had been taken out of the project: it is "
                  "loaded again from the campaign's file, and this one is "
                  "drawn in it. Edits it held that were not saved are in the "
                  "recovery file, offered at the next Open campaign" % role,
            level=LEVEL_WARNING, duration=10)
        log("the %s table had been taken out of the project and was loaded "
            "again" % role, loud=True)
        self.rewatch_layers()
        return lyr

    @property
    def polygons(self):
        return self.layer("polygons")

    @property
    def tile_layer(self):
        return self.layer("tiles")

    # ----------------------------------------------------------- classes
    def chip_room(self):
        """The width the chips really have right now.

        Not the width of the module: the width of one column of its body, which
        is a different thing as soon as the module is wide enough to be dealt
        into more than one. Before anything is shown there is nothing to
        measure and the guess stands in for it."""
        deck = getattr(self, "deck", None)
        width = deck.width() if deck is not None else 0
        if width > 60:
            return max(deck.room() - 6, 140)
        width = self.contentsRect().width()
        return max(width - 4, 140) if width > 60 else PANEL_W

    def reflow(self):
        """Told by the deck that the columns have moved: the chips are the one
        thing that has to be built again, because how many fit on a row
        depends on the column they ended up in.

        Guarded against itself. Rebuilding the chips changes the height of the
        module, which lays the panel out again, which comes back here: without
        the flag the two would call each other until the chips never finish
        being born and nothing is drawn at all."""
        if getattr(self, "_reflowing", False):
            return
        classes = self.campaign.active_classes()
        if classes and self.chip_columns(classes) != getattr(self, "_columns", None):
            self._reflowing = True
            try:
                self.rebuild_class_buttons()
            finally:
                self._reflowing = False
        elif classes:
            self.fit_names()

    def fit_names(self):
        """Cut the chips' names, and the banner's, to the width they have
        now. The chips are built again only when the number of columns
        changes, and two columns hold over a wide range of widths."""
        columns = getattr(self, "_columns", None)
        if not columns:
            return
        metrics = bold_metrics(self)
        cell = (self.chip_room() - 4 * (columns - 1)) // columns
        for b in self._buttons:
            name = b.property("full_name")
            if name:
                b.setText(metrics.elidedText(
                    name, Qt.TextElideMode.ElideRight,
                    cell - (16 if b.isChecked() else 12)))
        self.show_current_class()

    def chip_columns(self, classes):
        """As many columns as the longest name allows in the room there is,
        and never one column for a legend of four classes or more.

        One long name would put the whole legend in a single column: six
        classes and "salt efflorescence" make six rows of chips, and the
        tools under them go below the fold. Two columns hold as long as
        each can be 70 pixels wide; a name that does not fit is cut, and the
        chip's tooltip and the banner say it whole. Correct does the same
        with its long lists.

        A long legend takes its columns from the room, not from its longest
        name: with forty classes and one of them "Mediterranean maquis
        shrubland" a legend held at two columns at every width is twenty
        rows of chips with the tools two screens below them."""
        return legend_columns(self.natural_columns(classes), len(classes),
                              self.chip_room())

    def natural_columns(self, classes):
        """The columns the longest name allows, with no floor under them.
        Correct counts its own floor from here, with the tick in."""
        metrics = bold_metrics(self)
        widest = max([text_width(metrics, c["name"]) for c in classes] or [40])
        return max(1, min(5, len(classes),
                          (self.chip_room() + 4) // (widest + 24)))

    def resizeEvent(self, ev):
        """The panel can be widened at any moment. The chips follow, and only
        when the number of columns actually changes: rebuilding them at every
        pixel of a drag would flicker for nothing.

        The base class is named rather than asked for: the other two modules
        borrow this method, and a bare super() there looks for the wrong
        class and raises."""
        QGroupBox.resizeEvent(self, ev)
        self.reflow()

    def rebuild_class_buttons(self):
        for b in self._buttons:
            self.class_grid.removeWidget(b)
            b.setParent(None)
            b.deleteLater()
        self._buttons = []
        classes = self.campaign.active_classes()
        if self.class_name not in [c["name"] for c in classes]:
            self.class_name = classes[0]["name"] if classes else None
        # As many columns as the longest name allows: a chip with its name cut
        # in half is worse than a chip on a line of its own.
        metrics = bold_metrics(self)
        room = self.chip_room()
        columns = self.chip_columns(classes)
        self._columns = columns
        cell = (room - 4 * (columns - 1)) // columns

        self._cells = {}
        for i, c in enumerate(classes):
            chosen = c["name"] == self.class_name
            b = ClassChip(self, c["code"])
            # The chosen chip writes in bold inside a ring two pixels wide,
            # so it is cut a little shorter: at cell - 12 it lost its first
            # letter instead of its last.
            b.setProperty("full_name", c["name"])
            b.setText(metrics.elidedText(c["name"], Qt.TextElideMode.ElideRight,
                                         cell - (16 if chosen else 12)))
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            b.setFixedHeight(chip_height(b))
            b.setToolTip("%s, class %d.\nDouble click to rename it: the new "
                         "name runs through\neverything already drawn."
                         % (c["name"], c["code"]))
            b.setChecked(chosen)
            b.setStyleSheet(self._style(c["colour"], chosen))
            b.clicked.connect(shielded(
                lambda _=False, n=c["name"]: self.choose_class(n),
                "Class"))
            where = (i // columns, i % columns)
            self._cells[c["code"]] = where
            self.class_grid.addWidget(b, where[0], where[1])
            self._buttons.append(b)

        # The plus goes after the last class, in the next cell of the same
        # grid, so the legend ends where it can be made longer.
        i = len(classes)
        plus = QPushButton("+")
        plus.setFixedHeight(chip_height(plus))
        plus.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        # drawn as an empty slot, so a white class beside it is not taken
        # for it, nor it for a class
        plus.setStyleSheet(PLUS_STYLE % palette_colours())
        plus.setToolTip(
            "One more class, here, now.\n\nIt is born with the next colour "
            "of the palette and a name\nyou type on the spot. Nothing about "
            "the classes has to be\ndecided before the first stroke: the "
            "ground says what is\nin it, and that is usually at the third "
            "frame, not the first.")
        plus.clicked.connect(shielded(self.add_class, "Add class"))
        self.class_grid.addWidget(plus, i // columns, i % columns)
        self._buttons.append(plus)
        self.settle()
        self.show_current_class()

    # ------------------------------------------------- the legend, in place
    def class_by_code(self, code):
        for c in self.campaign.data["classes"]:
            if c["code"] == code:
                return c
        return None

    def start_rename(self, code):
        """Turn one chip into a box with its own name in it, where it is."""
        c = self.class_by_code(code)
        where = getattr(self, "_cells", {}).get(code)
        if c is None or where is None or getattr(self, "_renaming", None):
            return
        chip = None
        for b in self._buttons:
            if isinstance(b, ClassChip) and b.code == code:
                chip = b
        if chip is None:
            return
        box = NameBox(c["name"],
                      lambda text: self.finish_rename(code, text),
                      self.cancel_rename)
        self._renaming = (code, chip, box)
        # As wide as the chip it replaces, so that the legend does not jump
        # about while a name is being typed: the eye is on the letters, and a
        # row that reflows under them is the fastest way to mistype.
        if chip.width() > 20:
            box.setFixedWidth(chip.width())
        chip.hide()
        self.class_grid.addWidget(box, where[0], where[1])
        # Shown by hand. A widget dropped into a layout is shown for you only
        # when Qt considers the parent visible, and inside a dock that has
        # just been built that is not something to bet a rename on.
        box.show()
        box.setFocus(Qt.FocusReason.OtherFocusReason)

    def cancel_rename(self):
        held = getattr(self, "_renaming", None)
        self._renaming = None
        if not held:
            return
        _, chip, box = held
        self.class_grid.removeWidget(box)
        box.setParent(None)
        box.deleteLater()
        chip.show()

    def finish_rename(self, code, text):
        """Keep the typed name, and carry it into everything already drawn.

        The name has to be unique because the renderer paints by name: two
        classes called the same thing would be one colour on the map and two
        rows in the legend, and no way to tell which is which."""
        self.cancel_rename()
        c = self.class_by_code(code)
        if c is None:
            return
        fresh = (text or "").strip()
        if not fresh or fresh == c["name"]:
            return
        taken = {k["name"] for k in self.campaign.data["classes"]
                 if k["code"] != code}
        if fresh in taken:
            QMessageBox.warning(
                self, NAME,
                "There is already a class called '%s'.\n\nThe map is painted "
                "by name, so two classes cannot share one." % fresh)
            return
        was = c["name"]
        c["name"] = fresh
        try:
            self.campaign.save()
        except Exception as err:
            # Put it back. The legend had already been changed in memory, so a
            # manifest that would not be written left the panel showing the new
            # name, the features carrying the old one, and the next save writing
            # a legend nobody had agreed to.
            c["name"] = was
            self.rebuild_class_buttons()
            trouble(err, "Renaming a class")
            return
        if self.class_name == was:
            self.class_name = fresh
        moved = 0
        # The renaming is the program's own edit, not a mark being changed:
        # with the marks locked, a rename whose commit failed was taken for an
        # edit and walked back, leaving the features under the old name and
        # the legend under the new one. Done as our own, and the lock then
        # holds from where the rename left the tables.
        settling = getattr(self, "_settling", False)
        self._settling = True
        try:
            moved = self.panel.rename_features()
        except Exception as err:
            log("the new name did not reach what is drawn: %s" % err)
        finally:
            self._settling = settling
        if hasattr(self, "rebase_lock"):
            self.rebase_lock()
        restyle(self.campaign)
        self.rebuild_class_buttons()
        # Only the annotation module filters what it shows; the others have
        # nothing to re-filter, and asking them for it is how a method lent
        # between modules turns into a crash in the one that borrowed it.
        if hasattr(self, "apply_filter"):
            self.apply_filter()
        self.panel.describe_campaign()
        log("class %d renamed from '%s' to '%s'%s"
            % (code, was, fresh,
               ", %d thing%s renamed with it" % (moved, "" if moved == 1 else "s")
               if moved else ""), loud=True)

    def add_class(self):
        """A new class, on the spot, with its name ready to be typed."""
        code = self.campaign.next_code()
        if code > MAX_CLASS_CODE:
            QMessageBox.warning(self, NAME, no_room_for_class())
            log("no class added: the campaign has no class code left")
            return
        used = len(self.campaign.data["classes"])
        fresh = {"name": "class %d" % code,
                 "colour": PALETTE[used % len(PALETTE)],
                 "code": code}
        self.campaign.data["classes"].append(fresh)
        self.campaign.save()
        restyle(self.campaign)
        self.class_name = fresh["name"]
        self.rebuild_class_buttons()
        # restyle() hands the layer a plain categorized renderer, which is the
        # renderer the filter is built on top of: every rule, and with it the
        # operator, the pass and the current frame, is gone the moment it runs.
        # Adding a class did not put it back, so pressing + un-hid everybody
        # else's work without a word while the brush, Fill Gap and the coverage
        # went on seeing one operator and one pass. That is what made a frame
        # read 100% with another operator's polygon lying across it.
        #
        # Guarded, because this method is lent to the Objects module, which has
        # no filter to apply: unguarded, pressing + there raised AttributeError
        # after the class had already been saved, and the rename box never
        # opened. finish_rename has carried the same guard all along.
        if hasattr(self, "apply_filter"):
            self.apply_filter()
        self.panel.describe_campaign()
        log("class %d added: %s" % (code, fresh["name"]))
        # The name is the part that matters, so the box opens by itself and
        # "class 7" is only what it is called if nothing is typed over it.
        QTimer.singleShot(0, lambda: self.start_rename(code))

    def settle(self):
        """The grid is rebuilt in place, and a legend that goes from two rows
        to three does not by itself tell the layouts above it that it now needs
        more room: the chips end up drawn over the buttons underneath. Every
        box between the grid and the module is told, from the inside out."""
        self.class_grid.invalidate()
        deck = getattr(self, "deck", None)
        if deck is not None:
            for column in deck.columns:
                column.invalidate()
            deck.strip.invalidate()
            deck.updateGeometry()
        if self.layout() is not None:
            self.layout().invalidate()
        self.updateGeometry()

    def show_current_class(self):
        if self.class_name is None:
            self.current_label.setText("no class")
            self.current_label.setStyleSheet(
                "background-color:palette(button); color:palette(mid);"
                " border:1px dashed palette(mid); border-radius:4px;")
            return
        colour = self.current_colour()
        ink = ink_on(colour)
        # Cut to the banner, never past both its ends: centred and too long,
        # "Mediterranean maquis shrubland" lost its first letters as well as
        # its last. The whole name is in the tooltip.
        room = self.current_label.width() if self.current_label.width() > 60 \
            else self.chip_room()
        self.current_label.setText(self.current_label.fontMetrics().elidedText(
            self.class_name, Qt.TextElideMode.ElideRight, max(room - 16, 40)))
        self.current_label.setToolTip(self.class_name)
        self.show_tool_caption()
        self.current_label.setStyleSheet(
            "background-color:%s; color:%s; border:1px solid rgba(0,0,0,0.3);"
            " border-radius:4px;" % (colour, ink))

    CAPTIONS = (("b_tiles", "Tiles: click empty ground to place a frame"),
                ("b_move", "Move: drag a frame to where it belongs"),
                ("b_vertices", "Vertices: drag the corners of a shape"),
                ("b_brush", "Polygon: click or drag round an area"),
                ("round_brush", "Round brush: click or drag to paint"),
                ("b_line", "Line: click or drag, right click ends it"),
                ("b_points", "Points: each click drops one point"),
                ("b_tool", "Boxes: drag on the image to draw one"))

    def show_tool_caption(self):
        """The tool in hand and what a click does with it, in a few words."""
        label = getattr(self, "tool_caption", None)
        if label is None:
            return
        words = "No tool in hand: pick one under SHAPE"
        for attr, caption in self.CAPTIONS:
            b = getattr(self, attr, None)
            if b is not None and b.isChecked():
                words = caption
                break
        lock = getattr(self, "lock_marks", None)
        if lock is not None and lock.isChecked():
            words = "The marks are locked: nothing can be drawn"
        label.set_text(words)

    def _style(self, colour, chosen):
        """The chosen class is marked in the one colour guaranteed to read on
        its own chip: the ink the chip already writes with. A black ring is
        invisible on a dark brown and a white one on a pale grey."""
        ink = ink_on(colour)
        light = ink != "#ffffff"
        edge = "rgba(0,0,0,0.45)" if light else "rgba(255,255,255,0.45)"
        # The keyboard's place, dashed in the chip's own ink: the borders
        # here replace the style's focus frame.
        if chosen:
            return ("QPushButton{background-color:%s; color:%s; font-weight:bold;"
                    " border:2px solid %s; border-radius:3px; padding:0px 3px;}"
                    "QPushButton:focus{border-style:dashed;}"
                    % (colour, ink, ink))
        return ("QPushButton{background-color:%s; color:%s; border:1px solid %s;"
                " border-radius:3px; padding:1px 4px;}"
                "QPushButton:hover{border:2px solid %s; padding:0px 3px;}"
                "QPushButton:focus{border:2px dashed %s; padding:0px 3px;}"
                % (colour, ink, edge, ink, ink))

    def choose_class(self, name):
        """Pick the class the next mark belongs to.

        Every tool that draws in the class colour is told, the line included:
        left out, it would keep the colour of the class you had before, all
        the way through the drawing of the line, and only come out right once
        the line was finished. The trace is how you judge where the line is
        going, so it is the one place the colour matters most."""
        self.class_name = name
        self.rebuild_class_buttons()
        for tool in (self.brush, getattr(self, "line_tool", None),
                     getattr(self, "point_tool", None),
                     getattr(self, "tool", None)):
            paint = getattr(tool, "refresh_colour", None)
            if paint is not None:
                paint()
        time_mark(self, "class", class_code=self.code_of(name))

    def current_colour(self):
        for c in self.campaign.active_classes():
            if c["name"] == self.class_name:
                return c["colour"]
        return "#888888"

    def current_code(self):
        for c in self.campaign.active_classes():
            if c["name"] == self.class_name:
                return c["code"]
        return 0

    # ----------------------------------------------------------- tiles
    def show_side_in_pixels(self):
        px, py = self.geometry.pixel_m
        n = int(round(self.tile_side.value() / px)) if px else 0
        if px and abs(px - py) > 0.01 * px:
            # A frame is square in pixels, which is what a chip for training
            # has to be; on pixels that are not square on the ground it is
            # then a rectangle in metres, and the box says which one.
            self.side_px.setText("%d x %d px = %.2f x %.2f%s"
                                 % (n, n, n * px, n * py,
                                    spin_suffix(self.geometry)))
        else:
            self.side_px.setText("%d px" % n)
        self.tile_side.setStyleSheet("" if n >= 32 else "color:#c0392b;")

    def brush_changed(self, *args):
        px = self.geometry.pixel_m[0]
        n = int(round(self.radius.value() / px)) if px else 0
        self.radius_px.setText("%d px" % n)
        if self.brush is not None:
            self.brush.refresh_colour()

    def all_tiles(self):
        lyr = self.tile_layer
        return [] if lyr is None else list(lyr.getFeatures())

    def refresh_tiles(self):
        if not self.tiled:
            return
        current = self.tiles.currentData()
        self.tiles.blockSignals(True)
        self.tiles.clear()
        # A frame imported with a sampling design says which draw it is, in
        # the tooltip of its line in the list and under the list while it is
        # in hand; a frame placed by hand says nothing more than before.
        self.design_lines = {}
        for f in self.all_tiles():
            self.tiles.addItem(str(f["tile_id"]), f["tile_id"])
            said = design_tile_line(design_feature_values(f))
            if said:
                self.design_lines[f["tile_id"]] = said
                self.tiles.setItemData(self.tiles.count() - 1, said,
                                       Qt.ItemDataRole.ToolTipRole)
        if current:
            i = self.tiles.findData(current)
            if i >= 0:
                self.tiles.setCurrentIndex(i)
        self.tiles.blockSignals(False)
        self.show_design_line()
        self.refresh_coverage()

    def show_design_line(self, *args):
        """The quiet line under the list: the design of the frame in hand,
        hidden when it has none."""
        line = getattr(self, "design_line", None)
        if line is None:
            return
        said = (getattr(self, "design_lines", None) or {}).get(
            self.tiles.currentData(), "")
        line.setText(said)
        line.setVisible(bool(said))

    def tile_ids(self):
        """The frames that exist, whoever made them. The operator filter has
        no business here: a frame is ground, not a reading of it."""
        if not self.tiled:
            return []
        return [self.tiles.itemData(i) for i in range(self.tiles.count())]

    def current_tile_id(self):
        if not self.tiled:
            return None
        return self.tiles.currentData()

    def tile_geometry(self):
        if not self.tiled:
            return None
        return self.frame_geometry(self.current_tile_id())

    def frame_geometry(self, tid):
        """The outline of a frame by name, or None."""
        if not self.tiled or tid is None:
            return None
        for f in self.all_tiles():
            if f["tile_id"] == tid:
                return QgsGeometry(f.geometry())
        return None

    def tile_at(self, point):
        p = QgsGeometry.fromPointXY(point)
        for f in self.all_tiles():
            if f.geometry().contains(p):
                return f
        return None

    def measure_tile(self, feature):
        """Write onto a frame what it is now: its side, and whether the
        partition inside it is closed.

        Neither is set once and left. side_m is not just the nominal side asked
        for at the moment of creation; move the frame, or drag a corner with
        the QGIS vertex tool, and a stale number would go on being claimed,
        and travel into the metadata of every cutout made from that frame.
        closed means what its name says: every pixel inside the frame
        belongs to some class, so the frame is a closed partition and can be
        handed to somebody as a complete reading. A frame at 99.4 per cent is
        not closed, and saying so is the whole point of the column.

        And complete in one reading, one operator in one pass, the way Check
        measures it: two operators who have each painted sixty per cent of a
        frame, in different places, make one hundred together, and the frame
        would be written down as closed, a complete reading nobody had made."""
        tiles = self.tile_layer
        if tiles is None or feature is None or not feature.hasGeometry():
            return
        names = {f.name() for f in tiles.fields()}
        geom = feature.geometry()
        box = geom.boundingBox()
        side = 0.0
        try:
            side = self.geometry.measure.measureLine(
                QgsPointXY(box.xMinimum(), box.yMinimum()),
                QgsPointXY(box.xMaximum(), box.yMinimum()))
        except Exception:
            side = box.width()

        # Counted reading by reading, and the fullest reading decides. Summed
        # over every pass at once, a frame read twice reached two hundred per
        # cent and was written down as closed while the reading in hand was
        # barely started: the number said "finished" about work that was not.
        # Counted pass by pass, two operators in one pass were one reading,
        # and their two halves closed the frame. A reading is a pass and an
        # operator, here as in Check, in the filter and in the brush.
        total = self.geometry.area(geom)
        tid = feature["tile_id"]
        lyr = self.polygons
        # And within a reading, measured on the union rather than on a sum:
        # two polygons of one reading that overlap each other were counted
        # twice, which would paint the panel a green hundred per cent over a
        # frame that still has holes in it. closed is written
        # from this number, and a frame written down as closed is one somebody
        # is told they can hand over.
        held = {}
        if lyr is not None:
            for f in lyr.getFeatures():
                if f["tile_id"] != tid or not f.hasGeometry():
                    continue
                # clipped to the frame: after a hand edit a polygon can stick
                # out, and counting it whole put the coverage over one hundred
                piece = f.geometry().intersection(geom)
                if piece is None or piece.isEmpty():
                    continue
                reading = (self.pass_of(f), self.operator_of(f))
                held.setdefault(reading, []).append(piece)
        per_reading = {}
        for reading, pieces in held.items():
            one = None
            if len(pieces) > 1:
                try:
                    one = QgsGeometry.unaryUnion(pieces)
                except Exception:
                    one = None
            else:
                one = pieces[0]
            per_reading[reading] = self.geometry.area(one) \
                if (one is not None and not one.isEmpty()) \
                else sum(self.geometry.area(x) for x in pieces)
        painted = max(per_reading.values()) if per_reading else 0.0
        share = min(painted / total, 1.0) if total else 0.0

        if not tiles.isEditable():
            tiles.startEditing()
        if "side_m" in names:
            tiles.changeAttributeValue(
                feature.id(), tiles.fields().indexOf("side_m"),
                round(float(side), 4))
        if "closed" in names:
            tiles.changeAttributeValue(
                feature.id(), tiles.fields().indexOf("closed"),
                1 if share > CLOSED_SHARE else 0)

    def measure_all_tiles(self):
        """Every frame, at save time. Read into a list first: writing to a
        layer while its own iterator is still open is how a loop starts
        skipping features."""
        tiles = self.tile_layer
        if tiles is None:
            return 0
        everything = list(self.all_tiles())
        for f in everything:
            try:
                self.measure_tile(f)
            except Exception as err:
                log("cannot measure tile %s: %s" % (f["tile_id"], err))
        return len(everything)

    def free_tile_id(self):
        """The next frame's name.

        Counted from the highest there has ever been, not from the first gap.
        Reusing a gap means the id of a frame somebody deleted comes back on a
        different piece of ground, and any note, table or message that named
        the old one now points at the new one without a word.

        It is still only unique within this package. Two people working on two
        copies will both reach t050, and merging the copies would fuse two
        different pieces of ground into one name. That stays a limit: a cure
        would take an id nobody can guess, and those are unpleasant to say out
        loud to a colleague on the phone."""
        top = 0
        for f in self.all_tiles():
            name = f["tile_id"] or ""
            digits = "".join(c for c in str(name) if c.isdigit())
            if digits:
                try:
                    top = max(top, int(digits))
                except ValueError:
                    pass
        return "t%03d" % (top + 1)

    def tables_of_tile(self, tile_id):
        """Everything that carries this frame's name, table by table.

        Taking the polygons alone is not enough. The lines, the points and the
        boxes all carry a tile_id too, and they would be left behind pointing
        at a frame that no longer exists, or that has moved and no longer
        describes the ground under them."""
        out = []
        for role in ("polygons", "lines", "points", "boxes"):
            lyr = self.layer(role)
            if lyr is None:
                continue
            ids = [f.id() for f in lyr.getFeatures()
                   if f["tile_id"] == tile_id]
            if ids:
                out.append((role, lyr, ids))
        return out

    def frame_clash(self, geom, skip=None, among=None):
        """The names of the frames an outline would overlap, or an empty list.

        Frames may touch, edge to edge, and that is how a grid of them is laid
        down; they may not overlap. Ground inside two frames is ground read
        twice, counted twice in the coverage, and burned twice in the export
        with whatever class came last. So a frame may not be placed half over
        another one, or dragged on top of it, without the program saying so.

        Touching is told from overlapping by the area they share, not by
        whether they meet: two frames side by side share an edge, which has no
        area at all. A thousandth of a pixel is the allowance, far above the
        last digit of two edges worked out twice and far below anything a hand
        could do on purpose.

        skip is the feature id of the frame being moved, so that it does not
        clash with where it is now. among is a list of frames read once
        beforehand, for the tool that asks at every movement of the mouse."""
        if geom is None or geom.isEmpty():
            return []
        try:
            px, py = self.geometry.pixel_crs
            tiny = FRAME_OVERLAP_PX2 * abs(px * py)
        except Exception:
            tiny = 0.0
        frames = self.all_tiles() if among is None else among
        out = []
        for f in frames:
            if skip is not None and f.id() == skip:
                continue
            if not f.hasGeometry():
                continue
            other = f.geometry()
            if not geom.intersects(other):
                continue
            shared = geom.intersection(other)
            if shared is None or shared.isEmpty():
                continue
            if shared.area() > tiny:
                out.append(str(f["tile_id"]))
        return out

    @staticmethod
    def pass_of(feature):
        """The pass a mark belongs to, read off the mark. A mark written before
        the field existed, or with it left empty, was drawn in the first pass,
        which is what reading_of and Check already take it to be."""
        try:
            return int(feature["pass_no"] or 1)
        except (TypeError, ValueError, KeyError, IndexError):
            return 1

    def foreign_work(self, held):
        """What, of everything a frame holds, is not the current operator's
        work in the current pass: {(operator, pass): how many}.

        Every table and every pass, whatever is on screen. The filters decide
        what can be seen; they do not decide what moving or deleting a frame
        takes with it, and that is the whole reason for asking."""
        mine = self.operator_name()
        try:
            now_pass = int(self.pass_no.value())
        except (TypeError, ValueError):
            now_pass = 1
        out = {}
        for role, lyr, ids in held:
            for f in lyr.getFeatures(QgsFeatureRequest().setFilterFids(ids)):
                key = (self.operator_of(f), self.pass_of(f))
                if key == (mine, now_pass):
                    continue
                out[key] = out.get(key, 0) + 1
        return out

    def frame_refusal(self, tid, verb, held=None):
        """Why a frame may not be moved or deleted, or None when it may.

        A frame is somebody's reading of a piece of ground. Moving it, with its
        contents or without them, and deleting it, both rewrite or destroy what
        is inside, and what is inside may not be the person's own: another
        operator's polygons, the first pass hidden under a blind second one,
        would all go with the frame. So a frame can be moved or deleted only
        by the person whose work it holds, in the pass they are drawing; an
        empty frame by anybody.

        In a blind pass the names stay hidden. Saying "ANNA has twelve polygons
        here" to the second reader would tell them where the first reading
        was, which is the one thing a blind pass exists not to tell."""
        if held is None:
            held = self.tables_of_tile(tid)
        foreign = self.foreign_work(held)
        if not foreign:
            return None
        rule = ("Only a frame that is empty, or that holds nothing but your "
                "own work of pass %d, can be moved or deleted."
                % self.pass_no.value())
        if self.hiding():
            return ("tile %s cannot be %s: it holds work of another reading. %s"
                    % (tid, verb, rule))
        mine = self.operator_name()
        parts = []
        for (who, reading), n in sorted(foreign.items(),
                                        key=lambda kv: (kv[0][1], kv[0][0])):
            parts.append("%d mark%s by %s in pass %d"
                         % (n, "" if n == 1 else "s",
                            "you (%s)" % who if who == mine else who, reading))
        return ("tile %s cannot be %s: it holds work that is not yours in this "
                "pass, %s. %s" % (tid, verb, ", ".join(parts), rule))

    def refuse(self, msg):
        """A refusal, said where it is seen and kept in the log."""
        log(msg)
        iface.messageBar().pushMessage(NAME, msg, level=LEVEL_WARNING,
                                       duration=10)

    def create_tile(self, centre):
        if self.frames_locked():
            return
        lyr = self.table_back("tiles")
        if lyr is None:
            return
        side = self.tile_side.value()
        g, side_px = self.geometry.snapped_square(centre, side)
        if g is None or g.isEmpty():
            g, side_px = self.geometry.square(centre, side), 0
        if g is None or g.isEmpty():
            log("the square came out empty: centre %s, side %.2f m, CRS %s"
                % (centre.toString(2), side, crs_label(self.geometry.crs)))
            return
        # The filter comes off BEFORE the ids are read. all_tiles() honours a
        # subset string, so with one live the list came back short, the new
        # frame took an id that a hidden frame already had, and from then on a
        # delete of either one took out both, with both sets of work.
        if lyr.subsetString():
            lyr.setSubsetString("")
        # Not over another frame. A click on empty ground close to a frame
        # would put the new square half on top of it, and nothing would say so.
        # Asked with the filter off, for the same reason the id is.
        clash = self.frame_clash(g)
        if clash:
            self.refuse("no frame placed: a frame of %.2f m centred there would "
                        "overlap %s. Frames may touch but never overlap: click "
                        "further from it, or make the side smaller under "
                        "Settings" % (side, ", ".join(clash)))
            return
        tid = self.free_tile_id()
        if not lyr.isEditable():
            if not lyr.startEditing():
                log("cannot open the tiles layer for editing")
                return
        f = QgsFeature(lyr.fields())
        f.setGeometry(g)
        f["tile_id"] = tid
        f["side_m"] = float(side_px * self.geometry.pixel_m[0]) if side_px \
            else float(side)
        f["created"] = now()
        f["closed"] = 0
        if not lyr.addFeature(f):
            log("the tile was refused by the layer")
            with own_hands():
                lyr.rollBack()
            return
        if not lyr.commitChanges():
            log("the tile could not be written: %s" % "; ".join(lyr.commitErrors()))
            with own_hands():
                lyr.rollBack()
            self.panel.keep_safe()
            return
        # The commit took whatever else the table held with it: the net is
        # brought up to date now, and not at the next stroke.
        self.panel.keep_safe()
        lyr.updateExtents()
        lyr.triggerRepaint()
        self.frame_event("new", tid, None, bbox_of(g), f)
        self.refresh_tiles()
        self.select_tile(tid)
        if self.lock_view.isChecked():
            self.go_to()
        box = g.boundingBox()
        log("tile %s created, %.2f m a side, %.2f m2, at %s in %s. "
            "The layer now holds %d tiles."
            % (tid, side, self.geometry.area(g), box.center().toString(2),
               crs_label(self.geometry.crs), lyr.featureCount()))
        # One frame, then the map goes back to drawing. Placing a frame is what
        # you do before the work, not during it, and a tool still in hand after
        # the frame is down turns the next click, the one meant to begin a
        # polygon, into a second frame nobody asked for.
        self.use_brush()
        iface.messageBar().pushMessage(
            NAME, "frame %s placed, the polygon is back in hand: press Tiles "
                  "again for another frame" % tid, level=LEVEL_INFO, duration=4)

    def move_tile(self, feature, dx, dy):
        """Moving a tile that holds work: two honest answers, and neither is
        the default.

        Carry the work with it and the partition stays closed, every polygon
        still inside the frame it was drawn in, and every one of them now
        describing a different patch of earth: the shapes are right and the
        ground under them is not. Leave the work behind and the frame is
        clean, but an afternoon is gone. Which of the two is the lesser harm
        depends on why the frame is being moved, and only the person moving it
        knows that, so both are offered and Cancel is what Esc does.

        Two moves are refused before either is offered: one that would land
        the frame on top of another frame, and one of a frame that holds work
        other than the mover's own in this pass (frame_refusal says whose)."""
        if self.frames_locked():
            return
        tiles = self.tile_layer
        tid = feature["tile_id"]

        # Where it would land, worked out before anything is asked. The drag
        # ends wherever the mouse was released, which is never a pixel edge, so
        # the frame is put back on the grid first.
        was = feature.geometry().boundingBox()
        g = QgsGeometry(feature.geometry())
        g.translate(dx, dy)
        snapped, _ = self.geometry.regrid(g.boundingBox())
        if snapped is not None and not snapped.isEmpty():
            g = snapped
        # What the frame really moves by, which is not what the mouse did. The
        # marks are translated by this, to the last decimal, so that a polygon
        # that sat on a pixel edge still sits on one afterwards; translating
        # them by dx, dy would leave every edge a fraction of a pixel off the
        # grid and nothing would ever put it back.
        mx = g.boundingBox().xMinimum() - was.xMinimum()
        my = g.boundingBox().yMinimum() - was.yMinimum()
        if mx == 0 and my == 0:
            # Zoomed in far enough, a drag of several screen pixels is less
            # than half a raster pixel and snaps back into the cell it started
            # from. The frame is not moving, so there is nothing to ask, no
            # geometry to rewrite and nothing to announce: it was a click that
            # wandered. The threshold that matters is the grid, not the screen.
            log("tile %s: the drag snapped back into the same cell" % tid)
            return

        # Where it lands may not be on top of another frame, whoever made it.
        # Asked here, before the question and before anything is written: the
        # answer does not depend on what is inside, and a move that is going
        # to be refused should not first ask what to do with the contents.
        clash = self.frame_clash(g, skip=feature.id())
        if clash:
            self.refuse("tile %s not moved: where it was dropped it would "
                        "overlap %s. Frames may touch but never overlap: drag "
                        "it onto free ground" % (tid, ", ".join(clash)))
            self.apply_filter()
            return

        held = self.tables_of_tile(tid)
        # And only a frame that holds nothing but the mover's own work of this
        # pass. Everything it holds is carried or deleted with it, and that
        # includes the work nobody on screen can see.
        why = self.frame_refusal(tid, "moved", held)
        if why:
            self.refuse(why)
            self.apply_filter()
            return
        total = sum(len(ids) for _, _, ids in held)
        carry = False

        if total:
            if self.marks_locked():
                # Moving a full frame touches what is inside it, whether it is
                # carried along or deleted, and the marks lock exists to say
                # that nothing drawn may be touched. The brush is not the only
                # thing that consults it.
                return
            what = ", ".join("%d %s" % (len(ids), role)
                             for role, _, ids in held)
            ask = QMessageBox(self)
            ask.setIcon(QMessageBox.Icon.Warning)
            ask.setWindowTitle("Move tile")
            ask.setText("Tile %s holds %s." % (tid, what))
            ask.setInformativeText(
                "Take them with it: every mark is translated by the same "
                "amount, the frame stays a closed partition, and each mark "
                "now covers ground it was not drawn on.\n\n"
                "Leave them behind: they would sit outside the frame, so they "
                "are deleted.")
            with_them = ask.addButton("Move with its contents",
                                      QMessageBox.ButtonRole.AcceptRole)
            without = ask.addButton("Move and delete them",
                                    QMessageBox.ButtonRole.DestructiveRole)
            ask.addButton(QMessageBox.StandardButton.Cancel)
            ask.setDefaultButton(ask.button(QMessageBox.StandardButton.Cancel))
            run_dialog(ask)     # one place in the program knows how Qt spells exec
            chosen = ask.clickedButton()
            if chosen is with_them:
                carry = True
            elif chosen is not without:
                self.apply_filter()
                log("tile %s left where it was" % tid)
                return

        if not tiles.isEditable():
            tiles.startEditing()
        tiles.changeGeometry(feature.id(), g)
        if not tiles.commitChanges():
            # Not rolled back either: other frames placed a minute ago were
            # still in this same buffer.
            log("the tile could not be moved and is still waiting to be "
                "saved: %s" % "; ".join(tiles.commitErrors()), loud=True)
            if not tiles.isEditable():
                tiles.startEditing()
            self.apply_filter()
            return
        self.panel.keep_safe()
        tiles.updateExtents()
        tiles.triggerRepaint()
        self.frame_event("move", tid, bbox_of(feature.geometry()), bbox_of(g),
                         feature)

        # The contents are touched only now, and only because the frame has
        # already moved. The other way round, a frame whose move failed on a
        # locked package left the user with the frame exactly where it was and
        # its thirty seven polygons committed away for nothing: they had
        # answered "move it and lose them", not "lose them and keep it here".
        carried = 0
        # Carrying is a translation, not a hand edit. Every changeGeometry below
        # fires geometryChanged, and with nothing to say otherwise each one was
        # taken for a vertex dragged by hand: settle_edits ran on it, compared it
        # with where it was before the move, found a strip "freed" along one
        # side, and give_back handed that strip to a neighbour. A frame moved
        # with its contents came out with ground painted that nobody had
        # painted. The flag is what note_geometry_change already reads to tell
        # the program's own edits from a person's.
        self._settling = True
        try:
            self._carry_or_drop(held, carry, mx, my)
            carried = self._carried
        finally:
            self._settling = False
        # what is remembered is now where the polygons are, not where they were
        self.remember_shapes()

        for fresh in self.all_tiles():
            if fresh["tile_id"] == tid:
                self.measure_tile(fresh)
                tiles.commitChanges()
                break
        self.panel.keep_safe()
        self.apply_filter()
        self.refresh_coverage()
        # The line only runs at the end of a successful move, so the frame did
        # move; a report that raised here, naming a variable of the move, would
        # be the thing that failed after it.
        log("tile %s moved by %.2f, %.2f%s"
            % (tid, mx, my,
               (", %d thing%s moved with it" % (carried,
                                                "" if carried == 1 else "s")
                if carry else
                ", %d thing%s deleted with it" % (total,
                                                  "" if total == 1 else "s"))
               if total else ""), loud=bool(total and not carry))
        # Loud only when something was destroyed. A frame that travelled with
        # its contents shows what it did on the map, and a banner that stands
        # there for seven seconds after every drag is noise in front of the
        # thing being looked at.

    def _carry_or_drop(self, held, carry, mx, my):
        """Translate, or delete, what a moving frame holds, table by table."""
        self._carried = 0
        carried = 0
        for role, lyr, ids in held:
            if not lyr.isEditable():
                lyr.startEditing()
            if carry:
                # Everything the frame holds, hidden or not. move_tile lets
                # only a frame holding the mover's own work of this pass get
                # this far, but whatever the filters keep off the screen still
                # has to travel with the frame, or it would be left behind
                # outside it, invisible and wrong.
                for f in lyr.getFeatures(QgsFeatureRequest().setFilterFids(ids)):
                    shape = f.geometry()
                    if shape is None or shape.isEmpty():
                        continue
                    shape = QgsGeometry(shape)
                    shape.translate(mx, my)
                    if lyr.changeGeometry(f.id(), shape):
                        carried += 1
            else:
                lyr.deleteFeatures(ids)
            if not lyr.commitChanges():
                # No rollBack. A failed commit leaves the buffer as it was, so
                # rolling back threw away every mark still pending in that
                # table, including the ones drawn in other frames. Leave them
                # where they are: Save will try again.
                log("%s: what was inside the frame could not be %s, and it is "
                    "still waiting to be saved: %s"
                    % (role, "moved with it" if carry else "removed",
                       "; ".join(lyr.commitErrors()[:2])), loud=True)
            if not lyr.isEditable():
                lyr.startEditing()
            # Table by table, as flush_layers does: the commit took this
            # table's other pending strokes with it, and a crash before the
            # next one must not put them back a second time.
            self.panel.keep_safe()
            lyr.updateExtents()
            lyr.triggerRepaint()
        self._carried = carried

    def delete_tile(self):
        if self.frames_locked():
            return
        tid = self.current_tile_id()
        if tid is None:
            return
        held = self.tables_of_tile(tid)
        total = sum(len(ids) for _, _, ids in held)
        if total and self.marks_locked():
            # Deleting a frame deletes what is drawn in it, and the marks lock
            # exists to say nothing drawn may go. Moving a frame always asked
            # it; deleting one did not.
            return
        # The same rule as moving it. A question that only added "so many of
        # them belong to another operator and are hidden from you", and then
        # deleted them anyway on a Yes, would not do; in a blind pass it would
        # not say even that much, and the first reading would go without a
        # word.
        why = self.frame_refusal(tid, "deleted", held)
        if why:
            self.refuse(why)
            self.apply_filter()
            return
        what = ", ".join("%d %s" % (len(ids), role) for role, _, ids in held)
        # A warning, with a button that says what it does: this cannot be
        # undone, and a Yes under a question mark did not look like it.
        ask = QMessageBox(self)
        ask.setIcon(QMessageBox.Icon.Warning)
        ask.setWindowTitle("Delete tile")
        ask.setText("Delete tile %s%s?"
                    % (tid, " and the %s drawn in it" % what
                       if total else " (nothing drawn in it)"))
        drawn = [design_feature_values(f) for f in self.all_tiles()
                 if f["tile_id"] == tid]
        sample = drawn[0].get("sample_id") if drawn else None
        ask.setInformativeText(
            "This cannot be undone from here."
            + ("\n\nThis frame is sample %s of the imported design. "
               "Deleting it takes a draw out of the sample; it will be "
               "written in design_log.csv." % sample if sample else ""))
        go = ask.addButton("Delete tile", QMessageBox.ButtonRole.DestructiveRole)
        ask.setDefaultButton(ask.addButton(QMessageBox.StandardButton.Cancel))
        run_dialog(ask)     # one place in the program knows how Qt spells exec
        if ask.clickedButton() is not go:
            self.apply_filter()
            return
        # The frame goes first and its commit is read, the same order
        # move_tile settled on. The other way round, a package locked by
        # OneDrive or by a second QGIS took the thirty seven polygons and left
        # the frame sitting there, and the log said the frame was deleted.
        tiles = self.tile_layer
        gone = [f for f in self.all_tiles() if f["tile_id"] == tid]
        victim = [f.id() for f in gone]
        if victim:
            if not tiles.isEditable():
                tiles.startEditing()
            tiles.deleteFeatures(victim)
            if not tiles.commitChanges():
                log("the tile could not be deleted, so nothing was: %s"
                    % "; ".join(tiles.commitErrors()[:2]), loud=True)
                tiles.startEditing()
                self.apply_filter()
                return
            tiles.startEditing()
            self.panel.keep_safe()
            tiles.triggerRepaint()
            for f in gone:
                self.frame_event("delete", tid, bbox_of(f.geometry()), None, f)
        failed = []
        for role, lyr, ids in held:
            if not lyr.isEditable():
                lyr.startEditing()
            lyr.deleteFeatures(ids)
            if not lyr.commitChanges():
                failed.append(role)
                log("%s: what was inside the frame could not be removed: %s"
                    % (role, "; ".join(lyr.commitErrors()[:2])), loud=True)
            lyr.startEditing()
            # The frame's polygons are gone from the package. Until the net
            # says so it still lists them, and a crash then puts them back
            # into a frame that no longer exists.
            self.panel.keep_safe()
            lyr.triggerRepaint()
        log("tile %s deleted, with %s%s"
            % (tid, what or "nothing in it",
               "; %s could not be emptied and still hold it"
               % ", ".join(failed) if failed else ""))
        self.refresh_tiles()
        self.apply_filter()

    def frame_event(self, kind, tile_id, before, after, feature):
        """Tell whoever listens (measure.FRAME_LISTENERS) that a frame was
        placed (new), moved (move), deleted (delete) or imported (import):
        before and after are its bounding boxes, (xmin, ymin, xmax, ymax),
        or None, and feature the frame. Called only once the change is
        committed, so a listener never hears of a frame that is not in the
        package. A listener that fails is said in the log and the others
        still hear."""
        listeners = getattr(self.panel, "frame_listeners", None)
        try:
            found = listeners() if callable(listeners) else []
        except Exception as err:
            log("cannot ask who listens to the frames: %s" % err)
            found = []
        for listen in found:
            try:
                listen(self, kind, tile_id, before, after, feature)
            except Exception as err:
                log("a listener of the frames failed on %s %s: %s"
                    % (kind, tile_id, err))

    def edit_note(self):
        """A word on the frame, kept with it and shown on the map."""
        tid = self.current_tile_id()
        if tid is None:
            return
        lyr = self.tile_layer
        feature = None
        for f in self.all_tiles():
            if f["tile_id"] == tid:
                feature = f
                break
        if feature is None:
            return
        current = feature["note"] if "note" in feature.fields().names() else ""
        text, ok = QInputDialog.getText(self, "Note on %s" % tid, "note",
                                        QLineEdit.EchoMode.Normal, current or "")
        if not ok:
            return
        index = lyr.fields().indexOf("note")
        if index < 0:
            log("this campaign has no column for the note: reopen it")
            return
        if not lyr.isEditable():
            lyr.startEditing()
        lyr.beginEditCommand("note on %s" % tid)
        lyr.changeAttributeValue(feature.id(), index, text.strip())
        lyr.endEditCommand()
        if not lyr.commitChanges():
            log("the note could not be written: %s"
                % "; ".join(lyr.commitErrors()[:2]), loud=True)
            with own_hands():
                lyr.rollBack()
        lyr.startEditing()
        self.panel.keep_safe()
        lyr.triggerRepaint()
        self.refresh_tiles()

    def import_tiles(self):
        """Frames from a vector file, with the sampling design they were
        drawn under: a sample drawn in AcATaMa or in R (spsurvey, sampling,
        sf), or the frames somebody else worked on.

        The window (ImportFrames) says which columns are the design and what
        will happen to every unit before anything does. A frame keeps the
        whole of its shape, not just the middle; a feature with no geometry
        and a duplicate are counted; a frame over another frame is refused,
        as no click could make one. The units are taken in order of fid, an
        earlier draw winning, each one added, completed, already there or
        refused and why (design_plan); the five design columns come along
        into the tiles table; and every feature of the file gets a row in
        design_log.csv, written once the frames are on disk, as is the
        manifest's entry. A
        failed commit is written there too, as not_written. Nothing is
        estimated and nothing is derived from anything else."""
        if self.frames_locked():
            return
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Frames to import", "",
            "Vector files (*.gpkg *.geojson *.json *.shp);;All files (*)")
        if not chosen:
            return
        source = QgsVectorLayer(chosen, "frames", "ogr")
        if not source.isValid():
            QMessageBox.warning(self, NAME, "That file will not open as vectors.")
            return
        lyr = self.tile_layer
        if lyr is None:
            return
        grid = self.geometry
        move = None
        if source.crs().isValid() and source.crs() != grid.crs:
            move = QgsCoordinateTransform(source.crs(), grid.crs,
                                          QgsProject.instance())
        # The filter off before the frames are read, as create_tile has it:
        # with one live, the frames it hides were neither recognised nor
        # kept clear of, and a new frame could take the id of a hidden one.
        if lyr.subsetString():
            lyr.setSubsetString("")
        # Every feature is a unit, read into a list; the loop that reads
        # them skips none, so none can go without a row in the log.
        rows = import_read_rows(source, move)
        frames = self.all_tiles()
        existing = import_existing(frames)
        side_m = self.tile_side.value()
        side_px = design_settings_side(side_m, grid.pixel_m[0]) \
            if grid.pixel_m[0] > 0 else 1
        # the number free_tile_id names, and one more for each frame after
        first = design_next_tile([self.free_tile_id()]) - 1
        inside = import_inside(self.panel.active_raster(), grid.crs)

        def planner(choice):
            reader = import_stratum_reader(choice.get("stratum_raster"),
                                           grid.crs)
            return design_plan(
                rows, existing,
                clash=import_clash(self, frames, grid.pixel_crs),
                inside=inside, settings_side_px=side_px,
                own_side=choice.get("own_side"), origin=grid.origin,
                pixel=grid.pixel_crs, mapping=choice.get("mapping"),
                stratum_of=reader, design_typed=choice.get("design_text"),
                first_tile=first)

        ask = ImportFrames(self, import_source_words(chosen, source, rows),
                           source.fields().names(), import_rasters(), side_m,
                           side_px, design_all_square(rows, grid.pixel_crs),
                           planner, can_own_side=design_has_polygons(rows),
                           many=len(rows) > DESIGN_MANY)
        if not run_dialog(ask):
            return
        choice = ask.result()
        decisions = planner(choice)
        name = design_source_name(chosen)
        if not design_import_count(decisions):
            QMessageBox.information(
                self, NAME, "Nothing in %s would become a new frame, so "
                "nothing was imported and nothing was written." % name)
            return

        import_add_columns(lyr)
        index = {field: lyr.fields().indexOf(field) for field in DESIGN_FIELDS}
        by_tile = {str(f["tile_id"]): f for f in frames}
        if not lyr.isEditable():
            lyr.startEditing()
        lyr.beginEditCommand("import frames")
        added = []
        for d in decisions:
            values = d.get("values") or {}
            if d["outcome"] == "added":
                new = QgsFeature(lyr.fields())
                new.setGeometry(QgsGeometry.fromRect(QgsRectangle(*d["frame"])))
                new["tile_id"] = d["tile_id"]
                new["side_m"] = float(d["frame_side_px"] * grid.pixel_m[0])
                sample = values.get("sample_id")
                new["note"] = "sample %s" % sample if sample else "imported"
                new["created"] = now()
                new["closed"] = 0
                for field, i in index.items():
                    if i >= 0 and values.get(field) is not None:
                        new.setAttribute(i, values[field])
                if lyr.addFeature(new):
                    added.append((d, new))
                else:
                    d["outcome"] = "not_written"
                    d["reasons"] = ["the layer refused the frame"]
                    d["reason"] = d["reasons"][0]
                    d["tile_id"] = ""
            elif d["outcome"] == "completed":
                there = by_tile.get(d["tile_id"])
                for field, i in index.items():
                    if there is not None and i >= 0 \
                            and values.get(field) is not None:
                        lyr.changeAttributeValue(there.id(), i, values[field])
        lyr.endEditCommand()

        folder = self.campaign.folder
        log_path = design_log_path(folder)
        import_id = design_import_id()
        when = now()
        operator = design_operator(self)
        crs = design_crs_of(self)
        complain = (lambda text: design_say(text, loud=True))
        if not lyr.commitChanges():
            said = list(lyr.commitErrors())
            errors = "; ".join(said[:3])
            log("the frames could not be written: %s" % errors)
            with own_hands():
                lyr.rollBack()
            lyr.startEditing()
            self.panel.keep_safe()
            self.refresh_tiles()
            first_error = said[0] if said else "unknown"
            design_append_log(log_path, design_log_rows(
                design_not_written(decisions, first_error), import_id, when,
                operator, name, crs), complain)
            QMessageBox.critical(
                self, NAME,
                "The frames could not be written to the package.\n\n%s\n\n"
                "Nothing was added. Every feature of %s is in "
                "design_log.csv as not written. If another program is "
                "holding the package open, close it and import again."
                % (errors, name))
            return
        lyr.startEditing()
        self.panel.keep_safe()
        lyr.triggerRepaint()

        # On disk: now the log and the manifest say so, and whoever listens
        # hears of every frame added.
        design_append_log(log_path, design_log_rows(
            decisions, import_id, when, operator, name, crs), complain)
        counts = design_summary(decisions)
        full = choice.get("design_text") or "; ".join(sorted({
            d["design_full"] for d in decisions if d.get("design_full")}))
        self.campaign.data.setdefault("designs", []).append(
            design_manifest_entry(import_id, when, operator,
                                  beside_folder(chosen, self.campaign.folder),
                                  source.crs().authid()
                                  if source.crs().isValid() else "",
                                  choice.get("words") or {}, full,
                                  choice.get("own_side"), side_px, counts))
        try:
            self.campaign.save()
        except OSError as err:
            log("the manifest could not say which design was imported: %s"
                % err, loud=True)
        for d, f in added:
            self.frame_event("import", d["tile_id"], None, d["frame"], f)
        self.refresh_tiles()
        QMessageBox.information(self, NAME, design_done_text(decisions, name))
        log("frames imported from %s: %s" % (name, ", ".join(
            "%s %d" % (k, v) for k, v in counts.items() if v)))

    def repair(self):
        """Overlaps left by editing vertices by hand, resolved.

        The smallest polygon keeps the ground it shares, because the small one
        is the deliberate detail and the large one is the background it was
        drawn on top of. The holes that opened are counted but not filled:
        filling them would be a guess.

        Then the polygons of one class and one reading that touch each other,
        which a campaign drawn before they were merged on the spot is full of,
        become one polygon each. Same command, so one Undo takes back all of
        it, and it changes no pixel, only how many polygons there are."""
        if self.marks_locked():
            return
        lyr = self.polygons
        if lyr is None:
            return
        if not lyr.isEditable():
            lyr.startEditing()
        lyr.beginEditCommand("repair overlaps")
        claimed, fixed, lost, untangled, stuck = None, 0, 0, 0, 0
        merged = 0
        try:
            # Outlines that cross themselves first, and written back. Nothing
            # below can be computed against a bow tie: every cut fails, and
            # Repair would fail on exactly the polygons it was pressed for,
            # then say "0 overlaps resolved".
            for f in self.scope_polygons():
                if self.untangle(lyr, f.id()):
                    untangled += 1
            here = sorted(self.scope_polygons(),
                          key=lambda f: f.geometry().area())
            if len(here) < 2 and not untangled:
                lyr.destroyEditCommand()
                iface.messageBar().pushMessage(NAME, "nothing to repair here",
                                               level=LEVEL_INFO, duration=2)
                return
            for f in here:
                g = f.geometry()
                if claimed is not None and g.intersects(claimed):
                    # Through cut_away, not raw: a GEOS failure on an
                    # untidy ring returns a null geometry whose area reads as
                    # nothing, and "nothing left" one line later means
                    # deleteFeature, and Repair would eat a polygon it could
                    # not cut.
                    rest = self.cut_away(g, claimed, f, quiet=True)
                    if rest is None:
                        # Counted and said, not recommended back to itself.
                        # Its ground is still claimed below, so the polygons
                        # after it are cut against it rather than through it.
                        stuck += 1
                        claimed = claimed.combine(g.makeValid())
                        continue
                    # The same tolerance Check uses, a hundredth of a pixel.
                    # It was the four pixel sliver threshold, so an overlap
                    # of two pixels was a PROBLEM in Check and "0 overlaps
                    # resolved" here, the two buttons contradicting each other.
                    px, py = self.geometry.pixel_crs
                    if abs(rest.area() - g.area()) > OVERLAP_SHARE * px * py:
                        pieces = self.geometry.leftovers(rest)
                        if not pieces:
                            lyr.deleteFeature(f.id())
                            lost += 1
                            continue
                        lyr.changeGeometry(f.id(), pieces[0])
                        for extra in pieces[1:]:
                            lyr.addFeature(self.piece_of(extra, f))
                        fixed += 1
                        g = QgsGeometry.unaryUnion(pieces)
                claimed = g if claimed is None else claimed.combine(g)
            merged = self.merge_joined(seeds=self.scope_polygons())
            lyr.endEditCommand()
        except Exception as err:
            lyr.destroyEditCommand()
            log("the repair was abandoned: %s" % err)
            return
        lyr.triggerRepaint()
        self.refresh_coverage()
        holes = 0.0
        tile = self.tile_geometry()
        if tile is not None and claimed is not None:
            holes = self.geometry.area(tile.difference(claimed))
        message = "%d overlaps resolved%s%s%s%s%s" % (
            fixed,
            ", %d self-crossing outline%s untangled"
            % (untangled, "" if untangled == 1 else "s") if untangled else "",
            ", %d polygons swallowed whole" % lost if lost else "",
            ", %d polygon%s of one class joined to a neighbour"
            % (merged, "" if merged == 1 else "s") if merged else "",
            ", %d could not be cut even repaired: undo the last vertex move"
            % stuck if stuck else "",
            ", %.2f m2 left unpainted" % holes if holes > 0.01 else "")
        worry = holes > 0.01 or stuck
        iface.messageBar().pushMessage(NAME, message,
                                       level=LEVEL_WARNING if worry else LEVEL_INFO,
                                       duration=8 if stuck else 5)
        log(message)
        time_mark(self, "repair", tool="button", note=message)
        self.ticked()

    def select_tile(self, tile_id):
        i = self.tiles.findData(tile_id)
        if i >= 0:
            self.tiles.setCurrentIndex(i)

    def tile_changed(self, *args):
        self.apply_filter()
        # Another frame, another set of polygons: what was remembered belongs
        # to the frame that was just left.
        self.remember_shapes()
        self.refresh_coverage()
        time_mark(self, "frame", tile_id=self.current_tile_id() or "")
        if self.tiled and self.lock_view.isChecked():
            self.go_to()

    def go_to(self):
        g = self.tile_geometry()
        if g is None:
            return
        box = g.boundingBox()
        view = canvas().mapSettings().destinationCrs()
        if view != self.geometry.crs:
            box = QgsCoordinateTransform(self.geometry.crs, view,
                                         QgsProject.instance()).transformBoundingBox(box)
        box.grow(max(box.width(), box.height()) * 0.15)
        canvas().setExtent(box)
        canvas().refresh()

    def zoom_to_raster(self):
        raster = self.panel.active_raster()
        if raster is None:
            log("no raster selected")
            return
        box = raster.extent()
        view = canvas().mapSettings().destinationCrs()
        if raster.crs() != view:
            box = QgsCoordinateTransform(raster.crs(), view,
                                         QgsProject.instance()).transformBoundingBox(box)
        canvas().setExtent(box)
        canvas().refresh()
        log("view brought back onto %s" % raster.name())

    def settle_view(self):
        """Never leave the operator staring at empty space: go to the current
        tile if there is one, otherwise onto the raster."""
        if self.tiled and self.current_tile_id() is not None:
            self.go_to()
            return
        raster = self.panel.active_raster()
        if raster is None:
            return
        view = canvas().mapSettings().destinationCrs()
        here = canvas().extent()
        there = raster.extent()
        if raster.crs() != view:
            there = QgsCoordinateTransform(raster.crs(), view,
                                           QgsProject.instance()).transformBoundingBox(there)
        if not here.intersects(there):
            log("the view was off the image: bringing it back")
            self.zoom_to_raster()

    def apply_filter(self, *args):
        """What is shown is decided by the renderer, never by a data filter.

        setSubsetString has no effect on a layer that is open for editing, and
        this one is open the whole time the brush is in your hand, so using it
        would mean writing to disk every time a checkbox is ticked. A rule
        based renderer filters an open layer and touches no file."""
        lyr = self.polygons
        if lyr is None:
            return
        clauses = []
        if self.by_operator.isChecked():
            # the expression mirrors tidy_operator() step for step: trim, then
            # upper, then the blank sentinel. If the renderer folded the case
            # differently from the brush, a polygon would be hidden in the view
            # and still be there under the stroke, which is the one failure
            # this whole arrangement exists to prevent
            clauses.append(
                "CASE WHEN coalesce(trim(\"operator\"), '') = '' THEN %s "
                "ELSE upper(trim(\"operator\")) END = %s"
                % (sql_text(self.OPERATOR_BLANK),
                   sql_text(self.operator_name())))
        if self.tiled and self.only_current.isChecked() and self.current_tile_id():
            # Quoted like the operator, not pasted between two apostrophes.
            # The frame names are ours ("t001"), but they are read back from a
            # GeoPackage anybody can open and edit by hand, and one name with
            # an apostrophe in it broke the whole expression: a broken filter
            # hides nothing, so a blind pass showed every earlier one.
            clauses.append("\"tile_id\" = %s" % sql_text(self.current_tile_id()))
        if self.hiding():
            # coalesce: a mark written before the field existed has none, and
            # it is pass 1 (campaign.pass_number); a plain equality would
            # hide it from the reader of pass 1
            clauses.append("coalesce(\"pass_no\", 1) = %d"
                           % self.pass_no.value())

        style_by_class(lyr, self.campaign.active_classes(), "polygon")
        self.filter_layer(self.layer("lines"), clauses, "line")
        self.filter_layer(self.layer("points"), clauses, "point")
        self.filter_layer(self.layer("boxes"), clauses, "box")
        if clauses:
            try:
                rules = QgsRuleBasedRenderer.convertFromRenderer(lyr.renderer())
                joined = " AND ".join(clauses)
                for child in rules.rootRule().children():
                    old = child.filterExpression()
                    child.setFilterExpression(
                        "(%s) AND %s" % (old, joined) if old else joined)
                lyr.setRenderer(rules)
            except Exception as err:
                log("cannot filter the view: %s" % err)
        if lyr.subsetString():
            log("a data filter was left over from an older version: cleared")
            if lyr.isEditable():
                lyr.commitChanges()
                self.panel.keep_safe()
            lyr.setSubsetString("")
        lyr.triggerRepaint()
        try:
            iface.layerTreeView().refreshLayerSymbology(lyr.id())
        except Exception:
            pass
        self.show_blind()

    def filter_layer(self, lyr, clauses, how):
        """The same clauses, on a table that is not the polygons.

        They apply to every table, not to the polygons alone: a blind second
        pass that hid the polygons of the first and left its points and its
        lines in plain sight would not be blind at all. A table that lacks a
        field named in a clause is left alone rather than filtered on
        nothing."""
        if lyr is None:
            return
        have = {f.name().lower() for f in lyr.fields()}
        # a clause names its fields between double quotes; one that asks for a
        # column this table has not got is dropped rather than applied, because
        # a broken expression in QGIS filters nothing at all and would show
        # everything at the moment when something must be hidden
        # The quoted values are taken out before the field names are looked
        # for: a frame or an operator name with a double quote in it would
        # otherwise read as a field this table has not got, and the clause
        # that hides it would be dropped.
        usable = [c for c in clauses
                  if all(name.lower() in have
                         for name in re.findall(
                             r'"([^"]+)"', re.sub(r"'(?:[^']|'')*'", "''", c)))]
        style_by_class(lyr, self.campaign.active_classes(), how,
                       pixel_in_layer_units(self.campaign)
                       if how == "point" else None)
        if not usable:
            lyr.triggerRepaint()
            return
        try:
            rules = QgsRuleBasedRenderer.convertFromRenderer(lyr.renderer())
            joined = " AND ".join(usable)
            for child in rules.rootRule().children():
                old = child.filterExpression()
                child.setFilterExpression(
                    "(%s) AND %s" % (old, joined) if old else joined)
            lyr.setRenderer(rules)
        except Exception as err:
            log("cannot filter %s: %s" % (lyr.name(), err))
        lyr.triggerRepaint()

    def hiding(self):
        """Whether only the pass being drawn is shown (the blind switch),
        whichever pass that is: pass 1 hides pass 2 as pass 2 hides pass 1."""
        return bool(self.blind.isChecked())

    def other_passes(self):
        """The other passes this operator has, which blind hides."""
        return [n for n in self.pass_no.values()
                if n != self.pass_no.value()]

    def show_blind(self):
        """The amber strip. Pass and operator both speak from here, so that
        neither can overwrite what the other had to say."""
        lines = []
        # Who is drawing, in a campaign read by more than one person or in
        # more than one pass. The box that says it is folded under Settings,
        # and a reading nobody can see is how a second reader came to draw
        # as the first one.
        several = getattr(self.panel, "several_readers", None)
        try:
            several = bool(callable(several) and several())
        except Exception:
            several = False
        if several:
            lines.append(
                "<b>DRAWING AS %s, PASS %d.</b> Every mark is filed under "
                "this reading. Settings changes it."
                % (escape(self.operator_name()), self.pass_no.value()))
        others = self.other_passes() if self.hiding() else []
        if others:
            lines.append(
                "<b>PASS %d, DRAWING BLIND.</b> Only this pass is shown. %s. "
                "What you draw now is a new reading. Turn off \"%s\" under "
                "Settings if you meant to see %s."
                % (self.pass_no.value(), pass_words(others),
                   BLIND_WORDS, "it" if len(others) == 1 else "them"))
        veil = getattr(self.panel, "veil_reports", None)
        try:
            veiled = veil((self.operator_name(), self.pass_no.value()),
                          self.by_operator.isChecked(),
                          self.blind.isChecked()) if callable(veil) else 0
        except Exception as err:
            log("cannot switch off the measures hidden from you: %s" % err)
            veiled = 0
        if veiled:
            lines.append("Measures that show work hidden from you are "
                         "switched off.")
        n_other, names = self.others_here()
        if n_other:
            lines.append(
                "<b>OPERATOR: %s.</b> This frame holds %d polygon%s by %s that "
                "you cannot see and that stay untouched. Draw as if the frame "
                "were empty: that is exactly what makes the two readings "
                "comparable."
                % (self.operator_name(), n_other,
                   "" if n_other == 1 else "s", " and ".join(names)))
        if not lines:
            self.blind_note.setVisible(False)
            return
        colours = palette_colours()
        self.blind_note.setStyleSheet(
            "background:%s; color:%s; border-radius:3px; padding:4px;"
            % ("#5a4a14" if colours["dark"] else "#fdf3cf",
               colours["text"]))
        self.blind_note.setText("<br><br>".join(lines))
        self.blind_note.setVisible(True)

    def held_reading(self):
        """The reading the panel holds for the campaign: operator, pass and
        blind switch. None from a panel that holds none."""
        ask = getattr(self.panel, "reading", None)
        try:
            return ask() if callable(ask) else None
        except Exception as err:
            log("cannot read the reading the panel holds: %s" % err)
            return None

    def hand_back_reading(self):
        """Give the panel the reading as it is now set here, so that it
        outlives this module: the next Annotate, and Objects, draw as the
        same person in the same pass, and the campaign remembers it."""
        hold = getattr(self.panel, "hold_reading", None)
        if not callable(hold):
            return
        try:
            hold(self.operator_name(), int(self.pass_no.value()),
                 self.blind.isChecked(), self.by_operator.isChecked())
        except Exception as err:
            log("cannot hand the reading to the panel: %s" % err)

    def blind_changed(self, *args):
        self.hand_back_reading()
        self.apply_filter()

    def operator_changed(self, *args):
        """Changing the name changes the visible world, so it is said out loud.

        The danger to avoid is silence: somebody opens a tile of their own with
        the other name still in the box, finds it empty, and draws it again from
        scratch believing they never did it."""
        # the passes are the new operator's: one who has no pass 2 starts in
        # pass 1, not in the pass the last operator was in
        self.refill_passes()
        self.hand_back_reading()
        self.apply_filter()
        self.refresh_coverage()
        n_other, names = self.others_here()
        mine = len(self.scope_polygons())
        iface.messageBar().pushMessage(
            NAME,
            "operator '%s': %d polygon%s of yours in view%s"
            % (self.operator_name(), mine, "" if mine == 1 else "s",
               ", %d by %s hidden" % (n_other, " and ".join(names))
               if n_other else ""),
            level=LEVEL_INFO, duration=5)
        log("operator '%s': %d visible, %d hidden"
            % (self.operator_name(), mine, n_other))
        time_mark(self, "reading")

    def pass_changed(self, *args):
        if self.pass_no.value() > 1 and not self.blind.isChecked():
            self.blind.blockSignals(True)
            self.blind.setChecked(True)
            self.blind.blockSignals(False)
            log("pass %d: the other passes are hidden" % self.pass_no.value())
        self.hand_back_reading()
        self.apply_filter()
        self.refresh_coverage()
        time_mark(self, "reading")

    # ----------------------------------------------------------- painting
    OPERATOR_BLANK = "UNNAMED"

    @staticmethod
    def tidy_operator(text):
        """The one place a person's name is put into its written form.

        Trimmed and upper cased, always, wherever it comes from: the box, the
        + dialog, the manifest, a polygon already in the package. Case is the
        trap this closes. "Massi" and "massi" are one person to anybody
        reading the panel and two different people to a string comparison, and
        the second of the two would open their own finished tiles and find
        them empty. Folding the case makes that impossible rather than
        unlikely, which is the difference that matters when the cost of the
        mistake is a morning of work drawn twice."""
        return (text or "").strip().upper()

    def operator_name(self):
        """Who is drawing, as it ends up written in the file."""
        return self.tidy_operator(self.operator.currentText()) or self.OPERATOR_BLANK

    @staticmethod
    def operator_of(feature):
        """The same normalisation, read off a feature. A polygon written before
        the field existed, or written with the box left empty, is "UNNAMED"
        here and "UNNAMED" in the renderer: it belongs to somebody, so it can
        still be found, instead of falling out of every view at once.

        Reading through the same upper casing is also what makes the names
        already in the package line up with the ones written from now on: a
        polygon saved as "Massi" months ago and one saved as "MASSI" today are
        the same person here, without anything in the file having to be
        rewritten."""
        try:
            v = feature["operator"]
        except (KeyError, IndexError):
            return AnnotationSection.OPERATOR_BLANK
        return ((v or "").strip().upper()
                or AnnotationSection.OPERATOR_BLANK)

    def reading_of(self, f):
        """Which partition a polygon belongs to: its frame, its pass and its
        operator, read off the polygon instead of the panel.

        The operator always, whether or not "one operator at a time" is
        ticked. That box decides what is on screen; it does not make two
        readings one. With it off and the operator left out, dragging OP1's
        border cut OP2's polygons, and OP2's ground stopped the strip OP1 had
        let go of from going back to OP1's own neighbour."""
        try:
            p = int(f["pass_no"] or 1)
        except (TypeError, ValueError, KeyError):
            p = 1
        return (f["tile_id"] if self.tiled else None, p, self.operator_of(f))

    def scope_polygons(self):
        """The polygons the drawing has to reckon with: same tile, same pass,
        same operator.

        The operator clause lives here and not only in the renderer, and that
        matters. Everything passes through this method: the brush, the merging
        of same class neighbours, the class swap on Ctrl click, the coverage,
        fill tile and plug holes. Hiding another operator's work from the eyes
        alone would leave the brush colliding with it: in "paint under" mode the
        stroke would be eaten by polygons nobody can see, and holes would appear
        for no visible reason. Filtered here, the tile is genuinely empty for
        whoever reopens it, which is what measuring agreement needs.

        The operations that must see everything, because they move or destroy
        the ground itself, use all_polygons()."""
        lyr = self.polygons
        if lyr is None:
            return []
        p = self.pass_no.value()
        tid = self.current_tile_id()
        mine = self.operator_name()
        by_op = self.by_operator.isChecked()
        out = []
        for f in lyr.getFeatures():
            if f["pass_no"] != p:
                continue
            if self.tiled and f["tile_id"] != tid:
                continue
            if by_op and self.operator_of(f) != mine:
                continue
            if f.geometry() is None or f.geometry().isEmpty():
                continue
            out.append(f)
        return out

    def all_polygons(self, tile_id=None):
        """Every polygon of a tile, whoever drew it and in whatever pass.

        For the places where the tile's own geometry moves or disappears: what
        you cannot see still has to be clipped and counted, otherwise it stays
        in the file dangling outside the border."""
        lyr = self.polygons
        if lyr is None:
            return []
        tid = self.current_tile_id() if tile_id is None else tile_id
        return [f for f in lyr.getFeatures()
                if (not self.tiled or f["tile_id"] == tid)
                and f.geometry() is not None and not f.geometry().isEmpty()]

    def others_here(self):
        """How many polygons of this tile the current operator cannot see.

        Not a courtesy detail: the confirmations before moving or deleting a
        tile destroy that work too, and destroying what nobody can see, in
        silence, is the one thing this filter must never cause."""
        if not self.by_operator.isChecked():
            return 0, []
        mine = self.operator_name()
        other = [f for f in self.all_polygons()
                 if self.operator_of(f) != mine]
        return len(other), sorted({self.operator_of(f) for f in other})

    def vertex_layer(self):
        """The table the vertex tool should be pointed at.

        Whichever shape is in hand: holding Line you mean the lines, holding
        Points the points, and otherwise the polygons. The tool works on the
        active layer and only on that, so picking the wrong one is how you
        end up dragging a corner of something you were not looking at."""
        if getattr(self, "b_line", None) is not None and self.b_line.isChecked():
            return self.layer("lines")
        if getattr(self, "b_points", None) is not None \
                and self.b_points.isChecked():
            return self.layer("points")
        return self.polygons

    def vertex_tool_action(self):
        """QGIS's own vertex tool, under whichever name this version has."""
        for name in ("actionVertexTool", "actionVertexToolActiveLayer",
                     "actionNodeTool"):
            action = getattr(iface, name, None)
            if action is None:
                continue
            try:
                got = action()
            except Exception:
                continue
            if got is not None:
                return got
        return None

    def vertex_mode_changed(self, on):
        """Hand the map to QGIS's vertex tool, and take it back.

        The tool is not ours and there is no reason it should be: snapping,
        adding and removing vertices, multi part geometries and the undo stack
        are all in it already, and it is the same tool every QGIS user has
        learned. What was missing was the way in. It took selecting the right
        layer in the Layers panel and then finding the tool in the digitising
        toolbar, two steps that are easy to get wrong and impossible to guess.

        What is ours is what happens after a vertex has moved, and that
        happens by itself: settle_edits makes the edited polygon win."""
        if getattr(self, "_vertex_switching", False):
            return
        if not on:
            self.back_from_vertices()
            return
        if self.marks_locked():
            self.hold_vertices(False)
            return
        lyr = self.vertex_layer()
        if lyr is None:
            iface.messageBar().pushMessage(
                NAME, "there is no layer to edit the corners of",
                level=LEVEL_WARNING, duration=4)
            self.hold_vertices(False)
            return
        action = self.vertex_tool_action()
        if action is None:
            iface.messageBar().pushMessage(
                NAME, "this QGIS does not offer its vertex tool from here: "
                      "take it from the Digitizing toolbar",
                level=LEVEL_WARNING, duration=7)
            self.hold_vertices(False)
            return
        try:
            iface.setActiveLayer(lyr)
        except Exception as err:
            log("cannot make %s the active layer: %s" % (lyr.name(), err))
        if not lyr.isEditable():
            lyr.startEditing()
        # How everything looks before a hand touches it. settle_edits compares
        # against this to tell a border pushed forward from one pulled back.
        self.remember_shapes()
        action.trigger()
        log("vertex tool on %s" % lyr.name(), loud=True)

    def hold_vertices(self, down):
        """Move the latch without setting it off again."""
        self._vertex_switching = True
        try:
            self.b_vertices.setChecked(bool(down))
        finally:
            self._vertex_switching = False

    def back_from_vertices(self):
        """Give the map back to whichever shape is in hand."""
        if self.b_line.isChecked():
            self.use_line_tool()
        elif getattr(self, "b_points", None) is not None \
                and self.b_points.isChecked():
            self.use_point_tool()
        elif self.tiled and self.b_tiles.isChecked():
            self.use_tile_tool()
        else:
            self.use_brush()

    def drop_vertices(self):
        """Taking any shape lets the vertex tool go.

        The latch is not in the group of tools, so nothing would pop it up on
        its own: it would stay down, saying the map belongs to the vertex tool
        while the brush had already taken it back."""
        b = getattr(self, "b_vertices", None)
        if b is not None and b.isChecked():
            self.hold_vertices(False)

    def can_move_frames(self):
        """Whether a drag moves a frame. Off unless Move is down."""
        b = getattr(self, "b_move", None)
        return bool(b is not None and b.isChecked())

    def move_mode_changed(self, on):
        """Turning dragging on and off, and saying so with the pointer.

        A frame that moves under the hand by accident is one of the few things
        here that cannot be undone by looking at it: the polygons inside keep
        their coordinates and quietly come to describe another patch of
        ground. So dragging is a mode you switch on, and while it is on the
        pointer is a hand, which is the one thing everybody already reads as
        "this can be dragged".

        Pressing it also takes the map. A switch and nothing more would leave
        the polygon in hand with the pointer a cross, a drag across a frame
        would draw a polygon, and the only way to find out that Move needed
        Tiles pressed first would be to read the tooltip. A button that says
        frames can be dragged puts the map in the state where they can."""
        if on and self.tiled and canvas().mapTool() is not self.tile_tool:
            # use_tile_tool presses Tiles, which releases whatever shape was
            # held: the two are in one exclusive group.
            self.use_tile_tool()
        if self.tile_tool is not None:
            self.tile_tool.show_mode()
        if on:
            iface.messageBar().pushMessage(
                NAME, "frames can be dragged: the pointer is a hand over one",
                level=LEVEL_INFO, duration=3)
        log("frame dragging %s" % ("on" if on else "off"))

    def under_lock_changed(self, closed):
        """The lock beside "paint under the others".

        Shut, the tick cannot be moved: the one setting that can quietly cost
        an hour of drawing is not one to knock with an elbow. Open it and it
        behaves like any other box.

        Shift still inverts the mode for a single stroke whatever the lock
        says, and that is on purpose: a key held down while the hand draws is
        a deliberate act with an end to it, not a setting left the wrong way
        round."""
        self.paint_under.setEnabled(not closed)
        self.under_lock.setIcon(padlock_icon(closed))
        self.under_lock.setToolTip(
            ("Shut: 'paint under the others' cannot be changed by accident.\n"
             "Click to open it.\n\nShift still inverts it for one stroke."
             ) if closed else
            ("Open: the tick can be changed.\n"
             "Click to lock it where it is."))

    def under_mode(self):
        base = self.paint_under.isChecked()
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            base = not base
        return base

    def new_feature(self, geom, class_name):
        lyr = self.polygons
        f = QgsFeature(lyr.fields())
        f.setGeometry(geom)
        f["class_name"] = class_name
        f["class_code"] = self.code_of(class_name)
        f["tile_id"] = self.current_tile_id()
        f["pass_no"] = self.pass_no.value()
        f["operator"] = self.operator_name()
        f["created"] = now()
        return f

    def piece_of(self, geom, parent):
        """A piece split off a polygon that already exists: it keeps the
        reading it came from.

        new_feature() stamps the frame, the pass and the operator in hand,
        which is right for something drawn now and wrong for the leftover of a
        cut, a lobe of an untangled bow tie or the ground a neighbour took. With
        "one operator at a time" off, or a vertex dragged in another frame, the
        parent belongs to another reading, and its piece must not be filed
        under the one in hand: that would quietly rename another operator's
        work."""
        lyr = self.polygons
        f = QgsFeature(lyr.fields())
        f.setGeometry(geom)
        for name in ("class_name", "class_code", "tile_id", "pass_no",
                     "operator"):
            try:
                f[name] = parent[name]
            except (KeyError, IndexError):
                pass
        # the code from the legend, as new_feature() does, when the legend knows
        # the name: a parent carrying a stale code should not hand it on
        known = self.code_of(f["class_name"]) if f["class_name"] else 0
        if known:
            f["class_code"] = known
        f["created"] = now()
        return f

    def code_of(self, class_name):
        for c in self.campaign.data["classes"]:
            if c["name"] == class_name:
                return c["code"]
        return 0

    def cut_away(self, geom, union, feature=None, quiet=False):
        """geom minus union, or None when the machine could not work it out.

        QgsGeometry.difference does not raise when GEOS trips over a ring that
        touches itself: it hands back a null geometry, which reads exactly
        like "nothing left" and would be acted on as such. A background
        polygon holding ten thousand pixels would be deleted whole by a five
        pixel dab in its corner, silently, because one of its rings is untidy.

        So: try, and if it fails try again with BOTH sides repaired, and if it
        fails again leave the polygon alone and say so.

        Both sides, because the broken one may be the cutter, a polygon whose
        vertex was dragged across its own edge into a bow tie: repairing only
        the polygon being cut would change nothing and the retry would fail
        exactly as the first attempt did. The message would then say "press
        Repair", Repair would go through this same function, fail the same
        way, print the same advice from inside itself, and report "0 overlaps
        resolved". A loop with no way out, and a message pointing at the door
        to it.

        quiet is for Repair, which counts the failures and reports them itself
        rather than recommending itself."""
        cut = geom.difference(union)
        if cut is not None and not cut.isNull():
            return cut
        try:
            cut = geom.makeValid().difference(union.makeValid())
        except Exception:
            cut = None
        if cut is not None and not cut.isNull():
            return cut
        if quiet:
            return None
        who = ""
        if feature is not None:
            try:
                who = " of %s" % feature["class_name"]
            except Exception:
                who = ""
        log("a polygon%s could not be cut and was left as it is: press Repair, "
            "which untangles self-crossing outlines first" % who, loud=True)
        return None

    def untangle(self, lyr, fid):
        """An outline that crosses itself, written back as what it encloses.

        QGIS's vertex tool lets a vertex be dragged across an edge of its own
        polygon. What comes out is a bow tie: a ring that crosses itself, which
        GEOS refuses to do arithmetic with. Every later cut against it fails,
        the brush can no longer settle anything it touches, and the file keeps
        a shape no GIS will call valid.

        Repairing it in a local variable, to trim the neighbours with the
        repaired copy, would leave the broken one in the layer: the bow tie
        would stay, and every stroke near it would fail again. So the repaired
        shape is what gets written: the two lobes of a bow tie become
        two polygons of the same class. A lobe of any size stays: it was part
        of the polygon, and dropping a small one would leave a hole that Fill
        Gap could not see.

        Returns how many polygons now stand where the broken one stood, or 0
        when it was not broken or there is nothing sensible to put back."""
        f = lyr.getFeature(fid)
        if f is None or not f.isValid():
            return 0
        g = f.geometry()
        if g is None or g.isEmpty():
            return 0
        try:
            if g.isGeosValid():
                return 0
        except Exception:
            pass
        pieces = self.geometry.leftovers(g.makeValid())
        if not pieces:
            log("a %s outline crosses itself and nothing of it could be kept: "
                "it was left as it is" % f["class_name"], loud=True)
            return 0
        lyr.changeGeometry(fid, pieces[0])
        for extra in pieces[1:]:
            lyr.addFeature(self.piece_of(extra, f))
        log("a %s outline crossed itself: untangled into %d polygon%s"
            % (f["class_name"], len(pieces), "" if len(pieces) == 1 else "s"))
        return len(pieces)

    # One switch for the whole behaviour, so a test can compare a campaign
    # drawn with it and without it. The author chose merging, so there is no
    # setting for it.
    merging = True

    @staticmethod
    def draw_rank(fid):
        """Where a polygon stands in the order it is burned in. A mask burns the
        table in the order of its ids and the last one has the final word where
        two readings overlap; a polygon not yet saved has a negative id and is
        written after every saved one, in the order it was made."""
        return (0, fid) if fid >= 0 else (1, -fid)

    def rows_near(self, bb, reach=0.0):
        """The polygons of the table whose box meets this one, saved or not,
        whatever their reading. Through the table's own index (the filter
        rectangle), so a stroke in a frame of a few hundred polygons asks about
        the handful beside it and not about all of them."""
        lyr = self.polygons
        rect = QgsRectangle(bb.xMinimum() - reach, bb.yMinimum() - reach,
                            bb.xMaximum() + reach, bb.yMaximum() + reach)
        out = []
        for f in lyr.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
            g = f.geometry()
            if g is None or g.isEmpty() or not g.boundingBox().intersects(rect):
                continue
            out.append(f)
        return out

    def add_piece(self, geom, class_name):
        self.polygons.addFeature(self.new_feature(geom, class_name))

    def add_merging(self, geom, class_name):
        """A new piece of ground, joined to the polygons of its class and
        reading that it meets."""
        self.add_piece(geom, class_name)
        self.merge_joined(region=geom)

    def merge_joined(self, region=None, seeds=None):
        """Polygons of one class, one reading and one frame that overlap or
        share a border become one polygon. Returns how many polygons went into
        another.

        Called inside the edit command of the stroke, the vertex move or the
        repair that made them meet, so one Undo puts back what stood there
        before. It starts from the polygons that meet the region (or from the
        seeds, given) and follows the neighbours from there; a polygon of
        another reading, class or frame is never a candidate, which is what
        keeps a blind pass and a second operator out of it.

        This only changes how many polygons there are, never which pixel
        centres fall in a class, so every product burned from the table is the
        same with and without it. Three things keep that true:

        - the union must be ONE valid polygon. Two polygons that meet at a
          corner stay two, because their union is a multipolygon;
        - the polygon that stays has the id of one of the parts, chosen so that
          no polygon of another reading lying over the same ground changes
          sides in "where two readings overlap, the one drawn last wins". When
          no part can stand for the others without that, they stay separate;
        - the attributes are the same on every part (they were grouped by
          them), except the date of creation, which becomes the earliest.
          The table holds nothing else: no note and no confidence."""
        if not self.merging:
            return 0
        lyr = self.polygons
        if lyr is None:
            return 0
        px, py = self.geometry.pixel_crs
        dust = OVERLAP_SHARE * px * py
        if seeds is None:
            if region is None or region.isEmpty():
                return 0
            reach = merge_reach(self.geometry, region)
            seeds = [f for f in self.rows_near(region.boundingBox(), reach)
                     if within_reach(f.geometry(), region, reach)]
        merged = 0
        done = set()
        for seed in seeds:
            if seed.id() in done:
                continue
            fresh = lyr.getFeature(seed.id())
            if fresh is None or not fresh.isValid():
                continue                    # merged away a moment ago
            members = self._joined_with(fresh, px, py)
            done.update(m.id() for m in members)
            if len(members) < 2:
                continue
            merged += self._merge_group(members, dust)
        return merged

    def _joined_with(self, start, px, py):
        """start and every polygon of its class and reading that can be reached
        from it by overlapping or sharing a border."""
        key = (start["class_name"], self.reading_of(start))
        found = {start.id(): start}
        todo = [start]
        while todo:
            here = todo.pop()
            hg = here.geometry()
            try:
                if not hg.isGeosValid():
                    continue
            except Exception:
                continue
            reach = merge_reach(self.geometry, hg)
            for other in self.rows_near(hg.boundingBox(), reach):
                if other.id() in found:
                    continue
                if (other["class_name"], self.reading_of(other)) != key:
                    continue
                og = other.geometry()
                try:
                    if not og.isGeosValid():
                        continue
                except Exception:
                    continue
                if joint_of(hg, og, px, py):
                    found[other.id()] = other
                    todo.append(other)
        return list(found.values())

    def _merge_group(self, members, dust):
        """Make these polygons one, or leave them as they are. Returns how many
        were taken in."""
        lyr = self.polygons
        union = QgsGeometry.unaryUnion([m.geometry() for m in members])
        pieces = self.geometry.leftovers(union) if union is not None else []
        if len(pieces) != 1:
            return 0                        # not one polygon: leave them
        ids = {m.id() for m in members}
        # who else lies over this ground, and over which of the parts
        over = []
        reach = merge_reach(self.geometry, union)
        for x in self.rows_near(union.boundingBox(), reach):
            if x.id() in ids:
                continue
            xg = x.geometry()
            hit = []
            for i, m in enumerate(members):
                try:
                    both = m.geometry().intersection(xg)
                    if both is not None and not both.isEmpty() \
                            and both.area() > dust:
                        hit.append(i)
                except Exception:
                    continue
            if hit:
                over.append((self.draw_rank(x.id()), hit))
        order = sorted(members, key=lambda m: self.draw_rank(m.id()))
        keeper = None
        for cand in order:
            rank = self.draw_rank(cand.id())
            if all((xr > rank) == (xr > self.draw_rank(members[i].id()))
                   for xr, hit in over for i in hit):
                keeper = cand
                break
        if keeper is None:
            return 0
        # the earliest date of creation any part carries
        dates = [m["created"] for m in members if m["created"]]
        first = min(dates) if dates else None
        lyr.changeGeometry(keeper.id(), pieces[0])
        if first and keeper["created"] != first:
            lyr.changeAttributeValue(
                keeper.id(), lyr.fields().indexOf("created"), first)
        lyr.deleteFeatures([m.id() for m in members if m.id() != keeper.id()])
        return len(members) - 1

    def paint(self, geom, class_name=None, under=None):
        if self.marks_locked():
            return
        drawn = geom
        if self.class_name is None:
            return
        lyr = self.table_back("polygons")
        if lyr is None or (self.tiled and self.table_back("tiles") is None):
            return
        class_name = class_name or self.class_name
        under = self.under_mode() if under is None else under

        if self.tiled:
            tile = self.tile_geometry()
            if tile is None:
                iface.messageBar().pushMessage(NAME, "no tile selected",
                                               level=LEVEL_WARNING, duration=3)
                return
            geom = geom.makeValid().intersection(tile)
        else:
            geom = geom.makeValid()

        others = [f for f in self.scope_polygons() if f["class_name"] != class_name]
        if under and others:
            kept = self.cut_away(
                geom, QgsGeometry.unaryUnion([f.geometry() for f in others]))
            if kept is None:
                # A failed cut is not an empty one. Read raw, the null geometry
                # came back as "already painted: nothing left to fill", and the
                # stroke went in the bin wearing the wrong explanation.
                iface.messageBar().pushMessage(
                    NAME, "this stroke could not be fitted under what is "
                          "already there: nothing painted. Press Repair, or "
                          "draw it in two shorter strokes",
                    level=LEVEL_WARNING, duration=7)
                return
            geom = kept

        pieces = self.geometry.parts(geom)
        if not pieces:
            if under:
                msg = "already painted: nothing left to fill"
            elif geom.isEmpty():
                msg = ("nothing painted: the stroke fell outside the tile"
                       if self.tiled else "nothing painted: the stroke is empty")
            else:
                msg = ("nothing painted: %.4f square units, below the %.4f that "
                       "four pixels take" % (geom.area(), self.geometry.min_area_flat))
            iface.messageBar().pushMessage(NAME, msg, level=LEVEL_WARNING, duration=4)
            log(msg)
            return

        if not lyr.isEditable():
            lyr.startEditing()
        lyr.beginEditCommand("%s %s" % ("fill" if under else "stroke", class_name))
        try:
            if not under:
                union = QgsGeometry.unaryUnion(pieces)
                for f in self.scope_polygons():
                    fg = f.geometry()
                    if not fg.intersects(union):
                        continue
                    cut = self.cut_away(fg, union, f)
                    if cut is None:
                        continue
                    # Everything the stroke leaves of it stays, a fleck of a
                    # pixel too: it is ground that had a class a moment ago,
                    # and a frame marked closed counts on it. Dropped, it
                    # would be a hole that Fill Gap answered "no holes" to.
                    rest = self.geometry.leftovers(cut)
                    if not rest:
                        lyr.deleteFeature(f.id())
                        continue
                    lyr.changeGeometry(f.id(), rest[0])
                    for extra in rest[1:]:
                        lyr.addFeature(self.piece_of(extra, f))
            for piece in pieces:
                self.add_piece(piece, class_name)
            # in the same command, so one Undo takes the stroke and the
            # merging back together
            merged = self.merge_joined(region=QgsGeometry.unaryUnion(pieces))
            lyr.endEditCommand()
        except Exception as err:
            lyr.destroyEditCommand()
            log("error while painting: %s" % err)
            return
        lyr.triggerRepaint()
        try:
            iface.layerTreeView().refreshLayerSymbology(lyr.id())
        except Exception:
            pass
        self.refresh_coverage()
        area = sum(self.geometry.area(x) for x in pieces)
        if not getattr(self, "quiet_note", False):
            x, y = time_centre(geom)
            time_mark(self, "under" if under else "stroke",
                      class_code=self.code_of(class_name), area_m2=area,
                      n_vertices=time_vertices(drawn), x=x, y=y,
                      note=", ".join(
                          (["under"] if under else [])
                          + (["merged %d" % merged] if merged else [])))
        self.ticked()
        log("%s %s: %d piece%s, %.2f m2%s"
            % ("filled under" if under else "painted", class_name, len(pieces),
               "" if len(pieces) == 1 else "s", area,
               ", %d joined to neighbours" % merged if merged else ""))

    def close_holes(self):
        if self.marks_locked():
            return
        tile = self.tile_geometry()
        if tile is None:
            return
        existing = [f.geometry() for f in self.scope_polygons()]
        rest = tile if not existing \
            else tile.difference(QgsGeometry.unaryUnion(existing))
        parts = self.geometry.leftovers(rest)
        if not parts:
            iface.messageBar().pushMessage(NAME, "no holes", level=LEVEL_INFO, duration=2)
            return
        total = sum(self.geometry.area(p) for p in parts)
        q = QMessageBox.question(
            self, "Fill Gap",
            ("The frame is empty: all of it, %.2f m2, becomes '%s'.\n\n"
             "Proceed?" % (total, self.class_name)) if not existing else
            ("%d unpainted area%s, %.2f m2 in all.\nAssign them to '%s'?"
             % (len(parts), "" if len(parts) == 1 else "s", total,
                self.class_name)))
        if q != QMessageBox.StandardButton.Yes:
            return
        lyr = self.polygons
        if not lyr.isEditable():
            lyr.startEditing()
        lyr.beginEditCommand("fill gaps")
        for piece in parts:
            self.add_piece(piece, self.class_name)
        merged = self.merge_joined(region=QgsGeometry.unaryUnion(parts))
        lyr.endEditCommand()
        lyr.triggerRepaint()
        self.refresh_coverage()
        x, y = time_centre(tile)
        time_mark(self, "fill_gaps", tool="button",
                  class_code=self.current_code(), area_m2=total, x=x, y=y,
                  note="%d piece%s%s" % (
                      len(parts), "" if len(parts) == 1 else "s",
                      ", merged %d" % merged if merged else ""))
        self.ticked()

    # ----------------------------------------------------------- points
    def point_reach(self):
        """How close a click has to be to count as being on a point, measured
        on screen so it is the same at every zoom."""
        return HANDLE_PX * canvas().mapUnitsPerPixel()

    def point_at(self, point):
        layer = self.layer("points")
        if layer is None:
            return None
        reach = self.point_reach()
        box = QgsRectangle(point.x() - reach, point.y() - reach,
                           point.x() + reach, point.y() + reach)
        nearest, best = None, None
        for f in layer.getFeatures(QgsFeatureRequest().setFilterRect(box)):
            if not f.hasGeometry():
                continue
            d = f.geometry().distance(QgsGeometry.fromPointXY(point))
            if best is None or d < best:
                nearest, best = f, d
        return nearest

    def drop_point(self, point):
        """One point of the current class where the click landed.

        In a tiled campaign a point belongs to the frame in the list, like a
        stroke and a line do, and it is refused anywhere else. Going down
        wherever the click was, and looking up afterwards which frame it
        happened to be in, would write a point outside every frame with no
        frame at all, and burn its footprint into the mask on ground that no
        frame ever covered. A campaign drawn without frames is the one for
        points anywhere."""
        if self.marks_locked():
            return
        if self.class_name is None:
            return
        layer = self.table_back("points")
        if layer is None or (self.tiled
                             and self.table_back("tiles") is None):
            return
        tile_id = ""
        if self.tiled:
            tile = self.tile_geometry()
            if tile is None:
                iface.messageBar().pushMessage(NAME, "no tile selected",
                                               level=LEVEL_WARNING, duration=3)
                return
            refused = self.point_refusal(point, tile, self.point_size())
            if refused:
                iface.messageBar().pushMessage(NAME, refused,
                                               level=LEVEL_WARNING, duration=4)
                log(refused)
                return
            tile_id = self.current_tile_id()
        if not layer.isEditable():
            layer.startEditing()
        layer.beginEditCommand("point %s" % self.class_name)
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(point))
        f["class_name"] = self.class_name
        f["class_code"] = self.current_code()
        f["tile_id"] = tile_id
        f["operator"] = self.panel.who_is_drawing()
        if "pass_no" in layer.fields().names():
            f["pass_no"] = self.panel.which_pass()
        if "size_px" in layer.fields().names():
            f["size_px"] = self.point_size()
        if "conf" in layer.fields().names():
            f["conf"] = "low" if self.uncertain.isChecked() else "high"
        f["created"] = now()
        layer.addFeature(f)
        layer.endEditCommand()
        layer.triggerRepaint()
        self.refresh_coverage()
        time_mark(self, "point", class_code=self.current_code(), x=point.x(),
                  y=point.y())
        self.ticked()

    def remove_point_at(self, point):
        if self.marks_locked():
            return
        hit = self.point_at(point)
        if hit is None:
            iface.messageBar().pushMessage(
                NAME, "no point under the cursor", level=LEVEL_INFO, duration=2)
            return
        layer = self.layer("points")
        if not layer.isEditable():
            layer.startEditing()
        layer.beginEditCommand("remove point")
        layer.deleteFeature(hit.id())
        layer.endEditCommand()
        layer.triggerRepaint()
        self.refresh_coverage()
        time_mark(self, "point_remove", class_code=hit["class_code"],
                  x=point.x(), y=point.y())
        self.ticked()

    def reclass_point_at(self, point):
        if self.marks_locked():
            return
        hit = self.point_at(point)
        if hit is None or self.class_name is None:
            return
        layer = self.layer("points")
        if not layer.isEditable():
            layer.startEditing()
        layer.beginEditCommand("reclass point")
        fields = layer.fields()
        for name, value in (("class_name", self.class_name),
                            ("class_code", self.current_code())):
            index = fields.indexOf(name)
            if index >= 0:
                layer.changeAttributeValue(hit.id(), index, value)
        layer.endEditCommand()
        layer.triggerRepaint()
        self.refresh_coverage()
        time_mark(self, "point_reclass", class_code=self.current_code(),
                  from_code=hit["class_code"], x=point.x(), y=point.y())
        self.ticked()

    def point_refusal(self, point, frame, n):
        """Why a point of footprint n cannot go here, or None when it can.

        Two reasons, said apart because they are mended differently. A click
        outside the frame is the same refusal a line gets, in the same words.
        A click inside it, close enough to the edge that the square of pixels
        the point stands for would reach past it, is refused too: the export
        burns the whole square, so the part across the edge would label ground
        outside the frame, which a stroke there can never do because it is
        clipped. Click further in, or take a smaller footprint."""
        here = QgsGeometry.fromPointXY(point)
        if not frame.intersects(here):
            msg = "nothing drawn: the point fell outside the tile"
            other = self.tile_at(point)
            if other is not None:
                msg += (" (it is in %s: pick that frame in the list to draw "
                        "there)" % other["tile_id"])
            return msg
        if not self.geometry.point_fits(frame, point, n):
            half = int(n) // 2
            if half == 0:
                # on the right or bottom edge itself: the pixel a click there
                # labels is the first one beyond the frame
                return ("nothing drawn: the point fell outside the tile, on "
                        "its edge, where the pixel it labels is the one "
                        "beyond")
            # Said in the same terms as the README: the room the square
            # needs between the pixel clicked and the frame edge, four pixels
            # for a 9 x 9.
            return ("nothing drawn: the point's %d x %d footprint would reach "
                    "past the edge of the tile. It needs %d pixel%s of room "
                    "between the pixel clicked and the edge: click further "
                    "in, or pick a smaller point size"
                    % (n, n, half, "" if half == 1 else "s"))
        return None

    @staticmethod
    def point_size_of(feature):
        """The footprint a point was dropped with; 1 for a point written before
        the field existed, which is what it meant then."""
        try:
            return max(1, int(feature["size_px"] or 1))
        except (KeyError, IndexError, TypeError, ValueError):
            return 1

    def watch_point_moves(self):
        """Listen for points moved by hand, with the QGIS vertex tool.

        Dropping a point goes through drop_point and is kept inside its frame
        there. The vertex tool writes straight into the table, so without this
        a point could be dropped where it is allowed and then dragged out of
        its frame, which is the same point outside a frame by another road."""
        lyr = self.layer("points")
        if lyr is None or getattr(self, "_watching_points", None) is lyr:
            return
        try:
            hook(self, lyr.geometryChanged,
                 shielded(self.note_point_move, "Point move"))
        except Exception as err:
            log("cannot watch the points being moved: %s" % err)
            return
        self._watching_points = lyr
        # As with the polygons: a drag comes inside an edit command, an undo or
        # a redo replays one without opening any. Only drags are looked at.
        # When the two cannot be told apart, nothing is: walking back a replay
        # would walk the stack back further than the person asked.
        self._point_command = None
        try:
            hook(self, lyr.editCommandStarted,
                 shielded(lambda *a: self.point_command_is(True), "Point move"))
            hook(self, lyr.editCommandEnded,
                 shielded(lambda *a: self.point_command_is(False), "Point move"))
            hook(self, lyr.editCommandDestroyed,
                 shielded(lambda *a: self.point_command_is(False), "Point move"))
            self._point_command = False
        except Exception as err:
            log("cannot tell a point dragged from an undo on this QGIS: %s"
                % err)

    def point_command_is(self, open_):
        self._point_command = bool(open_)

    def note_point_move(self, fid, geom):
        """Remember the point and look at it once the drag has landed, for the
        same reason note_geometry_change waits: nothing may be undone from
        inside QGIS's own edit command."""
        if self._settling or not self.tiled:
            return
        if getattr(self, "_point_command", None) is not True:
            return
        if self.marks_locked(say=False):
            return          # the lock walks it back on its own
        moved = self.__dict__.setdefault("_points_moved", set())
        moved.add(fid)
        QTimer.singleShot(0, self.check_point_moves)

    def check_point_moves(self):
        """A point dragged out of its frame is put back.

        The rule is the one drop_point keeps: every pixel of the point's
        footprint inside the frame whose name it carries. A drag that breaks
        it for any of the points it moved is taken back whole, with the undo
        stack, so that the table is left exactly as it was before the drag.
        Moving a point to another frame is done by removing it and dropping it
        there, so that its tile_id is written by the program and not guessed."""
        moved = getattr(self, "_points_moved", None) or set()
        self._points_moved = set()
        lyr = self.layer("points")
        if lyr is None or not moved or not self.tiled:
            return
        strays = []
        for fid in sorted(moved):
            f = lyr.getFeature(fid)
            if f is None or not f.isValid() or not f.hasGeometry():
                continue
            tid = f["tile_id"]
            frame = self.frame_geometry(tid)
            box = f.geometry().boundingBox()
            if frame is None or not footprint_fits(
                    frame, box.xMinimum(), box.yMinimum(),
                    self.point_size_of(f), self.geometry.origin,
                    self.geometry.pixel_crs):
                strays.append(str(tid or ""))
        if not strays:
            return
        stack = lyr.undoStack()
        self._settling = True
        try:
            if stack is not None and stack.canUndo():
                stack.undo()
        except Exception as err:
            log("could not put the point back: %s" % err, loud=True)
            return
        finally:
            self._settling = False
        lyr.triggerRepaint()
        if len(strays) == 1 and not strays[0]:
            # a point RasterLabel 1.0 wrote outside every frame, with no
            # tile_id: there is no frame for it to be moved inside
            msg = ("point put back: it carries no frame, so it cannot be "
                   "moved into one. To put it in a frame, right click it to "
                   "remove it and drop it there")
        else:
            msg = ("point put back: it, or its square of pixels, would have "
                   "left %s. A point stays inside the frame it was dropped "
                   "in; to put it in another one, right click it to remove "
                   "it and drop it there"
                   % ("its tile %s" % strays[0] if len(strays) == 1 else
                      "its tile (%d points)" % len(strays)))
        iface.messageBar().pushMessage(NAME, msg, level=LEVEL_WARNING,
                                       duration=6)
        log(msg)
        self.refresh_coverage()

    def point_count(self):
        layer = self.layer("points")
        if layer is None:
            return 0
        if not self.tiled:
            return layer.featureCount()
        tile = self.current_tile_id()
        if tile is None:
            return layer.featureCount()
        return sum(1 for f in layer.getFeatures() if str(f["tile_id"]) == str(tile))

    def reclassify_at(self, point):
        """Ctrl+click: the polygon under the cursor takes the current class."""
        if self.marks_locked():
            return False
        p = QgsGeometry.fromPointXY(point)
        target = None
        for f in self.scope_polygons():
            if f.geometry().contains(p):
                target = f
                break
        if target is None:
            return False
        if target["class_name"] == self.class_name:
            return True
        lyr = self.polygons
        g = QgsGeometry(target.geometry())
        if not lyr.isEditable():
            lyr.startEditing()
        lyr.beginEditCommand("reclassify to %s" % self.class_name)
        lyr.deleteFeature(target.id())
        self.add_merging(g, self.class_name)     # joins what it now meets
        lyr.endEditCommand()
        lyr.triggerRepaint()
        self.refresh_coverage()
        time_mark(self, "reclass", tool="brush",
                  class_code=self.current_code(),
                  from_code=self.code_of(target["class_name"]),
                  area_m2=self.geometry.area(g), x=point.x(), y=point.y())
        self.ticked()
        return True

    def ticked(self):
        """One more thing drawn. Write everything down when enough have piled
        up, because the work that hurts to lose is the work nobody saved.

        Every path that changes the drawing calls this, and that is the whole
        contract: for a long time only the brush and the points did, so an
        afternoon spent on Fill Gap, Repair, lines and class swaps moved the
        counter not one step and nothing was ever written down by itself. The
        setting said "every 20 strokes" and meant "every 20 strokes of two
        particular tools".

        It also writes the net. Autosave decides how often the work reaches the
        GeoPackage; the net is written after every single stroke, because the
        thing it exists for is the crash that happens between two autosaves."""
        self.since_save += 1
        # The shapes are now what the last stroke left: a vertex dragged after
        # this has to be measured against them, not against what was there
        # before the stroke.
        self.remember_shapes()
        # The net first, then the autosave. The other way round, a crash in
        # the middle of the autosave would find a net written before this
        # stroke: the stroke's removals already in the package and its
        # additions nowhere, so a polygon that had been saved would be lost
        # for good.
        try:
            self.panel.keep_safe()
        except Exception as err:
            log("the recovery snapshot was not written: %s" % err)
        every = self.autosave.value()
        if every and self.since_save >= every:
            self.since_save = 0
            self.save(quiet=True)

    # ----------------------------------------------------------- the journal
    def note(self, action, timing=None, **fields):
        """One row of the journal of working time (ui_time, journal.py):
        what was done, with the reading in hand and the frame, and the time a
        map tool handed over for it. Never raises and never stops a stroke:
        a journal that cannot be written says so once in the log."""
        return time_note(self, "annotate", action, timing, **fields)

    def pop_timing(self):
        """The time of the stroke in hand, handed over by the map tool that
        drew it (tools.stroke_handed), taken once. None for a stroke made by
        a button, or by a suite calling paint() itself."""
        timing = getattr(self, "timing", None)
        self.timing = None
        return timing

    def undo_stroke(self):
        """Take back the last stroke, on the table the shape in hand writes to.

        Undoing the polygons and nothing else would take a line's painted band
        away and leave the centreline in the lines table saying a fissure ran
        there, and undoing a point would do nothing at all while looking as
        though it had."""
        if self.marks_locked():
            return
        roles = ["polygons"]
        if getattr(self, "b_line", None) is not None and self.b_line.isChecked():
            # A line is two things: the trace and the band painted from it.
            roles = ["lines", "polygons"]
        elif getattr(self, "b_points", None) is not None \
                and self.b_points.isChecked():
            roles = ["points"]
        undone = []
        for role in roles:
            lyr = self.layer(role)
            if lyr is not None and lyr.isEditable() and lyr.undoStack().canUndo():
                lyr.undoStack().undo()
                lyr.triggerRepaint()
                undone.append(role)
        if not undone:
            iface.messageBar().pushMessage(
                NAME, "nothing left to undo in %s: Undo stops at the last "
                "save, by hand or by itself" % " and ".join(roles),
                level=LEVEL_INFO, duration=3)
        else:
            # The net still lists the stroke that was just withdrawn, and a
            # restore would put it back. Undo is a change to the drawing like
            # any other, so it arms the net like any other.
            try:
                self.panel.keep_safe()
            except Exception as err:
                log("the recovery snapshot was not brought up to date: %s" % err)
            time_mark(self, "undo", tool="key", note=" and ".join(undone))
        self.refresh_coverage()

    def save(self, quiet=False):
        """Write everything down. A commit closes the editing session, so it
        is opened again straight away: the brush must never find the layer
        shut under it."""
        # The numbers on the frames are brought up to date first, so that what
        # is committed one line later is the measurement of what is being
        # committed, not of what it was an hour ago.
        try:
            self.measure_all_tiles()
        except Exception as err:
            log("cannot bring the frame measurements up to date: %s" % err)
        saved, trouble = 0, []
        # every table that can be open for editing has to be in this tuple, and
        # in the same one unsaved() reads. If they differed, say by "boxes",
        # the panel would know there were unsaved boxes, ask whether to save,
        # be told yes, skip the table and report success while the layers were
        # being dropped. Anything added here goes in unsaved() too.
        for role in EDITABLE_TABLES:
            lyr = self.layer(role)
            if lyr is None or not lyr.isEditable():
                continue
            if lyr.commitChanges():
                saved += 1
                lyr.startEditing()
                # The net is brought up to date after every table, not once
                # at the end: a crash between two commits left this table's
                # work both in the package and in the net, and a restore put
                # it in twice.
                try:
                    self.panel.keep_safe()
                except Exception as err:
                    log("the recovery snapshot was not brought up to date: %s"
                        % err)
            else:
                errors = lyr.commitErrors()
                trouble.append("%s: %s" % (role, "; ".join(errors[:3])))
                log("cannot save %s: %s" % (role, errors))
        # A commit gives every polygon drawn since the last one a new id. The
        # shapes kept for the vertex tool are filed under the old ones, and the
        # first border pulled back after a Save would find no "before", give
        # nothing away and leave a hole.
        self.remember_shapes()
        # A commit empties the undo stack, so a lock on the marks is held at
        # the bottom of the new one rather than at an index that is gone. The
        # layers say so themselves after a commit; this covers a QGIS whose
        # layers do not.
        self.rebase_lock()
        if not trouble:
            # Only a save that worked earns a fresh counter. Zeroing it after a
            # failure pushed the next automatic attempt a whole cycle away,
            # which is the opposite of what a failed save deserves.
            self.since_save = 0
        if trouble:
            iface.messageBar().pushMessage(
                NAME, "not everything could be saved. " + " | ".join(trouble),
                level=LEVEL_CRITICAL, duration=9)
        elif not quiet:
            iface.messageBar().pushMessage(
                NAME, "saved, %d layer%s written"
                % (saved, "" if saved == 1 else "s"), level=LEVEL_INFO, duration=2)
        else:
            log("saved by itself (%d layers written)" % saved)
        # And the net is asked to look again. It removes itself when nothing is
        # pending, which after a save that worked is the case, and a snapshot
        # left behind is read at the next open as work that was never saved.
        try:
            self.panel.keep_safe()
        except Exception as err:
            log("the recovery snapshot was not brought up to date: %s" % err)
        self.refresh_coverage()
        time_mark(self, "save", tool="" if quiet else "button",
                  note="by itself" if quiet else "")

    def unsaved(self):
        for role in EDITABLE_TABLES:
            lyr = self.layer(role)
            if lyr is not None and lyr.isEditable() and lyr.isModified():
                return True
        return False

    # ----------------------------------------------------------- coverage
    def refresh_coverage(self, *args):
        if not self.tiled:
            n = len(self.scope_polygons())
            points = self.point_count()
            self.coverage.setText(
                "%d polygon%s in pass %d%s"
                % (n, "" if n == 1 else "s", self.pass_no.value(),
                   ", %d point%s" % (points, "" if points == 1 else "s")
                   if points else ""))
            self.suggest(0, n)
            return
        tile = self.tile_geometry()
        if tile is None:
            self.coverage.setText("no tile selected")
            self.suggest(0, 0)
            return
        total_area = self.geometry.area(tile)
        per_class, painted = {}, 0.0
        # Measured on the union, not on the sum. The partition is meant to have
        # no overlaps, but "a moved vertex wins" can be switched off and Repair
        # exists precisely because overlaps happen: added up one by one they
        # pushed the share over a hundred per cent, turned the figure green,
        # had suggest() announce a finished frame and clamped the unpainted row
        # to zero, hiding the holes that were still there.
        clipped = []
        for f in self.reading_polygons():
            # Clipped to the frame, the same way measure_tile counts. A
            # polygon dragged half outside with the vertex tool would be
            # counted whole here, which puts the coverage over a hundred per
            # cent and has the panel announce a finished frame with holes
            # still in it.
            piece = f.geometry().intersection(tile)
            if piece is None or piece.isEmpty():
                continue
            clipped.append((f["class_name"], piece))
        by_class = {}
        for name, piece in clipped:
            by_class.setdefault(name, []).append(piece)
        for name, pieces in by_class.items():
            try:
                one = QgsGeometry.unaryUnion(pieces) if len(pieces) > 1 \
                    else pieces[0]
            except Exception:
                one = None
            per_class[name] = self.geometry.area(one) if (
                one is not None and not one.isEmpty()) \
                else sum(self.geometry.area(x) for x in pieces)
        try:
            everything = QgsGeometry.unaryUnion([x for _, x in clipped]) \
                if clipped else None
        except Exception:
            everything = None
        if everything is not None and not everything.isEmpty():
            painted = self.geometry.area(everything)
        else:
            painted = sum(per_class.values())
        painted = min(painted, total_area) if total_area else painted
        pc = 100 * painted / total_area if total_area else 0
        colour = "#008300" if pc > 99.5 else ("#eda100" if pc > 80 else "#eb6834")
        rows = ["<table cellspacing=3>",
                "<tr><td><b>coverage</b></td><td align=right>"
                "<b style='color:%s'>%.1f%%</b></td></tr>" % (colour, pc)]
        for c in self.campaign.active_classes():
            a = per_class.get(c["name"], 0.0)
            if a > 0:
                rows.append("<tr><td><span style='color:%s'>&#9632;</span> %s</td>"
                            "<td align=right>%.1f%%</td></tr>"
                            % (c["colour"], c["name"], 100 * a / total_area))
        rows.append("<tr><td>unpainted</td><td align=right>%.2f m2</td></tr>"
                    % max(total_area - painted, 0))
        points = self.point_count()
        if points:
            rows.append("<tr><td>points</td><td align=right>%d</td></tr>" % points)
        rows.append("</table>")
        self.coverage.setText("".join(rows))
        self.suggest(pc, len(self.reading_polygons()))

    def reading_polygons(self):
        """The polygons of the reading in hand: the pass and the operator in
        the panel, whether or not "one operator at a time" is ticked.

        That box decides what is on screen; it does not make two readings
        one. With it off, a coverage counting every operator of the pass
        together would read a green hundred for two people at sixty per cent
        each, and the yellow line would say the frame was done, while the
        file, and Check, said it was not. The figure on the panel is measured
        the way closed is: one reading on its own."""
        mine = self.operator_name()
        return [f for f in self.scope_polygons()
                if self.operator_of(f) == mine]

    def others_fill_frame(self):
        """The other operators of the pass whose work, with the reading in
        hand, leaves nothing of the frame unpainted, when "one operator at a
        time" is off and the brush and Fill Gap reckon with them: their
        names, or [] when there is a gap left or the box is ticked."""
        if self.by_operator.isChecked():
            return []
        tile = self.tile_geometry()
        if tile is None:
            return []
        mine = self.operator_name()
        scope = self.scope_polygons()
        others = sorted({self.operator_of(f) for f in scope} - {mine})
        if not others:
            return []
        pieces = []
        for f in scope:
            piece = f.geometry().intersection(tile)
            if piece is not None and not piece.isEmpty():
                pieces.append(piece)
        try:
            union = QgsGeometry.unaryUnion(pieces) if pieces else None
        except Exception:
            union = None
        total = self.geometry.area(tile)
        if not total or union is None or union.isEmpty():
            return []
        return others if self.geometry.area(union) / total > 0.995 else []

    def suggest(self, pc, n_polygons):
        """The yellow line: always the one thing worth doing now.

        The order is not a preference. Painting the small sharp things first
        and the background last means every later stroke can overshoot on
        purpose, because what is already there wins over it; start from the
        background and every fine edge has to be cut by hand."""
        others = []
        if (self.tiled and pc < 99.5 and self.class_name is not None
                and self.current_tile_id() is not None):
            others = self.others_fill_frame()
        if self.tiled and not self.tile_ids():
            # Only controls the panel has are named. A hint that names one
            # it does not have is worse than no hint: it sends somebody
            # looking for something they will never find, and the thing they
            # were told to set, the side of the frame, is the thing they end
            # up thinking is missing.
            text = ("<b>1.</b> Take <b>Tiles</b>, set <b>tile side</b> under "
                    "Settings, then click on the map: a frame of that size "
                    "lands where you click. <b>Import frames</b> takes them "
                    "from a file instead.")
        elif self.tiled and self.current_tile_id() is None:
            text = "<b>1.</b> Pick a frame from the list, then <b>Go</b>."
        elif self.class_name is None:
            text = "<b>2.</b> Pick a class, then take the brush or the polygon."
        elif others:
            # With "one operator at a time" off the brush and Fill Gap
            # reckon with every operator of the pass, and the coverage with
            # the reading in hand. Where the others have painted the rest,
            # the lines below sent the user to a Fill Gap that answered "no
            # holes" and to a brush with nowhere left to paint.
            text = ("<b>5.</b> Coverage <b>%.0f%%</b> in your reading. The "
                    "rest of the frame is %s's work in this pass, so Fill Gap "
                    "finds no gap, and a frame is closed by one reading, not "
                    "by two together. Tick <b>one operator at a time</b> to "
                    "paint the rest as your own."
                    % (pc, " and ".join(others)))
        elif n_polygons == 0:
            text = ("<b>3.</b> Start with the <i>small and sharp</i> things, "
                    "the details you want exact. With <b>paint under the "
                    "others</b> on you can overshoot as much as you like.")
        elif not self.tiled:
            text = ("<b>4.</b> %d polygon%s drawn in this pass. Without frames "
                    "there is no coverage to close: save when you are done."
                    % (n_polygons, "" if n_polygons == 1 else "s"))
        elif pc < 60:
            text = ("<b>4.</b> Now the larger patches. Overshoot across what "
                    "you have drawn: you will not touch it, you only fill the "
                    "gaps. Coverage <b>%.0f%%</b>." % pc)
        elif pc < 99.5:
            text = ("<b>5.</b> The background is what is left. Take the "
                    "commonest class and sweep over it, "
                    "or press <b>Fill Gap</b> and finish in one go. "
                    "Coverage <b>%.0f%%</b>." % pc)
        else:
            text = ("<b>6.</b> Frame complete. Check the doubtful borders "
                    "(%s+click swaps the class, Shift paints over), then "
                    "<b>Save</b> and move to the next one." % ctrl_name())
        self.step.setText(text)

    # ----------------------------------------------------------- tools
    def drop_move(self):
        """Move goes up whenever a shape takes the map.

        The latch and the map tool have to say the same thing. Left down while
        the brush is in hand it promises a hand cursor that is not there and a
        drag that draws a polygon instead of moving a frame, which is the
        confusion pressing Move now exists to end."""
        b = getattr(self, "b_move", None)
        if b is not None and b.isChecked():
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
            if self.tile_tool is not None:
                self.tile_tool.show_mode()
            log("frame dragging off: a shape took the map")

    def use_brush(self, round_=None):
        """round_ True or False picks the shape, None keeps the one in hand."""
        self.drop_vertices()
        self.drop_move()
        if self.brush is None:
            self.brush = BrushTool(canvas(), self)
        if round_ is True:
            self.round_brush.setChecked(True)
        elif round_ is False:
            self.b_brush.setChecked(True)
        elif not (self.b_brush.isChecked() or self.round_brush.isChecked()):
            self.b_brush.setChecked(True)
        self.tool_settings()
        self.brush.refresh_colour()
        canvas().setMapTool(self.brush)

    def frames_locked(self, say=True):
        """True when the frames are held. Says so once, where it can be seen.

        Every refusal is spoken. A button that silently does nothing is worse
        than one that is missing: you press it again, harder, and then go
        looking for the bug in the wrong place."""
        if not self.lock_frames.isChecked():
            return False
        if say:
            iface.messageBar().pushMessage(
                NAME, "the frames are locked: let the lock up to move or make "
                      "one", level=LEVEL_WARNING, duration=4)
        return True

    def marks_locked(self, say=True):
        if not self.lock_marks.isChecked():
            return False
        if say:
            iface.messageBar().pushMessage(
                NAME, "the marks are locked: let the lock up to draw",
                level=LEVEL_WARNING, duration=4)
        return True

    def locks_changed(self, *args):
        held = []
        # A shut padlock on the button itself. The word was cut down to
        # "Frames" and "Marks" to keep the columns even, and a short word does
        # not say by itself that it is a lock; the drawing does, and only when
        # it is shut, so a lock that is holding something reads as one from
        # across the room.
        for button, shut in ((self.lock_frames, self.lock_frames.isChecked()),
                             (self.lock_marks, self.lock_marks.isChecked())):
            try:
                button.setIcon((theme_icon("locked.svg") or padlock_icon(True))
                               if shut else QIcon())
            except Exception:
                pass
        if self.lock_frames.isChecked():
            held.append("frames")
        if self.lock_marks.isChecked():
            held.append("marks")
        # Where each table stands on its undo stack when the marks are shut:
        # hold_marks() keeps them there.
        self.rebase_lock()
        log("locked: %s" % (" and ".join(held) if held else "nothing"))
        self.show_blind()
        self.refresh_coverage()

    def tool_settings(self):
        """Show the settings the tool in hand actually reads, hide the rest.

        A panel that shows everything at once is not being generous, it is
        making you read four numbers to find the one that matters, and two of
        the four do nothing right now. What stays visible in every case is what
        holds across the tools: the pass, who is drawing, how often the work is
        written down, and the habits that apply to whatever leaves a mark.

        Nothing is disabled here, only hidden. A hidden setting keeps its value
        and comes back as it was when its tool comes back."""
        line = self.b_line.isChecked()
        round_ = self.round_brush.isChecked()
        points = self.b_points.isChecked()
        tiles = self.tiled and self.b_tiles.isChecked()
        marks = not points and not tiles       # polygon, round brush or line

        for widget, when in ((getattr(self, "row_radius", None), round_),
                             (getattr(self, "row_point", None), points),
                             (getattr(self, "row_line", None), line),
                             (self.line_over, line),
                             (self.uncertain, points),
                             (getattr(self, "row_tile", None), tiles),
                             (getattr(self, "row_paint_under", None), marks)):
            if widget is not None:
                widget.setVisible(bool(when))
        # A tool with a number of its own opens the settings, because hiding
        # that number behind a closed fold is how "the tile size cannot be
        # chosen" happens: it is there, two clicks away, and nothing says so.
        # Only on picking up a tool, so closing the fold on purpose while
        # holding one is respected.
        if (line or round_ or points or tiles) and not self.fold.isChecked():
            self.fold.setChecked(True)
        self.deck.deal()

    def point_size(self):
        return int(self.point_px.currentData() or 1)

    def sizes_in_use(self):
        """The footprints the points of this campaign already carry.

        A point written before the field existed comes back as 1, the single
        pixel, because that is what it meant when it was placed: nothing else
        was on offer."""
        layer = self.layer("points")
        seen = {}
        if layer is None:
            return seen
        has = "size_px" in layer.fields().names()
        for f in layer.getFeatures():
            n = 1
            if has:
                try:
                    n = int(f["size_px"] or 1)
                except (TypeError, ValueError):
                    n = 1
            seen[n] = seen.get(n, 0) + 1
        return seen

    def point_size_changed(self, *args):
        """Say what the footprint is on the ground, and warn about mixing.

        The warning is the point of this method. A campaign whose points are
        half single pixels and half nine by nine squares is not a set of
        samples, it is two sets with the same name, and every count taken from
        it is a number about nothing. Nothing is forbidden: there are honest
        reasons to mix, a coarse first pass and a fine second one among them.
        But it is said out loud at the moment of choosing, not discovered
        afterwards by somebody reading the table."""
        n = self.point_size()
        px = self.geometry.pixel_m[0]
        self.point_m.setText("%.2f m across" % (n * px) if px else "")
        seen = self.sizes_in_use()
        others = {k: v for k, v in seen.items() if k != n}
        if not others:
            return
        parts = ", ".join(
            "%d of %s" % (v, "1 px" if k == 1 else "%d x %d" % (k, k))
            for k, v in sorted(others.items()))
        iface.messageBar().pushMessage(
            NAME,
            "this campaign already holds points of another footprint (%s): "
            "mixing them makes any count over them a number about two "
            "different things" % parts,
            level=LEVEL_WARNING, duration=9)
        log("point footprints in this campaign: %s"
            % ", ".join("%dpx: %d" % (k, v) for k, v in sorted(seen.items())))

    def show_line_in_metres(self, *args):
        px = self.geometry.pixel_m[0]
        self.line_m.setText("%.2f m" % (self.line_px.value() * px) if px else "")

    def use_line_tool(self):
        self.drop_vertices()
        self.drop_move()
        if self.layer("lines") is None:
            iface.messageBar().pushMessage(
                NAME, "this campaign has no table for the lines: close it and "
                      "open it again", level=LEVEL_WARNING, duration=5)
            self.use_brush()
            return
        if self.line_tool is None:
            self.line_tool = LineTool(canvas(), self)
        self.b_line.setChecked(True)
        self.tool_settings()
        self.line_tool.refresh_colour()
        canvas().setMapTool(self.line_tool)
        log("line: click or drag to trace, right click or Enter to finish, "
            "Backspace takes back a vertex, Esc throws it away.")

    def draw_line(self, points):
        """A finished trace: the line goes in the file, the strip goes on the
        ground.

        The two are not a copy of one another. The line says "a fissure runs
        here, this long, this wide", and stays true whatever is painted over it
        later. The strip says "this ground is of this class now", and takes part
        in the same winner takes all partition as every brush stroke, which is
        what keeps the exported mask identical to the screen.

        Which way it settles is the button beside the width, and it is read
        here, once, at the moment of drawing. Reading it later, at export time,
        would mean recomputing the cut against polygons that have moved in the
        meantime, and what came out would no longer be what was drawn."""
        if self.marks_locked():
            return
        if self.class_name is None:
            return
        lyr = self.table_back("lines")
        if lyr is None or (self.tiled and self.table_back("tiles") is None):
            return
        if self.tiled:
            tile = self.tile_geometry()
            if tile is None:
                iface.messageBar().pushMessage(NAME, "no tile selected",
                                               level=LEVEL_WARNING, duration=3)
                return
        trace = QgsGeometry.fromPolylineXY(points)
        if self.tiled:
            trace = trace.intersection(tile)
        if trace is None or trace.isEmpty():
            iface.messageBar().pushMessage(
                NAME, "nothing drawn: the line fell outside the tile",
                level=LEVEL_WARNING, duration=4)
            return

        width_px = self.line_px.value()
        band, covered = self.geometry.strip(points, width_px)
        if band is None:
            iface.messageBar().pushMessage(
                NAME, "no pixel grid to snap the line to", level=LEVEL_WARNING, duration=4)
            return
        if self.tiled:
            band = band.intersection(tile)

        over = self.line_over.isChecked()
        length = self.geometry.length(trace)
        if not lyr.isEditable():
            lyr.startEditing()
        lyr.beginEditCommand("line %s" % self.class_name)
        f = QgsFeature(lyr.fields())
        f.setGeometry(trace)
        f["class_name"] = self.class_name
        f["class_code"] = self.current_code()
        f["tile_id"] = self.current_tile_id()
        if "pass_no" in lyr.fields().names():
            f["pass_no"] = self.pass_no.value()
        f["operator"] = self.operator_name()
        f["width_px"] = int(width_px)
        f["width_m"] = round(width_px * self.geometry.pixel_m[0], 4)
        f["length_m"] = round(length, 3)
        f["mode"] = "over" if over else "under"
        f["created"] = now()
        lyr.addFeature(f)
        lyr.endEditCommand()
        lyr.triggerRepaint()

        # and now the same machinery a stroke goes through, so that the line
        # cannot make an overlap that a brush would not have made. The time
        # is the line's: the stroke inside it writes no row of its own.
        timing = time_take(self)
        self.quiet_note = True
        try:
            self.paint(band, under=not over)
        finally:
            self.quiet_note = False
        iface.messageBar().pushMessage(
            NAME, "line %s: %.2f m, %d px wide, %s"
            % (self.class_name, length, width_px,
               "cutting over what it crossed" if over
               else "kept only where nothing was claimed"),
            level=LEVEL_INFO, duration=4)
        log("line %s: %.3f m, %d px wide, %d pixels claimed, %s"
            % (self.class_name, length, width_px, covered,
               "over" if over else "under"))
        x, y = time_centre(trace)
        time_mark(self, "line", timing=timing, class_code=self.current_code(),
                  area_m2=self.geometry.area(band), n_vertices=len(points),
                  x=x, y=y, note="over" if over else "under")
        self.ticked()

    def use_point_tool(self):
        self.drop_vertices()
        self.drop_move()
        if self.layer("points") is None:
            iface.messageBar().pushMessage(
                NAME, "this campaign has no table for the points: close it and "
                      "open it again", level=LEVEL_WARNING, duration=5)
            self.use_brush()
            return
        if self.point_tool is None:
            self.point_tool = PointTool(canvas(), self)
        self.b_points.setChecked(True)
        self.tool_settings()
        self.point_size_changed()
        self.point_tool.refresh_colour()
        canvas().setMapTool(self.point_tool)
        log("points: click to drop one, right click to take it back, %s and "
            "click to change its class, Esc to go back to the polygon."
            % ctrl_name())

    def use_tile_tool(self):
        self.drop_vertices()
        if not self.tiled:
            log("this campaign has no tiles")
            return
        if self.tile_tool is None:
            self.tile_tool = TileTool(canvas(), self)
        self.b_tiles.setChecked(True)
        self.tool_settings()
        canvas().setMapTool(self.tile_tool)
        log("tile mode: click on empty ground to create a tile, inside one to "
            "select it, drag from inside one to move it, Esc to go back to the "
            "polygon. A new frame gives the map back to the polygon by itself. "
            "Moving a tile that holds polygons asks first.")

    def release_tools(self):
        # Every tool this section ever handed to the canvas, not three of the
        # four: the line tool was missing, so closing a module while a line was
        # in hand left a map tool pointing at a section that no longer existed.
        # The vertex latch goes down too, because the tool behind it is QGIS's
        # own and nothing else would ever pop it up.
        time_close(self, "annotate")
        self.drop_vertices()
        # and the map goes back to the tool the person had, Pan when there was
        # none: unsetting ours left the canvas with no tool at all
        hand_back_tool(getattr(self, "_tool_before", None),
                       (self.brush, self.tile_tool, self.point_tool,
                        getattr(self, "line_tool", None)))
        self.give_back_project_settings()
        self._released = True
