"""The Cutouts module after the clean up: run where it can be run, read
where it cannot.

What matters: a cutout comes out whole or it does not come out at all, never
half of one; every layer gets the format it was asked for and a class map
never ends up in JPEG; and the numbers the module writes describe what is
really on the disk.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast
import os
import shutil
import sys
import tempfile

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()

SRC = os.environ.get("RL_SRC", _BUILT)
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def take(name, inside=None):
    for node in tree.body:
        if inside is None and isinstance(node, (ast.FunctionDef, ast.ClassDef)) \
                and node.name == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    t = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s not found" % name)


NAME = "RasterLabel"
GEOTIFF_TYPE = "image/tiff; application=geotiff"
g = {"gdal": gdal, "ogr": ogr, "osr": osr, "np": np, "os": os,
     "IOError": IOError, "NAME": NAME, "GEOTIFF_TYPE": GEOTIFF_TYPE,
     "log": lambda *a, **k: None}
exec(take("WHOLE_FORMATS").replace("WHOLE_FORMATS", "WHOLE_FORMATS") if False
     else "", g)
# the table of formats, taken out of the file
for line in source.splitlines():
    if line.startswith("WHOLE_FORMATS = ["):
        start = source.index("WHOLE_FORMATS = [")
        end = source.index("]", start) + 1
        exec(source[start:end], g)
        break
exec(take("shape_of"), g)
exec(take("long_path"), g)
exec(take("landed"), g)
exec(take("write_tif"), g)
exec(take("write_png"), g)
exec(take("put_raster"), g)
shape_of, put_raster = g["shape_of"], g["put_raster"]

print("the format each layer gets")
for driver, role, expected in (
        ("GTiff", "image", ("GTiff", ".tif")),
        ("PNG", "image", ("PNG", ".png")),
        ("JPEG", "image", ("JPEG", ".jpg")),
        ("GTiff", "classes", ("GTiff", ".tif")),
        ("PNG", "classes", ("PNG", ".png")),
        ("JPEG", "classes", ("GTiff", ".tif")),
        (None, "image", ("GTiff", ".tif"))):
    d, e, kind = shape_of(driver, role)
    check("%-6s as %-8s -> %s%s" % (driver, role, expected[0], expected[1]),
          (d, e) == expected, (d, e))
check("the type it declares follows the extension",
      shape_of("PNG", "image")[2] == "image/png"
      and shape_of("JPEG", "image")[2] == "image/jpeg"
      and shape_of("GTiff", "image")[2] == GEOTIFF_TYPE)

print()
print("the files really do come out, one per format")
tmp = tempfile.mkdtemp(prefix="cut_")
W, H = 64, 48
gt = (400000.0, 0.05, 0.0, 4100000.0, 0.0, -0.05)
srs = osr.SpatialReference(); srs.ImportFromEPSG(32633)
WKT = srs.ExportToWkt()
rgb = (np.random.default_rng(3).integers(0, 255, (3, H, W))).astype(np.uint8)
codes = np.zeros((1, H, W), np.uint8)
codes[0, 10:30, 10:40] = 3

for driver, ext in (("GTiff", ".tif"), ("PNG", ".png"), ("JPEG", ".jpg")):
    path = os.path.join(tmp, "img_" + driver + ext)
    put_raster(driver, path, rgb, gt, WKT)
    ds = gdal.Open(path)
    check("%s: written, %d x %d, %d bands"
          % (driver, ds.RasterXSize, ds.RasterYSize, ds.RasterCount),
          (ds.RasterXSize, ds.RasterYSize, ds.RasterCount) == (W, H, 3),
          (ds.RasterXSize, ds.RasterYSize, ds.RasterCount))
    if driver == "GTiff":
        check("and only the GeoTIFF carries the coordinates",
              ds.GetGeoTransform()[0] == gt[0] and bool(ds.GetProjection()))
    else:
        check("%s does not pretend to be a map" % driver,
              not ds.GetProjection(), ds.GetProjection()[:30])
    ds = None

path = os.path.join(tmp, "classes.tif")
put_raster("GTiff", path, codes, gt, WKT)
read_back = gdal.Open(path).ReadAsArray()
check("the class codes come back identical",
      np.array_equal(read_back, codes[0]), read_back.dtype)

print()
print("a write that cannot work raises, and leaves nothing behind")
bad = os.path.join(tmp, "not_there", "x.tif")
try:
    put_raster("GTiff", bad, rgb, gt, WKT)
    blew_up = False
except Exception:
    blew_up = True
check("it raises", blew_up)
check("and it leaves no file behind", not os.path.exists(bad))
try:
    put_raster("PNG", os.path.join(tmp, "not_there", "y.png"), rgb, gt, WKT)
    blew_up2 = False
except Exception:
    blew_up2 = True
check("the same for the PNG", blew_up2)

print()
print("the manifest and the sampler read the disk")
Section = "CutoutsSection"
shapes = take("shapes_on_disk", Section)
check("shapes_on_disk reads cutouts.csv", "csv.DictReader" in shapes)
check("and it counts the shapes, the most common one first",
      "key=lambda kv: -len(kv[1])" in shapes)
check("by cutouts, not by the rows of the layers of a cutout",
      "set()).add(" in shapes)
samp = take("write_sampler", Section)
check("the sampler is no longer handed a single cutout",
      "def write_sampler(self)" in samp)
check("it describes the whole folder", "shapes_on_disk()" in samp)
check("and it warns when there is more than one shape",
      "pieces of more than one " in samp and "shapes_found" in samp)

print()
print("a cutout comes out whole or it does not come out")
exp = take("export", Section)
check("cutting the layers happens inside a try", "self.cut_layers(" in exp)
check("and whatever had already landed is taken away again",
      "os.remove(long_path(gone))" in exp and "for path in files:" in exp
      and '(path, path + ".aux.xml")' in exp)
check("and it says so, instead of leaving it in the log",
      "QMessageBox.critical" in exp)
cut = take("cut_layers", Section)
check("cut_layers catches nothing: it raises and that is all",
      "except" not in cut)

batch = take("export_all_tiles", Section)
check("one crooked frame does not kill the whole batch",
      "except Exception as err" in batch)
check("and at the end it says how many went wrong", "broken" in batch)

print()
print("what no longer belongs here is gone")
for dead in ("label_array", "point_rows", "box_lines", "write_class_order",
             "label_overview"):
    check("%s does not exist any more" % dead,
          ("def %s(" % dead) not in source)
for checkbox in ("self.labels", "self.points_out", "self.boxes_out",
                 "self.only_painted"):
    check("the %s checkbox does not exist any more" % checkbox,
          ("%s = QCheckBox" % checkbox) not in source)
stac = take("write_stac", Section)
check("the STAC no longer writes a label item", "label:tasks" not in stac)
check("nor does it declare that extension", "LABEL_EXT" not in stac)
check("and it records the roles it really did cut",
      "rasterlabel:roles" in stac)

print()
print("the numbers written down are the true ones")
# measured by side_of(), which never writes nan: an ellipsoid on a layer with
# no system measured its pixels as degrees, and cutouts.csv said nan
side_of = take("side_of", Section)
check("the side is measured on the window, not read off the spin box",
      "self.side_of(" in cut and "measureLine" in side_of
      and 'self.side.value()' not in cut + side_of)
check("and the manifest has a column for the format",
      '"format", "side_m"' in source)

print()
print("nothing is written over anything")
res = take("result", "CutoutSetup")
check("the names are made unique AFTER tidy_tag()",
      res.index("tidy_tag(tag.text()") < res.index("while stem.lower() in taken"))
# And compared without case, because a tag becomes a file name: on Windows "RGB"
# and "rgb" are one file, so two rows differing only in case passed the loop and
# the second wrote over the first in the middle of a dataset.
check("and compared without case, because these become file names",
      "while stem.lower() in taken" in res and "taken.add(stem.lower())" in res)
check("a class map cannot come out as JPEG even from here",
      'driver == "JPEG"' in res)

print()
print("paint_whole does not carry off a file that was there before")
pw = take("paint_whole")
check("it writes down which files did not exist", "ours = {path" in pw)
check("and it leaves the others alone", "if path not in ours:" in pw)

print()
print("the writes that used to be silent now speak")
lg = take("log")
check("the log goes to the QGIS panel", "QgsMessageLog.logMessage" in lg)
check("and the serious ones reach the message bar too",
      "loud" in lg and "pushMessage" in lg)

shutil.rmtree(tmp, ignore_errors=True)
print()
print("where the files go")
# The folder used to be kept in the campaign manifest, which tied the module
# to a campaign it had no other use for, and Cutouts could not be opened
# until one was. QGIS remembers it now, on this machine; a campaign is read
# once, for the folder an earlier build kept there, and never written.
rem = take("remembered_folder", Section)
check("the folder is what QGIS remembers", 'self.setting("folder"' in rem)
check("a campaign's old folder is read only when QGIS has none, and only "
      "when a campaign is open",
      '"cutouts_folder"' in rem and "self.campaign is not None" in rem
      and rem.index('self.setting("folder"') < rem.index('"cutouts_folder"'))
check("and if neither has one, the default", "default_folder()" in rem)
keep = take("remember_folder", Section)
check("the choice is written into QGIS", 'self.keep_setting("folder"' in keep)
check("and not into any manifest", "save()" not in keep)
check("even when it is the same as the one we started from",
      "or self.default_folder()" in keep)
df = take("default_folder", Section)
check("the default is beside the QGIS project, not beside a manifest",
      "homePath()" in df and "campaign" not in df.split('"""')[-1])

