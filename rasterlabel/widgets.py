"""rasterlabel.widgets

The small controls the panel is built from.
"""
from qgis.PyQt.QtCore import QEvent, QObject, QSize, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QLabel, QLineEdit,
                                 QPushButton, QRadioButton, QSizePolicy)

from .theme import chip_height, text_width
from .view import step, zoom


class PassBox(QComboBox):
    """The passes there are, to pick one from.

    It answers value() and setValue() and says valueChanged, the way the
    spin box it replaced did, so what asks "which pass" does not care which
    one it is asking. setValue of a pass the list lacks adds it: a reading
    held for the session, or an old campaign's pass, has to be reachable
    even when nobody wrote it down."""

    valueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentIndexChanged.connect(self._said)

    def _said(self, *args):
        self.valueChanged.emit(self.value())

    def value(self):
        n = self.currentData()
        return int(n) if n is not None else 1

    def values(self):
        return [int(self.itemData(i)) for i in range(self.count())]

    def fill(self, numbers, keep=None):
        """Offer these passes and stand on keep when it is one of them, else
        on the first. Says nothing while it does."""
        numbers = sorted(set(int(n) for n in numbers)) or [1]
        keep = numbers[0] if keep not in numbers else keep
        self.blockSignals(True)
        self.clear()
        for n in numbers:
            self.addItem(str(n), n)
        self.setCurrentIndex(numbers.index(keep))
        self.blockSignals(False)

    def setValue(self, number):
        number = int(number)
        if number not in self.values():
            self.fill(self.values() + [number], number)
            self.valueChanged.emit(number)
            return
        self.setCurrentIndex(self.values().index(number))


