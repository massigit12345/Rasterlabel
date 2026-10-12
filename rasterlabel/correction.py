"""rasterlabel.correction

The correction campaign: a folder of its own, with no annotation campaign.
"""
import csv
import json
import os
import uuid

from datetime import datetime
from osgeo import gdal

from .constants import (CHANGES_SUFFIX, CORRECTION_FORMAT, CORRECTION_MANIFEST,
                        FLAG_BAND_NAME, NAME, RECENT_MAX, REVIEWED_BAND_NAME,
                        REVIEWED_MEANING, REVIEWED_SUFFIX, SETTINGS_ROOT,
                        VERSION)
from .compat import read_setting, write_setting
from .naming import (beside_folder, csv_untext_row, from_folder,
                     inside_folder, long_path, now, relative_or_name,
                     source_of, tidy)
from .project import (crs_from_text, crs_to_text, named_crs, pixel_of,
                      pixel_on_the_ground)
from .errors import log
from .campaign import release_file
from .rasters import (build_changes, build_copy, dress_class_band,
                      lossy_codec, open_raster, rotated_file, settle_held_aux,
                      strip_flag_band, style_of, write_style)


#  The correction campaign
# =====================================================================
class CorrectionCampaign(object):
    """A folder, a manifest, a working copy. The manifest is the truth.

    A correction is a campaign of its own, in the folder the user chooses, not
    a part of an annotation campaign. Correct mends any thematic map, made by
    any program, and has nothing to do with a campaign of hand drawing, so it
    must open without one. (Manifests of earlier builds kept the record as a
    line of campaign.json; owner_of_copy still finds those.) The folder holds:

        correction.json                this manifest
        <map>_corrected.tif            the working copy: the corrected map,
                                       with the bands of the map it corrects
        <map>_corrected.qml            its QGIS style, the classes
        <map>_corrected_changes.tif    which pixels a person changed
        <map>_corrected_reviewed.tif   which pixels a stroke went over
        <map>_corrected.tif.vat.dbf    its classes for ArcGIS, when the map
                                       it corrects has one
        operations.csv                 one row per stroke
        rasterlabel.log                while Correct is open

    No GeoPackage and no recovery folder: every stroke is written into the
    copy and into the record of changes as it is made, so there is never
    anything waiting in memory.

    It answers to the same few names an annotation campaign does, data["id"],
    data["grid"], group_name, stem and save(), because those are what the
    layer helpers and Geometry ask of whatever they are handed."""

    MANIFEST = CORRECTION_MANIFEST

    def __init__(self, folder):
        self.folder = folder
        self.data = {}

    @property
    def manifest_path(self):
        return os.path.join(self.folder, self.MANIFEST)

    @property
    def working_path(self):
        """The working copy. Written in the manifest relative to the folder,
        so the folder can be moved or zipped whole and still open; a record
        written by hand may carry an absolute path in "files" instead."""
        if (self.data.get("working_copy") or "").strip():
            return copy_in_folder(self.folder, self.data["working_copy"])
        files = self.data.get("files") or []
        return files[0] if files else ""

    @property
    def changes_path(self):
        """The record of which pixels a person changed, beside the copy."""
        return changes_path_of(self.data, self.working_path)

    @property
    def reviewed_path(self):
        """The record of which pixels a stroke went over, beside the copy."""
        return reviewed_path_of(self.data, self.working_path)

    @property
    def group_name(self):
        return "%s correction: %s" % (NAME, self.data.get("name", ""))

    @property
    def stem(self):
        return tidy(self.data.get("name") or "correction", "correction")

    # ------------------------------------------------------------- disk
    def save(self):
        self.data["modified"] = now()
        tmp = self.manifest_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest_on_disk(self.data, self.folder), f, indent=2,
                      ensure_ascii=False)
        os.replace(tmp, self.manifest_path)

    @classmethod
    def open(cls, folder):
        book = cls(folder)
        with open(book.manifest_path, encoding="utf-8") as f:
            book.data = json.load(f)
        if not isinstance(book.data, dict):
            raise ValueError("%s is not a correction manifest" % book.MANIFEST)
        manifest_in_hand(book.data, folder)
        path = book.working_path
        if not path or not os.path.exists(path):
            log("the working copy of the correction '%s' is not there: %s. "
                "Without it there is nothing to correct; if it was moved, put "
                "it back beside %s." % (book.data.get("name", "?"), path,
                                         book.MANIFEST), loud=True)
        elif not isinstance(book.data.get("grid"), dict) \
                or "pixel_m" not in book.data["grid"]:
            # A manifest written by hand, or by a build that kept none. The
            # copy carries its own grid in its header, so it is read from
            # there once and written down.
            book.data["grid"] = grid_of_copy(path, folder)
            try:
                book.save()
            except Exception as err:
                log("cannot write the grid into the manifest: %s" % err)
            log("correction '%s': the manifest had no grid, read from the "
                "working copy" % book.data.get("name", "?"))
        return book

    @classmethod
    def create(cls, folder, name, layer, band, classes, operator, notes=None,
               resume=False):
        """Make the folder, copy the map into it, and only then write the
        manifest. A creation stopped half way leaves a folder with no
        correction.json, which is not a correction, rather than a manifest
        pointing at a copy that was never finished.

        resume: the folder already holds the working copy of this map but no
        manifest, the leftover of a creation stopped half way or of a
        correction.json lost. The copy is kept as it is, corrections and all,
        and the counters are read back from its operations.csv. Without it a
        copy already there is an error, because reusing it in silence would
        begin a new correction on somebody's old work without a word.
        The panel asks first, and sets the old copy aside when told to start
        afresh."""
        os.makedirs(folder, exist_ok=True)
        book = cls(folder)
        source = source_of(layer)
        working = copy_name(source)
        target = os.path.join(folder, working)
        if resume:
            if not os.path.exists(target):
                raise IOError("there is no working copy to resume: %s" % target)
            log("the working copy already there is resumed: %s" % target)
        elif os.path.exists(target):
            raise IOError("a working copy is already there and was not set "
                          "aside: %s" % target)
        else:
            # The system set on the layer in QGIS when the file names none,
            # so the copy is not born without the one the manifest records.
            try:
                given = layer.crs().toWkt() if layer.crs().isValid() else None
            except Exception:
                given = None
            build_copy(source, target, notes, band_no=int(band), wkt=given)
            log("working copy written: %s, with the bands of the map it "
                "corrects" % target)
        changes = changes_of(target)
        if not resume or not (os.path.exists(long_path(changes))
                              or has_flag_band(target)):
            build_changes(target, changes)
            log("which pixels a person changes is recorded in %s"
                % os.path.basename(changes))
        # and which ground the strokes go over, for Model vs corrected: made
        # at creation, so a new correction has it complete from its first
        # stroke. A copy resumed without it starts one, its strokes so far
        # unknown.
        reviewed = reviewed_of(target)
        if not os.path.exists(long_path(reviewed)):
            try:
                build_reviewed(target, reviewed)
                log("which ground the strokes sweep is recorded in %s"
                    % os.path.basename(reviewed))
            except Exception as err:
                reviewed = None
                log("cannot start %s: %s. The strokes still work; which "
                    "ground they sweep is not remembered."
                    % (os.path.basename(reviewed_of(target)), err))
        nodata = None
        try:
            ds = gdal.Open(target)
            value = ds.GetRasterBand(int(band)).GetNoDataValue()
            nodata = value if value is None or value == value else None
            ds = None
        except Exception:
            nodata = None
        operator = (operator or "").strip().upper() or "OPERATOR 1"
        book.data = {
            "program": NAME, "kind": "correction",
            "format": CORRECTION_FORMAT, "version": VERSION,
            "id": uuid.uuid4().hex[:12],
            "name": tidy(name, "correction"),
            "created": now(),
            "operator": operator, "operators": [operator],
            "source": source, "band": int(band),
            "working_copy": working,
            "changes": os.path.basename(changes),
            "grid": grid_of_layer(layer, size=_size_of(target)),
            "nodata": nodata,
            "classes": [dict(code=int(c["code"]), name=str(c["name"]),
                             colour=str(c["colour"])) for c in classes],
            "classes_confirmed": now(),
            "operations": 0, "changed_m2": 0.0, "swept_m2": 0.0, "pairs": {},
            "last_opened": now(),
        }
        if resume:
            book.data.update(tally_operations(
                os.path.join(folder, "operations.csv")))
            book.data["resumed"] = now()
        if reviewed is not None:
            book.data["reviewed"] = os.path.basename(reviewed)
            # the strokes made before the record began, whose footprints
            # are not known: none for a new correction
            book.data["reviewed_since"] = 0 if not resume else \
                int(book.data.get("operations", 0) or 0)
        book.save()
        dress_copy(target, int(band), book.data["classes"], source)
        return book

    @classmethod
    def adopt(cls, record, campaign):
        """A correction kept inside an annotation campaign, given a campaign
        of its own where it already is. Nothing is copied or moved.

        Its folder, <campaign>/corrections/<name>, already holds the working
        copy and operations.csv; a correction.json is written beside them,
        and the record in campaign.json is kept, with a pointer to it. A
        crash in the middle leaves at worst a manifest beside a record that
        still opens. The pointer is the only thing Correct ever writes into
        an annotation manifest.

        The record of the ground the strokes sweep is not made here: nothing
        but the manifest, its style and the record of changes is added to a
        folder that is adopted. It is started at the next stroke, and
        "reviewed_since" then says how many strokes came before it (the
        operations counted here, as no stroke can come in between)."""
        # a record adopted before keeps its paths from the campaign's folder
        files = [from_folder(f, campaign.folder)
                 for f in record.get("files") or []]
        if not files:
            raise IOError("the correction '%s' names no working copy"
                          % record.get("name", "?"))
        working = files[0]
        folder = os.path.dirname(working)
        if os.path.exists(os.path.join(folder, cls.MANIFEST)):
            book = cls.open(folder)
        else:
            book = cls(folder)
            operator = ((campaign.data.get("operator") or "").strip().upper()
                        or "OPERATOR 1")
            grid = grid_of_copy(working, folder)
            nodata = None
            try:
                ds = gdal.Open(working)
                value = ds.GetRasterBand(int(record.get("band", 1))) \
                    .GetNoDataValue()
                nodata = value if value is None or value == value else None
                ds = None
            except Exception:
                nodata = None
            book.data = {
                "program": NAME, "kind": "correction",
                "format": CORRECTION_FORMAT, "version": VERSION,
                "id": uuid.uuid4().hex[:12],
                "name": record.get("name") or "correction",
                "created": record.get("created") or now(),
                "operator": operator, "operators": [operator],
                "source": from_folder(record.get("source", ""),
                                      campaign.folder),
                "band": int(record.get("band", 1)),
                "working_copy": os.path.basename(working),
                "changes": changes_name(working),
                "grid": grid,
                "nodata": nodata,
                "classes": [dict(c) for c in record.get("classes") or []],
                "operations": int(record.get("operations", 0) or 0),
                "changed_m2": float(record.get("changed_m2", 0.0) or 0.0),
                "swept_m2": float(record.get("swept_m2", 0.0) or 0.0),
                "pairs": dict(record.get("pairs") or {}),
                "last_opened": record.get("last_opened") or now(),
                "migrated_from": {"campaign": relative_or_name(campaign.folder,
                                                               folder),
                                  "campaign_id": campaign.data.get("id", ""),
                                  "correction": record.get("name", ""),
                                  "when": now()},
            }
            if book.data["classes"]:
                book.data["classes_confirmed"] = record.get("last_opened") \
                    or now()
            book.save()
        # relative to the campaign when it lies inside it, as it does when
        # the correction was kept there
        record["moved_to"] = inside_folder(book.manifest_path, campaign.folder)
        # and its paths from the campaign's folder, as every other path the
        # campaign keeps: a whole path carries the name of whoever made it
        record["files"] = [inside_folder(f, campaign.folder) for f in files]
        if record.get("source"):
            record["source"] = beside_folder(record["source"],
                                             campaign.folder)
        try:
            campaign.save()
        except Exception as err:
            # A campaign folder that cannot be written. The correction opens
            # all the same, from its own manifest; the record in campaign.json
            # is offered again next time and leads to the same folder.
            log("correction '%s' has a campaign of its own in %s, but the "
                "annotation campaign could not be told: %s"
                % (book.data["name"], folder, err), loud=True)
            return book
        log("correction '%s' now has a campaign of its own in %s; the "
            "annotation campaign keeps a pointer to it"
            % (book.data["name"], folder))
        return book

    # ------------------------------------------------------------- checks
    def reconcile(self):
        """Compare manifest and disk, as Campaign.reconcile does. Returns the
        list of disagreements; none of them stops the correction opening."""
        trouble = []
        path = self.working_path
        if not path or not os.path.exists(path):
            trouble.append("the working copy %s is missing"
                           % os.path.basename(path or "?"))
        else:
            ds = None
            try:
                ds = gdal.Open(path)
            except Exception:
                ds = None
            if ds is None:
                trouble.append("the working copy %s cannot be opened"
                               % os.path.basename(path))
            else:
                ds = None
                # A copy of an earlier build still carries its "corrected"
                # band, which moves out when Correct opens it: nothing to
                # say. A copy with neither the band nor the record beside it
                # has lost which pixels a person changed.
                changes = self.changes_path
                if not (has_flag_band(path)
                        or os.path.exists(long_path(changes))):
                    trouble.append(
                        "%s is not beside the working copy, so which pixels "
                        "a person changed is not known; a new, empty one is "
                        "started when Correct opens" % os.path.basename(changes))
                # The record of the ground swept: said only when the
                # manifest names one, so a correction of an earlier build
                # opens without a word about a record it never had.
                reviewed = self.reviewed_path
                if self.data.get("reviewed") and not os.path.exists(
                        long_path(reviewed)):
                    trouble.append(
                        "%s is not beside the working copy, so which ground "
                        "the strokes swept is not known; a new, empty one is "
                        "started at the next stroke" % os.path.basename(
                            reviewed))
        source = str(self.data.get("source") or "")
        if source and not os.path.exists(source.split("|")[0]):
            trouble.append("the map it started from is no longer where it "
                           "was:\n   %s\nThe correction works all the same; "
                           "'show the original beside it' cannot." % source)
        return trouble


