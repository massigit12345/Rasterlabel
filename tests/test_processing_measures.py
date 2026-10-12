"""The other measures in the Processing toolbox, in a real QGIS.

Besides rasterlabel:agreement the toolbox has the rest of the Measure menu,
so that the numbers of a paper can be made again from a script, a model or
a batch, without the panel: rasterlabel:model_vs_corrected, :time_report,
:uncertainty_report and :dataset_card. Each runs through processing.run on
small campaigns and corrections that this suite builds (tests/fixtures/
impact.py and a correction with an uncertainty of its own), with values
that can be worked out by hand:

- the provider holds the five algorithms, in a group of their own, with
  their parameters named in capitals and their numbers among the outputs;
- Model vs corrected on a 10 x 10 map, 10 pixels changed from class 2 to 1:
  the whole map gives overall accuracy 0.9 and quantity 0.1; the ground
  swept (the changed pixels) 0; two polygons, 0.8, and the selected one
  alone 0.6; the map of pairs is written; another person's correction and
  an agreement report come out beside the model's numbers; what it refuses
  (no polygons, a map of another size, a correction of another map, a
  missing copy) is refused in words with nothing written;
- Time on the shared campaign and a journal worked out by hand: 222 s of
  active time at 60 s, the frames by the three rules, a correction set
  beside it, a correction alone, and the refusals;
- Uncertainty on a map with an uncertainty source and a walk of places: the
  AUC is the one worked out from the pixels, the ECE and the random places
  are those of the engine, and a correction with no uncertainty, or one
  whose file of uncertainty is gone, is refused;
- the Dataset card of a campaign and of a correction, and the panel's
  blind gate over a campaign's readings;
- through all of them the inputs are only read: every file of the campaign
  or the correction, the manifest included, has the bytes and the time it
  had, no report is listed in a manifest, and the only thing added is a
  folder under reports/ (or the one named by OUTPUT_FOLDER).

Needs QGIS itself (tests/run.py, NEEDS_QGIS), on Qt 5 and Qt 6 alike.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROFILE = tempfile.mkdtemp(prefix="rl_processing_measures_profile_")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = PROFILE
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(HERE, "fixtures"))

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)[:600]) if not cond and detail != "" else ""),
          flush=True)
    if not cond:
        fails.append(name)


def finish():
    print()
    print("FAILED: %d" % len(fails) if fails else "all pass", flush=True)
    for f in fails:
        print("   " + f)
    sys.stdout.flush()
    os._exit(1 if fails else 0)


try:
    import qgis
    from qgis.core import (Qgis, QgsApplication, QgsFeature, QgsGeometry,
                           QgsProcessingException, QgsProcessingFeedback,
                           QgsVectorLayer)
    from qgis.PyQt.QtCore import QSettings
except ImportError as e:
    print("QGIS is not importable here: %s" % e)
    sys.exit(1)

import numpy as np                                                 # noqa: E402
from osgeo import gdal, osr                                        # noqa: E402

gdal.UseExceptions()
QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                  PROFILE)
app = QgsApplication([], False)
app.initQgis()
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(qgis.__file__))), "plugins"))
import processing                                                  # noqa: E402
from processing.core.Processing import Processing                  # noqa: E402
Processing.initialize()
import impact as F                                                 # noqa: E402
print("QGIS %s" % Qgis.QGIS_VERSION)

root = tempfile.mkdtemp(prefix="rl_processing_measures_")


def snapshot(folder, skip=("reports",)):
    """{relative path: (sha256, mtime)} of every file under folder but the
    reports/ the algorithms add, and the sorted names of what is directly
    in it."""
    files = {}
    for here, dirs, names in os.walk(folder):
        if os.path.relpath(here, folder) == ".":
            dirs[:] = [d for d in dirs if d not in skip]
        for n in names:
            p = os.path.join(here, n)
            with open(p, "rb") as fh:
                files[os.path.relpath(p, folder)] = (
                    hashlib.sha256(fh.read()).hexdigest(),
                    os.path.getmtime(p))
    return files


def listing(folder):
    return sorted(os.listdir(folder))


def only_reports_added(folder, top):
    """Nothing in folder but a reports/ folder is new since top."""
    return sorted(set(listing(folder)) - set(top)) in ([], ["reports"])         and set(top) <= set(listing(folder))


def manifest_of(folder, name):
    with open(os.path.join(folder, name), encoding="utf-8") as fh:
        return json.load(fh)


class Feedback(QgsProcessingFeedback):
    said = []

    def reportError(self, error, fatalError=False):  # noqa: N802
        self.said.append(error)

    def pushInfo(self, info):  # noqa: N802
        self.said.append(info)


def run(name, **params):
    del Feedback.said[:]
    return processing.run("rasterlabel:" + name, params, feedback=Feedback())


def refused(name, **params):
    """The words of the QgsProcessingException a run raises, or None."""
    try:
        run(name, **params)
    except QgsProcessingException as err:
        return str(err) + " " + " ".join(Feedback.said)
    except Exception as err:
        return "not a QgsProcessingException: %r" % err
    return None


def good(text):
    return text is not None and not text.startswith("not a Qgs")


def reports_of(folder):
    base = os.path.join(folder, "reports")
    return sorted(os.listdir(base)) if os.path.isdir(base) else []


# ---------------------------------------------------------------- provider
print("the provider")
import rasterlabel                                                 # noqa: E402
from rasterlabel import launch                                     # noqa: E402
plugin = rasterlabel.classFactory(None)
plugin.initProcessing()
registry = QgsApplication.processingRegistry()
provider = registry.providerById("rasterlabel")
check("the plugin puts RasterLabel in the toolbox", provider is not None)
NAMES = ("agreement", "model_vs_corrected", "time_report",
         "uncertainty_report", "dataset_card")
algs = {n: registry.algorithmById("rasterlabel:" + n) for n in NAMES}
check("with the five algorithms of the Measure menu",
      all(a is not None for a in algs.values()),
      [n for n, a in algs.items() if a is None])
check("in a group of their own, Measure",
      all(a.group() == "Measure" and a.groupId() == "measure"
          for a in algs.values() if a is not None))
check("each with a plain help string that says nothing is written in the "
      "campaign or correction",
      all(len(algs[n].shortHelpString()) > 400 for n in NAMES[1:]
          if algs[n] is not None)
      and all("only read" in algs[n].shortHelpString() for n in NAMES[1:]
              if algs[n] is not None))
check("and says it never lists the report in the manifest",
      all("manifest" in algs[n].shortHelpString() for n in NAMES[1:]
          if algs[n] is not None))


def parameters_of(name):
    return [p.name() for p in algs[name].parameterDefinitions()]


def outputs_of(name):
    return sorted(o.name() for o in algs[name].outputDefinitions())


check("model_vs_corrected: its parameters",
      parameters_of("model_vs_corrected") == [
          "CORRECTION", "SCOPE", "POLYGONS", "SELECTED_ONLY", "PEOPLE",
          "WRITE_MAP", "OUTPUT_FOLDER"], parameters_of("model_vs_corrected"))
check("model_vs_corrected: its outputs",
      {"SUMMARY", "PAIRS_MAP", "OVERALL", "QUANTITY", "ALLOCATION",
       "OUTPUT_FOLDER"} <= set(outputs_of("model_vs_corrected")),
      outputs_of("model_vs_corrected"))
check("time_report: its parameters",
      parameters_of("time_report") == [
          "OWNER", "PAIRED_WITH", "READINGS", "IDLE_S", "FRAMES",
          "OUTPUT_FOLDER"], parameters_of("time_report"))
check("time_report: its outputs",
      {"SUMMARY", "ACTIVE_H", "MIN_PER_HA_SCRATCH", "MIN_PER_HA_CORRECT",
       "RATIO", "FRAMES_USED", "OUTPUT_FOLDER"}
      <= set(outputs_of("time_report")), outputs_of("time_report"))
check("uncertainty_report: its parameters and outputs",
      parameters_of("uncertainty_report") == ["CORRECTION", "DRAW",
                                              "OUTPUT_FOLDER"]
      and {"SUMMARY", "AUC", "ECE", "AUC_RANDOM", "AUC_WHOLE", "ECE_RANDOM",
           "ECE_WHOLE", "OUTPUT_FOLDER"} <= set(
          outputs_of("uncertainty_report")), outputs_of("uncertainty_report"))
check("dataset_card: its parameters and outputs",
      parameters_of("dataset_card") == ["OWNER", "OUTPUT_FOLDER"]
      and {"CARD_MD", "CARD_JSON", "OUTPUT_FOLDER"} <= set(
          outputs_of("dataset_card")), outputs_of("dataset_card"))

# ------------------------------------------------------------ fixtures
CLASSES = F.CLASSES


def write_correction_json(folder, paths, name="model_corr", **extra):
    book = {"program": "RasterLabel", "kind": "correction", "format": 1,
            "id": "beefbeefbeef", "name": name,
            "created": "2026-10-08T09:00:00", "operator": "MASSI",
            "operators": ["MASSI"], "source": paths["source"], "band": 1,
            "working_copy": os.path.basename(paths["copy"]),
            "changes": os.path.basename(paths["changes"]),
            "grid": {"crs": "EPSG:32633", "origin": [500000.0, 4140010.0],
                     "pixel_crs": [1.0, 1.0], "pixel_m": [1.0, 1.0],
                     "size": [10, 10]},
            "nodata": 0, "classes": CLASSES, "operations": 2,
            "changed_m2": 10.0, "swept_m2": 10.0, "pairs": {}}
    book.update(extra)
    with open(os.path.join(folder, "correction.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump(book, fh, indent=2)
    return book


# the model's map: class 1 in columns 0-4, class 2 in 5-9; the person
# changed rows 0-1 of columns 5-9 (10 pixels) from class 2 to class 1
SRC = np.ones((10, 10), np.uint8)
SRC[:, 5:] = 2
CPY = SRC.copy()
CPY[0:2, 5:] = 1
OPS = [{"n": 1, "when": "2026-10-08T10:00:00", "operator": "MASSI",
        "into": "class 1", "only": "class 2", "pixels": 6,
        "swept_m2": "6.000", "changed_m2": "6.000", "x": 0, "y": 0,
        "col": 5, "row": 0, "width": 5, "height": 2},
       {"n": 2, "when": "2026-10-08T10:01:00", "operator": "MASSI",
        "into": "class 1", "only": "class 2", "pixels": 4,
        "swept_m2": "4.000", "changed_m2": "4.000", "x": 0, "y": 0,
        "col": 5, "row": 0, "width": 4, "height": 1}]
corr = os.path.join(root, "correction")
paths = F.make_correction(corr, SRC, CPY, None, OPS)
F._tif(os.path.join(corr, "model_corrected_reviewed.tif"), F.GRID_CARD,
       (SRC != CPY).astype(np.uint8))
write_correction_json(corr, paths, reviewed="model_corrected_reviewed.tif",
                      reviewed_since=0)
corr_before = snapshot(corr)
corr_top = listing(corr)


def polygon_layer(name):
    """Two polygons on the map: the right top quarter (columns 5-9, rows
    0-4, 10 of its 25 pixels changed) and the left top quarter (none)."""
    lyr = QgsVectorLayer("Polygon?crs=EPSG:32633", name, "memory")
    for wkt in ("POLYGON((500005 4140005, 500010 4140005, 500010 4140010, "
                "500005 4140010, 500005 4140005))",
                "POLYGON((500000 4140005, 500005 4140005, 500005 4140010, "
                "500000 4140010, 500000 4140005))"):
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromWkt(wkt))
        lyr.dataProvider().addFeatures([f])
    lyr.updateExtents()
    return lyr


# ----------------------------------------------------- model vs corrected
print()
print("Model vs corrected: the whole map")
out = run("model_vs_corrected", CORRECTION=corr, SCOPE=0)
check("overall accuracy 0.9, quantity 0.1, allocation 0",
      abs(out["OVERALL"] - 0.9) < 1e-9 and abs(out["QUANTITY"] - 0.1) < 1e-9
      and abs(out["ALLOCATION"]) < 1e-9, out)
check("100 pixels compared", out["PIXELS"] == 100, out["PIXELS"])
report = out["OUTPUT_FOLDER"]
check("the report is under the correction's reports/model_vs_corrected/",
      os.path.dirname(report) == os.path.join(corr, "reports",
                                              "model_vs_corrected")
      and os.path.basename(report).startswith("whole_"), report)
check("the summary, the tables and the map of pairs are there",
      os.path.isfile(out["SUMMARY"]) and out["SUMMARY"].startswith(report)
      and os.path.isfile(out["PAIRS_MAP"])
      and all(os.path.isfile(os.path.join(report, f)) for f in
              ("confusion.csv", "per_class.csv", "pairs.csv")), out)
with open(out["SUMMARY"], encoding="utf-8") as fh:
    summary = json.load(fh)
check("summary.json says model_vs_corrected, version 1.1",
      summary.get("rasterlabel:report") == "model_vs_corrected"
      and summary.get("version") == "1.1", summary.get("version"))
ds = gdal.Open(out["PAIRS_MAP"])
pairs = ds.GetRasterBand(1).ReadAsArray()
ds = None
check("the map of pairs holds three pairs (1/1, 1/2 changed, 2/2)",
      len(set(np.unique(pairs).tolist()) - {0, 255}) == 3,
      np.unique(pairs).tolist())
check("the correction is only read: every file as it was, the manifest "
      "too, and only reports/ added",
      snapshot(corr) == corr_before
      and sorted(set(listing(corr)) - set(corr_top)) == ["reports"]
      and "reports" not in manifest_of(corr, "correction.json"),
      sorted(set(listing(corr)) - set(corr_top)))

print()
print("on the ground swept, and without the map")
out = run("model_vs_corrected", CORRECTION=corr, SCOPE=1, WRITE_MAP=False)
check("the 10 pixels the strokes went over: all changed, overall 0",
      out["PIXELS"] == 10 and abs(out["OVERALL"]) < 1e-9, out)
check("no map of pairs asked, none written",
      out["PAIRS_MAP"] == "" and not [f for f in os.listdir(
          out["OUTPUT_FOLDER"]) if f.endswith(".tif")], out["PAIRS_MAP"])

print()
print("on a map in degrees, the ground row by row")
import math                                                        # noqa: E402

A_AXIS, FLAT = 6378137.0, 1 / 298.257223563
E2 = FLAT * (2 - FLAT)
E1 = math.sqrt(E2)


def band_m2(phi):
    s = math.sin(phi)
    return (A_AXIS * (1 - FLAT)) ** 2 * (
        s / (2 * (1 - E2 * s * s))
        + math.log((1 + E1 * s) / (1 - E1 * s)) / (4 * E1))


def cell_m2(lat0, lat1, width_deg):
    """A cell of longitude and latitude on the WGS 84 ellipsoid."""
    return abs(math.radians(width_deg)
               * (band_m2(math.radians(lat1)) - band_m2(math.radians(lat0))))


GRID_DEG = {"epsg": 4326, "origin": (10.0, 60.0), "pixel": 0.5,
            "size": (10, 10)}
row_area = [cell_m2(60.0 - 0.5 * r, 60.0 - 0.5 * (r + 1), 0.5)
            for r in range(10)]
side = math.sqrt(row_area[5])           # the pixel at the middle of the map
deg = os.path.join(root, "correction_deg")
dpaths = F.make_correction(deg, SRC, CPY, None, OPS, grid=GRID_DEG)
write_correction_json(deg, dpaths, name="deg_corr", id="cafecafecafe",
                      grid={"crs": "EPSG:4326", "origin": [10.0, 60.0],
                            "pixel_crs": [0.5, 0.5], "pixel_m": [side, side],
                            "size": [10, 10]})
out = run("model_vs_corrected", CORRECTION=deg, SCOPE=0, WRITE_MAP=False)
with open(out["SUMMARY"], encoding="utf-8") as fh:
    s_deg = json.load(fh)
changed_m2 = 5 * (row_area[0] + row_area[1])
check("the area of the 10 changed pixels is the ground they cover, row by "
      "row, as the panel gives it",
      abs(s_deg["overall"]["changed_m2_net"] - changed_m2) < 1e-6 * changed_m2,
      (s_deg["overall"]["changed_m2_net"], changed_m2))
check("and is not the pixel at the middle of the map times 10",
      abs(10 * side * side - changed_m2) > 0.02 * changed_m2,
      (10 * side * side, changed_m2))
check("the area of the whole scope is the ground of the 100 pixels",
      abs(s_deg["scope"]["area_m2"] - 10 * sum(row_area))
      < 1e-6 * 10 * sum(row_area), s_deg["scope"]["area_m2"])
near = 1e-6
band5 = sum(row_area)                    # one column of the map, top to bottom
top2 = row_area[0] + row_area[1]         # the two rows that were changed


def table(folder, name):
    with open(os.path.join(folder, name), encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def records(folder, name):
    with open(os.path.join(folder, name), encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def close(a, b):
    return abs(float(a) - b) <= near * max(abs(b), 1.0)


rows = table(out["OUTPUT_FOLDER"], "confusion.csv")
at = [r[0] if r else "" for r in rows].index("model \\ corrected (m2)")
m2 = {r[0]: [float(v) for v in r[1:]] for r in rows[at + 1:at + 4]}
names = ["%d %s" % (c["code"], c["name"]) for c in CLASSES]
check("the confusion matrix in m2 is the ground of each pair, row by row",
      close(m2[names[0]][0], 5 * band5) and close(m2[names[0]][1], 0.0)
      and close(m2[names[1]][0], 5 * top2)
      and close(m2[names[1]][1], 5 * (band5 - top2)), m2)
check("and its totals are the ground of the rows, the columns and the map",
      close(m2[names[0]][2], 5 * band5)
      and close(m2[names[1]][2], 5 * band5)
      and close(m2["total"][0], 5 * band5 + 5 * top2)
      and close(m2["total"][2], 10 * band5), m2["total"])
per = {int(r["code"]): r for r in records(out["OUTPUT_FOLDER"],
                                          "per_class.csv")}
check("the area of each class, of the model and of the corrected map, and the "
      "net change, are the ground too",
      close(per[1]["model_m2"], 5 * band5)
      and close(per[1]["corrected_m2"], 5 * band5 + 5 * top2)
      and close(per[1]["net_change_m2"], 5 * top2)
      and close(per[2]["model_m2"], 5 * band5)
      and close(per[2]["corrected_m2"], 5 * (band5 - top2))
      and close(per[2]["net_change_m2"], -5 * top2),
      {k: (v["model_m2"], v["corrected_m2"], v["net_change_m2"])
       for k, v in per.items()})
check("the report says every area is the ground, row by row",
      any("row by row" in n and "polygon" in n for n in s_deg["notes"]),
      s_deg["notes"])
quarter = QgsVectorLayer("Polygon?crs=EPSG:4326", "deg_quarter", "memory")
feat = QgsFeature()
feat.setGeometry(QgsGeometry.fromWkt(
    "POLYGON((12.5 57.5, 15 57.5, 15 60, 12.5 60, 12.5 57.5))"))
quarter.dataProvider().addFeatures([feat])
quarter.updateExtents()
outp = run("model_vs_corrected", CORRECTION=deg, SCOPE=2, POLYGONS=quarter,
           WRITE_MAP=False)
poly = table(outp["OUTPUT_FOLDER"], "polygons.csv")
head, first = poly[0], poly[1]
check("a polygon's area is the ground of its 25 pixels, row by row",
      int(first[head.index("pixels")]) == 25
      and close(first[head.index("area_m2")], 5 * sum(row_area[0:5])),
      (first, 5 * sum(row_area[0:5])))

out = run("model_vs_corrected", CORRECTION=corr, SCOPE=0, WRITE_MAP=False)
with open(out["SUMMARY"], encoding="utf-8") as fh:
    s_utm = json.load(fh)
check("a map in a metric system gives the pixels times the pixel, as it did",
      abs(s_utm["overall"]["changed_m2_net"] - 10.0) < 1e-9
      and abs(s_utm["scope"]["area_m2"] - 100.0) < 1e-9,
      (s_utm["overall"]["changed_m2_net"], s_utm["scope"]["area_m2"]))
rows = table(out["OUTPUT_FOLDER"], "confusion.csv")
at = [r[0] if r else "" for r in rows].index("model \\ corrected (m2)")
per = {int(r["code"]): r for r in records(out["OUTPUT_FOLDER"],
                                          "per_class.csv")}
check("and so do its classes and its confusion matrix in m2",
      [float(v) for v in rows[at + 1][1:]] == [50.0, 0.0, 50.0]
      and [float(v) for v in rows[at + 2][1:]] == [10.0, 40.0, 50.0]
      and [float(v) for v in rows[at + 3][1:]] == [60.0, 40.0, 100.0]
      and float(per[1]["model_m2"]) == 50.0
      and float(per[1]["corrected_m2"]) == 60.0
      and float(per[1]["net_change_m2"]) == 10.0
      and float(per[2]["net_change_m2"]) == -10.0,
      (rows[at:at + 5], per[1]))

print()
print("a manifest that holds the map by its way from its folder")
rel = os.path.join(root, "correction_rel")
shutil.copytree(corr, rel, ignore=shutil.ignore_patterns("reports"))
book_rel = manifest_of(rel, "correction.json")
book_rel["source"] = "model.tif"            # as the program writes it now
with open(os.path.join(rel, "correction.json"), "w", encoding="utf-8",
          newline="\n") as fh:
    json.dump(book_rel, fh, indent=2)
rel_before = snapshot(rel)
out = run("model_vs_corrected", CORRECTION=rel, SCOPE=0, WRITE_MAP=False)
check("Model vs corrected finds the map it started from, as the panel does",
      out["PIXELS"] == 100 and abs(out["OVERALL"] - 0.9) < 1e-9, out)
card_out = run("dataset_card", OWNER=rel)
with open(card_out["CARD_JSON"], encoding="utf-8") as fh:
    card_rel = json.load(fh)
check("and so does the dataset card: the classes before, and from what into "
      "what",
      card_rel["pixels"]["before"] is not None
      and card_rel["pixels"]["changed_px"] == 10
      and card_rel["pixels"]["changed_pairs_px"], card_rel["pixels"])
check("the manifest is only read: it still holds the way, and nothing else "
      "changed", manifest_of(rel, "correction.json")["source"] == "model.tif"
      and snapshot(rel) == rel_before)

print()
print("inside polygons")
layer = polygon_layer("quarters")
out = run("model_vs_corrected", CORRECTION=corr, SCOPE=2, POLYGONS=layer)
check("both polygons: 50 pixels, overall 0.8", out["PIXELS"] == 50
      and abs(out["OVERALL"] - 0.8) < 1e-9, out)
check("polygons.csv is written", os.path.isfile(os.path.join(
    out["OUTPUT_FOLDER"], "polygons.csv")))
layer.selectByIds([min(f.id() for f in layer.getFeatures())])
out = run("model_vs_corrected", CORRECTION=corr, SCOPE=2, POLYGONS=layer,
          SELECTED_ONLY=True)
check("the selected polygon alone: 25 pixels, overall 0.6",
      out["PIXELS"] == 25 and abs(out["OVERALL"] - 0.6) < 1e-9, out)
text = refused("model_vs_corrected", CORRECTION=corr, SCOPE=2)
check("the polygons scope with no layer is refused in words",
      good(text) and "POLYGONS" in text, text)
layer.removeSelection()
empty = QgsVectorLayer("Polygon?crs=EPSG:32633", "none", "memory")
text = refused("model_vs_corrected", CORRECTION=corr, SCOPE=2,
               POLYGONS=empty)
check("a layer with no polygon is refused", good(text)
      and "No polygon" in text, text)

print()
print("a folder named, correction.json named, people beside the model")
mine = os.path.join(root, "elsewhere", "mvc_report")
out = run("model_vs_corrected", CORRECTION=os.path.join(
    corr, "correction.json"), SCOPE=0, OUTPUT_FOLDER=mine)
check("with OUTPUT_FOLDER, the report goes there; the path of the "
      "correction.json is taken as the folder's",
      os.path.normcase(out["OUTPUT_FOLDER"]) == os.path.normcase(mine)
      and os.path.isfile(os.path.join(mine, "summary.json")),
      out["OUTPUT_FOLDER"])
out2 = run("model_vs_corrected", CORRECTION=corr, SCOPE=0,
           OUTPUT_FOLDER=mine, WRITE_MAP=False)
check("a folder that holds something gets a folder of its own inside",
      os.path.dirname(out2["OUTPUT_FOLDER"]) == mine
      and os.path.isfile(out2["SUMMARY"]), out2["OUTPUT_FOLDER"])
empty_dir = os.path.join(root, "empty_dir")
os.makedirs(empty_dir)
out3 = run("model_vs_corrected", CORRECTION=corr, SCOPE=0,
           OUTPUT_FOLDER=empty_dir, WRITE_MAP=False)
check("an empty folder is used as it is",
      os.path.normcase(out3["OUTPUT_FOLDER"]) == os.path.normcase(empty_dir),
      out3["OUTPUT_FOLDER"])

# another person's correction of the same map: ANN corrected 6 of the 10
other = os.path.join(root, "correction_other")
other_cpy = SRC.copy()
other_cpy[0, 5:] = 1
other_cpy[1, 5:8] = 1
op = F.make_correction(other, SRC, other_cpy, None, OPS[:1])
write_correction_json(other, dict(op, source=paths["source"]),
                      name="other_corr", id="deaddeaddead", operator="ANN",
                      operators=["ANN"])
other_before = snapshot(other, ())
out = run("model_vs_corrected", CORRECTION=corr, SCOPE=0, PEOPLE=other,
          WRITE_MAP=False)
with open(out["SUMMARY"], encoding="utf-8") as fh:
    s_people = json.load(fh)
check("another person's correction: set beside the model's numbers",
      os.path.isfile(os.path.join(out["OUTPUT_FOLDER"], "side_by_side.csv"))
      and "ANN" in json.dumps(s_people.get("people") or s_people),
      sorted(os.listdir(out["OUTPUT_FOLDER"])))
check("and theirs is only read too", snapshot(other, ()) == other_before
      and "reports" not in os.listdir(other))
text = refused("model_vs_corrected", CORRECTION=corr, PEOPLE=corr)
check("the correction itself as the people is refused", good(text)
      and "being measured" in text, text)
elsewhere = os.path.join(root, "correction_elsewhere")
ep = F.make_correction(elsewhere, SRC, other_cpy, None, OPS[:1])
write_correction_json(elsewhere, ep, name="elsewhere", id="aaaabbbbcccc")
text = refused("model_vs_corrected", CORRECTION=corr, PEOPLE=elsewhere)
check("a correction of another map is refused, naming both", good(text)
      and "another map" in text, text)

# an agreement report, made by rasterlabel:agreement on the shared campaign
shared = os.path.join(root, "shared")
F.make_shared_campaign(shared)
agree = run("agreement", CAMPAIGN=os.path.join(shared, "campaign.json"),
            READING_A="ANNA,1", READING_B="BRUNO,1", FRAMES=0,
            POINTS_IN=False, RESAMPLES=0, SEED=1, ALLOW_UNFINISHED=True)
out = run("model_vs_corrected", CORRECTION=corr, SCOPE=0, WRITE_MAP=False,
          PEOPLE=agree["SUMMARY"])
check("an agreement report as the people: the model beside them, by class "
      "name", os.path.isfile(os.path.join(out["OUTPUT_FOLDER"],
                                          "side_by_side.csv")),
      sorted(os.listdir(out["OUTPUT_FOLDER"])))
out = run("model_vs_corrected", CORRECTION=corr, SCOPE=0, WRITE_MAP=False,
          PEOPLE=os.path.dirname(agree["SUMMARY"]))
check("or the folder of that report", os.path.isfile(os.path.join(
    out["OUTPUT_FOLDER"], "side_by_side.csv")))
text = refused("model_vs_corrected", CORRECTION=corr,
               PEOPLE=os.path.join(corr, "operations.csv"))
check("a file that is no report is refused", good(text), text)

print()
print("what it refuses")
broken = os.path.join(root, "correction_broken")
shutil.copytree(corr, broken, ignore=shutil.ignore_patterns("reports"))
os.remove(os.path.join(broken, "model_corrected.tif"))
text = refused("model_vs_corrected", CORRECTION=broken)
check("a working copy that is gone", good(text) and "missing" in text, text)
check("and nothing is written", reports_of(broken) == [])
nosrc = os.path.join(root, "correction_nosrc")
shutil.copytree(corr, nosrc, ignore=shutil.ignore_patterns("reports"))
with open(os.path.join(nosrc, "correction.json"), encoding="utf-8") as fh:
    nosrc_book = json.load(fh)
nosrc_book["source"] = os.path.join(nosrc, "model.tif")
with open(os.path.join(nosrc, "correction.json"), "w", encoding="utf-8",
          newline="\n") as fh:
    json.dump(nosrc_book, fh)
os.remove(os.path.join(nosrc, "model.tif"))
text = refused("model_vs_corrected", CORRECTION=nosrc)
check("a map the model made that is gone: the panel's words", good(text)
      and "no longer where it was" in text, text)
check("and nothing is written", reports_of(nosrc) == [])
wide = os.path.join(root, "correction_wide")
os.makedirs(wide)
wp = F.make_correction(wide, np.ones((8, 8), np.uint8),
                       np.ones((8, 8), np.uint8), None, OPS[:1])
write_correction_json(wide, wp, name="wide")
shutil.copy(paths["source"], wp["source"])
text = refused("model_vs_corrected", CORRECTION=wide)
check("a map of another size than the copy: refused on the grid", good(text),
      text)
text = refused("model_vs_corrected", CORRECTION=os.path.join(root, "nowhere"))
check("a folder that is not there", good(text) and "not there" in text, text)
text = refused("model_vs_corrected", CORRECTION=shared)
check("a campaign where a correction is needed", good(text)
      and "needs a correction" in text, text)
check("none of the refusals touched the correction",
      snapshot(corr) == corr_before)

# ------------------------------------------------------------------ time
print()
print("Time")
T0 = "2026-10-08T09:00:00.000Z"


def jrow(action, end_s, dur_s=0, cls="", pauses="", tile="t001", session="S1",
         op="ANNA", pass_no="1", module="annotate", x="", y="", ref="",
         seq=[0]):
    from datetime import datetime, timedelta, timezone
    seq[0] += 1
    t0 = datetime(2026, 10, 8, 9, 0, 0, tzinfo=timezone.utc)
    return {"session": session, "seq": seq[0], "mono_ms": int(end_s * 1000),
            "t_utc": (t0 + timedelta(seconds=end_s)).isoformat(
                timespec="milliseconds").replace("+00:00", "Z"),
            "dur_ms": int(dur_s * 1000), "pauses_s": pauses, "module": module,
            "action": action, "operator": op, "pass_no": pass_no,
            "tile_id": tile, "class_code": cls, "x": x, "y": y, "ref": ref}


# ANNA: 182 s of active time at an idle limit of 60 s
ANNA_ROWS = [jrow("open", 0), jrow("stroke", 25, 15, 1),
             jrow("stroke", 50, 10, 1), jrow("view", 100),
             jrow("stroke", 230, 100, 2, "20.0;75.0"),
             jrow("focus_out", 240), jrow("focus_in", 245),
             jrow("stroke", 262, 12, 2), jrow("close", 400)]
# BRUNO: 20 + 20 = 40 s of lead and drawing at 60 s
BRUNO_ROWS = [jrow("open", 0, session="S2", op="BRUNO"),
              jrow("stroke", 20, 10, 1, session="S2", op="BRUNO"),
              jrow("stroke", 40, 10, 2, session="S2", op="BRUNO"),
              jrow("close", 40, session="S2", op="BRUNO")]
F.write_journal(os.path.join(shared, "journal.csv"),
                ANNA_ROWS + BRUNO_ROWS)
# a correction of the same grid, journal of two strokes inside t001
tcorr = os.path.join(root, "time_correction")
tg = F.GRID_AGREEMENT
tsrc = np.ones((10, 30), np.uint8)
tcpy = tsrc.copy()
tcpy[0:3, 0:3] = 2
tp = F.make_correction(tcorr, tsrc, tcpy, None, OPS[:1], grid=tg)
tbook = write_correction_json(tcorr, tp, name="time_corr")
tbook["grid"] = {"crs": "EPSG:32633", "origin": [500000.0, 4140010.0],
                 "pixel_crs": [0.05, 0.05], "pixel_m": [0.05, 0.05],
                 "size": [30, 10]}
with open(os.path.join(tcorr, "correction.json"), "w", encoding="utf-8",
          newline="\n") as fh:
    json.dump(tbook, fh)
CX, CY = 500000.25, 4140009.75
F.write_journal(os.path.join(tcorr, "journal.csv"), [
    jrow("open", 0, tile="", session="C1", op="ANNA", pass_no="",
         module="correct"),
    jrow("correct", 10, 8, 2, tile="", session="C1", op="ANNA", pass_no="",
         module="correct", x=CX, y=CY, ref=1),
    jrow("correct", 30, 10, 2, tile="", session="C1", op="ANNA", pass_no="",
         module="correct", x=CX, y=CY, ref=2),
    jrow("close", 40, tile="", session="C1", op="ANNA", pass_no="",
         module="correct")])
shared_before = snapshot(shared)
tcorr_before = snapshot(tcorr)
shared_top = listing(shared)

out = run("time_report", OWNER=shared)
check("active time of the campaign at 60 s: 182 + 40 s", abs(
    out["ACTIVE_H"] - 222 / 3600.0) < 1e-6, out["ACTIVE_H"])
check("drawn from scratch, minutes per hectare worked out from the "
      "frame's 0.25 m2 on average over the frames drawn",
      out["MIN_PER_HA_SCRATCH"] is not None
      and out["MIN_PER_HA_CORRECT"] is None and out["RATIO"] is None,
      out)
check("every frame read: t001, t002, t003", out["FRAMES_USED"] == 3,
      out["FRAMES_USED"])
tr = out["OUTPUT_FOLDER"]
check("the report is under the campaign's reports/time/",
      os.path.dirname(tr) == os.path.join(shared, "reports", "time"), tr)
check("its summary and tables are there",
      os.path.isfile(out["SUMMARY"]) and all(os.path.isfile(
          os.path.join(tr, f)) for f in ("time_per_frame.csv",
                                         "time_per_class.csv")), out)
with open(out["SUMMARY"], encoding="utf-8") as fh:
    tsum = json.load(fh)
check("30, 60 and 120 s are always there", sorted(tsum["sensitivity"])
      == ["120", "30", "60"] and tsum["parameters"]["idle_s"] == 60,
      tsum.get("parameters"))
check("the campaign is only read: files and manifest as they were, no "
      "report listed in the manifest",
      snapshot(shared) == shared_before
      and manifest_of(shared, "campaign.json")["reports"] == []
      and only_reports_added(shared, shared_top))

out = run("time_report", OWNER=shared, IDLE_S=30)
check("at an idle limit of 30 s the time is 132 + 40 s",
      abs(out["ACTIVE_H"] - 172 / 3600.0) < 1e-6, out["ACTIVE_H"])
out = run("time_report", OWNER=os.path.join(shared, "campaign.json"),
          READINGS="ANNA,1")
check("one reading: ANNA's 182 s", abs(out["ACTIVE_H"] - 182 / 3600.0)
      < 1e-6, out["ACTIVE_H"])
out = run("time_report", OWNER=shared, FRAMES=1)
check("closed only: the frames both closed and read, t001 and t002",
      out["FRAMES_USED"] == 2, out["FRAMES_USED"])
text = refused("time_report", OWNER=shared, READINGS="CARLA,1")
check("a reading the campaign does not hold is refused, naming the ones "
      "it has", good(text) and "CARLA" in text and "ANNA, pass 1" in text,
      text)
text = refused("time_report", OWNER=shared, FRAMES=2)
check("'drawn and corrected' with no correction is refused", good(text)
      and "PAIRED_WITH" in text, text)

print()
print("set beside a correction, and a correction alone")
out = run("time_report", OWNER=shared, PAIRED_WITH=tcorr,
          READINGS="ANNA,1", FRAMES=2)
check("drawn and corrected: the frame t001, the ratio 40 / 182",
      out["FRAMES_USED"] == 1 and out["RATIO"] is not None
      and abs(out["RATIO"] - 40.0 / 182.0) < 1e-6
      and out["MIN_PER_HA_CORRECT"] is not None, out)
check("the paired table is written", os.path.isfile(os.path.join(
    out["OUTPUT_FOLDER"], "time_paired.csv")))
out = run("time_report", OWNER=tcorr)
check("a correction alone: 40 s in its own reports/time/",
      abs(out["ACTIVE_H"] - 40 / 3600.0) < 1e-6
      and os.path.dirname(out["OUTPUT_FOLDER"]) == os.path.join(
          tcorr, "reports", "time"), out)
out = run("time_report", OWNER=tcorr, PAIRED_WITH=shared)
check("a correction with its campaign beside it: reported in the "
      "correction", os.path.dirname(out["OUTPUT_FOLDER"]) == os.path.join(
          tcorr, "reports", "time"), out["OUTPUT_FOLDER"])
mine = os.path.join(root, "elsewhere", "time_report")
out = run("time_report", OWNER=shared, OUTPUT_FOLDER=mine)
check("with OUTPUT_FOLDER, the report goes there",
      os.path.normcase(out["OUTPUT_FOLDER"]) == os.path.normcase(mine)
      and os.path.isfile(os.path.join(mine, "time_summary.json")),
      out["OUTPUT_FOLDER"])
text = refused("time_report", OWNER=shared, PAIRED_WITH=shared)
check("a campaign beside a campaign is refused", good(text)
      and "PAIRED_WITH" in text, text)
check("the campaign and the correction are only read",
      snapshot(shared) == shared_before and snapshot(tcorr) == tcorr_before
      and "reports" not in manifest_of(tcorr, "correction.json"))

print()
print("a campaign with no journal")
nj = os.path.join(root, "no_journal")
F.make_shared_campaign(nj)
text = refused("time_report", OWNER=nj)
check("is refused with the panel's words", good(text)
      and "No journal yet" in text, text)
check("and nothing is written", reports_of(nj) == [])
nc = os.path.join(root, "no_strokes")
ncp = F.make_correction(nc, SRC, SRC, None, [])
write_correction_json(nc, ncp, name="none")
text = refused("time_report", OWNER=nc)
check("a correction with no stroke on record is refused", good(text)
      and "Nothing to measure" in text, text)

# ----------------------------------------------------------- uncertainty
print()
print("Uncertainty")
from rasterlabel import uncertainty as U                           # noqa: E402

N = 128
ucorr = os.path.join(root, "unc_correction")
os.makedirs(ucorr)
rng = np.random.default_rng(5)
u_src = rng.integers(1, 3, (N, N)).astype(np.uint8)
prob = rng.integers(77, 256, (N, N)).astype(np.uint8)
u_cpy = u_src.copy()
low = prob < 160
flip = low & (rng.random((N, N)) < 0.7)
u_cpy[flip] = 3 - u_cpy[flip]
u_marks = (u_src != u_cpy).astype(np.uint8)
UG = {"epsg": 32633, "origin": (500000.0, 4140128.0), "pixel": 1.0,
      "size": (N, N)}


def tif_bands(path, grid, bands, nodata=0, names=None):
    ds = gdal.GetDriverByName("GTiff").Create(path, N, N, len(bands), gdal.GDT_Byte)
    ox, oy = grid["origin"]
    ds.SetGeoTransform((ox, grid["pixel"], 0.0, oy, 0.0, -grid["pixel"]))
    ds.SetProjection(F._srs(grid).ExportToWkt())
    for i, a in enumerate(bands):
        b = ds.GetRasterBand(i + 1)
        b.SetNoDataValue(nodata)
        b.WriteArray(a)
        if names:
            b.SetDescription(names[i])
    ds = None
    return path


usrc = tif_bands(os.path.join(ucorr, "model.tif"), UG, [u_src])
ucopy = tif_bands(os.path.join(ucorr, "model_corrected.tif"), UG,
                  [u_cpy, prob], names=["class", "probabilita x255"])
uchg = tif_bands(os.path.join(ucorr, "model_corrected_changes.tif"), UG,
                 [u_marks], nodata=0)
spec = {"kind": "probability", "source": "band", "band": 2, "scale": 255.0,
        "band_name": "probabilita x255"}
derived = U.unc_path_of(ucopy, {"uncertainty": spec})
said = U.unc_build(ucopy, 1, 0, spec, derived)
spec.update({"grid": said["grid"], "offset": said["offset"],
             "derived": os.path.basename(derived), "made": "2026-10-08T09:30",
             "valid_px": said["valid_px"],
             "zero_read_as_value": said["zero_read_as_value"],
             "clipped_px": said["clipped_px"], "map_px": said["map_px"]})
u8 = U.unc_read_u8(derived, N, N)
blocks = U.unc_score_blocks(u8, 32)
walk = U.Places.from_blocks(os.path.join(ucorr, "uncertainty_places.csv"),
                            blocks, (UG["origin"][0], 1.0, 0.0,
                                     UG["origin"][1], 0.0, -1.0), N, N, 7, 2,
                            True)
for _ in range(10):
    row = walk.next()
    c0, r0, w, h = row["col"], row["row"], row["width"], row["height"]
    walk.done("ANNA", overlay_on=False,
              changed_px=int(u_marks[r0:r0 + h, c0:c0 + w].sum()))
walk.save()
ubook = {"program": "RasterLabel", "kind": "correction", "format": 1,
         "id": "0badc0ffee00", "name": "unc_corr",
         "created": "2026-10-08T09:00:00", "operator": "ANNA",
         "operators": ["ANNA"], "source": usrc, "band": 1,
         "working_copy": "model_corrected.tif",
         "changes": "model_corrected_changes.tif",
         "grid": {"crs": "EPSG:32633", "origin": list(UG["origin"]),
                  "pixel_crs": [1.0, 1.0], "pixel_m": [1.0, 1.0],
                  "size": [N, N]},
         "nodata": 0, "classes": CLASSES, "operations": 3,
         "changed_m2": float(u_marks.sum()), "swept_m2": 0.0, "pairs": {},
         "uncertainty": spec,
         "places": {"side_px": 32, "random_every": 2, "seed": 7,
                    "blind": True, "file": "uncertainty_places.csv",
                    "eligible": walk.N}}
with open(os.path.join(ucorr, "correction.json"), "w", encoding="utf-8",
          newline="\n") as fh:
    json.dump(ubook, fh, indent=2)
with open(os.path.join(ucorr, "operations.csv"), "w", encoding="utf-8",
          newline="") as fh:
    fh.write("n,when,operator,into,only,pixels,swept_m2,changed_m2,x,y,col,"
             "row,width,height\n")
ucorr_before = snapshot(ucorr)
ucorr_top = listing(ucorr)

out = run("uncertainty_report", CORRECTION=ucorr)


def auc_by_hand(u, m):
    valid = u < 255
    chg = np.bincount(u[valid & (m == 1)], minlength=256).astype(float)
    other = np.bincount(u[valid & (m == 0)], minlength=256).astype(float)
    below = np.cumsum(other) - other
    return float((chg * (below + 0.5 * other)).sum()
                 / (chg.sum() * other.sum()))


want = auc_by_hand(u8, u_marks)
check("the AUC of the whole map is the one worked out from the pixels",
      out["AUC_WHOLE"] is not None and abs(out["AUC_WHOLE"] - want) < 1e-9
      and want > 0.6, (out["AUC_WHOLE"], want))
check("with random places done, AUC is theirs", out["RANDOM_DONE"] >= 2
      and out["AUC_RANDOM"] is not None and out["AUC"] == out["AUC_RANDOM"],
      out)
check("the ECE of 1 - p is a number between 0 and 1", out["ECE"] is not None
      and 0.0 <= out["ECE"] <= 1.0 and out["ECE_WHOLE"] is not None, out)
ur = out["OUTPUT_FOLDER"]
check("the report is under reports/uncertainty/ with its tables",
      os.path.dirname(ur) == os.path.join(ucorr, "reports", "uncertainty")
      and all(os.path.isfile(os.path.join(ur, f)) for f in (
          "calibration.csv", "capture.csv", "places.csv", "strokes.csv",
          "summary.json")), ur)
with open(out["SUMMARY"], encoding="utf-8") as fh:
    usum = json.load(fh)
check("summary.json: the kind, and the same numbers as the output",
      usum["uncertainty"]["kind"] == "probability"
      and abs(usum["auc"]["whole_map"] - out["AUC_WHOLE"]) < 1e-12
      and usum["places"]["random_done"] == out["RANDOM_DONE"], usum["auc"])
check("the picture of the curve is drawn",
      os.path.isfile(os.path.join(ur, "calibration.png")),
      usum.get("notes"))
check("the correction is only read: the places file, the file of "
      "uncertainty, the record of changes and the manifest as they were",
      snapshot(ucorr) == ucorr_before
      and only_reports_added(ucorr, ucorr_top)
      and "reports" not in manifest_of(ucorr, "correction.json"))
out = run("uncertainty_report", CORRECTION=ucorr, DRAW=False)
check("DRAW off: no picture", not os.path.exists(os.path.join(
    out["OUTPUT_FOLDER"], "calibration.png")))
mine = os.path.join(root, "elsewhere", "unc_report")
out = run("uncertainty_report", CORRECTION=os.path.join(
    ucorr, "correction.json"), OUTPUT_FOLDER=mine, DRAW=False)
check("with OUTPUT_FOLDER, the report goes there",
      os.path.normcase(out["OUTPUT_FOLDER"]) == os.path.normcase(mine)
      and os.path.isfile(os.path.join(mine, "summary.json")),
      out["OUTPUT_FOLDER"])
text = refused("uncertainty_report", CORRECTION=corr)
check("a correction with no uncertainty chosen is refused, in the panel's "
      "words", good(text) and "no uncertainty chosen" in text, text)
check("and nothing is written", "uncertainty" not in reports_of(corr))
gone = os.path.join(root, "unc_gone")
shutil.copytree(ucorr, gone, ignore=shutil.ignore_patterns("reports"))
os.remove(U.unc_path_of(os.path.join(gone, "model_corrected.tif"),
                        {"uncertainty": spec}))
text = refused("uncertainty_report", CORRECTION=gone)
check("a file of uncertainty that is gone: refused, saying to open Correct",
      good(text) and "not there" in text and "Correct" in text, text)
check("and nothing is written", reports_of(gone) == [])
nomark = os.path.join(root, "unc_nomark")
shutil.copytree(ucorr, nomark, ignore=shutil.ignore_patterns("reports"))
os.remove(os.path.join(nomark, "model_corrected_changes.tif"))
text = refused("uncertainty_report", CORRECTION=nomark)
check("no record of changes: refused by the engine, in its words",
      good(text) and "no record of which pixels" in text, text)
check("and nothing is written", reports_of(nomark) == [])

# ------------------------------------------------------------------ card
print()
print("Dataset card")
out = run("dataset_card", OWNER=shared)
cd = out["OUTPUT_FOLDER"]
check("the card of a campaign is under reports/card/, .md and .json",
      os.path.dirname(cd) == os.path.join(shared, "reports", "card")
      and os.path.isfile(out["CARD_MD"]) and os.path.isfile(out["CARD_JSON"])
      and out["CARD_MD"].endswith("_card.md")
      and out["CARD_JSON"].endswith("_card.json"), out)
with open(out["CARD_JSON"], encoding="utf-8") as fh:
    card = json.load(fh)
check("it describes the campaign: kind, two readings",
      card.get("kind") == "campaign" and len(card.get("readings") or []) == 2,
      card.get("kind"))
check("the campaign is only read", snapshot(shared) == shared_before
      and manifest_of(shared, "campaign.json")["reports"] == [])
out = run("dataset_card", OWNER=os.path.join(corr, "correction.json"))
with open(out["CARD_JSON"], encoding="utf-8") as fh:
    card = json.load(fh)
check("the card of a correction: 10 pixels changed",
      card.get("kind") == "correction"
      and card["pixels"]["changed_px"] == 10, card.get("pixels"))
check("under the correction's reports/card/, which is only read",
      os.path.dirname(out["OUTPUT_FOLDER"]) == os.path.join(
          corr, "reports", "card") and snapshot(corr) == corr_before)
mine = os.path.join(root, "elsewhere", "card")
out = run("dataset_card", OWNER=shared, OUTPUT_FOLDER=mine)
check("with OUTPUT_FOLDER, the card goes there",
      os.path.normcase(out["OUTPUT_FOLDER"]) == os.path.normcase(mine)
      and os.path.isfile(out["CARD_MD"]), out["OUTPUT_FOLDER"])
text = refused("dataset_card", OWNER=os.path.join(root, "nowhere"))
check("a folder that is not there is refused", good(text), text)
check("a folder with neither manifest is refused", good(refused(
    "dataset_card", OWNER=root)))
nopkg = os.path.join(root, "no_package")
shutil.copytree(shared, nopkg, ignore=shutil.ignore_patterns("reports"))
os.remove(os.path.join(nopkg, "annotation.gpkg"))
text = refused("dataset_card", OWNER=nopkg)
check("a campaign with no package is refused", good(text)
      and "no package" in text, text)
nocopy = os.path.join(root, "no_copy")
shutil.copytree(corr, nocopy, ignore=shutil.ignore_patterns("reports"))
os.remove(os.path.join(nocopy, "model_corrected.tif"))
text = refused("dataset_card", OWNER=nocopy)
check("a correction with no working copy is refused", good(text)
      and "not there" in text, text)
check("and nothing is written", reports_of(nopkg) == []
      and reports_of(nocopy) == [])


class Panel(object):
    """The panel with BRUNO's pass 1 hidden from the reader it holds."""

    class campaign(object):
        data = {"id": "0123456789ab"}

    def blind_gate(self, readings, what="agreement map", verb="compare"):
        hidden = [r for r in readings if r[0] == "BRUNO"]
        if not hidden:
            return None
        return ("ANNA is drawing pass 2 with one operator at a time on, so "
                "BRUNO, pass 1 is hidden from ANNA. The %s would show it. "
                "Untick 'one operator at a time' under Annotate's "
                "Settings, then %s." % (what, verb))