class Keys(QObject):
    """Sees the key before the canvas and before the active map tool."""

    ARROWS = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
              Qt.Key.Key_Up: (0, 1), Qt.Key.Key_Down: (0, -1)}

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Type.KeyPress or not self.panel.keyboard.isChecked():
            return False
        k, mods = ev.key(), ev.modifiers()
        if k in (Qt.Key.Key_PageUp, Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            zoom(True)
            return True
        if k in (Qt.Key.Key_PageDown, Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            zoom(False)
            return True
        if k in self.ARROWS:
            if mods & (Qt.KeyboardModifier.ControlModifier
                       | Qt.KeyboardModifier.AltModifier
                       | Qt.KeyboardModifier.MetaModifier):
                return False
            dx, dy = self.ARROWS[k]
            step(dx, dy, self.panel.step_percent(), bool(mods & Qt.KeyboardModifier.ShiftModifier))
            return True
        return False


#  The annotation module
# =====================================================================
class ClassChip(QPushButton):
    """A class you can pick with one click and rename with two.

    A legend decided before the first stroke and changed, if at all, in a
    dialog at the other end of the panel is the wrong shape
    for the work: nobody opening a scene they have not seen knows how many
    classes are in it. They find out at the third frame, in front of something
    that fits none of the names they invented an hour earlier, and at that
    moment the legend has to be one gesture away from the hand that is
    drawing, not four."""

    def __init__(self, section, code, parent=None):
        super().__init__(parent)
        self.section = section
        self.code = code

    def mouseDoubleClickEvent(self, ev):
        self.section.start_rename(self.code)
        ev.accept()


class NameBox(QLineEdit):
    """A chip while its name is being typed. Enter keeps it, Esc puts it back.

    Losing the focus keeps it too, because a name typed and then clicked away
    from was still typed on purpose; the one way out without writing is Esc,
    and that is the one most people already try."""

    def __init__(self, text, keep, drop, parent=None):
        super().__init__(text, parent)
        self.keep, self.drop = keep, drop
        self.setFixedHeight(chip_height(self))
        self.selectAll()
        self.returnPressed.connect(self._keep)
        self.editingFinished.connect(self._keep)

    def _keep(self):
        if self.keep is not None:
            keep, self.keep, self.drop = self.keep, None, None
            keep(self.text())

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            drop = self.drop
            self.keep = self.drop = None
            if drop is not None:
                drop()
            ev.accept()
            return
        super().keyPressEvent(ev)


class OneLine(QLabel):
    """A line of plain words that is cut to the room it has, never folded
    and never let past the edge.

    Cut at the end with an ellipsis, or in the middle for a path, whose two
    ends are the parts that say which folder it is. The whole text is in the
    tooltip, unless a tooltip of its own was given. The width it asks for is
    nothing, so a long text cannot make the panel wider."""

    def __init__(self, text="", middle=False, parent=None):
        super().__init__(parent)
        self._full = ""
        self._tip = None
        self._mode = (Qt.TextElideMode.ElideMiddle if middle
                      else Qt.TextElideMode.ElideRight)
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.setSizePolicy(policy)
        self.setMinimumWidth(1)
        self.set_text(text)

    def set_text(self, text, tip=None):
        self._full = text or ""
        self._tip = tip
        self._cut()

    def full_text(self):
        return self._full

    def _cut(self):
        # two pixels kept back: a word that fitted to the pixel was drawn
        # with its last letter clipped under Night Mapping on QGIS 3
        room = max(self.contentsRect().width() - 2, 1)
        shown = self.fontMetrics().elidedText(self._full, self._mode, room)
        QLabel.setText(self, shown)
        if self._tip is not None:
            self.setToolTip(self._tip)
        else:
            self.setToolTip(self._full if shown != self._full else "")

    def resizeEvent(self, ev):
        QLabel.resizeEvent(self, ev)
        self._cut()

    def changeEvent(self, ev):
        """Cut again when the font changes: a theme's sheet gives the label
        its font after the text was first cut to the width."""
        QLabel.changeEvent(self, ev)
        if ev.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._cut()

    def minimumSizeHint(self):
        hint = QLabel.minimumSizeHint(self)
        return QSize(1, hint.height())


# where a tick box's words are broken onto the next line
LINE_BREAK = "\n"


class Wrapping:
    """The words of a tick box or a radio button that go onto a second line
    when the box is narrower than they are, instead of being cut off at its
    edge; WrapTick and WrapRadio are this over a QCheckBox and a
    QRadioButton.

    Qt draws a button's words on one line whatever room it has, and cuts
    them without a sign: "blind: hide earlier passes" lost "passes" at two
    hundred and sixty pixels on a Linux desktop, whose font is larger than
    the one the settings were laid out with. The words are broken between
    two words, never inside one, from the width the box is given, and put
    back on one line as soon as it is wide enough again. text() is always
    the words as they were given.

    room, for a box with something beside it on its row (the lock beside
    "paint under the others"), says how wide the words may be from the
    width of the row: such a box is given only what it asks for, so its own
    width would never grow back."""

    def __init__(self, words="", parent=None, room=None):
        super().__init__(words, parent)
        self._words = words or ""
        self._room = room
        self.setAccessibleName(self._words)

    def text(self):
        return self._words

    def setText(self, words):
        self._words = words or ""
        self.setAccessibleName(self._words)
        super().setText(self._words)
        self.rewrap()

    def watch_row(self, row):
        """Wrap again whenever the row the box shares changes width."""
        row.installEventFilter(self)

    def eventFilter(self, watched, ev):
        if ev.type() == QEvent.Type.Resize:
            self.rewrap()
        return False

    def _chrome(self):
        """What the box takes beside its words: the tick and the gap after
        it, as the style in use draws them, read off the box itself."""
        shown = super().text()
        widest = max([text_width(self.fontMetrics(), line)
                      for line in shown.split(LINE_BREAK)] or [0])
        return max(0, super().sizeHint().width() - widest)

    def rewrap(self):
        room = self._room() if self._room is not None else self.width()
        if room <= 0:
            return
        avail = room - self._chrome() - 1
        metrics = self.fontMetrics()
        lines, line = [], ""
        for word in self._words.split():
            trial = (line + " " + word) if line else word
            if line and text_width(metrics, trial) > avail:
                lines.append(line)
                line = word
            else:
                line = trial
        if line:
            lines.append(line)
        shown = LINE_BREAK.join(lines) if lines else self._words
        if shown != super().text():
            super().setText(shown)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.rewrap()

    def changeEvent(self, ev):
        super().changeEvent(ev)
        if ev.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.rewrap()

    def minimumSizeHint(self):
        hint = super().sizeHint()
        widest = max([text_width(self.fontMetrics(), w)
                      for w in self._words.split()] or [0])
        return QSize(self._chrome() + widest + 1, hint.height())


class WrapTick(Wrapping, QCheckBox):
    """A tick box whose words wrap (see Wrapping)."""


class WrapRadio(Wrapping, QRadioButton):
    """A radio button whose words wrap (see Wrapping)."""


def narrow_tick(words, parent=None):
    """A WrapTick for a window that may be made narrower than its words.

    A tick box asks its layout for the width of its words on one line, and a
    layout will not give it less: a WrapTick in a grid held the window at the
    width of "the dataset card, with the pixel counts of this mask". Told it
    may shrink, it is given the room there is, wraps its words to it, and
    asks only for the widest word."""
    box = WrapTick(words, parent)
    box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    return box


def narrow_radio(words, parent=None):
    """The same for a radio button: given the room there is, it wraps its
    words, and asks only for the widest word."""
    button = WrapRadio(words, parent)
    button.setSizePolicy(QSizePolicy.Policy.Preferred,
                         QSizePolicy.Policy.Fixed)
    return button
