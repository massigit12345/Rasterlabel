"""rasterlabel.export

Writing the tables out in another shape.
"""
import csv
import io
import os
import re
import shutil
import tempfile
import zipfile
from decimal import Decimal

from osgeo import gdal, ogr

from .errors import log
from .naming import csv_text, long_path, now
from .project import PLACEHOLDER_SRS
from .campaign import (READING_TABLES, consensus_voters, majority,
                       operator_sets, operator_word, pass_number, reading_shares,
                       voters_in, release_file)


# The formats that write a coordinate as decimal text through GDAL's own
# number formatter, the one that writes WKT. Left to itself it writes fifteen
# significant digits, about ten nanometres on a longitude, and a polygon cut
# against its neighbours can hold two vertices a thousandth of that apart:
# valid in the GeoPackage, where a double is kept as it is, and a ring that
# touches itself, or crosses itself, once both are written as the same
# fifteen digits. That is what turned two polygons of a real campaign invalid
# in its KML and its CSV, while the GeoPackage, the shapefile and the
# GeoJSON, which keep the double itself or seventeen digits, stayed valid. The
# same rounding made eight pairs of neighbours overlap there, by slivers ten
# nanometres wide.
TEXT_DRIVERS = ("CSV", "KML")

# Seventeen digits give back every double exactly, and only without
# rounding: GDAL's rounding trims 0.30000000000000004 to 0.3, which is
# another number. Recent GDAL reads both options every time it writes; GDAL
# 3.8, the one in QGIS 3.36, reads them once, the first time anything in the
# process writes WKT, and in QGIS that has happened by the time a campaign is
# open. So the options are set, then asked whether they work, and when they
# do not the coordinates GDAL wrote are written again, exactly.
FULL_PRECISION = {"OGR_WKT_PRECISION": "17", "OGR_WKT_ROUND": "NO"}

# The formats whose file is written whole, and that GDAL cannot write over.
# CSV and GeoJSON hold one table a file; the KML holds them all, in one go.
# Over an old KML, GDAL hands the file to its other KML driver, LIBKML,
# which can open it for update: the export would come out in another layout,
# every coordinate with an altitude of 0 and fifteen digits, whatever was asked.
WRITTEN_WHOLE = ("CSV", "GeoJSON", "KML")

NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
# The WKT is the first column of every row GDAL writes, so it is looked for
# only at the start of a line: a note that quotes a polygon is text, and
# inside a quoted field a quote is always doubled, so no line of a note can
# start the way a row does.
GEOMETRY_TEXT = re.compile(
    r'^"((?:MULTI)?(?:POINT|LINESTRING|POLYGON)[ ZM]*\([^"]*\))"', re.M)
COORDINATES = re.compile(r"(<coordinates>)([^<]*)(</coordinates>)")


