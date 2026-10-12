"""rasterlabel.layout

The layouts: buttons that wrap, a slider that gets a row of its own when it
would be a stub, and cards dealt into columns.
"""
from qgis.PyQt.QtCore import QRect, QSize, Qt
from qgis.PyQt.QtWidgets import (QHBoxLayout, QLayout, QSizePolicy,
                                 QSpacerItem, QVBoxLayout, QWidget)

from .constants import (DECK_MAX, DECK_MIN, FREE_W, GROUP_GAP, ONE_COLUMN,
                        WIDE_CELL)


class FlowLayout(QLayout):
    """Lays its buttons out left to right and wraps when the row is full.

    Qt has no layout of this kind, and the panel needs one. It can be widened,
    narrowed, torn out of the frame and dropped on a second screen, and a
    layout worked out once at build time is a guess that goes wrong the first
    time somebody drags the edge. This one is asked again at every resize.

    Groups are kept apart by a wider gap, and the gap is dropped when the
    group happens to start a row, where the edge already separates it.

    With uniform on it stops being a ragged flow and becomes a grid: every
    button is given the width of the longest word among them, the row holds as
    many as the panel is wide enough for, and what is left over is shared out
    so the columns meet the edge. Two of them at three hundred pixels, three at
    four hundred, four at five: the count follows the drag, the buttons keep
    the same size as each other whatever it turns out to be. A group gap would
    put the columns out of line, so in this mode there is none; what divides
    one kind of command from another is the frame around it.

    counts, in the grid, is the column counts it may use, when only some of
    them make a clean shape: six commands written as two rows of three read
    well in three columns or in six, and in five they leave one alone on a
    row of its own; two modules side by side are halves of the row or one
    over the other. The grid then takes the largest of them that fits, and
    only falls back to whatever fits when none of them does. A short last
    row in such a grid is spread over the whole width, so the shape never
    ends in a hole."""

    def __init__(self, spacing=4, gap=GROUP_GAP, uniform=False, counts=()):
        super().__init__()
        self.items = []
        self.extra = {}
        self.gap = gap
        self.uniform = uniform
        self.counts = tuple(sorted(counts))
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # ---- the six methods a QLayout has to answer
    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)        # neither direction

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        """The widest single button: below that nothing can be laid out at
        all, and the panel must be allowed to say so."""
        size = QSize(0, 0)
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        if self.uniform and self.items:
            size = size.expandedTo(QSize(*self.cell()))
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    def cell(self):
        """One cell of the grid: as wide as the longest word needs, as tall as
        the tallest button.

        The width is read from each button's own minimum rather than from its
        hint, because a button let out of its fixed size to be stretched still
        remembers, in that minimum, exactly how much room its word asked for.
        Ask the hint instead and Qt answers with the style's idea of a button,
        which is wider, and the grid grows a little every time it is measured."""
        width = height = 0
        for item in self.items:
            hint = item.sizeHint()
            widget = item.widget()
            want = widget.minimumWidth() if widget is not None else 0
            width = max(width, want or hint.width())
            height = max(height, hint.height())
        return width, height

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._lay(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._lay(rect, False)

    # ---- adding
    def add(self, widget, new_group=False):
        if new_group and self.items:
            self.extra[len(self.items)] = self.gap
        if self.uniform:
            # dress() nails a button to the width of its word. In the grid the
            # width is decided by the row, so the ceiling has to come off;
            # the floor stays, and is what cell() reads back.
            widget.setMinimumWidth(widget.minimumWidth() or widget.width()
                                   or widget.sizeHint().width())
            widget.setMaximumWidth(FREE_W)
        self.addWidget(widget)

    def _lay(self, rect, measure_only):
        if self.uniform:
            return self._grid(rect, measure_only)
        margins = self.contentsMargins()
        left = rect.x() + margins.left()
        right = rect.right() - margins.right()
        x, y, line = left, rect.y() + margins.top(), 0
        for i, item in enumerate(self.items):
            hint = item.sizeHint()
            before = self.extra.get(i, 0) if x > left else 0
            if line and x + before + hint.width() > right + 1:
                x, y, line, before = left, y + line + self._spacing, 0, 0
            if not measure_only:
                item.setGeometry(QRect(x + before, y, hint.width(), hint.height()))
            x += before + hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y() + margins.bottom()

    def columns(self, room):
        """How many buttons fit across, given that much room. Never none, and
        never more than there are buttons to put in them."""
        cell_w = self.cell()[0]
        if not self.items or cell_w <= 0:
            return 1
        fit = int((room + self._spacing) // (cell_w + self._spacing))
        fit = max(1, min(fit, len(self.items)))
        allowed = [n for n in self.counts if n <= fit]
        return allowed[-1] if allowed else fit

    def _grid(self, rect, measure_only):
        """The same buttons, all one size, in as many columns as fit.

        The leftover pixels of a row are shared out one each from the left
        instead of being dropped at the end, so the last column lands exactly
        on the edge and no column is ever more than a pixel wider than its
        neighbour. Stretching has a ceiling: on a wide screen six commands
        should not become six banners, so past WIDE_CELL times their word they
        stop growing and the row simply ends where it ends.

        Except in a grid held to its counts: there the keys are wider than
        their words on purpose, to keep a shape, and every row of the shape
        meets the edge, the way the rows of the panel's blocks do one under
        the other."""
        margins = self.contentsMargins()
        left = rect.x() + margins.left()
        top = rect.y() + margins.top()
        room = rect.width() - margins.left() - margins.right()
        cell_w, cell_h = self.cell()
        if not self.items:
            return margins.top() + margins.bottom()
        cols = self.columns(room)
        rows = (len(self.items) + cols - 1) // cols
        spread = room - self._spacing * (cols - 1)
        wide, rest = divmod(max(spread, cell_w * cols), cols)
        ceiling = int(cell_w * WIDE_CELL)
        if wide > ceiling and not self.counts:
            wide, rest = ceiling, 0
        if not measure_only:
            short = len(self.items) - (rows - 1) * cols
            for i, item in enumerate(self.items):
                r, c = divmod(i, cols)
                width, extra = wide, rest
                if self.counts and r == rows - 1 and short < cols:
                    # The last row of a keypad held to its shape, when it is
                    # short: its keys share the whole row instead of leaving
                    # a hole at the end of it. Five keys are three and two,
                    # the two half a row each, and nothing is ever left alone
                    # on a row of its own with the edge a cell away.
                    width, extra = divmod(
                        max(room - self._spacing * (short - 1),
                            cell_w * short), short)
                x = left + sum(width + (1 if k < extra else 0) + self._spacing
                               for k in range(c))
                item.setGeometry(QRect(x, top + r * (cell_h + self._spacing),
                                       width + (1 if c < extra else 0), cell_h))
        return (rows * cell_h + (rows - 1) * self._spacing
                + margins.top() + margins.bottom())


class KeyRow(QLayout):
    """One row of keys that shares the width it is given, and keeps every
    word whole.

    The keys share the row equally whenever an equal share holds the longest
    word among them, which is the keypad's shape and what every row looks
    like at the widths most panels have. A narrower row, or a font larger
    than the one the keypad was drawn for (DejaVu at twelve points, as a
    Linux desktop gives it, is half as wide again as Segoe UI at nine), and
    the equal shares would cut the longest word: then each key gets what its
    own word needs and the room left over is shared out equally, so the row
    still meets both edges. Only when even that does not fit does the row
    wrap onto a second line.

    With a filler, the first widget added (the list of frames beside Go, Note
    and Delete), the keys keep one width, the one they were dressed to when
    there is room for it, and the filler takes what they leave. Short of
    room the keys come down to the width their words need, and the filler
    to its least.

    need(widget) is the least width that keeps a key's word whole with the
    air the style keeps round it, least(widget) the width under which the
    word would touch the frame: a row short of room for the first comes
    down to the second before it wraps. Both are asked again at every
    pass, so a theme that pads the buttons is measured as it is."""

    def __init__(self, need, spacing=4, filler=False, least=None):
        super().__init__()
        self.items = []
        self.need = need
        self.least = least or need
        self.filler = filler
        self.dressed = {}
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def add(self, widget):
        """A key, or with filler on, the filler first. A key nailed to the
        width of its word by dress() is let out of it: the row decides."""
        if not (self.filler and not self.items):
            self.dressed[id(widget)] = widget.width() or widget.minimumWidth()
            widget.setMinimumWidth(0)
            widget.setMaximumWidth(FREE_W)
        self.addWidget(widget)

    def _parts(self):
        widgets = [item.widget() for item in self.items]
        if self.filler and widgets:
            return widgets[0], widgets[1:]
        return None, widgets

    def _needs(self, keys, least=False):
        fn = self.least if least else self.need
        return [max(1, int(fn(k))) for k in keys]

    def _height(self):
        return max([item.sizeHint().height() for item in self.items] or [0])

    def minimumSize(self):
        filler, keys = self._parts()
        needs = self._needs(keys, least=True)
        if filler is None:
            width = max(needs or [0])
        else:
            width = filler.minimumWidth() + sum(needs) \
                + self._spacing * len(keys)
        return QSize(width, self._height())

    def sizeHint(self):
        filler, keys = self._parts()
        needs = self._needs(keys)
        width = sum(needs) + self._spacing * max(0, len(keys) - 1)
        if filler is not None:
            width += filler.minimumWidth() + self._spacing
        return QSize(width, self._height())

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._lay(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._lay(rect, False)

    @staticmethod
    def _shares(room, needs, spacing):
        """The widths of keys sharing a row of that much room: equal when an
        equal share holds every word, each word's need and an equal part of
        what is left otherwise. None when even the needs do not fit."""
        n = len(needs)
        free = room - spacing * (n - 1)
        if n * max(needs) <= free:
            wide, rest = divmod(free, n)
            return [wide + (1 if k < rest else 0) for k in range(n)]
        if sum(needs) <= free:
            more, rest = divmod(free - sum(needs), n)
            return [need + more + (1 if k < rest else 0)
                    for k, need in enumerate(needs)]
        return None

    def _lay(self, rect, measure_only):
        filler, keys = self._parts()
        tall = self._height()
        left, top, room = rect.x(), rect.y(), rect.width()
        if not keys:
            if filler is not None and not measure_only:
                filler.setGeometry(QRect(left, top, room, tall))
            return tall if filler is not None else 0
        needs = self._needs(keys)
        if filler is not None:
            free = room - filler.minimumWidth() - self._spacing * len(keys)
            dressed = max(self.dressed.get(id(k), 0) for k in keys)
            if dressed and len(keys) * dressed <= free:
                widths = [dressed] * len(keys)
            elif len(keys) * max(needs) <= free:
                widths = [max(needs)] * len(keys)
            elif sum(needs) <= free:
                widths = needs
            else:
                widths = self._needs(keys, least=True)
            if not measure_only:
                used = sum(widths) + self._spacing * len(keys)
                filler.setGeometry(QRect(left, top, max(1, room - used), tall))
                x = left + max(1, room - used) + self._spacing
                for k, w in zip(keys, widths):
                    k.setGeometry(QRect(x, top, w, tall))
                    x += w + self._spacing
            return tall
        # one line if the row holds them, with the air the style keeps or
        # with the least, else as many lines as it takes, each one shared
        # out the same way
        if self._shares(room, needs, self._spacing) is None:
            needs = self._needs(keys, least=True)
        lines, line = [], []
        for k, need in zip(keys, needs):
            trial = [n for _, n in line] + [need]
            if line and self._shares(room, trial, self._spacing) is None:
                lines.append(line)
                line = []
            line.append((k, need))
        lines.append(line)
        y = top
        for line in lines:
            widths = self._shares(room, [n for _, n in line], self._spacing) \
                or [n for _, n in line]
            if not measure_only:
                x = left
                for (k, _), w in zip(line, widths):
                    k.setGeometry(QRect(x, y, w, tall))
                    x += w + self._spacing
            y += tall + self._spacing
        return y - self._spacing - top


class SliderRow(QLayout):
    """A word, a slider and the number box that shows its value: on one row
    while the slider keeps room enough to be used, and on two when it would
    not, the word and the box on the first and the slider the whole width of
    the second.

    On one line the row at 260 pixels with a Linux desktop's font (DejaVu is
    half as wide again as Segoe UI) leaves the slider 22 pixels, a stub with
    a handle and no track, and the box a pixel from the edge. least() is
    the narrowest slider worth having, asked at every pass so that it
    follows the font it is drawn in; the row stays one line exactly as
    long as the word, that slider and the box, with the air between them,
    fit the width it is given."""

    def __init__(self, least, spacing=6):
        super().__init__()
        self.items = []
        self.least = least
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def add(self, word, slider, box):
        for widget in (word, slider, box):
            self.addWidget(widget)

    def _sizes(self):
        """(the word, the slider, the box) as sizes, or None before the
        three are in."""
        if len(self.items) != 3:
            return None
        return [item.sizeHint() for item in self.items]

    def _least(self):
        return max(1, int(self.least()))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._lay(QRect(0, 0, width, 0), True)

    def sizeHint(self):
        sizes = self._sizes()
        if sizes is None:
            return QSize(0, 0)
        word, slider, box = sizes
        wide = word.width() + box.width() + 2 * self._spacing \
            + max(self._least(), slider.width())
        return QSize(wide, max(s.height() for s in sizes))

    def minimumSize(self):
        sizes = self._sizes()
        if sizes is None:
            return QSize(0, 0)
        word, slider, box = sizes
        wide = max(word.width() + self._spacing + box.width(), self._least())
        return QSize(wide, max(s.height() for s in sizes))

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._lay(rect, False)

    @staticmethod
    def _put(item, x, y, w, row_high):
        """The item at x, centred on a row row_high tall that starts at y."""
        high = item.sizeHint().height()
        item.setGeometry(QRect(x, y + max(0, row_high - high) // 2, w, high))

    def _lay(self, rect, measure_only):
        sizes = self._sizes()
        if sizes is None:
            return 0
        word, slider, box = sizes
        gap, room = self._spacing, rect.width()
        left, top = rect.x(), rect.y()
        if word.width() + box.width() + 2 * gap + self._least() <= room:
            high = max(s.height() for s in sizes)
            if not measure_only:
                x = left
                self._put(self.items[0], x, top, word.width(), high)
                x += word.width() + gap
                track = room - word.width() - box.width() - 2 * gap
                self._put(self.items[1], x, top, track, high)
                self._put(self.items[2], left + room - box.width(), top,
                          box.width(), high)
            return high
        above = max(word.height(), box.height())
        if not measure_only:
            self._put(self.items[0], left, top, word.width(), above)
            self._put(self.items[2], left + room - box.width(), top,
                      box.width(), above)
            self.items[1].setGeometry(QRect(left, top + above + gap, room,
                                            slider.height()))
        return above + gap + slider.height()


class Deck(QWidget):
    """The body of a module, dealt into as many columns as the width holds.

    A module docked at the side of the map is a narrow strip and its pieces
    stack, one under the other, the way they were written. The same module
    dragged to the top of the window is wide and low, and then stacking is
    exactly the wrong thing: the eye has to travel down a column while the
    whole right half of the screen sits empty. So the pieces are dealt out
    sideways instead, into two, three or four columns, balanced by how much
    room each of them asks for. The pieces themselves never change: only how
    they are dealt."""

    def __init__(self, minimum=DECK_MIN, most=DECK_MAX, gap=16):
        super().__init__()
        self.pieces = []            # (layout or widget, weight)
        self.minimum = minimum
        self.most = most
        self.after = None           # what to tell once the columns have moved
        self._columns = 0
        self.strip = QHBoxLayout(self)
        self.strip.setContentsMargins(0, 0, 0, 0)
        self.strip.setSpacing(gap)
        self.columns = []
        self.struts = []
        for _ in range(most):
            column = QVBoxLayout()
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(7)
            # A column in use is never narrower than this. Without it a column
            # holding nothing but a few short chips shrinks to the width of the
            # chips and its neighbour swallows the rest of the strip.
            column.addStretch(1)
            strut = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
            column.addSpacerItem(strut)
            self.strip.addLayout(column, 0)
            self.columns.append(column)
            self.struts.append(strut)
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return self.strip.hasHeightForWidth()

    def heightForWidth(self, width):
        """A module whose buttons wrap is taller when it is narrow, and the box
        above has to be told so before it decides how much room to give it.
        Without this the deck is handed the height it asked for at some other
        width, and its pieces are drawn one on top of another."""
        return self.strip.heightForWidth(width)

    def minimumSizeHint(self):
        return self.strip.minimumSize()

    def sizeHint(self):
        return self.strip.sizeHint()

    def room(self):
        """The width one column has. Taken from the deck and the number of
        columns, never from what is inside them: a piece whose own size decided
        the width it is measured against would chase its own tail, growing and
        shrinking at every pass of the layout."""
        used = max(1, self._columns)
        return max(140, (self.width() - self.strip.spacing() * (used - 1)) // used)

    def add(self, piece, weight=1):
        """A piece is either a widget or a whole layout. Layouts are welcome
        on purpose: the class chips must not be wrapped in a widget of their
        own, because a widget keeps the height it was given when the legend
        changes and the last row is drawn over whatever comes next."""
        self.pieces.append((piece, weight))

    def columns_for(self, width):
        if ONE_COLUMN:
            return 1
        return max(1, min(self.most, len(self.pieces),
                          max(1, int(width)) // self.minimum))

    def split(self, wanted):
        """Cut the pieces into that many columns, in order, keeping the weight
        as even as the order allows. Order is never broken: a panel whose
        pieces change places when it is resized is worse than one that leaves
        a column a little longer than its neighbour."""
        total = float(sum(w for _, w in self.pieces)) or 1.0
        target = total / wanted
        plan, group, used = [], [], 0.0
        for i, (piece, weight) in enumerate(self.pieces):
            left = len(self.pieces) - i          # pieces not yet placed
            room = wanted - len(plan)            # columns not yet closed
            # A column must be closed when every piece still in hand is needed
            # to open one of the columns still to come, and it may be closed
            # whenever what is left can still fill them.
            must = left < room
            can = room > 1 and left >= room - 1
            if group and can and (must or used + weight / 2.0 > target):
                plan.append(group)
                group, used = [], 0.0
            group.append(piece)
            used += weight
        plan.append(group)
        while len(plan) < wanted:
            plan.append([])
        return plan

    def deal(self, force=False):
        wanted = self.columns_for(self.width())
        if wanted == self._columns and not force:
            return
        self._columns = wanted
        tail = 2                                 # the stretch and the strut
        for column in self.columns:
            while column.count() > tail:
                item = column.takeAt(0)
                inner = item.layout() if item is not None else None
                # A layout taken out of another one keeps it as its parent, and
                # Qt then refuses to put it anywhere else. Clearing the parent
                # is what makes a piece movable from one column to another.
                if inner is not None:
                    inner.setParent(None)
        for index, group in enumerate(self.split(wanted)):
            column = self.columns[index]
            for piece in group:
                if isinstance(piece, QLayout):
                    column.insertLayout(column.count() - tail, piece)
                else:
                    column.insertWidget(column.count() - tail, piece)
        for i in range(self.most):
            self.strip.setStretch(i, 1 if i < wanted else 0)
            self.struts[i].changeSize(self.minimum - 24 if i < wanted else 0, 0,
                                      QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
            self.columns[i].invalidate()
        self.strip.activate()
        if self.after is not None:
            self.after()

    def resizeEvent(self, ev):
        QWidget.resizeEvent(self, ev)
        self.deal()
