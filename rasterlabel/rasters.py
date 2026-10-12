"""rasterlabel.rasters

Reading pixels, burning labels, writing files.
"""
import math
import numpy as np
import os
import xml.etree.ElementTree as ET

from osgeo import gdal, ogr, osr
from qgis.PyQt.QtGui import QColor, QImage
from qgis.core import QgsMultiBandColorRenderer, QgsRectangle

from .constants import (FLAG_BAND_NAME, GEOTIFF_TYPE, MAX_CLASS_CODE,
                        MAX_THEMATIC_CLASSES, PALETTE, STRIP_PX,
                        STRIP_ROWS, WHOLE_FORMATS)
from .errors import log
from .campaign import (consensus_voters, frames_by_readings_text,
                       ignore_refusal, majority, operator_word, pass_number,
                       reading_metadata, unlabelled_metadata)
from .naming import long_path, source_of
from .project import crs_from_text, crs_label


def open_raster(path, *flags):
    """gdal.Open, answering None when the raster cannot be opened.

    GDAL answers None, or raises, depending on whether exceptions are on, and
    in QGIS they are: Processing switches them on when it loads. A layer that
    is no file at all, a web basemap or a database table, is a valid layer
    and not a path GDAL can open, so every place that opens what a layer
    names has to meet both."""
    try:
        return gdal.Open(path, *flags)
    except Exception:
        return None


#  The grid a raster is drawn on
# =====================================================================
# QGIS draws a raster that has no georeference, a photograph or a scan, with
# one unit to the pixel and y going down from 0 to minus the number of rows:
# the grid (0, 1, 0, 0, 0, -1). Every geometry the program stores on such a
# picture is in those coordinates. GDAL, asked for the grid of the same file,
# answers its own default, (0, 1, 0, 0, 0, 1), with y going up. Read that way
# every stroke in Correct fell "outside the map", the mask Whole wrote was
# empty and the record of changes was drawn beside the map instead of on it.
PICTURE_GRID = (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)


def pixel_grid(ds):
    """The grid of a GDAL dataset as QGIS draws it: its geotransform, or
    PICTURE_GRID when the file has none."""
    try:
        gt = ds.GetGeoTransform(can_return_null=True)
    except TypeError:
        # a binding without the keyword: the default is the sign of "none"
        gt = ds.GetGeoTransform()
        if tuple(gt) == (0.0, 1.0, 0.0, 0.0, 0.0, 1.0):
            gt = None
    return PICTURE_GRID if gt is None else tuple(gt)


