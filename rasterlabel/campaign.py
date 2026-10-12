"""rasterlabel.campaign

The folder, the manifest, the package.
"""
import json
import os
import uuid

from datetime import datetime, timezone
from osgeo import gdal, ogr, osr
from qgis.core import QgsProject

from .constants import (CLOSED_SHARE, DESIGN_FIELDS, JOURNAL_NAME,
                        JOURNAL_VERSION, MAX_CLASS_CODE, IGNORE_CODE, NAME,
                        OPERATOR_BLANK, TABLES, VERSION)
from .naming import beside_folder, from_folder, now, tidy
from .project import (PLACEHOLDER_SRS, crs_from_text, crs_label, crs_to_text,
                      crs_wkt, named_crs, pixel_on_the_ground)
from .errors import log, own_hands


#  The campaign
# =====================================================================
class Campaign(object):
    """A folder, a manifest, a GeoPackage. The manifest is the truth."""

    MANIFEST = "campaign.json"
    PACKAGE = "annotation.gpkg"

    def __init__(self, folder):
        self.folder = folder
        self.data = {}

    @property
    def manifest_path(self):
        return os.path.join(self.folder, self.MANIFEST)

    @property
    def package_path(self):
        return os.path.join(self.folder, self.PACKAGE)

    @property
    def group_name(self):
        return "%s: %s" % (NAME, self.data["name"])

    @property
    def stem(self):
        """The campaign's name, made safe to put in front of other names.

        Spaces and accents are the ones that hurt: a layer called
        'sito nord 2026 polygons' reads as four words in the Layers panel and
        as a broken path the day somebody uses the layer name to make a file.
        tidy() is the same one the cutouts use, so a campaign is spelled the
        same way everywhere."""
        return tidy(self.data.get("name") or "campaign", "campaign")

    def layer_name(self, table):
        """What a table is called once it is in QGIS.

        Campaign first, table after, joined by an underscore: aragona_2025 and
        its polygons become aragona_2025_polygons. The second half is the name
        of the table inside the GeoPackage, letter for letter, so that what is
        read in the Layers panel says where the thing actually lives. With two
        campaigns open at once, two layers both called polygons would be the
        state in which work gets drawn into the wrong one."""
        return "%s_%s" % (self.stem, table)

    # ------------------------------------------------------------- disk
    @classmethod
    def open(cls, folder):
        c = cls(folder)
        with open(c.manifest_path, encoding="utf-8") as f:
            c.data = json.load(f)
        # A campaign made by an older version has no table for the objects.
        # Adding the missing one costs nothing and touches none of the others.
        #
        # But prepare_package also CREATES the package when there is none, and
        # that is not a kindness here: a campaign whose annotation.gpkg has been
        # deleted, moved by a sync client or left on a drive that is not plugged
        # in would get a brand new empty one, reconcile would then find nothing
        # wrong, and the loss of every polygon would look exactly like a
        # campaign nobody had drawn in yet. So it is noticed first and said
        # loudly.
        was_there = os.path.exists(c.package_path)
        if was_there:
            # first, so that a table added below is made in that system too
            c.name_the_system()
        try:
            grid = c.data.get("grid") or {}
            missing = c.prepare_package(crs_from_text(grid.get("crs")))
            if missing:
                log("added to the package: %s" % ", ".join(missing))
        except Exception as err:
            log("cannot check the tables of the package: %s" % err)
        if not was_there:
            log("the GeoPackage of this campaign was not there and an empty one "
                "has been made: %s. If it held work, it has been moved or "
                "deleted, and the empty campaign you are looking at is not the "
                "one you drew. Close it without saving and find the file before "
                "doing anything else." % c.package_path, loud=True)
        return c

    @classmethod
    def create(cls, folder, name, with_tiles, raster, classes, operator):
        os.makedirs(folder, exist_ok=True)
        c = cls(folder)
        px, py = pixel_on_the_ground(raster)
        e = raster.extent()
        # The system under its EPSG name when it has one, so that the manifest
        # and the layers say EPSG:4326 about a WGS 84 that GDAL handed over
        # bound to itself, instead of "" and a nameless copy.
        crs = named_crs(raster.crs(), (e.center().x(), e.center().y()))
        c.data = {
            "program": NAME,
            "version": VERSION,
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "created": now(),
            "operator": operator,
            # Who works on it. The single "operator" field stays for the files
            # already written and for anyone reading the manifest from outside;
            # the list is the one the panel uses, because a campaign with two
            # readings of the same cell has two people in it, not one.
            "operators": [operator],
            "with_tiles": bool(with_tiles),
            "classes": classes,
            "grid": {
                "reference_raster": beside_folder(raster.source(), folder),
                "crs": crs_to_text(crs),
                "origin": [e.xMinimum(), e.yMaximum()],
                "pixel_crs": [raster.rasterUnitsPerPixelX(),
                              raster.rasterUnitsPerPixelY()],
                "pixel_m": [px, py],
            },
            "layers": [],
            "tiles": [],
            "cutouts": [],
            "corrections": [],
        }
        # A package left behind by a campaign whose manifest is gone would be
        # adopted silently, geometries included. A new campaign starts clean.
        if os.path.exists(c.package_path):
            release_file(c.package_path)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            spare = "%s.orphan-%s" % (c.package_path, stamp)
            try:
                os.replace(c.package_path, spare)
                move_sidecars(c.package_path, spare)
                log("a package with no manifest was set aside as %s"
                    % os.path.basename(spare))
            except OSError as err:
                raise IOError(
                    "There is an %s in that folder left over from a previous "
                    "campaign, and it cannot be moved aside:\n\n%s\n\nClose "
                    "whatever is holding it open and try again."
                    % (cls.PACKAGE, err))
        c.prepare_package(crs)
        c.save()
        return c

    def name_the_system(self):
        """Write into the manifest the system the campaign is in, when the
        manifest names none and the tables or the reference raster do.

        Files written by earlier builds have "" for any system without an EPSG
        code, the WGS 84 bound to itself of an ordinary orthomosaic among them.
        "" is also what a photograph with no coordinate system writes, so
        without this Check, the panel and the geometry would take the campaign
        for one. The tables are asked first, unless they hold only the
        GeoPackage's stand-in for no system, and then the reference raster,
        read from its header. A campaign on a picture has neither, and is left
        alone."""
        grid = self.data.get("grid")
        if not isinstance(grid, dict) or grid.get("crs") or "crs" not in grid:
            return None
        wkt, source = "", ""
        try:
            ds = ogr.Open(self.package_path)
            if ds is not None:
                for i in range(ds.GetLayerCount()):
                    srs = ds.GetLayerByIndex(i).GetSpatialRef()
                    if srs is not None and (srs.GetName() or "") not in PLACEHOLDER_SRS:
                        wkt, source = srs.ExportToWkt(), "the tables are"
                        break
            ds = None
        except Exception as err:
            log("cannot read the system of the tables: %s" % err)
        ref = str(from_folder(grid.get("reference_raster") or "",
                              self.folder)).split("|")[0]
        if not wkt and ref and os.path.isfile(ref):
            try:
                ds = gdal.Open(ref)          # read only: the header is enough
                srs = ds.GetSpatialRef() if ds is not None else None
                if srs is not None:
                    wkt, source = srs.ExportToWkt(["FORMAT=WKT2_2019"]), \
                        "the reference raster is"
                ds = None
            except Exception as err:
                log("cannot read the system of the reference raster: %s" % err)
        crs = crs_from_text(wkt)
        if not wkt or not crs.isValid():
            return None
        crs = named_crs(crs, tuple(grid.get("origin") or (0.0, 0.0)))
        grid["crs"] = crs_to_text(crs)
        try:
            self.save()
        except Exception as err:
            log("cannot write the system into the manifest: %s" % err)
        log("the manifest named no coordinate system and %s in %s: "
            "written into the manifest" % (source, crs_label(crs)))
        return crs

    def save(self):
        self.data["modified"] = now()
        tmp = self.manifest_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.manifest_path)

    def prepare_package(self, crs):
        """Create the three tables if they are not there. Never touch existing ones."""
        srs = spatial_reference(crs)
        exists = os.path.exists(self.package_path)
        drv = ogr.GetDriverByName("GPKG")
        ds = drv.Open(self.package_path, 1) if exists \
            else drv.CreateDataSource(self.package_path)
        if ds is None:
            raise IOError("cannot open or create %s" % self.package_path)
        present = {ds.GetLayerByIndex(i).GetName() for i in range(ds.GetLayerCount())}
        added = []
        for table, kind, fields in TABLES:
            if table in present:
                # A campaign made by an older version may be missing a column
                # rather than a whole table. Adding one is harmless and keeps
                # the work readable by both versions.
                lyr = ds.GetLayerByName(table)
                have = {lyr.GetLayerDefn().GetFieldDefn(i).GetName().lower()
                        for i in range(lyr.GetLayerDefn().GetFieldCount())}
                for fname, ftype in fields:
                    if fname.lower() in have:
                        continue
                    d = ogr.FieldDefn(fname, ftype)
                    if ftype == ogr.OFTString:
                        d.SetWidth(80)
                    if lyr.CreateField(d) == 0:
                        added.append("%s.%s" % (table, fname))
                continue
            lyr = ds.CreateLayer(table, srs, kind, ["GEOMETRY_NAME=geom"])
            for fname, ftype in fields:
                d = ogr.FieldDefn(fname, ftype)
                if ftype == ogr.OFTString:
                    d.SetWidth(80)
                lyr.CreateField(d)
            added.append(table)
        ds = None
        return added

    # ------------------------------------------------------------- legend
    def active_classes(self):
        return [c for c in self.data["classes"] if not c.get("retired")]

    def next_code(self):
        """The code the next class would get: one past the highest ever
        handed out, retired classes included, so that no number is ever given
        to two classes. It can be past MAX_CLASS_CODE, and whoever adds a
        class refuses it then, with no_room_for_class()."""
        return max([c["code"] for c in self.data["classes"]] or [0]) + 1

    # ------------------------------------------------------------- checks
    def reconcile(self):
        """Compare manifest and disk. Returns the list of disagreements."""
        trouble = []
        if not os.path.exists(self.package_path):
            trouble.append("the GeoPackage %s is missing" % self.PACKAGE)
        grid = self.data.get("grid") or {}
        # "crs" written and empty is a raster with no coordinate system, which
        # is allowed; only a grid with no "crs" at all is not one of ours.
        if not isinstance(grid, dict) or "crs" not in grid:
            trouble.append("the manifest has no grid: this may not be a %s "
                           "campaign, or it was edited by hand" % NAME)
        ref = from_folder(grid.get("reference_raster"), self.folder)
        if ref and not os.path.exists(ref.split("|")[0]):
            trouble.append("the reference raster is no longer where it was:\n   %s" % ref)
        for key, label in (("cutouts", "cutout"), ("corrections", "correction")):
            for item in self.data.get(key, []):
                # A correction that has a campaign of its own answers
                # for its files there; Check notes it if that folder is gone.
                if item.get("moved_to"):
                    continue
                for f in item.get("files", []):
                    if not os.path.exists(from_folder(f, self.folder)):
                        trouble.append("%s '%s': %s is missing"
                                       % (label, item.get("name", item.get("id")),
                                          os.path.basename(f)))
        return trouble