def _size_of(path):
    try:
        ds = gdal.Open(path)
        size = [ds.RasterXSize, ds.RasterYSize]
        ds = None
        return size
    except Exception:
        return None


def grid_of_layer(layer, size=None):
    """The grid of a thematic map, read from its layer the way Campaign.create
    reads the reference raster: so the pixel a correction measures its areas
    with is the map's own, not that of some annotation campaign."""
    e = layer.extent()
    crs = named_crs(layer.crs(), (e.center().x(), e.center().y()))
    px, py = pixel_on_the_ground(layer)
    grid = {"reference_raster": source_of(layer),
            "crs": crs_to_text(crs),
            "origin": [e.xMinimum(), e.yMaximum()],
            "pixel_crs": [layer.rasterUnitsPerPixelX(),
                          layer.rasterUnitsPerPixelY()],
            "pixel_m": [px, py]}
    if size:
        grid["size"] = list(size)
    return grid


def grid_of_copy(path, folder=None):
    """The same grid, read from the header of the working copy alone: for a
    correction that arrives with no layer, migrated or written by hand."""
    ds = open_raster(path)
    if ds is None:
        raise IOError("cannot read %s" % path)
    gt = ds.GetGeoTransform()
    size = (ds.RasterXSize, ds.RasterYSize)
    crs = crs_from_text(ds.GetProjection() or "")
    ds = None
    if crs.isValid():
        crs = named_crs(crs, (gt[0], gt[3]))
    px, py = pixel_of(crs, gt, size)
    return {"reference_raster": inside_folder(path, folder),
            "crs": crs_to_text(crs),
            "origin": [gt[0], gt[3]],
            "pixel_crs": [abs(gt[1]), abs(gt[5])],
            "pixel_m": [px, py],
            "size": list(size)}


