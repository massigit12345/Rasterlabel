"""The dataset card of a campaign measures ground, not the middle pixel.

A pixel of a map in degrees is not the same ground at 60 north and at the
equator. The card counted the pixels of each class right and then wrote their
area as the pixels times the pixel at the middle of the map, so 5000 pixels
of class 1 near 60 north were given the ground of 5000 pixels at 30 north,
nearly twice as much. Correct and Model vs corrected already add up the
ground row by row on the ellipsoid; the area of each class in the card (every
reading, the readings together, each consensus) does now too. On a map in a
metric system the pixel is one ground everywhere and the numbers are the
pixels times its area, as they were.

The area to compare with is the ellipsoid's own, worked out here from the
formula for a cell of longitude and latitude, not from the program.

Needs QGIS itself (tests/run.py, NEEDS_QGIS): the ellipsoid is QGIS's.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import math
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import qgiskit as K  # noqa: E402
import impact as F  # noqa: E402
import numpy as np  # noqa: E402

g, check = K.g, K.check
root = tempfile.mkdtemp(prefix="rl_card_ground_")
print("QGIS %s" % K.QGIS_VERSION)

# the WGS 84 ellipsoid, for an area that does not come from the program
A_AXIS = 6378137.0
FLAT = 1 / 298.257223563
B_AXIS = A_AXIS * (1 - FLAT)
E2 = FLAT * (2 - FLAT)
E1 = math.sqrt(E2)


def _band(phi):
    s = math.sin(phi)
    return B_AXIS * B_AXIS * (s / (2 * (1 - E2 * s * s))
                              + math.log((1 + E1 * s) / (1 - E1 * s))
                              / (4 * E1))


def cell_m2(lon0, lon1, lat0, lat1):
    """The area of a cell of longitude and latitude on the ellipsoid."""
    return abs(math.radians(lon1 - lon0)
               * (_band(math.radians(lat1)) - _band(math.radians(lat0))))


def manifest_of(folder):
    with open(os.path.join(folder, "campaign.json"), encoding="utf-8") as fh:
        return json.load(fh)


def campaign(name, grid, marks, pixel_m=None):
    folder = os.path.join(root, name)
    bbox = F.px_box(grid, 0, 0, grid["size"][0], grid["size"][1])
    package = F.make_campaign(folder, grid, [("f1", bbox, False)], marks,
                              name=name, campaign_id=(name * 12)[:12])
    F._tif(os.path.join(folder, "ortho.tif"), grid,
           np.zeros((grid["size"][1], grid["size"][0]), np.uint8))
    data = manifest_of(folder)
    if pixel_m is not None:
        data["grid"]["pixel_m"] = list(pixel_m)
        with open(os.path.join(folder, "campaign.json"), "w",
                  encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2)
    return folder, package, data


ANNA, BRUNO = ("ANNA", 1), ("BRUNO", 1)

# ------------------------------------------------------- a map in degrees
print("a campaign in degrees")
NX, NY, STEP = 100, 600, 0.1
GEO = {"epsg": 4326, "origin": (10.0, 60.0), "pixel": STEP, "size": (NX, NY)}
# the pixel the manifest holds is the one at the middle row, in metres
mid = cell_m2(10.0, 10.0 + STEP, 60.0 - (NY // 2 + 1) * STEP,
              60.0 - (NY // 2) * STEP)
side = math.sqrt(mid)
MARKS = [("polygons", ANNA, 1, F.px_box(GEO, 0, 0, NX, 50)),
         ("polygons", ANNA, 2, F.px_box(GEO, 0, 550, NX, 600)),
         ("polygons", BRUNO, 1, F.px_box(GEO, 0, 0, NX, 50))]
folder, package, data = campaign("geo", GEO, MARKS, (side, side))
card = g["card_gather_campaign"](data, folder, package)
products = {p["tag"]: p for p in card["products"]}


def ground(rows, columns=NX):
    return sum(cell_m2(10.0, 10.0 + columns * STEP, 60.0 - (r + 1) * STEP,
                       60.0 - r * STEP) for r in rows)


want1, want2 = ground(range(0, 50)), ground(range(550, 600))
mid_px = card["grid"]["pixel_area_m2"]
anna = products["ANNA_p1"]
check("the pixels are counted as ever: 5000 of class 1, 5000 of class 2",
      anna["counts"] == {1: 5000, 2: 5000}, anna["counts"])
check("class 1 near 60 north is its ground, %.0f m2, not the pixel at the "
      "middle of the map times 5000 (%.0f)" % (want1, 5000 * mid_px),
      abs(anna["m2"][1] / want1 - 1) < 0.005, (anna["m2"], want1))
check("class 2 at the equator is its ground too, %.0f m2" % want2,
      abs(anna["m2"][2] / want2 - 1) < 0.005, (anna["m2"], want2))
check("so the two are not in the ratio of their pixels",
      abs(anna["m2"][1] / anna["m2"][2] - 1) > 0.3, anna["m2"])
check("the readings together and the consensus are measured the same way",
      abs(products["all"]["m2"][1] / want1 - 1) < 0.005
      and abs(products["consensus_p1"]["m2"][1] / want1 - 1) < 0.005,
      {t: p["m2"] for t, p in products.items()})
check("the card says how the m2 were measured",
      any("ground of each row" in n for n in card["limits"])
      and not any(n.startswith("the campaign is in degrees")
                  for n in card["limits"]), card["limits"])

# ---------------------------------------------------- a map in a metric CRS
print()
print("a campaign in a metric system is what it was")
UTM = F.GRID_CARD
utm_marks = [("polygons", ANNA, 1, F.px_box(UTM, 0, 0, 6, 10)),
             ("polygons", ANNA, 2, F.px_box(UTM, 6, 0, 10, 10))]
folder_u, package_u, data_u = campaign("utm", UTM, utm_marks)
card_u = g["card_gather_campaign"](data_u, folder_u, package_u)
anna_u = {p["tag"]: p for p in card_u["products"]}["ANNA_p1"]
area = card_u["grid"]["pixel_area_m2"]
check("the m2 are the pixels times the pixel area, to the last digit",
      anna_u["m2"] == {k: round(n * area, 6)
                       for k, n in anna_u["counts"].items()}
      and anna_u["counts"] == {1: 60, 2: 40}, (anna_u["m2"], area))
check("with no note about rows", not any("ground of each row" in n
                                         for n in card_u["limits"]),
      card_u["limits"])

shutil.rmtree(root, ignore_errors=True)
sys.exit(K.finish())