class full_precision:
    """FULL_PRECISION for the length of a with, on this thread only, and
    whatever was set before put back afterwards. Thread-local because QGIS
    draws the map on other threads, through the same GDAL."""

    def __enter__(self):
        local = hasattr(gdal, "SetThreadLocalConfigOption")
        self.get = gdal.GetThreadLocalConfigOption if local \
            else gdal.GetConfigOption
        self.set = gdal.SetThreadLocalConfigOption if local \
            else gdal.SetConfigOption
        self.before = {k: self.get(k, None) for k in FULL_PRECISION}
        for k, v in FULL_PRECISION.items():
            self.set(k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.before.items():
            self.set(k, v)
        return False


def coordinates_exact():
    """Whether GDAL, here and now, writes a coordinate as text that reads back
    as the very same double. Asked with full_precision in force, of the same
    formatter the CSV and KML writers use."""
    x, y = 0.1 + 0.2, 1.0 / 3.0
    try:
        point = ogr.Geometry(ogr.wkbPoint)
        point.AddPoint_2D(x, y)
        back = ogr.CreateGeometryFromWkt(point.ExportToWkt())
        return back.GetX() == x and back.GetY() == y
    except Exception:
        return False


def runs_of(geom):
    """The coordinates of a geometry, one run of numbers per ring, line or
    point, in the order a writer goes through them: x, y and z, if it has
    one, of every vertex."""
    if geom is None or geom.IsEmpty():
        return []
    if geom.GetGeometryCount():
        out = []
        for i in range(geom.GetGeometryCount()):
            out.extend(runs_of(geom.GetGeometryRef(i)))
        return out
    three = geom.GetCoordinateDimension() == 3
    run = []
    for i in range(geom.GetPointCount()):
        p = geom.GetPoint(i)
        run.extend(p[:3] if three else p[:2])
    return [run]


def exact_text(value):
    """A double as the shortest text that reads back as the very same
    double, and in plain decimals: repr writes a longitude a hair east of
    Greenwich as 1e-05, and a KML reader is not obliged to read that."""
    text = repr(float(value))
    if ("e" in text or "E" in text) and "n" not in text:
        text = format(Decimal(text), "f")
    return text


def renumbered(text, values):
    """text with its numbers replaced by values, written exactly: Python's
    repr of a float is the shortest text that reads back as the same double.
    None when the two do not match one for one, or a number written is not
    the value it stands for, rounded: then this is not the text it was
    taken to be, and it is left alone."""
    found = NUMBER.findall(text)
    if len(found) != len(values):
        return None
    for old, new in zip(found, values):
        if abs(float(old) - new) > 1e-9 * max(1.0, abs(new)):
            return None
    it = iter(values)
    return NUMBER.sub(lambda m: exact_text(next(it)), text)


def rewrite_coordinates(target, staged, tables, driver):
    """Write again, exactly, every coordinate GDAL wrote as text in target,
    from the geometries of staged it wrote them from: the same tables, the
    same features, in the same order. True if the file was rewritten.

    Only the numbers inside a geometry change: the WKT column of a CSV, the
    <coordinates> of a KML. Anything that does not line up, a feature skipped
    or a number that is not the one expected, leaves the file as GDAL wrote
    it, and the reading back after it says what that costs."""
    source = ogr.Open(long_path(staged))
    if source is None:
        return False
    runs = []
    for table in tables:
        layer = source.GetLayerByName(table)
        if layer is None:
            continue
        layer.ResetReading()
        for f in layer:
            g = f.GetGeometryRef()
            if g is None or g.IsEmpty():
                continue
            if driver == "CSV":
                # one WKT per feature: all its runs in one
                runs.append([v for run in runs_of(g) for v in run])
            else:
                runs.extend(runs_of(g))
    layer = source = None
    try:
        with open(long_path(target), "rb") as f:
            text = f.read().decode("latin-1")
    except OSError as err:
        log("cannot read %s back: %s" % (os.path.basename(target), err))
        return False
    pattern = GEOMETRY_TEXT if driver == "CSV" else COORDINATES
    pieces, at, n = [], 0, 0
    for m in pattern.finditer(text):
        if n >= len(runs):
            return False
        body = m.group(1) if driver == "CSV" else m.group(2)
        start = m.start(1) if driver == "CSV" else m.start(2)
        new = renumbered(body, runs[n])
        if new is None:
            return False
        pieces.append(text[at:start])
        pieces.append(new)
        at = start + len(body)
        n += 1
    if n != len(runs):
        return False
    pieces.append(text[at:])
    with open(long_path(target), "wb") as f:
        f.write("".join(pieces).encode("latin-1"))
    return True


def invalid_polygons(path, where=None):
    """How many polygons each table of a file holds that are not valid."""
    found = {}
    try:
        ds = ogr.Open(long_path(path))
        if ds is None:
            return found
        for i in range(ds.GetLayerCount()):
            layer = ds.GetLayerByIndex(i)
            if where:
                layer.SetAttributeFilter(where)
            bad = 0
            for f in layer:
                g = f.GetGeometryRef()
                if g is not None and ogr.GT_Flatten(g.GetGeometryType()) in (
                        ogr.wkbPolygon, ogr.wkbMultiPolygon) \
                        and not g.IsValid():
                    bad += 1
            found[layer.GetName()] = bad
        layer = ds = None
    except Exception as err:
        log("cannot read %s back: %s" % (os.path.basename(path), err))
    return found


def tables_have_system(source, tables):
    """Whether the tables of a package are in a coordinate system that can be
    turned into longitude and latitude.

    Not when a table has none, or only the stand-in a GeoPackage gives a table
    with no system: the GDAL of QGIS 3.36 reads that stand-in back as a
    geographic system, so asking only whether there is one said yes there."""
    try:
        ds = ogr.Open(source)
        if ds is None:
            return True
        for table in tables:
            layer = ds.GetLayerByName(table)
            if layer is None:
                continue
            srs = layer.GetSpatialRef()
            if srs is None or srs.IsLocal() \
                    or (srs.GetName() or "").strip() in PLACEHOLDER_SRS:
                return False
        layer = ds = None
    except Exception as err:
        log("cannot read the system of the tables: %s" % err)
    return True


def feature_counts(path, where=None):
    """How many features with a geometry each table of a file holds, by name,
    or None when the file cannot be read back.

    With a geometry, because a feature GDAL could not reproject is written
    all the same, with its geometry left out: counting rows, a table whose
    every shape was lost looked whole."""
    found = {}
    try:
        ds = ogr.Open(long_path(path))
        if ds is None:
            return None
        for i in range(ds.GetLayerCount()):
            layer = ds.GetLayerByIndex(i)
            if where:
                layer.SetAttributeFilter(where)
            n = 0
            for f in layer:
                g = f.GetGeometryRef()
                if g is not None and not g.IsEmpty():
                    n += 1
            found[layer.GetName()] = n
        layer = ds = None
    except Exception as err:
        log("cannot count what %s holds: %s" % (os.path.basename(path), err))
        return None
    return found


def defuse_csv(path):
    """The CSV GDAL wrote, with every text cell a spreadsheet would run as a
    formula given the quote csv_text puts in front of it. The class names are
    what a person typed, and a file that opens in Excel is read by the cell.

    The file is read row by row, never whole: an export of a large campaign
    is hundreds of megabytes of geometry. It is left exactly as GDAL wrote it
    when nothing needs changing, which is nearly always, and that is found
    out by reading it once; only otherwise is it written again, row by row,
    through a temporary file. Returns the number of cells changed. Given a
    folder, which is what GDAL makes of several tables in one CSV file, it
    does each .csv in it."""
    if os.path.isdir(long_path(path)):
        return sum(defuse_csv(os.path.join(path, n))
                   for n in sorted(os.listdir(long_path(path)))
                   if n.lower().endswith(".csv"))
    # The geometry of a large polygon as text is longer than the 128 KB a cell
    # may have for the csv module, and a file it stops in would go unchecked.
    old_limit = csv.field_size_limit(2 ** 31 - 1)
    try:
        with io.open(long_path(path), encoding="utf-8", newline="") as fh:
            ending = "\r\n" if fh.readline().endswith("\r\n") else "\n"
            fh.seek(0)
            if not any(csv_text(c) != c for row in csv.reader(fh)
                       for c in row):
                return 0
    except (OSError, csv.Error, UnicodeDecodeError, MemoryError) as err:
        log("cannot check %s for formulas: %s" % (os.path.basename(path), err))
        return 0
    finally:
        csv.field_size_limit(old_limit)
    changed = 0
    spare = path + ".tmp"
    csv.field_size_limit(2 ** 31 - 1)
    try:
        with io.open(long_path(path), encoding="utf-8", newline="") as src:
            with io.open(long_path(spare), "w", encoding="utf-8",
                         newline="") as out:
                writer = csv.writer(out, lineterminator=ending)
                for row in csv.reader(src):
                    for i, cell in enumerate(row):
                        safe = csv_text(cell)
                        if safe != cell:
                            row[i] = safe
                            changed += 1
                    writer.writerow(row)
        os.replace(long_path(spare), long_path(path))
    except (OSError, csv.Error, UnicodeDecodeError, MemoryError) as err:
        log("cannot write %s without its formulas: %s"
            % (os.path.basename(path), err), loud=True)
        try:
            os.remove(long_path(spare))
        except OSError:
            pass
        return 0
    finally:
        csv.field_size_limit(old_limit)
    return changed


def remove_output(target, fmt):
    """Take away a file this export wrote, and the files that go with it."""
    try:
        if fmt != "KML":
            ogr.GetDriverByName(fmt).DeleteDataSource(long_path(target))
    except Exception:
        pass
    sides = (".csvt", ".prj") if fmt == "CSV" else ()
    for path in [target] + [os.path.splitext(target)[0] + s for s in sides]:
        try:
            if os.path.exists(long_path(path)):
                os.remove(long_path(path))
        except OSError as err:
            log("cannot remove %s: %s" % (os.path.basename(path), err))


def write_vectors(source, recipe, stem):
    """Copy the chosen tables out of the package, in the chosen shape.

    gdal does the conversion, which means the field types, the projection and
    the geometry survive the trip instead of being rebuilt by hand and getting
    it subtly wrong. What is decided here is only what to ask it for.

    Three lists come back: the files written, the tables that could not be,
    and what is worth saying about the files that were."""
    choice = recipe.get("reading") or {}
    if choice.get("mode", "all") != "all":
        return write_reading(source, recipe, stem)
    # One set of files per operator: only meaningful for every reading
    # together, which is what the window offers it for.
    if recipe.get("arrange") == "operator" and choice.get("readings"):
        return write_per_operator(source, recipe, stem)
    folder = recipe["folder"]
    os.makedirs(long_path(folder), exist_ok=True)
    driver = recipe["driver"]
    tables = list(recipe["tables"])
    written, failed, notes = [], [], []

    # gdal is asked for a table that is not in the package and answers with a
    # complaint on the console and a perfectly valid empty file, which is the
    # worst of both: nothing said wrong, nothing written. So the package is
    # read first and a table that is not in it is called a failure here.
    try:
        probe = ogr.Open(source)
        present = set()
        if probe is not None:
            for i in range(probe.GetLayerCount()):
                present.add(probe.GetLayerByIndex(i).GetName())
        probe = None
    except Exception as err:
        log("cannot read the package: %s" % err)
        present = set()
    if present:
        failed = [t for t in tables if t not in present]
        tables = [t for t in tables if t in present]
    if not tables:
        return [], failed, notes

    # A campaign with no coordinate system, a picture or a world file without
    # one, has its coordinates in pixels or in units nobody named, and nothing
    # can turn those into degrees. Handed to GDAL to reproject all the same,
    # GeoJSON and KML come out with no feature at all and are said written,
    # or, with the GDAL of QGIS 3.36, with pixels labelled as degrees. The
    # manifest says whether there is a system (recipe "system"); the tables are
    # asked as well. Without one the coordinates go out as they were drawn,
    # and KML, which holds degrees and nothing else, is refused.
    system = bool(recipe.get("system", True)) \
        and tables_have_system(source, tables)
    if not system and driver == "KML":
        notes.append("KML holds longitude and latitude only, and this "
                     "campaign has no coordinate system: nothing was written. "
                     "GeoPackage, Shapefile, GeoJSON or CSV write the "
                     "coordinates as they were drawn.")
        for note in notes:
            log(note, loud=True)
        return [], failed + tables, notes
    crs = recipe["crs"] if system else None
    # said whenever degrees were asked for, and for GeoJSON always: whoever
    # opens a GeoJSON reads its coordinates as longitude and latitude
    if not system and (recipe["crs"] or driver == "GeoJSON"):
        notes.append("the campaign has no coordinate system: the coordinates "
                     "are written as they were drawn, in pixels or in the "
                     "units of its world file, not in longitude and latitude")

    where = None
    if recipe["tile_id"]:
        # Every table carries the frame it belongs to, the frames included:
        # a frame's own tile_id is its name. So one clause narrows all four
        # down to the same piece of ground.
        # The name is quoted as SQLite quotes it, apostrophes doubled,
        # because a frame renamed by hand in the GeoPackage can carry one,
        # and an unquoted apostrophe breaks the clause and with it the
        # export. Not sql_text(): that is QGIS's quoting, where a
        # backslash escapes, and SQLite's has no such thing.
        where = "\"tile_id\" = '%s'" % (
            str(recipe["tile_id"]).replace("'", "''"))

    def options(layers, fmt, select):
        # Overwrite, because the names are fixed: <campaign>_<table>. Without
        # it, exporting a second time into the same folder would fail on the
        # file the first export wrote, and the window would blame the format.
        kwargs = {"format": fmt, "layers": list(layers),
                  "skipFailures": True, "accessMode": "overwrite"}
        if not system:
            # No system written either. The GDAL of QGIS 3.36 takes the
            # GeoPackage's stand-in for none for a geographic system, and a
            # shapefile would come out with a .prj saying its pixels were degrees.
            kwargs["dstSRS"] = "NULL"
            kwargs["reproject"] = False
        if select:
            if crs:
                kwargs["dstSRS"] = crs
                kwargs["reproject"] = True
            if where:
                kwargs["where"] = where
        if fmt == "CSV":
            kwargs["layerCreationOptions"] = ["GEOMETRY=AS_WKT",
                                              "CREATE_CSVT=YES"]
        elif fmt == "ESRI Shapefile":
            # The table of a shapefile is written in Latin-1 unless told
            # otherwise, and a class named in Chinese, Greek or Cyrillic came
            # out as question marks. UTF-8 also writes the .cpg that says so.
            kwargs["layerCreationOptions"] = ["ENCODING=UTF-8"]
        return gdal.VectorTranslateOptions(**kwargs)

    def translate(target, origin, opts, fmt):
        release_file(target)
        # Every call that reaches a file here goes through long_path: past
        # 260 characters SQLite cannot open the path as it is, and a
        # GeoPackage near that length was said to be a failure of the format.
        # The name that is logged and handed back stays the plain one.
        if fmt in WRITTEN_WHOLE and os.path.exists(long_path(target)):
            # Overwrite is not enough for these: GDAL opens the old file,
            # cannot take its one table out of it, says so on the console
            # and hands back the file as it was, which read as a success, or,
            # for a KML, rewrites it through LIBKML (see WRITTEN_WHOLE).
            # Exporting again into the same folder left the first export in
            # place, and the window said it had written it.
            try:
                if fmt != "KML":
                    ogr.GetDriverByName(fmt).DeleteDataSource(
                        long_path(target))
                if os.path.exists(long_path(target)):
                    os.remove(long_path(target))
            except Exception as err:
                log("cannot replace %s: %s" % (os.path.basename(target), err))
                return False
            for side in (".csvt", ".prj") if fmt == "CSV" else ():
                old = long_path(os.path.splitext(target)[0] + side)
                if os.path.exists(old):
                    os.remove(old)
        try:
            out = gdal.VectorTranslate(long_path(target), origin,
                                       options=opts)
        except Exception as err:
            log("cannot write %s: %s" % (os.path.basename(target), err))
            return False
        ok = out is not None
        out = None
        return ok

    with full_precision():
        rewrite = driver in TEXT_DRIVERS and not coordinates_exact()
        # When the digits cannot be asked for, the tables are first copied
        # as they will be written, reprojected and narrowed to the frame,
        # into a GeoPackage of their own, which keeps every double as it is;
        # the file is written from that, and its coordinates are then written
        # again from it, exactly.
        origin, stage = source, None
        if rewrite:
            log("this GDAL (%s) writes coordinates as text with fifteen "
                "digits; the %s is given them back in full"
                % (gdal.__version__, driver))
            stage = tempfile.mkdtemp(prefix="rasterlabel_export_")
            origin = os.path.join(stage, "as_written.gpkg")
            if not translate(origin, source, options(tables, "GPKG", True),
                             "GPKG"):
                shutil.rmtree(stage, ignore_errors=True)
                return [], failed + tables, notes
        try:
            if recipe["one_file"]:
                jobs = [(os.path.join(folder, stem + recipe["extension"]),
                         tables)]
            else:
                jobs = [(os.path.join(folder, "%s_%s%s" % (
                    stem, table, recipe["extension"])), [table])
                    for table in tables]
            for target, layers in jobs:
                if not translate(target, origin,
                                 options(layers, driver, stage is None),
                                 driver):
                    failed += layers
                    continue
                written.append((target, layers))
                if rewrite and not rewrite_coordinates(target, origin,
                                                       layers, driver):
                    log("the coordinates of %s are left as GDAL wrote them, "
                        "with fifteen digits" % os.path.basename(target))
                if driver == "CSV":
                    defuse_csv(target)
        finally:
            if stage is not None:
                shutil.rmtree(stage, ignore_errors=True)

    # Read back, every format, how many features of each table came out with
    # their geometry. GDAL is told to skip what it cannot write rather than
    # stop, and what it skips would be nowhere to be seen: a feature it cannot
    # reproject comes out with no geometry, a table it cannot reproject at
    # all comes out empty, and either file would be said written. A table that lost
    # shapes is said; a file that holds none of what it was asked for is taken
    # away and called a failure.
    wanted = feature_counts(source, where) or {}
    for target, layers in list(written):
        got = feature_counts(target)
        if got is None:
            continue
        asked = [t for t in layers if wanted.get(t)]
        empty = []
        for table in asked:
            have = got.get(table, 0) if len(layers) > 1 \
                else sum(got.values())
            if have >= wanted[table]:
                continue
            notes.append("%s: %d of the %d features of %s came out with "
                         "their geometry"
                         % (os.path.basename(target), have, wanted[table],
                            table))
            if have == 0:
                empty.append(table)
        if asked and len(empty) == len(asked):
            remove_output(target, driver)
            written.remove((target, layers))
            failed += layers
            notes.append("%s held nothing and was taken away"
                         % os.path.basename(target))
        else:
            failed += empty

    # Read back, every format: a polygon valid in the package and not in the
    # file is said, table by table, and not left to be found in another
    # program. One that was already invalid in the package is no news.
    before = invalid_polygons(source, where)
    for target, layers in written:
        after = invalid_polygons(target)
        for name, bad in sorted(after.items()):
            table = layers[0] if len(layers) == 1 else name
            more = bad - before.get(table, 0)
            if more > 0:
                notes.append("%s: %d polygon%s of %s came out invalid"
                             % (os.path.basename(target), more,
                                "" if more == 1 else "s", table))
    for note in notes:
        log(note, loud=True)
    return [t for t, _ in written], failed, notes


def write_per_operator(source, recipe, stem):
    """write_vectors once for each operator, every pass of that operator in
    the same files, the operator in their names: <stem>_<OPERATOR>_<table>.

    Each set is written the way a single reading is (write_reading), so the
    pass stays an attribute of every mark and every check on the way out is
    the one the other exports have. The three lists come back joined."""
    written, failed, notes = [], [], []
    for one in operator_sets(recipe["reading"]["readings"]):
        choice = {"mode": "one", "readings": one["readings"],
                  "tag": one["tag"], "label": one["operator"]}
        w, f, n = write_reading(source, dict(recipe, arrange=None,
                                             reading=choice),
                                "%s_%s" % (stem, one["tag"]))
        written += w
        failed += [t for t in f if t not in failed]
        notes += n
    return written, failed, notes


# What a format writes beside its main file, which belongs to the export as
# much as the file does: the type and projection files of a CSV, the parts of
# a shapefile.
SIDECARS = (".csvt", ".prj", ".cpg", ".dbf", ".shx")


def pack_zip(folder, files, name):
    """Every file an export wrote, and what goes beside each, in one .zip in
    the folder. Returns (its path, how many files it holds).

    The names inside are relative to the folder, with forward slashes, so the
    archive says nothing of where it was made. Written under a temporary name
    and renamed when whole: a crash or a full disk leaves the old archive as
    it was, or none, never half of one. Raises OSError, with the temporary
    file taken away."""
    members = {}
    for path in files:
        base = os.path.splitext(path)[0]
        for each in [path] + [base + s for s in SIDECARS]:
            if os.path.isfile(long_path(each)):
                arc = os.path.relpath(each, folder).replace(os.sep, "/")
                if not arc.startswith(".."):
                    members[arc] = each
    target = os.path.join(folder, name)
    tmp = target + ".tmp"
    try:
        with open(long_path(tmp), "wb") as raw:
            with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as pack:
                for arc in sorted(members):
                    pack.write(long_path(members[arc]), arc)
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(long_path(tmp), long_path(target))
    except Exception as err:
        try:
            if os.path.exists(long_path(tmp)):
                os.remove(long_path(tmp))
        except OSError:
            pass
        raise OSError("the archive could not be written: %s" % err)
    return target, len(members)


def write_reading(source, recipe, stem):
    """write_vectors for one reading, or for a consensus.

    The tables are first copied into a GeoPackage of their own holding only
    what goes out: the reading chosen, narrowed to the frame when one was
    asked for, with the polygons replaced by their consensus when that was
    asked for. That copy is then written out the way the whole package
    always is, so every format, every digit and every check on the way out
    is the same for a reading as for the campaign."""
    stage = tempfile.mkdtemp(prefix="rasterlabel_reading_")
    try:
        staged = os.path.join(stage, "reading.gpkg")
        try:
            narrowed_package(source, staged, recipe["tables"],
                             recipe.get("tile_id"), recipe["reading"])
        except Exception as err:
            log("cannot narrow the package to %s: %s"
                % (recipe["reading"].get("label", "the reading"), err),
                loud=True)
            return [], list(recipe["tables"]), []
        return write_vectors(staged, dict(recipe, reading=None, tile_id=None),
                             stem)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def narrowed_package(source, target, tables, tile_id, choice):
    """A GeoPackage of the chosen tables holding only the chosen readings.

    A mark is in a reading by its operator and its pass, read through the
    same operator_word and pass_number as everywhere else, so "Massi" with no
    pass and "MASSI" in pass 1 are one reading here too. The frames belong
    to nobody and go out whole; the tile filter applies to them as it
    always did."""
    mode = choice.get("mode", "all")
    keep = {tuple(r) for r in choice.get("readings") or []}
    src = ogr.Open(source)
    if src is None:
        raise IOError("cannot read %s" % os.path.basename(source))
    out = ogr.GetDriverByName("GPKG").CreateDataSource(target)
    if out is None:
        raise IOError("cannot make a working copy for the reading")
    try:
        for table in tables:
            lyr = src.GetLayerByName(table)
            if lyr is None:
                continue
            defn = lyr.GetLayerDefn()
            new = out.CreateLayer(table, lyr.GetSpatialRef(),
                                  defn.GetGeomType(), ["GEOMETRY_NAME=geom"])
            for i in range(defn.GetFieldCount()):
                new.CreateField(defn.GetFieldDefn(i))
            frame = defn.GetFieldIndex("tile_id")
            if mode == "consensus" and table == "polygons":
                for name in ("votes", "readings"):
                    if defn.GetFieldIndex(name) < 0:
                        new.CreateField(ogr.FieldDefn(name, ogr.OFTInteger))
                made = new.GetLayerDefn()
                # the pass, when every reading in the vote is of one pass
                passes = sorted({p for _, p in keep})
                one_pass = passes[0] if len(passes) == 1 else None
                # a frame is voted by the readings that covered it; one frame
                # asked for is measured alone
                voters = consensus_voters(
                    source, keep, shares=reading_shares(source, [tile_id])
                    if tile_id else None)
                for row in consensus_polygons(lyr, keep, tile_id, voters):
                    f = ogr.Feature(made)
                    f.SetGeometry(row["geometry"])
                    for name, value in (
                            ("class_name", row["class_name"]),
                            ("class_code", row["class_code"]),
                            ("tile_id", row["tile_id"]),
                            ("pass_no", one_pass),
                            ("operator", "CONSENSUS"),
                            ("created", now()),
                            ("votes", row["votes"]),
                            ("readings", row["readings"])):
                        if made.GetFieldIndex(name) >= 0 and value is not None:
                            f.SetField(name, value)
                    new.CreateFeature(f)
                    f = None
                continue
            who = defn.GetFieldIndex("operator")
            when = defn.GetFieldIndex("pass_no")
            made = new.GetLayerDefn()
            for f in lyr:
                if tile_id and (frame < 0
                                or str(f.GetField(frame)) != str(tile_id)):
                    continue
                if table in READING_TABLES and (
                        operator_word(f.GetField(who) if who >= 0 else None),
                        pass_number(f.GetField(when) if when >= 0 else None)) \
                        not in keep:
                    continue
                copy = ogr.Feature(made)
                copy.SetFrom(f)
                new.CreateFeature(copy)
                copy = None
            new = None
            lyr = None
    finally:
        out = None
        src = None


def polygonal(geom):
    """The polygons of a geometry, as one multipolygon, or None.

    An intersection of two polygons that share a border holds that border as
    a line too, and a multipolygon table cannot take a collection."""
    if geom is None or geom.IsEmpty():
        return None
    kind = ogr.GT_Flatten(geom.GetGeometryType())
    if kind == ogr.wkbPolygon:
        out = ogr.ForceToMultiPolygon(geom.Clone())
    elif kind == ogr.wkbMultiPolygon:
        out = geom.Clone()
    elif kind == ogr.wkbGeometryCollection:
        out = ogr.Geometry(ogr.wkbMultiPolygon)
        for i in range(geom.GetGeometryCount()):
            part = polygonal(geom.GetGeometryRef(i))
            if part is not None:
                for j in range(part.GetGeometryCount()):
                    out.AddGeometry(part.GetGeometryRef(j))
    else:
        return None
    if out.IsEmpty() or out.GetArea() <= 0:
        return None
    return out


def solid(geom):
    """polygonal(), with nothing as an empty multipolygon rather than None,
    for the sums that go on being worked on."""
    out = polygonal(geom)
    return out if out is not None else ogr.Geometry(ogr.wkbMultiPolygon)


def consensus_polygons(layer, readings, tile_id=None, voters=None):
    """The ground a strict majority of these readings give the same class,
    frame by frame, split by how many of them do.

    The same rule as the consensus of the whole raster, on the geometry
    instead of on the pixels: inside one reading the mark drawn last wins
    where two overlap, as it does when the reading is burned, and a piece
    of ground goes out in a class when more than half of the readings give
    it that class. Each row says how many did, in votes, out of how many,
    in readings. Ground the readings do not agree on goes out in no class.

    voters is campaign.consensus_voters' answer: the readings of a frame are
    those that covered it, so a frame read by 2 of 4 readings is voted by
    those 2 and the row says "readings: 2". None: every reading votes in
    every frame."""
    readings = [tuple(r) for r in readings]
    defn = layer.GetLayerDefn()
    who = defn.GetFieldIndex("operator")
    when = defn.GetFieldIndex("pass_no")
    frame = defn.GetFieldIndex("tile_id")
    code_at = defn.GetFieldIndex("class_code")
    name_at = defn.GetFieldIndex("class_name")
    ground, names = {}, {}
    layer.ResetReading()
    for f in layer:
        g = f.GetGeometryRef()
        if g is None or g.IsEmpty():
            continue
        r = (operator_word(f.GetField(who) if who >= 0 else None),
             pass_number(f.GetField(when) if when >= 0 else None))
        if r not in readings:
            continue
        tid = f.GetField(frame) if frame >= 0 else None
        if tile_id and str(tid) != str(tile_id):
            continue
        try:
            code = int(f.GetField(code_at) or 0)
        except (TypeError, ValueError):
            code = 0
        if code <= 0:
            continue
        if name_at >= 0:
            names.setdefault(code, f.GetField(name_at))
        own = ground.setdefault((tid, r), {})
        g = polygonal(g)
        if g is None:
            continue
        for other in list(own):
            if other != code:
                left = polygonal(own[other].Difference(g))
                if left is None:
                    del own[other]
                else:
                    own[other] = left
        own[code] = solid(own[code].Union(g)) if code in own else g
    out = []
    for tid in sorted({t for t, _ in ground}, key=lambda t: str(t)):
        here = voters_in(voters, tid, readings)
        readings_here = [r for r in readings if r in here]
        n = len(readings_here)
        need = majority(n)
        codes = sorted({c for (t, r), own in ground.items()
                        if t == tid and r in here for c in own})
        for code in codes:
            # levels[k] is the ground at least k + 1 of the readings give
            # this class, built one reading at a time
            levels = []
            for r in readings_here:
                g = ground.get((tid, r), {}).get(code)
                if g is None or g.IsEmpty():
                    continue
                top = len(levels)
                new_top = (solid(levels[top - 1].Intersection(g)) if top
                           else None)
                for k in range(top - 1, 0, -1):
                    levels[k] = solid(levels[k].Union(
                        solid(levels[k - 1].Intersection(g))))
                if top:
                    levels[0] = solid(levels[0].Union(g))
                else:
                    levels.append(g)
                if new_top is not None:
                    levels.append(new_top)
            for k in range(need, len(levels) + 1):
                piece = levels[k - 1]
                if k < len(levels) and not levels[k].IsEmpty():
                    piece = piece.Difference(levels[k])
                piece = polygonal(piece)
                if piece is None:
                    continue
                out.append({"geometry": piece, "class_code": code,
                            "class_name": names.get(code), "tile_id": tid,
                            "votes": k, "readings": n})
    return out
