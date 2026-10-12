"""Install the zip the way QGIS installs it, and drive the plugin through its life.

Everything else tests the program. This tests the delivery: the zip is unpacked
into a folder that is not the repository, the package is imported from there under
the name QGIS gives it, classFactory is called with an iface, the menu entry is
added, the button is pressed, and then the whole thing is unloaded and loaded
again, which is what Plugins, Reload does and what nobody has ever tried.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ["RL_ROOT"] = ROOT
import harness_imports
harness_imports            # it builds the fakes on import

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(name)


# ------------------------------------------------------------- a fake QGIS
class Action(object):
    """Enough of QAction for the wrapper. The real one is a Qt object, but what
    matters here is what the plugin does with it, not what Qt does."""


class Iface(object):
    def __init__(self):
        self.menu = []
        self.toolbar = []
        self.active = None

    def mainWindow(self):
        return None

    def addPluginToRasterMenu(self, name, action):
        self.menu.append((name, action))

    def removePluginRasterMenu(self, name, action):
        self.menu = [e for e in self.menu if e[1] is not action]

    def addToolBarIcon(self, action):
        self.toolbar.append(action)

    def removeToolBarIcon(self, action):
        self.toolbar = [a for a in self.toolbar if a is not action]

    def setActiveLayer(self, layer):
        self.active = layer

    def messageBar(self):
        class Bar(object):
            def pushMessage(self, *a, **k):
                pass
        return Bar()

    def __getattr__(self, name):
        return lambda *a, **k: None


# ------------------------------------------------------- unpack like QGIS does
here = tempfile.mkdtemp(prefix="rl_plugins_")
try:
    # The zip of the version that is being tested, not whichever zip is there:
    # a folder that has shipped twice holds more than one.
    import configparser as _cp
    _meta = _cp.ConfigParser()
    _meta.read(os.path.join(ROOT, "rasterlabel", "metadata.txt"), encoding="utf-8")
    wanted = "rasterlabel-%s.zip" % _meta.get("general", "version", fallback="")
    zips = sorted(f for f in os.listdir(os.path.join(ROOT, "dist"))
                  if f.endswith(".zip"))
    print("the zip QGIS would install")
    check("the zip for this version is in dist", wanted in zips,
          "looked for %s, found %s" % (wanted, zips))
    if wanted not in zips:
        raise SystemExit(1)
    path = os.path.join(ROOT, "dist", wanted)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        z.extractall(here)
    check("everything inside is under one folder named rasterlabel",
          all(n.startswith("rasterlabel/") for n in names),
          [n for n in names if not n.startswith("rasterlabel/")][:4])
    check("it carries metadata.txt", "rasterlabel/metadata.txt" in names)
    check("it carries __init__.py", "rasterlabel/__init__.py" in names)
    check("it carries the icon the metadata names", "rasterlabel/icon.svg" in names)
    check("it carries the licence", "rasterlabel/LICENSE" in names)
    check("it carries no test, tool or built file",
          not [n for n in names
               if "/tests/" in n or "/tools/" in n or "/dist/" in n
               or n.endswith(".pyc")],
          [n for n in names if "/tests/" in n or "/tools/" in n][:4])

    # metadata.txt is read by QGIS as an ini file before anything is imported
    print()
    print("metadata.txt, read the way QGIS reads it")
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(here, "rasterlabel", "metadata.txt"), encoding="utf-8")
    check("it has a [general] section", cfg.has_section("general"))
    for field in ("name", "qgisMinimumVersion", "description", "version",
                  "author", "email", "about"):
        check("it has %s" % field, cfg.has_option("general", field))
    icon = cfg.get("general", "icon", fallback="")
    check("the icon it names is in the zip",
          ("rasterlabel/" + icon) in names, icon)

    print()
    print("import it from where QGIS unpacked it, not from the repository")
    # QGIS puts the plugins folder on sys.path and imports the folder name.
    for name in list(sys.modules):
        if name == "rasterlabel" or name.startswith("rasterlabel."):
            del sys.modules[name]
    sys.path.insert(0, here)
    # and the repository must not be the thing that answers
    sys.path = [p for p in sys.path if os.path.abspath(p) != os.path.abspath(ROOT)]
    import rasterlabel as plug
    check("it imports", True)
    check("from the unpacked copy, not the repository",
          os.path.dirname(os.path.abspath(plug.__file__)).startswith(here),
          plug.__file__)
    check("it offers classFactory", callable(plug.classFactory))
    check("and says which build it is", isinstance(plug.BUILD, str))
    check("the version matches metadata.txt",
          plug.VERSION == cfg.get("general", "version"),
          (plug.VERSION, cfg.get("general", "version")))

    print()
    print("nothing was built or run merely by importing")
    # The panel is kept in launch.py's own namespace under _RASTERLABEL. If it
    # were there now, something had built a dock while QGIS was still starting,
    # which is how a plugin fails on a machine nobody can reproduce.
    import rasterlabel.launch as launch
    check("no panel exists yet", getattr(launch, "_RASTERLABEL", None) is None,
          getattr(launch, "_RASTERLABEL", None))
    check("and the panel builder is there, waiting to be called",
          callable(getattr(launch, "start", None)))

    print()
    print("load it, the way QGIS does")
    iface = Iface()
    obj = plug.classFactory(iface)
    check("classFactory returns something", obj is not None)
    for needed in ("initGui", "unload"):
        check("it has %s, which QGIS calls by name" % needed,
              callable(getattr(obj, needed, None)))
    obj.initGui()
    check("a menu entry was added", len(iface.menu) == 1, iface.menu)
    check("a toolbar icon was added", len(iface.toolbar) == 1)

    print()
    print("unload it, the way QGIS does when the plugin is disabled or reloaded")
    obj.unload()
    check("the menu entry went away", not iface.menu, iface.menu)
    check("the toolbar icon went away", not iface.toolbar, iface.toolbar)

    print()
    print("load it again: Plugins, Reload")
    obj2 = plug.classFactory(iface)
    obj2.initGui()
    check("one menu entry, not two", len(iface.menu) == 1, iface.menu)
    check("one toolbar icon, not two", len(iface.toolbar) == 1)
    obj2.unload()
    check("and it comes apart again", not iface.menu and not iface.toolbar)

    print()
    print("unload before initGui, which happens when loading failed half way")
    obj3 = plug.classFactory(iface)
    try:
        obj3.unload()
        ok = True
    except Exception as err:
        ok, why = False, err
    check("does not raise", ok, locals().get("why", ""))
finally:
    shutil.rmtree(here, ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