# GDAL's colour interpretations of a band of red, green and blue
RGB_INTERPRETATIONS = {3, 4, 5}


def colour_picture(path):
    """True when the raster at path is a picture in colour: three bands or
    more, read as red, green and blue. A map of classes exported as a picture
    is one, and its classes are colours across the three bands, not codes in
    one of them.

    GDAL calls any three bands of bytes in a GeoTIFF red, green and blue, so
    a stack of a classifier's (probability, class, entropy) reads as a
    picture too. A band that says what it holds, by a name, a colour table,
    category names or an attribute table, is not a colour of a picture: a
    raster with one is a stack and is not asked about."""
    ds = None
    try:
        ds = gdal.Open(str(path).split("|")[0])
        if ds is None or ds.RasterCount < 3:
            return False
        found = set()
        for b in range(1, ds.RasterCount + 1):
            band = ds.GetRasterBand(b)
            if (band.GetDescription() or band.GetColorTable() is not None
                    or band.GetCategoryNames()
                    or band.GetDefaultRAT() is not None):
                return False
            found.add(int(band.GetColorInterpretation()))
    except Exception:
        return False
    finally:
        ds = None
    return RGB_INTERPRETATIONS <= found


# What is said about a map that should not be corrected as it is: in full by
# the panel, which asks, and in a line by the window a new correction is
# chosen in, which says it as soon as the map is picked. A map on a rotated
# grid is refused, in the words of rasters.rotated_refusal.
def colour_text(name, band, distinct, codec=None):
    """The question asked before a picture in colour is taken for a class
    map: distinct is how many values its band holds, or None."""
    held = ""
    if distinct is not None:
        held = (" Band %d alone holds %d different values, and each of them "
                "would become a class." % (band, distinct))
    lossy = ""
    if codec:
        lossy = (" It is also stored as %s, which does not keep colours "
                 "exactly, so even the colours of one class are not all the "
                 "same." % codec)
    return ("'%s' is a picture in colour: its bands are red, green and blue. "
            "A map of classes saved as a picture keeps each class as a colour "
            "across the three bands, and a correction takes its classes from "
            "the codes of one band.%s%s\n\nConvert it first to a map of one "
            "band with one code per class, as the program that made the map "
            "can usually save it, and correct that.\n\nStart on this one "
            "anyway?" % (name, held, lossy))