print()
print("Cutouts saves no campaign")
_cs = [n for n in tree.body if isinstance(n, ast.ClassDef)
       and n.name == Section]
_body = "".join(lines[_cs[0].lineno - 1:_cs[0].end_lineno]) if _cs else ""
check("no campaign.save() anywhere in CutoutsSection",
      _body and "campaign.save()" not in _body,
      [l.strip() for l in _body.splitlines() if "campaign.save()" in l])
check("nothing is appended to the campaign's list of cutouts",
      'data.setdefault("cutouts"' not in _body
      and 'data["cutouts"]' not in _body)
check("the sizes of a side live in shapes.json, in the folder",
      '"shapes.json"' in _body
      and 'setdefault("cutout_shape"' not in _body)
check("which is written through a temporary file",
      "write_atomic(self.shapes_path" in take("write_shapes", Section)
      and "os.replace(spare, long_path(path))" in take("write_atomic")
      and "os.fsync(" in take("write_atomic"))
init = take("__init__", Section)
check("it opens with no campaign: the geometry is made only with one",
      "self.geometry = None" in init and "if self.campaign is not None:" in init)
ch = take("folder_changed", Section)
check("changing folder counts the cutouts again", "count_existing()" in ch)
check("and undo no longer tries to reach into the old one",
      "self.written = []" in ch)
