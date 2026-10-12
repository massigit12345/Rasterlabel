"""Make the example dataset of RasterLabel: a small synthetic scene.

    python tools/make_example.py                  # examples/rasterlabel_example/
    python tools/make_example.py some/folder      # or another folder

It needs numpy and the GDAL Python bindings, nothing else (not QGIS), and it
draws every number from a fixed seed, so the same call gives the same files,
byte for byte, on the same machine. Nothing here is real data: the scene is
made up, 600 x 400 pixels of half a metre in UTM 33 N (EPSG:32633), with a
winding channel, three ponds, round shrubs, a patch of low vegetation, a
track and a few roofs on bare ground.

The folder holds:

  scene_rgb.tif      a 3-band Byte picture of the scene, for New campaign
  model_map.tif      the map of an imaginary classifier on the same grid:
                     band 1 the class (1 to 4), band 2 "probability x255",
                     the probability of that class, low where the map is
                     wrong (not everywhere: a probability is not an oracle).
                     Its colour table and category names sit in
                     model_map.tif.aux.xml (GDAL keeps them there for a
                     file of several bands) and its QGIS style in
                     model_map.qml
  sample_design.gpkg twelve sample points as AcATaMa writes a stratified
                     design: sample_id, stratum, incl_prob, weight, design
  classes.csv        the four classes: code, name, colour

The truth the picture was drawn from is not written: the tutorial annotates
the picture the way a person would. scene_truth() returns it for the tests.
"""
import csv
import math
import os
import sys

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()
osr.UseExceptions()

SEED = 20261001
EPSG = 32633
WIDTH, HEIGHT = 600, 400
PIXEL = 0.5                      # metres
ORIGIN = (500000.0, 4200200.0)   # upper left corner, UTM 33 N
FRAME_PX = 60                    # a frame of 30 m, the side the tutorial sets
N_PER_STRATUM = 3

CLASSES = [
    {"code": 1, "name": "bare ground", "colour": "#c9a66b"},
    {"code": 2, "name": "vegetation", "colour": "#2e8b3d"},
    {"code": 3, "name": "water", "colour": "#2a78d6"},
    {"code": 4, "name": "built-up", "colour": "#8c8c94"},
]
BASE_RGB = {1: (178, 152, 118), 2: (62, 112, 50), 3: (38, 86, 132),
            4: (156, 150, 150)}
TEXTURE = {1: 14.0, 2: 20.0, 3: 6.0, 4: 8.0}

FILES = ("scene_rgb.tif", "model_map.tif", "model_map.tif.aux.xml",
         "model_map.qml", "sample_design.gpkg", "classes.csv")


# ----------------------------------------------------------------- the scene
# Objects, in pixel coordinates (column, row from the top), painted in this
# order: later ones cover earlier ones. Round things, long things, boxes.
def channel_centre(x):
    """The winding channel: its row at column x, and its half width."""
    row = 188.0 + 46.0 * np.sin(2.0 * np.pi * x / 400.0 + 0.7) \
        + 12.0 * np.sin(2.0 * np.pi * x / 130.0 + 2.0)
    half = 5.5 + 2.5 * np.sin(2.0 * np.pi * x / 170.0 + 1.1)
    return row, half


OBJECTS = [
    # kind, class, parameters
    ("blob", 2, [(70, 300, 46), (110, 322, 38), (150, 306, 34),
                 (92, 276, 28), (60, 340, 30)]),            # low vegetation
    ("channel", 3, None),                                    # the channel
    ("circle", 3, (448, 112, 24)),                           # a round pond
    ("circle", 3, (212, 84, 15)),                            # a small pond
    ("ellipse", 3, (338, 316, 26, 10, 0.5)),                 # an oblong pond
    ("circle", 2, (254, 262, 11)), ("circle", 2, (296, 232, 9)),
    ("circle", 2, (356, 252, 13)), ("circle", 2, (520, 298, 12)),
    ("circle", 2, (540, 52, 10)), ("circle", 2, (158, 140, 9)),
    ("circle", 2, (88, 66, 12)), ("circle", 2, (396, 34, 8)),
    ("circle", 2, (476, 336, 10)), ("circle", 2, (592 - 20, 218, 9)),
    ("strip", 4, ((30, 372), (572, 330), 4.0)),              # a track
    ("rect", 4, (404, 288, 438, 312)), ("rect", 4, (446, 292, 470, 316)),
    ("rect", 4, (150, 336, 190, 352)), ("rect", 4, (284, 340, 310, 364)),
    ("rect", 4, (108, 20, 140, 44)),
]