def lossy_text(name, codec):
    """The question asked before a class map stored with a lossy
    compression is corrected."""
    return ("'%s' is stored as %s, which does not keep values exactly: along "
            "the edges of its classes it holds values that are no class, made "
            "by the compression, and each of them will be listed as a class "
            "of its own.\n\nThe map as the program that made it wrote it, a "
            "GeoTIFF or a PNG, is the one to correct. Start on this one "
            "anyway?" % (name, codec))


def doubts_about(path):
    """What is worth knowing early about a map chosen for a new correction,
    as short lines, the empty list when nothing is: the window that chooses
    it says them as soon as it is picked, and the panel asks again, with
    buttons, when Ok is pressed."""
    name = os.path.basename(str(path).split("|")[0])
    if rotated_file(path):
        return ["'%s' has a rotated pixel grid: Correct would change other "
                "pixels than the ones painted over, so it is refused. Warp it "
                "north-up first, with nearest neighbour resampling." % name]
    out = []
    codec = lossy_codec(path)
    if colour_picture(path):
        out.append("'%s' is a picture in colour: its classes are colours "
                   "across three bands, not codes in one. Convert it to a map "
                   "of codes in one band first." % name)
    elif codec:
        out.append("'%s' is stored as %s, which does not keep values "
                   "exactly: the compression adds values that are no class "
                   "along the edges of the classes." % (name, codec))
    return out


