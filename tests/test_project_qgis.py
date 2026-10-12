"""The project, the launcher, the privacy of the files, in a real QGIS.

Four things that went wrong on the way a person starts, shares and moves a
campaign, each seen failing here before it was fixed.

New campaign. The window proposed the first raster by name and ignored the
one the person had selected in the Layers panel; "press Ok straight away"
made the campaign, for good, on the grid of the wrong picture.

The launcher. With the plugin installed, the two lines of the README built a
second panel beside the plugin's, two tools on one map: each copy of the code
only knew the panel it had made itself. And the dock had no name, so QGIS
could not remember where the person had put it.

What is written for others to read. campaign.json and correction.json kept
the whole path of everything, the name of the person who made the campaign
among it, in files that are zipped and sent. A file inside the folder is now
written relative to it, and a manifest written before is read as it was. The
Check and error reports, which are pasted into public issues, write the home
folder as ~. The dataset card names a file outside its folder by its name.

Setting a campaign aside. annotation.gpkg was moved and its -wal and -shm
were left, to be replayed into the next campaign written under that name.

Needs QGIS; tests/run.py skips it where QGIS is missing and, with
RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qgiskit as K  # noqa: E402
from qgis.PyQt.QtCore import QCoreApplication, QEvent  # noqa: E402
from qgis.PyQt.QtWidgets import QDockWidget  # noqa: E402
from qgis.core import QgsProject  # noqa: E402

print("QGIS %s" % K.QGIS_VERSION)
g = K.g
# a build without it fails the checks below, not the whole suite
from_folder = g.get("from_folder") or (lambda path, folder: path)
# inside the home of this run, so that "the home folder" is something the
# paths below are really under
HOME = os.path.expanduser("~")
root = tempfile.mkdtemp(prefix="rl_project_", dir=HOME)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def raw(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def forget_events():
    QCoreApplication.sendPostedEvents(
        None, getattr(QEvent, "Type", QEvent).DeferredDelete)
    K.app.processEvents()


# ------------------------------------------------------------ New campaign
print()
print("New campaign proposes the raster in hand")
data = os.path.join(root, "data")
image = K.layer_of(K.write_image(os.path.join(data, "z_image.tif"), n=50),
                   "z_image")
classes = K.layer_of(K.write_classes(os.path.join(data, "a_classes.tif")),
                     "a_classes", show=False)
top = K.layer_of(K.write_classes(os.path.join(data, "k_top.tif")), "k_top",
                 show=False)
panel = K.new_panel()
seen = []


def asked(d):
    seen.append((d.chosen_raster().name(), d.raster.count()))
    return 0


K.ANSWERS["NewCampaign"] = asked
K.iface.activeLayer = lambda: image
panel.new_campaign()
check_name = "the raster selected in the Layers panel, not the first by name"
K.check(check_name, seen == [("z_image", 3)], seen)

K.iface.activeLayer = lambda: None
K.ANSWERS["NewCampaign"] = asked
panel.new_campaign()
K.check("with nothing selected, the one on top of the Layers panel",
        seen[-1][0] == "k_top", seen)
K.check("the box of the panel started on the first by name, and said nothing",
        panel.rasters.currentText() == "a_classes", panel.rasters.currentText())

panel.rasters.setCurrentIndex(panel.rasters.findText("z_image"))
K.ANSWERS["NewCampaign"] = asked
panel.new_campaign()
K.check("the box of the panel, set to another by hand, counts",
        seen[-1][0] == "z_image", seen)
K.close_panel(panel)

# ------------------------------------------------------------ the launcher
print()
print("the launcher and the plugin share one panel")
main = K.iface.main
K.iface.addDockWidget = lambda area, dock: main.addDockWidget(area, dock)
K.iface.removeDockWidget = lambda dock: main.removeDockWidget(dock)


def docks():
    forget_events()
    return main.findChildren(QDockWidget, "RasterLabelDock")


def dock():
    """The one dock, or a stand-in that is shown and hidden by nobody."""
    found = docks()
    return found[0] if found else None


# the other copy of the program: the plugin, next to the file pasted into the
# console, each with its own idea of the panel that is up
other = {"__name__": "rasterlabel", "__file__": K.SRC}
exec(compile(K._code, K.SRC, "exec"), other)
K.check("the two copies are two namespaces", other is not g
        and other["main"] is not g["main"])

first = g["main"]()
K.check("the dock has a name QGIS can save its place under",
        len(docks()) == 1 and dock().objectName() == "RasterLabelDock",
        [d.objectName() for d in main.findChildren(QDockWidget)])
second = other["main"]()
K.check("the other copy does not build a second panel",
        len(docks()) == 1, len(docks()))
K.check("it hands back the panel that is up", second is first)
K.check("and puts the dock where it can be seen",
        dock() is not None and not dock().isHidden())

if dock() is not None:
    dock().hide()
other["main"]()
K.check("a dock the person closed is brought back, not duplicated",
        len(docks()) == 1 and not dock().isHidden())

# the X gave the arrow keys back; the dock shown again has to take them again
from qgis.PyQt.QtGui import QKeyEvent  # noqa: E402
from qgis.PyQt.QtWidgets import QApplication  # noqa: E402
zoomed = []
real_zoom = g["zoom"]
g["zoom"] = lambda *a: zoomed.append(a)
first.keyboard.setChecked(True)
plus = QKeyEvent(QEvent.Type.KeyPress, g["Qt"].Key.Key_Plus,
                 g["Qt"].KeyboardModifier.NoModifier, "+")
QApplication.sendEvent(K.iface.mapCanvas().viewport(), plus)
K.check("the keys of the map are the panel's again after the dock was closed "
        "and brought back", len(zoomed) == 1, zoomed)
g["zoom"] = real_zoom

third = g["main"]()
K.check("the copy that made the panel replaces it, as it always did",
        len(docks()) == 1 and third is not first, len(docks()))
g["shut_down"]()
K.check("and takes it down", len(docks()) == 0, len(docks()))

# a dock with nothing in it is a leftover
stale = QDockWidget("RasterLabel")
stale.setObjectName("RasterLabelDock")
main.addDockWidget(g["Qt"].DockWidgetArea.RightDockWidgetArea, stale)
fresh = other["main"]()
K.check("a leftover dock with no panel in it is taken away for a new one",
        len(docks()) == 1 and dock() is not stale and fresh is not None,
        len(docks()))
other["shut_down"]()
K.check("and the plugin's unload takes its own down", len(docks()) == 0)

# ------------------------------------------------- paths in the manifests
print()
print("campaign.json: a file inside the folder is written relative to it")
work = os.path.join(HOME, "work")
camp_dir = os.path.join(work, "camp")
inside = K.layer_of(K.write_image(os.path.join(camp_dir, "ortho.tif"), n=50),
                    "ortho_inside", show=False)
panel = K.new_panel()
camp = K.new_campaign(panel, camp_dir, inside)
text = read(camp.manifest_path)
grid = json.loads(text)["grid"]
K.check("the reference raster inside the folder is its name, not its path",
        grid["reference_raster"] == "ortho.tif", grid["reference_raster"])
K.check("and the home folder is nowhere in the manifest",
        HOME not in text and HOME.replace("\\", "/") not in text
        and HOME.replace("\\", "\\\\") not in text)
K.check("the campaign finds nothing wrong with it",
        g["Campaign"].open(camp_dir).reconcile() == [],
        g["Campaign"].open(camp_dir).reconcile())
K.check("the campaign knows where the raster is",
        from_folder(grid["reference_raster"], camp_dir)
        == os.path.join(camp_dir, "ortho.tif"))
K.close_panel(panel)

moved_dir = os.path.join(root, "sent_by_mail", "camp")
shutil.copytree(camp_dir, moved_dir)
K.check("the folder zipped and sent still finds its raster",
        g["Campaign"].open(moved_dir).reconcile() == [],
        g["Campaign"].open(moved_dir).reconcile())

old = json.loads(read(os.path.join(camp_dir, "campaign.json")))
old["grid"]["reference_raster"] = os.path.join(camp_dir, "ortho.tif")
with open(os.path.join(camp_dir, "campaign.json"), "w") as fh:
    json.dump(old, fh)
K.check("a manifest written before, with the whole path, opens as it did",
        g["Campaign"].open(camp_dir).reconcile() == [])
old["grid"]["reference_raster"] = os.path.join(camp_dir, "gone.tif")
with open(os.path.join(camp_dir, "campaign.json"), "w") as fh:
    json.dump(old, fh)
K.check("and one whose raster is gone still says so, with the name",
        any("no longer where it was" in t and "gone.tif" in t
            for t in g["Campaign"].open(camp_dir).reconcile()))

print()
print("a raster outside the folder is written by its way from the folder")
elsewhere = K.layer_of(K.write_image(os.path.join(root, "elsewhere", "o.tif"),
                                     n=50), "o_outside", show=False)
panel = K.new_panel()
out_dir = os.path.join(work, "camp_out")
camp2 = K.new_campaign(panel, out_dir, elsewhere)
ref = json.loads(read(camp2.manifest_path))["grid"]["reference_raster"]
K.check("it is a way from the folder, not the path of the file",
        not os.path.isabs(ref) and ref.startswith("../")
        and ref.endswith("elsewhere/o.tif"), ref)
K.check("the home folder is nowhere in the manifest",
        HOME not in read(camp2.manifest_path)
        and HOME.replace("\\", "/") not in read(camp2.manifest_path))
K.check("the campaign finds the file all the same",
        os.path.samefile(from_folder(ref, out_dir), elsewhere.source())
        and g["Campaign"].open(out_dir).reconcile() == [],
        g["Campaign"].open(out_dir).reconcile())
K.close_panel(panel)

print()
print("the home folder is not climbed out of, nor gone down through")
# a folder outside the home folder: the way to a map in the home would run
# through the name of whoever owns it, so it is written from ~
away = tempfile.mkdtemp(prefix="rl_project_away_")
try:
    panel = K.new_panel()
    camp_away = K.new_campaign(panel, os.path.join(away, "camp"), elsewhere)
    text = read(camp_away.manifest_path)
    ref = json.loads(text)["grid"]["reference_raster"]
    K.check("a campaign outside the home, its map in it: from ~",
            ref == "~/" + os.path.relpath(elsewhere.source(), HOME)
            .replace(os.sep, "/"), ref)
    K.check("the home folder and the way up to it are nowhere in the manifest",
            HOME not in text and HOME.replace("\\", "/") not in text
            and HOME.replace("\\", "\\\\") not in text
            and ".." not in ref)
    K.check("opened again, the campaign finds the map",
            os.path.samefile(from_folder(ref, camp_away.folder),
                             elsewhere.source())
            and g["Campaign"].open(camp_away.folder).reconcile() == [],
            g["Campaign"].open(camp_away.folder).reconcile())
    card = g["card_gather_campaign"](camp_away.data, camp_away.folder,
                                     camp_away.package_path,
                                     where=camp_away.folder)
    K.check("the dataset card finds the map that ~ names, and keeps only "
            "its name", card["grid"].get("reference_present") is True
            and card["grid"].get("reference_raster") == "o.tif"
            and HOME not in json.dumps(card), card["grid"])
    K.close_panel(panel)
    # a map outside the home folder, a campaign in it: no way up out of it
    far = K.layer_of(K.write_image(os.path.join(away, "maps", "o.tif"), n=50),
                     "o_far", show=False)
    panel = K.new_panel()
    camp_far = K.new_campaign(panel, os.path.join(work, "camp_far"), far)
    ref = json.loads(read(camp_far.manifest_path))["grid"]["reference_raster"]
    K.check("a map outside the home, a campaign in it: the whole path, no "
            "way up and out of the home folder",
            os.path.isabs(ref) and ".." not in ref
            and g["Campaign"].open(camp_far.folder).reconcile() == [], ref)
    K.close_panel(panel)
    # the same for the map a correction started from
    src_home = K.layer_of(os.path.join(data, "a_classes.tif"), "a_home",
                          show=False)
    fixed_away = g["CorrectionCampaign"].create(
        os.path.join(away, "corr"), "fix", src_home, 1,
        [{"code": 1, "name": "a", "colour": "#ff0000"}], "ANNA")
    said = read(fixed_away.manifest_path)
    man = json.loads(said)
    K.check("a correction outside the home, its map in it: from ~",
            man["source"] == "~/" + os.path.relpath(
                os.path.join(data, "a_classes.tif"), HOME).replace(os.sep, "/"),
            man["source"])
    K.check("no home folder in it", HOME not in said
            and HOME.replace("\\", "/") not in said
            and HOME.replace("\\", "\\\\") not in said)
    K.check("opened again it is the map itself",
            g["same_file"](g["CorrectionCampaign"].open(
                os.path.join(away, "corr")).data["source"],
                os.path.join(data, "a_classes.tif")))
finally:
    shutil.rmtree(away, ignore_errors=True)

print()
print("correction.json and the record a campaign keeps of it")
camp3_dir = os.path.join(work, "camp3")
os.makedirs(os.path.join(camp3_dir, "corrections", "fix"))
legacy = os.path.join(camp3_dir, "corrections", "fix", "map_corrected.tif")
shutil.copy(os.path.join(data, "a_classes.tif"), legacy)
panel = K.new_panel()
camp3 = K.new_campaign(panel, camp3_dir, inside)
record = {"name": "fix", "files": [legacy], "band": 1, "source":
          os.path.join(data, "a_classes.tif"), "created": "2026-10-01T10:00:00",
          "classes": [{"code": 1, "name": "a", "colour": "#ff0000"}],
          "operations": 2}
camp3.data["corrections"] = [record]
camp3.save()
book = g["CorrectionCampaign"].adopt(record, camp3)
cj = read(book.manifest_path)
K.check("the correction's grid points at its copy by name",
        json.loads(cj)["grid"]["reference_raster"] == "map_corrected.tif",
        json.loads(cj)["grid"]["reference_raster"])
K.check("it says which campaign it came from without saying where",
        json.loads(cj)["migrated_from"]["campaign"] == "../..",
        json.loads(cj)["migrated_from"])
K.check("the record in campaign.json points at the correction relatively",
        camp3.data["corrections"][0]["moved_to"]
        == "corrections/fix/correction.json",
        camp3.data["corrections"][0]["moved_to"])
K.check("neither file holds the home folder",
        HOME not in cj and HOME not in read(camp3.manifest_path))
K.check("the campaign still finds the correction it moved",
        g["corrections_of"](os.path.join(data, "a_classes.tif"), camp3)
        and g["_moved_corrections"](camp3) == [],
        (g["corrections_of"](os.path.join(data, "a_classes.tif"), camp3),
         g["_moved_corrections"](camp3)))
K.check("and the campaign folder, opened again, finds nothing wrong",
        g["Campaign"].open(camp3_dir).reconcile() == [],
        g["Campaign"].open(camp3_dir).reconcile())
shutil.rmtree(os.path.join(camp3_dir, "corrections", "fix"))
gone = g["_moved_corrections"](camp3)
K.check("a correction folder deleted is said, with a path from the folder",
        len(gone) == 1 and "corrections/fix/correction.json" in str(gone[0])
        .replace("\\", "/"), [str(x) for x in gone])

print()
print("a new correction keeps the copy and the source relative")
src_layer = K.layer_of(os.path.join(data, "a_classes.tif"), "a_classes_2",
                       show=False)
corr_dir = os.path.join(work, "corr")
fixed = g["CorrectionCampaign"].create(
    corr_dir, "fix", src_layer, 1,
    [{"code": 1, "name": "a", "colour": "#ff0000"}], "ANNA")
manifest = json.loads(read(fixed.manifest_path))
K.check("the working copy is its name", manifest["working_copy"]
        == os.path.basename(manifest["working_copy"]))
K.check("the map it came from is a way from the folder",
        not os.path.isabs(manifest["source"])
        and manifest["source"].endswith("data/a_classes.tif"),
        manifest["source"])
K.check("and no path of this machine is in the manifest",
        HOME not in read(fixed.manifest_path)
        and HOME.replace("\\", "/") not in read(fixed.manifest_path))
reopened = g["CorrectionCampaign"].open(corr_dir)
K.check("opened again it is the map itself",
        g["same_file"](reopened.data["source"],
                       os.path.join(data, "a_classes.tif"))
        and os.path.isabs(reopened.data["source"]), reopened.data["source"])
K.check("a peek at the manifest says the same",
        g["same_file"](g["peek_correction"](fixed.manifest_path)["source"],
                       os.path.join(data, "a_classes.tif")))
reopened.save()
K.check("and saved again it stays relative",
        json.loads(read(fixed.manifest_path))["source"] == manifest["source"])
old = json.loads(read(fixed.manifest_path))
old["source"] = os.path.join(data, "a_classes.tif")
with open(fixed.manifest_path, "w") as fh:
    json.dump(old, fh)
K.check("a manifest written before, with the whole path, opens as it did",
        g["CorrectionCampaign"].open(corr_dir).data["source"]
        == os.path.join(data, "a_classes.tif"))
K.close_panel(panel)

# ----------------------------------------------- what is pasted into issues
print()
print("the reports that are pasted into public issues write ~ for the home")
panel = K.new_panel()
camp4 = K.new_campaign(panel, os.path.join(work, "camp4"), inside)
text, bad, notes = K.check_report(camp4)
K.check("Check names the folder of the campaign", "camp4" in text)
K.check("without the home folder", HOME not in text
        and HOME.replace("\\", "/") not in text, [l for l in text.splitlines()
                                                    if HOME in l][:3])
K.check("the home is ~ there", "~" in text)
try:
    raise OSError("cannot write %s" % os.path.join(HOME, "work", "x.gpkg"))
except OSError as err:
    class Fake:
        pass
    rep = g["Trouble"].build_report(Fake(), err, "Saving", "it could not save")
K.check("the error report has the message and the trace",
        "cannot write" in rep and "Traceback" in rep)
K.check("and not the home folder", HOME not in rep, rep[:400])

print()
print("the dataset card names a file outside its folder, not its way")
card_dir = os.path.join(work, "card")
os.makedirs(card_dir)
outside = os.path.join(root, "elsewhere", "export.gpkg")
shutil.copy(os.path.join(data, "a_classes.tif"), outside)
inside_file = os.path.join(card_dir, "mask.tif")
shutil.copy(outside, inside_file)
done = g["card_exports"]([{"path": outside, "role": "vectors"},
                          {"path": inside_file, "role": "vectors"}],
                         card_dir, None, [], (0, 1, 0, 0, 0, -1), "")
K.check("a file beside the card is given relative to it",
        done[1]["path"] == "mask.tif", done[1]["path"])
K.check("one elsewhere by its name alone", done[0]["path"] == "export.gpkg",
        done[0]["path"])
card = g["card_gather_correction"](fixed.data, fixed.folder)
K.check("the card of a correction has no path of this machine",
        HOME not in json.dumps(card) and root not in json.dumps(card),
        [k for k, v in card.items() if HOME in json.dumps(v)])

# ------------------------------------------------- the log is not a dataset file
print()
print("the log in the Cutouts folder is nobody's data")
cut = os.path.join(work, "cutouts_folder")
os.makedirs(cut)
g["log_to"](cut)
g["log"]("written in %s" % os.path.join(HOME, "secret", "x"))
g["log_to"](None)
logfile = os.path.join(cut, "rasterlabel.log")
K.check("the log is written in the folder, where it always was",
        os.path.exists(logfile))
K.check("without the home folder in it", HOME not in read(logfile),
        read(logfile)[:300])
K.check("and the home written as ~", "~" in read(logfile))

g["log_to"](camp4.folder)
g["log"]("something said beside the campaign")
card = g["card_gather_campaign"](camp4.data, camp4.folder,
                                 camp4.package_path, where=camp4.folder)
written = g["card_write"](card, camp4.folder, "camp4")
g["log_to"](None)
K.check("the dataset card of a folder that holds the log does not list it",
        len(written) == 2 and all(
            "rasterlabel.log" not in read(f) for f in written),
        [f for f in written if "rasterlabel.log" in read(f)])
K.check("and no path of this machine is in the card",
        all(HOME not in read(f) and root not in read(f) for f in written),
        [os.path.basename(f) for f in written if HOME in read(f)])

K.close_panel(panel)

# ------------------------------------------------ set aside (SQLite sidecars)
print()
print("a campaign set aside takes its -wal and -shm with it")
aside = os.path.join(work, "aside")
panel = K.new_panel()
camp5 = K.new_campaign(panel, aside, inside)
K.close_panel(panel)
QgsProject.instance().clear()
inside = K.layer_of(os.path.join(camp_dir, "ortho.tif"), "ortho_again",
                    show=False)
package = os.path.join(aside, "annotation.gpkg")
for tail, body in (("-wal", b"old pages"), ("-shm", b"shared")):
    with open(package + tail, "wb") as fh:
        fh.write(body)
moved = g["set_aside"](aside)
K.check("the manifest, the package and the sidecars are moved",
        len(moved) == 4 and sum(m.endswith("-wal") for m in moved) == 1
        and sum(m.endswith("-shm") for m in moved) == 1, moved)
K.check("no -wal or -shm is left under the old name",
        not os.path.exists(package + "-wal")
        and not os.path.exists(package + "-shm"),
        sorted(os.listdir(aside)))
stamped = [m for m in moved if m.startswith("annotation.gpkg.replaced-")
           and not m.endswith(("-wal", "-shm"))][0]
K.check("they sit beside the package under the name SQLite looks for",
        raw(os.path.join(aside, stamped + "-wal")) == b"old pages"
        and raw(os.path.join(aside, stamped + "-shm")) == b"shared", sorted(os.listdir(aside)))
panel = K.new_panel()
camp6 = K.new_campaign(panel, aside, inside)
K.check("a campaign made in the folder after it starts with none of them",
        not os.path.exists(package + "-wal")
        and not os.path.exists(package + "-shm"))
K.close_panel(panel)

print()
print("a package with no manifest, set aside by the next campaign, is no different")
orphan = os.path.join(work, "orphan")
os.makedirs(orphan)
shutil.copy(package, os.path.join(orphan, "annotation.gpkg"))
with open(os.path.join(orphan, "annotation.gpkg-wal"), "wb") as fh:
    fh.write(b"orphan pages")
panel = K.new_panel()
K.new_campaign(panel, orphan, inside)
K.close_panel(panel)
left = sorted(os.listdir(orphan))
K.check("the orphan's -wal went with it",
        any(n.startswith("annotation.gpkg.orphan-") and n.endswith("-wal")
            for n in left) and "annotation.gpkg-wal" not in left, left)

shutil.rmtree(root, ignore_errors=True)
K.finish()
