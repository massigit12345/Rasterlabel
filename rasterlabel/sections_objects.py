"""rasterlabel.sections_objects

Objects: boxes with a class on them.
"""
from html import escape

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QButtonGroup, QDoubleSpinBox, QGridLayout,
                                 QGroupBox, QHBoxLayout, QLabel, QSpinBox,
                                 QToolButton, QVBoxLayout, QWidget)
from qgis.core import QgsFeature, QgsGeometry, QgsPointXY

from .constants import (AUTOSAVE, FIELD_W, LEVEL_CRITICAL, LEVEL_INFO,
                        LEVEL_WARNING, MIN_BOX_PX, NAME)
from .compat import iface
from .naming import ctrl_name, now
from .campaign import operator_word, pass_number
from .project import canvas
from .errors import log, shielded
from .layout import Deck
from .theme import banner_height, follows_width, heading, plain, primary, spread
from .widgets import OneLine
from .geometry import Geometry
from .layers import find_mine
from .tools import BoxTool, hand_back_tool, tool_in_hand
from .sections_annotate import AnnotationSection
from .ui_time import time_close, time_mark, time_note, time_open


class Held(object):
    """One setting of the reading the panel holds, read the way Annotate
    reads its check box or its spin box. The filter Annotate puts on the
    tables is then put on them from here too, the same one, rather than a
    second copy of it that could drift away from the first."""

    def __init__(self, read):
        self.read = read

    def isChecked(self):
        return bool(self.read())

    def value(self):
        return self.read()


class ReadingFilter(object):
    """The filter of the reading in hand, put on the tables of a campaign
    with no module open to do it.

    Annotate and Objects filter the tables as they open, and the tables are
    drawn by that filter alone. A campaign opened by itself, before either
    is pressed, would show every operator and every pass on top of each other
    in the colours of the legend until Annotate was pressed. This is the
    same filter, the very methods of Annotate lent over, set from the
    reading the panel holds: the map looks the same before Annotate is
    pressed as after."""

    OPERATOR_BLANK = AnnotationSection.OPERATOR_BLANK
    apply_filter = AnnotationSection.__dict__["apply_filter"]
    filter_layer = AnnotationSection.__dict__["filter_layer"]
    hiding = AnnotationSection.__dict__["hiding"]
    layer = AnnotationSection.__dict__["layer"]

    def __init__(self, panel):
        self.panel = panel
        self.campaign = panel.campaign
        self.tiled = bool(self.campaign.data.get("with_tiles"))
        held = lambda: panel.reading() or {}      # noqa: E731
        self.by_operator = Held(lambda: held().get("by_operator", True))
        self.blind = Held(lambda: held().get("blind", True))
        self.pass_no = Held(lambda: int(panel.which_pass()))
        self.only_current = Held(lambda: False)

    @property
    def polygons(self):
        return self.layer("polygons")

    def current_tile_id(self):
        return None

    def operator_name(self):
        return operator_word(self.panel.who_is_drawing())

    def show_blind(self):
        """Nothing to say: there is no strip when no module is open."""


