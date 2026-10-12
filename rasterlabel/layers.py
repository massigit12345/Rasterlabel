"""rasterlabel.layers

Whose layer it is, what colour it is, what it says.
"""
import os

from qgis.PyQt.QtGui import QColor
from qgis.core import (QgsCategorizedSymbolRenderer, QgsFillSymbol,
                       QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings,
                       QgsProject, QgsProperty, QgsRendererCategory,
                       QgsSingleSymbolRenderer, QgsSymbolLayer,
                       QgsTextBufferSettings, QgsTextFormat,
                       QgsVectorLayerSimpleLabeling)

from .constants import (LABEL_OVER_POINT, POLYGON_ALPHA, PREFIX, UNIT_RENDER_MAP,
                        first_attr)
from .compat import iface
from .project import rgba
from .errors import log, own_hands
from .campaign import (READING_TABLES, hidden_from, operator_word,
                       pass_number)


#  Layer ownership: the program owns its layers and can find them again
# =====================================================================
def mark(layer, campaign_id, role):
    layer.setCustomProperty("%s/campaign" % PREFIX, campaign_id)
    layer.setCustomProperty("%s/role" % PREFIX, role)


def my_layers(campaign_id=None):
    out = []
    for lyr in QgsProject.instance().mapLayers().values():
        cid = lyr.customProperty("%s/campaign" % PREFIX)
        if cid and (campaign_id is None or cid == campaign_id):
            out.append(lyr)
    return out


def find_mine(campaign_id, role):
    for lyr in my_layers(campaign_id):
        if lyr.customProperty("%s/role" % PREFIX) == role:
            return lyr
    return None


def group_node(name):
    root = QgsProject.instance().layerTreeRoot()
    g = root.findGroup(name)
    return g if g is not None else root.insertGroup(0, name)


