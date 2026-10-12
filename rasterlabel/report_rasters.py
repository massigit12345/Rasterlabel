"""rasterlabel.report_rasters

The categorical GeoTIFFs of the reports and their styles.

Every map a report writes is a raster of codes, one band, and nothing else: a
disagreement map (agree, disagree, only A, only B, neither), a map of pairs
(which class of A met which class of B), whatever a measure needs to show
where. They are all written the same way: compressed and tiled, with nodata
0 for the ground outside what was measured, the band named, the colours in
the file when the type allows a colour table (Byte only, in GeoTIFF), and
always a .qml beside it, so QGIS opens it with its classes and their names
whatever the type. The .qml lists only the codes that are there: a legend of
two hundred pairs nobody met would be a list to scroll, not a legend.

A report is written in a folder of its own named .tmp until it is whole
(reports.report_folder), so nothing here writes under a temporary name.
"""
import os

from osgeo import gdal
from qgis.PyQt.QtGui import QColor

from .naming import long_path
from .rasters import open_raster, style_of, write_style

RR_CREATION = ["COMPRESS=DEFLATE", "PREDICTOR=2", "TILED=YES",
               "BIGTIFF=IF_SAFER", "SPARSE_OK=TRUE"]
# The diagonal of a map of pairs, where A and B said the same: one quiet
# grey for all of them, so that what stands out is where they differ.
RR_SAME_COLOUR = "#c8c8c8"
RR_UNKNOWN_COLOUR = "#808080"
RR_ARROW = "→"
# The types a map of codes may have, by name; GDAL's own number for each is
# looked up when it is wanted.
RR_TYPES = {"byte": "GDT_Byte", "uint8": "GDT_Byte", "uint16": "GDT_UInt16",
            "uint32": "GDT_UInt32", "int16": "GDT_Int16", "int32": "GDT_Int32"}


def rr_type(dtype):
    """A GDAL type from a GDAL type, a numpy dtype or its name."""
    if isinstance(dtype, int):
        return dtype
    name = getattr(dtype, "name", None) or str(dtype)
    found = RR_TYPES.get(name.lower())
    if found is not None:
        found = getattr(gdal, found, None)
    if found is None:
        raise ValueError("no categorical GeoTIFF of type %s" % name)
    return found


def rr_open(path, gt, w, h, wkt, dtype, nodata=0, band_name="code"):
    """A new one band GeoTIFF of codes at path, open for writing: DEFLATE
    with the horizontal predictor, tiled, BigTIFF when it has to be, and
    sparse, so the ground outside what was measured costs nothing."""
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(long_path(path), int(w), int(h), 1, rr_type(dtype),
                       RR_CREATION)
    if ds is None:
        raise IOError("cannot write %s: %s"
                      % (os.path.basename(path), gdal.GetLastErrorMsg()))
    ds.SetGeoTransform(tuple(gt))
    if wkt:
        ds.SetProjection(wkt)
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    if band_name:
        band.SetDescription(str(band_name))
    return ds


def rr_entry_colour(entry):
    col = QColor(str(entry.get("colour") or ""))
    return col if col.isValid() else QColor(RR_UNKNOWN_COLOUR)


def rr_key(name):
    """A metadata key as GDAL keeps it whole: rasterlabel:report becomes
    rasterlabel_report."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in str(name))


def _rr_close(ds):
    """Close a dataset now, whoever else still holds the handle (the caller
    of rr_open does): until it is, the last tiles are not in the file.
    Close() is GDAL 3.8 and later; before it, the caller lets go."""
    close = getattr(ds, "Close", None)
    if callable(close):
        close()


def rr_finish(ds, path, entries, metadata=None, embed_table=True):
    """Close a map opened by rr_open and give it its classes: the colour
    table and the names in the file when it is Byte, and a .qml beside it
    in any case, with the entries that are there (an entry may say
    "present": False). Returns the path of the .qml. The handle is closed:
    it is not to be used again."""
    entries = [e for e in (entries or []) if e.get("present", True)]
    embed = bool(embed_table and entries
                 and ds.GetRasterBand(1).DataType == gdal.GDT_Byte)
    ds.FlushCache()
    _rr_close(ds)
    ds = None
    # The colours, the names and the tags go in once the codes are written
    # and the file is closed: a GeoTIFF refuses a colour table on a band
    # already written in the same session ("cannot modify tag
    # PhotometricInterpretation while writing").
    if embed or metadata:
        ds = open_raster(long_path(path), gdal.GA_Update)
        if ds is None:
            raise IOError("cannot finish %s: %s"
                          % (os.path.basename(path), gdal.GetLastErrorMsg()))
        band = ds.GetRasterBand(1)
        if embed:
            table = gdal.ColorTable()
            names = [""] * 256
            for e in entries:
                code = int(e["code"])
                if 0 <= code <= 255:
                    c = rr_entry_colour(e)
                    table.SetColorEntry(code,
                                        (c.red(), c.green(), c.blue(), 255))
                    names[code] = str(e.get("name") or "")
            band.SetColorTable(table)
            band.SetColorInterpretation(gdal.GCI_PaletteIndex)
            top = max(int(e["code"]) for e in entries)
            band.SetCategoryNames(names[:top + 1])
        if metadata:
            # GDAL reads "a:b=c" as the item a with the value "b=c": a key
            # keeps letters, digits and underscores, so it reads back whole
            ds.SetMetadata({rr_key(k): str(v) for k, v in metadata.items()})
        band = None
        _rr_close(ds)
        ds = None
    qml = style_of(path)
    write_style(qml, 1, [{"code": int(e["code"]), "name": e.get("name", ""),
                          "colour": rr_entry_colour(e).name()}
                         for e in entries])
    return qml


def _rr_lookup(values, codes, code, default):
    """A name or a colour for a code, from a dict by code or from a list in
    the order of codes."""
    if isinstance(values, dict):
        return values.get(code, default)
    try:
        return values[list(codes).index(code)]
    except (ValueError, IndexError, TypeError):
        return default


def rr_pair_value(i, j, k):
    """The code of the pair (A's class at index i, B's at index j) among k
    codes: 1 + i*k + j. 0 is left for outside and nodata."""
    return 1 + int(i) * int(k) + int(j)


def rr_pair_entries(codes, names, colours, present=None):
    """The entries of a map of pairs: one per pair of codes, in the order
    of their values. The diagonal is "same: <name>" in one grey; a pair
    that differs is "<A's name> → <B's name>" in the colour of B, the
    reading taken as the reference. 0 is not an entry: it is transparent.
    present, a collection of values, marks the pairs that are in the map
    (entries not in it carry "present": False); None marks them all."""
    codes = [int(c) for c in codes]
    k = len(codes)
    wanted = None if present is None else {int(v) for v in present}
    out = []
    for i, a in enumerate(codes):
        name_a = str(_rr_lookup(names, codes, a, "unlabelled" if a == 0
                                else "class %d" % a))
        for j, b in enumerate(codes):
            value = rr_pair_value(i, j, k)
            name_b = str(_rr_lookup(names, codes, b, "unlabelled" if b == 0
                                    else "class %d" % b))
            if i == j:
                name, colour = "same: %s" % name_a, RR_SAME_COLOUR
            else:
                name = "%s %s %s" % (name_a, RR_ARROW, name_b)
                colour = _rr_lookup(colours, codes, b, RR_UNKNOWN_COLOUR)
            out.append({"code": value, "name": name, "colour": colour,
                        "a": a, "b": b,
                        "present": wanted is None or value in wanted})
    return out