def peek_correction(path):
    """The manifest at path, read and nothing else, or None."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        manifest_in_hand(data, os.path.dirname(os.path.abspath(path)))
        return data
    except Exception:
        return None


def manifest_on_disk(data, folder):
    """The manifest as it is written: the map the correction started from and
    the reference raster of its grid by their way from the folder, so the
    file that is zipped and sent does not carry the name of whoever made it.
    The data in hand is not touched."""
    out = dict(data)
    if out.get("source"):
        out["source"] = beside_folder(out["source"], folder)
    grid = out.get("grid")
    if isinstance(grid, dict) and grid.get("reference_raster"):
        out["grid"] = dict(grid, reference_raster=beside_folder(
            grid["reference_raster"], folder))
    return out


def manifest_in_hand(data, folder):
    """The reverse, in place: those two paths made whole from the folder the
    manifest lies in, for everything that opens the map. A whole path, which
    every manifest written before held, is left as it is, and so is a way
    that leads nowhere, which whoever reports it missing quotes."""
    if data.get("source"):
        data["source"] = from_folder(data["source"], folder)
    grid = data.get("grid")
    if isinstance(grid, dict) and grid.get("reference_raster"):
        grid["reference_raster"] = from_folder(grid["reference_raster"],
                                               folder)


def same_file(a, b):
    """Two paths to one file. normcase, as everywhere a path is compared: on
    Windows C:\\Work and C:\\work are one folder."""
    if not a or not b:
        return False
    try:
        return (os.path.normcase(os.path.abspath(str(a).split("|")[0]))
                == os.path.normcase(os.path.abspath(str(b).split("|")[0])))
    except Exception:
        return False


def has_flag_band(path):
    """True when the raster at path carries the "corrected" band that earlier
    builds added to every working copy to remember which pixels a person
    changed. A copy made now has no such band, its record is a raster of its
    own beside it, but a copy made by an earlier build still has it until
    Correct opens it and moves it out. A raster of that one band alone is
    the record itself, not a copy."""
    ds = None
    try:
        ds = gdal.Open(str(path).split("|")[0])
        if ds is None or ds.RasterCount < 2:
            return False
        return any((ds.GetRasterBand(b).GetDescription() or "").lower()
                   == FLAG_BAND_NAME for b in range(1, ds.RasterCount + 1))
    except Exception:
        return False
    finally:
        ds = None


def changes_name(copy):
    """The file name of the record of changed pixels of this working copy:
    <map>_corrected_changes.tif beside <map>_corrected.tif."""
    stem = os.path.splitext(os.path.basename(str(copy).split("|")[0]))[0]
    return "%s%s.tif" % (stem, CHANGES_SUFFIX)


def changes_of(copy):
    """The record of changed pixels beside this working copy."""
    path = str(copy).split("|")[0]
    return os.path.join(os.path.dirname(path), changes_name(path))


def copy_in_folder(folder, name):
    """Where the working copy the manifest names lies: in the folder of the
    correction, whatever the manifest says. Only the file name is taken, so a
    record that climbs out of the folder with "..", or names a path on another
    drive, cannot send Correct to write the map and the style of somebody
    else's file. Correct writes the name alone, so a record it wrote is
    unchanged."""
    name = str(name or "").strip().replace("\\", "/").rstrip("/")
    return os.path.join(folder, name.rsplit("/", 1)[-1])


def changes_path_of(record, copy):
    """The record of changed pixels of a correction: the one its manifest
    names, beside the copy, or the one every copy is given when it names
    none, as a manifest of an earlier build does not."""
    name = str((record or {}).get("changes") or "").strip()
    if name:
        return os.path.join(os.path.dirname(str(copy).split("|")[0]),
                            os.path.basename(name))
    return changes_of(copy)


# The record of the ground the strokes swept: a byte band, 1 where a stroke
# of Correct went over the pixel, shown in blue when opened on its own.
REVIEWED_COLOUR = (0, 170, 255, 255)


def reviewed_name(copy):
    """The file name of the record of the ground swept of this working copy:
    <map>_corrected_reviewed.tif beside <map>_corrected.tif."""
    stem = os.path.splitext(os.path.basename(str(copy).split("|")[0]))[0]
    return "%s%s.tif" % (stem, REVIEWED_SUFFIX)


def reviewed_of(copy):
    """The record of the ground swept beside this working copy."""
    path = str(copy).split("|")[0]
    return os.path.join(os.path.dirname(path), reviewed_name(path))


def reviewed_path_of(record, copy):
    """The record of the ground swept of a correction: the one its manifest
    names, beside the copy, or the one every copy is given when it names
    none."""
    name = str((record or {}).get("reviewed") or "").strip()
    if name:
        return os.path.join(os.path.dirname(str(copy).split("|")[0]),
                            os.path.basename(name))
    return reviewed_of(copy)


def build_reviewed(copy, path):
    """The record of the ground swept, empty, beside the copy: the record of
    changes with other words on it (rasters.build_changes)."""
    return build_changes(copy, path, name=REVIEWED_BAND_NAME,
                         meaning=REVIEWED_MEANING, colour=REVIEWED_COLOUR)


def is_reviewed_raster(path):
    """True when path is the record of the ground swept of a working copy:
    one band, named as that record's band is named."""
    ds = None
    try:
        ds = gdal.Open(str(path).split("|")[0])
        if ds is None or ds.RasterCount != 1:
            return False
        return ((ds.GetRasterBand(1).GetDescription() or "").lower()
                == REVIEWED_BAND_NAME)
    except Exception:
        return False
    finally:
        ds = None


def is_changes_raster(path):
    """True when path is the record of changed pixels of a working copy: one
    band, named as that record's band is named."""
    ds = None
    try:
        ds = gdal.Open(str(path).split("|")[0])
        if ds is None or ds.RasterCount != 1:
            return False
        return ((ds.GetRasterBand(1).GetDescription() or "").lower()
                == FLAG_BAND_NAME)
    except Exception:
        return False
    finally:
        ds = None