def scene_truth():
    """The classes the picture was drawn from, rows x columns, uint8."""
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH].astype("float64")
    xx += 0.5
    yy += 0.5
    t = np.ones((HEIGHT, WIDTH), np.uint8)
    for kind, cls, par in OBJECTS:
        t[_inside(kind, par, xx, yy)] = cls
    return t


def _inside(kind, par, xx, yy):
    if kind == "blob":
        m = np.zeros(xx.shape, bool)
        for cx, cy, r in par:
            m |= (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
        return m
    if kind == "circle":
        cx, cy, r = par
        return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    if kind == "ellipse":
        cx, cy, a, b, ang = par
        c, s = math.cos(ang), math.sin(ang)
        u = (xx - cx) * c + (yy - cy) * s
        v = -(xx - cx) * s + (yy - cy) * c
        return (u / a) ** 2 + (v / b) ** 2 <= 1.0
    if kind == "rect":
        x0, y0, x1, y1 = par
        return (xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1)
    if kind == "strip":
        (x0, y0), (x1, y1), half = par
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        u = ((xx - x0) * dx + (yy - y0) * dy) / length
        v = (-(xx - x0) * dy + (yy - y0) * dx) / length
        return (u >= 0) & (u <= length) & (np.abs(v) <= half)
    if kind == "channel":
        row, half = channel_centre(xx)
        return np.abs(yy - row) <= half
    raise ValueError(kind)


def outlines():
    """Every object as a polygon of pixel coordinates, [(class, [(col, row),
    ...]), ...], for programs that draw the scene back (tools/tutorial_walk.py)."""
    out = []
    for kind, cls, par in OBJECTS:
        if kind == "blob":
            for cx, cy, r in par:
                out.append((cls, _circle(cx, cy, r, r, 0.0)))
        elif kind == "circle":
            out.append((cls, _circle(par[0], par[1], par[2], par[2], 0.0)))
        elif kind == "ellipse":
            out.append((cls, _circle(*par)))
        elif kind == "rect":
            x0, y0, x1, y1 = par
            out.append((cls, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))
        elif kind == "strip":
            (x0, y0), (x1, y1), half = par
            length = math.hypot(x1 - x0, y1 - y0)
            nx, ny = -(y1 - y0) / length * half, (x1 - x0) / length * half
            out.append((cls, [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny),
                              (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]))
        elif kind == "channel":
            xs = np.linspace(0.0, WIDTH, 121)
            row, half = channel_centre(xs)
            top = [(float(x), float(r - h)) for x, r, h in zip(xs, row, half)]
            low = [(float(x), float(r + h)) for x, r, h in zip(xs, row, half)]
            out.append((cls, top + low[::-1]))
    return out


def _circle(cx, cy, a, b, ang, n=40):
    c, s = math.cos(ang), math.sin(ang)
    pts = []
    for k in range(n):
        t = 2.0 * math.pi * k / n
        u, v = a * math.cos(t), b * math.sin(t)
        pts.append((cx + u * c - v * s, cy + u * s + v * c))
    return pts


# --------------------------------------------------------------------- noise
def smooth(rng, cell):
    """Smooth noise in 0..1: random values on a lattice, interpolated."""
    ny, nx = HEIGHT // cell + 2, WIDTH // cell + 2
    lat = rng.random((ny, nx))
    ys = np.arange(HEIGHT) / float(cell)
    xs = np.arange(WIDTH) / float(cell)
    y0, x0 = ys.astype(int), xs.astype(int)
    fy, fx = ys - y0, xs - x0
    fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
    a = lat[y0][:, x0]
    b = lat[y0][:, x0 + 1]
    c = lat[y0 + 1][:, x0]
    d = lat[y0 + 1][:, x0 + 1]
    top = a + (b - a) * fx[None, :]
    low = c + (d - c) * fx[None, :]
    return top + (low - top) * fy[:, None]


def blur3(a):
    """A 3 x 3 mean, edges repeated."""
    p = np.pad(a, ((1, 1), (1, 1)) + ((0, 0),) * (a.ndim - 2), mode="edge")
    out = np.zeros(a.shape, "float64")
    for dy in range(3):
        for dx in range(3):
            out += p[dy:dy + a.shape[0], dx:dx + a.shape[1]]
    return out / 9.0


def edges(a):
    """Pixels that differ from a neighbour on the left, right, above or below."""
    e = np.zeros(a.shape, bool)
    e[:, 1:] |= a[:, 1:] != a[:, :-1]
    e[:, :-1] |= a[:, :-1] != a[:, 1:]
    e[1:, :] |= a[1:, :] != a[:-1, :]
    e[:-1, :] |= a[:-1, :] != a[1:, :]
    return e


# --------------------------------------------------------------- the picture
def picture(truth, rng):
    """scene_rgb: the truth in its colours, textured, lit, a little blurred."""
    rgb = np.zeros((HEIGHT, WIDTH, 3), "float64")
    grain = smooth(rng, 6) - 0.5
    patch = smooth(rng, 28) - 0.5
    for cls, base in BASE_RGB.items():
        m = truth == cls
        for b in range(3):
            rgb[..., b][m] = base[b]
    # the built-up pixels vary in tone, roof from roof
    tone = 1.0 + 0.55 * (smooth(rng, 10) - 0.5)
    rgb *= np.where(truth == 4, tone, 1.0)[..., None]
    amp = np.zeros((HEIGHT, WIDTH))
    for cls, a in TEXTURE.items():
        amp[truth == cls] = a
    texture = (grain * 1.4 + patch * 1.1) * amp
    rgb += texture[..., None] * np.array([1.0, 0.95, 0.8])
    rgb += rng.standard_normal((HEIGHT, WIDTH, 1)) * 3.5
    # a pale rim where water meets ground, a dark one under the shrubs
    rim = edges(truth) & (truth != 4)
    rgb[rim] *= np.array([1.06, 1.04, 0.98])
    rgb = blur3(rgb)
    light = 0.94 + 0.12 * (np.add.outer(np.arange(HEIGHT) / HEIGHT,
                                        np.arange(WIDTH) / WIDTH) / 2.0)
    rgb *= light[..., None]
    return np.clip(np.rint(rgb), 0, 255).astype(np.uint8)


# ------------------------------------------------------------ the model's map
def model(truth, rng):
    """(classes, probability): the map of an imaginary classifier, with errors
    put where a classifier of this kind makes them, and a probability that
    is low where it is wrong, with exceptions both ways."""
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH].astype("float64")
    m = truth.copy()
    # the narrow stretches of the channel are missed, left as ground
    for lo, hi in ((110, 185), (385, 440)):
        m[(truth == 3) & (xx >= lo) & (xx < hi) & (yy > 120) & (yy < 260)] = 1
    # the big pond, west half taken for vegetation
    m[(truth == 3) & (np.hypot(xx - 448, yy - 112) <= 24) & (xx < 448)] = 2
    # the oblong pond, all of it, taken for ground
    m[(truth == 3) & (np.hypot(xx - 338, yy - 316) <= 30)] = 1
    # two roofs missed, a stretch of the track missed
    m[(truth == 4) & (xx >= 404) & (xx < 438) & (yy >= 288)] = 1
    m[(truth == 4) & (xx >= 150) & (xx < 190) & (yy >= 336) & (yy < 352)] = 1
    m[(truth == 4) & (xx >= 300) & (xx < 380) & (yy > 335)] = 1
    # dark shrubs taken for water, and a shrub patch lost to the ground
    for cx, cy in ((254, 262), (356, 252), (88, 66)):
        m[(truth == 2) & (np.hypot(xx - cx, yy - cy) <= 14)] = 3
    m[(truth == 2) & (xx >= 40) & (xx < 100) & (yy >= 310)] = 1
    # a bare patch taken for built-up (a quarry floor)
    m[(truth == 1) & (xx >= 505) & (xx < 560) & (yy >= 150) & (yy < 190)] = 4
    # the borders are off by a pixel here and there
    border = edges(truth)
    pick = rng.random((HEIGHT, WIDTH))
    pad = np.pad(truth, 2, mode="edge")
    shifts = [pad[2:-2, 1:-3], pad[2:-2, 3:-1], pad[1:-3, 2:-2],
              pad[3:-1, 2:-2]]
    which = np.minimum((rng.random((HEIGHT, WIDTH)) * 4).astype(int), 3)
    moved = np.choose(which, shifts)
    flip = border & (pick < 0.35)
    m[flip & (m == truth)] = moved[flip & (m == truth)]
    wrong = m != truth
    # the probability of the class the map gives
    low = smooth(rng, 24)
    p = 0.80 + 0.19 * smooth(rng, 18)
    p[low < 0.12] = 0.42 + 0.2 * smooth(rng, 12)[low < 0.12]    # unsure, right
    p[edges(m)] *= 0.78
    q = 0.36 + 0.26 * smooth(rng, 9)
    sure = smooth(rng, 40) > 0.80                               # sure, wrong
    p = np.where(wrong & ~sure, q, p)
    p = np.where(wrong & sure, 0.80 + 0.12 * smooth(rng, 9), p)
    p += rng.standard_normal((HEIGHT, WIDTH)) * 0.03
    p = np.clip(p, 0.05, 0.995)
    return m.astype(np.uint8), np.rint(p * 255.0).astype(np.uint8)