launch._RASTERLABEL = (None, None, Panel())
text = refused("dataset_card", OWNER=shared)
check("a reading hidden from the panel's reader refuses the card, in the "
      "panel's words", good(text) and "one operator at a time" in text
      and "card would show it" in text and "write the card" in text, text)
Panel.campaign.data = {"id": "ffffffffffff"}
out = run("dataset_card", OWNER=shared)
check("another campaign open in the panel: no reader to blind here",
      os.path.isfile(out["CARD_MD"]))
Panel.campaign.data = {"id": "0123456789ab"}
out = run("dataset_card", OWNER=corr)
check("a correction has no readings to hide", os.path.isfile(
    out["CARD_MD"]))
out = run("time_report", OWNER=shared)
check("Time is not gated in the panel, so it is not here either",
      os.path.isdir(out["OUTPUT_FOLDER"]))
launch._RASTERLABEL = None

print()
print("Cancel in the toolbox")


class Stopped(Feedback):
    """A feedback the person has already cancelled."""

    def isCanceled(self):  # noqa: N802
        return True


def stopped(name, **params):
    del Feedback.said[:]
    try:
        processing.run("rasterlabel:" + name, params, feedback=Stopped())
    except QgsProcessingException as err:
        return str(err)
    return None


before_shared, before_corr = reports_of(shared), reports_of(corr)
for name, owner in (("time_report", shared), ("time_report", corr),
                    ("dataset_card", shared), ("dataset_card", corr)):
    gone = os.path.join(root, "cancel_%s_%s" % (name, os.path.basename(
        owner)))
    text = stopped(name, OWNER=owner, OUTPUT_FOLDER=gone)
    check("%s of %s: Cancel stops it, in the same words as the others"
          % (name, os.path.basename(owner)),
          text is not None and "Cancelled: nothing was written" in text,
          text)
    check("and no folder, not even a .tmp, is left",
          not os.path.exists(gone) and not os.path.exists(gone + ".tmp")
          and not [d for d in os.listdir(root) if d.endswith(".tmp")])
text = stopped("dataset_card", OWNER=shared)
text2 = stopped("time_report", OWNER=shared)
check("without OUTPUT_FOLDER nothing is added to the reports/ either",
      text is not None and text2 is not None
      and reports_of(shared) == before_shared
      and reports_of(corr) == before_corr)

print()
print("through the whole run")
check("no report was listed in any manifest",
      manifest_of(shared, "campaign.json")["reports"] == []
      and "reports" not in manifest_of(corr, "correction.json")
      and "reports" not in manifest_of(tcorr, "correction.json")
      and "reports" not in manifest_of(ucorr, "correction.json"))
check("and not a .tmp folder is left",
      not [d for here, dirs, _ in os.walk(root) for d in dirs
           if d.endswith(".tmp")])

print()
print("unloaded")
plugin.unload()
check("the plugin's unload takes the provider away",
      registry.providerById("rasterlabel") is None)

shutil.rmtree(root, ignore_errors=True)
finish()