def copy_of_manifest(manifest_path, data=None):
    """The working copy a correction.json names, read as CorrectionCampaign
    reads it, or "" when the manifest cannot be read."""
    if data is None:
        data = peek_correction(manifest_path)
    if not data:
        return ""
    book = CorrectionCampaign(os.path.dirname(manifest_path))
    book.data = data
    return book.working_path


def why_a_working_copy(source, campaign=None):
    """Why this map looks like the working copy of a correction, in words, or
    None when it does not. Correcting a correction would split its history
    in two.

    In order of trust: the "corrected" band inside the file, which a copy of
    an earlier build carries; the record of changed pixels beside it, which
    every copy made now has; the name every working copy is given; a
    correction.json beside it that names this very file as its copy; the
    folder an annotation campaign kept its corrections in. And the record of
    changed pixels itself, chosen as a map: it is no thematic map.

    A correction.json beside the map is not enough on its own. A correction
    made in the folder of the map it corrects writes its manifest beside the
    original, and the original then looked like a copy and could never be
    corrected again: the manifest has to name this file as its copy."""
    if is_changes_raster(source):
        return ("it is the record of which pixels a person changed in a "
                "working copy, not a map")
    if is_reviewed_raster(source):
        return ("it is the record of which pixels the strokes of Correct went "
                "over in a working copy, not a map")
    if has_flag_band(source):
        return ("it carries the '%s' band that every working copy of an "
                "earlier build has" % FLAG_BAND_NAME)
    stem = os.path.splitext(os.path.basename(source))[0]
    if is_changes_raster(changes_of(source)):
        return ("%s beside it records which pixels a person changed in it"
                % changes_name(source))
    if is_reviewed_raster(reviewed_of(source)):
        return ("%s beside it records which pixels the strokes went over in "
                "it" % reviewed_name(source))
    if stem.endswith("_corrected"):
        return "its name ends in _corrected, the name every working copy is given"
    beside = os.path.join(os.path.dirname(source), CORRECTION_MANIFEST)
    if os.path.exists(beside) and same_file(copy_of_manifest(beside), source):
        return ("the %s beside it names it as its working copy"
                % CORRECTION_MANIFEST)
    if campaign is not None:
        inside = os.path.join(campaign.folder, "corrections")
        here = os.path.normcase(os.path.abspath(source))
        mine = os.path.normcase(os.path.abspath(inside))
        if here.startswith(mine + os.sep):
            return ("it is inside the corrections folder of the annotation "
                    "campaign")
    return None


def made_by_a_correction(source, campaign=None):
    """True when this map is already the working copy of a correction."""
    return why_a_working_copy(source, campaign) is not None


def owner_of_copy(source, campaign=None):
    """The correction whose working copy this map is, as (kind, value, name):
    ("open", its correction.json, name) or ("legacy", the name of a record of
    the annotation campaign, name). None when no owner is found.

    Looked for where a correction can be: its correction.json beside the
    copy, the corrections opened lately on this machine, and the records of
    the annotation campaign that is open."""
    beside = os.path.join(os.path.dirname(source), CORRECTION_MANIFEST)
    for manifest in [beside] + recent_corrections():
        if not os.path.exists(manifest):
            continue
        data = peek_correction(manifest)
        if data and same_file(copy_of_manifest(manifest, data), source):
            return "open", manifest, data.get("name") or "?"
    if campaign is not None:
        for record in campaign.data.get("corrections", []):
            files = record.get("files") or [""]
            if not same_file(from_folder(files[0], campaign.folder), source):
                continue
            moved = from_folder(record.get("moved_to") or "", campaign.folder)
            if moved and os.path.exists(moved):
                data = peek_correction(moved) or {}
                return ("open", moved,
                        data.get("name") or record.get("name") or "?")
            return ("legacy", str(record.get("name", "")),
                    record.get("name") or "?")
    return None


def corrections_of(source, campaign=None):
    """The corrections already made on this map that can still be opened,
    newest first, as (kind, correction.json or record name, name).

    Known means: opened lately on this machine, a correction.json in the
    map's own folder, or a record of the annotation campaign that is open.
    One whose working copy is gone is left out: there is nothing to open."""
    out, seen = [], set()

    def add(manifest):
        key = os.path.normcase(os.path.abspath(manifest))
        if key in seen or not os.path.exists(manifest):
            return
        data = peek_correction(manifest)
        if not data or not same_file(data.get("source"), source):
            return
        copy = copy_of_manifest(manifest, data)
        if not copy or not os.path.exists(copy):
            return
        seen.add(key)
        out.append(("open", manifest, data.get("name") or "?"))

    for manifest in recent_corrections():
        add(manifest)
    add(os.path.join(os.path.dirname(source), CORRECTION_MANIFEST))
    if campaign is not None:
        for record in campaign.data.get("corrections", []):
            if record.get("moved_to"):
                add(from_folder(record["moved_to"], campaign.folder))
                continue
            files = [from_folder(f, campaign.folder)
                     for f in record.get("files") or [""]]
            if same_file(from_folder(record.get("source"), campaign.folder),
                         source) and os.path.exists(files[0]):
                out.append(("legacy", str(record.get("name", "")),
                            record.get("name") or "?"))
    return out