def has_grid(ds):
    """Whether the file carries a georeference of its own, a world file or
    an .aux.xml among them, rather than the picture grid QGIS gives it."""
    try:
        return ds.GetGeoTransform(can_return_null=True) is not None
    except TypeError:
        return tuple(ds.GetGeoTransform()) != (0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def is_rotated(gt):
    """Whether a geotransform turns the pixels: rows that are not parallel to
    the x axis, as a Helmert world file from the Georeferencer or some
    aerial products have. No pixel-aligned square can be drawn on such a
    grid."""
    return bool(gt) and (abs(gt[2]) > 0 or abs(gt[4]) > 0)


def rotated_file(path):
    """Whether the raster at path is on a rotated grid; False when it cannot
    be read, which whoever reads it next says in its own words."""
    pushed = _quiet_gdal()
    try:
        ds = gdal.Open(str(path).split("|")[0])
    except Exception:
        ds = None
    finally:
        _loud_gdal(pushed)
    if ds is None:
        return False
    turned = is_rotated(pixel_grid(ds))
    ds = None
    return turned


ROTATED_ADVICE = ("Warp it north-up first, keeping its system: Raster > "
                  "Projections > Warp (Reproject), nearest neighbour for a "
                  "map of classes, or gdalwarp -r near <map> <map>_northup.tif")


def rotated_refusal(path):
    """Why Correct does not take a map on a rotated grid, in words."""
    return ("'%s' has a rotated pixel grid: its rows are not parallel to the "
            "x axis. Correct works on the map's own pixels, and a stroke on "
            "this grid would change pixels beside the ones under it, while "
            "the log and the tally recorded it as right.\n\n%s, and correct "
            "that one." % (os.path.basename(str(path).split("|")[0]),
                           ROTATED_ADVICE))


def wkt_of(ds, layer=None):
    """The coordinate system to write into a file made from ds: the file's
    own, or, when the file names none, the one set on its layer in QGIS
    (Layer > Set CRS, or a .prj the program applied). Read from GDAL alone,
    a system set in QGIS reached the manifest but not the mask, the cutouts
    or the corrected copy, which then opened with none."""
    try:
        own = ds.GetProjection() or ""
    except Exception:
        own = ""
    if own:
        return own
    try:
        if layer is not None and layer.crs().isValid():
            return layer.crs().toWkt()
    except Exception:
        pass
    return ""


def prj_beside(path):
    """The system a .prj beside a raster names, as (wkt, label), or None.

    GDAL reads the world file of a PNG, a JPEG, a BMP, a WebP or a JPEG 2000
    and not the .prj beside it, so a picture placed with both opens in QGIS
    on the right grid and with no system."""
    base = str(path).split("|")[0]
    for prj in (os.path.splitext(base)[0] + ".prj", base + ".prj"):
        if not os.path.isfile(prj):
            continue
        try:
            with open(prj, encoding="utf-8", errors="replace") as f:
                text = f.read().strip()
        except OSError:
            continue
        if not text:
            continue
        srs = osr.SpatialReference()
        try:
            ok = srs.SetFromUserInput(text) == 0
        except Exception:
            ok = False
        if not ok:
            try:
                ok = srs.ImportFromESRI([text]) == 0
            except Exception:
                ok = False
        if not ok:
            continue
        try:
            srs.AutoIdentifyEPSG()
        except Exception:
            pass
        wkt = srs.ExportToWkt()
        crs = crs_from_text(wkt)
        if not wkt or not crs.isValid():
            continue
        return wkt, crs_label(crs)
    return None


def crs_not_in_file(layer):
    """A coordinate system the layer could have and its file does not
    carry, as (wkt, label, where), or None.

    where is "prj" for a .prj beside the file that QGIS did not apply, and
    "qgis" for a system set on the layer in QGIS by hand. The files the
    program writes from the raster are written through GDAL, and GDAL knows
    neither.

    A .prj is offered only for a file GDAL places on the ground, by a world
    file or otherwise: beside a picture whose world file this GDAL does not
    read (the .wpw of a WebP before GDAL 3.9) it would put the picture's
    pixels, at 0, 0, into that system (raster_notes says so instead)."""
    path = source_of(layer)
    pushed = _quiet_gdal()
    try:
        ds = gdal.Open(path)
    except Exception:
        ds = None
    finally:
        _loud_gdal(pushed)
    if ds is None:
        return None
    own = ds.GetProjection() or ""
    placed = has_grid(ds)
    ds = None
    if own:
        return None
    if layer.crs().isValid():
        return layer.crs().toWkt(), crs_label(layer.crs()), "qgis"
    found = prj_beside(path) if placed else None
    if found is not None:
        return found[0], found[1], "prj"
    return None


def write_crs_beside(path, wkt):
    """Write a coordinate system for a raster into the .aux.xml beside it,
    where GDAL keeps what a format cannot hold, and say whether GDAL reads
    it back. The raster itself is not touched."""
    base = str(path).split("|")[0]
    pushed = _quiet_gdal()
    try:
        ds = gdal.Open(base)
        if ds is None:
            return False
        ds.SetProjection(wkt)
        ds.FlushCache()
        ds = None
        back = gdal.Open(base)
        ok = back is not None and bool(back.GetProjection())
        back = None
    except Exception as err:
        log("cannot write the coordinate system beside %s: %s"
            % (os.path.basename(base), err))
        ok = False
    finally:
        _loud_gdal(pushed)
    return ok


def raster_notes(layer):
    """What the New campaign window says about a raster beyond its pixel and
    its system, one sentence each: the grid turned, the photo turned, the
    system left out of the file."""
    out = []
    path = source_of(layer)
    pushed = _quiet_gdal()
    try:
        ds = gdal.Open(path)
    except Exception:
        ds = None
    finally:
        _loud_gdal(pushed)
    if ds is None:
        return out
    gt = pixel_grid(ds)
    placed = has_grid(ds)
    own_wkt = ds.GetProjection() or ""
    width, height = ds.RasterXSize, ds.RasterYSize
    try:
        turned = ds.GetMetadataItem("EXIF_Orientation")
    except Exception:
        turned = None
    ds = None
    if is_rotated(gt):
        out.append(
            "Its pixel grid is rotated: QGIS shows its %d x %d pixels "
            "resampled north-up, as %d x %d, and frames, lines and points sit "
            "on that view of it, up to half a pixel off its own pixels. "
            "Correct refuses such a map. %s."
            % (width, height, layer.width(), layer.height(), ROTATED_ADVICE))
    if turned not in (None, "", "1"):
        out.append(
            "This photo is stored turned (EXIF orientation %s): QGIS shows it "
            "as it is stored, which a photo viewer does not, and the mask and "
            "the cutouts follow the stored pixels. Rotate the file itself "
            "first if that is not what you want." % turned)
    missing = crs_not_in_file(layer)
    stray = None if placed or layer.crs().isValid() else prj_beside(path)
    if stray is not None:
        out.append(
            "A .prj beside the file names %s, but GDAL found no world file "
            "it reads to place the picture with, so it is drawn at 0, 0 with "
            "one unit to the pixel and the system is not applied. If it "
            "belongs on the ground, georeference it first (Raster > "
            "Georeferencer) or open it in a QGIS whose GDAL reads its world "
            "file." % stray[1])
    if missing is not None and missing[2] == "prj":
        out.append(
            "A .prj beside the file names %s, but QGIS did not apply it, "
            "because GDAL does not read a .prj beside this format. Ok offers "
            "to write it beside the file, so that the campaign, the masks and "
            "the cutouts carry it." % missing[1])
    elif missing is not None:
        out.append(
            "Its system, %s, is the one its layer has in QGIS, set by hand "
            "or by the project, and is not in the file. Ok offers to write it "
            "beside the file, so that the masks and the cutouts carry it "
            "too." % missing[1])
    elif placed and not own_wkt and not layer.crs().isValid():
        out.append(
            "It is placed by a world file or an .aux.xml but names no "
            "coordinate system, so sizes are in the units of that file, not "
            "metres. If you know its system, set it first (Layer > Set CRS) "
            "and open this window again.")
    return out


def burn(shapes, gt, w, h, wkt):
    """A byte raster of the given (geometry, value) pairs on the given grid.

    GDAL without ALL_TOUCHED burns the pixels whose centre falls inside the
    polygon, which is the convention the whole program uses. Features are
    burned in the order they arrive, so the last one has the final word."""
    target = gdal.GetDriverByName("MEM").Create("", w, h, 1, gdal.GDT_Byte)
    target.SetGeoTransform(gt)
    if wkt:
        target.SetProjection(wkt)
    target.GetRasterBand(1).Fill(0)
    srs = None
    if wkt:
        srs = osr.SpatialReference()
        try:
            srs.ImportFromWkt(wkt)
        except Exception:
            srs = None
    source = Stencil.in_memory("burn")
    layer = source.CreateLayer("g", srs, ogr.wkbUnknown)
    layer.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    definition = layer.GetLayerDefn()
    written = 0
    for geom, value in shapes:
        try:
            shape = ogr.CreateGeometryFromWkb(bytes(geom.asWkb()))
        except Exception:
            shape = None
        if shape is None:
            continue
        feature = ogr.Feature(definition)
        feature.SetGeometry(shape)
        feature.SetField("v", int(value))
        layer.CreateFeature(feature)
        feature = None
        written += 1
    if written:
        gdal.RasterizeLayer(target, [1], layer,
                            options=["ATTRIBUTE=v", "ALL_TOUCHED=FALSE"])
    out = target.GetRasterBand(1).ReadAsArray()
    layer = None
    source = None
    target = None
    return out


def paint_whole(recipe, progress=None):
    """The whole raster, with the annotation of the campaign on it.

    Written in horizontal strips. A survey is a couple of gigabytes and holding
    it whole would fail on the machines this runs on, so a strip of output rows
    is read, painted and written, and only that strip is ever in memory. The
    cost is that the stretch has to be decided before the loop starts, from the
    layer's own display limits or from a first cheap pass, instead of from the
    pixels of each strip: a stretch that changed from strip to strip would put
    visible seams across the picture.

    Nothing here assumes a survey. A raster with no projection and no
    georeferencing, a scan or a photograph, is written back with whatever
    transform QGIS gave it and without a projection, and everything else works
    the same: the plugin is an annotator that happens to know about maps, not a
    map tool that happens to annotate.

    The pictures are drawn the way QGIS draws the layer on the screen, strip
    by strip, through its own style: the bands it shows, its stretch or none,
    its palette, its brightness, contrast and saturation (styled_strip).
    Rebuilt from the raw bands with a stretch of their own, an image would
    come out in other colours than the screen, a palette as grey indices, and
    what is transparent on the screen as opaque.
    Where the layer may be transparent, the pictures get an alpha band; a
    JPEG cannot hold one and gets what is transparent on white."""
    src = recipe["ds"]
    scale = max(1, int(recipe["scale"]))
    w = max(1, src.RasterXSize // scale)
    h = max(1, src.RasterYSize // scale)
    gt0 = pixel_grid(src)
    gt = (gt0[0], gt0[1] * scale, gt0[2] * scale,
          gt0[3], gt0[4] * scale, gt0[5] * scale)
    wkt = src.GetProjection()
    bands = recipe["rgb"]
    limits = recipe["limits"]
    alpha = recipe["alpha"] / 100.0
    colours = recipe["colours"]          # code -> (r, g, b)
    layer = recipe.get("layer")
    # Decided once, before any file is made: the band count of a file cannot
    # change half way through it.
    see_through = layer is not None and may_be_transparent(layer, src)
    styled = layer is not None
    written = []

    # Which readings go in. Every one of them, last drawn on top, is what
    # this always did, and is right when the passes are layers of one piece
    # of work. Two operators reading the same frame are not layers: on top of
    # each other the second one simply erased the first wherever they
    # differed, and the mask was neither reading. So the work can be narrowed
    # to one reading, or the readings can vote.
    choice = recipe.get("reading") or {"mode": "all"}
    mode = choice.get("mode", "all")
    chosen = [tuple(r) for r in choice.get("readings") or []]
    keep = None if mode == "all" else set(chosen)

    # the stencils, built once: the ground the classes claim, the traces of the
    # lines on top of it, the points, and the outlines of the boxes
    package = recipe["package"]
    # the whole geotransform, rotation terms and all: the four numbers of a
    # north-up grid put every point of a rotated raster in the wrong pixel
    grid = tuple(gt)
    areas = Stencil(package, "polygons", "class_code", wkt, keep=keep) \
        if mode != "consensus" else None
    traces = Stencil(package, "lines", "class_code", wkt, keep=keep) \
        if recipe["want_lines"] else None
    # every point is grown to its own footprint, read off the feature: a
    # campaign can hold a coarse first pass and a fine second one, and drawing
    # them all at one size would hide exactly the difference that matters
    dots = Stencil(package, "points", "class_code", wkt,
                   size_field="size_px", grid=grid,
                   fallback=recipe.get("dot_px", 1), keep=keep) \
        if recipe["want_points"] else None
    frames = Stencil(package, "boxes", "class_code", wkt,
                     transform=lambda g: g.Boundary(), keep=keep) \
        if recipe["want_boxes"] else None
    points_in = bool(recipe["points_in_mask"] and recipe["want_points"])
    # A consensus is voted pixel by pixel, and every reading votes with what
    # its own mask would hold: its areas, and its points on top when they go
    # into the mask.
    voters = []
    electorate = None
    by_some = False
    if mode == "consensus":
        # who votes where: in a frame the readings that covered it, not all
        # of them (a frame read by 2 of 4 people needs both of the 2)
        electorate = ConsensusCover(package, wkt, chosen, points_in)
        # said back to the caller, which words the rule it reports
        by_some = recipe["consensus_partial"] = electorate.partial
        for r in chosen:
            voters.append((
                Stencil(package, "polygons", "class_code", wkt, keep={r}),
                Stencil(package, "points", "class_code", wkt,
                        size_field="size_px", grid=grid,
                        fallback=recipe.get("dot_px", 1), keep={r})
                if points_in else None))
    # The mask is one byte a pixel while every code fits in one, which is
    # always, since a campaign hands out no code past MAX_CLASS_CODE. A
    # campaign that holds one all the same, from a manifest edited by hand
    # or a build with no ceiling, gets a mask wide enough for it, instead of
    # the byte that turned class 256 into 0 without a word.
    feeding = [s for pair in voters for s in pair] \
        + [areas] + ([dots] if points_in else [])
    feeding = [s for s in feeding if s is not None]
    # What the mask holds where nobody painted: 0, as RasterLabel 1.0
    # wrote it, or an ignore value, everywhere or only outside the
    # frames. Inside a frame, ground nobody painted is then 0, the class
    # "none of these"; a polygon traced outside every frame keeps its class.
    unlabelled = recipe.get("unlabelled") or "zero"
    ignore = recipe.get("ignore") if unlabelled != "zero" else None
    if ignore is None:
        unlabelled = "zero"
    fenced = None
    if unlabelled == "frames":
        # frames belong to nobody: every one of them, whoever drew in it
        fenced = Stencil(package, "tiles", None, wkt, value=1)
    mask_kind = mask_type(
        max([getattr(s, "highest", 0) for s in feeding] or [0]),
        min([getattr(s, "lowest", 0) for s in feeding] or [0]),
        ignore)
    # Counted as written, for the dataset card: what each file holds,
    # value by value, from the very arrays that go to disk.
    tally = recipe.get("tally")

    # which of the targets did not exist before we started. Only those may be
    # taken away if something goes wrong: a file the user agreed to replace is
    # still their file until it has been replaced, and destroying it while the
    # dialog says "nothing was written" is the worst of both.
    ours = {path for _, path, _ in recipe["outputs"]
            if not os.path.exists(path)}
    targets = {}
    try:
        # Refused before any file exists: a mark with no class code would
        # go out as 0 among ignore values, a claim nobody made; and an
        # ignore value a class already uses would make that class vanish
        # from the training.
        if ignore is not None and any(k == "mask"
                                      for k, _, _ in recipe["outputs"]):
            if fenced is not None and not fenced.ok:
                raise ValueError("the campaign has no frames to tell inside "
                                 "from outside")
            uncoded = sum(getattr(s, "uncoded", 0) for s in feeding)
            if uncoded:
                raise ValueError(
                    "%d mark%s no class code (0 or empty): give %s a class, "
                    "or run Check" % (uncoded, "s have" if uncoded > 1
                                      else " has", "them" if uncoded > 1
                                      else "it"))
            held = set()
            for s in feeding:
                held |= getattr(s, "codes", set())
            refusal = ignore_refusal(ignore, held)
            if refusal:
                raise ValueError(refusal)
        for what, path, driver in recipe["outputs"]:
            if what == "mask":
                ds = open_for_write(driver, path, w, h, 1, gt, wkt,
                                    dtype=mask_kind)
                if ignore is not None:
                    # the absence, declared: QGIS draws it see-through and
                    # a loader reads it as the value to leave out
                    ds.GetRasterBand(1).SetNoDataValue(ignore)
            elif what == "votes":
                # beside a consensus: how many readings gave each pixel its
                # class, and how many painted it at all; and, where some
                # frames were read by fewer readings than the vote holds,
                # how many of them voted there
                ds = open_for_write(driver, path, w, h,
                                    3 if by_some else 2, gt, wkt)
            else:
                clear = see_through and driver != "JPEG"
                ds = open_for_write(driver, path, w, h, 4 if clear else 3,
                                    gt, wkt, alpha=clear)
            targets[what] = (ds, path, driver)
            ds = None

        rows = 0
        while rows < h:
            take = min(STRIP_ROWS, h - rows)
            # The corner of the strip, row `rows` and column 0, on the full
            # affine grid: a rotated raster moves along x as well as y from
            # one row to the next, and with y alone every strip after the
            # first was burned metres away from its pixels.
            gt_strip = (gt[0] + rows * gt[2], gt[1], gt[2],
                        gt[3] + rows * gt[5], gt[4], gt[5])
            # And where the strip lies in the whole, so the shapes are
            # burned in the pixels of the whole raster and a strip of any
            # height gives the pixels one pass would (Stencil.burn_into).
            at = {"whole": grid, "row": rows}

            need_picture = any(k in targets for k in
                               ("painted", "plain", "figure"))
            picture = opacity = None
            if need_picture and styled:
                drawn = styled_strip(layer, gt_strip, w, take)
                if drawn is not None:
                    picture, opacity = drawn
                elif rows == 0:
                    # Not drawable here (a rotated raster: QGIS draws it on a
                    # grid of its own), so every strip is stretched from the
                    # bands instead, the first as the last: a strip drawn one
                    # way beside a strip drawn the other would be a seam.
                    styled = False
            if need_picture and picture is None:
                block = src.ReadAsArray(
                    0, rows * scale, src.RasterXSize, take * scale,
                    buf_xsize=w, buf_ysize=take)
                if block is None:
                    raise IOError("cannot read the raster at row %d" % rows)
                if block.ndim == 2:
                    block = block[None]
                picture = np.zeros((3, take, w), np.uint8)
                for i, b in enumerate(bands):
                    plane = block[min(b - 1, block.shape[0] - 1)].astype(np.float32)
                    low, high = limits[i]
                    picture[i] = (255 * np.clip(
                        (plane - low) / max(high - low, 1e-6), 0, 1)).astype(np.uint8)
                block = None
                if see_through:
                    # what GDAL calls no data, or the raster's own alpha
                    held = src.GetRasterBand(min(bands[0], src.RasterCount))
                    opacity = held.GetMaskBand().ReadAsArray(
                        0, rows * scale, src.RasterXSize, take * scale,
                        buf_xsize=w, buf_ysize=take)
                    held = None
            if opacity is not None and int(opacity.min()) == 255:
                opacity = None

            if "plain" in targets:
                put_picture(targets["plain"][0], picture, opacity, rows)

            if mode == "consensus":
                labels = []
                for own, own_dots in voters:
                    label = own.burn_into(gt_strip, w, take, wkt, **at)
                    if own_dots is not None:
                        d = own_dots.burn_into(gt_strip, w, take, wkt,
                                               **at)
                        label = np.where(d > 0, d, label)
                    labels.append(label)
                member = electorate.voting(gt_strip, w, take, wkt, **at)
                classes, votes, labelled = vote(labels, member)
                extra = classes
                # painted by some and agreed by too few: not a label
                disputed = (labelled > 0) & (classes == 0)
                if "votes" in targets:
                    out = targets["votes"][0]
                    out.GetRasterBand(1).WriteArray(votes, 0, rows)
                    out.GetRasterBand(2).WriteArray(labelled, 0, rows)
                    if by_some:
                        out.GetRasterBand(3).WriteArray(
                            electorate.how_many(member, labelled.shape)
                            .astype(votes.dtype), 0, rows)
                    out = None
                    if tally is not None:
                        _tally_add(tally, "votes", votes)
            else:
                classes = areas.burn_into(gt_strip, w, take, wkt, **at)
                extra = classes
                disputed = None
                if points_in and dots is not None and "mask" in targets:
                    d = dots.burn_into(gt_strip, w, take, wkt, **at)
                    extra = np.where(d > 0, d, classes)
            if "mask" in targets:
                if ignore is not None:
                    inside = None
                    if fenced is not None:
                        inside = fenced.burn_into(gt_strip, w, take, wkt,
                                                  **at) > 0
                    extra = settle_unlabelled(extra, unlabelled, ignore,
                                              class_array(mask_kind), inside,
                                              disputed)
                targets["mask"][0].GetRasterBand(1).WriteArray(extra, 0, rows)
                if tally is not None:
                    _tally_add(tally, "mask", extra)

            if need_picture and ("painted" in targets or "figure" in targets):
                over = picture.astype(np.float32)
                # how opaque the picture is under the paint, 0 to 1, or None
                # where all of it is
                cover = None if opacity is None \
                    else opacity.astype(np.float32) / 255.0
                # the areas, translucent, so the image stays readable under them
                hit = classes > 0
                if hit.any():
                    for code, (r, g, b) in colours.items():
                        m = classes == code
                        if not m.any():
                            continue
                        if cover is None:
                            for i, v in enumerate((r, g, b)):
                                over[i][m] = over[i][m] * (1 - alpha) + v * alpha
                            continue
                        # over a picture that is itself see-through, the paint
                        # goes on top of what is there: on a transparent pixel
                        # it is the class colour at the opacity of the paint
                        below = cover[m]
                        top = alpha + below * (1 - alpha)
                        for i, v in enumerate((r, g, b)):
                            under = over[i][m] * below * (1 - alpha)
                            over[i][m] = (v * alpha + under) / top
                        cover[m] = top
                # the thin things, solid: a trace blended at forty per cent on
                # a busy image is a trace nobody can follow
                for stencil, touched in ((traces, True), (dots, False),
                                         (frames, True)):
                    if stencil is None:
                        continue
                    burned = stencil.burn_into(gt_strip, w, take, wkt,
                                               all_touched=touched, **at)
                    for code, (r, g, b) in colours.items():
                        m = burned == code
                        if not m.any():
                            continue
                        for i, v in enumerate((r, g, b)):
                            over[i][m] = v
                        if cover is not None:
                            cover[m] = 1.0
                over = np.clip(over, 0, 255).astype(np.uint8)
                shown = None if cover is None else \
                    np.clip(np.rint(cover * 255), 0, 255).astype(np.uint8)
                for kind in ("painted", "figure"):
                    if kind in targets:
                        put_picture(targets[kind][0], over, shown, rows)

            rows += take
            if progress is not None:
                progress(rows, h)

        # Which readings went in, and how, said inside every GeoTIFF that
        # comes out, so a mask found in a folder a year later still says
        # whose it is. PNG and JPEG keep no such thing in the file, and GDAL
        # would put it in an .aux.xml beside them, a second file nobody asked
        # for; their names say it instead.
        for what in list(targets):
            ds, path, driver = targets[what]
            if driver == "GTiff":
                # and with them the build, the campaign and the pixel rule,
                # when the caller hands them (the dataset card does), and on
                # the mask what it holds where nobody painted
                items = dict(reading_metadata(choice, by_some),
                             **(recipe.get("provenance") or {}))
                if by_some:
                    items["RASTERLABEL_FRAMES_READ_BY"] = electorate.said()
                if what == "mask":
                    items.update(unlabelled_metadata(
                        unlabelled, ignore, mode == "consensus"))
                ds.SetMetadata(items)
                if what == "mask":
                    ds.GetRasterBand(1).SetDescription("class_code")
                elif what == "votes":
                    ds.GetRasterBand(1).SetDescription("votes")
                    ds.GetRasterBand(2).SetDescription("readings_labelled")
                    if ds.RasterCount > 2:
                        ds.GetRasterBand(3).SetDescription("readings_voting")
            finish_write(ds, driver, path)
            # the last two references to the dataset go, which closes it, and
            # only then can its scratch file be taken away on Windows. The
            # entry stays: a later file that fails still takes this one away
            # with it, as it always did.
            ds = None
            targets[what] = (None, path, driver)
            if driver != "GTiff":
                drop_scratch(path)
            written.append(path)
        # The legend of the mask, once every file is on disk: its classes as
        # a colour table and category names inside a GeoTIFF, and a .qml
        # beside it for QGIS. Without them the codes open as grey, and
        # whoever is handed the mask cannot tell what a 3 is. The codes in
        # the file are not touched.
        if "mask" in targets and recipe.get("classes"):
            said, style = dress_mask(targets["mask"][1], targets["mask"][2],
                                     recipe["classes"])
            if said:
                log(said)
            if style:
                recipe["sidecars"] = list(
                    recipe.get("sidecars") or []) + [style]
        targets = {}
    finally:
        # something went wrong part way: nothing half written is left behind
        # to be mistaken for a finished file. Every reference to a dataset has
        # to be gone before its file can be removed, because Windows refuses
        # to delete a file that is still open (Linux does not mind, which is
        # why this only shows up on Windows). Clearing the local name and
        # popping the entry from targets is not enough if the loop walks a
        # snapshot list of the items: that list lives until the loop ends and
        # holds every (dataset, path, driver) tuple, so the dataset is never
        # closed, the removal fails, and the failure is swallowed. So the loop
        # walks the keys only, the entry is popped and unpacked, and once ds
        # is cleared nothing else holds the dataset.
        for kind in list(targets):
            ds, path, driver = targets.pop(kind)
            ds = None
            if driver != "GTiff":
                # the scratch GeoTIFF a PNG or a JPEG was being painted into
                # is always ours, whatever happens to the file itself
                drop_scratch(path)
            if path not in ours:
                log("%s was there before and is left alone"
                    % os.path.basename(path))
                continue
            if not os.path.exists(path):
                # Nothing reached the disk, so there is nothing to take
                # away and nothing to warn about. This is the normal case
                # for PNG and JPEG, which are painted into a scratch file
                # and copied out only by finish_write at the very end: a
                # failure before that leaves no file at all. Removing it anyway raised
                # FileNotFoundError, and the warning below then told the
                # user, in the message bar, that a half-written file had
                # been left behind when there was none. The warning is for
                # a file that is really there and really could not be
                # removed, which is the only case it is kept for.
                continue
            try:
                os.remove(path)
            except OSError as e:
                # not fatal, the real error is already on its way up; but a
                # half-written file left behind has to be said out loud, or
                # it will be taken for a finished one
                log("%s is half written and could not be removed: %s"
                    % (os.path.basename(path), e), loud=True)
        for st in [areas, traces, dots, frames, fenced, electorate] + [
                s for pair in voters for s in pair]:
            if st is not None:
                st.close()
    return written, (w, h)


def mask_type(highest, lowest=0, ignore=None):
    """The narrowest type that holds these class codes in a mask.

    One byte while every code is between 0 and MAX_CLASS_CODE, which is the
    only case a campaign can make; wider only for a code that really is past
    it, so a mask is never made two bytes deep for codes that fit in one.

    With an ignore value it must hold that too: 255 beside codes up to
    MAX_CLASS_CODE is still one byte, which is what 255 was kept for; a
    negative one is signed, 16 bits when the codes allow it; a larger one
    is 16 bits unsigned."""
    if ignore is not None:
        if ignore < 0:
            if lowest >= -32768 and highest <= 32767:
                return gdal.GDT_Int16
            return gdal.GDT_Int32
        if ignore == 255 and 0 <= lowest and highest <= MAX_CLASS_CODE:
            return gdal.GDT_Byte
        hi = max(highest, ignore)
        if lowest >= 0 and hi <= 65535:
            return gdal.GDT_UInt16
        return gdal.GDT_Int32
    if lowest < 0:
        return gdal.GDT_Int32
    if highest <= MAX_CLASS_CODE:
        return gdal.GDT_Byte
    if highest <= 65535:
        return gdal.GDT_UInt16
    return gdal.GDT_UInt32


def settle_unlabelled(classes, mode, ignore, dtype, inside=None,
                      disputed=None):
    """The mask as it goes to disk: the class codes in the type of the file,
    and the ignore value where nobody painted.

    "ignore" writes it wherever the codes are 0; "frames" only outside every
    frame (inside is True within one), and where the readings of a consensus
    painted and did not agree, inside a frame too: that is not "none of
    these", it is ground nobody could agree on. "zero" leaves the 0. A label
    always wins: a polygon traced outside the frames keeps its class."""
    out = classes.astype(dtype)
    if ignore is None or mode == "zero":
        return out
    empty = classes == 0
    if mode == "frames":
        where = empty if inside is None else empty & ~inside
        if disputed is not None:
            where = where | (empty & disputed)
        out[where] = ignore
    else:
        out[empty] = ignore
    return out


def _tally_add(tally, what, values):
    """Count the values of one strip into tally[what], {value: pixels}.
    Bytes and 16 bits unsigned by bincount, which does not sort a strip of
    a whole survey; anything else by unique."""
    held = tally.setdefault(what, {})
    if values.dtype.kind == "u" and values.dtype.itemsize <= 2:
        n = np.bincount(values.ravel())
        found = np.nonzero(n)[0]
        n = n[found]
    else:
        found, n = np.unique(values, return_counts=True)
    for v, c in zip(found.tolist(), n.tolist()):
        held[int(v)] = held.get(int(v), 0) + int(c)


def class_array(kind):
    """The numpy type a class band of one of the types class_band_type
    answers is held in."""
    return {gdal.GDT_Byte: np.uint8, gdal.GDT_UInt16: np.uint16,
            gdal.GDT_Int16: np.int16}.get(kind, np.int32)


def is_class_code(value):
    """True when value can be a class code: a whole number a 32 bit integer
    holds. The nodata of a float map is often not one."""
    return (math.isfinite(value) and value == math.floor(value)
            and -2 ** 31 <= value < 2 ** 31)


def class_nodata(ds, band_no, held):
    """The nodata a cutout of this class band declares, when it has one.

    The map's own nodata, when it is a class code the cutout's type holds and
    not 0 (zero stays "no class", a value with a meaning, never an absence).
    When the map's nodata is not a code at all, as with -3.4e38 in a float
    map, the pixels that hold it need a number to be written as and a
    nodata to be declared as: the top of the type, which class_band_type left
    room for. None for a map with no nodata."""
    nodata = ds.GetRasterBand(band_no).GetNoDataValue()
    if nodata is None or not math.isfinite(nodata):
        return None
    limits = np.iinfo(class_array(held))
    if not is_class_code(nodata):
        return int(limits.max)
    if nodata == 0 or not limits.min <= nodata <= limits.max:
        return None
    return int(nodata)


def class_band_type(ds, band_no, ignore=None):
    """The type a cutout of this class band is written in: a byte when every
    value the band holds fits in one, and the narrowest wider type only when a
    value really does not.

    It was always a byte, whatever the map: a map of classes stored in 16
    bits with a class 300 came out of every cutout with 300 turned into 44,
    and nothing said so. These are the map's own values, not codes this
    program handed out, so nothing is kept back here: a 255 in the map is a
    255 in the cutout. Decided on the whole band, not on the window, so every
    cutout of one map comes out in the same type; the nodata value counts,
    because a window that runs past the edge of the map holds it.

    So does an ignore value the cutout writes over the padding and the
    map's own nodata: a byte map cut with an ignore of 300 or -100 needs
    the wider type."""
    band = ds.GetRasterBand(band_no)
    fits = ignore is None or 0 <= ignore <= 255
    if band.DataType == gdal.GDT_Byte and fits:
        return gdal.GDT_Byte
    nodata = band.GetNoDataValue()
    try:
        low, high = band.ComputeRasterMinMax(False)
    except Exception:
        low = high = None
    if low is None or high is None:
        low = high = 0.0
    if nodata is not None and math.isfinite(nodata):
        if is_class_code(nodata):
            low, high = min(low, nodata), max(high, nodata)
        elif ignore is None:
            # A nodata that is not a class code at all, the -3.4e38 that
            # Raster Calculator and SAGA write for a float map: it must not
            # widen the type to hold it. The cutout takes a code of its own
            # for it, the top of whatever type the classes need, so one more
            # than the highest class has to fit.
            high = high + 1
    if ignore is not None:
        low, high = min(low, ignore), max(high, ignore)
    low, high = math.floor(low), math.floor(high)
    if low >= 0 and high <= 255:
        return gdal.GDT_Byte
    if low >= 0 and high <= 65535:
        return gdal.GDT_UInt16
    if low >= -32768 and high <= 32767:
        return gdal.GDT_Int16
    return gdal.GDT_Int32


def vote(labels, member=None):
    """The consensus of several readings of the same pixels.

    labels holds one array per reading, the class each pixel has in it and 0
    where it has none. A pixel takes the class a strict majority of the
    readings gave it, and 0 where no class has one: of two readings, the class
    both gave it. A strict majority can be held by one class only, so there is
    never a tie to break. Returns the classes, how many readings gave each
    pixel its class (0 where it has none), and how many painted it at all:
    where those two differ, the readings disagree.

    member, when given, is an array of booleans, readings by rows by columns,
    true where that reading takes part in the vote at that pixel: a reading
    that did not cover the frame gives no vote and no label there, and the
    majority is of the readings that did (ConsensusCover). None: every
    reading votes everywhere."""
    stack = np.stack(labels)
    n = stack.shape[0]
    if member is None:
        need = majority(n)
    else:
        stack = np.where(member, stack, 0).astype(stack.dtype)
        need = majority(member.sum(axis=0))
    small = np.uint8 if n <= 255 else np.uint16
    classes = np.zeros(stack.shape[1:], stack.dtype)
    votes = np.zeros(stack.shape[1:], small)
    for code in np.unique(stack):
        if code == 0:
            continue
        count = (stack == code).sum(axis=0)
        won = count >= need
        classes[won] = code
        votes[won] = count[won]
    labelled = (stack != 0).sum(axis=0).astype(small)
    return classes, votes, labelled


def styled_source(layer):
    """What QGIS draws a raster layer from, up to its colours: the renderer,
    then the brightness, contrast and gamma, then the hue and saturation. Not
    the resampling and the reprojection that come after them in the pipe: a
    strip is asked for on the raster's own pixels, where they do nothing."""
    pipe = layer.pipe()
    for name in ("hueSaturationFilter", "brightnessFilter"):
        try:
            stage = getattr(pipe, name)()
        except Exception:
            stage = None
        if stage is not None and stage.input() is not None:
            return stage
    return layer.renderer()


def styled_strip(layer, gt, w, h):
    """A strip of the raster as QGIS shows it, drawn by the layer's own style:
    three bands and the alpha, or None when it cannot be drawn here.

    It can be only on a grid QGIS draws the raster on pixel for pixel, north
    up: a rotated raster QGIS draws on a grid of its own, and the strip
    would not land on its pixels."""
    if abs(gt[2]) + abs(gt[4]) > 0 or gt[1] <= 0 or gt[5] >= 0:
        return None
    try:
        extent = QgsRectangle(gt[0], gt[3] + h * gt[5], gt[0] + w * gt[1],
                              gt[3])
        # Always with a feedback: the hue and saturation stage of QGIS reads
        # it without asking whether it was given one, and a strip asked for
        # without one crashes QGIS the moment the saturation is changed.
        # Imported here, the one place it is needed.
        from qgis.core import QgsRasterBlockFeedback
        block = styled_source(layer).block(1, extent, w, h,
                                           QgsRasterBlockFeedback())
        if block is None or not block.isValid():
            return None
        image = block.image()
        if image is None or image.isNull() \
                or (image.width(), image.height()) != (w, h):
            return None
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        line = image.bytesPerLine()
        bits = image.constBits()
        bits.setsize(line * h)
        data = np.frombuffer(bits, np.uint8).reshape(h, line)
        data = data[:, :w * 4].reshape(h, w, 4)
        picture = np.ascontiguousarray(data[:, :, :3].transpose(2, 0, 1))
        shown = np.ascontiguousarray(data[:, :, 3])
        return picture, shown
    except Exception as err:
        log("%s could not be drawn with its style, the whole raster is "
            "stretched from its bands instead: %s" % (layer.name(), err))
        return None


def may_be_transparent(layer, ds):
    """Whether QGIS may show some of this raster see-through: an alpha band, a
    nodata value, a transparent colour or class, an opacity below full. The
    pictures of the whole raster then get an alpha band of their own, decided
    once, before the first strip: the band count of a file cannot change half
    way through it."""
    try:
        renderer = layer.renderer()
        if renderer is not None:
            if renderer.opacity() < 1.0 or renderer.alphaBand() > 0:
                return True
            kept = renderer.rasterTransparency()
            if kept is not None and not kept.isEmpty():
                return True
            if renderer.type() == "paletted" and any(
                    c.color.alpha() < 255 for c in renderer.classes()):
                return True
        provider = layer.dataProvider()
        for b in range(1, provider.bandCount() + 1):
            if provider.sourceHasNoDataValue(b) \
                    and provider.useSourceNoDataValue(b):
                return True
            if provider.userNoDataValues(b):
                return True
    except Exception as err:
        log("cannot tell from its style whether %s is transparent: %s"
            % (layer.name(), err))
    for b in range(1, ds.RasterCount + 1):
        if ds.GetRasterBand(b).GetMaskFlags() != gdal.GMF_ALL_VALID:
            return True
    return False


def put_picture(ds, rgb, shown, row):
    """Write a strip of a picture at this row: the three bands, and the alpha
    in the fourth when the file has one. A file without one, a JPEG, gets what
    is see-through on white, as QGIS draws it on the canvas of a new project.
    shown is the alpha of each pixel, or None where all of it is opaque."""
    if ds.RasterCount >= 4:
        for i in range(3):
            ds.GetRasterBand(i + 1).WriteArray(rgb[i], 0, row)
        ds.GetRasterBand(4).WriteArray(
            shown if shown is not None
            else np.full(rgb.shape[1:], 255, np.uint8), 0, row)
        return
    if shown is not None:
        a = shown.astype(np.float32) / 255.0
        rgb = np.clip(np.rint(rgb.astype(np.float32) * a + 255.0 * (1 - a)),
                      0, 255).astype(np.uint8)
    for i in range(3):
        ds.GetRasterBand(i + 1).WriteArray(rgb[i], 0, row)


def scratch_of(path):
    """The scratch GeoTIFF a PNG or a JPEG is painted into, beside it."""
    return path + ".part.tif"


def drop_scratch(path):
    """Take away the scratch file of a PNG or a JPEG, if there is one."""
    part = scratch_of(path)
    if not os.path.exists(long_path(part)):
        return
    try:
        gdal.GetDriverByName("GTiff").Delete(part)
    except Exception:
        pass
    try:
        if os.path.exists(long_path(part)):
            os.remove(long_path(part))
    except OSError as err:
        log("%s could not be removed: %s" % (os.path.basename(part), err))


def open_for_write(driver, path, w, h, bands, gt, wkt, dtype=gdal.GDT_Byte,
                   alpha=False):
    """A dataset to write into, whatever the driver can and cannot do.

    PNG and JPEG cannot be created and then written band by band: their drivers
    only know how to copy a finished raster. So for those the work goes into a
    scratch GeoTIFF beside the file, tiled, and is copied out at the end.
    Doing it in memory would hold every picture whole, about seven bytes a
    pixel for the painted image, the plain one and the mask: eight gigabytes
    for a photograph of 40000 x 30000, the very thing the strips are there to
    avoid. The caller does not need to know which kind it got, only
    to call finish_write() when it is done and drop_scratch() once the dataset
    is closed. alpha makes the last band an alpha band."""
    keeps_gt = driver == "GTiff"
    options = ["TILED=YES", "BIGTIFF=IF_SAFER"]
    if alpha:
        options += ["PHOTOMETRIC=RGB", "ALPHA=YES"]
    if driver == "GTiff":
        ds = gdal.GetDriverByName("GTiff").Create(
            path, w, h, bands, dtype,
            ["COMPRESS=DEFLATE", "PREDICTOR=2"] + options)
    else:
        # fast to write and to read back: it lives only until the copy
        ds = gdal.GetDriverByName("GTiff").Create(
            scratch_of(path), w, h, bands, dtype,
            ["COMPRESS=DEFLATE", "ZLEVEL=1"] + options)
    if ds is None:
        raise IOError(
            "cannot create %s. The disk may be full, the folder read only, or "
            "the file already open.\n%s"
            % (os.path.basename(path), gdal.GetLastErrorMsg() or ""))
    if gt is not None:
        ds.SetGeoTransform(gt)
    if wkt and keeps_gt:
        ds.SetProjection(wkt)
    return ds


def finish_write(ds, driver, path):
    """Close a dataset opened by open_for_write, copying it out when the driver
    needed a copy. Raises if anything did not land."""
    if driver == "GTiff":
        ds.FlushCache()
        ds = None
    else:
        options = ["QUALITY=92"] if driver == "JPEG" else []
        out = gdal.GetDriverByName(driver).CreateCopy(path, ds, 0, options)
        ds = None
        if out is None:
            raise IOError("cannot write %s. %s"
                          % (os.path.basename(path), gdal.GetLastErrorMsg() or ""))
        out = None
    if not landed(path):
        raise IOError("%s was not written" % os.path.basename(path))


def pixel_holding(gt, x, y):
    """The column and the row of the pixel that holds a map point, on any
    geotransform, rotated or not."""
    if gt[2] == 0 and gt[4] == 0:
        return (int(math.floor((x - gt[0]) / gt[1])),
                int(math.floor((y - gt[3]) / gt[5])))
    det = gt[1] * gt[5] - gt[2] * gt[4]
    dx, dy = x - gt[0], y - gt[3]
    return (int(math.floor((gt[5] * dx - gt[2] * dy) / det)),
            int(math.floor((gt[1] * dy - gt[4] * dx) / det)))


class Stencil(object):
    """The annotation of a campaign, held once and burned window by window.

    A whole orthomosaic does not fit in memory, so it is written in strips, and
    every strip has to be given the annotation that falls inside it. Rebuilding
    the vector layer for each strip would read the package a dozen times; this
    keeps one memory layer and moves a spatial filter across it."""

    def __init__(self, package, table, field, wkt, transform=None,
                 size_field=None, grid=None, fallback=1, keep=None,
                 value=None, by_tile=None):
        """keep, when given, is the set of readings, (operator, pass), whose
        marks are held: the others are left out of every window.

        With no field, every feature burns value: the frames, to tell the
        ground inside them from the ground outside. by_tile, for the frames,
        burns {tile_id: code} instead: a frame is held once, under the
        first of its tile_id that has an area, as reading_shares counts it,
        and a frame that is not in the dict is left out. codes is every code
        the marks carry, and uncoded how many carry none (0 or empty)."""
        self.ok = False
        self.source = None
        self.layer = None
        self.pixels = None
        self.highest = 0
        self.lowest = 0
        self.codes = set()
        self.uncoded = 0
        self.count = 0
        self.kind = gdal.GDT_Byte
        data = ogr.Open(package)
        if data is None:
            return
        src = data.GetLayerByName(table)
        if src is None:
            data = None
            return
        srs = None
        if wkt:
            srs = osr.SpatialReference()
            try:
                srs.ImportFromWkt(wkt)
            except Exception:
                srs = None
        self.source = self.in_memory(table)
        self.layer = self.source.CreateLayer("g", srs, ogr.wkbUnknown)
        self.layer.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
        definition = self.layer.GetLayerDefn()
        held = src.GetLayerDefn()
        who = held.GetFieldIndex("operator")
        when = held.GetFieldIndex("pass_no")
        tile_at = held.GetFieldIndex("tile_id")
        seen = set()
        n = 0
        for f in src:
            g = f.GetGeometryRef()
            if g is None or g.IsEmpty():
                continue
            if by_tile is not None:
                tid = f.GetField(tile_at) if tile_at >= 0 else None
                tid = None if tid is None else str(tid)
                if tid not in by_tile or tid in seen or not g.GetArea() > 0:
                    continue
                seen.add(tid)
            if keep is not None and (
                    operator_word(f.GetField(who) if who >= 0 else None),
                    pass_number(f.GetField(when) if when >= 0 else None)) \
                    not in keep:
                continue
            g = g.Clone()
            if size_field is not None and grid is not None:
                # A square of whole pixels, built on the raster grid rather than
                # around the point. Centring a square of side n on the point
                # itself gives n pixels when the point sits at the middle of one
                # and n + 1 when it sits on a corner, so "9 x 9" would sometimes
                # be ten across. The pixel that holds the point is found first,
                # and the square is grown from that pixel outwards: it is n
                # across, always, wherever inside the pixel the click landed.
                try:
                    n = int(f.GetField(size_field) or 0)
                except Exception:
                    n = 0
                if n < 1:
                    n = fallback
                # grid is the whole geotransform. On a rotated raster a
                # pixel is not a box of gt[1] by gt[5] in map units, so
                # both the pixel that holds the point and the corners of
                # the square are found on the affine grid. North up, or
                # north down, it is the same arithmetic as ever.
                col, row = pixel_holding(grid, g.GetX(), g.GetY())
                half = n // 2
                ring = ogr.Geometry(ogr.wkbLinearRing)
                for c_, r_ in ((col - half, row - half),
                               (col + half + 1, row - half),
                               (col + half + 1, row + half + 1),
                               (col - half, row + half + 1),
                               (col - half, row - half)):
                    ring.AddPoint_2D(grid[0] + c_ * grid[1] + r_ * grid[2],
                                     grid[3] + c_ * grid[4] + r_ * grid[5])
                square = ogr.Geometry(ogr.wkbPolygon)
                square.AddGeometry(ring)
                g = square
            if transform is not None:
                g = transform(g)
                if g is None or g.IsEmpty():
                    continue
            out = ogr.Feature(definition)
            out.SetGeometry(g)
            if by_tile is not None:
                code = int(by_tile[tid])
            elif field is None:
                code = int(value or 0)
            else:
                try:
                    code = int(f.GetField(field) or 0)
                except Exception:
                    code = 0
            out.SetField("v", code)
            self.highest = max(self.highest, code)
            self.lowest = min(self.lowest, code)
            self.codes.add(code)
            if code <= 0:
                self.uncoded += 1
            self.layer.CreateFeature(out)
            out = None
            n += 1
        src = None
        data = None
        self.count = n
        self.ok = n > 0
        # burned in a type that holds every code it carries: a byte, unless
        # a code really is past one
        self.kind = mask_type(self.highest, self.lowest)

    @staticmethod
    def in_memory(name):
        """A vector datasource in memory. GDAL 3.11 took the old "Memory"
        driver into "MEM" and prints a deprecation warning at every use of
        the old name, which it will stop answering to; before 3.11 only
        "Memory" exists for vectors."""
        driver = None
        try:
            if int(gdal.VersionInfo("VERSION_NUM")) >= 3110000:
                driver = ogr.GetDriverByName("MEM")
        except (TypeError, ValueError):
            driver = None
        if driver is None:
            driver = ogr.GetDriverByName("Memory")
        return driver.CreateDataSource(name)

    def burn_into(self, gt, w, h, wkt, all_touched=False, whole=None,
                  col=0, row=0):
        """The class codes falling in this window, as an array of bytes, or of
        a wider type when a code does not fit in one.

        gt is the grid of the window. When the window is a piece of a bigger
        raster, `whole` is the grid of that raster and col, row the corner of
        the window in it: the window is then burned from the shapes in pixel
        coordinates of the whole raster, which a strip only shifts by whole
        rows. Shifting the grid instead moved the rounding with it, and a
        pixel whose centre lies exactly on the edge of a polygon was inside
        for one strip height and outside for another."""
        if not self.ok:
            return np.zeros((h, w), np.uint8)
        if whole is not None:
            burned = self.burn_in_pixels(whole, col, row, w, h, all_touched)
            if burned is not None:
                return burned
        # The window's four corners, not two: on a rotated raster the
        # bottom left corner lies h * gt[2] further along x and the top right
        # w * gt[4] further along y, and a filter built from the top left and
        # the bottom right left out whatever was drawn out there.
        corners = ((0, 0), (w, 0), (0, h), (w, h))
        xs = [gt[0] + c * gt[1] + r * gt[2] for c, r in corners]
        ys = [gt[3] + c * gt[4] + r * gt[5] for c, r in corners]
        self.layer.SetSpatialFilterRect(min(xs), min(ys), max(xs), max(ys))
        target = gdal.GetDriverByName("MEM").Create("", w, h, 1, self.kind)
        target.SetGeoTransform(gt)
        if wkt:
            target.SetProjection(wkt)
        target.GetRasterBand(1).Fill(0)
        gdal.RasterizeLayer(
            target, [1], self.layer,
            options=["ATTRIBUTE=v",
                     "ALL_TOUCHED=%s" % ("TRUE" if all_touched else "FALSE")])
        out = target.GetRasterBand(1).ReadAsArray()
        target = None
        self.layer.SetSpatialFilter(None)
        return out

    def in_pixels(self, whole):
        """The shapes as they lie on the pixels of the grid `whole`, made
        once per grid, or None when the grid cannot be turned round. The
        arithmetic is GDAL's own (the inverse of the geotransform, applied
        as GDAL applies it), so a window burned from these gives the pixels
        that one burn over the whole raster gives."""
        key = tuple(float(v) for v in whole)
        if self.pixels is not None and self.pixels[0] == key:
            return self.pixels[1]
        try:
            inv = gdal.InvGeoTransform(key)
        except RuntimeError:
            inv = None              # a grid with no inverse
        if inv and len(inv) == 2 and not hasattr(inv[0], "__len__"):
            inv = inv[1] if inv[0] else None
        if not inv:
            return None
        self.pixels = None
        mem = self.in_memory("pixels")
        layer = mem.CreateLayer("g", self.pixel_space(), ogr.wkbUnknown)
        layer.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
        definition = layer.GetLayerDefn()
        self.layer.ResetReading()
        for f in self.layer:
            g = f.GetGeometryRef()
            if g is None:
                continue
            g = g.Clone()
            self.move_to_pixels(g, inv)
            out = ogr.Feature(definition)
            out.SetGeometry(g)
            out.SetField("v", f.GetField("v"))
            layer.CreateFeature(out)
            out = None
        self.layer.ResetReading()
        self.pixels = (key, (mem, layer))
        return self.pixels[1]

    @staticmethod
    def pixel_space():
        """A local coordinate system for the pixel-space layer and for the
        raster it is burned into, the same one on both. With none on either,
        GDAL 3.8 (QGIS 3.36) warns at every burn that it assumes matching
        coordinate systems, once per strip."""
        srs = osr.SpatialReference()
        srs.SetLocalCS("pixels")
        return srs

    @staticmethod
    def move_to_pixels(geom, inv):
        """Every vertex of geom moved to pixel coordinates, in place."""
        parts = geom.GetGeometryCount()
        if parts:
            for i in range(parts):
                Stencil.move_to_pixels(geom.GetGeometryRef(i), inv)
            return
        for i in range(geom.GetPointCount()):
            x, y = geom.GetX(i), geom.GetY(i)
            geom.SetPoint_2D(i, inv[0] + x * inv[1] + y * inv[2],
                             inv[3] + x * inv[4] + y * inv[5])

    def burn_in_pixels(self, whole, col, row, w, h, all_touched):
        """burn_into for a window of a bigger raster, from the shapes in the
        pixel coordinates of that raster. None when there are none to use."""
        held = self.in_pixels(whole)
        if held is None:
            return None
        layer = held[1]
        layer.SetSpatialFilterRect(col - 1.0, row - 1.0,
                                   col + w + 1.0, row + h + 1.0)
        target = gdal.GetDriverByName("MEM").Create("", w, h, 1, self.kind)
        # the pixels of the whole raster are the units, and the window sits
        # at (col, row) in them: shifting by whole numbers is exact
        target.SetGeoTransform((float(col), 1.0, 0.0, float(row), 0.0, 1.0))
        target.SetProjection(self.pixel_space().ExportToWkt())
        target.GetRasterBand(1).Fill(0)
        gdal.RasterizeLayer(
            target, [1], layer,
            options=["ATTRIBUTE=v",
                     "ALL_TOUCHED=%s" % ("TRUE" if all_touched else "FALSE")])
        out = target.GetRasterBand(1).ReadAsArray()
        target = None
        layer.SetSpatialFilter(None)
        return out

    def close(self):
        self.layer = None
        self.source = None
        self.pixels = None


class ConsensusCover(object):
    """Which readings vote at each pixel of a consensus.

    The readings that covered the frame a pixel lies in, and outside every
    frame the readings that painted anywhere (campaign.consensus_voters says
    why). Built once, before the strips: the frames are burned with a code
    for the set of readings that covered each, and a strip then asks which
    readings vote at each of its pixels."""

    def __init__(self, package, wkt, readings, points_in=False, shares=None):
        self.readings = [tuple(r) for r in readings]
        self.info = consensus_voters(package, self.readings, points_in,
                                     shares)
        self.partial = bool(self.info["partial"])
        self.stencil = None
        self.table = None
        if not self.partial:
            return
        # code 0 is the ground outside every frame, one code to a distinct
        # set of readings after it
        sets = [self.info["outside"]]
        by_tile = {}
        for tid, who in sorted(self.info["frames"].items()):
            if who not in sets:
                sets.append(who)
            by_tile[tid] = sets.index(who)
        self.table = np.array([[r in who for who in sets]
                               for r in self.readings], dtype=bool)
        if by_tile:
            self.stencil = Stencil(package, "tiles", None, wkt,
                                   by_tile=by_tile)

    def voting(self, gt, w, h, wkt, **at):
        """Which readings vote at each pixel of a window, as an array of
        booleans (readings, rows, columns), or None where every reading
        votes everywhere. Burned the way the readings are: same window,
        same pixels."""
        if not self.partial:
            return None
        if self.stencil is not None:
            where = self.stencil.burn_into(gt, w, h, wkt, **at)
        else:
            where = np.zeros((h, w), np.uint8)
        return self.table[:, where]

    def how_many(self, member, shape):
        """How many readings vote at each pixel, for the array voting gave
        (None: all of them) and the shape of the window."""
        if member is None:
            return np.full(shape, len(self.readings), np.uint16)
        return member.sum(axis=0).astype(np.uint16)

    def said(self):
        """The frames by the number of readings that voted in them, as a
        sentence, or "" where every reading voted everywhere."""
        return frames_by_readings_text(self.info["by_readings"]) \
            if self.partial else ""

    def close(self):
        if self.stencil is not None:
            self.stencil.close()
            self.stencil = None


def shape_of(driver, role):
    """The driver, the extension and the media type for one layer's file.

    A layer of class codes is never handed to a lossy codec whatever the row
    says. The rest is a lookup, kept in one place so that the extension on
    disk and the type written into the catalogue can never disagree."""
    kinds = {"GTiff": GEOTIFF_TYPE, "PNG": "image/png", "JPEG": "image/jpeg"}
    for word, name, extension, exact, _ in WHOLE_FORMATS:
        if name == driver:
            if role == "classes" and not exact:
                return "GTiff", ".tif", GEOTIFF_TYPE
            return name, extension, kinds.get(name, "application/octet-stream")
    return "GTiff", ".tif", GEOTIFF_TYPE


def landed(path):
    """True when a file is on disk and is not empty, however long its path.

    Asked through long_path(), because GDAL writes past the 260 characters of
    Windows and Python's plain os.path calls do not see that far: a file that
    had landed whole was called missing, and the cutout it belonged to was
    abandoned with its files still on disk."""
    try:
        return os.path.getsize(long_path(path)) > 0
    except OSError:
        return False


def put_raster(driver, path, array, gt, wkt, dtype=gdal.GDT_Byte,
               nodata=None):
    """One raster, in whichever of the three shapes was asked for.

    GeoTIFF keeps its coordinates. PNG and JPEG do not: they are pictures, and
    the world file is not written either, on purpose. Somebody who picked JPEG
    asked for a picture, and a picture that pretends to be a map is worse than
    one that admits it is not. nodata is declared in a GeoTIFF only."""
    if driver == "GTiff":
        write_tif(path, array, gt, wkt, nodata=nodata, dtype=dtype)
        return
    if array.shape[0] == 1:
        array = np.repeat(array, 3, axis=0) if driver == "JPEG" else array
    mem = gdal.GetDriverByName("MEM").Create(
        "", array.shape[2], array.shape[1], array.shape[0], dtype)
    if mem is None:
        raise IOError("cannot build %s in memory" % os.path.basename(path))
    for i in range(array.shape[0]):
        mem.GetRasterBand(i + 1).WriteArray(array[i])
    options = ["QUALITY=92"] if driver == "JPEG" else []
    out = gdal.GetDriverByName(driver).CreateCopy(path, mem, 0, options)
    mem = None
    if out is None:
        raise IOError("cannot write %s. %s"
                      % (os.path.basename(path), gdal.GetLastErrorMsg() or ""))
    out = None
    if not landed(path):
        raise IOError("%s was not written" % os.path.basename(path))


def write_tif(path, array, gt, wkt, nodata=None, dtype=gdal.GDT_Byte,
              colours=None, names=None, mask=None):
    """One GeoTIFF, and an exception the moment it is not one.

    gdal answers a refused Create with None, not with an error: a full disk, or
    a file QGIS is holding open, would come back as an AttributeError three
    lines later, from the middle of a loop that was writing a batch of cutouts.
    The file left behind would be truncated and be appended to the manifest and
    to the STAC catalogue as though it were finished, which is the worst kind
    of failure there is: one that leaves a plausible artefact behind.

    So every step is checked, and the half written file is taken away, so the
    caller can only ever find a whole file or nothing.

    nodata is one value for every band or a list with one per band, None
    where a band has none. colours, when given, is the colour interpretation
    of each band (Red, Green, Blue for the first three of an image), and names
    the description of each; without them every band is Undefined and
    unnamed, as before.

    mask, when given, is one byte per pixel, 0 where the file holds no data
    and 255 where it does, written as the mask of the whole dataset inside
    the file: the padding of a cutout past the edge of an image that has no
    nodata, which would otherwise be black pixels like any other."""
    driver = gdal.GetDriverByName("GTiff")
    try:
        ds = driver.Create(path, array.shape[2], array.shape[1], array.shape[0],
                           dtype, ["COMPRESS=DEFLATE", "PREDICTOR=2",
                                   "TILED=YES"])
    except Exception as err:
        raise IOError("cannot create %s: %s" % (os.path.basename(path), err))
    if ds is None:
        raise IOError(
            "cannot create %s. The disk may be full, the folder read only, or "
            "the file already open in QGIS.\n%s"
            % (os.path.basename(path), gdal.GetLastErrorMsg() or ""))
    try:
        ds.SetGeoTransform(gt)
        if wkt:
            ds.SetProjection(wkt)
        for i in range(array.shape[0]):
            band = ds.GetRasterBand(i + 1)
            if band is None:
                raise IOError("band %d of %s could not be opened"
                              % (i + 1, os.path.basename(path)))
            if band.WriteArray(array[i]) not in (0, None):
                raise IOError("band %d of %s could not be written"
                              % (i + 1, os.path.basename(path)))
            band.SetColorInterpretation(
                colours[i] if colours and i < len(colours)
                else gdal.GCI_Undefined)
            nd = nodata[i] if isinstance(nodata, (list, tuple)) else nodata
            if nd is not None:
                band.SetNoDataValue(nd)
            if names and i < len(names) and names[i]:
                band.SetDescription(str(names[i]))
        if mask is not None:
            # Inside the file, whatever this GDAL does by default: a .msk
            # beside it would be a file no book of the cutout lists.
            was = gdal.GetConfigOption("GDAL_TIFF_INTERNAL_MASK")
            gdal.SetConfigOption("GDAL_TIFF_INTERNAL_MASK", "YES")
            try:
                made = ds.CreateMaskBand(gdal.GMF_PER_DATASET)
            finally:
                gdal.SetConfigOption("GDAL_TIFF_INTERNAL_MASK", was)
            if made not in (0, None):
                raise IOError("the mask of %s could not be made"
                              % os.path.basename(path))
            wrote = ds.GetRasterBand(1).GetMaskBand().WriteArray(mask)
            if wrote not in (0, None):
                raise IOError("the mask of %s could not be written"
                              % os.path.basename(path))
        ds.FlushCache()
    except Exception:
        ds = None
        # a truncated file that nobody can tell from a whole one is worse than
        # no file: it would be listed in the manifest and read months later
        try:
            os.remove(long_path(path))
        except OSError:
            pass
        raise
    ds = None
    if not landed(path):
        raise IOError("%s was not written" % os.path.basename(path))


def write_png(path, rgb, alpha):
    """A picture for a figure: no coordinates, transparent outside the cutout."""
    mem = gdal.GetDriverByName("MEM").Create("", rgb.shape[2], rgb.shape[1],
                                             4, gdal.GDT_Byte)
    for i in range(3):
        mem.GetRasterBand(i + 1).WriteArray(rgb[i])
    mem.GetRasterBand(4).WriteArray(alpha)
    out = gdal.GetDriverByName("PNG").CreateCopy(path, mem, 0)
    mem = None
    if out is None:
        raise IOError("cannot write %s. %s"
                      % (os.path.basename(path), gdal.GetLastErrorMsg() or ""))
    out = None


def colour_table(array, classes):
    """Paint class codes with the campaign colours. Code 0 stays transparent."""
    out = np.zeros((3,) + array.shape, np.uint8)
    for c in classes:
        hit = array == c["code"]
        if hit.any():
            col = QColor(c["colour"])
            for i, v in enumerate((col.red(), col.green(), col.blue())):
                out[i][hit] = v
    return out


def display_limits(layer, bands):
    """The stretch the layer already shows on screen, so two surveys stretched
    differently in the project stay comparable once cut."""
    renderer = layer.renderer()
    if not isinstance(renderer, QgsMultiBandColorRenderer):
        return None
    getters = {renderer.redBand(): renderer.redContrastEnhancement,
               renderer.greenBand(): renderer.greenContrastEnhancement,
               renderer.blueBand(): renderer.blueContrastEnhancement}
    out = []
    for b in bands:
        get = getters.get(b)
        if get is None:
            return None
        enhancement = get()
        if enhancement is None:
            return None
        # With no enhancement QGIS draws the values as they are, whatever
        # limits the band keeps: applying those anyway turned a blue of 30 on
        # the screen into 0 in the file.
        kinds = getattr(type(enhancement), "ContrastEnhancementAlgorithm",
                        None)
        if kinds is not None and enhancement.contrastEnhancementAlgorithm() \
                == kinds.NoEnhancement:
            out.append((0.0, 255.0))
            continue
        out.append((float(enhancement.minimumValue()),
                    float(enhancement.maximumValue())))
    return out


def renderer_bands(layer):
    r = layer.renderer()
    if isinstance(r, QgsMultiBandColorRenderer):
        return [r.redBand() or 1, r.greenBand() or 2, r.blueBand() or 3]
    n = layer.dataProvider().bandCount()
    return [1, min(2, n), min(3, n)]


def class_band_of(layer):
    """The band of a layer that holds its classes, as a guess for the user to
    confirm: the band its style draws in classes, when it is styled that
    way, then the first band whose name says "class", then the first that
    carries an attribute table, a colour table or category names, then
    band 1.

    The style first because it is the one thing the user has already said:
    a map of probability, class and entropy whose .qml draws band 2 in
    classes was offered band 1, the probability, when its bands had no
    names. Only a style that names classes (style_classes) counts: a
    pseudocolor stretch over the probability says nothing about where the
    classes are, and a band named "class" was then passed over for it."""
    provider = layer.dataProvider()
    try:
        renderer = layer.renderer()
        kind = renderer.type() if renderer is not None else ""
        if kind in ("paletted", "singlebandpseudocolor"):
            band = int((getattr(renderer, "inputBand", None)
                        or renderer.band)())
            if 1 <= band <= provider.bandCount() \
                    and style_classes(layer, band):
                return band
    except Exception:
        pass
    for b in range(1, provider.bandCount() + 1):
        if "class" in provider.generateBandName(b).lower():
            return b
    # A band that carries its classes in the file: an attribute table, a
    # colour table or category names, which no other band of a stack has.
    # Looked for in a file on disk only: a layer read from a server is not
    # opened again for a guess.
    try:
        path = str(layer.source()).split("|")[0]
    except Exception:
        return 1
    if not os.path.isfile(long_path(path)):
        return 1
    ds = None
    pushed = _quiet_gdal()
    try:
        ds = pam_ready(gdal.Open(path))
        for b in range(1, (ds.RasterCount if ds is not None else 0) + 1):
            band = ds.GetRasterBand(b)
            get = getattr(band, "GetDefaultRAT", None)
            rat = get() if get is not None else None
            if (rat is not None and rat.GetRowCount()) \
                    or band.GetColorTable() is not None \
                    or band.GetCategoryNames():
                return b
    except Exception:
        pass
    finally:
        ds = None
        _loud_gdal(pushed)
    return 1


def values_in(path, band_no, sample=512):
    """The distinct values in a band, read small.

    A class map holds a handful of numbers; a photograph holds thousands.
    Reading a reduced version answers the question in a moment however large
    the file is."""
    try:
        ds = gdal.Open(path)
        if ds is None:
            return None
        band = ds.GetRasterBand(band_no)
        wide = min(sample, ds.RasterXSize)
        tall = min(sample, ds.RasterYSize)
        array = band.ReadAsArray(0, 0, ds.RasterXSize, ds.RasterYSize,
                                 buf_xsize=wide, buf_ysize=tall)
        ds = None
        if array is None:
            return None
        array = array[np.isfinite(array)]
        return set(np.unique(array).astype(np.int64).tolist()[:4096])
    except Exception as err:
        log("cannot read the values of %s: %s" % (os.path.basename(path), err))
        return None


def lossy_codec(path):
    """The name of the compression the raster at path is stored with when it
    does not give every value back as it was written: "JPEG", "WebP",
    "JPEG 2000", or None when nothing is lost or nothing can be said.

    A class map saved that way holds, along the edges of its classes, values
    that are no class at all, smeared there by the compression. GDAL says it
    in COMPRESSION_REVERSIBILITY, LOSSY or LOSSLESS, for WebP and JPEG 2000,
    which can be either: a WebP or a JPEG 2000 written without loss is as
    exact as a GeoTIFF and is not named. A JPEG, a .jpg or a GeoTIFF
    compressed with it, is always lossy and has no such item; so is a
    GeoTIFF compressed with LERC when an error is allowed (MAX_Z_ERROR)."""
    pushed = _quiet_gdal()
    ds = None
    try:
        ds = gdal.Open(str(path).split("|")[0])
        if ds is None:
            return None
        driver = str(ds.GetDriver().ShortName or "").upper()
        ims = ds.GetMetadata("IMAGE_STRUCTURE") or {}
    except Exception:
        return None
    finally:
        ds = None
        _loud_gdal(pushed)
    compression = str(ims.get("COMPRESSION") or "").upper()
    kept = str(ims.get("COMPRESSION_REVERSIBILITY") or "").upper()
    if kept == "LOSSLESS":
        return None
    if compression.startswith("LERC") and not kept:
        try:
            allowed = float(ims.get("MAX_Z_ERROR") or 0)
        except (TypeError, ValueError):
            allowed = 0.0
        return "LERC" if allowed > 0 else None
    if kept != "LOSSY" and driver != "JPEG" and compression != "JPEG":
        return None
    if driver.startswith("JP2") or "JPEG2000" in compression \
            or "JP2" in compression:
        return "JPEG 2000"
    if driver == "WEBP" or compression == "WEBP":
        return "WebP"
    if driver == "JPEG" or compression == "JPEG":
        return "JPEG"
    return compression or driver or "a lossy compression"



#  The classes of a thematic map
# =====================================================================
#  A correction mends the map an algorithm produced, and that map has its own
#  numbering: twelve land covers, a mask of three, whatever the model was
#  trained on. The campaign legend is the numbering of what people draw in
#  Annotate and Objects, and the two have no reason to agree. So a correction
#  takes its classes from the map itself: from the way it is styled in QGIS
#  when the style names them, and from the values the band really holds when
#  it does not.
def thematic_colour(i):
    """A default colour for the i-th class of a map that brought none.

    The palette of the legend first, because it was chosen to be told apart;
    past its end, hues spread by the golden angle, which never land twice on
    the same one, at two brightnesses so neighbours differ in more than hue."""
    if 0 <= i < len(PALETTE):
        return PALETTE[i]
    hue = (i * 137.508) % 360.0
    return QColor.fromHsv(int(hue), 170, 200 if i % 2 else 150).name()


class BandPlane(object):
    """One band of a raster file, read a window at a time and never held.

    Holding the whole class band, and the whole record of changes beside it,
    in memory, and counting the codes of the first by turning all of it into
    64 bit integers, would ask of a map of 400 million pixels several
    gigabytes more than its own size, and QGIS on a laptop would close. This
    answers the few things Correct asks of those arrays, a pixel, the window
    under a stroke, the strips of a count, from the file.

    Every stroke is written into the file as it is made (write_window), so
    the file is the truth and nothing held here can fall behind it. Anything
    that is not a window, an array operation on the whole band, still works:
    it reads the band whole, once, which is what it always did, and is the
    reason to ask for windows and strips instead."""
    ndim = 2

    def __init__(self, path, band_no=1):
        self.path = path
        self.band_no = int(band_no)
        ds = open_raster(path)
        if ds is None:
            raise IOError("cannot read %s" % path)
        band = None
        try:
            self.nx, self.ny = ds.RasterXSize, ds.RasterYSize
            band = ds.GetRasterBand(self.band_no)
            self.nodata = band.GetNoDataValue()
            # the type numpy reads it as, from one pixel of it
            self.dtype = band.ReadAsArray(0, 0, 1, 1).dtype
        finally:
            band = None
            ds = None

    @property
    def shape(self):
        return (self.ny, self.nx)

    @property
    def size(self):
        return self.ny * self.nx

    def __len__(self):
        return self.ny

    def window(self, col, row, w, h):
        """The pixels of w x h from col, row, a copy of what the file holds
        now."""
        ds = open_raster(self.path)
        if ds is None:
            raise IOError("cannot read %s" % self.path)
        try:
            out = ds.GetRasterBand(self.band_no).ReadAsArray(
                int(col), int(row), int(w), int(h))
        finally:
            ds = None
        if out is None:
            raise IOError("cannot read %s" % self.path)
        return out

    def strips(self, pixels=STRIP_PX):
        """(first row, rows) down the band, each strip about pixels large,
        read through one handle held while the strips are taken."""
        take = max(1, int(pixels) // max(1, self.nx))
        ds = open_raster(self.path)
        if ds is None:
            raise IOError("cannot read %s" % self.path)
        band = None
        try:
            band = ds.GetRasterBand(self.band_no)
            for row in range(0, self.ny, take):
                yield row, band.ReadAsArray(0, row, self.nx,
                                            min(take, self.ny - row))
        finally:
            band = None
            ds = None

    @staticmethod
    def _span(index, n):
        """(first, how many, step, whether it was a single number) of an
        index along an axis of n pixels."""
        if isinstance(index, slice):
            first, stop, step = index.indices(n)
            if step < 0:
                raise IndexError("a band is read forwards")
            return first, max(0, stop - first), step, False
        i = int(index)
        if i < 0:
            i += n
        if not 0 <= i < n:
            raise IndexError("index %d is out of range for %d pixels"
                             % (int(index), n))
        return i, 1, 1, True

    def __getitem__(self, key):
        """band[row, col] is one pixel, band[a:b, c:d] a window, band[a:b]
        some rows: whole numbers, and slices that go forwards."""
        if not isinstance(key, tuple):
            key = (key,)
        if len(key) > 2 or any(k is Ellipsis for k in key):
            raise IndexError("a band is indexed by row and column")
        rows = key[0] if key else slice(None)
        cols = key[1] if len(key) > 1 else slice(None)
        row, h, row_step, one_row = self._span(rows, self.ny)
        col, w, col_step, one_col = self._span(cols, self.nx)
        if h == 0 or w == 0:
            dims = [len(range(0, n, step)) for n, step, one in
                    ((h, row_step, one_row), (w, col_step, one_col))
                    if not one]
            return np.zeros(dims or [0], self.dtype)
        got = self.window(col, row, w, h)[::row_step, ::col_step]
        if one_row and one_col:
            return got[0, 0]
        if one_row:
            return got[0]
        if one_col:
            return got[:, 0]
        return got

    def __array__(self, dtype=None, copy=None):
        got = self.window(0, 0, self.nx, self.ny)
        return got if dtype is None else got.astype(dtype)

    def copy(self):
        return self.window(0, 0, self.nx, self.ny)

    # A comparison of the whole band is an array, as it is for one in
    # memory; without these Python would answer False and an array
    # operation on the result would go on with that.
    def __eq__(self, other):
        return np.asarray(self) == other

    def __ne__(self, other):
        return np.asarray(self) != other

    __hash__ = None


def band_strips(values, pixels=STRIP_PX):
    """The pieces of a band, or of any array, about pixels large: a band read
    from its file hands its own strips over; an array in memory is cut into
    runs of rows, or of its flat pixels when it is not two dimensional."""
    if hasattr(values, "strips"):
        for _, strip in values.strips(pixels):
            yield strip
        return
    a = np.asarray(values)
    if a.ndim == 2 and a.shape[1]:
        take = max(1, int(pixels) // a.shape[1])
        for row in range(0, a.shape[0], take):
            yield a[row:row + take]
        return
    flat = a.reshape(-1)
    for first in range(0, flat.size, max(1, int(pixels))):
        yield flat[first:first + int(pixels)]


def _value_counts(values):
    """(the distinct values, how many pixels hold each) of a band or an
    array, NaN and infinity left out, taken a strip at a time: the most that
    is held besides the strip is the list of distinct values.

    A byte or a short is counted with bincount, the fast way through a large
    raster, and anything wider with unique."""
    seen = np.zeros(0)
    counts = np.zeros(0, dtype=np.int64)
    for a in band_strips(values):
        a = np.asarray(a).ravel()
        if a.dtype.kind == "f":
            a = a[np.isfinite(a)]
        if not a.size:
            continue
        if a.dtype.kind in "ui" and a.dtype.itemsize <= 2:
            # the code itself is the place in the count, for a byte or a
            # short; a signed one is moved up by half its range so that it
            # is one too, without a wider copy of the strip
            bits = 8 * a.dtype.itemsize
            if a.dtype.kind == "i":
                unsigned = np.dtype("u%d" % a.dtype.itemsize)
                as_place = a.view(unsigned) + unsigned.type(1 << (bits - 1))
                shift = -(1 << (bits - 1))
            else:
                as_place, shift = a, 0
            by_code = np.bincount(as_place)
            found = np.nonzero(by_code)[0]
            part, n = found + shift, by_code[found]
        else:
            part, n = np.unique(a, return_counts=True)
        if not seen.size:
            seen, counts = part, n.astype(np.int64)
            continue
        both = np.concatenate([seen, part])
        seen, back = np.unique(both, return_inverse=True)
        counts = np.bincount(back.reshape(-1),
                             weights=np.concatenate([counts, n])
                             ).astype(np.int64)
    return seen, counts


def codes_present(values, nodata=None):
    """The distinct values of a class band, nodata left out.

    Whatever its type: a class map in sixteen bits, or in floats holding whole
    numbers, is still a class map, so nothing here assumes one byte and codes
    up to 255. Counted a strip at a time (_value_counts), so a map of
    hundreds of millions of pixels is read without being held, from the file
    if it is given as a BandPlane."""
    if values is None:
        return []
    found, _ = _value_counts(values)
    out = []
    for v in found.tolist():
        if nodata is not None and v == nodata:
            continue
        if float(v) != int(v):
            continue                    # not a code: a class map holds whole numbers
        out.append(int(v))
    return sorted(set(out))


def class_counts(values, nodata=None):
    """How many pixels hold each code, nodata left out, as {code: count}.

    For the window that shows the classes before the copy is made: a class
    with no pixels at all is one the style names and the map does not hold,
    and the user should see that before deciding it is right. Counted a
    strip at a time, as codes_present is."""
    if values is None:
        return {}
    found, counts = _value_counts(values)
    out = {}
    for v, n in zip(found.tolist(), counts.tolist()):
        if nodata is not None and v == nodata:
            continue
        if float(v) != int(v):
            continue
        out[int(v)] = out.get(int(v), 0) + int(n)
    return out


def style_classes(layer, band_no):
    """The classes the layer's own style declares, or None.

    Two styles name classes: Paletted/Unique values, which is the one QGIS
    gives a band with a colour table, and Singleband pseudocolor when its
    ramp is Exact or Discrete with whole-number entries. An interpolated
    ramp is a stretch, not a legend, and says nothing about classes."""
    if layer is None:
        return None
    try:
        renderer = layer.renderer()
        kind = renderer.type() if renderer is not None else ""
    except Exception:
        return None
    found = []
    try:
        if kind not in ("paletted", "singlebandpseudocolor"):
            return None
        band = getattr(renderer, "inputBand", None) or renderer.band
        if band() != band_no:
            return None
        if kind == "paletted":
            for c in renderer.classes():
                found.append((c.value, c.color, c.label))
        else:
            ramp = renderer.shader().rasterShaderFunction()
            # Exact is 2 and Discrete is 1 in every QGIS 3; asked by name
            # first so that a renumbering cannot slip through.
            exact = getattr(type(ramp), "Exact", 2)
            discrete = getattr(type(ramp), "Discrete", 1)
            if ramp.colorRampType() not in (exact, discrete):
                return None
            for item in ramp.colorRampItemList():
                found.append((item.value, item.color, item.label))
    except Exception as err:
        log("cannot read the classes of the style of '%s': %s"
            % (layer.name(), err))
        return None
    out = []
    for value, colour, label in found:
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(v) or v != int(v):
            continue
        out.append({"code": int(v), "colour": QColor(colour).name(),
                    "name": (label or "").strip()})
    return out or None


#  The attribute table of a class band
# ---------------------------------------------------------------------
#  A classifier, ArcGIS above all, names its classes in a table beside the
#  pixels rather than in a style: a Raster Attribute Table, one row per
#  class, with its value, its pixel count, its name and often its colour.
#  GDAL keeps it in the .aux.xml or inside the file; ArcGIS writes it as
#  <map>.tif.vat.dbf, which the GDAL of QGIS 3.36 does not read and that of
#  QGIS 3.44 and 4 reads with its colour columns unmarked. So the table is
#  read here from either, its columns told apart by what GDAL says they are
#  and, where it says nothing, by the names classifiers give them.
VAT_SUFFIX = ".vat.dbf"
RAT_VALUE_NAMES = ("value", "classvalue", "class_value", "code", "pixelvalue",
                   "pixel_value", "val")
RAT_NAME_NAMES = ("class_name", "classname", "class_names", "name", "label",
                  "class", "category", "description", "landcover", "type")
RAT_COUNT_NAMES = ("count", "histogram", "pixelcount", "pixel_count",
                   "npixels")
RAT_COLOUR_NAMES = {"red": ("red", "r"), "green": ("green", "g"),
                    "blue": ("blue", "b"), "alpha": ("alpha", "opacity")}


def vat_of(path):
    """The ArcGIS value attribute table of a raster: <map>.tif.vat.dbf."""
    return str(path).split("|")[0] + VAT_SUFFIX


def _gdal_const(name, fallback):
    return getattr(gdal, name, fallback)


def pam_ready(ds):
    """The .aux.xml of a GeoTIFF read in before a band's names, colour table
    or attribute table are asked for or set. GDAL reads it the first time
    the grid or the coordinate system is asked for, and not before: until
    then the category names of any band but the first read as none, and
    names set on it were lost when the file closed. Returns ds."""
    try:
        if ds is not None:
            ds.GetGeoTransform()
    except Exception:
        pass
    return ds


def table_of_rat(rat):
    """A GDAL Raster Attribute Table as a plain table: its columns (name,
    kind, GDAL type and usage) and its rows, every value as GDAL hands it.

    None for a table of ranges, a row for each interval of values (columns
    of minimum and maximum, or rows binned from a value other than 0 by a
    step other than 1): that is the legend of a continuous band, not a list
    of classes, and is neither read as one nor rewritten."""
    if rat is None:
        return None
    ranges = (_gdal_const("GFU_Min", 3), _gdal_const("GFU_Max", 4))
    if any(rat.GetUsageOfCol(i) in ranges
           for i in range(rat.GetColumnCount())):
        return None
    try:
        binned = rat.GetLinearBinning()
        if isinstance(binned, (list, tuple)) and len(binned) == 3 \
                and binned[0] and (binned[1] != 0 or binned[2] != 1):
            return None
    except Exception:
        pass
    integer = _gdal_const("GFT_Integer", 0)
    real = _gdal_const("GFT_Real", 1)
    columns = []
    for i in range(rat.GetColumnCount()):
        gft = rat.GetTypeOfCol(i)
        columns.append({"name": rat.GetNameOfCol(i) or "",
                        "kind": ("int" if gft == integer else "real"
                                 if gft == real else "text"),
                        "gft": gft, "usage": rat.GetUsageOfCol(i)})
    rows = []
    for r in range(rat.GetRowCount()):
        row = []
        for i, c in enumerate(columns):
            if c["kind"] == "int":
                row.append(rat.GetValueAsInt(r, i))
            elif c["kind"] == "real":
                row.append(rat.GetValueAsDouble(r, i))
            else:
                row.append(rat.GetValueAsString(r, i))
        rows.append(row)
    try:
        kind = rat.GetTableType()
    except Exception:
        kind = None
    return {"columns": columns, "rows": rows, "table_type": kind,
            "from": "rat"}


def table_of_vat(path):
    """<map>.tif.vat.dbf as a plain table, the width of every field kept so
    the copy's own can be written alike. None when there is none."""
    dbf = vat_of(path)
    if not os.path.exists(long_path(dbf)):
        return None
    pushed = _quiet_gdal()
    ds = None
    try:
        ds = ogr.Open(dbf)
        if ds is None:
            return None
        layer = ds.GetLayer(0)
        defn = layer.GetLayerDefn()
        columns = []
        for i in range(defn.GetFieldCount()):
            f = defn.GetFieldDefn(i)
            kind = f.GetType()
            columns.append({"name": f.GetName(),
                            "kind": ("int" if kind in (ogr.OFTInteger,
                                                       ogr.OFTInteger64)
                                     else "real" if kind == ogr.OFTReal
                                     else "text"),
                            "ogr": kind, "width": f.GetWidth(),
                            "precision": f.GetPrecision(), "usage": 0})
        rows = []
        for feature in layer:
            row = []
            for i, c in enumerate(columns):
                if not feature.IsFieldSet(i):
                    row.append(0 if c["kind"] != "text" else "")
                elif c["kind"] == "int":
                    row.append(feature.GetFieldAsInteger64(i))
                elif c["kind"] == "real":
                    row.append(feature.GetFieldAsDouble(i))
                else:
                    row.append(feature.GetFieldAsString(i))
            rows.append(row)
        return {"columns": columns, "rows": rows, "table_type": None,
                "from": "vat"}
    except Exception as err:
        log("cannot read %s: %s" % (os.path.basename(dbf), err))
        return None
    finally:
        ds = None
        _loud_gdal(pushed)


def attribute_table(path, band_no=1, ds=None):
    """The attribute table of a class band, as table_of_rat gives it: the
    one GDAL reads, or the .vat.dbf beside the file when GDAL reads none.
    None when the band has neither."""
    table = None
    pushed = _quiet_gdal()
    try:
        probe = pam_ready(ds if ds is not None
                          else gdal.Open(str(path).split("|")[0]))
        if probe is not None and 1 <= int(band_no) <= probe.RasterCount:
            band = probe.GetRasterBand(int(band_no))
            get = getattr(band, "GetDefaultRAT", None)
            rat = get() if get is not None else None
            if rat is not None and rat.GetRowCount() and rat.GetColumnCount():
                table = table_of_rat(rat)
            rat = None
            band = None
    except Exception:
        table = None
    finally:
        probe = None
        _loud_gdal(pushed)
    if table is None and int(band_no) == 1:
        table = table_of_vat(path)
    return table


def table_roles(table):
    """Which column of an attribute table holds what: {"value", "name",
    "count", "red", "green", "blue", "alpha"} to the index of the column, or
    None, and "scale", 1.0 when the colours are written from 0 to 1 and
    255.0 when from 0 to 255. "by_name" is True when the colours were found
    by the names of their columns only, which is how QGIS misses them."""
    columns = table["columns"]
    usage = {"value": (_gdal_const("GFU_MinMax", 5),),
             "name": (_gdal_const("GFU_Name", 2),),
             "count": (_gdal_const("GFU_PixelCount", 1),),
             "red": (_gdal_const("GFU_Red", 6),),
             "green": (_gdal_const("GFU_Green", 7),),
             "blue": (_gdal_const("GFU_Blue", 8),),
             "alpha": (_gdal_const("GFU_Alpha", 9),)}
    named = {"value": RAT_VALUE_NAMES, "name": RAT_NAME_NAMES,
             "count": RAT_COUNT_NAMES}
    named.update(RAT_COLOUR_NAMES)
    generic = _gdal_const("GFU_Generic", 0)
    roles = {}
    by_name = False
    for role in ("value", "name", "count", "red", "green", "blue", "alpha"):
        found = None
        for i, c in enumerate(columns):
            if c.get("usage") in usage[role]:
                found = i
                break
        if found is None:
            for want in named[role]:
                for i, c in enumerate(columns):
                    if i in roles.values():
                        continue
                    if c.get("usage", 0) != generic:
                        continue
                    if c["name"].strip().lower() != want:
                        continue
                    if (role == "name") != (c["kind"] == "text"):
                        continue
                    found = i
                    break
                if found is not None:
                    break
            if found is not None and role in ("red", "green", "blue"):
                by_name = True
        roles[role] = found
    if roles["red"] is None or roles["green"] is None or roles["blue"] is None:
        roles["red"] = roles["green"] = roles["blue"] = roles["alpha"] = None
        by_name = False
    scale = 255.0
    if roles["red"] is not None:
        top = 0.0
        for row in table["rows"]:
            for role in ("red", "green", "blue"):
                try:
                    top = max(top, float(row[roles[role]]))
                except (TypeError, ValueError):
                    pass
        if all(columns[roles[r]]["kind"] == "real"
               for r in ("red", "green", "blue")) and top <= 1.0:
            scale = 1.0
    roles["scale"] = scale
    roles["by_name"] = by_name
    return roles


def classes_of_table(table):
    """{code: {"name", "colour"}} from an attribute table: the name of each
    class and its colour as #rrggbb, or None when the table gives none. A
    table with no column of values numbers its rows from 0, the way GDAL
    and Erdas write one, and each row is the class of its number."""
    if not table or not table.get("rows"):
        return {}
    roles = table_roles(table)
    out = {}
    for i, row in enumerate(table["rows"]):
        if roles["value"] is None:
            code = i
        else:
            try:
                v = float(row[roles["value"]])
            except (TypeError, ValueError):
                continue
            if not math.isfinite(v) or v != int(v):
                continue
            code = int(v)
        name = ""
        if roles["name"] is not None:
            name = str(row[roles["name"]] or "").strip()
        colour = None
        if roles["red"] is not None:
            try:
                rgb = [float(row[roles[k]]) * (255.0 / roles["scale"])
                       for k in ("red", "green", "blue")]
                alpha = 255.0
                if roles["alpha"] is not None:
                    alpha = float(row[roles["alpha"]]) * (255.0 / roles["scale"])
                if alpha > 0:
                    colour = QColor(*[max(0, min(255, int(round(x))))
                                      for x in rgb]).name()
            except (TypeError, ValueError):
                colour = None
        if roles["value"] is None and not name and colour is None:
            continue
        out[code] = {"name": name, "colour": colour}
    return out


def thematic_classes(values, nodata=None, layer=None, band_no=1, path=None,
                     notes=None):
    """The classes of a correction: its own, never the campaign legend.

    The style of the layer first, so that the chips carry the names and
    colours the map is already looked at with. Then every value the band holds
    that the style did not name, so that nothing in the map is without a chip.
    A map with no style that names classes falls back to its attribute table
    (attribute_table), then to its GDAL colour table and category names when
    it has them, and to "class 7" in a palette colour when it has none of
    them. Zero is a class like any other, unless it is the nodata value.

    A style entry labelled with its own number is a class with no name:
    that is the label QGIS gives every entry of a colour table, and the
    attribute table or the category names of the file name it better."""
    notes = notes if notes is not None else []
    present = codes_present(values, nodata)
    styled = style_classes(layer, band_no) or []
    table, names, told, roles = None, [], {}, {}
    if path:
        try:
            ds = pam_ready(gdal.Open(path))
            band = ds.GetRasterBand(band_no) if ds is not None else None
            if band is not None:
                # A copy: the table belongs to the band, and once the file
                # is closed the band's own is gone and every entry read from
                # it fails, or reads freed memory.
                table = band.GetColorTable()
                table = table.Clone() if table is not None else None
                names = list(band.GetCategoryNames() or [])
            band = None
            ds = None
        except Exception:
            table, names = None, []
        rat = attribute_table(path, band_no)
        if rat is not None:
            told = classes_of_table(rat)
            roles = table_roles(rat)
            # Counted by name: an ArcGIS table of Value and Count alone has
            # a row for every class and names none of them.
            named = sum(1 for t in told.values() if t.get("name"))
            if named:
                notes.append("the attribute table of %s names %d class%s"
                             % (os.path.basename(str(path).split("|")[0]),
                                named, "" if named == 1 else "es"))

    def file_name(code):
        """The name the file itself gives a code, or "": its attribute table
        first, then its category names."""
        name = (told.get(code) or {}).get("name") or ""
        if not name and 0 <= code < len(names):
            name = (names[code] or "").strip()
        return name

    # A style can list far more than the map's classes. QGIS gives a band
    # with a colour table a Paletted style with one entry per entry of the
    # table, 256 for a byte band, most of them black and labelled with their
    # own number. A class the map does not hold is kept only when someone
    # gave it a name: that is a class the model may have missed, while "37"
    # in black is only the end of a table.
    held = set(present)
    out, seen, dropped = [], set(), 0
    for c in styled:
        if c["code"] in seen or (nodata is not None and c["code"] == nodata):
            continue
        if c["name"] in ("", str(c["code"])):
            c["name"] = file_name(c["code"])
        if c["code"] not in held and not c["name"]:
            dropped += 1
            continue
        # QGIS 3.44 and 4 read a .vat.dbf with its colour columns unmarked
        # and draw its classes in random colours under the right names. The
        # colours the table gives are the map's own.
        mine = told.get(c["code"]) or {}
        if roles.get("by_name") and mine.get("colour") \
                and mine.get("name") == c["name"]:
            c["colour"] = mine["colour"]
        seen.add(c["code"])
        c["origin"] = "style"
        out.append(c)
    if dropped:
        notes.append("%d entries of the style of '%s' are neither in the map "
                     "nor named, and are not given a class"
                     % (dropped, layer.name()))
    if len(out) > MAX_THEMATIC_CLASSES:
        notes.append("the style names %d classes: only the first %d are "
                     "given a chip" % (len(out), MAX_THEMATIC_CLASSES))
        for c in out[MAX_THEMATIC_CLASSES:]:
            seen.discard(c["code"])
        out = out[:MAX_THEMATIC_CLASSES]
    if out:
        notes.append("classes taken from the style of '%s': %s"
                     % (layer.name(), ", ".join(str(c["code"]) for c in out)))
    extra = [v for v in present if v not in seen]
    if out and extra:
        notes.append("values in the map that its style does not name, given "
                     "a class each: %s" % ", ".join(str(v) for v in extra))
    # A class the attribute table names and the map does not hold is kept,
    # as one a style names is: the model may have missed it.
    extra = sorted(set(extra) | set(
        v for v, t in told.items()
        if v not in seen and t.get("name")
        and not (nodata is not None and v == nodata)))
    room = max(0, MAX_THEMATIC_CLASSES - len(out))
    if len(extra) > room:
        notes.append("the band holds %d different values: only the first %d "
                     "are given a chip" % (len(extra), room))
        extra = extra[:room]
    from_style = bool(out)
    for v in extra:
        mine = told.get(v) or {}
        colour, name = mine.get("colour"), mine.get("name") or ""
        origin = "attribute table" if (colour or name) else None
        if colour is None and table is not None:
            try:
                if 0 <= v < table.GetCount():
                    r, g, b, a = table.GetColorEntry(v)[:4]
                    if a:
                        colour = QColor(r, g, b).name()
            except Exception:
                colour = None
        if not name:
            name = file_name(v)
        # Where the reading came from, for the window that asks the user to
        # confirm it: a class named by the style, one the attribute table or
        # the colour table of the file carries, or a bare value given a
        # colour of its own.
        out.append({"code": v, "name": name,
                    "colour": colour or thematic_colour(len(out)),
                    "origin": origin or ("colour table" if (colour or name)
                                         else "value")})
        seen.add(v)
    if not from_style:
        notes.append("classes taken from the values in the map: %s"
                     % (", ".join(str(c["code"]) for c in out) or "none"))
    return name_classes(out)


def name_classes(classes):
    """Every class with a name, and no two with the same one: a style may
    leave a label empty, or give two values the same."""
    taken = set()
    for c in classes:
        name = (c.get("name") or "").strip() or "class %d" % c["code"]
        if name in taken:
            name = "%s (%d)" % (name, c["code"])
        c["name"] = name
        taken.add(name)
    return classes


#  The working copy of a thematic map, and the files beside it
# =====================================================================
#  The correction of a thematic map is a thematic map. The working copy has
#  the bands of the map it corrects and nothing else: the same bands in the
#  same order, with the same names, type, nodata, grid and layout, the class
#  band holding the corrected classes and every other band as it was. It
#  opens in QGIS, in GDAL and in any other program the way the original does.
#
#  A sixth band, "corrected", to say which pixels a person changed, would
#  make QGIS take the first three bands for red, green and blue, and the map
#  would open as a picture of class, probability and entropy (RasterLabel
#  1.0 wrote it so). That record lives beside the copy, in a raster of its
#  own:
#
#      <map>_corrected.tif            the corrected map
#      <map>_corrected_changes.tif    1 where a person changed a pixel
#      <map>_corrected.qml            the QGIS style it opens with
#
#  and the classes are also written as the colour table and category names of
#  the class band, for every program that is not QGIS.

# Compressions that give back every value as it was written. Anything else,
# JPEG or WEBP above all, would change the codes of a class map, so a source
# compressed that way is copied with LZW instead.
LOSSLESS = ("LZW", "DEFLATE", "ZSTD", "PACKBITS", "LZMA")


def _quiet_gdal():
    """GDAL errors kept off the console: every call below says what went
    wrong in its own words. A fake gdal without the call is let through."""
    push = getattr(gdal, "PushErrorHandler", None)
    if push is None:
        return False
    push("CPLQuietErrorHandler")
    return True


def _loud_gdal(pushed):
    if pushed:
        gdal.PopErrorHandler()


def _there(path):
    """os.path.exists, past the 260 characters of Windows: a correction in a
    deep folder writes its files there through GDAL, which is not bound by
    the limit, and Python has to find them where GDAL put them."""
    return os.path.exists(long_path(path))


def _move(a, b):
    os.replace(long_path(a), long_path(b))


def _drop(path):
    os.remove(long_path(path))


def temporary_name(path):
    """Where a file is written before it takes its real name: beside it, so
    the rename is one step on one disk, and still a .tif, so that anything
    that looks at the folder sees a raster and not a mystery."""
    stem, ext = os.path.splitext(path)
    return "%s.partial%s" % (stem, ext or ".tif")


def is_bigtiff(src):
    """True when the GeoTIFF src was opened from is a BigTIFF: version 43 in
    its header, where a classic TIFF has 42. GDAL says it nowhere else."""
    head = None
    try:
        handle = gdal.VSIFOpenL(src.GetDescription(), "rb")
        if handle is None:
            return False
        try:
            head = gdal.VSIFReadL(1, 4, handle)
        finally:
            gdal.VSIFCloseL(handle)
    except Exception:
        return False
    if not head or len(head) < 4:
        return False
    if head[:2] == b"II":
        return head[2:4] == b"\x2b\x00"
    if head[:2] == b"MM":
        return head[2:4] == b"\x00\x2b"
    return False


def creation_options_like(src):
    """GeoTIFF creation options that give a copy the layout of src: its
    compression when that one keeps every value, its predictor, its
    interleave, its tiles or its strips. A copy laid out like the original is
    as fast to read in the same places, and is the same file to anybody who
    compares the two."""
    try:
        ims = src.GetMetadata("IMAGE_STRUCTURE") or {}
    except Exception:
        ims = {}
    try:
        gtiff = src.GetDriver().ShortName == "GTiff"
    except Exception:
        gtiff = False
    compression = str(ims.get("COMPRESSION") or "").upper()
    # A BigTIFF stays a BigTIFF: IF_SAFER alone made a classic TIFF of a
    # small one, which some readers then took for another kind of file.
    out = ["BIGTIFF=YES" if gtiff and is_bigtiff(src) else "BIGTIFF=IF_SAFER"]
    if compression in LOSSLESS:
        out.append("COMPRESS=%s" % compression)
    elif compression or not gtiff:
        # Lossy, unknown, or a format that says nothing: a class map is
        # never handed to a codec that could move its codes.
        compression = "LZW"
        out.append("COMPRESS=LZW")
    predictor = str(ims.get("PREDICTOR") or "")
    if predictor in ("2", "3") and compression in ("LZW", "DEFLATE", "ZSTD",
                                                   "LZMA"):
        out.append("PREDICTOR=%s" % predictor)
    interleave = str(ims.get("INTERLEAVE") or "").upper()
    if src.RasterCount > 1 and interleave in ("PIXEL", "BAND"):
        out.append("INTERLEAVE=%s" % interleave)
    try:
        bx, by = src.GetRasterBand(1).GetBlockSize()
    except Exception:
        bx, by = 0, 0
    if bx and bx == src.RasterXSize:
        out.append("BLOCKYSIZE=%d" % max(1, by))        # strips, as it had
    elif bx and bx % 16 == 0 and by % 16 == 0:
        out += ["TILED=YES", "BLOCKXSIZE=%d" % bx, "BLOCKYSIZE=%d" % by]
    else:
        out.append("TILED=YES")
    return out


def _translate(destination, src, **options):
    """gdal.Translate, raising IOError whichever way this GDAL reports a
    failure: an exception when exceptions are on, None when they are off."""
    pushed = _quiet_gdal()
    try:
        out = gdal.Translate(destination, src, format="GTiff", **options)
    except Exception as err:
        out, why = None, str(err)
    else:
        why = gdal.GetLastErrorMsg() if out is None else ""
    finally:
        _loud_gdal(pushed)
    if out is None:
        raise IOError("cannot write %s. The disk may be full or the folder "
                      "read only.\n%s" % (os.path.basename(destination), why))
    out.FlushCache()
    out = None


def _forget_statistics(path, band_no):
    """The statistics GDAL or QGIS kept for the class band are those of the
    map before it was corrected: a maximum of 4 on a map a person has just
    painted a class 5 into. They are dropped; whoever needs them again
    computes them from the pixels."""
    if not band_no:
        return
    ds = open_raster(path, gdal.GA_Update)
    if ds is None or not 1 <= int(band_no) <= ds.RasterCount:
        ds = None
        return
    band = ds.GetRasterBand(int(band_no))
    kept = {k: v for k, v in (band.GetMetadata() or {}).items()
            if not k.upper().startswith("STATISTICS_")}
    if len(kept) != len(band.GetMetadata() or {}):
        band.SetMetadata(kept)
    band = None
    ds.FlushCache()
    ds = None


def type_for_all(kinds):
    """The one GDAL type that holds every value of every one of these types,
    as GDAL itself unites them: Int16 and UInt16 give Int32, Int32 and
    Float32 give Float64. Bit size alone would have made UInt16 of Int16 and
    UInt16, and every negative value of the Int16 band a zero. A GDAL without
    the call gets the widest by size, and the comparison after the copy
    refuses whatever that type could not hold."""
    union = getattr(gdal, "DataTypeUnion", None)
    out = kinds[0]
    for kind in kinds[1:]:
        if union is not None:
            out = union(out, kind)
        elif gdal.GetDataTypeSize(kind) > gdal.GetDataTypeSize(out):
            out = kind
    return out


def build_copy(source, destination, log_lines=None, band_no=None, wkt=None):
    """The working copy of a thematic map: the map itself, band for band.

    Every band in its order, with its description, its type, its nodata, its
    colour interpretation and its metadata, on the same grid and in the same
    layout; nothing added. The statistics of the class band are left behind,
    because the correction is about to change them. GeoTIFF keeps one type
    for every band, so a source whose bands differ in type (a VRT, an IMG, a
    netCDF) is the one thing that cannot be copied as it is: the copy then
    uses the one type that holds every value of every band (type_for_all),
    says so, and compares the copy with the source band for band, pixel for
    pixel and nodata for nodata, refusing it if a single value moved.

    wkt, when given, is the system to write into a copy whose source names
    none: the one set on the layer in QGIS (wkt_of). A source that names
    one keeps its own.

    The source is opened read only and is never written to. Returns the
    number of bands."""
    src = open_raster(source)
    if src is None:
        raise IOError("cannot read %s" % source)
    n = src.RasterCount
    kinds = [src.GetRasterBand(b).DataType for b in range(1, n + 1)]
    options = {"creationOptions": creation_options_like(src)}
    given_srs = bool(wkt) and not (src.GetProjection() or "")
    if given_srs:
        options["outputSRS"] = wkt
        if log_lines is not None:
            log_lines.append("the map names no coordinate system in its file: "
                             "the copy gets the one its layer has in QGIS")
    mixed = len(set(kinds)) > 1
    if mixed:
        common = type_for_all(kinds)
        options["outputType"] = common
        if log_lines is not None:
            log_lines.append("the bands do not share one type, which a GeoTIFF "
                             "cannot hold: the copy uses %s for all of them, "
                             "which holds every value of each"
                             % gdal.GetDataTypeName(common))
    tmp = temporary_name(destination)
    try:
        _translate(tmp, src, **options)
        if mixed:
            back = gdal.Open(tmp)
            if back is None:
                raise IOError("%s does not read back" % os.path.basename(tmp))
            bands = list(range(1, n + 1))
            wrong = differences(src, bands, back, bands, same_type=False)
            if given_srs:
                wrong = [w for w in wrong
                         if w != "the coordinate system changed"]
            back = None
            if wrong:
                raise IOError(
                    "%s has bands of different types, and the copy in one "
                    "type would not be the same map: %s. Nothing was made; "
                    "convert the map to one type and correct that."
                    % (os.path.basename(source), "; ".join(wrong)))
        src = None
        _forget_statistics(tmp, band_no)
        _move(tmp, destination)
        if _there(tmp + ".aux.xml"):
            _move(tmp + ".aux.xml", destination + ".aux.xml")
    except Exception:
        src = None
        for leftover in (tmp, tmp + ".aux.xml"):
            try:
                if _there(leftover):
                    _drop(leftover)
            except OSError:
                pass
        raise
    return n


def build_changes(like, destination, flags=None, name=FLAG_BAND_NAME,
                  meaning="1 a person changed this pixel in Correct, 0 it is "
                          "as the map arrived",
                  colour=(255, 0, 255, 255)):
    """The record of which pixels a person changed, beside the working copy:
    one byte band on the grid of the copy, 0 where the map is as it arrived
    and 1 where somebody changed it, with a colour table that shows the ones
    in magenta and leaves the rest clear when it is opened on its own.

    flags, when given, is a band whose non-zero pixels are the ones changed:
    the "corrected" band of a copy made by RasterLabel 1.0. Without it the
    record starts empty, as a new correction does.

    name, meaning and colour are the band's description, its MEANING item and
    the colour of the ones. Left as they are, this is the record of changes;
    another record of pixels on the same grid (which ones a stroke went over)
    is the same file with other words on it.

    Written under a temporary name and put in place only once it reads back
    whole, so an interruption leaves the record that was there, or none, and
    never half of one. Returns how many pixels it marks as changed."""
    ref = open_raster(like)
    if ref is None:
        raise IOError("cannot read %s" % like)
    w, h = ref.RasterXSize, ref.RasterYSize
    # The grid of the copy, or none when the copy has none: GDAL's default
    # written as if it were real put the record of a picture at y 0 to
    # +rows, while QGIS draws the picture at 0 to -rows, beside it.
    gt = pixel_grid(ref) if has_grid(ref) else None
    wkt = ref.GetProjection()
    ref = None
    tmp = temporary_name(destination)
    pushed = _quiet_gdal()
    try:
        ds = gdal.GetDriverByName("GTiff").Create(
            tmp, w, h, 1, gdal.GDT_Byte,
            ["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"])
    except Exception as err:
        ds, why = None, str(err)
    else:
        why = gdal.GetLastErrorMsg() if ds is None else ""
    finally:
        _loud_gdal(pushed)
    if ds is None:
        raise IOError("cannot create %s. The disk may be full or the folder "
                      "read only.\n%s" % (os.path.basename(destination), why))
    marked = 0
    try:
        if gt is not None:
            ds.SetGeoTransform(gt)
        if wkt:
            ds.SetProjection(wkt)
        band = ds.GetRasterBand(1)
        band.SetDescription(name)
        band.SetMetadataItem("MEANING", meaning)
        table = gdal.ColorTable()
        table.SetColorEntry(0, (0, 0, 0, 0))
        table.SetColorEntry(1, tuple(int(c) for c in colour))
        band.SetColorTable(table)
        if flags is None:
            band.Fill(0)
        else:
            for row in range(0, h, STRIP_ROWS):
                take = min(STRIP_ROWS, h - row)
                strip = (flags.ReadAsArray(0, row, w, take) != 0).astype(np.uint8)
                marked += int(strip.sum())
                band.WriteArray(strip, 0, row)
        band = None
        ds.FlushCache()
        ds = None
        back = gdal.Open(tmp)
        if back is None or (back.RasterXSize, back.RasterYSize) != (w, h):
            raise IOError("%s does not read back" % os.path.basename(tmp))
        if flags is not None:
            again = 0
            got = back.GetRasterBand(1)
            for row in range(0, h, STRIP_ROWS):
                take = min(STRIP_ROWS, h - row)
                again += int(got.ReadAsArray(0, row, w, take).sum())
            got = None
            if again != marked:
                raise IOError("%s reads back %d changed pixels, not %d"
                              % (os.path.basename(tmp), again, marked))
        back = None
        _move(tmp, destination)
    except Exception:
        ds = None
        try:
            if _there(tmp):
                _drop(tmp)
        except OSError:
            pass
        raise
    return marked


def write_window(path, band_no, array, col, row):
    """array written into band band_no of path at col, row, through a handle
    opened for this alone and closed before it returns.

    This is how Correct writes a stroke, and an Undo, into the working copy
    and into the record of changes beside it. It does not hold one handle
    open for writing for the whole correction and only flush it after a
    stroke. Through the libtiff of Debian and Ubuntu a compressed block
    flushed that way cannot be read by any other handle until the writer
    closes: QGIS would draw the map blank after the first stroke, no other
    program could read it, and a QGIS that died would leave the blocks of
    the last stroke unreadable.
    Closed after every stroke, the file on disk is whole between any two
    strokes, for whoever reads it and whatever happens to QGIS next. Opening
    it again costs a few milliseconds a stroke on a map of 10000 x 10000.

    Raises IOError, in GDAL's words, when the file cannot be opened for
    writing or the window does not reach the disk. The error carries
    touched: False when the file was never opened for writing, so nothing
    reached the disk and there is nothing to put back."""
    name = os.path.basename(path)

    def refuse(text, touched):
        error = IOError(text)
        error.touched = touched
        return error

    def why():
        said = getattr(gdal, "GetLastErrorMsg", None)
        return (said() if said is not None else "") or "GDAL gave no reason"

    reset = getattr(gdal, "ErrorReset", None)
    last = getattr(gdal, "GetLastErrorType", None)
    pushed = _quiet_gdal()
    ds = band = None
    try:
        if reset is not None:
            reset()
        try:
            ds = gdal.Open(path, gdal.GA_Update)
        except Exception as err:
            raise refuse("cannot open %s for writing: %s" % (name, err), False)
        if ds is None:
            raise refuse("cannot open %s for writing: %s" % (name, why()),
                         False)
        try:
            band = ds.GetRasterBand(int(band_no))
            failed = band.WriteArray(array, int(col), int(row)) not in (0, None)
            band = None
            close = getattr(ds, "Close", None)
            if close is not None:
                failed = close() not in (0, None) or failed
            ds = None
        except Exception as err:
            raise refuse("cannot write %s: %s" % (name, err), True)
        if failed or (last is not None and last() >= 3):   # CE_Failure
            raise refuse("cannot write %s: %s" % (name, why()), True)
    finally:
        band = None
        ds = None
        _loud_gdal(pushed)


def flag_band_of(ds):
    """The number of the band RasterLabel 1.0 added to say which pixels a
    person changed, or None."""
    found = None
    for b in range(1, ds.RasterCount + 1):
        if (ds.GetRasterBand(b).GetDescription() or "").lower() == FLAG_BAND_NAME:
            found = b
    return found


def _same_value(a, b):
    if a is None or b is None:
        return a is None and b is None
    if a != a and b != b:
        return True                     # both NaN
    return a == b


def differences(a, a_bands, b, b_bands, same_type=True):
    """Where two rasters differ, band against band, in words: size, grid,
    coordinate system, type, description, nodata and every pixel, read in
    strips so a map of gigabytes is compared without being held. An empty
    list when they are the same.

    same_type=False lets a band change its type, as one of a map whose bands
    differ in type must in a GeoTIFF, and asks only that every value, the
    nodata among them, be the same number."""
    out = []
    if (a.RasterXSize, a.RasterYSize) != (b.RasterXSize, b.RasterYSize):
        return ["%d x %d pixels against %d x %d"
                % (a.RasterXSize, a.RasterYSize, b.RasterXSize, b.RasterYSize)]
    if tuple(a.GetGeoTransform()) != tuple(b.GetGeoTransform()):
        out.append("the grid moved")
    if (a.GetProjection() or "") != (b.GetProjection() or ""):
        out.append("the coordinate system changed")
    if len(a_bands) != len(b_bands):
        return out + ["%d bands against %d" % (len(a_bands), len(b_bands))]
    w, h = a.RasterXSize, a.RasterYSize
    for i, j in zip(a_bands, b_bands):
        x, y = a.GetRasterBand(i), b.GetRasterBand(j)
        if same_type and x.DataType != y.DataType:
            out.append("band %d changed type" % j)
            continue
        if (x.GetDescription() or "") != (y.GetDescription() or ""):
            out.append("band %d lost its name" % j)
        if not _same_value(x.GetNoDataValue(), y.GetNoDataValue()):
            out.append("band %d changed its nodata" % j)
        for row in range(0, h, STRIP_ROWS):
            take = min(STRIP_ROWS, h - row)
            p = x.ReadAsArray(0, row, w, take)
            q = y.ReadAsArray(0, row, w, take)
            if p is None or q is None:
                out.append("band %d cannot be read" % j)
                break
            same = (np.array_equal(p, q, equal_nan=True)
                    if "f" in (p.dtype.kind, q.dtype.kind)
                    else np.array_equal(p, q))
            if not same:
                out.append("band %d differs from row %d" % (j, row))
                break
    return out


def held_aux_of(copy, bands):
    """Where the .aux.xml of a copy of so many bands waits while the copy is
    replaced: beside it, with the number of bands it speaks of in its name, so
    that whoever finds it later knows which copy it belongs to."""
    return "%s.aux.xml.%d-bands" % (copy, int(bands))


def settle_held_aux(copy):
    """A rewrite of the copy stopped between its two renames, finished or
    undone: the .aux.xml put aside for the old copy is given back to it if the
    old copy is still there, and dropped if the new one has taken its place,
    whose own .aux.xml, if it had one, is put where GDAL looks for it.

    It has to run before anything reads the copy: the names of its bands,
    the "corrected" one among them, may be in that .aux.xml only. Returns a
    line for the log, or "" when there was nothing to settle."""
    folder = os.path.dirname(copy) or "."
    head = os.path.basename(copy) + ".aux.xml."
    try:
        names = [n for n in os.listdir(long_path(folder))
                 if n.startswith(head) and n.endswith("-bands")]
    except OSError:
        return ""
    if not names:
        return ""
    aux = copy + ".aux.xml"
    tmp_aux = temporary_name(copy) + ".aux.xml"
    pushed = _quiet_gdal()
    try:
        ds = gdal.Open(copy)
        count = ds.RasterCount if ds is not None else None
    except Exception:
        count = None
    finally:
        ds = None
        _loud_gdal(pushed)
    said = []
    for name in names:
        held = os.path.join(folder, name)
        try:
            bands = int(name[len(head):-len("-bands")])
        except ValueError:
            continue
        try:
            if count == bands:
                # The old copy is still in place: its .aux.xml goes back.
                if _there(aux):
                    _drop(aux)
                _move(held, aux)
                said.append("the .aux.xml of %s given back to it, whose "
                            "rewrite had stopped before it took its place"
                            % os.path.basename(copy))
            elif count is not None:
                _drop(held)
                if not _there(aux) and _there(tmp_aux) \
                        and not _there(temporary_name(copy)):
                    _move(tmp_aux, aux)
                said.append("the old .aux.xml of %s dropped: the copy had been "
                            "rewritten when the work stopped"
                            % os.path.basename(copy))
        except OSError as err:
            said.append("%s could not be settled: %s" % (name, err))
    return "; ".join(said)


def strip_flag_band(copy, changes, band_no=1, before_swap=None):
    """A working copy made by RasterLabel 1.0, brought to the shape of the
    map it corrects: its "corrected" band moved out to the record beside it,
    and the copy rewritten with the other bands only.

    Nothing is lost on the way, whenever it stops. The record is written
    first, whole and checked against the band, before the copy is touched.
    The copy without the band is written under a temporary name and compared
    with the old one band for band, pixel for pixel. Then before_swap, when
    given, is called with what is about to be done, which is where the
    manifest is told the new number of the class band before the copy can
    change under it. Only then does the new copy take the old one's place:
    the old .aux.xml is put aside under a name that says how many bands it
    speaks of (held_aux_of), the copy is renamed over the old one, the new
    .aux.xml, if there is one, is put in place, and the old one is dropped.
    Stopped anywhere in there, settle_held_aux finishes or undoes it the next
    time; stopped before, the old copy is there, flag band and all, and the
    next opening simply does it again.

    Returns None when the copy has no such band, else what was done:
    {"pixels": changed pixels, "band": the class band now, "dropped": the
    number the flag band had, "bands": how many are left}."""
    settled = settle_held_aux(copy)
    if settled:
        log(settled)
    src = open_raster(copy)
    if src is None:
        raise IOError("cannot read %s" % copy)
    n = src.RasterCount
    flag = flag_band_of(src)
    if flag is None:
        src = None
        return None
    keep = [b for b in range(1, n + 1) if b != flag]
    if not keep:
        src = None
        raise IOError("%s holds the '%s' band and nothing else"
                      % (os.path.basename(copy), FLAG_BAND_NAME))
    band_no = int(band_no or 1)
    now_band = band_no - 1 if flag < band_no else band_no
    tmp = temporary_name(copy)
    aux = copy + ".aux.xml"
    held = held_aux_of(copy, n)
    swapped = False
    try:
        pixels = build_changes(copy, changes, flags=src.GetRasterBand(flag))
        _translate(tmp, src, bandList=keep,
                   creationOptions=creation_options_like(src))
        _forget_statistics(tmp, now_band)
        back = gdal.Open(tmp)
        if back is None:
            raise IOError("%s does not read back" % os.path.basename(tmp))
        wrong = differences(src, keep, back, list(range(1, len(keep) + 1)))
        back = None
        if wrong:
            raise IOError("the copy rewritten without the '%s' band is not "
                          "the same as the copy: %s"
                          % (FLAG_BAND_NAME, "; ".join(wrong)))
        src = None
        done = {"pixels": pixels, "band": now_band, "dropped": flag,
                "bands": len(keep)}
        if before_swap is not None:
            before_swap(done)
        # The .aux.xml of the old copy speaks of its bands, the one that is
        # going among them, and of the statistics the class band had before
        # it was corrected. Everything else it held, the names of the bands,
        # is inside the new copy and was compared above. It waits under a
        # name of its own while the copy is replaced, so that no moment
        # leaves the old copy without it or the new one with it.
        if _there(aux):
            _move(aux, held)
        try:
            _move(tmp, copy)
        except Exception:
            if _there(held) and not _there(aux):
                _move(held, aux)
            raise
        swapped = True
    except Exception:
        src = None
        if not swapped:
            for leftover in (tmp, tmp + ".aux.xml"):
                try:
                    if _there(leftover):
                        _drop(leftover)
                except OSError:
                    pass
        raise
    try:
        if _there(tmp + ".aux.xml"):
            _move(tmp + ".aux.xml", aux)
        if _there(held):
            _drop(held)
    except OSError as err:
        log("the old %s could not be replaced: %s. It is settled the next "
            "time the correction opens." % (os.path.basename(aux), err))
    return done


def colour_entries(classes):
    """The colour table and category names of a class band, as two lists
    indexed by the code: the colour of every class, clear for every value
    that is none, and its name. None when a table cannot hold the codes,
    which GDAL numbers from 0 up."""
    codes = [int(c["code"]) for c in classes]
    if not codes or min(codes) < 0 or max(codes) > 65535:
        return None
    size = max(codes) + 1
    colours = [(0, 0, 0, 0)] * size
    names = [""] * size
    for c in classes:
        col = QColor(str(c.get("colour") or ""))
        if col.isValid():
            colours[int(c["code"])] = (col.red(), col.green(), col.blue(), 255)
        names[int(c["code"])] = str(c.get("name") or "")
    return colours, names


def band_counts(band, nodata=None):
    """How many pixels of a band hold each value, {code: count}, read in
    strips so a map of gigabytes is counted without being held."""
    out = {}
    w, h = band.XSize, band.YSize
    for row in range(0, h, STRIP_ROWS):
        take = min(STRIP_ROWS, h - row)
        for code, n in class_counts(band.ReadAsArray(0, row, w, take),
                                    nodata).items():
            out[code] = out.get(code, 0) + n
    return out


def band_marked(ds, band_no=1):
    """How many pixels of a band of an open dataset are not zero, read in
    strips: the pixels a record of changes marks, counted without holding
    the record."""
    marked = 0
    w, h = ds.RasterXSize, ds.RasterYSize
    band = ds.GetRasterBand(band_no)
    for row in range(0, h, STRIP_ROWS):
        take = min(STRIP_ROWS, h - row)
        marked += int(np.count_nonzero(band.ReadAsArray(0, row, w, take)))
    return marked


def _blank(column):
    return "" if column["kind"] == "text" else 0


def _cell(column, value):
    """A value as the column holds it: whole numbers in an integer column."""
    if column["kind"] == "int":
        return int(round(float(value)))
    if column["kind"] == "real":
        return float(value)
    return str(value)


def table_rows_for(table, classes, counts):
    """The rows of an attribute table rewritten for these classes: one per
    class, with its value, its name, its colour where the table has colour
    columns and its pixel count where it has a count column, counted again;
    every other column keeps what the row of that value held, and a class
    the table did not have gets them empty. A table with no column of values
    is indexed by the value, so its rows run from 0 to the highest code, and
    a row that is no class loses its name and its colour."""
    columns = table["columns"]
    roles = table_roles(table)
    classes = sorted((c for c in classes if "code" in c),
                     key=lambda c: int(c["code"]))
    if roles["value"] is None:
        codes = [int(c["code"]) for c in classes if int(c["code"]) >= 0]
        size = max([len(table["rows"])] + [k + 1 for k in codes])
        mine = {int(c["code"]): c for c in classes}
        out = []
        for k in range(size):
            row = (list(table["rows"][k]) if k < len(table["rows"])
                   else [_blank(col) for col in columns])
            out.append(_fill_row(row, columns, roles, k, mine.get(k), counts))
        return out
    by_code = {}
    for row in table["rows"]:
        try:
            by_code.setdefault(int(float(row[roles["value"]])), row)
        except (TypeError, ValueError, OverflowError):
            continue
    out = []
    for c in classes:
        code = int(c["code"])
        old = by_code.get(code)
        row = list(old) if old is not None else [_blank(col) for col in columns]
        out.append(_fill_row(row, columns, roles, code, c, counts))
    return out


def _fill_row(row, columns, roles, code, cls, counts):
    """One row of table_rows_for: cls is the class of this code, or None for
    a row of a table indexed by value that is no class."""
    if roles["value"] is not None:
        row[roles["value"]] = _cell(columns[roles["value"]], code)
    if roles["name"] is not None:
        row[roles["name"]] = str((cls or {}).get("name") or "")
    if roles["red"] is not None:
        colour = QColor(str((cls or {}).get("colour") or ""))
        rgba = ((colour.red(), colour.green(), colour.blue(), 255)
                if cls is not None and colour.isValid() else (0, 0, 0, 0))
        for k, role in enumerate(("red", "green", "blue", "alpha")):
            if roles[role] is not None:
                row[roles[role]] = _cell(columns[roles[role]],
                                         rgba[k] * roles["scale"] / 255.0)
    if roles["count"] is not None:
        row[roles["count"]] = _cell(columns[roles["count"]],
                                    counts.get(code, 0))
    return row


def write_rat(band, table, rows):
    """The rows written as the band's Raster Attribute Table, with the
    columns, types, usages and table type the old one had. Colour columns
    known only by their names, as GDAL reads those of a .vat.dbf, are told
    to be colours: QGIS then draws the classes in them, and not in colours
    of its own choosing. True when GDAL took it."""
    roles = table_roles(table)
    usages = [c["usage"] for c in table["columns"]]
    if roles["by_name"]:
        for role, name in (("red", "GFU_Red"), ("green", "GFU_Green"),
                           ("blue", "GFU_Blue"), ("alpha", "GFU_Alpha")):
            if roles[role] is not None and hasattr(gdal, name):
                usages[roles[role]] = getattr(gdal, name)
    rat = gdal.RasterAttributeTable()
    for c, usage in zip(table["columns"], usages):
        rat.CreateColumn(c["name"], c["gft"], usage)
    rat.SetRowCount(len(rows))
    for r, row in enumerate(rows):
        for i, c in enumerate(table["columns"]):
            if c["kind"] == "int":
                rat.SetValueAsInt(r, i, int(row[i]))
            elif c["kind"] == "real":
                rat.SetValueAsDouble(r, i, float(row[i]))
            else:
                rat.SetValueAsString(r, i, str(row[i]))
    if table.get("table_type") is not None:
        try:
            rat.SetTableType(table["table_type"])
        except Exception:
            pass
    return band.SetDefaultRAT(rat) in (0, None)


def write_vat(dbf, table, rows):
    """The rows written as an ArcGIS <map>.tif.vat.dbf, with the fields,
    widths and precisions of the one they were read from: under a temporary
    name first, then renamed over the old one."""
    stem = dbf[:-len(".dbf")]
    tmp_stem = stem + ".partial"
    for ext in (".dbf", ".cpg"):
        if _there(tmp_stem + ext):
            _drop(tmp_stem + ext)
    pushed = _quiet_gdal()
    try:
        out = ogr.GetDriverByName("ESRI Shapefile").CreateDataSource(
            tmp_stem + ".dbf")
        if out is None:
            raise IOError("cannot create %s" % os.path.basename(dbf))
        layer = out.CreateLayer(os.path.basename(tmp_stem), None, ogr.wkbNone)
        for c in table["columns"]:
            field = ogr.FieldDefn(c["name"], c["ogr"])
            if c.get("width"):
                field.SetWidth(c["width"])
            if c.get("precision"):
                field.SetPrecision(c["precision"])
            layer.CreateField(field)
        defn = layer.GetLayerDefn()
        for row in rows:
            feature = ogr.Feature(defn)
            for i in range(len(table["columns"])):
                feature.SetField(i, row[i])
            layer.CreateFeature(feature)
            feature = None
        defn = None
        layer = None
        out = None
    finally:
        _loud_gdal(pushed)
    for ext in (".dbf", ".cpg"):
        if not _there(tmp_stem + ext):
            continue
        try:
            _move(tmp_stem + ext, stem + ext)
        except PermissionError:
            # QGIS 3.36 reads a .vat.dbf itself, through a pool of open
            # files that keeps it open after the layer has gone, and Windows
            # renames nothing over an open file. It still lets it be
            # written: the new table is written into the old file.
            with open(long_path(tmp_stem + ext), "rb") as f:
                body = f.read()
            with open(long_path(stem + ext), "r+b") as f:
                f.write(body)
                f.truncate()
            _drop(tmp_stem + ext)


def dress_attribute_table(path, band_no, classes, ds=None, template=None):
    """The attribute table of the class band, where the map has one, made
    the correction's: a row per class with its name, its colour and its
    pixel count as the corrected map has them now (table_rows_for). That is
    the copy's own Raster Attribute Table, copied with the map it corrects,
    and its <copy>.tif.vat.dbf, made from the map's own (template) the first
    time, when the map has one. Without this the copy carried the names,
    colours and counts of the map before it was corrected, and a program
    that reads the table, QGIS without the .qml among them, showed those: a
    class added in the correction was not in it at all.

    ds, when given, is a handle the caller holds open for writing (Correct
    holds none: it closes the copy after every stroke, write_window). A file
    of several bands keeps its table in an .aux.xml that such a handle writes
    when it closes, over the colour table written beside it by another, so
    its table is then left for the closing, when no handle is open
    (drop_correction).
    Returns a line for the log, "" when the map has no table."""
    said = []
    vat = vat_of(path)
    vat_table = table_of_vat(path) if _there(vat) else (
        table_of_vat(template) if template else None)
    counts = {}
    pushed = _quiet_gdal()
    mine = probe = target = None
    try:
        probe = pam_ready(ds if ds is not None else gdal.Open(path))
        if probe is None or not 1 <= int(band_no) <= probe.RasterCount:
            return ""
        single = probe.RasterCount == 1
        band = probe.GetRasterBand(int(band_no))
        get = getattr(band, "GetDefaultRAT", None)
        rat = get() if get is not None else None
        rat_table = (table_of_rat(rat) if rat is not None
                     and rat.GetColumnCount() else None)
        rat = None
        if rat_table is None and vat_table is None:
            return ""
        counts = band_counts(band, band.GetNoDataValue())
        band = None
        if rat_table is not None and ds is not None and not single:
            said.append("its attribute table follows when Correct closes")
        elif rat_table is not None:
            if ds is None:
                probe = None
                mine = pam_ready(gdal.Open(path, gdal.GA_Update))
                target = mine
            else:
                target = ds
            ok = target is not None and write_rat(
                target.GetRasterBand(int(band_no)), rat_table,
                table_rows_for(rat_table, classes, counts))
            if target is not None:
                target.FlushCache()
            said.append("its attribute table rewritten, %d rows"
                        % len(classes) if ok
                        else "no attribute table (refused by GDAL)")
    except Exception as err:
        said.append("no attribute table: %s" % err)
    finally:
        target = None
        mine = None
        probe = None
        _loud_gdal(pushed)
    if vat_table is not None and int(band_no) == 1:
        try:
            write_vat(vat, vat_table, table_rows_for(vat_table, classes,
                                                     counts))
            said.append("%s written" % os.path.basename(vat))
        except Exception as err:
            said.append("no %s: %s" % (os.path.basename(vat), err))
    return "; ".join(said)


def dress_class_band(path, band_no, classes, ds=None, template=None):
    """The classes written into the class band itself, as its colour table
    and its category names, so GDAL, rasterio, ArcGIS and every program that
    reads them draws the map in its classes, the way QGIS does from the .qml;
    and into its attribute table, when the map has one
    (dress_attribute_table, template being the map whose .vat.dbf the copy
    follows the first time).

    A GeoTIFF of one band keeps the table inside the file; one of several
    bands cannot (TIFF has no palette for them), and GDAL keeps it in the
    .aux.xml beside it, where it reads it back for band 1 alone: a class
    band further down gets its category names only, and QGIS its classes
    from the .qml. ds, when given, is a handle the caller already holds
    open for writing (Correct holds none between strokes, write_window): a
    second one writing into
    the same file at the same time could leave it broken, so a file of one
    band is written through that handle, and one of several bands through a
    handle that only reads, whose .aux.xml is all it writes.

    Returns a line for the log. Never raises: the map is whole without a
    colour table, and a program that cannot read one still has the .qml."""
    try:
        attributes = dress_attribute_table(path, band_no, classes, ds=ds,
                                           template=template)
    except Exception as err:
        attributes = "no attribute table: %s" % err
    said = _dress_colour_table(path, band_no, classes, ds=ds)
    return said + ("; " + attributes if attributes else "")


def _dress_colour_table(path, band_no, classes, ds=None):
    """The colour table and the category names of dress_class_band."""
    table = colour_entries(classes)
    if table is None:
        return ("no colour table: GDAL numbers a table from 0, and these "
                "codes are not all between 0 and 65535")
    colours, names = table
    mine = None
    pushed = _quiet_gdal()
    try:
        probe = ds if ds is not None else gdal.Open(path)
        if probe is None:
            return "no colour table: %s cannot be read" % os.path.basename(path)
        single = probe.RasterCount == 1
        if not 1 <= int(band_no) <= probe.RasterCount:
            return "no colour table: there is no band %d" % int(band_no)
        if single and ds is None:
            probe = None
            mine = gdal.Open(path, gdal.GA_Update)
            target = mine
        elif single:
            target = ds
        else:
            # Read only on purpose: GDAL then keeps what is set in .aux.xml.
            mine = probe if ds is None else gdal.Open(path)
            target = mine
        pam_ready(target)
        if target is None:
            return "no colour table: %s cannot be opened" % os.path.basename(path)
        band = target.GetRasterBand(int(band_no))
        said = []
        wide = band.DataType != gdal.GDT_Byte and band.GetColorTable() is None
        if wide:
            # A TIFF gives a band of sixteen bits a table of 65536 colours
            # whatever its codes, and QGIS 3.36 then takes ten seconds to
            # open the map, .qml or not, at every opening. A map that came
            # with no table gets none; the .qml and the category names say
            # its classes, and one that came with a table keeps it.
            # A GeoTIFF holds a table on a band of bytes or sixteen bits
            # only, so on any other the reason is that one.
            said.append("no colour table (the map has none, and one on a "
                        "band of UInt16 would make QGIS 3.36 slow to open it)"
                        if band.DataType == gdal.GDT_UInt16 else
                        "no colour table (a GeoTIFF holds one on a band of "
                        "Byte or UInt16 only, and this one is %s)"
                        % gdal.GetDataTypeName(band.DataType))
        elif single or int(band_no) == 1:
            ct = gdal.ColorTable()
            for v, entry in enumerate(colours):
                ct.SetColorEntry(v, entry)
            try:
                ok = band.SetColorTable(ct) in (0, None)
            except Exception:
                ok = False
            if ok and int(band_no) == 1:
                try:
                    band.SetColorInterpretation(gdal.GCI_PaletteIndex)
                except Exception:
                    pass
            said.append("a colour table of %d entries" % len(colours) if ok
                        else "no colour table (%s)"
                        % (gdal.GetLastErrorMsg() or "refused by GDAL"))
        else:
            # GDAL writes a table for any band into the .aux.xml, and reads
            # it back for the first band of a GeoTIFF only: on the second it
            # was never seen again, and it turned the band into a palette
            # with no colours. The category names are read on any band.
            said.append("no colour table (GDAL reads one only on band 1 of "
                        "a GeoTIFF of several bands)")
        try:
            named = band.SetRasterCategoryNames(names) in (0, None)
        except Exception:
            named = False
        said.append("the names of %d classes" % len(classes) if named
                    else "no category names")
        band = None
        target.FlushCache()
        target = None
        where = "inside the file" if single else "in its .aux.xml"
        return "class band %d of %s given %s, %s" % (
            int(band_no), os.path.basename(path), " and ".join(said), where)
    except Exception as err:
        return "no colour table for %s: %s" % (os.path.basename(path), err)
    finally:
        mine = None
        probe = None
        _loud_gdal(pushed)


#  The QGIS style of the corrected map
# ---------------------------------------------------------------------
#  QGIS opens a raster with the style of the .qml of the same name beside it,
#  if there is one: that is how the original map opens with its classes, and
#  how the corrected map does too. The file is written the way QGIS
#  writes one for a Paletted/Unique values style, and when the map being
#  corrected brought a .qml of its own, the new one is that one with its
#  classes replaced, so whatever else it set (opacity, resampling, a
#  transparency, the blend mode) is set the same way on the corrected map.
#  Once the corrected map has a .qml, that one is followed instead: whatever
#  the user set on it in QGIS and kept with Save as Default, its opacity, its
#  resampling, its blend mode, stays, and only its classes follow the
#  correction's.
QML_DEFAULT = """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.36.0" styleCategories="AllStyleCategories">
  <pipe>
    <provider>
      <resampling enabled="false" zoomedOutResamplingMethod="nearestNeighbour" zoomedInResamplingMethod="nearestNeighbour" maxOversampling="2"/>
    </provider>
    <rasterrenderer alphaBand="-1" type="paletted" band="1" opacity="1" nodataColor="">
      <rasterTransparency/>
      <minMaxOrigin>
        <limits>None</limits>
        <extent>WholeRaster</extent>
        <statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower>
        <cumulativeCutUpper>0.98</cumulativeCutUpper>
        <stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <colorPalette/>
    </rasterrenderer>
    <brightnesscontrast gamma="1" contrast="0" brightness="0"/>
    <huesaturation saturation="0" invertColors="0" grayscaleMode="0" colorizeBlue="128" colorizeGreen="128" colorizeStrength="100" colorizeOn="0" colorizeRed="255"/>
    <rasterresampler maxOversampling="2"/>
    <resamplingStage>resamplingFilter</resamplingStage>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
"""
QML_DOCTYPE = "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>"


def style_of(path):
    """The .qml QGIS reads as the style of this raster: same folder, same
    name, .qml for the extension."""
    return os.path.splitext(str(path).split("|")[0])[0] + ".qml"


def style_text(band_no, classes, template=None):
    """The text of a QGIS style that draws band_no in these classes, as a
    Paletted/Unique values style: each class its code, its colour, its name.

    template is the text of a .qml to follow, the one the corrected map
    brought: its renderer is made a paletted one on the class band, keeping
    its opacity and its transparency, and everything else in it is kept."""
    root = None
    doctype = True
    if template:
        try:
            root = ET.fromstring(template)
            doctype = template.lstrip().startswith("<!DOCTYPE")
        except ET.ParseError:
            root = None
        if root is not None and (root.tag != "qgis"
                                 or root.find("pipe") is None):
            root = None
    if root is None:
        root = ET.fromstring(QML_DEFAULT)
        doctype = True
    pipe = root.find("pipe")
    renderer = pipe.find("rasterrenderer")
    if renderer is None:
        renderer = ET.SubElement(pipe, "rasterrenderer")
    elif renderer.get("type") != "paletted":
        # A style of another kind on the original: its renderer gives way
        # to a paletted one, which keeps what it said about transparency.
        fresh = ET.Element("rasterrenderer")
        for key in ("alphaBand", "opacity", "nodataColor"):
            if renderer.get(key) is not None:
                fresh.set(key, renderer.get(key))
        for child in renderer:
            if child.tag in ("rasterTransparency", "minMaxOrigin"):
                fresh.append(child)
        at = list(pipe).index(renderer)
        pipe.remove(renderer)
        pipe.insert(at, fresh)
        renderer = fresh
    renderer.set("type", "paletted")
    renderer.set("band", str(int(band_no)))
    if renderer.get("opacity") is None:
        renderer.set("opacity", "1")
    palette = renderer.find("colorPalette")
    if palette is None:
        palette = ET.SubElement(renderer, "colorPalette")
    for entry in list(palette):
        palette.remove(entry)
    palette.text = None
    for c in classes:
        col = QColor(str(c.get("colour") or ""))
        entry = ET.SubElement(palette, "paletteEntry")
        entry.set("value", str(int(c["code"])))
        entry.set("color", col.name() if col.isValid() else "#000000")
        entry.set("alpha", "255")
        entry.set("label", str(c.get("name") or ""))
    try:
        ET.indent(root, space="  ")
    except AttributeError:
        pass                            # Python before 3.9 writes it flat
    text = ET.tostring(root, encoding="unicode")
    return (QML_DOCTYPE + "\n" if doctype else "") + text + "\n"


def _is_style(text):
    """True when text reads as a QGIS style with a pipe, the one kind a
    corrected map's style can follow."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return False
    return root.tag == "qgis" and root.find("pipe") is not None


def write_style(path, band_no, classes, template_path=None):
    """The .qml at path, from style_text, written whole or not at all: under
    a temporary name first, then renamed over the old one.

    template_path is the .qml to follow, or a list of them in order of
    preference: the first that is there and reads as a QGIS style is the one
    followed. Returns it, or None when none was and the built-in style was
    used."""
    if isinstance(template_path, (list, tuple)):
        candidates = list(template_path)
    else:
        candidates = [template_path]
    template = used = None
    for candidate in candidates:
        if not candidate or not _there(candidate):
            continue
        try:
            with open(long_path(candidate), encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        if _is_style(text):
            template, used = text, candidate
            break
    text = style_text(band_no, classes, template)
    tmp = path + ".partial"
    with open(long_path(tmp), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    _move(tmp, path)
    return used


def dress_mask(path, driver, classes):
    """The legend of a mask Whole has written: (what to log, the .qml or None).

    A GeoTIFF gets the classes inside it, as its colour table and category
    names (dress_class_band); any mask gets the .qml of the same name beside
    it, which QGIS reads (write_style), and which follows one that is already
    there, so what was set on it by hand stays. A PNG holds no category
    names, and GDAL would put them in an .aux.xml nobody asked for, so for a
    PNG the .qml is all. Pixel values are never touched. Never raises: the
    mask is whole without a legend."""
    legend = []
    seen = set()
    for c in classes or []:
        try:
            code = int(c["code"])
        except (KeyError, TypeError, ValueError):
            continue
        if code in seen:
            continue
        seen.add(code)
        legend.append({"code": code, "name": str(c.get("name") or ""),
                       "colour": str(c.get("colour") or "")})
    if not legend:
        return "", None
    legend.sort(key=lambda c: c["code"])
    said = []
    if driver == "GTiff":
        said.append(dress_class_band(path, 1, legend))
    style = style_of(path)
    try:
        write_style(style, 1, legend, template_path=[style])
        said.append("%s written" % os.path.basename(style))
    except (OSError, ValueError, ET.ParseError) as err:
        said.append("no %s: %s" % (os.path.basename(style), err))
        style = None
    return "; ".join(said), style


def count_rows(path, table):
    try:
        ds = ogr.Open(path)
        if ds is None:
            return 0
        layer = ds.GetLayerByName(table)
        return 0 if layer is None else int(layer.GetFeatureCount())
    except Exception:
        return 0