def spatial_reference(crs):
    """The osr twin of a QGIS system, for the tables of the GeoPackage.

    It was ImportFromWkt(toWkt()) and nothing else, and a system that failed
    to come through that one door went into the GeoPackage as no system at
    all: the tables were given the stand-in for "undefined", silently, while
    the raster under them was a perfectly good WGS 84. The code is tried
    first, then each way QGIS can write the system down. An empty one comes
    back only for a raster that really has none, and is said otherwise."""
    srs = osr.SpatialReference()
    if crs is None or not crs.isValid():
        return srs
    tries = []
    for make in (crs.authid, lambda: crs_wkt(crs), crs.toWkt, crs.toProj):
        try:
            tries.append(make())
        except Exception:
            pass
    for text in tries:
        if not text:
            continue
        try:
            candidate = osr.SpatialReference()
            if candidate.SetFromUserInput(text) == 0:
                return candidate
        except Exception:
            continue
    log("the coordinate system %s could not be handed to the GeoPackage: the "
        "tables are made without one" % crs_label(crs), loud=True)
    return srs


def describe_existing(folder):
    """What a folder already holds, so the warning can be concrete instead of
    generic. Returns (name, counts) or (None, {}) if there is nothing."""
    manifest = os.path.join(folder, Campaign.MANIFEST)
    if not os.path.exists(manifest):
        return None, {}
    try:
        with open(manifest, encoding="utf-8") as f:
            name = json.load(f).get("name", "unnamed")
    except Exception:
        name = "unreadable manifest"
    counts = {}
    package = os.path.join(folder, Campaign.PACKAGE)
    if os.path.exists(package):
        try:
            ds = ogr.Open(package)
            if ds is not None:
                for i in range(ds.GetLayerCount()):
                    lyr = ds.GetLayerByIndex(i)
                    counts[lyr.GetName()] = lyr.GetFeatureCount()
                ds = None
        except Exception:
            pass
    return name, counts