class ObjectsSection(QGroupBox):
    """Boxes with a class on them: what detection is trained on.

    Boxes are free to overlap and free to be redrawn. Nothing is clipped,
    nothing is subtracted, and the annotation polygons are not touched: the
    two products live side by side in the same campaign and are exported
    separately."""

    def __init__(self, panel):
        super().__init__("")
        self.panel = panel
        self.campaign = panel.campaign
        reference = find_mine(self.campaign.data["id"], "boxes") \
            or find_mine(self.campaign.data["id"], "tiles") \
            or find_mine(self.campaign.data["id"], "polygons")
        self.geometry = Geometry(self.campaign,
                                 reference.crs() if reference is not None else None)
        self.tiled = self.campaign.data["with_tiles"]
        self.class_name = None
        self.selected = None
        self.tool = None
        self._tool_before = tool_in_hand()   # what the map had before this
        self._buttons = []
        self.since_save = 0             # edits since the boxes last reached disk
        # The reading is the panel's, as in Annotate: who draws, which pass,
        # and whether the other readings are hidden. Without it every box
        # would be stamped with the campaign's creator and pass 1, whoever
        # drew it, in front of every other reading's boxes.
        self.by_operator = Held(
            lambda: self.held_reading().get("by_operator", True))
        self.blind = Held(lambda: self.held_reading().get("blind", True))
        self.pass_no = Held(lambda: int(self.panel.which_pass()))
        self.only_current = Held(lambda: False)
        self.build()
        self.apply_filter()
        self.show_blind()
        time_open(self, "objects")

    # ----------------------------------------------------------- the journal
    def note(self, action, timing=None, **fields):
        """One row of the campaign's journal of working time, as Annotate
        writes it, filed under Objects."""
        return time_note(self, "objects", action, timing, **fields)

    def pop_timing(self):
        timing = getattr(self, "timing", None)
        self.timing = None
        return timing

    def box_note(self, action, rect, **fields):
        """A row about a box: where it is and how large."""
        try:
            centre = rect.center()
            fields.setdefault("x", centre.x())
            fields.setdefault("y", centre.y())
            fields.setdefault("area_m2", self.geometry.area(
                QgsGeometry.fromRect(rect)))
        except Exception:
            pass
        return time_mark(self, action, **fields)

    # ----------------------------------------------------------- the panel
    def build(self):
        follows_width(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(7)

        self.current_label = QLabel("")
        self.current_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = self.current_label.font()
        f.setPointSize(max(f.pointSize() + 1, 11))
        f.setBold(True)
        self.current_label.setFont(f)
        self.current_label.setFixedHeight(banner_height(self.current_label))
        self.current_label.setToolTip("The class a new box is given.")

        # What the next click on the map does, under the class it will be
        # given, as in Annotate.
        self.tool_caption = OneLine()
        self.tool_caption.setObjectName("quiet")
        self.tool_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.class_grid = QGridLayout()
        self.class_grid.setContentsMargins(0, 0, 0, 0)
        self.class_grid.setSpacing(4)

        self.deck = Deck()
        self.deck.after = self.reflow
        legend = QVBoxLayout()
        legend.setSpacing(4)
        legend.addWidget(self.current_label)
        legend.addWidget(self.tool_caption)
        legend.addSpacing(2)
        legend.addLayout(self.class_grid)
        self.deck.add(legend, 3)

        self.b_tool = self._tool(
            "Boxes",
            "Drag on empty ground to draw a box.\nClick one to pick it up, then "
            "drag its middle to move it\nor a corner to stretch it. Delete "
            "removes it,\nEsc puts it down, " + ctrl_name() + " and click gives it the class\n"
            "you are holding.")
        self.b_tool.clicked.connect(shielded(self.use_tool, "Boxes"))
        self.b_tool.toggled.connect(lambda *_: self.show_tool_caption())
        self.tools = QButtonGroup(self)
        self.tools.setExclusive(True)
        self.tools.addButton(self.b_tool)

        # The same words as Annotate: what leaves a mark, what mends it, and
        # Save under them. Delete last in its row, where the hand slows down.
        tools = QVBoxLayout()
        tools.setSpacing(8)
        tools.addWidget(heading("SHAPE", plain(spread([self.b_tool], gap=4))))
        tools.addWidget(heading("EDIT", plain(spread([
            self._act("Undo", "Undo the last box.", self.undo),
            self._act("Delete", "Remove the box you have picked up.",
                      self.delete_selected, danger=True)], gap=4))))
        tools.addSpacing(4)
        tools.addLayout(spread([primary(self._act(
            "Save", "Write the boxes to the package.", self.save))]))
        self.deck.add(tools, 2)

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
        self.smallest = QDoubleSpinBox()
        self.smallest.setRange(self.geometry.pixel_m[0], 100.0)
        self.smallest.setDecimals(2)
        self.smallest.setSuffix(" m")
        self.smallest.setFixedWidth(FIELD_W)
        self.smallest.setValue(round(MIN_BOX_PX * self.geometry.pixel_m[0], 2))
        self.smallest.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.smallest.setToolTip(
            "A rectangle with a side shorter than this is a misclick, not an\n"
            "object, and is thrown away instead of being written.")
        self.smallest.valueChanged.connect(self.show_smallest)
        self.smallest_px = QLabel("")
        self.smallest_px.setObjectName("quiet")
        inner.addLayout(self._field("smallest", self.smallest, self.smallest_px))

        # The same setting, with the same default, as in Annotate: boxes sat
        # in an edit buffer until somebody pressed Save, and an afternoon of
        # them could be lost to a locked package nobody was told about.
        self.autosave = QSpinBox()
        self.autosave.setRange(0, 200)
        self.autosave.setValue(AUTOSAVE)
        self.autosave.setSuffix(" boxes")
        self.autosave.setFixedWidth(FIELD_W)
        self.autosave.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.autosave.setToolTip(
            "Writes the boxes to the package by itself every so many changes.\n"
            "Zero turns it off and nothing is written until you press Save.\n\n"
            "A save, by hand or by itself, closes the undo history: Undo\n"
            "cannot take back a box that has been written.")
        inner.addLayout(self._field("autosave", self.autosave))
        self.settings.setVisible(False)
        self.settings_box.addWidget(self.settings)
        self.deck.add(self.settings_box, 2)

        # Who the boxes are filed under, always in sight: there is no box
        # for it here as there is in Annotate, only the button that opens
        # the window to change it.
        self.reading_label = QLabel("")
        self.reading_label.setWordWrap(True)
        self.reading_label.setObjectName("quiet")
        self.reading_button = QToolButton()
        self.reading_button.setText("Change")
        self.reading_button.setAutoRaise(True)
        self.reading_button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.reading_button.setToolTip(
            "Who is drawing, in which pass, and whether only this pass is\n"
            "shown. Every box is filed under that reading.")
        self.reading_button.clicked.connect(
            shielded(self.change_reading, "Who is drawing"))
        reading_row = QHBoxLayout()
        reading_row.setSpacing(4)
        reading_row.addWidget(self.reading_label, 1)
        reading_row.addWidget(self.reading_button, 0,
                              Qt.AlignmentFlag.AlignTop)

        self.tally = QLabel("")
        self.tally.setWordWrap(True)
        self.tally.setObjectName("quiet")
        tail = QVBoxLayout()
        tail.setSpacing(5)
        tail.addLayout(reading_row)
        tail.addWidget(self.tally)
        self.deck.add(tail, 2)

        self.deck.deal(force=True)
        outer.addWidget(self.deck)

        self.rebuild_class_buttons()
        self.show_smallest()
        self.show_tally()

    _tool = AnnotationSection.__dict__["_tool"]
    _act = AnnotationSection.__dict__["_act"]
    _field = AnnotationSection.__dict__["_field"]
    show_settings = AnnotationSection.__dict__["show_settings"]
    chip_room = AnnotationSection.__dict__["chip_room"]
    chip_columns = AnnotationSection.__dict__["chip_columns"]
    natural_columns = AnnotationSection.__dict__["natural_columns"]
    reflow = AnnotationSection.__dict__["reflow"]
    fit_names = AnnotationSection.__dict__["fit_names"]
    show_tool_caption = AnnotationSection.__dict__["show_tool_caption"]
    CAPTIONS = AnnotationSection.CAPTIONS
    resizeEvent = AnnotationSection.__dict__["resizeEvent"]
    _style = AnnotationSection.__dict__["_style"]
    settle = AnnotationSection.__dict__["settle"]
    show_current_class = AnnotationSection.__dict__["show_current_class"]
    current_colour = AnnotationSection.__dict__["current_colour"]
    current_code = AnnotationSection.__dict__["current_code"]
    rebuild_class_buttons = AnnotationSection.__dict__["rebuild_class_buttons"]
    # The chips it borrows can be renamed and added to, so the four methods
    # behind that gesture come with them. They were not lent at first and the
    # plus was built here with nothing behind it: a button that raises the
    # moment it is pressed, in a module nobody had pressed yet.
    class_by_code = AnnotationSection.__dict__["class_by_code"]
    start_rename = AnnotationSection.__dict__["start_rename"]
    cancel_rename = AnnotationSection.__dict__["cancel_rename"]
    finish_rename = AnnotationSection.__dict__["finish_rename"]
    add_class = AnnotationSection.__dict__["add_class"]
    # The filter of the readings, as Annotate applies it, on the boxes too.
    OPERATOR_BLANK = AnnotationSection.OPERATOR_BLANK
    apply_filter = AnnotationSection.__dict__["apply_filter"]
    filter_layer = AnnotationSection.__dict__["filter_layer"]
    hiding = AnnotationSection.__dict__["hiding"]
    layer = AnnotationSection.__dict__["layer"]

    @property
    def polygons(self):
        return self.layer("polygons")

    # ----------------------------------------------------------- the reading
    def held_reading(self):
        ask = getattr(self.panel, "reading", None)
        try:
            return (ask() if callable(ask) else None) or {}
        except Exception as err:
            log("cannot read the reading the panel holds: %s" % err)
            return {}

    def operator_name(self):
        return operator_word(self.panel.who_is_drawing())

    def my_reading(self):
        return (self.operator_name(), int(self.panel.which_pass()))

    @staticmethod
    def box_reading(f):
        """(operator, pass) of a box, read the way every export and Check
        read them."""
        values = []
        for name in ("operator", "pass_no"):
            try:
                values.append(f[name])
            except (KeyError, IndexError):
                values.append(None)
        return operator_word(values[0]), pass_number(values[1])

    def has_pass(self):
        layer = self.boxes
        return layer is not None and "pass_no" in layer.fields().names()

    def is_mine(self, f):
        """Whether a box belongs to the reading in hand. In a table that has
        no pass, by its operator alone."""
        who, p = self.box_reading(f)
        me, mine = self.my_reading()
        return who == me and (p == mine or not self.has_pass())

    def is_hidden(self, f):
        """Whether the filter keeps a box off the screen: the same two
        clauses apply_filter writes, operator and pass."""
        who, p = self.box_reading(f)
        me, mine = self.my_reading()
        if self.by_operator.isChecked() and who != me:
            return True
        return bool(self.hiding() and self.has_pass() and p != mine)

    def show_blind(self):
        """Who the boxes are filed under, and what is hidden from them."""
        if not self.held_reading():
            self.reading_label.setText("")
            return
        me, p = self.my_reading()
        text = "drawing as <b>%s, pass %d</b>" % (escape(me), p)
        if self.hiding():
            text += ", blind: only the boxes of this pass are shown"
        elif self.by_operator.isChecked():
            text += ": the boxes of the other operators are hidden"
        self.reading_label.setText(text)

    def change_reading(self):
        if not self.panel.change_reading():
            return
        self.select_box(None)
        if self.tool is not None:
            self.tool.show_selection()
        self.apply_filter()
        self.show_blind()
        self.show_tally()

    def not_yours(self, fid):
        """Refuse to touch a box of another reading. True when refused.

        A second reader who pressed on the first reader's box picked it up
        and moved it, or deleted it, and the first reading changed under a
        name that never touched it. The second reader draws a box of their
        own instead, over it if need be: boxes are free to overlap."""
        layer = self.boxes
        if layer is None or fid is None:
            return False
        f = layer.getFeature(fid)
        if f is None or self.is_mine(f):
            return False
        self.select_box(None)
        if self.tool is not None:
            self.tool.show_selection()
        iface.messageBar().pushMessage(
            NAME, "that box belongs to another reading and stays as it is: "
            "draw a box of your own", level=LEVEL_WARNING, duration=4)
        log("a box of another reading was left alone")
        return True

    def choose_class(self, name):
        self.class_name = name
        self.rebuild_class_buttons()
        if self.tool is not None:
            self.tool.refresh_colour()
        time_mark(self, "class", class_code=self.current_code())

    def show_smallest(self, *args):
        px = self.geometry.pixel_m[0]
        self.smallest_px.setText("%d px" % (int(round(self.smallest.value() / px))
                                            if px else 0))

    def show_tally(self):
        boxes = [f for f in self.all_boxes() if not self.is_hidden(f)]
        if not boxes:
            self.tally.setText("no box yet: drag on the image to draw one")
            return
        counts = {}
        for f in boxes:
            counts[f["class_name"]] = counts.get(f["class_name"], 0) + 1
        rows = ["<table cellspacing=3><tr><td><b>%d boxes</b></td><td></td></tr>"
                % len(boxes)]
        for c in self.campaign.active_classes():
            n = counts.get(c["name"], 0)
            if n:
                rows.append("<tr><td><span style='color:%s'>&#9632;</span> %s</td>"
                            "<td align=right>%d</td></tr>" % (c["colour"], c["name"], n))
        rows.append("</table>")
        self.tally.setText("".join(rows))

    # ----------------------------------------------------------- the layer
    @property
    def boxes(self):
        return find_mine(self.campaign.data["id"], "boxes")

    def all_boxes(self):
        layer = self.boxes
        return [] if layer is None else list(layer.getFeatures())

    def box_at(self, point):
        """The smallest box under the cursor, so a box inside another one can
        still be picked up."""
        layer = self.boxes
        if layer is None:
            return None
        p = QgsGeometry.fromPointXY(point)
        hits = [f for f in layer.getFeatures()
                if f.hasGeometry() and f.geometry().intersects(p)]
        if not hits:
            return None
        # Only the boxes of the reading in hand can be picked up. A press on
        # another reading's box draws a new one, which is what a second
        # reader has to do: their reading of that object, not a move of the
        # first one's. Said when the other box is in sight; a hidden one
        # stays as unseen as it is.
        mine = [f for f in hits if self.is_mine(f)]
        if mine:
            return min(mine, key=lambda f: f.geometry().boundingBox().area())
        seen = [f for f in hits if not self.is_hidden(f)]
        if seen:
            who, p_no = self.box_reading(seen[0])
            iface.messageBar().pushMessage(
                NAME, "that box is %s's, pass %d: another reading, which "
                "stays as it is. Drag to draw your own." % (who, p_no),
                level=LEVEL_INFO, duration=4)
        return None

    def select_box(self, fid):
        self.selected = fid
        layer = self.boxes
        if layer is not None:
            layer.removeSelection()
            if fid is not None:
                layer.select(fid)

    def selected_rect(self):
        layer = self.boxes
        if layer is None or self.selected is None:
            return None
        f = layer.getFeature(self.selected)
        if f is None or not f.hasGeometry():
            return None
        return f.geometry().boundingBox()

    def tile_holding(self, rect):
        """Which tile a box belongs to, decided by its middle, so a box that
        sticks out of a tile still belongs to the tile it was drawn in."""
        if not self.tiled:
            return ""
        tiles = find_mine(self.campaign.data["id"], "tiles")
        if tiles is None:
            return ""
        middle = QgsGeometry.fromPointXY(
            QgsPointXY(rect.center().x(), rect.center().y()))
        for f in tiles.getFeatures():
            if f.hasGeometry() and f.geometry().intersects(middle):
                return str(f["tile_id"])
        return ""

    # ----------------------------------------------------------- editing
    def too_small(self, rect):
        side = self.smallest.value()
        wide = self.geometry.measure.measureLine(
            QgsPointXY(rect.xMinimum(), rect.yMinimum()),
            QgsPointXY(rect.xMaximum(), rect.yMinimum()))
        tall = self.geometry.measure.measureLine(
            QgsPointXY(rect.xMinimum(), rect.yMinimum()),
            QgsPointXY(rect.xMinimum(), rect.yMaximum()))
        # A failed measurement must not delete. It fails as zero, and as NaN
        # or infinity, which a plain "<= 0" would let through: a box measured
        # NaN would never be too small and would be stored with no width and
        # no height.
        if not (0 < wide < float("inf") and 0 < tall < float("inf")):
            wide = rect.width() / max(self.geometry.pixel_crs[0], 1e-12) \
                * self.geometry.pixel_m[0]
            tall = rect.height() / max(self.geometry.pixel_crs[1], 1e-12) \
                * self.geometry.pixel_m[1]
        return wide < side or tall < side, wide, tall

    def create_box(self, rect):
        layer = self.boxes
        if layer is None or self.class_name is None:
            return
        small, wide, tall = self.too_small(rect)
        if small:
            iface.messageBar().pushMessage(
                NAME, "%.2f by %.2f m: smaller than the %.2f m you asked for"
                % (wide, tall, self.smallest.value()), level=LEVEL_INFO, duration=3)
            return
        if not layer.isEditable():
            layer.startEditing()
        layer.beginEditCommand("box %s" % self.class_name)
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromRect(rect))
        f["class_name"] = self.class_name
        f["class_code"] = self.current_code()
        f["tile_id"] = self.tile_holding(rect)
        f["operator"] = self.panel.who_is_drawing()
        if "pass_no" in layer.fields().names():
            f["pass_no"] = self.panel.which_pass()
        f["width_m"] = round(wide, 3)
        f["height_m"] = round(tall, 3)
        f["created"] = now()
        layer.addFeature(f)
        layer.endEditCommand()
        layer.triggerRepaint()
        self.show_tally()
        self.keep_safe()
        log("box %s, %.2f by %.2f m" % (self.class_name, wide, tall))
        self.box_note("box", rect, class_code=self.current_code(),
                      tile_id=f["tile_id"] or "")
        self.ticked()

    def keep_safe(self):
        """Write the boxes that are not saved into the recovery net.

        Boxes live in an edit buffer like the polygons, and a crash loses the
        buffer. The net is brought up to date at every edit: when a box is
        drawn, stretched, given another class or deleted, when the last edit
        is undone and when the boxes are saved. Otherwise after a crash those
        edits would come back as they had been at the last stroke, without a
        word. Undoing the last edit leaves the buffer as it was before it,
        and a buffer with nothing pending removes the file."""
        try:
            self.panel.keep_safe()
        except Exception as err:
            log("the recovery snapshot was not brought up to date: %s" % err)

    def reshape_box(self, rect):
        layer = self.boxes
        if layer is None or self.selected is None:
            return
        if self.not_yours(self.selected):
            return
        small, wide, tall = self.too_small(rect)
        if small:
            iface.messageBar().pushMessage(
                NAME, "a box cannot be smaller than %.2f m" % self.smallest.value(),
                level=LEVEL_WARNING, duration=3)
            return
        if not layer.isEditable():
            layer.startEditing()
        layer.beginEditCommand("reshape box")
        layer.changeGeometry(self.selected, QgsGeometry.fromRect(rect))
        fields = layer.fields()
        for name, value in (("width_m", round(wide, 3)),
                            ("height_m", round(tall, 3)),
                            ("tile_id", self.tile_holding(rect))):
            index = fields.indexOf(name)
            if index >= 0:
                layer.changeAttributeValue(self.selected, index, value)
        layer.endEditCommand()
        layer.triggerRepaint()
        self.keep_safe()
        self.box_note("box_reshape", rect, tile_id=self.tile_holding(rect))
        self.ticked()

    def assign_class_at(self, point):
        hit = self.box_at(point)
        if hit is None or self.class_name is None:
            return
        if self.not_yours(hit.id()):
            return
        layer = self.boxes
        if not layer.isEditable():
            layer.startEditing()
        layer.beginEditCommand("reclass box")
        fields = layer.fields()
        for name, value in (("class_name", self.class_name),
                            ("class_code", self.current_code())):
            index = fields.indexOf(name)
            if index >= 0:
                layer.changeAttributeValue(hit.id(), index, value)
        layer.endEditCommand()
        layer.triggerRepaint()
        self.select_box(hit.id())
        self.show_tally()
        self.keep_safe()
        self.box_note("box_reclass", hit.geometry().boundingBox(),
                      class_code=self.current_code(),
                      from_code=hit["class_code"], tile_id=hit["tile_id"])
        self.ticked()

    def delete_selected(self):
        layer = self.boxes
        if layer is None or self.selected is None:
            iface.messageBar().pushMessage(
                NAME, "click a box first, then Delete", level=LEVEL_INFO, duration=2)
            return
        if self.not_yours(self.selected):
            return
        if not layer.isEditable():
            layer.startEditing()
        gone = layer.getFeature(self.selected)
        layer.beginEditCommand("delete box")
        layer.deleteFeature(self.selected)
        layer.endEditCommand()
        layer.triggerRepaint()
        self.select_box(None)
        if self.tool is not None:
            self.tool.show_selection()
        self.show_tally()
        self.keep_safe()
        try:
            self.box_note("box_delete", gone.geometry().boundingBox(),
                          from_code=gone["class_code"],
                          tile_id=gone["tile_id"])
        except Exception:
            self.box_note("box_delete", None)
        self.ticked()

    def undo(self):
        layer = self.boxes
        if layer is not None and layer.isEditable() and layer.undoStack().canUndo():
            layer.undoStack().undo()
            layer.triggerRepaint()
            self.select_box(None)
            if self.tool is not None:
                self.tool.show_selection()
            self.show_tally()
            self.keep_safe()
            time_mark(self, "undo", tool="key")

    def ticked(self):
        """One more change to the boxes. The net has been written already;
        this decides whether the package is written too, every so many
        changes, as Annotate does."""
        self.since_save += 1
        every = self.autosave.value()
        if every and self.since_save >= every:
            # Zeroed by a save that worked, not here: a refused one is tried
            # again at the next change.
            self.save(quiet=True)

    def save(self, quiet=False):
        """Write the boxes down, and say how it went: in the message bar, as
        Annotate does. Saying nothing, in the log only, would let a package
        that refused the boxes be found out when the work was already gone
        from the screen."""
        layer = self.boxes
        if layer is None:
            return
        written = 0
        if layer.isEditable():
            picked = self.selected_identity()
            if not layer.commitChanges():
                errors = layer.commitErrors()
                log("cannot save the boxes: %s" % errors)
                iface.messageBar().pushMessage(
                    NAME, "not everything could be saved. boxes: %s"
                    % "; ".join(errors[:3]), level=LEVEL_CRITICAL, duration=9)
                self.keep_safe()
                return
            written = 1
            self.reselect(picked)
        self.since_save = 0
        if quiet:
            log("boxes saved by itself")
        else:
            log("boxes saved")
            iface.messageBar().pushMessage(
                NAME, "saved, %d layer%s written"
                % (written, "" if written == 1 else "s"),
                level=LEVEL_INFO, duration=2)
        self.keep_safe()
        self.show_tally()
        time_mark(self, "save", tool="" if quiet else "button",
                  note="by itself" if quiet else "")

    def selected_identity(self):
        """What it takes to find the selected box again after a save: a box
        not yet saved has a temporary id, and the save gives it a new one."""
        layer = self.boxes
        if layer is None or self.selected is None or self.selected >= 0:
            return None
        f = layer.getFeature(self.selected)
        if f is None or not f.hasGeometry():
            return None
        return self.selected, f.geometry().asWkt(), f["created"]

    def reselect(self, picked):
        """Pick the box up again under the id the save gave it. If it cannot
        be told apart, nothing stays selected, which is better than a
        selection that points at nothing and a Delete that does nothing."""
        if picked is None:
            return
        old, wkt, created = picked
        found = None
        layer = self.boxes
        if layer is not None:
            for f in layer.getFeatures():
                if f.hasGeometry() and f["created"] == created \
                        and f.geometry().asWkt() == wkt:
                    found = f.id()
                    break
        self.select_box(found)
        if self.tool is not None:
            self.tool.show_selection()

    def unsaved(self):
        layer = self.boxes
        return layer is not None and layer.isEditable() and layer.isModified()

    # ----------------------------------------------------------- the tool
    def use_tool(self):
        if self.tool is None:
            self.tool = BoxTool(canvas(), self)
        self.b_tool.setChecked(True)
        self.tool.refresh_colour()
        canvas().setMapTool(self.tool)
        log("boxes: drag to draw, click to pick up, corners to stretch, "
            "Delete to remove, %s and click to change the class." % ctrl_name())

    def release_tools(self):
        time_close(self, "objects")
        hand_back_tool(getattr(self, "_tool_before", None), (self.tool,))
        layer = self.boxes
        if layer is not None:
            layer.removeSelection()