def copy_name(source):
    """The file name every working copy of this map is given."""
    stem = os.path.splitext(os.path.basename(str(source).split("|")[0]))[0]
    return "%s_corrected.tif" % stem


def beside_the_copy(copy):
    """The names of the files a working copy has beside it, the copy first:
    what is set aside with it."""
    name = os.path.basename(str(copy).split("|")[0])
    changes = changes_name(name)
    reviewed = reviewed_name(name)
    return [name, name + ".aux.xml", name + ".ovr",
            os.path.basename(style_of(name)), changes, changes + ".aux.xml",
            name + ".vat.dbf", name + ".vat.cpg", reviewed,
            reviewed + ".aux.xml"]


def dress_copy(copy, band_no, classes, source=None, ds=None, say=False):
    """The classes of the correction written where other programs read them:
    the .qml QGIS opens the corrected map with, the colour table and
    category names of its class band, and its attribute table and
    .tif.vat.dbf when the map it corrects has them, with the pixel counts
    of the corrected map. Done whenever the classes change and
    every time Correct opens and closes, so the two never fall behind them.

    The .qml follows the one the corrected map already has, when it has
    one: a user who restyled it in QGIS and kept that with Save as Default
    keeps the opacity, the resampling and everything else they set, and
    only the renderer, its band and its classes are made the correction's.
    The first time, it follows the .qml of the map it corrects, when that
    map has one. ds is an open handle on the copy, if the caller has one
    (see dress_class_band). Never raises: the corrected map is whole
    without either, and what could not be written is said in the log."""
    classes = [c for c in classes or [] if "code" in c]
    if not copy or not classes:
        return
    if has_flag_band(copy):
        # A copy of an earlier build is left exactly as it is until its band
        # has moved out (bring_up_to_date); it is dressed after that.
        return
    own = style_of(copy)
    template = style_of(source) if source else None
    if template and same_file(template, own):
        template = None
    try:
        used = write_style(own, band_no, classes, [own, template])
        if say:
            log("%s written: QGIS opens the corrected map with its %d "
                "classes%s" % (os.path.basename(own), len(classes),
                               "" if not used
                               else ", keeping the rest of the style it had"
                               if same_file(used, own)
                               else ", the way %s says"
                               % os.path.basename(used)))
    except Exception as err:
        log("cannot write the style of the corrected map, %s: %s"
            % (os.path.basename(own), err), loud=True)
    said = dress_class_band(copy, band_no, classes, ds=ds, template=source)
    # Whatever could not be written is said, whichever part of it it was.
    if say or said.startswith("no ") or "; no " in said:
        log(said)


def bring_up_to_date(copy, band_no, record=None, book=None):
    """A working copy made by an earlier build, given the shape of the map it
    corrects: its "corrected" band moved out to <copy>_changes.tif and the
    copy rewritten with the bands of the original only (strip_flag_band
    says how nothing can be lost on the way). The record, when given, is
    told where the changes are and, if the class band moved, which band it
    is now; book saves it. One line in the log.

    The record is saved before the new copy takes the old one's place, not
    after: stopped between the two, a manifest saved after would still name
    the class band of the old copy for a copy whose bands had moved down by
    one, and every stroke would land in the wrong band. Saved before, it
    keeps the band the old copy had in "band_before", which is the one used
    if the old copy turns out to be still there; a rename that fails puts
    the record back as it was.

    Returns None when the copy is already in shape, else what was done, with
    "released", the number of layers of the project that had to let go of
    the file. Raises, with the copy as it was, when it cannot be done: a
    layer of another program holding the file is the usual reason."""
    settled = settle_held_aux(copy)
    if settled:
        log(settled)
    if not has_flag_band(copy):
        return None
    pending = (record or {}).get("changes_moved_out")
    if isinstance(pending, dict) and pending.get("band_before"):
        # Stopped after the manifest was told and before the copy was
        # replaced: the copy is the old one, and so is its class band.
        band_no = int(pending["band_before"])
    changes = changes_path_of(record, copy)
    released = 0
    for path in (copy, changes):
        let_go = release_file(path)
        if let_go:
            released += let_go
            log("released %d layer%s that held %s open"
                % (let_go, "" if let_go == 1 else "s",
                   os.path.basename(path)))
    keys = ("changes", "band", "changes_moved_out")
    before = ({k: record[k] for k in keys if k in record}
              if record is not None else {})
    told = []

    def tell(done):
        if record is None:
            return
        record["changes"] = os.path.basename(changes)
        record["band"] = done["band"]
        record["changes_moved_out"] = {"when": now(),
                                       "pixels": done["pixels"],
                                       "from_band": done["dropped"],
                                       "band_before": int(band_no or 1),
                                       "bands": done["bands"]}
        told.append(True)
        if book is not None:
            book.save()

    try:
        done = strip_flag_band(copy, changes, band_no, before_swap=tell)
    except Exception:
        if told:
            for k in keys:
                record.pop(k, None)
            record.update(before)
            if book is not None:
                try:
                    book.save()
                except Exception as err:
                    log("cannot put the manifest back: %s" % err, loud=True)
        raise
    if done is None:
        return None
    done["released"] = released
    log("working copy %s brought to the bands of the map it corrects: its "
        "'%s' band, %d pixel%s a person changed, now in %s, and the copy has "
        "the %d bands of the original"
        % (os.path.basename(copy), FLAG_BAND_NAME, done["pixels"],
           "" if done["pixels"] == 1 else "s", os.path.basename(changes),
           done["bands"]))
    return done


