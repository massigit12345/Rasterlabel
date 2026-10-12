"""The correction of a thematic map is a thematic map.

A model's map often carries more than its classes: the one this suite builds
is laid out like the land cover maps Correct is used on, five bands of bytes,
the class first, then the probability and the entropy scaled to 255, a
validity mask and the class before sieving, nodata 0 on every band, in
geographic coordinates, tiled and compressed, the names of its bands in its
.aux.xml and a .qml beside it that QGIS opens it with: a Paletted style on
band 1, four classes, opacity 0.7.

The working copy used to be that map plus a sixth band, "corrected", with no
style, and QGIS opened it as a picture: class on red, probability on green,
entropy on blue. So this suite makes a correction of that map through the
panel, with real files read and written by GDAL and QGIS faked, and asks:

  the copy is the map band for band: the same bands in the same order, with
  the same names, type, nodata, grid, coordinate system, tiles, compression
  and interleave, every pixel the same, and nothing added;
  a .qml beside it draws band 1 in the classes of the correction, paletted,
  at the opacity the original's .qml set;
  the class band carries the classes as a colour table and category names,
  for the programs that are not QGIS;
  which pixels a person changed is a raster beside the copy, named in
  correction.json, written by a stroke and taken back by Undo;
  a class added, a code adopted from the map and a colour changed in the
  classes window reach the .qml and the colour table at once;
  a working copy, and the record of its changes, are refused as maps to
  correct, with the reason; a fresh copy sets the old one aside with its
  record and its style;
  a working copy of the earlier build, six bands and the "corrected" one
  last, opens as a correction of five bands: the band moves out to the file
  beside it pixel for pixel, the copy is rewritten without it and compared
  before it replaces the old one, its .aux.xml loses the band, the manifest
  is told and the log says it in one line; and when the rewrite is stopped
  half way, the copy is exactly as it was and opening it again finishes
  the job; the user is told on the message bar, also that their own layer of
  the old copy had to leave the project;
  a style the user set on the corrected map (opacity, blend mode) survives
  the next open, class change and close;
  a map whose bands differ in type is copied in the type that holds them
  all, Int32 for UInt16 and Int16, negative values and nodata kept, and a
  copy that would change a value is refused;
  a conversion killed just before or just after the new copy replaces the
  old one, with the class band after the flag band, leaves a manifest that
  points at the right band and an .aux.xml that belongs to the copy, once
  it is opened again;
  Set aside in a folder shared with an annotation campaign moves only the
  correction's files.

Needs the GDAL Python bindings. QGIS is faked, see correctkit.py; the suite
that opens the corrected map in a real QGIS is test_correct_qgis_style.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import shutil
import sys
import tempfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                                 # noqa: E402
from osgeo import gdal, osr                                        # noqa: E402
import correctkit as K                                             # noqa: E402

gdal.UseExceptions()
g, check = K.g, K.check

root = tempfile.mkdtemp(prefix="rl_correct_thematic_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])
data = os.path.join(root, "output")
os.makedirs(data)

NX, NY = 150, 100
GT = (13.597001325635429, 5.6448e-07, 0.0, 37.377110918744194, 0.0,
      -4.50488e-07)
NAMES = ["classe", "probabilita x255", "entropia x255", "validita",
         "classe senza setaccio"]
CLASSES = [(1, "#2b3a4a", "fango fresco"), (2, "#e8e2d5", "fango secco"),
           (3, "#d9a441", "suolo"), (4, "#2f7b5f", "vegetazione")]
srs = osr.SpatialReference()
srs.ImportFromEPSG(4326)

rng = np.random.default_rng(11)
CLASS = rng.integers(1, 5, (NY, NX)).astype(np.uint8)
CLASS[:10, :] = 0                                       # a strip of nodata
BANDS = [CLASS,
         np.where(CLASS > 0, rng.integers(66, 256, (NY, NX)), 0).astype(np.uint8),
         np.where(CLASS > 0, rng.integers(1, 255, (NY, NX)), 0).astype(np.uint8),
         (CLASS > 0).astype(np.uint8),
         np.where(CLASS > 0, rng.integers(1, 5, (NY, NX)), 0).astype(np.uint8)]


def write_thematic(path):
    """The map, the way the model wrote it: the pixels and the grid in the
    GeoTIFF, the names of the bands and their statistics in .aux.xml, as
    GDAL keeps them for a file opened only to be read."""
    ds = gdal.GetDriverByName("GTiff").Create(
        path, NX, NY, 5, gdal.GDT_Byte,
        ["COMPRESS=LZW", "TILED=YES", "BLOCKXSIZE=64", "BLOCKYSIZE=64",
         "INTERLEAVE=PIXEL"])
    ds.SetGeoTransform(GT)
    ds.SetProjection(srs.ExportToWkt())
    for i, a in enumerate(BANDS):
        ds.GetRasterBand(i + 1).WriteArray(a)
        ds.GetRasterBand(i + 1).SetNoDataValue(0)
    ds.GetRasterBand(1).SetColorInterpretation(gdal.GCI_GrayIndex)
    ds = None
    ds = gdal.Open(path)
    for i, name in enumerate(NAMES):
        ds.GetRasterBand(i + 1).SetDescription(name)
    ds.GetRasterBand(1).ComputeStatistics(False)
    ds = None


source = os.path.join(data, "72_mappa_fold.tif")
write_thematic(source)
with open(os.path.join(data, "72_mappa_fold.qml"), "w", encoding="utf-8") as f:
    f.write('<qgis><pipe><rasterrenderer type="paletted" band="1" '
            'opacity="0.7">\n<colorPalette>\n'
            + "".join('<paletteEntry value="%d" color="%s" label="%s"/>\n'
                      % c for c in CLASSES)
            + "</colorPalette>\n</rasterrenderer></pipe></qgis>")
style = K.Paletted(None, 1, [K.Paletted.Class(v, c, n) for v, c, n in CLASSES])
layer = K.add_layer(K.Layer(source, "72_mappa_fold", renderer=style,
                            lid="layer_map"))
before_source = {f: open(os.path.join(data, f), "rb").read()
                 for f in os.listdir(data)}

panel = g["Panel"]()
SEEN = {}
ASKS = []
PRESS = []


def answer_box(d):
    labels = [b.text().replace("&", "") for b in d.buttons()]
    ASKS.append((d.text(), d.informativeText(), labels))
    want = PRESS.pop(0) if PRESS else "Cancel"
    for b in d.buttons():
        if b.text().replace("&", "") == want:
            b.click()
            break
    K.ANSWERS["QMessageBox"] = answer_box
    return 0


def new_on(lay, folder, name="fix"):
    def fill(d):
        d.existing.setCurrentIndex(d.existing.findData("new:"))
        d.name.setText(name)
        d.raster.setCurrentIndex(d.raster.findData(lay.id()))
        d.fill_bands()
        d.folder.setText(folder)
        d.operator.setText("ann")
        return 1
    return fill


def press(*labels, classes=True):
    del ASKS[:]
    PRESS[:] = list(labels)
    K.ANSWERS["QMessageBox"] = answer_box
    if classes:
        K.ANSWERS["ConfirmClasses"] = lambda d: 1
    K.BOXES.clear()
    panel.toggle_module(1)
    K.ANSWERS.pop("QMessageBox", None)
    K.ANSWERS.pop("ConfirmClasses", None)
    return panel.section


def structure(path):
    """What a GIS sees of a raster before it reads a pixel."""
    ds = gdal.Open(path)
    out = {"size": (ds.RasterXSize, ds.RasterYSize),
           "gt": ds.GetGeoTransform(),
           "srs": osr.SpatialReference(wkt=ds.GetProjection())
           .GetAuthorityCode(None),
           "layout": {k: v for k, v in
                      (ds.GetMetadata("IMAGE_STRUCTURE") or {}).items()
                      if k in ("COMPRESSION", "INTERLEAVE")},
           "bands": [(ds.GetRasterBand(b).GetDescription(),
                      gdal.GetDataTypeName(ds.GetRasterBand(b).DataType),
                      ds.GetRasterBand(b).GetNoDataValue(),
                      tuple(ds.GetRasterBand(b).GetBlockSize()))
                     for b in range(1, ds.RasterCount + 1)]}
    ds = None
    return out


def pixels(path, band):
    ds = gdal.Open(path)
    out = ds.GetRasterBand(band).ReadAsArray()
    ds = None
    return out


def palette_of(qml):
    """(band, opacity, [(code, colour, name)]) of the paletted renderer of a
    .qml, read as QGIS reads it: by its elements."""
    import xml.etree.ElementTree as ET
    r = ET.parse(qml).getroot().find("pipe/rasterrenderer")
    return (r.get("type"), int(r.get("band")), float(r.get("opacity")),
            [(int(e.get("value")), e.get("color"), e.get("label"))
             for e in r.find("colorPalette")])


def colour_table(path, band=1):
    ds = gdal.Open(path)
    b = ds.GetRasterBand(band)
    ct = b.GetColorTable()
    entries = ([ct.GetColorEntry(i)[:4] for i in range(ct.GetCount())]
               if ct is not None else None)
    names = list(b.GetCategoryNames() or [])
    interp = gdal.GetColorInterpretationName(b.GetColorInterpretation())
    ds = None
    return entries, names, interp


def hexes(entries, codes):
    return {v: "#%02x%02x%02x" % entries[v][:3] for v in codes}


try:
    print("a correction of a thematic map of five bands, through the panel")
    folder = os.path.join(root, "correction_1")
    K.ANSWERS["OpenCorrection"] = new_on(layer, folder, "correction_1")
    section = press()
    check("Correct opened on it", type(section).__name__ == "CorrectionSection",
          (K.BOXES, K.UNEXPECTED))
    copy = os.path.join(folder, "72_mappa_fold_corrected.tif")
    changes = os.path.join(folder, "72_mappa_fold_corrected_changes.tif")
    qml = os.path.join(folder, "72_mappa_fold_corrected.qml")

    print()
    print("the copy is the map, band for band")
    want, got = structure(source), structure(copy)
    check("the same bands in the same order, names, type, nodata and tiles",
          got["bands"] == want["bands"], (got["bands"], want["bands"]))
    check("five of them, and not a sixth", len(got["bands"]) == 5,
          len(got["bands"]))
    check("the same size and grid, to the last decimal",
          got["size"] == want["size"] and got["gt"] == want["gt"],
          (got["gt"], want["gt"]))
    check("the same coordinate system", got["srs"] == want["srs"] == "4326",
          (got["srs"], want["srs"]))
    check("compressed and interleaved the same way",
          got["layout"] == want["layout"] == {"COMPRESSION": "LZW",
                                              "INTERLEAVE": "PIXEL"},
          (got["layout"], want["layout"]))
    check("every pixel of every band the same",
          all(np.array_equal(pixels(copy, b + 1), a)
              for b, a in enumerate(BANDS)))
    ds = gdal.Open(copy)
    check("and the statistics of the class band, about to change, left "
          "behind", not any(k.startswith("STATISTICS_") for k in
                            (ds.GetRasterBand(1).GetMetadata() or {})),
          ds.GetRasterBand(1).GetMetadata())
    ds = None
    check("the original is byte for byte what it was, and its folder too",
          {f: open(os.path.join(data, f), "rb").read()
           for f in os.listdir(data)} == before_source,
          sorted(os.listdir(data)))

    print()
    print("it opens like the original: its .qml, and its colour table")
    check("a .qml beside the copy", os.path.exists(qml), os.listdir(folder))
    kind, band, opacity, palette = palette_of(qml)
    check("paletted on band 1, at the opacity of the original's .qml",
          (kind, band, opacity) == ("paletted", 1, 0.7), (kind, band, opacity))
    check("with the classes of the correction: code, colour and name",
          palette == list(CLASSES), palette)
    entries, names, interp = colour_table(copy)
    check("the class band carries them as a colour table",
          entries is not None and hexes(entries, [1, 2, 3, 4])
          == {v: c for v, c, _ in CLASSES}, entries)
    check("nodata and every value that is no class are clear",
          entries is not None and entries[0][3] == 0, entries)
    check("and as category names", names[1:5] == [n for _, _, n in CLASSES]
          and names[0] == "", names)
    check("read as a palette by GDAL", interp == "Palette", interp)
    check("kept in .aux.xml, the one place GDAL keeps a table for a TIFF of "
          "several bands", "<ColorTable>" in open(copy + ".aux.xml",
                                                  encoding="utf-8").read())

    print()
    print("which pixels a person changed is beside it, not inside it")
    book = json.load(open(os.path.join(folder, "correction.json"),
                          encoding="utf-8"))
    check("correction.json names the record of changes",
          book.get("changes") == "72_mappa_fold_corrected_changes.tif", book)
    check("which starts empty, on the grid of the copy",
          os.path.exists(changes) and not pixels(changes, 1).any()
          and structure(changes)["gt"] == GT)
    inside = np.zeros((30, 40), bool)
    inside[:, :] = True
    section.mask_of = lambda geom: (20, 30, inside)     # rows 30-59, cols 20-59
    section.choose_from(4)
    section.choose_class(1)
    section.paint(K.Stroke())
    window = BANDS[0][30:60, 20:60]
    moved = window == 4
    after = pixels(copy, 1)
    check("the stroke changed vegetazione into fango fresco in the copy",
          (after[30:60, 20:60][moved] == 1).all()
          and int((after != BANDS[0]).sum()) == int(moved.sum()),
          int((after != BANDS[0]).sum()))
    marks = pixels(changes, 1)
    check("and marked exactly those pixels in the record beside it",
          int(marks.sum()) == int(moved.sum())
          and (marks[30:60, 20:60].astype(bool) == moved).all(),
          (int(marks.sum()), int(moved.sum())))
    check("the other bands are untouched",
          all(np.array_equal(pixels(copy, b + 1), BANDS[b])
              for b in range(1, 5)))
    section.undo()
    check("Undo takes it back from the copy",
          np.array_equal(pixels(copy, 1), BANDS[0]))
    check("and from the record of changes", not pixels(changes, 1).any())
    section.paint(K.Stroke())
    check("painted again, marked again",
          int(pixels(changes, 1).sum()) == int(moved.sum()))

    print()
    print("the classes change, and the .qml and the colour table follow")
    section.adopt([7], "a code met in the map,")
    kind, band, opacity, palette = palette_of(qml)
    check("a code adopted from the map is in the .qml",
          7 in [v for v, _, _ in palette], palette)
    entries, names, _ = colour_table(copy)
    check("and in the colour table, with its name",
          entries is not None and len(entries) == 8 and entries[7][3] == 255
          and names[7] == section.class_of(7)["name"], (entries, names))
    section.classes()[3]["colour"] = "#10067b"           # vegetazione
    section.classes_changed()
    check("a colour changed in the classes window reaches the .qml",
          palette_of(qml)[3][3][1] == "#10067b", palette_of(qml)[3])
    entries, _, _ = colour_table(copy)
    check("and the colour table", entries and hexes(entries, [4])
          == {4: "#10067b"}, entries and entries[4])
    check("the opacity of the original is still the one",
          palette_of(qml)[2] == 0.7)
    panel.close_module()
    check("closing leaves the style as the classes are",
          palette_of(qml)[3][3][1] == "#10067b"
          and hexes(colour_table(copy)[0], [4]) == {4: "#10067b"})
    check("and the folder holds the corrected map, its style and its record",
          {"72_mappa_fold_corrected.tif", "72_mappa_fold_corrected.tif.aux.xml",
           "72_mappa_fold_corrected.qml", "72_mappa_fold_corrected_changes.tif",
           "correction.json", "operations.csv"} <= set(os.listdir(folder))
          and not [f for f in os.listdir(folder) if ".partial" in f],
          sorted(os.listdir(folder)))

    print()
    print("a working copy, or its record, is no map to correct")
    copy_layer = K.add_layer(K.Layer(copy, "copy", lid="layer_copy"))
    K.ANSWERS["OpenCorrection"] = new_on(copy_layer,
                                         os.path.join(root, "again"), "again")
    press("Cancel", classes=False)
    check("the copy is refused, with the record beside it as the reason",
          ASKS and "already the working copy" in ASKS[0][0]
          and "72_mappa_fold_corrected_changes.tif beside it records which "
              "pixels a person changed" in ASKS[0][0], ASKS)
    check("and its owner is offered", ASKS and ASKS[0][2] ==
          ["Open the correction that owns it", "Cancel"], ASKS)
    K.LOADED.pop(copy_layer.id(), None)
    check("the record itself is refused too",
          "record of which pixels a person changed" in
          (g["why_a_working_copy"](changes) or ""),
          g["why_a_working_copy"](changes))
    check("and the original is not a copy", g["why_a_working_copy"](source)
          is None, g["why_a_working_copy"](source))

    print()
    print("a fresh copy sets the old one aside, with its record and style")
    loose = os.path.join(root, "loose")
    os.makedirs(loose)
    for f in ("72_mappa_fold_corrected.tif", "72_mappa_fold_corrected.tif.aux.xml",
              "72_mappa_fold_corrected.qml",
              "72_mappa_fold_corrected_changes.tif", "operations.csv"):
        shutil.copy2(os.path.join(folder, f), loose)
    K.ANSWERS["OpenCorrection"] = new_on(layer, loose, "loose")
    press("Make a new correction", "Start from a fresh copy")
    check("it was offered to be resumed or started afresh",
          ASKS and ASKS[-1][2] == ["Resume it", "Start from a fresh copy",
                                   "Cancel"], ASKS)
    spare = [f for f in os.listdir(loose) if f.startswith("set_aside_")]
    check("the old copy, its .aux.xml, its .qml, its record and its log are "
          "set aside together",
          len(spare) == 1 and sorted(os.listdir(os.path.join(loose, spare[0])))
          == ["72_mappa_fold_corrected.qml", "72_mappa_fold_corrected.tif",
              "72_mappa_fold_corrected.tif.aux.xml",
              "72_mappa_fold_corrected_changes.tif", "operations.csv"],
          (os.listdir(loose), spare))
    check("and the new copy is the map again",
          np.array_equal(pixels(os.path.join(loose,
                                             "72_mappa_fold_corrected.tif"), 1),
                         BANDS[0]))
    panel.close_module()

    print()
    print("a working copy of the earlier build: six bands, 'corrected' last")
    old = os.path.join(root, "old_build")
    os.makedirs(old)
    legacy = os.path.join(old, "72_mappa_fold_corrected.tif")
    # Made exactly as build_copy made it then: every band of the map, their
    # names, nodata, colour interpretation wiped, LZW in tiles, and one byte
    # band more, named "corrected".
    ds = gdal.GetDriverByName("GTiff").Create(
        legacy, NX, NY, 6, gdal.GDT_Byte,
        ["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"])
    ds.SetGeoTransform(GT)
    ds.SetProjection(srs.ExportToWkt())
    painted = BANDS[0].copy()
    painted[50:70, 100:130] = np.where(painted[50:70, 100:130] > 0, 3, 0)
    flag = (painted != BANDS[0]).astype(np.uint8)
    for i, a in enumerate([painted] + BANDS[1:]):
        b = ds.GetRasterBand(i + 1)
        b.WriteArray(a)
        b.SetDescription(NAMES[i])
        b.SetNoDataValue(0)
        b.SetColorInterpretation(gdal.GCI_Undefined)
    ds.GetRasterBand(6).WriteArray(flag)
    ds.GetRasterBand(6).SetDescription("corrected")
    ds = None
    ds = gdal.Open(legacy)             # and the statistics QGIS left in .aux.xml
    for b in range(1, 7):
        ds.GetRasterBand(b).ComputeStatistics(True)
    ds = None
    check("it is the shape the earlier build left",
          len(structure(legacy)["bands"]) == 6
          and structure(legacy)["bands"][5][0] == "corrected"
          and "band=\"6\"" in open(legacy + ".aux.xml", encoding="utf-8").read())
    with open(os.path.join(old, "operations.csv"), "w", encoding="utf-8") as f:
        f.write(",".join(g["CorrectionSection"].LOG_COLUMNS) + "\n")
    manifest = os.path.join(old, "correction.json")
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump({"program": "RasterLabel", "kind": "correction",
                   "format": 1, "version": "1.1", "id": "62d83bfd3ca3",
                   "name": "correction_1", "operator": "OPERATOR 1",
                   "operators": ["OPERATOR 1"], "source": source, "band": 1,
                   "working_copy": "72_mappa_fold_corrected.tif",
                   "nodata": 0.0,
                   "classes": [{"code": v, "name": n, "colour": c}
                               for v, c, n in CLASSES],
                   "operations": 1, "changed_m2": 1.0, "swept_m2": 1.0,
                   "pairs": {}}, f, indent=2)
    legacy_bytes = open(legacy, "rb").read()
    legacy_aux = open(legacy + ".aux.xml", "rb").read()

    # Stopped half way: the moment the rewritten copy would take the old
    # one's place, the rename fails, as it does when another program holds
    # the file open on Windows.
    real_replace = os.replace

    def refuse(a, b):
        if os.path.normcase(os.path.abspath(b)) == \
                os.path.normcase(os.path.abspath(legacy)):
            raise PermissionError(32, "the file is in use", b)
        return real_replace(a, b)

    os.replace = refuse
    try:
        K.BOXES.clear()
        book = panel.open_existing("open", manifest)
        check("the correction opens from its manifest",
              book is not None and panel.correction is book)
        panel.toggle_module(1)
    finally:
        os.replace = real_replace
    check("a rewrite that cannot take the copy's place stops the module, "
          "and says nothing was changed",
          panel.section is None and any("Nothing was changed" in t
                                        for _, t in K.BOXES), K.BOXES)
    check("the copy is byte for byte as it was, six bands and all",
          open(legacy, "rb").read() == legacy_bytes
          and open(legacy + ".aux.xml", "rb").read() == legacy_aux)
    check("and nothing half written is left beside it",
          not [f for f in os.listdir(old) if ".partial" in f
               or f.endswith("-bands")], os.listdir(old))
    stopped = json.load(open(manifest, encoding="utf-8"))
    check("the manifest, told before the rename, is put back as it was",
          stopped.get("band") == 1 and "changes_moved_out" not in stopped,
          stopped)
    panel.close_correction()

    print()
    print("opened again, it is brought to the bands of the map it corrects")
    # The user had the old copy in the project, as a picture: it has to
    # leave the project for the file to be replaced, and they are told.
    old_layer = K.add_layer(K.Layer(legacy, "my old copy", lid="layer_old"))
    del K.SAID[:]
    book = panel.open_existing("open", manifest)
    panel.toggle_module(1)
    section = panel.section
    check("Correct opens on it", type(section).__name__ == "CorrectionSection",
          K.BOXES)
    check("the message bar says the copy is being converted, before it is",
          any("converting 72_mappa_fold_corrected.tif" in t for t in K.SAID),
          K.SAID)
    check("and that the user's layer of the old copy was taken out",
          any("72_mappa_fold_corrected.tif converted" in t
              and "Your layer of the old copy was taken out" in t
              for t in K.SAID), K.SAID)
    check("which it was", old_layer.id() not in K.LOADED,
          sorted(K.LOADED))
    got = structure(legacy)
    check("the copy now has the five bands of the map, named as they are",
          [b[0] for b in got["bands"]] == NAMES, got["bands"])
    check("and its type, nodata, grid and coordinate system",
          [b[1:3] for b in got["bands"]] == [("Byte", 0.0)] * 5
          and got["gt"] == GT and got["srs"] == "4326")
    check("the corrected classes are pixel for pixel what they were",
          np.array_equal(pixels(legacy, 1), painted))
    check("and every other band too",
          all(np.array_equal(pixels(legacy, b + 1), BANDS[b])
              for b in range(1, 5)))
    moved_out = os.path.join(old, "72_mappa_fold_corrected_changes.tif")
    check("its 'corrected' band is beside it, pixel for pixel",
          os.path.exists(moved_out)
          and np.array_equal(pixels(moved_out, 1), flag))
    check("the same number of changed pixels as the band held",
          int(pixels(moved_out, 1).sum()) == int(flag.sum()) > 0,
          (int(pixels(moved_out, 1).sum()), int(flag.sum())))
    aux = open(legacy + ".aux.xml", encoding="utf-8").read()
    check("its .aux.xml no longer speaks of a sixth band, nor of the old "
          "statistics of the class band",
          'band="6"' not in aux and "STATISTICS_MAXIMUM" not in
          aux.split('band="2"')[0], aux[:400])
    data_now = json.load(open(manifest, encoding="utf-8"))
    check("the manifest names the record and says when the band moved out",
          data_now.get("changes") == "72_mappa_fold_corrected_changes.tif"
          and data_now.get("changes_moved_out", {}).get("pixels")
          == int(flag.sum())
          and data_now["changes_moved_out"].get("from_band") == 6, data_now)
    log_text = open(os.path.join(old, "rasterlabel.log"),
                    encoding="utf-8").read()
    check("one line of the log says it, with the count",
          log_text.count("brought to the bands of the map it corrects") == 1
          and "%d pixels a person changed" % int(flag.sum()) in log_text,
          [l for l in log_text.splitlines() if "brought" in l])
    kind, band, opacity, palette = palette_of(
        os.path.join(old, "72_mappa_fold_corrected.qml"))
    check("and it now opens paletted, with its classes",
          (kind, band) == ("paletted", 1) and palette == list(CLASSES),
          (kind, band, palette))
    check("a stroke marks the record beside it",
          section.marks is not None and np.asarray(section.marks).sum() == flag.sum())
    text, bad, notes = g["report"](None, panel.correction, campaign_too=False)
    check("Check says the copy has the bands of the map, in its order",
          "the working copy has the 5 bands of the map it corrects" in text,
          [l for l in text.splitlines() if "band" in l])
    check("and what the record beside it holds",
          "72_mappa_fold_corrected_changes.tif records %d pixels changed"
          % int(flag.sum()) in text, [l for l in text.splitlines()
                                      if "changes" in l])
    panel.close_module()
    check("opened once more, nothing moves again",
          panel.open_existing("open", manifest) is not None)
    panel.toggle_module(1)
    log_text = open(os.path.join(old, "rasterlabel.log"),
                    encoding="utf-8").read()
    check("the log still says it once",
          log_text.count("brought to the bands of the map it corrects") == 1)
    panel.close_module()

    print()
    print("a style set on the corrected map in QGIS is kept")
    # Save as Default in QGIS writes exactly <map>_corrected.qml. It used to
    # be rewritten from the original's .qml at every open, save, close and
    # class change, and the user's opacity went back to the original's.
    import xml.etree.ElementTree as ET
    tree = ET.parse(qml)
    rr = tree.getroot().find("pipe/rasterrenderer")
    rr.set("opacity", "0.42")
    ET.SubElement(tree.getroot(), "blendMode").text = "6"
    tree.write(qml, encoding="unicode")
    manifest_1 = os.path.join(folder, "correction.json")
    panel.open_existing("open", manifest_1)
    panel.toggle_module(1)
    section = panel.section
    check("the correction opens again",
          type(section).__name__ == "CorrectionSection", K.BOXES)
    check("and its .qml keeps the opacity set in QGIS",
          palette_of(qml)[2] == 0.42, palette_of(qml)[:3])
    section.adopt([9], "a code met in the map,")
    check("a class added keeps it too, and is in the .qml",
          palette_of(qml)[2] == 0.42
          and 9 in [v for v, _, _ in palette_of(qml)[3]], palette_of(qml))
    panel.close_module()
    root_el = ET.parse(qml).getroot()
    check("closing keeps it, and the blend mode the user set",
          palette_of(qml)[2] == 0.42
          and root_el.find("blendMode") is not None
          and root_el.find("blendMode").text == "6", palette_of(qml)[:3])
    check("while the renderer is still paletted on the class band",
          palette_of(qml)[:2] == ("paletted", 1), palette_of(qml)[:2])
    with open(qml, "w", encoding="utf-8") as f:
        f.write("<qgis><pipe><rasterrenderer")              # cut short
    g["dress_copy"](copy, 1, [{"code": v, "name": n, "colour": c}
                              for v, c, n in CLASSES], source)
    check("a .qml that no longer reads gives way to the original's",
          palette_of(qml)[:3] == ("paletted", 1, 0.7), palette_of(qml)[:3])

    print()
    print("a map whose bands differ in type")
    # A VRT of a UInt16 band and an Int16 band with negative values and a
    # nodata of -1. Chosen by bit size alone, the copy was UInt16, and every
    # negative value of the second band, its nodata among them, became 0.
    mixed_dir = os.path.join(root, "mixed")
    os.makedirs(mixed_dir)
    u16 = (np.arange(NX * NY).reshape(NY, NX) % 4 + 1).astype(np.uint16)
    i16 = (np.arange(NX * NY).reshape(NY, NX) % 700 - 350).astype(np.int16)
    i16[:5, :] = -1
    parts = []
    for name, arr, kind, nd in (("u16", u16, gdal.GDT_UInt16, None),
                                ("i16", i16, gdal.GDT_Int16, -1)):
        path = os.path.join(mixed_dir, name + ".tif")
        ds = gdal.GetDriverByName("GTiff").Create(path, NX, NY, 1, kind)
        ds.SetGeoTransform(GT)
        ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).WriteArray(arr)
        if nd is not None:
            ds.GetRasterBand(1).SetNoDataValue(nd)
        ds = None
        parts.append(path)
    vrt = os.path.join(mixed_dir, "mixed.vrt")
    gdal.BuildVRT(vrt, parts, separate=True).FlushCache()
    ds = gdal.Open(vrt)
    check("the source has a UInt16 band and an Int16 band",
          [gdal.GetDataTypeName(ds.GetRasterBand(b).DataType)
           for b in (1, 2)] == ["UInt16", "Int16"])
    ds = None
    mixed_copy = os.path.join(mixed_dir, "mixed_corrected.tif")
    notes = []
    g["build_copy"](vrt, mixed_copy, notes, band_no=1)
    ds = gdal.Open(mixed_copy)
    kinds = [gdal.GetDataTypeName(ds.GetRasterBand(b).DataType)
             for b in (1, 2)]
    check("the copy uses Int32, which holds both, not UInt16",
          kinds == ["Int32", "Int32"], kinds)
    check("the negative values of the Int16 band are still there",
          np.array_equal(ds.GetRasterBand(2).ReadAsArray(), i16)
          and np.array_equal(ds.GetRasterBand(1).ReadAsArray(), u16))
    check("and so is its nodata of -1",
          ds.GetRasterBand(2).GetNoDataValue() == -1,
          ds.GetRasterBand(2).GetNoDataValue())
    ds = None
    check("the log says which type, and why",
          notes and "Int32" in notes[0], notes)
    # A type that cannot hold them, as a GDAL without DataTypeUnion could
    # pick: the copy is compared with the source and refused.
    real_union = gdal.DataTypeUnion
    gdal.DataTypeUnion = lambda a, b: gdal.GDT_UInt16
    refused = None
    narrow = os.path.join(mixed_dir, "narrow_corrected.tif")
    try:
        g["build_copy"](vrt, narrow, [], band_no=1)
    except IOError as err:
        refused = str(err)
    finally:
        gdal.DataTypeUnion = real_union
    check("a copy that would change a value is refused, saying where",
          refused is not None and "band 2" in refused, refused)
    check("and leaves nothing behind",
          not [f for f in os.listdir(mixed_dir) if f.startswith("narrow")],
          os.listdir(mixed_dir))

    print()
    print("a conversion stopped between its steps, class band after the flag")

    class Killed(BaseException):
        """What a QGIS killed by the user looks like to the code it was
        running: nothing after this point runs, no except clause catches
        it, no finally of the program's puts anything back."""

    def legacy_flag_first(where):
        """A copy of the earlier build whose 'corrected' band is band 1 and
        the class band 2, with the statistics QGIS left in its .aux.xml,
        and the correction.json that says band 2."""
        os.makedirs(where)
        path = os.path.join(where, "72_mappa_fold_corrected.tif")
        ds = gdal.GetDriverByName("GTiff").Create(
            path, NX, NY, 6, gdal.GDT_Byte,
            ["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"])
        ds.SetGeoTransform(GT)
        ds.SetProjection(srs.ExportToWkt())
        ds.GetRasterBand(1).WriteArray(flag)
        ds.GetRasterBand(1).SetDescription("corrected")
        for i, a in enumerate([painted] + BANDS[1:]):
            b = ds.GetRasterBand(i + 2)
            b.WriteArray(a)
            b.SetDescription(NAMES[i])
            b.SetNoDataValue(0)
        ds = None
        ds = gdal.Open(path)
        for b in range(1, 7):
            ds.GetRasterBand(b).ComputeStatistics(True)
        ds = None
        with open(os.path.join(where, "correction.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"program": "RasterLabel", "kind": "correction",
                       "format": 1, "version": "1.1", "id": "a1b2c3d4e5f6",
                       "name": "flag_first", "operator": "OPERATOR 1",
                       "operators": ["OPERATOR 1"], "source": source,
                       "band": 2,
                       "working_copy": "72_mappa_fold_corrected.tif",
                       "nodata": 0.0,
                       "classes": [{"code": v, "name": n, "colour": c}
                                   for v, c, n in CLASSES],
                       "operations": 1, "changed_m2": 1.0, "swept_m2": 1.0,
                       "pairs": {}}, f, indent=2)
        return path

    def kill_at_swap(path, after):
        """os.replace that kills the run at the rename of the new copy over
        the old one: before it is done, or right after."""
        def replace(a, b):
            if os.path.normcase(os.path.abspath(b)) == \
                    os.path.normcase(os.path.abspath(path)):
                if after:
                    real_replace(a, b)
                raise Killed()
            return real_replace(a, b)
        return replace

    def run_killed(path, after):
        book = g["CorrectionCampaign"].open(os.path.dirname(path))
        os.replace = kill_at_swap(path, after)
        died = False
        try:
            g["bring_up_to_date"](path, book.data["band"], book.data, book)
        except Killed:
            died = True
        finally:
            os.replace = real_replace
        return died

    def reopen(path):
        book = g["CorrectionCampaign"].open(os.path.dirname(path))
        g["bring_up_to_date"](path, book.data["band"], book.data, book)
        return g["CorrectionCampaign"].open(os.path.dirname(path)).data

    # Killed before the rename: the manifest has already been told band 1,
    # and the copy is still the old one, whose class band is band 2.
    first = legacy_flag_first(os.path.join(root, "flag_first_before"))
    check("killed just before the new copy takes the old one's place",
          run_killed(first, after=False))
    on_disk = json.load(open(os.path.join(os.path.dirname(first),
                                          "correction.json"), encoding="utf-8"))
    check("the manifest was told the new class band before the rename, and "
          "keeps the old one",
          on_disk.get("band") == 1
          and on_disk.get("changes_moved_out", {}).get("band_before") == 2,
          on_disk)
    check("the old copy is still there, six bands",
          len(structure(first)["bands"]) == 6)
    data_after = reopen(first)
    got = structure(first)
    check("opened again, the conversion uses the band the old copy had",
          [b[0] for b in got["bands"]] == NAMES and data_after["band"] == 1,
          (got["bands"], data_after.get("band")))
    check("and the class band of the manifest holds the corrected classes",
          np.array_equal(pixels(first, data_after["band"]), painted))
    check("the changes are beside it, pixel for pixel",
          np.array_equal(pixels(g["changes_of"](first), 1), flag))
    check("and its .aux.xml was given back to it and then replaced",
          not [f for f in os.listdir(os.path.dirname(first))
               if f.endswith("-bands")], os.listdir(os.path.dirname(first)))

    # Killed right after the rename: the manifest already names band 1, and
    # the old .aux.xml, with a sixth band and the old statistics of the
    # class band, must not stay with the new copy.
    second_kill = legacy_flag_first(os.path.join(root, "flag_first_after"))
    check("killed right after the new copy took the old one's place",
          run_killed(second_kill, after=True))
    on_disk = json.load(open(os.path.join(os.path.dirname(second_kill),
                                          "correction.json"), encoding="utf-8"))
    check("the manifest already names the class band of the new copy",
          on_disk.get("band") == 1, on_disk.get("band"))
    check("band 1 of the copy is that class band",
          np.array_equal(pixels(second_kill, 1), painted)
          and structure(second_kill)["bands"][0][0] == "classe")
    data_after = reopen(second_kill)
    aux_path = second_kill + ".aux.xml"
    aux = (open(aux_path, encoding="utf-8").read()
           if os.path.exists(aux_path) else "")
    check("opened again, the old .aux.xml is gone: no sixth band",
          'band="6"' not in aux and not [
              f for f in os.listdir(os.path.dirname(second_kill))
              if f.endswith("-bands")], (aux[:300],
                                         os.listdir(os.path.dirname(second_kill))))
    ds = gdal.Open(second_kill)
    check("and no statistics of the class band from before the correction",
          not any(k.startswith("STATISTICS_") for k in
                  (ds.GetRasterBand(1).GetMetadata() or {})),
          ds.GetRasterBand(1).GetMetadata())
    check("its bands are named as the map's, from the copy itself",
          [ds.GetRasterBand(b).GetDescription() for b in range(1, 6)]
          == NAMES)
    ds = None
    check("and the manifest still names band 1", data_after["band"] == 1,
          data_after.get("band"))

    print()
    print("Set aside in a folder shared with an annotation campaign")
    shared = os.path.join(root, "TEST_SHARED")
    K.ANSWERS["OpenCorrection"] = new_on(layer, shared, "shared")
    section = press("Make a new correction")
    check("a correction made in it",
          type(section).__name__ == "CorrectionSection", (ASKS, K.BOXES))
    # The annotation campaign the user made in the same folder.
    for name in ("campaign.json", "annotation.gpkg", "image.tif"):
        with open(os.path.join(shared, name), "w", encoding="utf-8") as f:
            f.write(name)
    ours = sorted(f for f in os.listdir(shared)
                  if f not in ("campaign.json", "annotation.gpkg",
                               "image.tif", "rasterlabel.log"))
    section.delete()
    check("the folder is not renamed",
          os.path.isdir(shared) and not [
              f for f in os.listdir(root) if f.startswith("TEST_SHARED.removed-")],
          os.listdir(root))
    check("the annotation campaign is where it was",
          all(os.path.exists(os.path.join(shared, n))
              for n in ("campaign.json", "annotation.gpkg", "image.tif")),
          os.listdir(shared))
    spare = [f for f in os.listdir(shared) if f.startswith("set_aside_")]
    check("and the correction's own files are in a set_aside_ folder in it",
          len(spare) == 1 and sorted(os.listdir(os.path.join(shared, spare[0])))
          == ours, (spare, ours, spare and os.listdir(
              os.path.join(shared, spare[0]))))
    check("which include correction.json, the copy, its .qml and its record",
          {"correction.json", "72_mappa_fold_corrected.tif",
           "72_mappa_fold_corrected.qml",
           "72_mappa_fold_corrected_changes.tif"} <= set(ours), ours)
    check("the module is closed, and the correction with it",
          panel.section is None and panel.correction is None)
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
