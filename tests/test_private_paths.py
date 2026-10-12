"""A path or a source that is written for somebody else carries no name.

A manifest, a dataset folder or a report is zipped, published, sent. These are
the rules the helpers of naming.py keep for what goes in them, tried on the
paths of Windows and on those of a POSIX machine alike (the helpers are run
over ntpath and over posixpath, whatever this machine is):

  inside the folder, the way from it; elsewhere under the home folder, from
  ~ (~/maps/a.tif); a way that would climb out of the home folder is never
  written, and neither is one that goes down through it; a file on another
  drive or a server keeps its whole path, which has no home in it;
  ~ is read back from the home folder of whoever opens it, a whole path
  written before is read as it was;
  a source that is not a file (a WMS, a tile server, a PostGIS table, a
  link with user:password@) loses its password, user name and token, keeps
  authcfg, and two spellings of one source (with and without them) are the
  same layer for Cutouts.

The code is lifted out of the built file, as written. No QGIS, no GDAL.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import io
import ntpath
import os
import posixpath
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
SRC = os.environ.get("RL_SRC") or os.path.join(ROOT, "dist", "rasterlabel.py")
source = io.open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)

fails = []


def check(name, cond, detail=""):
    cond = bool(cond)
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)[:300]) if not cond else ""))
    if not cond:
        fails.append(name)


def take(name):
    for node in tree.body:
        if getattr(node, "name", None) == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return "".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("%s not found" % name)


NAMES = ("long_path", "home_folder", "home_rest", "with_tilde",
         "_LOGIN_KEYS", "_LOGIN_PAIR", "_LOGIN_LINK", "_VSI_NAME",
         "clean_source", "inside_folder", "beside_folder", "relative_or_name",
         "from_folder", "without_home")
HELD = set()                # the paths the fake file system says are there


def world(flavour, home):
    """The helpers, over the paths of Windows ("nt") or of POSIX, with this
    home folder and the files of HELD."""
    module = ntpath if flavour == "nt" else posixpath
    path = types.SimpleNamespace(**{n: getattr(module, n) for n in dir(module)
                                    if not n.startswith("__")})
    path.expanduser = lambda p: (home + p[1:]) if p[:1] == "~" and \
        p[1:2] in ("", "/", "\\") else p
    path.exists = lambda p: p in HELD
    fake = types.SimpleNamespace(path=path, sep=module.sep, name=flavour)
    g = {"os": fake, "re": re, "sys": sys}
    for name in NAMES:
        exec(take(name), g)
    return g


def trials(flavour, g, home, sep, mod):
    j = lambda *p: sep.join(p)
    inside = j(home, "work", "camp")                # a folder in the home
    maps_in = j(home, "maps", "a.tif")              # a map in the home
    if flavour == "nt":
        away = "C:\\work\\camp"                     # a folder outside it
        far = "C:\\data\\a.tif"                     # a map outside it
        other = "D:\\data\\a.tif"                   # another drive
        server = "\\\\srv\\share\\a.tif"
    else:
        away = "/data/camp"
        far = "/data/maps/a.tif"
        other = "/" + "mnt" + "/usb/a.tif"     # another volume
        server = "/srv/share/a.tif"
    user = "alice"
    beside, back = g["beside_folder"], g["from_folder"]

    print("%s: beside_folder" % flavour)
    check("a file in the folder, by its name",
          beside(j(inside, "o.tif"), inside) == "o.tif",
          beside(j(inside, "o.tif"), inside))
    check("a map elsewhere in the home, the way up and down inside it",
          beside(maps_in, inside) == "../../maps/a.tif",
          beside(maps_in, inside))
    check("the home folder's map seen from a folder outside it: from ~",
          beside(maps_in, away) == "~/maps/a.tif", beside(maps_in, away))
    check("and with a layer name after the bar",
          beside(maps_in + "|layername=x", away) == "~/maps/a.tif|layername=x")
    check("a map outside the home seen from a folder in it: never the way "
          "up out of the home, the whole path (which has no home in it)",
          beside(far, inside) == far, beside(far, inside))
    check("both outside the home: the way up and down, as before",
          beside(far, away) == (
              "../../data/a.tif" if flavour == "nt" else "../maps/a.tif"),
          beside(far, away))
    check("the home folder itself is ~", beside(home, away) == "~",
          beside(home, away))
    check("a server or another volume seen from a folder in the home keeps "
          "its whole path",
          beside(server, inside) == server and beside(other, inside) == other,
          (beside(server, inside), beside(other, inside)))
    if flavour == "nt":
        check("another drive or a server, from a folder outside the home: "
              "whole, there is no way to it",
              beside(other, away) == other and beside(server, away) == server)
    check("no way written leaves the name in it",
          all(user not in beside(p, f) for p in (maps_in, far, home)
              for f in (inside, away)),
          [beside(p, f) for p in (maps_in, far, home) for f in (inside, away)])
    check("no way written climbs out of the home folder",
          all(not beside(p, inside).startswith("../../../")
              for p in (maps_in, far, other)))
    for text in ("https://example.org/tiles/{z}.png", "relative.tif", "",
                 None, "/vsicurl/https://example.org/a.tif"):
        check("%r is not a file here, as it was" % (text,),
              beside(text, inside) == text)

    print("%s: inside_folder" % flavour)
    ins = g["inside_folder"]
    check("in the folder, the way from it",
          ins(j(inside, "sub", "o.tif"), inside) == "sub/o.tif")
    check("elsewhere in the home, from ~", ins(maps_in, inside) == "~/maps/a.tif",
          ins(maps_in, inside))
    check("outside the home, as it was", ins(far, inside) == far)
    check("a folder that holds the home: its files are written from ~, not "
          "down through the name",
          ins(maps_in, mod.dirname(home)) == "~/maps/a.tif",
          ins(maps_in, mod.dirname(home)))

    print("%s: relative_or_name" % flavour)
    rel = g["relative_or_name"]
    check("a campaign seen from its correction, inside the home",
          rel(inside, j(inside, "corrections", "fix")) == "../..")
    check("a folder of the home seen from outside it: from ~",
          rel(inside, away) == "~/work/camp", rel(inside, away))
    check("a folder outside seen from the home: its name, no way up",
          rel(away, inside) == mod.basename(away), rel(away, inside))

    print("%s: from_folder" % flavour)
    HELD.add(j(inside, "o.tif"))
    check("~ is the home folder of whoever opens it",
          back("~", away) == mod.normpath(home))
    check("~/maps/a.tif is read from the home folder",
          back("~/maps/a.tif", away) == mod.normpath(j(home, "maps", "a.tif")),
          back("~/maps/a.tif", away))
    check("with the layer name after the bar",
          back("~/maps/a.tif|layername=x", away)
          == mod.normpath(j(home, "maps", "a.tif")) + "|layername=x")
    check("a whole path written before is what it was",
          back(maps_in, away) == maps_in and back(far, inside) == far)
    check("a relative name the folder holds is joined to it",
          back("o.tif", inside) == mod.normpath(j(inside, "o.tif")),
          back("o.tif", inside))
    check("what was written is read back as the same place",
          mod.normpath(back(beside(maps_in, away), away))
          == mod.normpath(maps_in))
    check("and so the home itself",
          mod.normpath(back(beside(home, away), away)) == mod.normpath(home))

    print("%s: a file read through /vsi names" % flavour)
    inner = (home.replace("\\", "/") + "/data/a.zip/b.tif")
    vsi = "/vsizip/" + inner
    clean = g["clean_source"](vsi)
    check("the home folder is ~ in it", clean == "/vsizip/~/data/a.zip/b.tif",
          clean)
    check("and is read back from the home",
          back(clean, away).replace("\\", "/").replace("//", "/")
          == vsi.replace("//", "/"), back(clean, away))
    check("the name of a zip outside the home is as it was",
          g["clean_source"]("/vsizip/" + far.replace("\\", "/"))
          == "/vsizip/" + far.replace("\\", "/"))

    print("%s: without_home also takes the logins out" % flavour)
    said = g["without_home"]("cannot open %s with password=s3cret"
                             % maps_in)
    check("the home is ~ and the password is gone",
          said == "cannot open ~%smaps%sa.tif with" % (sep, sep)
          or said == "cannot open ~%smaps%sa.tif" % (sep, sep), said)


# the homes are put together: no path of anybody's machine is written here
NT_HOME = "C:" + "\\" + "Users" + "\alice"
POSIX_HOME = "/" + "home" + "/alice"
for flavour, home, sep, mod in (("nt", NT_HOME, "\\", ntpath),
                                ("posix", POSIX_HOME, "/", posixpath)):
    trials(flavour, world(flavour, home), home, sep, mod)
    print()

# --------------------------------------------------------------- the sources
print("sources that are not files")
g = world("posix", POSIX_HOME)
clean = g["clean_source"]
cases = [
    ("a WMS with a user name and a password",
     "contextualWMSLegend=0&crs=EPSG:32633&url=https://maps.example.org/wms"
     "&username=bob&password=s3cret&layers=ortho",
     "contextualWMSLegend=0&crs=EPSG:32633&url=https://maps.example.org/wms"
     "&layers=ortho"),
    ("a PostGIS table",
     "PG: dbname=gis host=db.lab.it user=bob password=s3cret table=ortho",
     "PG: dbname=gis host=db.lab.it table=ortho"),
    ("values in quotes, the quote doubled or escaped",
     "PG: dbname='gis' user='bob smith' password='it''s \\' x' table=ortho",
     "PG: dbname='gis' table=ortho"),
    ("authcfg is kept",
     "PG: dbname=gis authcfg=a1b2c3 user=bob table=ortho",
     "PG: dbname=gis authcfg=a1b2c3 table=ortho"),
    ("a token in the query of a tile server",
     "type=xyz&url=https://t.example.org/{z}/{x}/{y}.png?token=abc123"
     "&zmax=19&zmin=0",
     "type=xyz&url=https://t.example.org/{z}/{x}/{y}.png?zmax=19&zmin=0"),
    ("an access_token, last in the query",
     "type=xyz&url=https://t.example.org/{z}.png?access_token=abc",
     "type=xyz&url=https://t.example.org/{z}.png?"),
    ("user:password@ in the link",
     "type=xyz&url=https://bob:s3cret@t.example.org/{z}.png&zmax=19",
     "type=xyz&url=https://t.example.org/{z}.png&zmax=19"),
    ("a GDAL link to a server",
     "/vsicurl/https://bob:pw@host/x.tif", "/vsicurl/https://host/x.tif"),
    ("the link written in percent codes",
     "url=https%3A%2F%2Fbob%3Apw%40host%2Fwms%3Ftoken%3Dabc&layers=x",
     "url=https%3A%2F%2Fhost%2Fwms%3F&layers=x"),
    ("a source with nothing to hide",
     "authcfg=a1b2c3&url=https://x/wms&layers=ortho",
     "authcfg=a1b2c3&url=https://x/wms&layers=ortho"),
    ("a word that is not a key", "the user is bob", "the user is bob"),
    ("a line of code in a traceback", "    signature = (what, err)",
     "    signature = (what, err)"),
    ("a file path", "/data/ortho.tif|layername=x", "/data/ortho.tif|layername=x"),
]
for what, given, expected in cases:
    check(what, clean(given) == expected, clean(given))
for secret in ("s3cret", "abc123", "bob:"):
    check("%s is in none of the cleaned sources" % secret,
          not [w for w, given, _ in cases if secret in clean(given)])
check("nothing and not-text stay as they are",
      clean("") == "" and clean(None) is None and clean(12) == 12)
beside = g["beside_folder"]
wms = ("contextualWMSLegend=0&url=https://maps.example.org/wms"
       "&username=bob&password=s3cret&layers=ortho")
check("the reference raster of a campaign that is a WMS has no login",
      "s3cret" not in beside(wms, "/data/camp")
      and "bob" not in beside(wms, "/data/camp"), beside(wms, "/data/camp"))
check("nor one that is a database table",
      "s3cret" not in beside("PG: dbname=gis user=bob password=s3cret", "/d"))

# The layers of a Cutouts folder are known by their source, and the source a
# folder remembers has no login: the live layer, which has, must be the same.
exec(take("layer_key"), g)
key = g["layer_key"]
check("a layer with its password and the folder's record of it are one",
      key(wms) == key(clean(wms)), (key(wms), key(clean(wms))))
check("a file is still its normalised path",
      key("/data//maps/../ortho.tif|layername=x") == "/data/ortho.tif")

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