def release_file(path):
    """Drop from the project every layer that reads this file.

    Windows refuses to rename a file that a process still holds open, and a
    GeoPackage loaded in the project is held open. Any layer pointing at it has
    to go before the file can be moved."""
    try:
        target = os.path.normcase(os.path.abspath(path))
    except Exception:
        return 0
    ids = []
    for lyr in QgsProject.instance().mapLayers().values():
        try:
            source = os.path.normcase(os.path.abspath(lyr.source().split("|")[0]))
        except Exception:
            continue
        if source == target:
            try:
                if lyr.isEditable():
                    with own_hands():
                        lyr.rollBack()
            except Exception:
                pass
            ids.append(lyr.id())
    if ids:
        with own_hands():
            QgsProject.instance().removeMapLayers(ids)
    return len(ids)


def move_sidecars(path, target, done=None):
    """The files SQLite keeps beside a database, moved to follow it to target.

    -wal holds what has not yet been folded into the file, -shm the memory
    shared between connections, -journal the old pages of a transaction. All
    are named after the database. Left behind, they sit beside whatever is
    written under the old name next, and SQLite replays the old pages into
    it; and the copy that was set aside loses the polygons the -wal still
    held. They keep the name the database is given, which is the name SQLite
    looks for if the copy is ever renamed back. Returns the names moved.

    done, when given, is a list that each move is added to, as (from, to), the
    moment it is made, so that a caller whose later step fails can undo them."""
    moved = []
    for tail in ("-wal", "-shm", "-journal"):
        extra = path + tail
        if not os.path.exists(extra):
            continue
        try:
            os.replace(extra, target + tail)
        except OSError as err:
            raise IOError(
                "%s cannot be moved aside because something still holds it "
                "open.\n\n%s\n\nClose any other program using it, or remove "
                "from the project every layer that reads it, and try again."
                % (os.path.basename(extra), err))
        moved.append(os.path.basename(target + tail))
        if done is not None:
            done.append((extra, target + tail))
    return moved


