"""rasterlabel.theme

Colours, fonts and the boxes the controls sit in.
"""
import re

from qgis.PyQt.QtCore import (QEvent, QObject, QPointF, QRectF, QSize, Qt,
                              QTimer)
from qgis.PyQt.QtGui import (QBrush, QColor, QFont, QFontMetrics, QIcon,
                             QPainter, QPalette, QPen, QPixmap, QPolygonF)
from qgis.PyQt.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout,
                                 QLabel, QLayout, QPushButton, QSizePolicy,
                                 QStyle, QStyleOptionButton, QVBoxLayout,
                                 QWidget)

from .constants import (BANNER_H, CLASS_H, GROUP_GAP, ICON_H, NAME, PAD,
                        PRIMARY_H)
from .layout import FlowLayout, KeyRow


# ---------------------------------------------------------------- the look
#  Colours are read from the theme QGIS is running with, never written in.
#  A panel painted for the light theme turns unreadable the moment somebody
#  switches to Night Mapping, and the accent is the one the whole program
#  already uses for selection, so the panel belongs to it rather than shouting
#  over it.
#
#  And as little as possible is painted at all. Buttons, combo boxes, spin
#  boxes, line edits and tick boxes in their ordinary state are drawn by
#  QGIS's own style, so the panel looks like every other dock beside it, in
#  the light theme, in Night Mapping and in Blend of Gray. A stylesheet rule
#  that reaches a spin box takes its arrows away under Fusion; one that paints
#  the normal state of a button turns it into a light slab inside a dark
#  theme. What is painted here is only what carries meaning: the tool or
#  module in hand (the accent), what cannot be pressed (it steps back), and
#  what destroys work (it says so, before the pointer gets there).
def mix(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


def luminance(colour):
    """The relative luminance of the WCAG, from 0 for black to 1 for white."""
    c = QColor(colour)

    def channel(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(c.red()) + 0.7152 * channel(c.green())
            + 0.0722 * channel(c.blue()))


def contrast(a, b):
    """How far apart two colours read, from 1 (the same) to 21."""
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def ink_on(colour):
    """The ink that reads best on a fill: white or black, whichever is
    further from it. Chosen by contrast and not by brightness, which wrote
    white on a mid grey or a ripe brown where black reads twice as well.
    Black and not a near black: on the fills halfway between the two, a
    brown like crust, near black fell under 4.5 to 1 where black still
    clears it, and that is the colour every fill can be."""
    light, dark = "#ffffff", "#000000"
    return light if contrast(light, colour) >= contrast(dark, colour) \
        else dark


def quieter(text, ground, t, least=4.5):
    """The text colour taken towards the ground by t, but never so far that
    it drops under the contrast small writing needs."""
    while t > 0.02 and contrast(mix(text, ground, t), ground) < least:
        t -= 0.04
    return mix(text, ground, max(t, 0.0))


def _theme_colour(selector, prop):
    """A colour the application stylesheet gives one kind of widget, or None.

    QGIS's dark themes do not paint through the palette: Night Mapping
    reports a Window of #535353 and paints its docks #323232, and it writes
    the labels in a grey of its own. Colours mixed from the palette alone came
    out for a ground the panel never stands on. The theme's own rules are
    read instead, where it has them."""
    try:
        sheet = QApplication.instance().styleSheet() or ""
    except Exception:
        return None
    found = None
    for block in sheet.split("}"):
        if "{" not in block:
            continue
        head, body = block.split("{", 1)
        names = [n.strip() for n in head.split(",")]
        if selector not in names:
            continue
        for part in body.split(";"):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            value = value.strip()
            if key.strip() == prop and value.startswith("#"):
                colour = QColor(value.split()[0])
                if colour.isValid():
                    found = colour
    return found


def _button_grounds():
    """Every colour the theme paints the face of a button with.

    Night Mapping paints its buttons with a gradient from #565656 to #464646
    and says #efefef in the palette, which it never shows; Fusion and the
    light theme paint the palette's Button. Words written on a button have to
    read on all of them, so all of them are given."""
    found = []
    try:
        sheet = QApplication.instance().styleSheet() or ""
    except Exception:
        sheet = ""
    for block in sheet.split("}"):
        if "{" not in block:
            continue
        head, body = block.split("{", 1)
        names = [n.strip() for n in head.split(",")]
        if "QPushButton" not in names:
            continue
        for part in body.split(";"):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            if key.strip() in ("background", "background-color"):
                found += [QColor(c) for c in
                          re.findall(r"#[0-9a-fA-F]{6}\b", value)]
    if not found:
        found = [QApplication.palette().color(QPalette.ColorRole.Button)]
    return found


def readable_on(colour, grounds, least=4.5):
    """The colour, made lighter on dark grounds or darker on light ones until
    it reads on every one of them."""
    colour = QColor(colour)
    dark = sum(luminance(g) for g in grounds) / len(grounds) < 0.18
    towards = QColor("#ffffff" if dark else "#000000")
    for step in range(0, 101, 4):
        tried = mix(colour, towards, step / 100.0)
        if min(contrast(tried, g) for g in grounds) >= least:
            return tried
    return towards


def palette_colours():
    p = QApplication.palette()
    window = _theme_colour("QDockWidget", "background-color") \
        or p.color(QPalette.ColorRole.Window)
    text = _theme_colour("QLabel", "color") \
        or p.color(QPalette.ColorRole.WindowText)
    accent = p.color(QPalette.ColorRole.Highlight)
    on_accent = p.color(QPalette.ColorRole.HighlightedText)
    if contrast(on_accent, accent) < 3.0:
        on_accent = QColor(ink_on(accent))
    dark = window.lightness() < 128
    # The pressed tool or module in the accent, nudged until its own words
    # read on it: QGIS's blue under white is a shade too light for 9 points.
    checked = QColor(accent)
    for _ in range(8):
        if contrast(on_accent, checked) >= 4.5:
            break
        checked = checked.darker(107) if luminance(on_accent) > 0.4 \
            else checked.lighter(107)
    # The ring round a pressed button that has the keyboard: its own border
    # takes the place of the style's focus frame, so it is drawn here. It
    # stands between the fill and the panel and has to read against both:
    # white on QGIS's blue vanished into the light panel round it, the
    # theme's grey on Night Mapping's orange into the button.
    ring = max((text, on_accent, QColor("#000000"), QColor("#ffffff")),
               key=lambda c: min(contrast(c, checked), contrast(c, window)))
    # A grey button's words: far enough from the ground to be read, which
    # is how a grey button says why it is grey, and never so near the live
    # ones that it passes for one. Three to one where the theme's own words
    # stand far from the ground; in Night Mapping, whose words are grey to
    # begin with, two and a half times fainter than they are.
    off_least = min(3.0, contrast(text, window) / 2.5)
    t = 0.30
    while t < 0.9 and contrast(mix(text, window, t), window) > off_least:
        t += 0.02
    # Red that reads on the buttons it is written on, whatever the theme
    # paints them with: #ef7b70 cleared 4.5 to 1 on the dock and fell to 3
    # on Night Mapping's buttons, the three keys that destroy work being the
    # faintest in their rows.
    danger = readable_on("#ef7b70" if dark else "#b3261e",
                         _button_grounds() + [window])
    return {
        "window": window.name(),
        "text": text.name(),
        "dim": quieter(text, window, 0.42).name(),   # secondary, still legible
        "line": mix(text, window, 0.78).name(),      # hairlines and frames
        # A grey button steps back: no fill, a faint outline, faint words.
        # Fusion draws a disabled button as an enabled one with grey text,
        # and fifteen of them in a row looked like fifteen things to press.
        # No fill means the ground shows through, whatever the theme paints
        # the dock with, so it can never come out lighter than the live ones.
        "off_edge": mix(text, window, 0.82).name(),
        "off_text": mix(text, window, t).name(),
        "accent": accent.name(),
        "checked": checked.name(),
        "accent_edge": checked.darker(125).name(),
        "on_accent": on_accent.name(),
        "ring": ring.name(),
        "danger": danger.name(),
        # the guidance strip: warm, quiet, and readable in both themes. It is
        # not a warning, so it must not borrow the colour of one; it is the
        # line you read without looking for it.
        "step_bg": "#3a3320" if dark else "#fff6d5",
        "step_ink": "#f0dfa8" if dark else "#4a3c00",
        "step_edge": "#6b5c32" if dark else "#e0c96a",
        "dark": dark,
    }


def label_sheet():
    """The rules that are safe anywhere, the dialogs included: they name
    only labels and frames, by the object name the program gave them.

    Set on the panel itself, whose children the dialogs are, so a quiet line
    in a dialog is as quiet as one in the panel."""
    return """
    QLabel#section {
        color: %(text)s;
        font-weight: bold;
    }
    QLabel#subsection {
        color: %(dim)s;
        font-weight: bold;
    }
    QLabel#quiet { color: %(dim)s; }
    QLabel#warn { color: %(danger)s; }
    QLabel#step {
        background: %(step_bg)s;
        color: %(step_ink)s;
        border: 1px solid %(step_edge)s;
        border-radius: 4px;
        padding: 6px 8px;
    }
    QFrame[rule="true"] { color: %(line)s; background: %(line)s; border: none; }
    """ % palette_colours()


def stylesheet():
    """The rules for the controls of the panel, and only of the panel.

    Set on the panel's body and not on the panel: every dialog the panel
    opens is its child, and the keypad's compact buttons would cascade into
    them, leaving OK and Cancel thirty pixels wide. The body holds the
    panel's controls and none of its windows.

    No rule names a combo box, a spin box, a line edit or a tick box, and
    the buttons are named only in a state: tests/test_layout.py holds the
    sheet to both."""
    return """
    QPushButton:checked {
        background: %(checked)s;
        color: %(on_accent)s;
        border: 1px solid %(accent_edge)s;
        border-radius: 3px;
        font-weight: bold;
    }
    /* the border above replaces the style's focus frame, so the keyboard's
       place on a pressed button is drawn here */
    QPushButton:checked:focus { border: 2px solid %(ring)s; }
    QPushButton:disabled {
        background: transparent;
        color: %(off_text)s;
        border: 1px solid %(off_edge)s;
        border-radius: 3px;
    }
    QPushButton[danger="true"]:enabled { color: %(danger)s; }
    /* Measure greyed is drawn by the rule above, which puts the arrow of
       its menu in the bottom corner, over the last letter: it stays where
       the style puts it on the live key, after the word */
    QPushButton#measure::menu-indicator {
        subcontrol-origin: padding;
        subcontrol-position: center right;
        right: 4px;
    }
    QToolButton#fold {
        border: none;
        color: %(text)s;
        font-weight: bold;
        padding: 2px 0px;
    }
    QToolButton#fold:hover { color: %(accent)s; }
    QToolButton#unfold { border: none; padding: 0px; }
    /* with no border of their own they show no focus either: given one */
    QToolButton#fold:focus, QToolButton#unfold:focus {
        border: 1px solid %(accent)s;
        border-radius: 3px;
    }
    /* the open module: one hairline round it, and no room kept at the top
       for a title it does not have (Night Mapping keeps thirty pixels) */
    QGroupBox {
        border: 1px solid %(line)s;
        border-radius: 4px;
        margin-top: 0px;
        padding-top: 0px;
    }
    """ % palette_colours()


# ---------------------------------------------------------------- icons
#  QGIS's own icons, beside the word and never instead of it, and on six
#  buttons only: the four modules, which are what the blocks are for, and
#  Save and Delete, the two presses that decide what is kept. An icon on
#  every key was sixteen colours fighting in a narrow column, and it pushed
#  rows of four keys onto a second line. Every name below is in QGIS 3.36,
#  3.44 and 4.2 alike. A name a QGIS does not carry, or no QGIS at all (the
#  suites), gives no icon, and the button is the word alone.
ICONS = {
    "Annotate": "mActionCapturePolygon.svg",
    "Objects": "mActionRectangleExtent.svg",
    "Correct": "mActionToggleEditing.svg",
    "Cutouts": "algorithms/mAlgorithmClip.svg",
    "Save": "mActionSaveEdits.svg",
    "Delete": "mActionDeleteSelectedFeatures.svg",
}
ICON_PX = 16
_icon_cache = {}


def theme_icon(name):
    """QGIS's icon of that name, or None when there is none to be had."""
    if not name:
        return None
    if name in _icon_cache:
        return _icon_cache[name]
    icon = None
    try:
        from qgis.core import QgsApplication
        found = QgsApplication.getThemeIcon(name)
        if found is not None and not found.isNull() \
                and not found.pixmap(ICON_PX, ICON_PX).isNull():
            icon = found
    except Exception:
        icon = None
    _icon_cache[name] = icon
    return icon


def icon_for(word):
    return theme_icon(ICONS.get(word))


def swatch_style(colour):
    """A colour well: the colour, a hairline that reads on light and dark
    alike, rounded like the chips."""
    return ("QPushButton { background-color: %s; border: 1px solid "
            "rgba(0,0,0,0.35); border-radius: 3px; min-height: 20px; }"
            "QPushButton:hover { border: 1px solid palette(highlight); }"
            # the rule above replaces the style's focus frame
            "QPushButton:focus { border: 2px solid palette(highlight); }"
            % colour)


def intro(title, body):
    """The head of a dialog, the way the Trouble window has it: one bold
    line saying what the window is for, then the detail in quiet words that
    wrap to the width of the window instead of breaking where the source
    code did."""
    holder = QWidget()
    box = QVBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 4)
    box.setSpacing(4)
    head = QLabel(title)
    f = head.font()
    f.setBold(True)
    f.setPointSizeF(f.pointSizeF() * 1.1)
    head.setFont(f)
    box.addWidget(head)
    words = QLabel(body)
    words.setObjectName("quiet")
    words.setWordWrap(True)
    box.addWidget(words)
    return holder


