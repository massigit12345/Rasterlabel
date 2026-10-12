"""Model vs corrected, for real: the strips, the matrices, the tables, the map.

Fixture F, worked by hand: a 4 x 4 map on 10 m pixels (100 m2 a pixel),
EPSG:32633, Byte with nodata 0, classes 1 olive, 2 crop and 3 mud.

    model S       corrected C    other C2       swept R
    1 1 2 2       1 1 1 2        1 1 2 2        rows 0 and 1 whole,
    1 1 2 2       1 1 2 2        1 1 2 2        and the pixel at row 2,
    3 3 2 2       3 2 2 2        3 2 2 2        column 1
    3 3 3 0       3 3 3 0        3 3 3 0

What is checked, by the numbers of the cases (T1-T18; T12 and the
panel side of T13 and T14 are in test_reviewed_sidecar):

- T1 whole: the matrix [[4,0,0],[1,5,0],[0,1,4]], OA 13/15, PA, UA, IoU,
  F1, Q and A, and no kappa for the model anywhere;
- T2 the two net transitions, crop -> olive and mud -> crop, 100 m2 each;
- T3 the swept scope, 9 px, 60 % of the map, PA of mud undefined: an
  empty cell in the CSV and null in the JSON;
- T4 and T5 people: C2 against C, whole and swept, with kappa, and the
  excess of the model's error over theirs;
- T6 the map of pairs read back, 1 + i*K + j (crop -> olive is 4, mud ->
  crop 8), 0 outside the scope and on nodata, its tags and its .qml;
- T7 the same layout in UInt16 codes 1000/2000/3000 and in Float32 with NaN
  nodata, the same numbers; a 2.5 is not a code and is counted apart;
- T8 gross against net; T9 a pixel changed and changed back; T10 another
  correction on another grid refused, nothing written; T11 the measure
  grey with the reconcile text when the map it started from is gone;
- T13 a correction with no record of the ground swept: the swept scope is
  the changed pixels alone, and the report says so;
- T15 the modules: the engine and the maths import no QGIS, the bundle
  carries both, the correction's Measure menu has the entry;
- T16 Pontius' identity on random maps; T17 strips of 512 rows give the
  very pairs one read does; T18 a cancel leaves nothing;
- the polygons scope, one matrix per polygon and an interval over five or
  more; an agreement report beside it, matched by name;
- the panel's own way through: Measure ▸ Model vs corrected on a real
  correction, the window, the report in the manifest, the tally line, and
  another person's correction asked about before it is used.

Real GDAL, QGIS faked (correctkit with RL_KIT_REAL_GDAL).
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import csv
import io
import json
import os
import shutil
import sys
import tempfile

os.environ["RL_KIT_REAL_GDAL"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import correctkit as K                                             # noqa: E402
import numpy as np                                                 # noqa: E402
from osgeo import gdal, ogr, osr                                   # noqa: E402

gdal.UseExceptions()
g, check = K.g, K.check
ROOT = os.path.dirname(HERE)

S = np.array([[1, 1, 2, 2], [1, 1, 2, 2], [3, 3, 2, 2], [3, 3, 3, 0]],
             np.uint8)
C = np.array([[1, 1, 1, 2], [1, 1, 2, 2], [3, 2, 2, 2], [3, 3, 3, 0]],
             np.uint8)
C2 = np.array([[1, 1, 2, 2], [1, 1, 2, 2], [3, 2, 2, 2], [3, 3, 3, 0]],
              np.uint8)
R = np.zeros((4, 4), np.uint8)
R[0:2, :] = 1
R[2, 1] = 1
GT = (500000.0, 10.0, 0.0, 4140040.0, 0.0, -10.0)
srs = osr.SpatialReference()
srs.ImportFromEPSG(32633)
WKT = srs.ExportToWkt()
CLASSES = [{"code": 1, "name": "olive", "colour": "#6b8e23"},
           {"code": 2, "name": "crop", "colour": "#e6c229"},
           {"code": 3, "name": "mud", "colour": "#8b5a2b"}]
EPS = 1e-6

root = tempfile.mkdtemp(prefix="rl_mvc_")
K.HOME[0] = os.path.join(root, "project")
os.makedirs(K.HOME[0])


def tif(path, array, nodata=0, dtype=None, gt=GT, desc=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    a = np.asarray(array)
    kind = dtype or {np.dtype(np.uint8): gdal.GDT_Byte,
                     np.dtype(np.uint16): gdal.GDT_UInt16,
                     np.dtype(np.float32): gdal.GDT_Float32}[a.dtype]
    ds = gdal.GetDriverByName("GTiff").Create(path, a.shape[1], a.shape[0],
                                              1, kind)
    ds.SetGeoTransform(gt)
    ds.SetProjection(WKT)
    band = ds.GetRasterBand(1)
    band.WriteArray(a)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    if desc:
        band.SetDescription(desc)
    ds = None
    return path


def read(path):
    ds = gdal.Open(path)
    out = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    return out


def fixture(name, s=S, c=C, r=R, other=None, nodata=0, record=None):
    folder = os.path.join(root, name)
    paths = {"folder": folder,
             "source": tif(os.path.join(folder, "model.tif"), s, nodata),
             "copy": tif(os.path.join(folder, "model_corrected.tif"), c,
                         nodata),
             "changes": tif(os.path.join(folder,
                                         "model_corrected_changes.tif"),
                            (np.asarray(s) != np.asarray(c)).astype(np.uint8)
                            if not (np.asarray(s).dtype.kind == "f")
                            else (~np.isclose(s, c, equal_nan=True))
                            .astype(np.uint8), None, gdal.GDT_Byte,
                            desc="corrected")}
    if r is not None:
        paths["reviewed"] = tif(os.path.join(
            folder, "model_corrected_reviewed.tif"), r, None, gdal.GDT_Byte,
            desc="reviewed")
    else:
        paths["reviewed"] = os.path.join(folder,
                                         "model_corrected_reviewed.tif")
    if other is not None:
        paths["other"] = tif(os.path.join(folder, "other",
                                          "model_corrected.tif"), other,
                             nodata)
    data = {"id": "c0ffee000001", "name": name, "operator": "ANN",
            "operators": ["ANN"], "created": "2020-01-01T00:00:00",
            "source": paths["source"], "band": 1,
            "working_copy": "model_corrected.tif",
            "changes": "model_corrected_changes.tif",
            "grid": {"crs": "EPSG:32633", "pixel_m": [10.0, 10.0]},
            "classes": [dict(c) for c in CLASSES], "operations": 2,
            "changed_m2": 200.0, "swept_m2": 900.0,
            "pairs": {"crop -> olive": [1, 100.0], "mud -> crop": [1, 100.0]}}
    if r is not None:
        data.update({"reviewed": "model_corrected_reviewed.tif",
                     "reviewed_since": 0})
    data.update(record or {})
    with io.open(os.path.join(folder, "correction.json"), "w",
                 encoding="utf-8") as fh:
        json.dump(data, fh)
    paths["data"] = data
    return paths


def recipe(p, scope="whole", other=False, polygons=None, write_map=True,
           codes=(1, 2, 3), names=None, strip_rows=None):
    out = {"model": {"path": p["source"], "band": 1},
           "corrected": {"path": p["copy"], "band": 1}, "scope": scope,
           "changes": p["changes"], "reviewed": p["reviewed"],
           "polygons": polygons,
           "codes": list(codes),
           "names": names or {c["code"]: c["name"] for c in CLASSES},
           "colours": {c["code"]: c["colour"] for c in CLASSES},
           "pixel_m2": 100.0, "write_map": write_map}
    if other:
        out["other"] = {"path": p["other"], "band": 1}
    if strip_rows:
        out["strip_rows"] = strip_rows
    return out


def report(p, scope="whole", other=False, people=None, polygons=None,
           progress=None, **kw):
    if other and people is None:
        people = {"kind": "correction", "operator": "GIU",
                  "name": "giu fix", "path": p["other"]}
    return g["mvc_report"](recipe(p, scope, other, polygons, **kw),
                           p["data"], p["folder"], people, None, progress)


def near(a, b, eps=EPS):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(near(x, y, eps) for x, y in zip(a, b))
    if a != a:
        return b is None or b != b
    return abs(float(a) - float(b)) < eps


def per_class(result, key):
    return [c[key] for c in result["summarized"]["metrics"]["per_class"]]


def csv_rows(path):
    with io.open(path, encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def summary_of(result):
    with io.open(os.path.join(result["folder"], "summary.json"),
                 encoding="utf-8") as fh:
        return json.load(fh)


def box(x0, y0, x1, y1):
    ring = ogr.Geometry(ogr.wkbLinearRing)
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)):
        ring.AddPoint_2D(x, y)
    poly = ogr.Geometry(ogr.wkbPolygon)
    poly.AddGeometry(ring)
    return bytes(poly.ExportToWkb())


def px_box(c0, r0, c1, r1):
    return box(GT[0] + c0 * GT[1], GT[3] + r1 * GT[5],
               GT[0] + c1 * GT[1], GT[3] + r0 * GT[5])


try:
    # ------------------------------------------------------------- T1, T2
    print("T1 the whole map")
    F = fixture("f")
    whole = report(F)
    s = whole["summarized"]
    check("the matrix is [[4,0,0],[1,5,0],[0,1,4]], model in rows",
          s["matrix"].tolist() == [[4, 0, 0], [1, 5, 0], [0, 1, 4]],
          s["matrix"].tolist())
    o = s["metrics"]["overall"]
    check("15 px, OA 0.866667", s["n"] == 15 and near(o["po"], 13 / 15.0),
          (s["n"], o["po"]))
    check("PA [0.8, 0.833333, 1.0]", near(per_class(whole, "rate_B"),
                                          [0.8, 5 / 6.0, 1.0]))
    check("UA [1.0, 0.833333, 0.8]", near(per_class(whole, "rate_A"),
                                          [1.0, 5 / 6.0, 0.8]))
    check("IoU [0.8, 0.714286, 0.8]", near(per_class(whole, "iou"),
                                           [0.8, 5 / 7.0, 0.8]))
    check("F1 [0.888889, 0.833333, 0.888889]",
          near(per_class(whole, "f1"), [8 / 9.0, 5 / 6.0, 8 / 9.0]))
    check("Q 0.066667, A 0.066667, D 0.133333",
          near(o["quantity"], 1 / 15.0) and near(o["allocation"], 1 / 15.0)
          and near(o["disagreement"], 2 / 15.0), o)
    check("q_k [0.066667, 0, 0.066667], a_k [0, 0.133333, 0]",
          near(per_class(whole, "q"), [1 / 15.0, 0, 1 / 15.0])
          and near(per_class(whole, "a"), [0, 2 / 15.0, 0]))
    check("no kappa for the model", "kappa" not in o, sorted(o))
    sj = summary_of(whole)
    check("nor in summary.json",
          "kappa" not in sj["overall"] and sj["headline"]["people_kappa"]
          is None and not [n for n in sj["notes"] if "kappa" in n
                           and "no kappa" not in n], sj["overall"])
    check("summary.json says version 1.1, the axes and the reference",
          sj["version"] == "1.1" and sj["axes"] == {"A": "model",
                                                    "B": "corrected"}
          and sj["rasterlabel:report"] == "model_vs_corrected"
          and any("reference = the corrected map" in n for n in sj["notes"]),
          (sj["version"], sj["axes"]))
    check("the folder is reports/model_vs_corrected/whole_<stamp>, whole",
          os.path.dirname(whole["folder"]) == os.path.join(
              F["folder"], "reports", "model_vs_corrected")
          and os.path.basename(whole["folder"]).startswith("whole_")
          and not whole["folder"].endswith(".tmp"), whole["folder"])
    check("with every file it lists", all(
        os.path.exists(os.path.join(whole["folder"], f))
        for f in sj["files"]) and "pairs.csv" in sj["files"]
        and "model_corrected_mvc_whole_pairs.tif" in sj["files"],
        sj["files"])
    rows = csv_rows(os.path.join(whole["folder"], "confusion.csv"))
    check("confusion.csv: model \\ corrected, code and name, totals",
          rows[0] == ["model \\ corrected", "1 olive", "2 crop", "3 mud",
                      "total"] and rows[2] == ["2 crop", "1", "5", "0", "6"]
          and rows[4] == ["total", "5", "6", "4", "15"], rows[:5])
    check("and the same in m2 below it",
          ["2 crop", "100", "500", "0", "600"] in rows, rows[5:])

    print()
    print("T2 the net transitions")
    t = s["transitions"]
    check("exactly two", len(t) == 2, t)
    words = {(r["a_name"], r["b_name"]): r for r in t}
    check("crop -> olive, 1 px, 100 m2, value 1 + 1*3 + 0 = 4",
          ("crop", "olive") in words
          and words[("crop", "olive")]["pixels"] == 1
          and near(words[("crop", "olive")]["area_m2"], 100)
          and words[("crop", "olive")]["value"] == 4, t)
    check("mud -> crop, 1 px, 100 m2, value 1 + 2*3 + 1 = 8",
          ("mud", "crop") in words
          and words[("mud", "crop")]["value"] == 8, t)
    check("net changed 2 px, 200 m2",
          sj["overall"]["changed_px_net"] == 2
          and near(sj["overall"]["changed_m2_net"], 200), sj["overall"])
    pr = csv_rows(os.path.join(whole["folder"], "pairs.csv"))
    head = pr[0]
    crop_olive = [r for r in pr[1:] if r[head.index("value")] == "4"]
    check("pairs.csv carries the logged strokes of the same pair",
          crop_olive and crop_olive[0][head.index("logged_strokes")] == "1"
          and crop_olive[0][head.index("logged_m2")] == "100", pr)

    # ------------------------------------------------------------- T3
    print()
    print("T3 the ground swept")
    swept = report(F, "swept")
    s3 = swept["summarized"]
    check("the matrix is [[4,0,0],[1,3,0],[0,1,0]], 9 px",
          s3["matrix"].tolist() == [[4, 0, 0], [1, 3, 0], [0, 1, 0]]
          and s3["n"] == 9, s3["matrix"].tolist())
    o3 = s3["metrics"]["overall"]
    check("OA 0.777778, Q 0.111111, A 0.111111",
          near(o3["po"], 7 / 9.0) and near(o3["quantity"], 1 / 9.0)
          and near(o3["allocation"], 1 / 9.0), o3)
    pa = per_class(swept, "rate_B")
    check("PA [0.8, 0.75, undefined]",
          near(pa[:2], [0.8, 0.75]) and pa[2] != pa[2], pa)
    check("UA [1.0, 0.75, 0.0], IoU [0.8, 0.6, 0.0]",
          near(per_class(swept, "rate_A"), [1.0, 0.75, 0.0])
          and near(per_class(swept, "iou"), [0.8, 0.6, 0.0]))
    sj3 = summary_of(swept)
    check("share of the map 0.6", near(sj3["scope"]["share_of_map"], 0.6),
          sj3["scope"])
    rows = csv_rows(os.path.join(swept["folder"], "per_class.csv"))
    col = rows[0].index("producers_accuracy")
    check("the CSV cell for PA of mud is empty", rows[3][col] == "",
          rows[3])
    check("and null in the JSON",
          sj3["per_class"]["3"]["producers_accuracy"] is None,
          sj3["per_class"]["3"])
    check("the note says the swept ground is a lower bound",
          any("lower bound" in n for n in sj3["notes"]), sj3["notes"])

    # ------------------------------------------------------------- T4, T5
    print()
    print("T4 people against people, the whole map")
    P = fixture("people", other=C2)
    pw = report(P, other=True)
    pe = pw["summarized"]["people"]
    check("the matrix is [[4,0,0],[1,6,0],[0,0,4]]",
          pe["matrix"].tolist() == [[4, 0, 0], [1, 6, 0], [0, 0, 4]],
          pe["matrix"].tolist())
    check("OA 0.933333, pe 0.346667, kappa 0.897959, Q 0.066667, A 0",
          near(pe["overall"]["oa"], 14 / 15.0)
          and near(pe["overall"]["pe"], 0.346667)
          and near(pe["overall"]["kappa"], 0.897959)
          and near(pe["overall"]["quantity"], 1 / 15.0)
          and near(pe["overall"]["allocation"], 0.0), pe["overall"])
    check("IoU [0.8, 0.857143, 1.0]",
          near([pe["matched"][c]["iou"] for c in (1, 2, 3)],
               [0.8, 6 / 7.0, 1.0]))
    side = {r["class"]: r for r in pw["summarized"]["side_by_side"]}
    check("excess: olive 0, crop 0.142857, mud 0.2",
          near(side["olive"]["excess_error"], 0)
          and near(side["crop"]["excess_error"], 1 / 7.0)
          and near(side["mud"]["excess_error"], 0.2), side)
    sjp = summary_of(pw)
    check("side_by_side.csv is written, and the kappa is the people's",
          "side_by_side.csv" in sjp["files"]
          and near(sjp["people"]["overall"]["kappa"], 0.897959)
          and near(sjp["headline"]["people_kappa"], 0.897959), sjp["files"])
    check("and the model still has none", "kappa" not in sjp["overall"])

    print()
    print("T5 people on the ground swept")
    ps = report(P, "swept", other=True)
    pe5 = ps["summarized"]["people"]
    iou5 = [pe5["matched"][c]["iou"] for c in (1, 2, 3)]
    check("OA 0.888889, IoU [0.8, 0.8, undefined], kappa 0.780488",
          near(pe5["overall"]["oa"], 8 / 9.0) and near(iou5[:2], [0.8, 0.8])
          and iou5[2] != iou5[2] and near(pe5["overall"]["kappa"], 0.780488),
          (pe5["overall"], iou5))

    # ------------------------------------------------------------- T6
    print()
    print("T6 the map of pairs read back")
    tif_w = os.path.join(whole["folder"], "model_corrected_mvc_whole_pairs.tif")
    m = read(tif_w)
    check("(0,0) = 1, (0,2) = 4, (2,1) = 8, (3,3) = 0",
          (m[0, 0], m[0, 2], m[2, 1], m[3, 3]) == (1, 4, 8, 0), m)
    tif_s = os.path.join(swept["folder"], "model_corrected_mvc_swept_pairs.tif")
    ms = read(tif_s)
    check("on the swept scope (3,0) is 0, outside it", ms[3, 0] == 0
          and ms[0, 0] == 1 and ms[2, 1] == 8, ms)
    ds = gdal.Open(tif_w)
    md = ds.GetMetadata()
    band = ds.GetRasterBand(1)
    check("on the copy's grid, Byte, nodata 0",
          ds.GetGeoTransform() == GT and band.DataType == gdal.GDT_Byte
          and band.GetNoDataValue() == 0)
    check("its tags say what it is", md.get("RASTERLABEL_COMPARISON")
          == "model_vs_corrected" and md.get("RASTERLABEL_SCOPE") == "whole"
          and md.get("RASTERLABEL_VERSION") == "1.1", md)
    names = band.GetCategoryNames() or []
    check("its classes are inside it",
          len(names) > 8 and names[4] == "crop → olive"
          and names[1] == "same: olive", names[:9])
    band = None
    ds = None
    qml = os.path.splitext(tif_w)[0] + ".qml"
    check("and a .qml beside it", os.path.exists(qml)
          and "crop → olive" in io.open(qml, encoding="utf-8").read())

    # ------------------------------------------------------------- T7
    print()
    print("T7 any codes: UInt16, Float32 with NaN")
    big = {1: 1000, 2: 2000, 3: 3000}

    def remap(a, kind):
        out = np.zeros(a.shape, kind)
        for k, v in big.items():
            out[a == k] = v
        return out

    U = fixture("u16", remap(S, np.uint16), remap(C, np.uint16))
    u = g["mvc_report"](recipe(U, codes=(1000, 2000, 3000),
                               names={1000: "olive", 2000: "crop",
                                      3000: "mud"}),
                        U["data"], U["folder"])
    check("UInt16 codes 1000/2000/3000: the same matrix",
          u["summarized"]["matrix"].tolist() == s["matrix"].tolist()
          and u["summarized"]["codes"] == [1000, 2000, 3000],
          u["summarized"]["matrix"].tolist())
    check("the same IoU", near(per_class(u, "iou"), per_class(whole, "iou")))
    check("the map of pairs is still a Byte (3 codes)",
          read(u["map"]["path"]).dtype == np.uint8 and
          read(u["map"]["path"])[0, 2] == 4)
    sf = S.astype(np.float32)
    cf = C.astype(np.float32)
    sf[3, 3] = cf[3, 3] = np.nan
    Fl = fixture("f32", sf, cf, nodata=float("nan"))
    fl = report(Fl)
    check("Float32 with NaN nodata: the same matrix",
          fl["summarized"]["matrix"].tolist() == s["matrix"].tolist(),
          fl["summarized"]["matrix"].tolist())
    sf2, cf2 = sf.copy(), cf.copy()
    sf2[3, 3] = cf2[3, 3] = 2.5
    Fl2 = fixture("f32b", sf2, cf2, nodata=float("nan"))
    fl2 = report(Fl2)
    sj7 = summary_of(fl2)
    check("a 2.5 is no code: not_a_code 1, and it is left out",
          sj7["overall"]["not_a_code"] == 1
          and fl2["summarized"]["matrix"].tolist() == s["matrix"].tolist(),
          sj7["overall"])

    # ------------------------------------------------------------- T8, T9
    print()
    print("T8 gross against net")
    G = fixture("gross", record={"changed_m2": 300.0, "operations": 3})
    gr = summary_of(report(G))
    check("logged changed_m2_gross 300, net 200",
          near(gr["logged"]["changed_m2_gross"], 300)
          and near(gr["overall"]["changed_m2_net"], 200)
          and gr["logged"]["operations"] == 3, (gr["logged"], gr["overall"]))
    check("swept over changed from the log",
          near(gr["logged"]["swept_over_changed"], 3.0), gr["logged"])

    print()
    print("T9 changed and changed back")
    A = fixture("aba")
    ch = read(A["changes"])
    ch[1, 1] = 1
    tif(A["changes"], ch, None, gdal.GDT_Byte, desc="corrected")
    ab = report(A)
    sja = summary_of(ab)
    check("marked_but_unchanged 1", sja["overall"]["marked_but_unchanged"]
          == 1, sja["overall"])
    check("and the pixel counts as agreeing",
          ab["summarized"]["matrix"].tolist() == s["matrix"].tolist())

    # ------------------------------------------------------------- T10
    print()
    print("T10 another correction on another grid")
    X = fixture("grid", other=C2)
    tif(X["other"], np.ones((5, 4), np.uint8))
    before = os.listdir(X["folder"])
    try:
        report(X, other=True)
        refused = None
    except IOError as err:
        refused = str(err)
    check("refused, with the reason", refused is not None
          and "4 x 5 pixels" in refused and "4 x 4" in refused, refused)
    check("and nothing written", os.listdir(X["folder"]) == before
          and not os.path.exists(os.path.join(X["folder"], "reports",
                                              "model_vs_corrected"))
          or not os.listdir(os.path.join(X["folder"], "reports",
                                         "model_vs_corrected")),
          os.listdir(X["folder"]))
    check("the setup window says it too, before any run",
          "4 x 5 pixels" in (g["mvc_grid_refusal"](
              X["other"], X["copy"], "GIU's correction") or ""))

    # ------------------------------------------------------------- T10b
    print()
    print("T10b the map it started from had its system set in QGIS")
    # Layer > Set CRS on a georeferenced file that names none: the copy is
    # written with the system, the map it started from never has one.
    X = fixture("setcrs")
    bare = os.path.join(X["folder"], "bare", "model.tif")
    os.makedirs(os.path.dirname(bare))
    mem = gdal.GetDriverByName("GTiff").Create(bare, 4, 4, 1, gdal.GDT_Byte)
    mem.SetGeoTransform(GT)
    mem.GetRasterBand(1).WriteArray(S)
    mem.GetRasterBand(1).SetNoDataValue(0)
    mem = None
    X["data"]["source"] = bare
    check("the file names no system, the copy does",
          not gdal.Open(bare).GetProjection()
          and gdal.Open(X["copy"]).GetProjection())
    check("the setup window does not refuse it for its system",
          g["mvc_grid_refusal"](bare, X["copy"], "the map it started from",
                                empty_ok=True) is None)
    check("though a map that is not that map still is refused",
          "coordinate system" in (g["mvc_grid_refusal"](
              bare, X["copy"], "another map") or ""))
    X["source"] = bare
    done = report(X)
    check("and the report is made", done and done.get("folder")
          and os.path.isdir(done["folder"]), done)
    other_system = os.path.join(X["folder"], "bare", "elsewhere.tif")
    mem = gdal.GetDriverByName("GTiff").Create(other_system, 4, 4, 1,
                                               gdal.GDT_Byte)
    mem.SetGeoTransform(GT)
    wgs = osr.SpatialReference()
    wgs.ImportFromEPSG(4326)
    mem.SetProjection(wgs.ExportToWkt())
    mem = None
    check("a map in another system is refused all the same",
          "another coordinate system" in (g["mvc_grid_refusal"](
              other_system, X["copy"], "the map it started from",
              empty_ok=True) or ""))

    # ------------------------------------------------------------- T13
    print()
    print("T13 a correction with no record of the ground swept")
    L = fixture("legacy", r=None)
    lg = report(L, "swept")
    sjl = summary_of(lg)
    check("the swept scope is the changed pixels alone: 2 px",
          lg["summarized"]["n"] == 2, lg["summarized"]["n"])
    check("and it says so", any("not recorded" in n for n in sjl["notes"])
          and sjl["reviewed"]["recorded"] is False
          and sjl["reviewed"]["path"] is None, sjl["notes"])
    L2 = fixture("since", record={"reviewed_since": 7})
    sj13 = summary_of(report(L2, "swept"))
    check("strokes before the record are said to have left no footprint",
          sj13["reviewed"]["reviewed_since"] == 7
          and sj13["logged"]["strokes_without_footprint"] == 7
          and any("first 7 strokes left no footprint" in n
                  for n in sj13["notes"]), sj13["notes"])

    # ------------------------------------------------------------- polygons
    print()
    print("inside the polygons of a layer")
    Pg = fixture("poly")
    two = [{"fid": 1, "wkb": px_box(0, 0, 2, 2)},
           {"fid": 2, "wkb": px_box(2, 2, 4, 4)}]
    po = report(Pg, "polygons", polygons=two)
    sp = po["summarized"]
    check("the pixels whose centres are inside: 4 + 3 (one is nodata)",
          sp["n"] == 7 and [r["pixels"] for r in sp["polygon_rows"]]
          == [4, 3], [r["pixels"] for r in sp["polygon_rows"]])
    check("polygon 1 all olive, all agreeing; polygon 2 one mud -> crop",
          near([r["oa"] for r in sp["polygon_rows"]], [1.0, 1.0])
          and sp["polygon_rows"][0]["changed_px"] == 0,
          sp["polygon_rows"])
    rows = csv_rows(os.path.join(po["folder"], "polygons.csv"))
    check("polygons.csv: fid, pixels, area, swept share, changed, OA",
          rows[0] == ["fid", "pixels", "area_m2", "swept_share",
                      "changed_px", "oa"] and rows[1][:2] == ["1", "4"],
          rows)
    check("fewer than 5 polygons: no interval, and why",
          "fewer than 5 polygons" in (sp["bootstrap"] or {}).get("reason",
                                                                  ""),
          sp["bootstrap"])
    five = [{"fid": i + 1, "wkb": px_box(c, r, c + 2, r + 2)}
            for i, (c, r) in enumerate(((0, 0), (2, 0), (0, 2), (2, 2),
                                        (1, 1)))]
    p5 = report(Pg, "polygons", polygons=five)
    ci = (p5["summarized"]["bootstrap"] or {}).get("ci") or {}
    check("five polygons: an interval for OA over the polygons",
          ci.get("po") and ci["po"][0] <= ci["po"][1], ci.get("po"))
    sj5 = summary_of(p5)
    check("one pixel under two polygons counts once in the pooled numbers",
          p5["summarized"]["n"] == 15 and sj5["scope"]["polygons"] == 5,
          p5["summarized"]["n"])
    rows = csv_rows(os.path.join(p5["folder"], "per_class.csv"))
    check("per_class.csv carries the interval of IoU",
          "iou_ci_low" in rows[0], rows[0])

    # ------------------------------------------------------------- report
    print()
    print("an agreement report beside it")
    rep = os.path.join(root, "camp", "reports", "agreement", "A_vs_B")
    os.makedirs(rep)
    with io.open(os.path.join(rep, "summary.json"), "w",
                 encoding="utf-8") as fh:
        json.dump({"rasterlabel:report": "agreement",
                   "axes": {"A": "ANNA, pass 1", "B": "BRUNO, pass 1"},
                   "pooled": {"overall": 0.9, "kappa": 0.8, "quantity": 0.05,
                              "allocation": 0.05}}, fh)
    with io.open(os.path.join(rep, "per_class.csv"), "w", encoding="utf-8",
                 newline="") as fh:
        out = csv.writer(fh, lineterminator="\n")
        out.writerow(["code", "name", "iou", "iou_ci_low", "iou_ci_high",
                      "f1"])
        out.writerow([7, " Olive ", 0.9, 0.85, 0.95, 0.94])
        out.writerow([2, "wheat", 0.7, "", "", 0.8])
        out.writerow([9, "sand", 0.5, "", "", 0.6])
    people = g["mvc_read_people"](os.path.join(rep, "summary.json"))
    check("read back: kind, readings, overall",
          people["kind"] == "agreement_report"
          and people["readings"] == ["ANNA, pass 1", "BRUNO, pass 1"]
          and near(people["overall"]["kappa"], 0.8), people)
    ar = report(F, people=people)
    side = {r["code"]: r for r in ar["summarized"]["side_by_side"]}
    check("olive matched by name, crop by code, sand unmatched",
          sorted(side) == [1, 2]
          and ar["summarized"]["people"]["unmatched"] == ["sand"], side)
    check("a class is beyond the people only below their low end",
          side[1]["beyond_people"] and near(side[1]["people_iou_lo"], 0.85),
          side[1])
    sja = summary_of(ar)
    check("and the summary says it is not a paired comparison",
          any("not a paired comparison" in n for n in sja["notes"])
          and sja["people"]["unmatched"] == ["sand"], sja["notes"])
    try:
        g["mvc_read_people"](whole["folder"])
        wrong = None
    except IOError as err:
        wrong = str(err)
    check("a report of another kind is refused", wrong is not None
          and "not the summary.json of an agreement report" in wrong, wrong)

    # ------------------------------------------------------------- T15
    print()
    print("T15 the modules")
    pkg = os.path.join(ROOT, "rasterlabel")
    if os.path.isdir(pkg):
        for name in ("agreement.py", "model_vs_corrected.py"):
            tree = ast.parse(io.open(os.path.join(pkg, name),
                                     encoding="utf-8").read())
            mods = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    mods.add((node.module or "").split(".")[0])
            check("%s imports no QGIS and no Qt" % name,
                  not mods & {"qgis", "PyQt5", "PyQt6"}, sorted(mods))
        order = io.open(os.path.join(ROOT, "tools", "bundle.py"),
                        encoding="utf-8").read()
        check("the bundle carries the engine and its window",
              '"model_vs_corrected"' in order and '"ui_mvc"' in order)
    entries = g["measure_entries"](g["CORRECTION_MEASURES"])
    labels = [e[1] for e in entries if e is not None]
    check("the correction's Measure menu has Model vs corrected…",
          "Model vs corrected…" in labels, labels)

    # ------------------------------------------------------------- T16
    print()
    print("T16 Pontius' identity on random maps")
    rng = np.random.default_rng(16)
    a16 = rng.integers(1, 7, (50, 50)).astype(np.uint8)
    b16 = a16.copy()
    flip = rng.random((50, 50)) < 0.35
    b16[flip] = rng.integers(1, 7, int(flip.sum()))
    Q = fixture("pontius", a16, b16, r=None)
    q16 = g["mvc_report"](recipe(Q, codes=range(1, 7), names={
        i: "c%d" % i for i in range(1, 7)}, write_map=False),
        Q["data"], Q["folder"])
    met = q16["summarized"]["metrics"]
    ov = met["overall"]
    check("|D - (Q + A)| < 1e-9",
          abs(ov["disagreement"] - (ov["quantity"] + ov["allocation"]))
          < 1e-9, ov)
    check("sum of (q_k + a_k) / 2 is D",
          abs(sum((c["q"] + c["a"]) / 2.0 for c in met["per_class"])
              - ov["disagreement"]) < 1e-9)

    # ------------------------------------------------------------- T17
    print()
    print("T17 strips give the pairs one read gives")
    a17 = rng.integers(0, 9, (700, 1500)).astype(np.uint8)
    b17 = a17.copy()
    flip = rng.random((700, 1500)) < 0.2
    b17[flip] = rng.integers(0, 9, int(flip.sum()))
    W = fixture("strips", a17, b17, r=None, nodata=None)
    in_strips = g["mvc_compare"](dict(recipe(W, codes=range(9),
                                             write_map=False), map=None))
    at_once = g["mvc_compare"](dict(recipe(W, codes=range(9),
                                           write_map=False, strip_rows=700),
                                    map=None))
    check("the same dict of pairs with 512 rows a strip as with one read",
          in_strips["pairs"] == at_once["pairs"]
          and sum(in_strips["pairs"].values()) == 700 * 1500,
          sum(in_strips["pairs"].values()))

    # ------------------------------------------------------------- T18
    print()
    print("T18 a cancel leaves nothing")
    Cn = fixture("cancel", a17, b17, r=None, nodata=None)
    base = os.path.join(Cn["folder"], "reports", "model_vs_corrected")
    try:
        g["mvc_report"](recipe(Cn, codes=range(9)), Cn["data"],
                        Cn["folder"], None, None,
                        lambda done, total: done < 512)
        stopped = False
    except g["MvcCancelled"]:
        stopped = True
    check("the run stops", stopped)
    check("and no report folder is left, .tmp or not",
          not os.path.isdir(base) or os.listdir(base) == [],
          os.listdir(base) if os.path.isdir(base) else None)

    # ------------------------------------------------------------- panel
    print()
    print("the panel's own way: Measure ▸ Model vs corrected")
    data_dir = os.path.join(root, "maps")
    src = tif(os.path.join(data_dir, "model.tif"), S)
    styled = K.Paletted(None, 1, [K.Paletted.Class(c["code"], c["colour"],
                                                   c["name"])
                                  for c in CLASSES])
    layer = K.add_layer(K.Layer(src, "model", styled))
    panel = g["Panel"]()

    def new_on(folder, who):
        def answer(d):
            d.existing.setCurrentIndex(d.existing.findData("new:"))
            d.name.setText(os.path.basename(folder))
            d.raster.setCurrentIndex(d.raster.findData(layer.id()))
            d.fill_bands()
            d.folder.setText(folder)
            d.operator.setText(who)
            return 1
        return answer

    def stroke(section, rows, cols, from_code, into):
        inside = np.ones((rows[1] - rows[0], cols[1] - cols[0]), bool)
        section.mask_of = lambda geom: (cols[0], rows[0], inside)
        section.choose_from(from_code)
        section.choose_class(into)
        section.paint(K.Stroke())

    # GIU's correction first, so ANN's window can offer it
    K.ANSWERS["OpenCorrection"] = new_on(os.path.join(root, "giu_fix"), "giu")
    K.ANSWERS["ConfirmClasses"] = lambda d: 1
    panel.toggle_module(1)
    stroke(panel.section, (2, 3), (1, 2), 3, 2)       # mud -> crop at (2,1)
    panel.close_correction()
    ann = os.path.join(root, "ann_fix")
    K.ANSWERS["OpenCorrection"] = new_on(ann, "ann")
    K.ANSWERS["ConfirmClasses"] = lambda d: 1

    def press(label):
        def answer(box):
            for b in box.buttons():
                if b.text().replace("&", "") == label:
                    b.click()
            return 0
        return answer

    # the map has GIU's correction already: a new one beside it
    K.ANSWERS["QMessageBox"] = press("Make a new correction")
    panel.toggle_module(1)
    section = panel.section
    check("Correct is open on ANN's correction",
          type(section).__name__ == "CorrectionSection")
    # rows 0-1, cols 1-2: olive crop / olive crop; crop -> olive
    stroke(section, (0, 2), (1, 3), 2, 1)
    menu = K.QtWidgets.QMenu()
    acts = {a.objectName(): a for a in g["measure_fill"](menu, "correction",
                                                         panel)}
    act = acts.get("measure_model_vs_corrected")
    check("the entry is there and can be pressed",
          act is not None and act.isEnabled(), sorted(acts))
    SEEN = {}

    def setup(d):
        SEEN["whole"] = d.whole_note.text()
        SEEN["swept"] = d.swept_note.text()
        SEEN["people"] = [d.people.itemText(i) for i in
                          range(d.people.count())]
        SEEN["polygons_off"] = not d.inside.isEnabled()
        d.swept.setChecked(True)
        d.refresh()
        SEEN["folder"] = d.where.text()
        SEEN["go"] = d.go.isEnabled()
        return 1

    def shown(w):
        SEEN["window"] = w
        SEEN["text"] = w.text()
        return 1

    K.ANSWERS["ModelVsCorrectedSetup"] = setup
    K.ANSWERS["ReportWindow"] = shown
    result = g["mvc_start"](panel)
    check("the window says the whole map, 15 px, an upper bound",
          "15 px" in SEEN.get("whole", "") and "upper bound"
          in SEEN.get("whole", ""), SEEN.get("whole"))
    check("and the ground swept, 4 px, 26.7 % of the map, a lower bound",
          "4 px, 26.7 % of the map" in SEEN.get("swept", "")
          and "lower bound" in SEEN.get("swept", ""), SEEN.get("swept"))
    check("it offers nobody, GIU's correction and an agreement report",
          SEEN.get("people", [None])[0] == "nobody"
          and any(t.startswith("GIU's correction") for t in SEEN["people"])
          and SEEN["people"][-1] == "an agreement report…",
          SEEN.get("people"))
    check("no polygon layer: that ground is off", SEEN.get("polygons_off"))
    check("the folder shown is under the correction's reports",
          os.path.join("ann_fix", "reports", "model_vs_corrected", "swept_")
          in SEEN.get("folder", ""), SEEN.get("folder"))
    check("a report was made", result is not None
          and os.path.isdir(result["folder"]), K.BOXES[-2:])
    if result is not None:
        check("on the 4 px swept: the model agrees on half",
              result["summarized"]["n"] == 4
              and near(result["summarized"]["metrics"]["overall"]["po"],
                       0.5), result["summarized"]["n"])
        check("the window shows it", "50.0 %" in SEEN.get("text", "")
              and "crop → olive" in SEEN.get("text", ""), SEEN.get("text"))
        view = SEEN["window"].views[0]
        tips = [view.horizontalHeaderItem(i).toolTip()
                for i in range(view.columnCount())
                if view.horizontalHeaderItem(i).text() == "PA"]
        check("PA explains itself, the corrected map as the reference",
              tips and "reference" in tips[0], tips)
        data = json.load(open(os.path.join(ann, "correction.json"),
                              encoding="utf-8"))
        entry = [e for e in data.get("reports") or []
                 if e.get("kind") == "model_vs_corrected"]
        check("the manifest remembers it, with its headline",
              entry and entry[-1]["label"] == "swept"
              and entry[-1]["headline"]["pixels"] == 4
              and entry[-1]["folder"].startswith(
                  "reports/model_vs_corrected/swept_"), entry)
        check("and the tally says it", "last measured, ground swept: the "
              "model agrees on 50.0 % of 4 px" in section.tally.text(),
              section.tally.text())
    names = section.own_files()
    check("T14: own_files names the record of the ground swept and reports",
          "model_corrected_reviewed.tif" in names and "reports" in names,
          names)
    check("so the folder with its report is not taken for a shared one",
          not section.shares_folder(ann), os.listdir(ann))

    print()
    print("another person's correction is asked about first")

    def setup_people(d):
        i = [k for k in range(d.people.count())
             if d.people.itemText(k).startswith("GIU's correction")][0]
        d.people.setCurrentIndex(i)
        SEEN["people_note"] = d.people_note.text()
        return 1

    def decline(box):
        SEEN["asked"] = box.text()
        return 0

    K.ANSWERS["ModelVsCorrectedSetup"] = setup_people
    K.ANSWERS["QMessageBox"] = decline
    before = sorted(os.listdir(os.path.join(ann, "reports",
                                            "model_vs_corrected")))
    again = g["mvc_start"](panel)
    check("it asks, with what it ends", "blindness" in SEEN.get("asked", ""),
          SEEN.get("asked"))
    check("declined: nothing is run", again is None and sorted(os.listdir(
        os.path.join(ann, "reports", "model_vs_corrected"))) == before)

    K.ANSWERS["ModelVsCorrectedSetup"] = setup_people
    K.ANSWERS["QMessageBox"] = press("Compare")
    K.ANSWERS["ReportWindow"] = shown
    both = g["mvc_start"](panel)
    check("agreed: the people's numbers are beside the model's",
          both is not None and both["summarized"]["people"] is not None
          and "People agree on" in SEEN.get("text", ""), K.BOXES[-2:])
    if both is not None:
        pp = both["summarized"]["people"]["overall"]
        # GIU changed (2,1) mud -> crop; ANN (0,2) and (1,2) crop -> olive
        check("on the whole map: 12 of 15 agree, with kappa",
              near(pp["oa"], 12 / 15.0) and pp["kappa"] is not None, pp)
    check("and no layer of the other's map", not [
        l for l in K.LOADED.values()
        if "giu" in str(getattr(l, "path", "")).lower()])

    print()
    print("T11 the map it started from gone")
    moved = src + ".away"
    os.rename(src, moved)
    try:
        acts = {a.objectName(): a for a in g["measure_fill"](
            menu, "correction", panel)}
        act = acts.get("measure_model_vs_corrected")
        check("the entry is grey", act is not None and not act.isEnabled())
        check("and its tooltip carries the reconcile text",
              act is not None and "the map it started from is no longer "
              "where it was" in act.toolTip().lower()
              and "put it back" in act.toolTip(), act and act.toolTip())
    finally:
        os.rename(moved, src)
    panel.close_correction()
finally:
    shutil.rmtree(root, ignore_errors=True)

sys.exit(K.finish())