def set_aside(folder):
    """Move the existing campaign out of the way instead of deleting it, so an
    overwrite is a mistake that can still be undone by hand.

    All or nothing. The package goes first, because it is the file that gets
    held open (by another program, a sync client, a layer of another QGIS) and
    so the one that refuses; the manifest goes last. If any move fails, the
    ones already made are undone, so a folder that could not be set aside is
    still a campaign that opens, not one left with an annotation.gpkg and
    a campaign.json.replaced-<stamp> and no campaign.json to open it by."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    moved = []
    done = []                   # (where it was, where it went), to undo
    freed = 0
    for filename in (Campaign.PACKAGE, Campaign.MANIFEST):
        path = os.path.join(folder, filename)
        if not os.path.exists(path):
            continue
        released = release_file(path)
        freed += released
        if released:
            log("released %d layers that were holding %s open"
                % (released, filename))
        target = "%s.replaced-%s" % (path, stamp)
        try:
            try:
                os.replace(path, target)
            except OSError as err:
                raise IOError(
                    "%s cannot be moved aside because something still holds "
                    "it open.\n\n%s\n\nClose any other program using it, or "
                    "remove from the project every layer that reads it, and "
                    "try again." % (filename, err))
            done.append((path, target))
            moved.append(os.path.basename(target))
            if filename == Campaign.PACKAGE:
                moved += move_sidecars(path, target, done)
        except IOError as err:
            stuck = []
            for was, went in reversed(done):
                try:
                    os.replace(went, was)
                except OSError as back:
                    stuck.append("%s is now %s (%s)" % (
                        os.path.basename(was), os.path.basename(went), back))
            if stuck:
                said = ("Some of it could not be put back, so rename these by "
                        "hand to open the campaign again:\n- %s"
                        % "\n- ".join(stuck))
            else:
                said = ("Nothing was changed: the previous campaign is still "
                        "in the folder and opens as before.")
            if freed:
                said += (" The layers that read it were taken out of the "
                         "project; Open campaign brings them back.")
            raise IOError("%s\n\n%s" % (err, said))
    return moved


def no_room_for_class():
    """What is said when a campaign has handed out its last class code."""
    return ("A campaign has %d class codes, 1 to %d, and every one of them "
            "has been handed out. Retired classes keep theirs, so that "
            "nothing already exported changes meaning.\n\nThe mask is one "
            "byte a pixel, 0 is \"nobody painted it\" and %d is kept for "
            "\"ignore\", so there is no code left to give a new class. "
            "Rename a class you no longer use instead."
            % (MAX_CLASS_CODE, MAX_CLASS_CODE, IGNORE_CODE))


#  Readings
# =====================================================================
# A reading is one operator's work in one pass: the unit the frames are closed
# by, the unit Check measures, and the unit an export can be narrowed to. Every
# place that needs to know which reading a mark belongs to reads it through the
# two functions below, so that a polygon saved as "Massi" with no pass and one
# saved as "MASSI" in pass 1 are the same reading everywhere, and no two places
# can disagree about it.
READING_TABLES = ("polygons", "lines", "points", "boxes")


def operator_word(value):
    """The operator of a mark, in its written form: trimmed, upper cased, and
    OPERATOR_BLANK when the field is empty or missing."""
    if isinstance(value, str):
        text = value
    else:
        text = "" if not value else str(value)
    return text.strip().upper() or OPERATOR_BLANK


def pass_number(value):
    """The pass of a mark. Empty, zero or missing is the first pass, which is
    what every build before the field existed drew in."""
    try:
        return int(value or 1)
    except (TypeError, ValueError):
        return 1


def reading_label(reading):
    return "%s, pass %d" % (reading[0], reading[1])


def readings_in(package, tables=None):
    """Every reading the package holds, as {(operator, pass): marks}.

    Read straight from the file, attributes only, so that what the export
    windows offer is what the export will read. tables narrows the count to
    these tables, for whoever needs to know who painted rather than who drew
    anything at all."""
    counts = {}
    try:
        ds = ogr.Open(package)
    except Exception as err:
        log("cannot read the readings of %s: %s"
            % (os.path.basename(package), err))
        return counts
    if ds is None:
        return counts
    for table in (tables or READING_TABLES):
        lyr = ds.GetLayerByName(table)
        if lyr is None:
            continue
        defn = lyr.GetLayerDefn()
        who = defn.GetFieldIndex("operator")
        when = defn.GetFieldIndex("pass_no")
        # Counted by SQLite, one row per name and pass as they are written,
        # and only then put into their written form. Walked feature by
        # feature, geometry and all, a campaign of a hundred and fifty
        # thousand polygons took four seconds to open either window.
        grouped = None
        try:
            grouped = ds.ExecuteSQL(
                'SELECT %s AS who, %s AS pass, COUNT(*) AS n FROM "%s" '
                'GROUP BY 1, 2'
                % ('"operator"' if who >= 0 else "NULL",
                   '"pass_no"' if when >= 0 else "NULL", table))
        except Exception as err:
            log("cannot count the readings of %s by SQL: %s" % (table, err))
            grouped = None
        if grouped is not None:
            try:
                for row in grouped:
                    key = (operator_word(row.GetField(0)),
                           pass_number(row.GetField(1)))
                    counts[key] = counts.get(key, 0) + int(row.GetField(2))
            finally:
                ds.ReleaseResultSet(grouped)
            lyr = None
            continue
        lyr.SetIgnoredFields(["OGR_GEOMETRY"])
        for f in lyr:
            key = (operator_word(f.GetField(who) if who >= 0 else None),
                   pass_number(f.GetField(when) if when >= 0 else None))
            counts[key] = counts.get(key, 0) + 1
        lyr.SetIgnoredFields([])
        lyr = None
    ds = None
    return counts


def reading_choices(counts):
    """What the Whole raster and Export windows offer, in that order.

    All the readings together, which is what both always wrote and is right
    when the passes are layers of one piece of work; each reading on its own;
    and, wherever there are two readings or more to put side by side, their
    consensus: one per pass read by several operators, and one of every
    reading when there is more than one pass."""
    readings = sorted(counts, key=lambda r: (r[1], r[0]))
    out = [{"mode": "all", "readings": readings, "tag": "",
            "label": "all readings together"}]
    # The tag goes into file names, so two readings must never share one:
    # two names that differ only in an accented letter are one name once
    # tidied, "ANNA B" and "ANNA_B" are too, and a disk that does not tell
    # the case apart takes CONSENSUS_p1 for consensus_p1. The second of
    # two that would meet gets a number, and the export of one reading can
    # never overwrite the export of another.
    taken = {"consensus_p%d" % p for _, p in readings} | {"consensus_all"}
    for r in readings:
        tag = base = tidy("%s_p%d" % r, "reading")
        n = 2
        while tag.lower() in taken:
            tag = "%s_%d" % (base, n)
            n += 1
        taken.add(tag.lower())
        out.append({"mode": "one", "readings": [r], "tag": tag,
                    "label": reading_label(r)})
    passes = sorted({p for _, p in readings})
    for p in passes:
        same = [r for r in readings if r[1] == p]
        if len(same) > 1:
            out.append({"mode": "consensus", "readings": same,
                        "tag": "consensus_p%d" % p,
                        "label": "consensus of pass %d: %s"
                                 % (p, ", ".join(op for op, _ in same))})
    if len(passes) > 1:
        out.append({"mode": "consensus", "readings": readings,
                    "tag": "consensus_all",
                    "label": "consensus of every reading (%d)" % len(readings)})
    return out


def zip_name(stem):
    """The name of the archive that packs an export."""
    return "%s_export.zip" % stem


def operator_sets(readings):
    """The readings grouped by operator, for an export with one set of files
    per operator: [{"operator", "tag", "readings"}], the operators in
    alphabetical order, each holding all of its passes.

    The tag goes into file names, so it is tidied, and two operators whose
    names meet once tidied ("ANNA B" and "ANNA_B", or two that differ only in
    case on a disk that does not tell them apart) never share one: the second
    gets a number, as the tags of reading_choices do."""
    by = {}
    for op, p in sorted(readings, key=lambda r: (r[0], r[1])):
        by.setdefault(op, []).append((op, p))
    out, taken = [], set()
    for op, rs in by.items():
        tag = base = tidy(str(op), "operator")
        n = 2
        while tag.lower() in taken:
            tag = "%s_%d" % (base, n)
            n += 1
        taken.add(tag.lower())
        out.append({"operator": op, "tag": tag, "readings": rs})
    return out


def majority(n):
    """How many of n readings make a consensus: more than half of them. Of
    two, both; of three, two. Never a tie, so never more than one class."""
    return n // 2 + 1


def reading_rule(choice, partial=False):
    """The sentence that says how the readings were put together, written
    into what comes out, so that a file can say which reading it is.

    partial is for a consensus in which some frame was read by fewer of the
    readings than the vote holds: the majority is then taken among the
    readings that covered the frame, and the sentence says so."""
    mode = choice.get("mode", "all")
    readings = [tuple(r) for r in choice.get("readings") or []]
    if mode == "one":
        return "one reading only: %s" % reading_label(readings[0])
    if mode == "consensus" and partial:
        return ("consensus of %d readings: in each frame a pixel takes the "
                "class that a strict majority of the readings that covered "
                "that frame gave it (n // 2 + 1 of those n: a frame read by "
                "2 of the %d readings needs both), and is 0 where no class "
                "has one; outside every frame the readings that painted "
                "anywhere vote" % (len(readings), len(readings)))
    if mode == "consensus":
        return ("consensus of %d readings: each pixel takes the class at "
                "least %d of them gave it, a strict majority, and is 0 where "
                "no class has one" % (len(readings), majority(len(readings))))
    return ("every reading together: where two readings overlap, the mark "
            "drawn last wins")


def reading_metadata(choice, partial=False):
    """The same, as the metadata items of a GeoTIFF."""
    readings = [tuple(r) for r in choice.get("readings") or []]
    return {"RASTERLABEL_VERSION": VERSION,
            "RASTERLABEL_READING_MODE": choice.get("mode", "all"),
            "RASTERLABEL_READINGS": "; ".join(reading_label(r)
                                              for r in readings),
            "RASTERLABEL_READING_RULE": reading_rule(choice, partial)}


#  Where nobody painted: 0, or an ignore value
# =====================================================================
# A mask has always held 0 where nobody painted. A training script that
# skips those pixels has to be told which value they are, and three kinds of
# ground are 0 for three different reasons: outside every frame nobody
# looked; inside a frame nobody painted, which in a "paint everything in the
# frame" campaign is the class "none of these"; and where the readings of a
# consensus painted and did not agree. The ignore value keeps them apart.
# It is never a class code (1 to MAX_CLASS_CODE) and never 0, and it is not
# a foreground either: samgeo and Deepness write 255 for the foreground of a
# binary mask, and a mask of theirs and one of ours mean opposite things by
# it.
def ignore_refusal(value, codes=()):
    """Why this ignore value cannot be used, as a sentence, or None.

    codes are the class codes it must not meet: every code of the legend,
    retired ones included, or every code the marks hold."""
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            whole = float(value) == int(value)
        except (TypeError, ValueError, OverflowError):
            whole = False
        if not whole or isinstance(value, bool):
            return "the ignore value is a whole number"
        value = int(value)
    if value == 0:
        return "0 is already 'nobody painted it': choose '0, as before'"
    if 1 <= value <= MAX_CLASS_CODE:
        return ("1 to %d are the codes a campaign hands out; the ignore value "
                "is %d, past %d, or negative"
                % (MAX_CLASS_CODE, IGNORE_CODE, IGNORE_CODE))
    if value in {int(c) for c in codes or ()}:
        return "class code %d already uses it" % value
    if value < -32768 or value > 65535:
        return "a mask holds -32768 to 65535"
    return None


def unlabelled_rule(mode, ignore=None, consensus=False):
    """The sentence that says what a mask holds where nobody painted."""
    disputed = ", and where the readings do not agree" if consensus else ""
    if mode == "ignore":
        return "%d where nobody painted%s" % (ignore, disputed)
    if mode == "frames":
        return ("0 inside the frames where nobody painted, %d outside every "
                "frame%s" % (ignore, disputed))
    return "0 where nobody painted"


def unlabelled_metadata(mode, ignore=None, consensus=False):
    """The same, as the metadata items of a GeoTIFF mask. The ignore value
    itself only when there is one: its presence is what Cutouts reads."""
    out = {"RASTERLABEL_UNLABELLED": mode,
           "RASTERLABEL_UNLABELLED_RULE": unlabelled_rule(mode, ignore,
                                                          consensus)}
    if mode != "zero" and ignore is not None:
        out["RASTERLABEL_IGNORE_INDEX"] = str(int(ignore))
    return out


def unlabelled_tag(mode, ignore=None):
    """What goes into the name of a mask: "" for 0, ign255 for the ignore
    value everywhere, ign255out for outside the frames; a minus is an m."""
    if mode == "zero" or ignore is None:
        return ""
    word = "ign%s" % str(int(ignore)).replace("-", "m")
    return word + "out" if mode == "frames" else word


def frames_closed_for(shares, choice):
    """(frames, closed) of a campaign for the reading chosen: a frame is
    closed for one reading when that reading closed it, and for every
    reading together when each of those readings did. For a consensus the
    readings that count in a frame are the ones that covered it, as
    consensus_voters has them, so a frame two of four people read is closed
    when those two closed it; a frame nobody covered asks all of them.
    shares is reading_shares' {tile: {reading: share}}. Points are not
    looked at: a reading that only put a point in a frame is not a reading
    that closed it."""
    wanted = {tuple(r) for r in (choice or {}).get("readings") or []}
    covering = (choice or {}).get("mode") == "consensus"
    closed = 0
    for one in (shares or {}).values():
        one = one or {}
        done = reading_closed(one)
        here = {r for r in wanted if r in one} if covering else set()
        if wanted and (here or wanted) <= done:
            closed += 1
    return len(shares or {}), closed


def reading_tag(reading):
    """A reading as it goes into a file name: ANNA_p1. The same spelling as
    reading_choices gives, before it numbers a second one that would meet."""
    return tidy("%s_p%d" % (reading[0], reading[1]), "reading")


def pair_tag(a, b):
    """Two readings as they go into a file name: ANNA_p1_vs_BRUNO_p1."""
    return "%s_vs_%s" % (reading_tag(a), reading_tag(b))


def comparison_kind(a, b):
    """What comparing two readings measures.

    "inter": two people in the same pass, the agreement between readers.
    "intra": one person in two passes, how far one reader agrees with
    themselves. "other": a different person in a different pass, which is
    neither, and is said so. A reading compared with itself is refused by
    whoever asks, not here."""
    op_a, op_b = operator_word(a[0]), operator_word(b[0])
    pass_a, pass_b = pass_number(a[1]), pass_number(b[1])
    if op_a != op_b and pass_a == pass_b:
        return "inter"
    if op_a == op_b and pass_a != pass_b:
        return "intra"
    return "other"


def hidden_from(reader, reading, one_operator, blind):
    """Whether Annotate keeps this reading out of the reader's sight.

    The two clauses of apply_filter, one for one: "only my work" hides every
    operator but the reader, in every pass; blind shows only the pass being
    drawn and hides every other pass, the earlier ones and the later ones
    alike (going back to pass 1 with pass 2 in front of it was no more blind
    than the other way round). reader and reading are (operator, pass)."""
    who, when = operator_word(reader[0]), pass_number(reader[1])
    op, p = operator_word(reading[0]), pass_number(reading[1])
    return bool((one_operator and op != who) or (blind and p != when))


# The most passes one operator can have: the pass is one digit in the
# panel's settings, in the name of a layer and in the files that go out.
MAX_PASS = 9


def passes_of(data, operator, found=(), also=()):
    """The passes that exist for an operator, in order, 1 always among them.

    Three sources, put together like the operators are: the manifest, which
    the + beside the pass writes; the passes found in the tables, which is
    how a campaign made before the list existed keeps the passes it already
    has; and also, the pass a reading in hand is in."""
    key = operator_word(operator)
    out = {1}
    listed = (data.get("passes") or {}) if isinstance(data, dict) else {}
    for name, numbers in listed.items():
        if operator_word(name) == key:
            for n in (numbers or []):
                out.add(pass_number(n))
    for n in found:
        out.add(pass_number(n))
    for n in also:
        out.add(pass_number(n))
    return sorted(n for n in out if 1 <= n <= MAX_PASS)


def next_pass(data, operator, found=()):
    """The pass a + adds for this operator, or None at the most there are."""
    n = max(passes_of(data, operator, found)) + 1
    return n if n <= MAX_PASS else None


def write_pass(data, operator, number):
    """Write a pass into the manifest's list for the operator, which the
    caller then saves. The list is kept sorted and without repeats; the
    operator is kept in its written form. Returns True when it was new."""
    key = operator_word(operator)
    number = pass_number(number)
    listed = data.get("passes")
    if not isinstance(listed, dict):
        listed = {}
        data["passes"] = listed
    for name in list(listed):
        if operator_word(name) == key:
            key = name
            break
    numbers = sorted({pass_number(n) for n in (listed.get(key) or [])}
                     | {1, number})
    fresh = listed.get(key) != numbers
    listed[key] = numbers
    return fresh


#  Read only
# =====================================================================
# Campaign.open() checks the package and adds any table or column an older
# build did not make, which is a write, and it makes an empty package when
# there is none, which is worse. The measuring windows, the card and
# Processing only read, so they read through these: the manifest as JSON,
# the package opened read only, nothing created and nothing changed.
def campaign_read_only(folder):
    """(data, package) of a campaign, without touching either.

    data is campaign.json as it is on disk. package is the GeoPackage opened
    read only through OGR, or None when it is not there or cannot be read;
    the caller lets go of it (package = None) when done. A manifest that is
    missing or is not JSON raises, as json.load does."""
    with open(os.path.join(folder, Campaign.MANIFEST), encoding="utf-8") as f:
        data = json.load(f)
    path = os.path.join(folder, Campaign.PACKAGE)
    package = None
    if os.path.isfile(path):
        try:
            package = ogr.Open(path, 0)
        except Exception as err:
            log("cannot read %s: %s" % (os.path.basename(path), err))
            package = None
    return data, package


def _package_read(package):
    """(datasource, opened here) out of a path or an open datasource."""
    if package is None:
        return None, False
    if isinstance(package, str):
        if not os.path.isfile(package):
            return None, False
        try:
            return ogr.Open(package, 0), True
        except Exception as err:
            log("cannot read %s: %s" % (os.path.basename(package), err))
            return None, False
    return package, False


def _field_of(defn, name):
    """The index of a column, case ignored, or -1."""
    for i in range(defn.GetFieldCount()):
        if defn.GetFieldDefn(i).GetName().lower() == name:
            return i
    return -1


def _sql_list(values):
    return ", ".join("'%s'" % str(v).replace("'", "''") for v in values)


def _polygons_of(geom):
    """The polygons inside an OGR geometry, however deep a clip nested them."""
    kind = ogr.GT_Flatten(geom.GetGeometryType())
    if kind == ogr.wkbPolygon:
        yield geom
    elif kind in (ogr.wkbMultiPolygon, ogr.wkbGeometryCollection):
        for i in range(geom.GetGeometryCount()):
            for part in _polygons_of(geom.GetGeometryRef(i)):
                yield part


def _area_of_union(pieces):
    """The area of the union of OGR geometries: an overlap counts once."""
    if len(pieces) == 1:
        return pieces[0].GetArea()
    try:
        # UnionCascaded takes a MultiPolygon only: a GeometryCollection made
        # GDAL print "must be a MultiPolygon" every time before the slower
        # pairwise union below did the work. A clipped piece can itself be a
        # MultiPolygon or a collection, so its polygons are taken one by one;
        # the lines and points a clip can leave have no area anyway.
        bag = ogr.Geometry(ogr.wkbMultiPolygon)
        for p in pieces:
            for part in _polygons_of(p):
                bag.AddGeometry(part)
        if not bag.GetGeometryCount():
            return 0.0
        one = bag.UnionCascaded()
        if one is not None:
            return one.GetArea()
    except Exception:
        pass
    try:
        one = pieces[0].Clone()
        for p in pieces[1:]:
            one = one.Union(p)
        return one.GetArea()
    except Exception:
        # what measure_tile falls back to as well: the plain sum
        return sum(p.GetArea() for p in pieces)


def _clipped(geom, frame):
    """geom inside frame, or None. An invalid ring is mended once first."""
    for mend in (False, True):
        try:
            piece = (geom.Buffer(0) if mend else geom).Intersection(frame)
        except Exception:
            continue
        if piece is not None:
            return piece if not piece.IsEmpty() else None
    return None


def reading_shares(package, tile_ids=None):
    """How much of each frame each reading covers: {tile: {reading: share}}.

    The one definition of a closed frame, the one measure_tile writes into
    the "closed" column and Check compares it with: the polygons of one
    reading (operator and pass, read through operator_word and pass_number)
    whose tile_id is the frame's, each clipped to the frame, their union
    measured, over the frame's area. A union, so two polygons of one
    reading that overlap count once; one reading at a time, so two people's
    halves never close a frame. Areas are planar, in the package's system;
    as a share they hardly differ from the ellipsoid's.

    package is a path or a datasource open for reading; nothing is written.
    tile_ids narrows it to these frames. Every frame asked for is in the
    answer, with {} when nobody painted in it; a frame with no tile_id, or
    no area, is not. Where two frames share a tile_id the first counts."""
    out = {}
    ds, here = _package_read(package)
    if ds is None:
        return out
    tiles = polys = None
    try:
        tiles = ds.GetLayerByName("tiles")
        polys = ds.GetLayerByName("polygons")
        if tiles is None:
            return out
        wanted = None if tile_ids is None else {str(t) for t in tile_ids}
        idx = _field_of(tiles.GetLayerDefn(), "tile_id")
        if idx < 0:
            return out
        frames = {}
        tiles.ResetReading()
        for f in tiles:
            tid = f.GetField(idx)
            if tid is None or str(tid) == "":
                continue
            tid = str(tid)
            if (wanted is not None and tid not in wanted) or tid in frames:
                continue
            g = f.GetGeometryRef()
            if g is None or g.IsEmpty() or not g.GetArea() > 0:
                continue
            frames[tid] = g.Clone()
            out[tid] = {}
        if polys is None or not frames:
            return out
        defn = polys.GetLayerDefn()
        i_tile = _field_of(defn, "tile_id")
        i_who = _field_of(defn, "operator")
        i_pass = _field_of(defn, "pass_no")
        if i_tile < 0:
            return out
        if wanted is not None and len(frames) <= 500:
            polys.SetAttributeFilter('"%s" IN (%s)' % (
                defn.GetFieldDefn(i_tile).GetName(), _sql_list(frames)))
        pieces = {}
        try:
            polys.ResetReading()
            for f in polys:
                tid = f.GetField(i_tile)
                tid = None if tid is None else str(tid)
                if tid not in frames:
                    continue
                g = f.GetGeometryRef()
                if g is None or g.IsEmpty():
                    continue
                piece = _clipped(g, frames[tid])
                if piece is None or not piece.GetArea() > 0:
                    continue
                key = (operator_word(f.GetField(i_who) if i_who >= 0
                                     else None),
                       pass_number(f.GetField(i_pass) if i_pass >= 0
                                   else None))
                pieces.setdefault((tid, key), []).append(piece)
        finally:
            polys.SetAttributeFilter(None)
        for (tid, key), held in pieces.items():
            out[tid][key] = min(_area_of_union(held) / frames[tid].GetArea(),
                                1.0)
    except Exception as err:
        log("cannot measure the frames of the package: %s" % err)
    finally:
        tiles = polys = None
        if here:
            ds = None
    return out


def reading_closed(shares):
    """The readings that closed a frame: a share above CLOSED_SHARE.

    Given reading_shares' {tile: {reading: share}}, {tile: set of readings};
    given one frame's {reading: share}, the set for that frame. A frame is
    closed for one reading when that reading closed it, and for several (all
    of them together, or a consensus) when every one of them did."""
    values = list(shares.values())
    if values and all(isinstance(v, dict) for v in values):
        return {tid: reading_closed(one) for tid, one in shares.items()}
    return {r for r, s in shares.items()
            if s is not None and float(s) > CLOSED_SHARE}


def consensus_voters(package, readings, points_in=False, shares=None):
    """Who votes where in a consensus of these readings.

    A frame read by 2 of 4 people is voted by those 2, and a pixel needs a
    majority of them, not of the 4: the other two never saw the frame, and
    counting them as votes against asked for both of two and three of four
    at once, so a pair of readers could never agree on anything. A reading
    covered a frame when it has a mark in it, the touch reading_shares
    measures: a polygon with the frame's tile_id and some area inside the
    frame, and, in a vote that takes points in, a point with that tile_id.
    It need not have closed the frame: a reading that began and left a pixel
    unpainted votes against it there, as an unpainted pixel always did.

    Ground outside every frame has no frame to cover. A free-hand campaign
    is all of it, and a mark drawn outside the frames of a framed campaign
    is in none. There the readings that painted anywhere in the campaign
    vote, which is the frames' own rule with the campaign as the frame: a
    stray mark of one reading out of four still needs three to stand.

    Returns {"frames": {tile_id: frozenset of readings}, "outside":
    frozenset, "partial": True when a frame that was read, or the ground
    outside the frames, is voted by fewer readings than are in the vote,
    "by_readings": {k: frames voted by k readings}}. Where partial is False
    every reading votes everywhere and the vote is the one it always was.
    shares is reading_shares' answer, for whoever has it already."""
    readings = [tuple(r) for r in readings]
    wanted = set(readings)
    if shares is None:
        shares = reading_shares(package)
    frames = {tid: set(r for r in by if r in wanted)
              for tid, by in shares.items()}
    if points_in and frames:
        ds, here = _package_read(package)
        pts = None
        try:
            pts = ds.GetLayerByName("points") if ds is not None else None
            if pts is not None:
                defn = pts.GetLayerDefn()
                i_tile = _field_of(defn, "tile_id")
                i_who = _field_of(defn, "operator")
                i_pass = _field_of(defn, "pass_no")
                pts.ResetReading()
                for f in pts:
                    g = f.GetGeometryRef()
                    if i_tile < 0 or g is None or g.IsEmpty():
                        continue
                    tid = f.GetField(i_tile)
                    tid = None if tid is None else str(tid)
                    key = (operator_word(f.GetField(i_who) if i_who >= 0
                                         else None),
                           pass_number(f.GetField(i_pass) if i_pass >= 0
                                       else None))
                    if tid in frames and key in wanted:
                        frames[tid].add(key)
        except Exception as err:
            log("cannot read the points of the package: %s" % err)
        finally:
            pts = None
            if here:
                ds = None
    tables = ("polygons", "points") if points_in else ("polygons",)
    outside = frozenset(r for r in readings_in(package, tables)
                        if r in wanted)
    full = frozenset(readings)
    held = {tid: frozenset(who) for tid, who in frames.items()}
    by_readings = {}
    for who in held.values():
        if who:
            by_readings[len(who)] = by_readings.get(len(who), 0) + 1
    partial = (any(who and who != full for who in held.values())
               or outside != full)
    return {"frames": held, "outside": outside, "partial": partial,
            "by_readings": by_readings}