def titled(what):
    """The title of a window of the program: its name first, so a dialog
    left behind QGIS in the taskbar says whose it is."""
    return "%s: %s" % (NAME, what)


def browse(tip):
    """The button beside a folder or a file, the same in every window: three
    dots, as QGIS's own, never wider than they need. It was 'choose' in one
    window, 'Choose' in another and a bar of dots as wide as the field in a
    third."""
    b = QPushButton("…")
    b.setToolTip(tip)
    b.setFixedWidth(32)
    return b


def short_combo(box, chars=6):
    """A list that keeps to the room its window gives it.

    Sized to its contents a list takes the width of its longest item: a
    layer named at length, a reading with a long operator's name, a sentence
    that explains a choice, and a window made for 300 pixels was held at 460
    in DejaVu, whose letters are wider than the ones it was drawn with. A long
    item is cut at the edge of the box instead, and whole in the list when it
    opens; chars is how many letters the box shows at least."""
    box.setSizeAdjustPolicy(
        QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    box.setMinimumContentsLength(chars)
    box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return box


def short_spin(spin, sample="000000"):
    """A number box that asks for the room of a number like sample, not of the
    biggest it could hold: a box that goes up to 2 147 483 647, or to a
    trillion with four decimals, asked for a hundred pixels more than a window
    of 300 has, with the fonts of Linux. A longer number scrolls in the box."""
    metrics = spin.fontMetrics()
    spin.setMinimumWidth(text_width(metrics, sample) + 2 * metrics.height())
    return spin


def rule():
    """A hairline across a window, in the colour of the panel's own."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setProperty("rule", True)
    line.setFixedHeight(1)
    return line


def column_head(word):
    label = QLabel(word)
    label.setObjectName("subsection")
    return label


# ---------------------------------------------------------------- buttons
#  The word on every button, and QGIS's icon beside it where QGIS
#  has one: see ICONS. Every button is exactly as wide as its word and icon.
def text_width(metrics, words):
    try:
        return metrics.horizontalAdvance(words)
    except AttributeError:                  # Qt 5.10 and older
        return metrics.width(words)


def bold_metrics(widget):
    """A pressed button writes its word in bold, and bold is wider. Measuring
    the plain font would cut the label off exactly when it matters most."""
    f = QFont(widget.font())
    f.setBold(True)
    return QFontMetrics(f)


def key_height(widget, least=ICON_H):
    """As tall as a key is, or taller when the font QGIS was given is.

    A fixed height has three pixels to spare at QGIS's 11 point font and cuts
    the words off at 13: the height follows the line the font needs."""
    return max(least, widget.fontMetrics().height() + 10)


def chip_height(widget):
    """A class chip, as tall as CLASS_H or as the font needs: at QGIS's 13
    point font a chip of 24 pixels cut the lower half of every name."""
    return max(CLASS_H, widget.fontMetrics().height() + 8)


def banner_height(widget, lines=1):
    """The class in hand over the chips: one line in its own large font, or
    in Correct two, a small word over the class. Fixed at 36 and 42 pixels,
    a 13 point font would lose half of the name."""
    if lines == 1:
        return max(BANNER_H, widget.fontMetrics().height() + 12)
    small = QFont(widget.font())
    small.setPointSize(max(widget.font().pointSize() - 3, 7))
    return max(BANNER_H + 6, QFontMetrics(small).height()
               + widget.fontMetrics().height() + 12)


def fit_field(box, least=0):
    """A number box as wide as its own style asks to show its largest value
    and its unit, and never narrower than least. A width written in, 66
    pixels, held under Fusion and cut '33 %' to '33' under the windows11
    style QGIS 4 uses on Windows 11, which asks for 106."""
    box.setFixedWidth(max(least, box.sizeHint().width()))
    return box


def button_pad(button):
    """The room the style keeps around the word of a button, measured from
    the style itself. PAD was enough for Fusion; the windows11 style keeps
    more and cut the first letter off Go."""
    pad = 0
    try:
        opt = QStyleOptionButton()
        opt.initFrom(button)
        opt.text = "x"
        # measured on a word wide enough that no style's least width for a
        # button (eighty pixels in Fusion) has a say in it
        pad = button.style().sizeFromContents(
            QStyle.ContentsType.CT_PushButton, opt, QSize(200, 20),
            button).width() - 200
    except Exception:
        pad = 0
    return max(PAD, pad)


# The least air beside the word of a key in a row that has no room left:
# four pixels each side, past which the word would touch the frame.
TIGHT_PAD = 8


def menu_room(button):
    """The room the arrow of a button with a menu takes beside its word, as
    the style draws it: a key that opens a menu (Measure) is that much
    wider than its word, or the arrow is drawn over the last letter."""
    try:
        if button.menu() is None:
            return 0
        return button.style().pixelMetric(
            QStyle.PixelMetric.PM_MenuButtonIndicator, None, button)
    except Exception:
        return 0


def key_need(button, tight=False):
    """The least width a key can be given with its word still whole: the
    word in the font it is written in, the room the style keeps round it,
    the icon, and the arrow of a menu. In bold only for a key that can be
    pressed and stay down, the one kind a stylesheet writes in bold.

    dress() measures every key in bold, which leaves a key a little air on
    a panel with room for it; this is the floor a row comes down to when it
    has none (KeyRow). tight is the floor under that one, for a row that
    still does not fit: the word and its frame, with TIGHT_PAD of air in
    place of the room the style likes to keep, which a theme that pads
    every button (Night Mapping) makes generous."""
    metrics = (bold_metrics(button) if button.isCheckable()
               else button.fontMetrics())
    pad = TIGHT_PAD if tight else button_pad(button)
    need = text_width(metrics, button.text()) + pad
    if not button.icon().isNull():
        need += ICON_PX + 6
    return need + menu_room(button)


def key_least(button):
    return key_need(button, tight=True)


def dress(button, word, pad=None):
    button.setText(word)
    icon = icon_for(word)
    extra = menu_room(button)
    if icon is not None:
        button.setIcon(icon)
        button.setIconSize(QSize(ICON_PX, ICON_PX))
        extra += ICON_PX + 6
    elif word in ICONS:
        button.setIcon(QIcon())
    height = button.height() if button.property("primary") \
        else key_height(button)
    button.setFixedSize(text_width(bold_metrics(button), word)
                        + (button_pad(button) if pad is None else pad) + extra,
                        height)
    return button


def hold_shape(dialog, least):
    """The smallest a window may be made: least wide, and at that width as
    tall as everything in it needs, its wrapped words included.

    Qt does not count words that wrap in the least height of a window: a
    window whose layout holds one lets itself be made as small as nothing,
    and the class list and the buttons under it get drawn over each other.
    A layout told to keep its minimum ignores a minimum width given by hand.
    So both are given by hand, from the height the layout needs at that
    width; called again whenever what the window shows changes."""
    layout = dialog.layout()
    layout.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
    layout.activate()
    width = max(least, layout.totalMinimumSize().width())
    tall = layout.totalMinimumSize().height()
    try:
        need = layout.minimumHeightForWidth(width)
    except Exception:
        need = -1
    dialog.setMinimumSize(width, max(tall, need))
    if dialog.width() < width or dialog.height() < max(tall, need):
        dialog.resize(max(dialog.width(), width),
                      max(dialog.height(), tall, need))
    return dialog


class ShapeKeeper(QObject):
    """Holds a window's least height up to date while it is being resized.

    hold_shape measures once, at the width the window has when it is built.
    A tick box that wraps its words (WrapTick) is one line tall then and two
    or three when the window is made narrower, and the least height measured
    before is too small for it: the rows below get drawn over each other.
    After each resize, once the boxes have wrapped, the shape is held again."""

    def __init__(self, dialog, least):
        super().__init__(dialog)
        self.dialog = dialog
        self.least = least
        self.pending = False
        dialog.installEventFilter(self)

    def eventFilter(self, watched, ev):
        if watched is self.dialog and ev.type() == QEvent.Type.Resize \
                and not self.pending:
            self.pending = True
            QTimer.singleShot(0, self.settle)
        return False

    def settle(self):
        self.pending = False
        if self.dialog.layout() is None:
            return
        # twice: the first pass lays the boxes out, and they wrap; the
        # second measures them wrapped
        hold_shape(self.dialog, self.least)
        hold_shape(self.dialog, self.least)


def keep_shape(dialog, least):
    """hold_shape now, and again after every resize: for a window with tick
    boxes that wrap."""
    hold_shape(dialog, least)
    if getattr(dialog, "_shape_keeper", None) is None:
        dialog._shape_keeper = ShapeKeeper(dialog, least)
    return dialog


def primary(button, height=None):
    """A module button, or Save: what a block or a module is for, so it is
    the first thing the eye lands on. Taller than a key and written in bold,
    with QGIS's icon; drawn by QGIS's style like every other button until it
    is pressed, when it takes the accent. It is not tinted: a tint mixed from
    Night Mapping's orange came out a muddy brown, and the accent is kept for
    what is in hand."""
    button.setProperty("primary", True)
    f = QFont(button.font())
    f.setBold(True)
    button.setFont(f)
    button.setFixedHeight(height or key_height(button, PRIMARY_H))
    return button


def bar(groups, room=None, gap=GROUP_GAP, uniform=True, counts=()):
    """The command bar of a module: buttons of one size, in as many columns as
    the panel is wide enough to hold.

    As wide as their own word they would make every row a different
    shape, and the eye would have to find each button again after every
    resize. All one size, the bar reads as a keypad: the hand learns where
    Save is and the place stays put whether the panel shows two columns or
    four."""
    flow = FlowLayout(4, gap, uniform, counts)
    for i, group in enumerate(groups):
        for j, button in enumerate(group):
            flow.add(button, new_group=(i > 0 and j == 0))
    return flow


def keypad(rows, gap=4):
    """The keys of a block of the panel, row by row as they are written.

    Each row shares the whole width of the block. The rows are not one grid:
    a row of three is in thirds and a row of two in halves, so a block whose
    keys do not make whole rows of three ends in two halves instead of a key
    alone or a hole. And a row too narrow for equal keys gives each key the
    width its word needs (KeyRow) instead of falling to fewer columns, which
    would break the rows of New, Open and Close apart on a Linux desktop,
    whose larger font does not hold three keys at two hundred and sixty
    pixels."""
    box = QVBoxLayout()
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(gap)
    for row in rows:
        line = KeyRow(key_need, gap, least=key_least)
        for button in row:
            line.add(button)
        box.addLayout(line)
    return box


def full_width(button):
    """Undo the fixed width dress() gave a button, and let it take the room.

    dress() makes every button exactly as wide as its own word, which is right
    for a keypad of eight. It is wrong for a box of one or two: Save, and the
    pairs Tiles/Move and Frames/Marks, are the buttons the hand goes to without
    looking, and a narrow word floating at the left of a wide bar is harder to
    hit than the same word stretched across it."""
    extra = 0 if button.icon().isNull() else ICON_PX + 6
    button.setMinimumWidth(
        text_width(bold_metrics(button), button.text())
        + button_pad(button) + extra)
    button.setMaximumWidth(16777215)            # QWIDGETSIZE_MAX
    if not button.property("primary"):
        button.setFixedHeight(key_height(button))
    policy = button.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
    button.setSizePolicy(policy)
    return button


def spread(buttons, gap=GROUP_GAP):
    """A row of buttons that share the whole width, equally.

    Not a FlowLayout: these never wrap, because there are at most two of them
    and the point is that each one is half the bar, in the same place, at every
    width the panel can be given."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(gap)
    for button in buttons:
        row.addWidget(full_width(button), 1)
    return row


def heading(word, widget):
    """The small name a module writes over each group of its keys.

    The blocks of the panel have had one since the beginning and the groups
    of a module did not, which left the row of shapes looking like the row of
    commands underneath it. A word costs a few pixels of height and saves the
    question."""
    holder = QWidget()
    box = QVBoxLayout(holder)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(4)
    label = QLabel(word)
    label.setObjectName("subsection")
    f = label.font()
    f.setPointSize(max(f.pointSize() - 1, 7))
    label.setFont(f)
    box.addWidget(label)
    if isinstance(widget, QWidget):
        box.addWidget(widget)
    else:
        box.addLayout(widget)
    return follows_width(holder)


def plain(layout):
    """A group of keys in a widget of its own, with no frame round it.

    Inside the module the groups are told apart by their small headings and
    a little air. A frame round each of them inside the module's own frame
    was two borders everywhere, forty pixels of lines in the one column where
    every pixel is wanted for the work."""
    holder = QWidget()
    holder.setLayout(layout)
    return follows_width(holder)


def follows_width(widget):
    """Let this widget's height depend on the width it is given.

    Buttons that wrap and chips that reflow make a box taller as it gets
    narrower, and the layout above will not ask unless the size policy says it
    should. Qt does not work this out by itself across a widget: the chain of
    layouts carries it, a widget in the middle of the chain breaks it. Every
    box that has a wrapping thing inside it says so here."""
    policy = widget.sizePolicy()
    policy.setHeightForWidth(True)
    widget.setSizePolicy(policy)
    return widget


def _canvas(size, ratio=1.0):
    """A transparent square to draw an icon on, with as many pixels as a
    screen at that ratio has. The painter keeps working in logical units."""
    pm = QPixmap(int(round(size * ratio)), int(round(size * ratio)))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def _icon(size, paint):
    """An icon drawn by paint(painter), once for every pixel ratio it may be
    shown at: the logical size, the screen's own and twice that.

    One pixmap of the screen's ratio came out crisp on Qt 6, and on Qt 5 at
    150 percent, unless the application asked for high resolution pixmaps,
    it was shrunk to the logical size and blown up again, and the arrows
    came out lopsided. With every size in the icon, Qt picks the one it
    needs and never scales a drawing."""
    ratios = {1.0, 2.0}
    try:
        ratios.add(max(1.0, float(QApplication.instance().devicePixelRatio())))
    except Exception:
        pass
    icon = QIcon()
    for ratio in sorted(ratios):
        pm = _canvas(size, ratio)
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            paint(p)
        finally:
            p.end()
        icon.addPixmap(pm)
    return icon


def arrow_icon(where, size=12):
    """A small solid triangle pointing up, down, left or right, in the ink
    of the panel's words.

    The arrows of a font are hairlines in every UI face QGIS uses, smaller
    than the 'fit' beside them, and these are the keys pressed while the eye
    is on the map. A shape the size of the key's word reads at a glance."""
    ink = QColor(palette_colours()["text"])

    def paint(p):
        p.setPen(QPen(Qt.PenStyle.NoPen))
        p.setBrush(QBrush(ink))
        a, b, c = size * 0.12, size * 0.5, size * 0.88
        lo, hi = size * 0.22, size * 0.78
        shape = {"up": [(a, hi), (b, lo), (c, hi)],
                 "down": [(a, lo), (b, hi), (c, lo)],
                 "left": [(hi, a), (lo, b), (hi, c)],
                 "right": [(lo, a), (hi, b), (lo, c)]}[where]
        p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in shape]))
    return _icon(size, paint)