def undone_of(record):
    """What the manifest says was undone, as numbers: {"operations",
    "changed_m2", "swept_m2", "pairs"}, all zero for a correction that never
    had an Undo (it has no "undone" at all) and for anything unreadable.

    operations, changed_m2, swept_m2 and pairs of the manifest, like the rows
    of operations.csv, count every stroke that was written, an undone one
    included. This is the part of them that was undone, so that the net is
    their difference."""
    out = {"operations": 0, "changed_m2": 0.0, "swept_m2": 0.0, "pairs": {}}
    held = (record or {}).get("undone")
    if not isinstance(held, dict):
        return out
    try:
        out["operations"] = max(0, int(held.get("operations") or 0))
        out["changed_m2"] = max(0.0, float(held.get("changed_m2") or 0.0))
        out["swept_m2"] = max(0.0, float(held.get("swept_m2") or 0.0))
    except (TypeError, ValueError):
        return {"operations": 0, "changed_m2": 0.0, "swept_m2": 0.0,
                "pairs": {}}
    pairs = held.get("pairs")
    for pair, counted in (pairs.items() if isinstance(pairs, dict) else []):
        try:
            out["pairs"][str(pair)] = [int(counted[0]), float(counted[1])]
        except (TypeError, ValueError, IndexError):
            continue
    return out


def tally_operations(path):
    """The counters of a manifest, rebuilt from operations.csv: what a
    correction whose manifest was lost had done. Zeros when there is no log."""
    out = {"operations": 0, "changed_m2": 0.0, "swept_m2": 0.0, "pairs": {}}
    if not os.path.exists(path):
        return out
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in map(csv_untext_row, csv.DictReader(f)):
                try:
                    moved = float(row.get("changed_m2") or 0.0)
                    swept = float(row.get("swept_m2") or 0.0)
                except ValueError:
                    continue
                out["operations"] += 1
                out["changed_m2"] += moved
                out["swept_m2"] += swept
                pair = "%s -> %s" % (row.get("only") or "every class",
                                     row.get("into") or "?")
                n, area = out["pairs"].get(pair, [0, 0.0])
                out["pairs"][pair] = [n + 1, round(area + moved, 3)]
    except Exception as err:
        log("cannot read %s: %s" % (path, err))
    out["changed_m2"] = round(out["changed_m2"], 3)
    out["swept_m2"] = round(out["swept_m2"], 3)
    return out


def set_aside_leftovers(folder, names):
    """Move these files of the folder into a folder of their own, named
    set_aside_ and the time, instead of deleting them. Returns that folder,
    or None when none of them was there.

    A layer of the project that holds one of them open is let go first,
    because Windows refuses to move an open file. One that still cannot be
    moved raises, and whatever had been moved is put back: the folder is
    left as it was, never half set aside."""
    present = [n for n in names if os.path.exists(os.path.join(folder, n))]
    if not present:
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    spare, k = os.path.join(folder, "set_aside_" + stamp), 2
    while os.path.exists(spare):
        spare = os.path.join(folder, "set_aside_%s_%d" % (stamp, k))
        k += 1
    os.makedirs(spare)
    moved = []
    for n in present:
        path = os.path.join(folder, n)
        try:
            released = release_file(path)
            if released:
                log("released %d layer%s that held %s open"
                    % (released, "" if released == 1 else "s", n))
            os.replace(path, os.path.join(spare, n))
        except OSError as err:
            for done in moved:
                try:
                    os.replace(os.path.join(spare, done),
                               os.path.join(folder, done))
                except OSError:
                    pass
            try:
                os.rmdir(spare)
            except OSError:
                pass
            # Said as it is: a file held open is the usual reason, but a path
            # too long for Windows or a folder that cannot be written to end
            # here too.
            raise IOError(
                "%s cannot be moved into %s.\n\n%s\n\nIf another program "
                "holds it open, close it and try again. Nothing was moved."
                % (n, os.path.basename(spare), err))
        moved.append(n)
    log("set aside, not deleted: %s, now in %s" % (", ".join(moved), spare))
    return spare


#  The corrections opened lately, remembered by QGIS on this machine
# =====================================================================
RECENT_KEY = SETTINGS_ROOT + "/corrections/recent"


def recent_corrections():
    """The manifests opened lately, newest first, those gone left out."""
    out = []
    for path in read_setting(RECENT_KEY, [], list):
        if path and os.path.exists(path) and path not in out:
            out.append(path)
    return out[:RECENT_MAX]


def remember_correction(path):
    kept = [p for p in recent_corrections()
            if os.path.normcase(p) != os.path.normcase(path)]
    write_setting(RECENT_KEY, ([path] + kept)[:RECENT_MAX])


def forget_correction(path):
    write_setting(RECENT_KEY, [p for p in recent_corrections()
                               if os.path.normcase(p) != os.path.normcase(path)])
