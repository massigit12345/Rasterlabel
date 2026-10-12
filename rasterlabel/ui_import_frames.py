"""rasterlabel.ui_import_frames

Import frames: the window that says which columns of the file are the
sampling design, which side the frames take, and what will happen to every
unit of the file before anything does.

The window plans and nothing else. What it shows under "What will happen"
is design_plan run on the units as they are read, again at every change of
a column or of the side: a pure function, so no layer is touched before
Import is pressed, and what Import then writes is exactly what was shown.
The import itself is AnnotationSection.import_tiles.
"""
import math

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import (QButtonGroup, QComboBox, QDialog,
                                 QDialogButtonBox, QGridLayout, QLabel,
                                 QLineEdit, QPushButton, QSizePolicy)
from qgis.core import (QgsCoordinateTransform, QgsGeometry, QgsPointXY,
                       QgsProject, QgsRectangle)

from .constants import DESIGN_FIELDS, GEOM_LINE, GEOM_POINT, GEOM_POLYGON
from .project import crs_label, project_rasters
from .errors import log
from .design import (DesignBoxes, design_box_clasher, design_feature_values,
                     design_guess_mapping, design_import_count,
                     design_inside_box, design_plain, design_preview,
                     design_source_name)
from .theme import keep_shape, hold_shape, titled
from .widgets import narrow_radio

# The words of the five rows, in the order of the tiles table.
IMPORT_FIELD_WORDS = {"sample_id": "sample id", "stratum": "stratum",
                      "incl_prob": "incl. prob", "weight": "weight",
                      "design": "design"}
IMPORT_NONE = "(none)"
IMPORT_TYPED = "(typed below)"
IMPORT_TIP = (
    "Take frames from a vector file: a sample drawn in AcATaMa, in R or\n"
    "elsewhere, or the frames somebody else worked on. The design columns\n"
    "come along (sample id, stratum, inclusion probability, weight,\n"
    "design). Every frame is put on the pixel grid, and every feature of\n"
    "the file is written to design_log.csv: added, moved onto the grid,\n"
    "resized, or refused and why.")
IMPORT_NOTHING_TIP = ("nothing in this file would become a new frame; see "
                      "the counts above")
IMPORT_CAVEAT = ("A refused draw changes the inclusion probabilities of the "
                 "sample. Each one is written to design_log.csv.")
# The narrowest the window may be made, and the width it opens at.
IMPORT_LEAST_W = 300
IMPORT_OPEN_W = 420


