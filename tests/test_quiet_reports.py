"""What the program says about itself has to be true, and said once.

Four small things, each of which told the user something that was not so or
said it in a way that got in the way:

  * A Paint Whole Raster to PNG or JPEG that failed part way warned, loudly,
    that a half-written file had been left behind and could not be removed.
    There was no file. PNG and JPEG are painted into a scratch file and
    copied out at the end, so a failure before the end leaves nothing on
    disk, and the removal that failed was the removal of a file that never
    existed.
  * Every line of the log was printed on the console as well, inside QGIS
    too, where nobody reads it, and a console that could not spell the
    message raised a second error out of the code reporting the first.
  * The build stamp was an MD5, which every security scanner reports as a
    weak hash of high severity, the QGIS plugin site's included, although it
    only names a build.
  * The Check report listed Python, numpy, the system and RasterLabel itself
    twice, in two spellings, and called Windows 11 "Windows 10".

The functions are taken from the shipped file and run with the parts of QGIS
and GDAL they touch replaced, so nothing here needs either.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import hashlib
import os
import shutil
import sys
import tempfile
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.environ.get("RL_ROOT") or os.path.dirname(_HERE)
SRC = os.environ.get("RL_SRC", os.path.join(_ROOT, "dist", "rasterlabel.py"))
source = open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


def take(name):
    for node in tree.body:
        if getattr(node, "name", None) == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("%s not found" % name)


# ==========================================================================
print("a paint that fails part way warns only about a file that is there")


class Raster(object):
    """The source raster, as far as paint_whole reads it before the strips."""
    RasterXSize, RasterYSize = 100, 100
    def GetGeoTransform(self, **k): return (0.0, 1.0, 0.0, 0.0, 0.0, -1.0)
    def GetProjection(self): return ""


class Stencil(object):
    def __init__(self, *a, **k): pass
    def close(self): pass


def paint(outputs, writer, remove=None):
    """Run paint_whole with these outputs. writer(kind, path) stands in for
    open_for_write; remove, when given, stands in for os.remove. Returns what
    was raised and what was logged, as (loud, message) pairs."""
    said = []
    fake_os = os
    if remove is not None:
        fake_os = types.SimpleNamespace(path=os.path, remove=remove)
    g = {"os": fake_os, "np": None, "STRIP_ROWS": 64, "Stencil": Stencil,
         "mask_type": lambda *a, **k: None,
         "IOError": IOError,
         "log": lambda msg, loud=False: said.append((loud, str(msg))),
         "open_for_write": lambda driver, path, *a, **k: writer(driver, path),
         "finish_write": lambda ds, driver, path: None}
    for name in ("paint_whole", "pixel_grid", "scratch_of", "drop_scratch",
                 "long_path"):
        exec(take(name), g)
    recipe = {"ds": Raster(), "scale": 1, "rgb": [1, 2, 3],
              "limits": [(0.0, 255.0)] * 3, "alpha": 45, "colours": {},
              "outputs": outputs, "package": "unused.gpkg",
              "want_lines": False, "want_points": False, "want_boxes": False,
              "points_in_mask": False, "dot_px": 1}
    raised = None
    try:
        g["paint_whole"](recipe)
    except Exception as err:
        raised = err
    return raised, said


tmp = tempfile.mkdtemp(prefix="quiet_")
try:
    # PNG: the first output is painted into a scratch file that never reached
    # the disk, the second cannot be opened.
    png = os.path.join(tmp, "painted.png")
    mask = os.path.join(tmp, "mask.png")

    def in_memory(driver, path):
        if path == mask:
            raise IOError("cannot create mask.png. The disk may be full")
        return object()

    raised, said = paint([("painted", png, "PNG"), ("mask", mask, "PNG")],
                         in_memory)
    check("the real error still goes up", isinstance(raised, IOError), raised)
    check("nothing was left on disk", not os.path.exists(png))
    loud = [m for is_loud, m in said if is_loud]
    check("and nobody is told that a half-written file was left behind",
          not loud, loud)
    check("not even quietly",
          not any("half written" in m for _, m in said), said)

    # GeoTIFF: the first output is a real file on disk, and the removal fails
    # the way Windows makes it fail when something still has the file open.
    tif = os.path.join(tmp, "painted.tif")
    mask_tif = os.path.join(tmp, "mask.tif")

    def on_disk(driver, path):
        if path == mask_tif:
            raise IOError("cannot create mask.tif")
        with open(path, "wb") as fh:
            fh.write(b"half")
        return object()

    def refused(path):
        raise PermissionError(13, "the file is in use", path)

    raised, said = paint([("painted", tif, "GTiff"), ("mask", mask_tif, "GTiff")],
                         on_disk, remove=refused)
    loud = [m for is_loud, m in said if is_loud]
    check("a half-written file that is really there and cannot be removed "
          "is still said out loud",
          len(loud) == 1 and "painted.tif" in loud[0] and "half written" in loud[0],
          said)
    os.remove(tif)

    # And when the removal works, the file is gone and there is nothing to say.
    raised, said = paint([("painted", tif, "GTiff"), ("mask", mask_tif, "GTiff")],
                         on_disk)
    check("a half-written file that can be removed is removed",
          not os.path.exists(tif))
    check("without a warning", not [m for l, m in said if l], said)

    # A file the user agreed to replace is still theirs: it is not taken away.
    with open(png, "wb") as fh:
        fh.write(b"the user's own")
    raised, said = paint([("painted", png, "PNG"), ("mask", mask, "PNG")],
                         in_memory)
    check("a file that was there before is left alone", os.path.exists(png))
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# ==========================================================================
print()
print("the log goes to the console only where somebody reads it")


class MessageLog(object):
    said = []

    @classmethod
    def logMessage(cls, msg, *a):
        cls.said.append(msg)


def run_log(msg, inside_qgis, debug=False, console=None):
    printed, filed = [], []

    def fake_print(*a, **k):
        if console is not None:
            console(*a)
        printed.append(" ".join(str(x) for x in a))

    g = {"print": fake_print, "os": os, "NAME": "RasterLabel",
         "QgsMessageLog": MessageLog, "LEVEL_INFO": 0, "LEVEL_WARNING": 1,
         "to_file": filed.append,
         "iface": object() if inside_qgis else None}
    exec(take("log"), g)
    g.setdefault("DEBUG_VARIABLE", "RASTERLABEL_DEBUG")
    old = os.environ.pop("RASTERLABEL_DEBUG", None)
    if debug:
        os.environ["RASTERLABEL_DEBUG"] = "1"
    MessageLog.said = []
    raised = None
    try:
        g["log"](msg)
    except Exception as err:
        raised = err
    finally:
        os.environ.pop("RASTERLABEL_DEBUG", None)
        if old is not None:
            os.environ["RASTERLABEL_DEBUG"] = old
    return printed, filed, list(MessageLog.said), raised


printed, filed, logged, raised = run_log("campaign opened", inside_qgis=True)
check("inside QGIS nothing is printed", not printed, printed)
check("the message log still has it", logged == ["campaign opened"], logged)
check("and so does the file", filed == ["campaign opened"], filed)
printed, _, _, _ = run_log("campaign opened", inside_qgis=True, debug=True)
check("with RASTERLABEL_DEBUG set it is printed inside QGIS too",
      printed == ["[RasterLabel] campaign opened"], printed)
printed, _, _, _ = run_log("campaign opened", inside_qgis=False)
check("outside QGIS, where the console is all there is, it is printed",
      printed == ["[RasterLabel] campaign opened"], printed)


def cp1252(*a):
    "\n".join(str(x) for x in a).encode("cp1252")


_, filed, logged, raised = run_log("class \u03b1\u03bc\u03bc\u03bf\u03c2 saved",
                                   inside_qgis=False, console=cp1252)
check("a console that cannot spell the message does not make log() raise",
      raised is None, repr(raised))
check("and the line still reaches the message log and the file",
      len(logged) == 1 and len(filed) == 1, (logged, filed))
trouble = take("trouble").splitlines()
unguarded = [i for i, l in enumerate(trouble)
             if "print(" in l and not trouble[i - 1].strip() == "try:"]
check("the last-resort print of the trouble window is guarded as well",
      not unguarded, [trouble[i].strip() for i in unguarded])


# ==========================================================================
print()
print("the build stamp is not a hash a security scanner calls weak")
stamp = take("build_stamp")
check("it uses no MD5", "hashlib.md5" not in stamp)
check("it uses SHA-256", "hashlib.sha256(" in stamp)


def stamp_of(filename, package):
    g = {"hashlib": hashlib, "os": os, "sys": sys, "SHAPE": [],
         "__package__": package}
    exec(compile(stamp, filename, "exec"), g)
    return g["build_stamp"](), g["SHAPE"]


got, shape = stamp_of(SRC, None)
with open(SRC, "rb") as fh:
    want = hashlib.sha256(fh.read()).hexdigest()[:8]
check("the single file is stamped with the first eight letters of its "
      "SHA-256", got == want and not shape, (got, want, shape))
pkg = os.path.join(_ROOT, "rasterlabel")
got, shape = stamp_of(os.path.join(pkg, "constants.py"), "rasterlabel")
digest = hashlib.sha256()
for name in sorted(f for f in os.listdir(pkg) if f.endswith(".py")):
    digest.update(name.encode("utf-8"))
    with open(os.path.join(pkg, name), "rb") as fh:
        digest.update(fh.read())
check("the package is stamped over every module, names and contents",
      got == digest.hexdigest()[:8] and shape == ["package"],
      (got, digest.hexdigest()[:8], shape))
check("and the stamp is still eight hexadecimal letters",
      len(got) == 8 and all(c in "0123456789abcdef" for c in got), got)


# ==========================================================================
print()
print("the Check report says each thing once, and says it right")


class Gdal(object):
    @staticmethod
    def VersionInfo(_): return "3.8.4"

    @staticmethod
    def GetDriverByName(_): return object()


def system_line(system, release, version):
    fake = types.SimpleNamespace(system=lambda: system, release=lambda: release,
                                 version=lambda: version)
    g = {"platform": fake, "sys": sys, "gdal": Gdal, "VERSION": "1.1",
         "BUILD": "abcd1234", "SHAPE": "package", "BUILT_FOR": (3, 36),
         "BUILT_FOR_NAME": "Maidenhead",
         "qgis_version_text": lambda: "3.36.0"}
    exec(take("environment"), g)
    rows = g["environment"]()
    return dict(rows).get("system"), rows, g


line, _, _ = system_line("Windows", "10", "10.0.26200")
check("Windows 11 is called Windows 11", line == "Windows 11", line)
line, _, _ = system_line("Windows", "10", "10.0.22000")
check("from its very first build", line == "Windows 11", line)
line, _, _ = system_line("Windows", "10", "10.0.19045")
check("and Windows 10 is still Windows 10", line == "Windows 10", line)
line, _, _ = system_line("Windows", "11", "10.0.26200")
check("what a newer Python already says is kept", line == "Windows 11", line)
line, _, _ = system_line("Linux", "6.8.0-45-generic", "#45-Ubuntu SMP")
check("Linux is left as it is", line == "Linux 6.8.0-45-generic", line)

_, rows, envg = system_line("Windows", "10", "10.0.26200")
g = {"OK": "ok", "NOTE": "note", "BAD": "problem", "NAME": "RasterLabel",
     "VERSION": "1.1", "BUILD": "abcd1234", "WANTED_DRIVERS": [],
     "environment": envg["environment"], "gdal": Gdal, "ogr": Gdal,
     "log_path": lambda: None, "platform": envg["platform"], "sys": sys,
     "importlib": __import__("importlib")}
exec(take("Finding"), g)
exec(take("about_the_machine"), g)
findings = g["about_the_machine"]()
labels = [f.what.split()[0].lower() for f in findings
          if f.level == "ok" and f.what.split()[0].lower() in
          ("python", "numpy", "system", "platform", "gdal", "qgis", "qt")]
twice = sorted(set(l for l in labels if labels.count(l) > 1))
check("no version is listed twice", not twice, (twice, labels))
check("there is no second line for the platform under another name",
      "platform" not in labels, labels)
check("the system line says Windows 11",
      any(f.what.split() == ["system", "Windows", "11"] for f in findings),
      [f.what for f in findings])
check("Python is still in it, once", labels.count("python") == 1, labels)
# The program's own line was the last one said twice: "RasterLabel 1.1, build
# abcd1234" from about_the_machine() and "RasterLabel 1.1 build abcd1234, as a
# package (...)" from environment(). The second says more, so it is the one.
ours = [f.what for f in findings if "rasterlabel" in f.what.lower()]
check("RasterLabel itself is listed once", len(ours) == 1, ours)
check("and that line has the build, the shape and the QGIS it was built for",
      len(ours) == 1 and "abcd1234" in ours[0] and "package" in ours[0]
      and "3.36" in ours[0], ours)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