usable = take("folder_is_usable", Section)
check("before cutting, it really does try to write", "probe" in usable)
check("and if it cannot, it says so instead of finding out halfway",
      "QMessageBox.critical" in usable)
exp2 = take("export", Section)
check("the single cutout goes through that check",
      "self.folder_is_usable()" in exp2)
check("and so does the batch", "self.folder_is_usable()" in batch)
st = take("show_state", Section)
check("the panel says where they are going", "into %s" in st)
check("and the whole path is in the tooltip", "setToolTip(where)" in st)


def chosen_folder(remembered, manifest, home):
    """remembered_folder, the part of it that decides."""
    want = (remembered or "").strip()
    if not want and manifest is not None:
        want = (manifest.get("cutouts_folder") or "").strip()
    return want or (home + "/cutouts")


for remembered, manifest, expected in (
        ("", None, "/proj/cutouts"),
        ("   ", None, "/proj/cutouts"),
        ("", {}, "/proj/cutouts"),
        ("", {"cutouts_folder": "  "}, "/proj/cutouts"),
        ("", {"cutouts_folder": "D:/dataset"}, "D:/dataset"),
        ("E:/mine", {"cutouts_folder": "D:/dataset"}, "E:/mine"),
        ("E:/mine", None, "E:/mine")):
    got = chosen_folder(remembered, manifest, "/proj")
    check("%-10r %-34s -> %s" % (remembered, str(manifest), expected),
          got == expected, got)

print()
print("FAILED: %d" % len(fails) if fails else "all of them pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
