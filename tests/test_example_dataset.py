"""The example dataset: made again, it is the same; and it is what the tutorial says.

tools/make_example.py writes examples/rasterlabel_example/ from a fixed seed:
a synthetic scene, the map of an imaginary classifier on the same grid, a
sample design and the legend. This suite makes it twice into scratch folders
and holds it to what the tutorial (docs/tutorial.md) tells a person:

- the same call twice gives the same bytes, file by file, the GeoPackage
  included (GDAL stamps it with the time of the run; the generator fixes
  that stamp), and a folder given on the command line is where it goes;
- the whole folder is under 3 MB;
- scene_rgb.tif is 600 x 400 pixels of Byte in three bands, half a metre, in
  UTM 33 N (EPSG:32633), and not flat;
- model_map.tif is two bands on the same grid: classes 1 to 4, all four
  present, with the colour table and the names of the classes beside it
  (the .aux.xml GDAL keeps for a file of several bands) and a .qml QGIS
  reads; band 2 is "probability x255", never 0, and lower where the map is
  wrong than where it is right;
- sample_design.gpkg holds twelve points, three in each stratum, the five
  columns an import keeps (sample_id, stratum, incl_prob, weight, design),
  inclusion probabilities n_h / N_h of the strata of the map, weights that
  are their inverse, and frames of 60 pixels round them that stay inside the
  scene and never overlap;
- classes.csv names the four classes of the map, with the colours of its
  table;
- the files committed in examples/rasterlabel_example/ are the ones this
  generator makes (the pixels, compared; not the bytes, which a GDAL or a
  libm of another build may write differently).

Needs the GDAL bindings (tests/run.py, NEEDS_GDAL).
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import csv
import io
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)[:500]) if not cond and detail != "" else ""))
    if not cond:
        fails.append(name)


try:
    import numpy as np
    from osgeo import gdal, ogr, osr
except ImportError as e:
    print("the GDAL bindings are not importable here: %s" % e)
    sys.exit(1)
gdal.UseExceptions()
ogr.UseExceptions()
import make_example as ME  # noqa: E402

root = tempfile.mkdtemp(prefix="rl_example_")


def raw(path):
    with open(path, "rb") as fh:
        return fh.read()


def read_all(path):
    """(array of every band, the dataset's geotransform, projection, bands)."""
    ds = gdal.Open(path)
    try:
        a = ds.ReadAsArray()
        return (a if a.ndim == 3 else a[None], ds.GetGeoTransform(),
                ds.GetProjection(), ds.RasterCount)
    finally:
        ds = None


def points(path):
    ds = ogr.Open(path)
    try:
        lyr = ds.GetLayer(0)
        out = []
        for f in lyr:
            g = f.GetGeometryRef()
            row = {k: f.GetField(k) for k in (
                "sample_id", "stratum", "incl_prob", "weight", "design")}
            row["x"], row["y"] = g.GetX(), g.GetY()
            out.append(row)
        return out, lyr.GetSpatialRef().GetAuthorityCode(None), \
            [lyr.GetLayerDefn().GetFieldDefn(i).GetName()
             for i in range(lyr.GetLayerDefn().GetFieldCount())], \
            lyr.GetGeomType()
    finally:
        lyr = None
        ds = None


try:
    print("made twice, the same")
    one = os.path.join(root, "one")
    two = os.path.join(root, "two")
    got1 = ME.make_example(one)
    got2 = ME.make_example(two)
    check("the six files are written",
          sorted(os.listdir(one)) == sorted(ME.FILES), sorted(os.listdir(one)))
    for name in ME.FILES:
        check("%s: the same bytes both times" % name,
              raw(got1[name]) == raw(got2[name]))
    check("made again over the same folder, still the same",
          all(raw(ME.make_example(one)[n]) == raw(got2[n])
              for n in ME.FILES))
    check("nothing but the six files is left in the folder",
          sorted(os.listdir(one)) == sorted(ME.FILES))
    size = sum(os.path.getsize(os.path.join(one, n)) for n in ME.FILES)
    check("the folder is under 3 MB: %d bytes" % size, size < 3 * 1024 * 1024,
          size)
    three = os.path.join(root, "from", "the", "command", "line")
    code = ME.main(["make_example.py", three])
    check("a folder given on the command line is made and filled",
          code == 0 and sorted(os.listdir(three)) == sorted(ME.FILES))

    print()
    print("the scene")
    rgb, gt, wkt, n = read_all(got1["scene_rgb.tif"])
    srs = osr.SpatialReference()
    srs.ImportFromWkt(wkt)
    check("three bands of Byte, 600 x 400 pixels",
          n == 3 and rgb.dtype == np.uint8 and rgb.shape == (3, 400, 600),
          (n, rgb.dtype, rgb.shape))
    check("half a metre a pixel, north up, from (500000, 4200200)",
          gt == (500000.0, 0.5, 0.0, 4200200.0, 0.0, -0.5), gt)
    check("in UTM 33 N, EPSG:32633", srs.GetAuthorityCode(None) == "32633",
          srs.GetAuthorityCode(None))
    check("not flat: every band has a spread of values",
          all(rgb[b].std() > 8 for b in range(3)),
          [float(rgb[b].std()) for b in range(3)])
    check("and neither dark nor washed out", 40 < rgb.mean() < 215,
          float(rgb.mean()))

    print()
    print("the model's map")
    mp, gt2, wkt2, n2 = read_all(got1["model_map.tif"])
    cls, prob = mp[0], mp[1]
    check("two bands of Byte on the grid of the scene",
          n2 == 2 and mp.dtype == np.uint8 and mp.shape == (2, 400, 600)
          and gt2 == gt and wkt2 == wkt, (n2, gt2))
    check("band 1: the codes 1 to 4, all four present, nothing else",
          sorted(int(v) for v in np.unique(cls)) == [1, 2, 3, 4],
          np.unique(cls))
    check("band 2: never 0, and a real spread",
          int(prob.min()) > 0 and prob.std() > 10, (prob.min(), prob.std()))
    truth = ME.scene_truth()
    wrong = cls != truth
    check("the map is wrong somewhere, between 2 and 12 % of the pixels",
          0.02 < wrong.mean() < 0.12, float(wrong.mean()))
    check("and it is less sure where it is wrong: %.2f against %.2f"
          % (prob[wrong].mean() / 255.0, prob[~wrong].mean() / 255.0),
          prob[wrong].mean() < prob[~wrong].mean() - 40,
          (float(prob[wrong].mean()), float(prob[~wrong].mean())))
    # the share of right/wrong pairs ranked the right way: an AUC of 1 - p
    # for the wrong pixels, estimated on a sample
    rng = np.random.default_rng(3)
    w = prob[wrong]
    r = prob[~wrong]
    a = rng.choice(w, 20000)
    b = rng.choice(r, 20000)
    auc = float((a < b).mean() + 0.5 * (a == b).mean())
    check("1 - p separates the wrong pixels from the right ones: AUC %.2f"
          % auc, 0.8 < auc < 0.97, auc)
    names = None
    ds = gdal.Open(got1["model_map.tif"])
    try:
        band1 = ds.GetRasterBand(1)
        table = band1.GetColorTable()
        names = band1.GetRasterCategoryNames()
        described = [ds.GetRasterBand(i).GetDescription() for i in (1, 2)]
        nodata = [ds.GetRasterBand(i).GetNoDataValue() for i in (1, 2)]
        colours = {}
        if table is not None:
            for c in ME.CLASSES:
                r_, g_, b_, a_ = table.GetColorEntry(c["code"])
                colours[c["code"]] = "#%02x%02x%02x" % (r_, g_, b_)
    finally:
        band1 = ds = None
    check("band 1 has a colour table: the four colours of the legend",
          colours == {c["code"]: c["colour"] for c in ME.CLASSES}, colours)
    check("and the category names",
          names is not None and list(names[1:5]) ==
          [c["name"] for c in ME.CLASSES], names)
    check("the bands are named 'class' and 'probability x255'",
          described == ["class", "probability x255"], described)
    check("nodata 0 on both", nodata == [0.0, 0.0], nodata)
    check("the colour table is in the .aux.xml beside the TIFF, which is "
          "what GDAL does for a file of two bands",
          os.path.isfile(got1["model_map.tif.aux.xml"]))
    qml = ET.parse(got1["model_map.qml"]).getroot()
    entries = [(e.get("value"), e.get("color"), e.get("label"))
               for e in qml.iter("paletteEntry")]
    check("model_map.qml is a paletted style with the four classes",
          qml.find("pipe/rasterrenderer").get("type") == "paletted"
          and qml.find("pipe/rasterrenderer").get("band") == "1"
          and entries == [(str(c["code"]), c["colour"], c["name"])
                          for c in ME.CLASSES], entries)

    print()
    print("the sample design")
    pts, auth, fields, geom = points(got1["sample_design.gpkg"])
    check("twelve points in EPSG:32633", len(pts) == 12 and auth == "32633"
          and geom == ogr.wkbPoint, (len(pts), auth, geom))
    check("with the five columns of a design", fields == [
        "sample_id", "stratum", "incl_prob", "weight", "design"], fields)
    check("sample_id 1 to 12", [p["sample_id"] for p in pts]
          == list(range(1, 13)))
    check("three points in each of the four strata",
          sorted(p["stratum"] for p in pts) == [1, 1, 1, 2, 2, 2, 3, 3, 3,
                                                4, 4, 4])
    counts = np.bincount(cls.ravel(), minlength=5)
    check("the inclusion probability is 3 / N of the stratum, N the pixels "
          "of the map in it", all(
              abs(p["incl_prob"] - 3.0 / counts[p["stratum"]]) < 1e-9
              for p in pts), [(p["stratum"], p["incl_prob"]) for p in pts][:3])
    check("the weight is its inverse", all(
        abs(p["weight"] * p["incl_prob"] - 1.0) < 1e-8 for p in pts))
    check("every point stands on a pixel of its own stratum", all(
        cls[int((ME.ORIGIN[1] - p["y"]) / ME.PIXEL),
            int((p["x"] - ME.ORIGIN[0]) / ME.PIXEL)] == p["stratum"]
        for p in pts))
    check("the design says what it is",
          all(p["design"] == "stratified random, n=12" for p in pts),
          pts[0]["design"])
    half = ME.FRAME_PX // 2
    boxes = []
    for p in pts:
        c = int((p["x"] - ME.ORIGIN[0]) / ME.PIXEL)
        r = int((ME.ORIGIN[1] - p["y"]) / ME.PIXEL)
        boxes.append((c - half, r - half, c + half, r + half))
    check("a frame of %d px round each stays inside the scene"
          % ME.FRAME_PX, all(b[0] >= 0 and b[1] >= 0 and b[2] <= 600
                             and b[3] <= 400 for b in boxes), boxes)
    overlaps = [(i, j) for i in range(12) for j in range(i + 1, 12)
                if min(boxes[i][2], boxes[j][2]) > max(boxes[i][0],
                                                       boxes[j][0])
                and min(boxes[i][3], boxes[j][3]) > max(boxes[i][1],
                                                        boxes[j][1])]
    check("and no two frames overlap", not overlaps, overlaps)
    first_two = [truth[b[1]:b[3], b[0]:b[2]] for b in boxes[:2]]
    check("the first two frames, the ones the tutorial draws, each hold at "
          "least two classes of the scene, each over 8 % of the frame",
          all(len([v for v in np.bincount(w_.ravel(), minlength=5)[1:]
                   if v >= 0.08 * w_.size]) >= 2 for w_ in first_two))

    print()
    print("the legend")
    with io.open(got1["classes.csv"], encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    check("classes.csv: code, name, colour, four rows",
          list(rows[0]) == ["code", "name", "colour"] and len(rows) == 4,
          rows[:1])
    check("the codes, names and colours of the map",
          [(int(r["code"]), r["name"], r["colour"]) for r in rows] ==
          [(c["code"], c["name"], c["colour"]) for c in ME.CLASSES])
    check("the colours are written as #rrggbb, the way the Classes window "
          "takes them", all(re.match(r"^#[0-9a-f]{6}$", r["colour"])
                            for r in rows))

    print()
    print("what is committed is what the generator makes")
    here = os.path.join(ROOT, "examples", "rasterlabel_example")
    if not os.path.isdir(here):
        print("  (examples/rasterlabel_example is not beside the suites, so "
              "only the generator was looked at)")
    else:
        check("the same six files", sorted(os.listdir(here)) ==
              sorted(ME.FILES), sorted(os.listdir(here)))
        for name in ("scene_rgb.tif", "model_map.tif"):
            a_, ga, wa, _ = read_all(os.path.join(here, name))
            b_, gb, wb, _ = read_all(got1[name])
            same = float((a_ == b_).mean())
            check("%s: the same grid and the same pixels (%.4f)"
                  % (name, same), ga == gb and wa == wb and a_.shape == b_.shape
                  and same > 0.999, (ga, gb, a_.shape, b_.shape, same))
        check("sample_design.gpkg: the same twelve points",
              [(p["sample_id"], p["stratum"], round(p["x"], 3),
                round(p["y"], 3), p["incl_prob"], p["weight"])
               for p in points(os.path.join(here, "sample_design.gpkg"))[0]]
              == [(p["sample_id"], p["stratum"], round(p["x"], 3),
                   round(p["y"], 3), p["incl_prob"], p["weight"])
                  for p in pts])
        for name in ("classes.csv", "model_map.qml"):
            check("%s: the same text" % name,
                  raw(os.path.join(here, name)).replace(b"\r\n", b"\n")
                  == raw(got1[name]))
        committed = sum(os.path.getsize(os.path.join(here, n))
                        for n in ME.FILES)
        check("the committed folder is under 3 MB: %d bytes" % committed,
              committed < 3 * 1024 * 1024)
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
