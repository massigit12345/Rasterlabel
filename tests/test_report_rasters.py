"""The maps of the reports, written for real and read back with GDAL, and
the window every report is shown in.

- rr_open and rr_finish write a one band GeoTIFF of codes: DEFLATE with the
  horizontal predictor, tiled, nodata 0, the band named, the grid and the
  system given; a Byte map carries its colour table and the names of its
  classes, a wider one does not, and both get a .qml beside them that
  lists only the codes that are in the map;
- rr_pair_entries gives one entry per pair of codes, value 1 + i*K + j, the
  diagonal "same: <name>" in one grey, a pair that differs "<A> → <B>" in
  B's colour, and 0 for no entry at all: with codes [0, 1, 2] the pair
  (1, 2) is 6;
- the report window shows an undefined value as a dash, copies the headline
  and the tables as tab separated text, and the Where rows of a setup
  window hold the folder and "put the maps in QGIS".
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

os.environ["RL_KIT_REAL_GDAL"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import correctkit as K                                             # noqa: E402
import numpy as np                                                 # noqa: E402
from osgeo import gdal, osr                                        # noqa: E402

g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_report_rasters_")
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)
WKT = srs.ExportToWkt()
GT = (500000.0, 1.0, 0.0, 4140010.0, 0.0, -1.0)


def palette(qml):
    root_ = ET.parse(qml).getroot()
    return [(int(e.get("value")), e.get("label"), e.get("color"))
            for e in root_.iter("paletteEntry")]


print("a Byte map of codes")
path = os.path.join(root, "aragona_agreement_ANNA_p1_vs_BRUNO_p1_disagreement.tif")
classes = [dict(c) for c in g["DISAGREEMENT_CLASSES"]]
values = np.zeros((300, 300), np.uint8)
values[10:20, 10:20] = 1
values[30:40, 30:40] = 2
ds = g["rr_open"](path, GT, 300, 300, WKT, "Byte", 0, "disagreement")
ds.GetRasterBand(1).WriteArray(values)
present = {1, 2}
for c in classes:
    c["present"] = c["code"] in present
qml = g["rr_finish"](ds, path, classes, {"rasterlabel:report": "agreement"})
ds = None
ds = gdal.Open(path)
band = ds.GetRasterBand(1)
check("it is a GeoTIFF of one band of bytes",
      ds.GetDriver().ShortName == "GTiff" and ds.RasterCount == 1
      and band.DataType == gdal.GDT_Byte)
structure = ds.GetMetadata("IMAGE_STRUCTURE")
check("compressed with DEFLATE and the predictor",
      structure.get("COMPRESSION") == "DEFLATE"
      and structure.get("PREDICTOR") == "2", structure)
check("tiled", band.GetBlockSize()[0] < 300 and band.GetBlockSize()[1] < 300,
      band.GetBlockSize())
check("nodata 0, the band named",
      band.GetNoDataValue() == 0 and band.GetDescription() == "disagreement",
      (band.GetNoDataValue(), band.GetDescription()))
check("on the grid and in the system it was given",
      ds.GetGeoTransform() == GT and "32633" in ds.GetProjection())
check("the codes as written", (band.ReadAsArray() == values).all())
table = band.GetColorTable()
check("the colours are in the file",
      table is not None and table.GetColorEntry(1)[:3] == (0x1b, 0xaf, 0x7a)
      and table.GetColorEntry(2)[:3] == (0xd6, 0x35, 0x7a),
      None if table is None else [table.GetColorEntry(i) for i in (1, 2)])
names = band.GetCategoryNames() or []
check("and so are the names of the codes that are in it",
      names[1:3] == ["agree", "disagree"], names)
check("the report's word is in the metadata, under a key GDAL keeps whole",
      ds.GetMetadataItem("rasterlabel_report") == "agreement",
      ds.GetMetadata())
ds = band = None
check("a .qml beside it, of the same name",
      qml == os.path.splitext(path)[0] + ".qml" and os.path.isfile(qml), qml)
check("listing only the codes in the map, with their names and colours",
      palette(qml) == [(1, "agree", "#1baf7a"), (2, "disagree", "#d6357a")],
      palette(qml))

print()
print("a map of pairs wider than a byte")
codes = list(range(0, 17))                   # 17 x 17 = 289 pairs: UInt16
names = {c: "class %d" % c for c in codes}
names[0] = "unlabelled"
colours = {c: "#%02x%02x%02x" % (c * 10, 255 - c * 10, 128) for c in codes}
entries = g["rr_pair_entries"](codes, names, colours, present=[1, 19, 289])
path2 = os.path.join(root, "aragona_agreement_x_pairs.tif")
ds = g["rr_open"](path2, GT, 64, 64, WKT, np.dtype("uint16"), 0, "pairs")
pairs = np.zeros((64, 64), np.uint16)
pairs[0, 0], pairs[1, 1], pairs[2, 2] = 1, 19, 289
ds.GetRasterBand(1).WriteArray(pairs)
qml2 = g["rr_finish"](ds, path2, entries)
ds = None
ds = gdal.Open(path2)
check("it is UInt16", ds.GetRasterBand(1).DataType == gdal.GDT_UInt16)
check("with no colour table, which a GeoTIFF of that type cannot hold",
      ds.GetRasterBand(1).GetColorTable() is None)
check("and its values as written",
      (ds.GetRasterBand(1).ReadAsArray() == pairs).all())
ds = None
check("its .qml carries the three pairs that are there, by name",
      palette(qml2) == [(1, "same: unlabelled", "#c8c8c8"),
                        (19, "same: class 1", "#c8c8c8"),
                        (289, "same: class 16", "#c8c8c8")], palette(qml2))
try:
    g["rr_type"]("float32")
    refused = False
except ValueError:
    refused = True
check("a float map is not a map of codes: refused", refused)

print()
print("the pairs")
entries = g["rr_pair_entries"]([0, 1, 2], {0: "unlabelled", 1: "crust",
                                           2: "water"},
                               {0: "#ffffff", 1: "#b0651f", 2: "#2f6f9f"})
by = {e["code"]: e for e in entries}
check("one entry per pair of codes, 1 to K*K",
      sorted(by) == list(range(1, 10)), sorted(by))
check("the pair (crust, water) is 1 + 1*3 + 2 = 6",
      by[6]["a"] == 1 and by[6]["b"] == 2, by[6])
check("named A → B, in B's colour",
      by[6]["name"] == "crust → water" and by[6]["colour"] == "#2f6f9f",
      by[6])
check("the diagonal is the same class, in one grey",
      [by[v]["name"] for v in (1, 5, 9)]
      == ["same: unlabelled", "same: crust", "same: water"]
      and {by[v]["colour"] for v in (1, 5, 9)} == {"#c8c8c8"})
check("0 is no entry: outside and nodata are transparent", 0 not in by)
check("and every pair is there when none is said to be missing",
      all(e["present"] for e in entries))
check("the value of a pair is the one the agreement writes",
      g["rr_pair_value"](1, 2, 3) == 6 and g["rr_pair_value"](0, 0, 3) == 1)
listed = g["rr_pair_entries"]([3, 7], ["crops", "roads"],
                              ["#e6c229", "#444444"], present=[2])
check("names and colours may come as lists in the order of the codes",
      [(e["code"], e["name"], e["colour"], e["present"]) for e in listed]
      == [(1, "same: crops", "#c8c8c8", False),
          (2, "crops → roads", "#444444", True),
          (3, "roads → crops", "#e6c229", False),
          (4, "same: roads", "#c8c8c8", False)], listed)

print()
print("the window every report is shown in")
nan = float("nan")
w = g["ReportWindow"](None, "Compare two readings", "11 frames · 440 000 px",
                      [("overall agreement", 0.912345), ("kappa", nan),
                       ("frames", 11)],
                      [{"title": "Per class", "columns": ["class", "IoU"],
                        "rows": [["crust", 0.8], ["water", None]],
                        "colours": ["#b0651f", "#2f6f9f"]}],
                      ["Kappa is an agreement statistic."], folder=root)
check("titled as the program's windows are",
      w.windowTitle() == "RasterLabel: Compare two readings", w.windowTitle())
view = w.views[0]
check("a table per part, with a swatch of the class first",
      view.rowCount() == 2 and view.columnCount() == 3
      and view.item(0, 0).background().color().name() == "#b0651f")
check("an undefined value is a dash, never a zero",
      view.item(1, 2).text() == "—", view.item(1, 2).text())
check("a number is drawn with fixed decimals: 0.8 is 0.800",
      view.item(0, 2).text() == "0.800", view.item(0, 2).text())
text = w.text()
check("Copy is the headline and the tables, tab separated",
      "overall agreement\t0.9123" in text and "kappa\t—" in text
      and "class\tIoU" in text and "crust\t0.8" in text
      and "water\t—" in text, text)
check("and the notes", text.rstrip().endswith(
    "Kappa is an agreement statistic."), text)
check("Open folder is there when there is a folder", w.b_folder.isEnabled())
w.copy()
check("and Copy puts it on the clipboard",
      K.QtWidgets.QApplication.clipboard().text() == text)
check("a number that is not one is a dash",
      g["report_shown"](float("inf")) == "—" and g["report_shown"](None)
      == "—" and g["report_shown"](3) == "3")

print()
print("the tables of the window are tidy")
AR = K.QtCore.Qt.AlignmentFlag.AlignRight
w2 = g["ReportWindow"](
    None, "Model vs corrected: whole map", "1258300 px, 3146.75 m²",
    [("ratio", 0.9889), ("amount", 31.4159), ("count", 12020), ("tiny", 2e-5)],
    [{"title": "Per class", "columns": ["class", "IoU", "PA", "m²", "px"],
      "rows": [["crust", 0.9889, 1, 20.5, 8200],
               ["a class with a very long name indeed", 1.0, 0.5, 9.3, 3720],
               ["water", 0.0123, None, 1234.5, 1258300]],
      "colours": ["#b0651f", "#2f6f9f", "#f2e500"]}], ["a note"], folder=root)
t = w2.views[0]
check("a column of ratios has three decimals, a 1 is 1.000",
      [t.item(r, 2).text() for r in range(3)] == ["0.989", "1.000", "0.012"],
      [t.item(r, 2).text() for r in range(3)])
check("a column with a dash keeps its decimals",
      [t.item(r, 3).text() for r in range(3)] == ["1.000", "0.500", "—"],
      [t.item(r, 3).text() for r in range(3)])
check("amounts have two decimals and the thousands set apart",
      [t.item(r, 4).text() for r in range(3)]
      == ["20.50", "9.30", "1 234.50"], [t.item(r, 4).text() for r in range(3)])
check("counts are whole numbers with the thousands set apart",
      [t.item(r, 5).text() for r in range(3)]
      == ["8 200", "3 720", "1 258 300"],
      [t.item(r, 5).text() for r in range(3)])
check("numbers and their headers are right aligned, names left",
      all(int(t.item(r, c).textAlignment()) & int(AR)
          for r in range(3) for c in (2, 3, 4, 5))
      and int(t.horizontalHeaderItem(2).textAlignment()) & int(AR)
      and not int(t.item(0, 1).textAlignment()) & int(AR))
check("the headline: ratios to three decimals, amounts to two, counts apart",
      [v.text() for v in w2.findChildren(K.QtWidgets.QLabel)
       if v.font().bold() and v.text()][:4]
      == ["0.989", "31.42", "12 020", "2.0e-05"],
      [v.text() for v in w2.findChildren(K.QtWidgets.QLabel)
       if v.font().bold()])
check("Copy keeps the plain figures, for a spreadsheet",
      "crust	0.9889	1	20.5	8200" in w2.text(), w2.text())
w2.show()
K.app.processEvents()
rows_high = t.horizontalHeader().height() + sum(t.rowHeight(r)
                                                 for r in range(3))
check("the table is as tall as its rows, and does not scroll",
      abs(t.height() - rows_high) <= 2 * t.frameWidth() + 20
      and not t.verticalScrollBar().isVisible(), (t.height(), rows_high))
check("the swatch column is the narrowest",
      t.columnWidth(0) < min(t.columnWidth(c) for c in range(1, 6)),
      [t.columnWidth(c) for c in range(6)])
check("it opens at least 300 wide and can be made no narrower than that",
      w2.width() >= 300 and w2.minimumWidth() == 300,
      (w2.width(), w2.minimumWidth()))
w2.resize(300, w2.height())
K.app.processEvents()
check("at 300 px nothing of the table is cut at its foot",
      t.height() >= rows_high, (t.height(), rows_high))
many = g["ReportWindow"](None, "x", "", [], [{"columns": ["a", "b"], "rows": [
    ["r%d" % i, i] for i in range(40)]}], [])
check("a long table scrolls instead of growing without end",
      many.views[0].sizeHint().height() < 40 * many.views[0].rowHeight(0))
check("the helpers: thousands set apart, a share as a percentage, a count",
      g["report_number"](3146.75, "f2") == "3 146.75"
      and g["report_number"](0.5, "pct") == "50.0 %"
      and g["report_screen"](7) == "7")

host = K.QtWidgets.QDialog()
grid = K.QtWidgets.QGridLayout(host)
target = os.path.join(root, "reports", "agreement", "ANNA_p1_vs_BRUNO_p1_x")
row, field, maps = g["report_where_rows"](grid, 4, target)
check("the Where rows: the folder the report will be written in",
      field.text() == target)
check("and put the maps in QGIS, ticked", maps.isChecked()
      and maps.text() == "put the maps in QGIS", maps.text())
check("three rows taken", row == 7, row)

sys.exit(K.finish())