# ------------------------------------------------------------ the sample
def sample_points(classes, truth, rng):
    """Twelve points, three in each class of the map, never so close that two
    frames of FRAME_PX would overlap or leave the scene, each frame holding at
    least two classes of the scene. The first two are the frames richest in
    classes of different strata, the ones the tutorial draws."""
    half = FRAME_PX // 2 + 1
    chosen = []

    def window(c, r):
        return truth[r - FRAME_PX // 2:r + FRAME_PX // 2,
                     c - FRAME_PX // 2:c + FRAME_PX // 2]

    def richness(c, r):
        w = window(c, r)
        shares = np.bincount(w.ravel(), minlength=5)[1:] / float(w.size)
        return int((shares >= 0.08).sum())

    for stratum in (1, 2, 3, 4):
        rows, cols = np.nonzero(classes == stratum)
        keep = (rows >= half) & (rows < HEIGHT - half) \
            & (cols >= half) & (cols < WIDTH - half)
        rows, cols = rows[keep], cols[keep]
        order = np.argsort(rng.random(rows.size))
        got = 0
        for need in (2, 1):
            for k in order:
                if got == N_PER_STRATUM:
                    break
                r, c = int(rows[k]), int(cols[k])
                if richness(c, r) < need:
                    continue
                if any(max(abs(c - c2), abs(r - r2)) < FRAME_PX + 2
                       for c2, r2, _ in chosen):
                    continue
                if any(c2 == c and r2 == r for c2, r2, _ in chosen):
                    continue
                chosen.append((c, r, stratum))
                got += 1
        if got < N_PER_STRATUM:
            raise RuntimeError("no room for %d frames in stratum %d"
                               % (N_PER_STRATUM, stratum))
    rich = sorted(range(len(chosen)),
                  key=lambda i: (-richness(chosen[i][0], chosen[i][1]), i))
    first = [rich[0]]
    for i in rich[1:]:
        if chosen[i][2] != chosen[first[0]][2]:
            first.append(i)
            break
    rest = [i for i in range(len(chosen)) if i not in first]
    return [chosen[i] for i in first + rest]


# -------------------------------------------------------------------- writers
def _srs():
    s = osr.SpatialReference()
    s.ImportFromEPSG(EPSG)
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def _create(path, bands, arrays, descriptions):
    ds = gdal.GetDriverByName("GTiff").Create(
        path, WIDTH, HEIGHT, bands, gdal.GDT_Byte,
        ["COMPRESS=NONE", "TILED=NO", "BIGTIFF=NO", "INTERLEAVE=PIXEL"])
    ds.SetGeoTransform((ORIGIN[0], PIXEL, 0.0, ORIGIN[1], 0.0, -PIXEL))
    ds.SetProjection(_srs().ExportToWkt())
    for b, (a, d) in enumerate(zip(arrays, descriptions), 1):
        band = ds.GetRasterBand(b)
        band.WriteArray(a)
        if d:
            band.SetDescription(d)
    return ds


def write_scene(path, rgb):
    ds = _create(path, 3, [rgb[..., b] for b in range(3)],
                 ["red", "green", "blue"])
    for b, ci in enumerate((gdal.GCI_RedBand, gdal.GCI_GreenBand,
                            gdal.GCI_BlueBand), 1):
        ds.GetRasterBand(b).SetColorInterpretation(ci)
    ds = None


def write_model(path, classes, prob):
    ds = _create(path, 2, [classes, prob], ["class", "probability x255"])
    for b in (1, 2):
        ds.GetRasterBand(b).SetNoDataValue(0)
    ds = None
    # the colour table and the names of band 1: a TIFF of two bands cannot
    # hold a palette, so GDAL keeps them in the .aux.xml, as the program does
    ds = gdal.Open(path)
    ct = gdal.ColorTable()
    ct.SetColorEntry(0, (0, 0, 0, 0))
    names = [""]
    for c in CLASSES:
        h = c["colour"].lstrip("#")
        ct.SetColorEntry(c["code"], (int(h[0:2], 16), int(h[2:4], 16),
                                     int(h[4:6], 16), 255))
        names.append(c["name"])
    band = ds.GetRasterBand(1)
    band.SetColorTable(ct)
    band.SetRasterCategoryNames(names)
    band.SetColorInterpretation(gdal.GCI_PaletteIndex)
    ds.FlushCache()
    ds = None


def write_style(path):
    entries = "\n".join(
        '        <paletteEntry value="%d" color="%s" alpha="255" label="%s"/>'
        % (c["code"], c["colour"], c["name"]) for c in CLASSES)
    text = """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
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
      <colorPalette>
%s
      </colorPalette>
    </rasterrenderer>
    <brightnesscontrast gamma="1" contrast="0" brightness="0"/>
    <huesaturation saturation="0" invertColors="0" grayscaleMode="0" colorizeBlue="128" colorizeGreen="128" colorizeStrength="100" colorizeOn="0" colorizeRed="255"/>
    <rasterresampler maxOversampling="2"/>
    <resamplingStage>resamplingFilter</resamplingStage>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
""" % entries
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_design(path, points, classes):
    """sample_design.gpkg: what AcATaMa writes for a stratified random sample
    drawn on a map: the strata are the classes of the map, the inclusion
    probability of a point n_h / N_h (N_h the pixels of its stratum) and the
    weight its inverse, the pixels one point speaks for."""
    counts = np.bincount(classes.ravel(), minlength=5)
    if os.path.exists(path):
        os.remove(path)
    ds = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    lyr = ds.CreateLayer("samples", _srs(), ogr.wkbPoint,
                         ["GEOMETRY_NAME=geom", "FID=fid"])
    for name, kind in (("sample_id", ogr.OFTInteger),
                       ("stratum", ogr.OFTInteger),
                       ("incl_prob", ogr.OFTReal), ("weight", ogr.OFTReal),
                       ("design", ogr.OFTString)):
        lyr.CreateField(ogr.FieldDefn(name, kind))
    ds.StartTransaction()
    for k, (c, r, stratum) in enumerate(points, 1):
        f = ogr.Feature(lyr.GetLayerDefn())
        f.SetField("sample_id", k)
        f.SetField("stratum", int(stratum))
        prob = float("%.10g" % (N_PER_STRATUM / float(counts[stratum])))
        f.SetField("incl_prob", prob)
        f.SetField("weight", float("%.10g" % (1.0 / prob)))
        f.SetField("design", "stratified random, n=%d" % len(points))
        x = ORIGIN[0] + (c + 0.5) * PIXEL
        y = ORIGIN[1] - (r + 0.5) * PIXEL
        f.SetGeometry(ogr.CreateGeometryFromWkt("POINT (%r %r)" % (x, y)))
        lyr.CreateFeature(f)
    ds.CommitTransaction()
    ds = None
    # GDAL stamps gpkg_contents with the time of the run: a fixed one keeps
    # the file the same from one run to the next
    import sqlite3
    con = sqlite3.connect(path)
    try:
        con.execute("UPDATE gpkg_contents SET last_change = "
                    "'2026-10-01T00:00:00.000Z'")
        con.commit()
        # The header of an SQLite file counts the writes made to it, and GDAL
        # now and then makes one more (about one run in twelve on Linux), so
        # two runs could differ in those two counters alone. A copy made by
        # VACUUM INTO is written in one go, the same every time.
        packed = path + ".packed"
        if os.path.exists(packed):
            os.remove(packed)
        con.execute("VACUUM INTO ?", (packed,))
    finally:
        con.close()
    os.replace(packed, path)


def write_classes(path):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["code", "name", "colour"])
        for c in CLASSES:
            w.writerow([c["code"], c["name"], c["colour"]])


def make_example(folder):
    """Write the example into folder (made if need be); returns {name: path}."""
    os.makedirs(folder, exist_ok=True)
    rng = np.random.default_rng(SEED)
    truth = scene_truth()
    rgb = picture(truth, rng)
    classes, prob = model(truth, rng)
    points = sample_points(classes, truth, rng)
    out = {name: os.path.join(folder, name) for name in FILES}
    for name in ("model_map.tif.aux.xml",):
        if os.path.exists(out[name]):
            os.remove(out[name])
    write_scene(out["scene_rgb.tif"], rgb)
    write_model(out["model_map.tif"], classes, prob)
    write_style(out["model_map.qml"])
    write_design(out["sample_design.gpkg"], points, classes)
    write_classes(out["classes.csv"])
    return out


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    folder = argv[1] if len(argv) > 1 else os.path.join(
        os.path.dirname(here), "examples", "rasterlabel_example")
    out = make_example(folder)
    total = 0
    for name in FILES:
        size = os.path.getsize(out[name])
        total += size
        print("  %-24s %9d bytes" % (name, size))
    print("  %-24s %9d bytes, in %s" % ("together", total, folder))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