def voters_in(cover, tile_id, readings):
    """The readings that vote in the frame tile_id, out of consensus_voters'
    answer (None: all of them, everywhere). A tile_id that names no frame,
    or none, is ground outside every frame."""
    if cover is None:
        return frozenset(tuple(r) for r in readings)
    key = None if tile_id is None else str(tile_id)
    if key is not None and key in cover["frames"]:
        return cover["frames"][key]
    return cover["outside"]


def frames_by_readings_text(by_readings):
    """{2: 12, 4: 3} as "12 frames by 2 readings, 3 frames by 4 readings"."""
    return ", ".join("%d frame%s by %d reading%s"
                     % (n, "" if n == 1 else "s", k, "" if k == 1 else "s")
                     for k, n in sorted(by_readings.items()))


def frame_design(package):
    """{tile: {sample_id, stratum, incl_prob, weight, design}} of the frames
    imported with a sampling design, as they are in the tiles table.

    {} when the tiles have none of these columns, or no frame carries a
    value in any of them; a frame placed by hand, with all five empty, is
    not listed. Nothing is derived: what is there is given back, None where
    a column is empty."""
    out = {}
    ds, here = _package_read(package)
    if ds is None:
        return out
    tiles = None
    try:
        tiles = ds.GetLayerByName("tiles")
        if tiles is None:
            return out
        defn = tiles.GetLayerDefn()
        idx = _field_of(defn, "tile_id")
        cols = [(name, _field_of(defn, name)) for name in DESIGN_FIELDS]
        if idx < 0 or all(i < 0 for _, i in cols):
            return out
        tiles.ResetReading()
        for f in tiles:
            tid = f.GetField(idx)
            if tid is None or str(tid) == "" or str(tid) in out:
                continue
            row = {name: (f.GetField(i)
                          if i >= 0 and f.IsFieldSetAndNotNull(i) else None)
                   for name, i in cols}
            if any(v is not None and v != "" for v in row.values()):
                out[str(tid)] = row
    except Exception as err:
        log("cannot read the sampling design of the frames: %s" % err)
    finally:
        tiles = None
        if here:
            ds = None
    return out


#  The manifest's journal
# =====================================================================
def manifest_journal(when=None):
    """The "journal" block of a manifest: kept, in journal.csv, from now on.

    It is not written into a manifest before the first mark is drawn. A
    block saying "on" from a given moment would make Time count every day
    since then as a day of no work, without a word, when no rows were being
    written. Given at the first mark, to a new campaign or correction and to
    an older manifest alike, "since" says from when on its rows are there."""
    moment = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return {"on": True, "file": JOURNAL_NAME, "version": JOURNAL_VERSION,
            "since": moment.replace(microsecond=0).isoformat()
            .replace("+00:00", "Z")}