def file_key(path):
    """A path as a key: absolute, without the long path prefix, and with the
    case folded where the disk does not tell case apart."""
    path = (path or "").strip()
    if path.startswith("\\\\?\\UNC\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def reads_file(layer, path):
    """Whether this layer is valid and reads the file at path."""
    try:
        if not layer.isValid():
            return False
        return file_key(layer.source().split("|")[0]) == file_key(path)
    except Exception:
        return False


def drop_stale(owner_id, path, roles, what="campaign"):
    """Take out of the project the layers marked as this campaign's that do
    not read its file. Returns how many went.

    A QGIS project saves the layers with their marks. Copy the campaign
    folder, reopen the project and open the copy, and the layers the project
    brought back carry the same campaign id and read the original: found by
    the id and reused, they sent every stroke into the original GeoPackage
    while the panel showed the copy. Move the folder instead and the same
    layers read nothing: invalid, every stroke lost, and a save that said "0
    layers written". So a marked layer is the campaign's only while it is
    valid and reads the campaign's own file; any other is removed, which
    touches no file, and the right one is loaded in its place."""
    gone = []
    for lyr in my_layers(owner_id):
        if lyr.customProperty("%s/role" % PREFIX) not in roles:
            continue
        if reads_file(lyr, path):
            continue
        try:
            was = lyr.source().split("|")[0]
        except Exception:
            was = "?"
        gone.append((lyr.id(), lyr.name(), was, lyr.isValid()))
    if not gone:
        return 0
    with own_hands():
        QgsProject.instance().removeMapLayers([g[0] for g in gone])
    for _, name, was, valid in gone:
        log("the layer '%s' of this %s read %s%s, not %s: taken out of the "
            "project and loaded again from the %s's own file" % (
                name, what, was, "" if valid else ", which is not there",
                path, what), loud=True)
    return len(gone)


def add_layer(layer, campaign, role):
    """Adds only if it is not there already. Returns the live layer.

    "There already" means a layer marked with this campaign and role that is
    valid and reads the same file as the one offered; one that reads another
    file, or nothing, is taken out of the project first (see drop_stale)."""
    existing = find_mine(campaign.data["id"], role)
    if existing is not None:
        source = layer.source().split("|")[0]
        if reads_file(existing, source):
            return existing
        drop_stale(campaign.data["id"], source, (role,))
    mark(layer, campaign.data["id"], role)
    QgsProject.instance().addMapLayer(layer, False)
    group_node(campaign.group_name).addLayer(layer)
    return layer


def drop_layers(campaign_id, group_name):
    """Removes the program's layers from the project without touching a file.

    The group they sit in goes with them only when nothing else is in it.
    Removed whole, it would take a layer of the user's put there, a memory
    layer with an hour of notes in it say, and a memory layer has no file to
    be opened from again. What is not the program's own is not
    the program's to take out, so the group stays, with those layers in it,
    and the log says so."""
    root = QgsProject.instance().layerTreeRoot()
    top = root.findGroup(group_name)
    own = my_layers(campaign_id)
    ids = [l.id() for l in own]
    # The groups inside the campaign's own that hold its layers (the maps of
    # the reports have one each), found before the layers go: afterwards they
    # are empty and nothing says whose they were.
    inner = []
    if top is not None:
        for lid in ids:
            node = root.findLayer(lid)
            up = node.parent() if node is not None else None
            while up is not None and up.parent() is not None:
                if up.name() == group_name:
                    break
                if up.name() not in inner:
                    inner.append(up.name())
                up = up.parent()
    if ids:
        with own_hands():
            QgsProject.instance().removeMapLayers(ids)
    if top is not None:
        for name in inner:
            sub = top.findGroup(name)
            if sub is not None and not sub.children():
                top.removeChildNode(sub)
        left = len(top.children())
        if left:
            log("the group '%s' stays in the project: %d thing%s in it %s not "
                "the program's own" % (group_name, left,
                                       "" if left == 1 else "s",
                                       "is" if left == 1 else "are"),
                loud=True)
        else:
            root.removeChildNode(top)
    # What the layers drew stays on the canvas until something asks it to be
    # drawn again: the project forgets the layers at once, the picture does
    # not, and the polygons of a campaign that is closed stayed on the map
    # until the user panned or zoomed.
    refresh_canvas()
    return len(ids)


def refresh_canvas():
    """Draw the map again from the layers that are in the project now."""
    try:
        view = iface.mapCanvas()
    except Exception:
        return
    if view is None:
        return
    for how in ("refreshAllLayers", "refresh"):
        ask = getattr(view, how, None)
        if callable(ask):
            try:
                ask()
                return
            except Exception as err:
                log("cannot redraw the map: %s" % err)


def passes_found(campaign_id):
    """{operator: {passes}} of the marks in the tables of a campaign, each
    read the way every export reads them (campaign.operator_word and
    pass_number). How a campaign made before the manifest kept a list of
    passes still shows the ones it has."""
    out = {}
    for role in READING_TABLES:
        lyr = find_mine(campaign_id, role)
        if lyr is None:
            continue
        names = {n.lower(): n for n in lyr.fields().names()}
        if "pass_no" not in names:
            continue
        who = names.get("operator")
        for f in lyr.getFeatures():
            out.setdefault(operator_word(f[who] if who else None),
                           set()).add(pass_number(f[names["pass_no"]]))
    return out


#  Styling: the layers must let the raster through
# =====================================================================
def tidy_layers(campaign):
    """Two leftovers from an interrupted session have to go before anything
    else touches the work.

    A feature with no geometry breaks every set operation the brush does, and
    a data filter left on by RasterLabel 1.0 keeps whole tiles invisible
    with no way for the operator to guess why."""
    removed, cleared = 0, []
    for role in ("polygons", "lines", "points", "boxes", "tiles"):
        lyr = find_mine(campaign.data["id"], role)
        if lyr is None:
            continue
        if lyr.subsetString():
            if lyr.isEditable():
                lyr.commitChanges()
            lyr.setSubsetString("")
            cleared.append(role)
        orphans = [f.id() for f in lyr.getFeatures()
                   if not f.hasGeometry() or f.geometry().isEmpty()]
        if not orphans:
            continue
        if not lyr.isEditable():
            lyr.startEditing()
        lyr.deleteFeatures(orphans)
        if lyr.commitChanges():
            removed += len(orphans)
        else:
            with own_hands():
                lyr.rollBack()
    if removed:
        log("%d features with no geometry removed: they would have broken the "
            "drawing" % removed)
    if cleared:
        log("a data filter was still on %s: cleared, everything is visible "
            "again" % ", ".join(cleared))
    return removed, cleared


def style_tiles(layer):
    symbol = QgsFillSymbol.createSimple({
        "color": "255,220,0,25",             # barely there, so the image reads
        "outline_color": "255,220,0,255",
        "outline_width": "0.9",
        "outline_style": "solid"})
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    label_tiles(layer)
    layer.triggerRepaint()


def label_tiles(layer):
    """The number on the frame, and the note beside it when there is one.

    With a dozen frames scattered over a survey, telling them apart by opening
    the list is the kind of small friction that adds up over a day."""
    try:
        settings = QgsPalLayerSettings()
        settings.fieldName = ("\"tile_id\" || coalesce('  ' || \"note\", '')")
        settings.isExpression = True
        text = QgsTextFormat()
        text.setSize(10)
        text.setColor(QColor("#8a2a12"))
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(1.2)
        buffer.setColor(QColor("#ffffff"))
        text.setBuffer(buffer)
        settings.setFormat(text)
        if LABEL_OVER_POINT is not None:
            settings.placement = LABEL_OVER_POINT
        else:
            # older than any QGIS this is installed on, reached only by the
            # single file pasted into the console
            for where in ("OverPoint", "Horizontal", "AroundPoint"):
                value = getattr(QgsPalLayerSettings, where, None)
                if value is not None:
                    settings.placement = value
                    break
        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        layer.setLabelsEnabled(True)
    except Exception as err:
        log("cannot label the frames: %s" % err)


def style_by_class(layer, classes, geometry="polygon", pixel=None):
    """The look of a table, one symbol per class.

    pixel is the size of a raster pixel in the units of the layer, and it is
    what a point is drawn at. A point carries the footprint it stands for,
    size_px, and a dot of a fixed 2.2 millimetres would be the same whether it
    meant one pixel or nine by nine: the number would be in the file and
    nowhere on the screen. Drawn in map units and scaled by its own size_px,
    the dot covers exactly the ground it claims, and a campaign holding both
    kinds shows the difference instead of hiding it."""
    categories = []
    for c in classes:
        if geometry == "box":
            sym = QgsFillSymbol.createSimple({
                "color": "255,255,255,0",       # hollow: you must see what is inside
                "outline_color": rgba(c["colour"]),
                "outline_width": "0.7",
                "outline_style": "solid"})
        elif geometry == "polygon":
            sym = QgsFillSymbol.createSimple({
                "color": rgba(c["colour"], POLYGON_ALPHA),
                "outline_color": rgba(c["colour"]),
                "outline_width": "0.2"})
        elif geometry == "line":
            # drawn thin and solid on purpose: on screen the trace marks where
            # the line was tracked, while the ground it claimed is shown by the
            # strip that went into the polygons. Two different things, and they
            # have to look different or nobody can tell them apart.
            sym = QgsLineSymbol.createSimple({
                "color": rgba(c["colour"]),
                "width": "0.4",
                "capstyle": "round"})
        else:
            sym = QgsMarkerSymbol.createSimple({
                "name": "circle",
                "color": rgba(c["colour"]),
                "outline_color": "255,255,255,255",
                "outline_width": "0.3",
                "size": "2.2"})
            if pixel:
                size_as_ground(sym, pixel)
        categories.append(QgsRendererCategory(c["name"], sym, c["name"]))
    layer.setRenderer(QgsCategorizedSymbolRenderer("class_name", categories))
    layer.triggerRepaint()


def size_as_ground(symbol, pixel):
    """Make a marker as wide as the ground its point speaks for.

    Two things at once: the size is read in map units instead of millimetres,
    so it follows the zoom the way the raster does, and it is given by the
    feature's own size_px times the size of a pixel. A point written before
    the field existed comes back as 1, which is what it meant.

    Wrapped in a try because it is decoration: a QGIS that has moved one of
    these classes should leave the points drawn in the old fixed size, not
    leave the layer with no symbol at all."""
    try:
        # QgsSymbolLayer.Property.Size is the spelling from 3.30 on and the one
        # the plugin site's Qt 6 check asks for; PropertySize is the one before.
        size = first_attr(QgsSymbolLayer, "Property.Size", "PropertySize")
        symbol.setSizeUnit(UNIT_RENDER_MAP)
        symbol.setSize(max(pixel, 1e-12))
        layer0 = symbol.symbolLayer(0)
        layer0.setSizeUnit(UNIT_RENDER_MAP)
        layer0.setDataDefinedProperty(
            size,
            QgsProperty.fromExpression(
                "max(coalesce(\"size_px\", 1), 1) * %.12g" % pixel))
        layer0.setStrokeWidthUnit(UNIT_RENDER_MAP)
        layer0.setStrokeWidth(pixel * 0.15)
    except Exception as err:
        log("the points keep their fixed size: %s" % err)


def pixel_in_layer_units(campaign):
    """One raster pixel across, in the units the layers are stored in.

    Not metres: the campaign of a raster in geographic coordinates is stored
    in degrees, and a symbol asked for two metres there would be drawn two
    degrees wide. pixel_crs is the one already measured in those units."""
    try:
        px, py = campaign.data["grid"].get(
            "pixel_crs", campaign.data["grid"]["pixel_m"])
        return abs(float(px)) or abs(float(py))
    except Exception:
        return 0.0


def restyle(campaign):
    classes = campaign.active_classes()
    pixel = pixel_in_layer_units(campaign)
    for role, how in (("tiles", None), ("polygons", "polygon"),
                      ("lines", "line"),
                      ("points", "point"), ("boxes", "box")):
        lyr = find_mine(campaign.data["id"], role)
        if lyr is None:
            continue
        if how is None:
            style_tiles(lyr)
        else:
            style_by_class(lyr, classes, how, pixel if how == "point" else None)
    try:
        iface.layerTreeView().refreshLayerSymbology(
            find_mine(campaign.data["id"], "polygons").id())
    except Exception:
        pass


#  The layers of the reports
# =====================================================================
# A report's rasters and vectors are loaded in a group of their own inside the
# group of the campaign or the correction they measure, "agreement ANNA p1 vs
# BRUNO p1" or "model vs corrected swept", each layer marked with what it is
# and with the readings it shows, so that a reader who is not to see one of
# them has the layer switched off (veil_report_layers).
REPORT_KEY = "%s/report" % PREFIX
READINGS_KEY = "%s/readings" % PREFIX


def is_report_layer(layer):
    """True for a map a report loaded: a picture of the work, not part of
    it, so neither Whole nor Cutouts offers it as a layer of the dataset."""
    try:
        return bool(layer.customProperty(REPORT_KEY))
    except Exception:
        return False


def report_group_name(kind, label=None):
    """The group a report's layers go in: its kind and its label in words."""
    words = str(kind or "report").replace("_", " ")
    if label:
        words += " " + str(label).replace("_", " ")
    return words


def report_readings_text(readings):
    """Readings as the layer property keeps them: "ANNA,1;BRUNO,1"."""
    out = []
    for r in readings or []:
        try:
            out.append("%s,%d" % (str(r[0]).strip(), int(r[1] or 1)))
        except (TypeError, ValueError, IndexError):
            continue
    return ";".join(out)


def report_readings_of(text):
    """The readings a report layer shows, read back from its property."""
    out = []
    for piece in str(text or "").split(";"):
        if "," not in piece:
            continue
        who, _, p = piece.rpartition(",")
        try:
            out.append((who.strip(), int(p)))
        except ValueError:
            continue
    return out


def add_report_layer(layer, owner, kind, label, part, readings=None,
                     visible=True):
    """Put one layer of a report into the project, in the report's group
    under the group of its owner (a campaign or a correction). Returns the
    layer.

    A report run again loads its layers in place of the older ones of the
    same kind, label and part: the older layer is taken out of the project,
    and its folder, which is never written over, stays where it was."""
    owner_id = owner.data["id"]
    role = "report:%s:%s:%s" % (kind, label or "", part)
    old = [l.id() for l in my_layers(owner_id)
           if l.customProperty("%s/role" % PREFIX) == role]
    if old:
        with own_hands():
            QgsProject.instance().removeMapLayers(old)
    mark(layer, owner_id, role)
    layer.setCustomProperty(REPORT_KEY, kind)
    if readings:
        layer.setCustomProperty(READINGS_KEY, report_readings_text(readings))
    QgsProject.instance().addMapLayer(layer, False)
    parent = group_node(owner.group_name)
    name = report_group_name(kind, label)
    group = parent.findGroup(name)
    if group is None:
        group = parent.addGroup(name)
    node = group.addLayer(layer)
    if node is not None and not visible:
        node.setItemVisibilityChecked(False)
    return layer


def veil_report_layers(owner_id, reader, one_operator, blind):
    """Switch off every report layer of this owner that shows a reading the
    reader may not see, by the rule of the Annotate filter
    (campaign.hidden_from). Returns how many such layers there are, the
    ones already off included. Only switched off, never removed, and never
    switched back on: a reader who may see them again turns them on."""
    veiled = 0
    root = QgsProject.instance().layerTreeRoot()
    for lyr in my_layers(owner_id):
        if not lyr.customProperty(REPORT_KEY):
            continue
        shown = report_readings_of(lyr.customProperty(READINGS_KEY))
        if not any(hidden_from(reader, r, one_operator, blind) for r in shown):
            continue
        veiled += 1
        node = root.findLayer(lyr.id()) if root is not None else None
        if node is not None and node.itemVisibilityChecked():
            node.setItemVisibilityChecked(False)
            log("the layer '%s' shows work hidden from %s, pass %s: switched "
                "off" % (lyr.name(), reader[0], reader[1]))
    return veiled