def person_icon(size=14):
    """A head and a pair of shoulders, drawn instead of shipped.

    The plugin is one file and has to stay one file, so an icon cannot be a
    .png sitting next to it. Drawing it at call time from the palette also
    means it comes out legible whether QGIS is in its light theme or its dark
    one, instead of being a dark glyph on a dark button."""
    ink = QColor(palette_colours()["text"])

    def paint(p):
        p.setPen(QPen(Qt.PenStyle.NoPen))
        p.setBrush(QBrush(ink))
        head = size * 0.34
        p.drawEllipse(QRectF((size - head) / 2.0, size * 0.10, head, head))
        # the shoulders: a disc with its top half clipped away
        body = size * 0.64
        p.setClipRect(QRectF(0, size * 0.54, size, size * 0.46))
        p.drawEllipse(QRectF((size - body) / 2.0, size * 0.52, body, body))
    return _icon(size, paint)


def padlock_icon(closed=True, size=14):
    """A padlock, shut or open, drawn from the palette like the person is.

    Drawn and not written as a character: the lock glyphs a font may or may
    not have come out as an empty box on one machine and as a colour emoji on
    another, and this one is neither."""
    ink = QColor(palette_colours()["text"])

    def paint(p):
        body = QRectF(size * 0.18, size * 0.46, size * 0.64, size * 0.44)
        p.setPen(QPen(Qt.PenStyle.NoPen))
        p.setBrush(QBrush(ink))
        p.drawRoundedRect(body, size * 0.10, size * 0.10)
        pen = QPen(ink)
        pen.setWidthF(max(1.2, size * 0.11))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        # the shackle: a half circle, upright when shut and tipped over to the
        # side when open, which is the difference the eye actually catches
        left = size * (0.30 if closed else 0.42)
        arc = QRectF(left, size * 0.16, size * 0.40, size * 0.42)
        p.drawArc(arc, 0 * 16, 180 * 16)
        if closed:
            p.drawLine(QPointF(arc.left(), arc.center().y()),
                       QPointF(arc.left(), body.top()))
            p.drawLine(QPointF(arc.right(), arc.center().y()),
                       QPointF(arc.right(), body.top()))
        else:
            p.drawLine(QPointF(arc.left(), arc.center().y()),
                       QPointF(arc.left(), body.top()))
    return _icon(size, paint)
