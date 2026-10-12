"""The TO chip in hand in Correct can be found at a glance, on any colour.

Correct fills its TO chips with the colours of the map's classes, and a map can
have forty of them. The chip in hand used to differ from the others by bold
lettering and a ring of two pixels in its own ink: on a navy or a dark brown
chip that white ring read as one more edge, and the user could not tell which
class the brush would write. So this suite opens the real CorrectionSection on
maps of four and of forty classes, very dark and very light colours among them,
and asks:

  exactly one TO chip carries the tick, the one chosen, and in the FROM row
  the chosen chip of a class carries one too, in the ink of the text;
  the tick is a drawn icon, in the ink of its chip;
  the ring is thick and in that ink, and a dark chip has a dark rim round the
  white ring, so it stands out from the pale panel as well as from the chip;
  in the pixels: ring, tick and fill really are that far apart on the screen;
  a name that fits its chip is not cut when the chip is chosen, and where two
  columns are forced on a long list and the tick does cut it, the banner and
  the tooltip still say it whole; after the panel is made narrower the name is
  cut to the room the tick leaves;
  the chips not chosen, and every chip of Annotate, keep the style they had.

Needs PyQt5 or PyQt6, and numpy. Not GDAL.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correctkit as K                                             # noqa: E402
import numpy as np                                                 # noqa: E402
from qtbinding import QtGui, QtWidgets                                 # noqa: E402

g, check = K.g, K.check

COLOURS = ["#000000", "#ffffff", "#0b0b2e", "#f7f7f0", "#3b2314", "#ffff00",
           "#1b7f2a", "#e6c229", "#444444", "#1f78b4", "#ff00ff", "#7f7f7f",
           "#202020", "#fefefe", "#5a0000", "#00ffff"]
NAMES = ["water", "crops", "roads", "forest", "Mediterranean maquis"]
NODATA = 255

# Annotate's chip styles exactly as they were: this change is Correct's own.
ANNOTATE_CHOSEN = (
    "QPushButton{background-color:#0b0b2e; color:#ffffff; font-weight:bold;"
    " border:2px solid #ffffff; border-radius:3px; padding:0px 3px;}"
    "QPushButton:focus{border-style:dashed;}")
ANNOTATE_PLAIN = (
    "QPushButton{background-color:#ffff00; color:#000000; border:1px solid "
    "rgba(0,0,0,0.45); border-radius:3px; padding:1px 4px;}"
    "QPushButton:hover{border:2px solid #000000; padding:0px 3px;}"
    "QPushButton:focus{border:2px dashed #000000; padding:0px 3px;}")

root = tempfile.mkdtemp(prefix="rl_to_chip_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])


def luminance(c):
    def lin(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def open_on(n, width):
    """Correct on a map of n classes, coloured from COLOURS in turn."""
    codes = list(range(1, n + 1))
    source = os.path.join(root, "data", "map_%d_%d.tif" % (n, width))
    K.write_map(source, np.array(codes * 2, np.uint8).reshape(2, n), NODATA)
    style = K.Paletted(None, 1, [
        K.Paletted.Class(c, COLOURS[(c - 1) % len(COLOURS)],
                         NAMES[c - 1] if c <= len(NAMES) else "class %d" % c)
        for c in codes])
    layer = K.add_layer(K.Layer(source, "map%d_%d" % (n, width), style))

    def first(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText("fix %d %d" % (n, width))
        d.raster.setCurrentIndex(d.raster.findData(layer.id()))
        d.fill_bands()
        d.folder.setText(os.path.join(root, "fix_%d_%d" % (n, width)))
        d.operator.setText("ann")
        return 1
    K.ANSWERS["OpenCorrection"] = first
    K.ANSWERS["ConfirmClasses"] = lambda d: 1
    panel = g["Panel"]()
    panel.resize(width, 1600)
    panel.show()
    panel.toggle_module(1)
    settle()
    return panel, panel.section


def settle():
    for _ in range(4):
        QtWidgets.QApplication.processEvents()


def to_chips(section):
    return [b for b in section._buttons if b.text() != "+"]


def colour_of(section, code):
    return QtGui.QColor(section.class_of(code)["colour"])


def pixels(button):
    image = button.grab().toImage().convertToFormat(QtGui.QImage.Format.Format_RGB32)
    ratio = image.devicePixelRatio() or 1.0
    return image, ratio


def at(image, ratio, x, y):
    return QtGui.QColor(image.pixel(int(x * ratio), int(y * ratio)))


def banner_to(section):
    doc = QtGui.QTextDocument()
    doc.setHtml(section.into_pill.text())
    return " ".join(doc.toPlainText().split())


def banner_has_room(section, name):
    """Whether the TO half of the banner can show name whole: the room and
    the smaller size show_banner falls back on, measured the same way."""
    banner = section.banner
    room = (max(banner.width(), 140) if banner.width() > 60
            else section.chip_room())
    half = max((room - section.arrow.width() - 8) // 2 - 10, 30)
    plain = QtGui.QFont(section.from_pill.font())
    plain.setPointSize(max(plain.pointSize() - 2, 8))
    return g["text_width"](QtGui.QFontMetrics(plain), name) <= half


def ticked(section):
    return [b for b in section._buttons if b.property("ticked")]


def from_ticked(section):
    return [b for b in section._from_buttons if b.property("ticked")]


try:
    print("Annotate's chips are as they were")
    a = g["AnnotationSection"]
    check("a chosen chip of Annotate: bold, a ring of two pixels in its ink",
          a._style(None, "#0b0b2e", True) == ANNOTATE_CHOSEN,
          a._style(None, "#0b0b2e", True))
    check("a chip of Annotate not chosen: unchanged",
          a._style(None, "#ffff00", False) == ANNOTATE_PLAIN,
          a._style(None, "#ffff00", False))
    check("and Annotate has no tick and no TO style of its own",
          not hasattr(a, "_to_style") and not hasattr(a, "_mark_room"))

    for n, width in ((4, 380), (40, 380), (40, 260)):
        print()
        print("%d classes, a panel %d pixels wide" % (n, width))
        panel, s = open_on(n, width)
        check("Correct opened", type(s).__name__ == "CorrectionSection",
              type(s).__name__)
        codes = [c["code"] for c in s.classes()]
        worst = None
        for code in codes:
            s.choose_class(code)
            s.choose_from(codes[(codes.index(code) + 1) % len(codes)])
            settle()
            marked = ticked(s)
            chosen = [b for b in to_chips(s) if b.isChecked()]
            name = s.class_of(code)["name"]
            fill = colour_of(s, code)
            # the ink that reads furthest from the fill, white or black
            dark = contrast(QtGui.QColor("#ffffff"), fill) >= \
                contrast(QtGui.QColor("#000000"), fill)
            ink = "#ffffff" if dark else "#000000"
            ok = (len(marked) == 1 and len(chosen) == 1
                  and marked[0] is chosen[0]
                  and chosen[0].property("full_name") == name
                  and not chosen[0].icon().isNull())
            if not ok:
                check("class %d: one tick, on the chosen TO chip" % code, False,
                      [b.property("full_name") for b in marked])
                continue
            b = chosen[0]
            sheet = b.styleSheet()
            ring = ("border:4px solid %s" % ink) if dark \
                else ("border:3px solid %s" % ink)
            if ring not in sheet or ("color:%s" % ink) not in sheet:
                check("class %d (%s): the ring is thick and in its ink"
                      % (code, fill.name()), False, sheet)
            if (b.rim == "#101010") != dark:
                check("class %d (%s): a dark rim round a dark chip, none round "
                      "a light one" % (code, fill.name()), False, b.rim)
            # the pixels: halfway down the left edge, then the middle of the
            # ring, then the fill well inside
            image, ratio = pixels(b)
            mid = b.height() // 2
            edge = at(image, ratio, 0.5, mid)
            inner = at(image, ratio, 3 if dark else 1.5, mid)
            inside = at(image, ratio, 6, 4)
            seen = contrast(inner, inside)
            if worst is None or seen < worst[0]:
                worst = (seen, fill.name())
            if dark and luminance(edge) > 0.05:
                check("class %d (%s): the outer rim is dark on the screen"
                      % (code, fill.name()), False, edge.name())
            # the tick: the chip drawn without its icon differs from the chip
            # drawn with it, and the pixels that differ are in the ink
            icon = b.icon()
            b.setIcon(QtGui.QIcon())
            bare, _ = pixels(b)
            b.setIcon(icon)
            inks = 0
            for x in range(image.width()):
                for y in range(image.height()):
                    if image.pixel(x, y) != bare.pixel(x, y) and contrast(
                            QtGui.QColor(image.pixel(x, y)), fill) > 3:
                        inks += 1
            if inks < 6:
                check("class %d (%s): the tick shows" % (code, fill.name()),
                      False, inks)
            ft = from_ticked(s)
            want = s.class_of(s.from_code)["name"]
            if (len(ft) != 1 or ft[0].property("full_name") != want
                    or not ft[0].isChecked() or ft[0].icon().isNull()):
                check("class %d: the chosen FROM chip carries the one tick"
                      % code, False, [b.property("full_name") for b in ft])
            else:
                sheet = ft[0].styleSheet()
                edge = s.class_of(s.from_code)["colour"]
                if not ("background-color:palette(base)" in sheet
                        and ("border-left:7px solid %s" % edge) in sheet
                        and "font-weight:bold" in sheet
                        and "border:3px solid palette(text)" in sheet):
                    check("class %d: the chosen FROM chip is neutral, with "
                          "the class colour as its edge, a thick outline and "
                          "bold lettering" % code, False, sheet)
                if ft[0].rim != s.palette().text().color().name():
                    check("class %d: the chosen FROM chip is rimmed in the "
                          "ink of the text" % code, False, ft[0].rim)
            for f in s._from_buttons:
                if f.property("full_name") == "any class" or f.isChecked():
                    continue
                if not ("background-color:palette(base)" in f.styleSheet()
                        and "border-left:6px solid" in f.styleSheet()):
                    check("class %d: a FROM chip not chosen is neutral with "
                          "a coloured edge" % code, False, f.styleSheet())
            others = [x for x in to_chips(s) if x is not b]
            if any(x.styleSheet() != s._style(x.styleSheet().split(
                    "background-color:")[1].split(";")[0], False)
                    for x in others):
                check("class %d: the chips not chosen keep their style" % code,
                      False)
        # 3 to 1 is what WCAG asks of the edge of a control against what is
        # next to it; the threshold the chips' own lettering uses keeps white
        # on a mid grey at 4 to 1.
        check("on every colour the ring stands out from the chip "
              "(contrast %.1f at worst, on %s)" % worst if worst else "no chip",
              worst is not None and worst[0] >= 3.0, worst)

        # a name that fits its chip is not cut when the chip is chosen
        fits = {}
        s.choose_class(codes[0])
        settle()
        for b in to_chips(s)[1:]:
            fits[b.property("full_name")] = b.text() == b.property("full_name")
        cut = []
        for code in codes[1:]:
            s.choose_class(code)
            settle()
            b = [x for x in to_chips(s) if x.isChecked()][0]
            name = b.property("full_name")
            if fits.get(name) and b.text() != name:
                cut.append((name, b.text(), banner_to(s), b.toolTip(),
                            banner_has_room(s, name), s.banner.toolTip()))
        # The columns are counted with the tick in, so a name that fits is not
        # cut when it is chosen. The one exception is a long list squeezed
        # into the two columns Correct never goes below: there the tick can
        # cut a name, and the banner and the tooltip must still say it whole.
        whole = s._chip_columns(s.classes() + [{"name": "+"}]) > 1
        if whole:
            check("a name that fits is not cut by the tick when chosen",
                  not cut, cut)
        else:
            # Whole in the banner when the banner has the room for it, which
            # depends on the font: Qt 6 on Linux picks a smaller one than Qt 5,
            # so a name fits a chip there that it never fits under Qt 5, and
            # the banner, which keeps half its width for FROM, cannot hold it.
            # Then the banner cuts it as it was made to, from the end, and the
            # banner's own tooltip says it whole.
            check("two columns forced: a name the tick cuts is whole in the "
                  "banner and the tooltip",
                  all(c[0] in c[3] and (
                      c[2] == "TO " + c[0] if c[4] else
                      c[2].startswith("TO ") and c[2].endswith("…")
                      and c[0].startswith(c[2][3:-1]) and c[0] in c[5])
                      for c in cut), cut)
        if n == 40 and width == 380:
            narrow = width - 60
            panel.resize(narrow, 1600)
            settle()
            s.fit_chip_names()
            b = [x for x in to_chips(s) if x.isChecked()][0]
            metrics = g["bold_metrics"](s)
            columns = s._columns[1]
            cell = (s.chip_room() - 5 * (columns - 1)) // columns
            room = cell - 12 - (g.get("TICK_PX", 0) + 4)
            check("after the panel is made narrower the chosen name is cut "
                  "to the room the tick leaves",
                  g["text_width"](metrics, b.text()) <= room + 1,
                  (b.text(), room))
        panel.close_module()
        settle()
        panel.close()
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