class ImportFrames(QDialog):
    """Which columns are the design, which side, and what will happen.

    source: {"name", "what" ("120 points, EPSG:32633"), "note" (said when
    the file has no system, or "")}. fields: the column names of the file.
    rasters: [(name, layer id)] of the single-band rasters the stratum can
    be read from. planner(choice) -> the decisions of design_plan for a
    choice as result() gives it. many: wait for the hand to stop before
    planning again."""

    def __init__(self, parent, source, fields, rasters, settings_side_m,
                 settings_side_px, all_square, planner, can_own_side=True,
                 many=False):
        super().__init__(parent)
        self.setWindowTitle(titled("Import frames"))
        self.planner = planner
        self.decisions = []
        self.many = bool(many)
        self.fields = [f for f in fields if str(f).lower() != "fid"]
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        row = 0

        grid.addWidget(self._words("From"), row, 0)
        self.source_name = self._words(source.get("name") or "")
        grid.addWidget(self.source_name, row, 1)
        row += 1
        self.source_what = self._quiet(source.get("what") or "")
        grid.addWidget(self.source_what, row, 1)
        row += 1
        self.source_note = self._quiet(source.get("note") or "")
        self.source_note.setVisible(bool(source.get("note")))
        grid.addWidget(self.source_note, row, 1)
        row += 1

        grid.addWidget(self._part("The design"), row, 0, 1, 2)
        row += 1
        guess = design_guess_mapping(self.fields)
        self.combos = {}
        for field in DESIGN_FIELDS:
            grid.addWidget(self._words(IMPORT_FIELD_WORDS[field]), row, 0)
            box = self._combo()
            if field == "design":
                box.addItem(IMPORT_TYPED, "typed")
            else:
                box.addItem(IMPORT_NONE, None)
            for name in self.fields:
                box.addItem(str(name), "column:%s" % name)
            if field == "stratum":
                for name, layer_id in rasters:
                    box.addItem("from raster: %s" % name,
                                "raster:%s" % layer_id)
            if guess.get(field):
                i = box.findData("column:%s" % guess[field])
                if i >= 0:
                    box.setCurrentIndex(i)
            grid.addWidget(box, row, 1)
            self.combos[field] = box
            row += 1
        self.typed = QLineEdit()
        self.typed.setPlaceholderText("stratified random, AcATaMa, n=120")
        self.typed.setToolTip(
            "The design, in words, written into every frame (80 characters "
            "in the column, all of it in the manifest).")
        grid.addWidget(self.typed, row, 1)
        row += 1
        self.values_note = self._quiet(
            "Every value is carried exactly as given: no weight is worked "
            "out from a probability, and nothing is normalised.")
        grid.addWidget(self.values_note, row, 0, 1, 2)
        row += 1

        grid.addWidget(self._part("Frame side"), row, 0, 1, 2)
        row += 1
        self.side_group = QButtonGroup(self)
        # radio buttons that wrap: with the wider fonts of Linux "Settings:
        # 12.50 m (250 px)" held the window at 361
        self.settings_side = narrow_radio(
            "Settings: %.2f m (%d px)" % (settings_side_m, settings_side_px))
        self.settings_side.setToolTip("Every frame takes the side set in "
                                      "Settings.")
        self.own_side = narrow_radio("each shape's own side")
        for i, b in enumerate((self.settings_side, self.own_side)):
            self.side_group.addButton(b, i)
            grid.addWidget(b, row, 0, 1, 2)
            row += 1
        self.side_note = self._quiet("points and lines take the Settings side"
                                     if can_own_side else
                                     "the file holds no polygons: every "
                                     "frame takes the Settings side")
        grid.addWidget(self.side_note, row, 0, 1, 2)
        row += 1
        if can_own_side and all_square:
            self.own_side.setChecked(True)
        else:
            self.settings_side.setChecked(True)
        self.own_side.setEnabled(bool(can_own_side))

        grid.addWidget(self._part("What will happen"), row, 0, 1, 2)
        row += 1
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        grid.addWidget(self.preview, row, 0, 1, 2)
        row += 1
        self.caveat = self._quiet(IMPORT_CAVEAT)
        grid.addWidget(self.caveat, row, 0, 1, 2)
        row += 1
        grid.setRowStretch(row, 1)
        row += 1

        buttons = QDialogButtonBox()
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.go = QPushButton("Import")
        self.go.setDefault(True)
        buttons.addButton(self.go, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        grid.addWidget(buttons, row, 0, 1, 2)

        self.wait = QTimer(self)
        self.wait.setSingleShot(True)
        self.wait.setInterval(200)
        self.wait.timeout.connect(self.refresh)
        for box in self.combos.values():
            box.currentIndexChanged.connect(self.changed)
        self.typed.textChanged.connect(self.changed)
        self.side_group.buttonClicked.connect(self.changed)
        self.refresh()
        self.resize(IMPORT_OPEN_W, self.sizeHint().height())
        keep_shape(self, IMPORT_LEAST_W)

    # ------------------------------------------------------------ parts
    def _part(self, words):
        label = QLabel(words)
        f = label.font()
        f.setBold(True)
        label.setFont(f)
        label.setWordWrap(True)
        return label

    def _words(self, words):
        label = QLabel(words)
        label.setWordWrap(True)
        return label

    def _quiet(self, words):
        label = self._words(words)
        label.setObjectName("quiet")
        return label

    def _combo(self):
        box = QComboBox()
        box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        box.setMinimumContentsLength(6)
        box.setSizePolicy(QSizePolicy.Policy.Expanding,
                          QSizePolicy.Policy.Fixed)
        return box

    # ------------------------------------------------------------ state
    def changed(self, *args):
        self.typed.setEnabled(self.combos["design"].currentData() == "typed")
        if self.many:
            self.wait.start()
        else:
            self.refresh()

    def result(self):
        """{mapping {field: column or None}, stratum_raster (a layer id or
        None), design_text (typed, or None), own_side, words (the mapping
        as the manifest writes it: a column, "raster:<name>", "typed" or
        None)}."""
        mapping, words = {}, {}
        stratum_raster = None
        design_text = None
        for field, box in self.combos.items():
            data = box.currentData()
            mapping[field] = None
            words[field] = None
            if isinstance(data, str) and data.startswith("column:"):
                mapping[field] = data[len("column:"):]
                words[field] = mapping[field]
            elif isinstance(data, str) and data.startswith("raster:"):
                stratum_raster = data[len("raster:"):]
                words[field] = "raster:%s" % box.currentText()[
                    len("from raster: "):]
            elif data == "typed":
                text = self.typed.text().strip()
                design_text = text or None
                words[field] = "typed" if text else None
        return {"mapping": mapping, "stratum_raster": stratum_raster,
                "design_text": design_text,
                "own_side": self.own_side.isChecked()
                and self.own_side.isEnabled(), "words": words}

    def refresh(self, *args):
        """What will happen, planned again from the choice as it is now."""
        self.typed.setEnabled(self.combos["design"].currentData() == "typed")
        try:
            self.decisions = list(self.planner(self.result()) or [])
            lines = design_preview(self.decisions)
        except Exception as err:
            self.decisions = []
            lines = ["cannot plan the import: %s" % err]
        self.preview.setText("\n".join(lines))
        refused = any(d.get("outcome") == "refused" for d in self.decisions)
        self.caveat.setVisible(refused)
        n = design_import_count(self.decisions)
        self.go.setText("Import %d" % n)
        self.go.setEnabled(n > 0)
        self.go.setToolTip("" if n > 0 else IMPORT_NOTHING_TIP)
        if self.layout() is not None and self.isVisible():
            hold_shape(self, IMPORT_LEAST_W)
        return self.decisions


#  What the window and the import read of QGIS
# =====================================================================
def import_value(value):
    """A value of the file as the design reads it: NULL as None, a date
    or anything else Qt hands over as its text."""
    value = design_plain(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    text = getattr(value, "toString", None)
    try:
        return text() if callable(text) else str(value)
    except Exception:
        return str(value)


def import_kind(geometry):
    """point, line, polygon, or none for no geometry or an empty one."""
    if geometry is None or geometry.isEmpty():
        return "none"
    t = geometry.type()
    if t == GEOM_POLYGON:
        return "polygon"
    if t == GEOM_LINE:
        return "line"
    if t == GEOM_POINT:
        return "point"
    return "none"


def import_read_rows(source, move=None):
    """Every feature of the file, in order of fid, as design_plan reads a
    unit: its kind, its bounding box in the campaign's system, whether it
    could be brought into it, its columns and how many parts it has. A
    feature with no geometry is a unit too: it is refused, and said."""
    names = list(source.fields().names())
    rows = []
    for f in sorted(source.getFeatures(), key=lambda f: f.id()):
        attrs = {}
        for name in names:
            try:
                attrs[name] = import_value(f.attribute(name))
            except Exception:
                attrs[name] = None
        g = QgsGeometry(f.geometry()) if f.hasGeometry() else None
        kind = import_kind(g)
        bbox, ok, parts = None, True, 1
        if kind != "none":
            try:
                parts = len(g.asGeometryCollection()) if g.isMultipart() \
                    else 1
            except Exception:
                parts = 1
            if move is not None:
                try:
                    g.transform(move)
                except Exception:
                    ok = False
            if ok:
                b = g.boundingBox()
                box = (b.xMinimum(), b.yMinimum(), b.xMaximum(),
                       b.yMaximum())
                if all(math.isfinite(v) for v in box):
                    bbox = box
                else:
                    ok = False
        rows.append({"fid": f.id(), "kind": kind, "bbox": bbox,
                     "transform_ok": ok, "attrs": attrs,
                     "parts": max(1, parts)})
    return rows


def import_source_words(path, source, rows):
    """{name, what, note} of the file, for the top of the window."""
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    words = {"point": ("point", "points"), "line": ("line", "lines"),
             "polygon": ("polygon", "polygons"),
             "none": ("without geometry", "without geometry")}
    order = ("point", "line", "polygon", "none")
    bits = ["%d %s" % (n, words[k][0 if n == 1 else 1])
            for k, n in sorted(kinds.items(), key=lambda kv:
                               order.index(kv[0]))]
    crs = source.crs()
    what = "%s, %s" % (", ".join(bits) or "no features",
                       crs_label(crs) if crs.isValid()
                       else "no coordinate system")
    note = "" if crs.isValid() else "no CRS: read as the campaign's"
    return {"name": design_source_name(path), "what": what, "note": note}


def import_rasters():
    """[(name, layer id)] of the single-band rasters of the project, which
    the stratum can be read from: the map a sample was stratified on."""
    out = []
    for lyr in project_rasters(need_crs=False):
        try:
            if lyr.bandCount() == 1:
                out.append((lyr.name(), lyr.id()))
        except Exception:
            pass
    return out


def import_stratum_reader(layer_id, crs):
    """reader(x, y) -> the value of a single-band raster at a point of the
    campaign's system, as a stratum is written (2, not 2.0), or None off
    the raster or on nodata."""
    lyr = QgsProject.instance().mapLayer(layer_id) if layer_id else None
    if lyr is None:
        return None
    move = None
    try:
        if lyr.crs().isValid() and crs is not None and crs.isValid() \
                and lyr.crs() != crs:
            move = QgsCoordinateTransform(crs, lyr.crs(),
                                          QgsProject.instance())
    except Exception:
        move = None
    provider = lyr.dataProvider()

    def reader(x, y):
        p = QgsPointXY(x, y)
        if move is not None:
            p = move.transform(p)
        value, ok = provider.sample(p, 1)
        if not ok or value is None:
            return None
        try:
            f = float(value)
        except (TypeError, ValueError):
            return str(value)
        if not math.isfinite(f):
            return None
        return int(f) if f == int(f) else f
    return reader


def import_inside(raster, crs):
    """inside(box) against the extent of the campaign's raster, in the
    campaign's system; always "in" without a raster."""
    if raster is None:
        return design_inside_box(None)
    try:
        box = raster.extent()
        if raster.crs().isValid() and crs is not None and crs.isValid() \
                and raster.crs() != crs:
            box = QgsCoordinateTransform(raster.crs(), crs,
                                         QgsProject.instance()
                                         ).transformBoundingBox(box)
        return design_inside_box((box.xMinimum(), box.yMinimum(),
                                  box.xMaximum(), box.yMaximum()))
    except Exception as err:
        log("cannot tell where the raster ends: %s" % err)
        return design_inside_box(None)


def import_existing(frames):
    """The frames there, as design_plan reads them: tile_id, bounding box
    and design."""
    out = []
    for f in frames:
        bbox = None
        if f.hasGeometry():
            b = f.geometry().boundingBox()
            bbox = (b.xMinimum(), b.yMinimum(), b.xMaximum(), b.yMaximum())
        out.append({"tile_id": str(f["tile_id"] or ""), "bbox": bbox,
                    "design": design_feature_values(f), "fid": f.id()})
    return out


def import_clash(section, frames, pixel):
    """clash(box, accepted) for design_plan. The frames there are asked of
    QGIS through Annotate's own frame_clash, whatever their shape, once a
    look at the boxes has kept only the neighbours; the frames accepted
    from the file so far are boxes on the grid and are asked as boxes."""
    near = DesignBoxes()
    for i, f in enumerate(frames):
        if f.hasGeometry():
            b = f.geometry().boundingBox()
            near.add(i, (b.xMinimum(), b.yMinimum(), b.xMaximum(),
                         b.yMaximum()))
    of_file = design_box_clasher([], pixel)

    def clash(box, accepted):
        geom = QgsGeometry.fromRect(QgsRectangle(*box))
        keep = sorted({i for i, _ in near.near(box)})
        hit = section.frame_clash(geom, among=[frames[i] for i in keep]) \
            if keep else []
        return sorted(set(hit) | set(of_file(box, accepted)))
    return clash


def import_add_columns(lyr):
    """The five design columns, added to a tiles layer that was loaded
    before the package had them. Opening a campaign adds them to the file
    (prepare_package), so this is for a layer older than that."""
    have = set(n.lower() for n in lyr.fields().names())
    missing = [(name, real) for name, real in (
        ("sample_id", False), ("stratum", False), ("incl_prob", True),
        ("weight", True), ("design", False)) if name not in have]
    if not missing:
        return []
    # Each made as a copy of a column of the same kind already there, side_m
    # for a number and note for a text: no type is spelled, and the
    # spelling is what differs between QGIS 3 and QGIS 4.
    from qgis.core import QgsField
    like = {True: lyr.fields().indexOf("side_m"),
            False: lyr.fields().indexOf("note")}
    if like[True] < 0 or like[False] < 0:
        log("the design columns could not be added to the frames layer: it "
            "has no side_m or no note to copy them from", loud=True)
        return []
    fields = []
    for name, real in missing:
        field = QgsField(lyr.fields().field(like[real]))
        field.setName(name)
        fields.append(field)
    if not lyr.dataProvider().addAttributes(fields):
        log("the design columns could not be added to the frames layer",
            loud=True)
        return []
    lyr.updateFields()
    return [name for name, _ in missing]
