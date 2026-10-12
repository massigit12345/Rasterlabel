"""The recovery net after a frame is deleted, moved, placed, noted, imported or
a class is renamed, in a real QGIS: a session killed right after, and the next
one opening the campaign.

Each of these commits a whole table, and a commit takes with it every stroke
the user had pending in that table. The file on disk that the net keeps was
only rewritten by a stroke, a Save and the panel's own flush, so for as long
as nothing was drawn afterwards it still listed work that was already in the
package, and the polygons of a frame that was just deleted. A crash in that
window gave an offer "Work from an earlier session was never saved", and Put
them back drew the strokes a second time (two marks on the same ground) and
a polygon inside a frame that no longer existed.

Each case is two runs of this file. The first draws, does the thing, and is
killed the way a crash kills. The second opens the campaign and answers the
question, if there is one, with Put them back:

  delete       a stroke in each of two frames, the second frame deleted;
  move_carry   the same, the second frame moved with what is in it;
  move_drop    the same, moved and what is in it deleted;
  rename       a stroke, a class renamed across everything drawn;
  create       a note pending on a frame, a stroke, a new frame placed;
  note         the same, with a note written on another frame;
  import       the same, with frames imported from a file.

The three that commit the frames alone leave the stroke of the polygons table
pending, and rightly: the net must still hold it, and must no longer hold the
note that the commit wrote.

Needs QGIS; tests/run.py skips it where QGIS is missing and, with
RL_REQUIRE_QGIS=1, fails it.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = ("delete", "move_carry", "move_drop", "rename", "create", "note",
         "import")


def parent():
    root = tempfile.mkdtemp(prefix="rl_framenet_")
    bad = []
    try:
        for case in CASES:
            print()
            print(case)
            folder = os.path.join(root, case)
            os.makedirs(folder)
            for phase in ("draw", "open"):
                out = subprocess.run(
                    [sys.executable, os.path.abspath(__file__), case, phase,
                     folder], capture_output=True, cwd=HERE,
                    encoding="utf-8", errors="replace", timeout=600)
                text = (out.stdout or "") + (out.stderr or "")
                shown = [line for line in text.splitlines()
                         if line.startswith(("  ok", "  FAIL", "CRASH",
                                             "Traceback", "  File", "    "))
                         or "Error" in line]
                for line in shown:
                    print("  " + line if not line.startswith("  ") else line)
                if phase == "draw":
                    if "CRASH" not in text or out.returncode == 0:
                        print("  FAIL %s: the first run was not killed where "
                              "it should have been (exit %s)"
                              % (case, out.returncode))
                        print(text[-2000:])
                        bad.append("%s: draw" % case)
                        break
                    if "  FAIL" in text:
                        bad.append("%s: draw" % case)
                elif out.returncode != 0:
                    if "FAIL" not in text:
                        print(text[-2000:])
                    bad.append("%s: open" % case)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print()
    print("FAILED: %d" % len(bad) if bad else "all pass")
    for b in bad:
        print("   " + b)
    return 1 if bad else 0


# ------------------------------------------------------------- the runs
def child(case, phase, root):
    import qgiskit as K
    from qgis.core import QgsPointXY
    camp = os.path.join(root, "camp")
    package = os.path.join(camp, "annotation.gpkg")
    image = K.layer_of(K.write_image(os.path.join(root, "data", "image.tif"))
                       if phase == "draw" else
                       os.path.join(root, "data", "image.tif"))
    panel = K.new_panel()

    if phase == "draw":
        K.new_campaign(panel, camp, image, tiled=True)
        section = K.annotate(panel)
        section.autosave.setValue(0)
        section.tile_side.setValue(4.0)
        section.choose_class("mud")

        def frame(x, y):
            section.create_tile(QgsPointXY(K.X0 + x, K.Y0 - y))
            return section.current_tile_id()

        def stroke_in(tid, dx=0.5):
            section.select_tile(tid)
            bb = section.tile_geometry().boundingBox()
            section.paint(K.square(bb.xMinimum() + dx, bb.yMinimum() + 0.5,
                                   1.0))

        def tile_feature(tid):
            return [f for f in section.all_tiles() if f["tile_id"] == tid][0]

        def net_rows():
            _, rows = K.g["read_snapshot"](panel.recovery.path) \
                if os.path.exists(panel.recovery.path) else ({}, [])
            return rows

        def note_pending(tid, text="by hand"):
            """A change to a frame that waits in its buffer, and the net
            written down with it, as the next stroke does."""
            tiles = section.tile_layer
            if not tiles.isEditable():
                tiles.startEditing()
            tiles.changeAttributeValue(
                tile_feature(tid).id(), tiles.fields().indexOf("note"), text)
            panel.keep_safe()

        a = frame(5, 5)
        stroke_in(a)

        if case in ("delete", "move_carry", "move_drop"):
            b = frame(13, 5)
            stroke_in(b)
            K.check("two strokes are in the net before the frame is touched",
                    len([r for r in net_rows() if r["role"] == "polygons"])
                    == 2, net_rows())
            if case == "delete":
                K.CLICK.append("Delete tile")
                section.select_tile(b)
                section.delete_tile()
            else:
                K.CLICK.append("Move with its contents" if case == "move_carry"
                               else "Move and delete them")
                section.move_tile(tile_feature(b), 4.0, 0.0)
            K.check("everything is on disk now, and the net holds nothing",
                    not panel.pending_layers() and not net_rows(),
                    ([r for r, _ in panel.pending_layers()], net_rows()))
            print("CRASH right after the frame was touched", flush=True)
            K.hard_kill()

        if case == "rename":
            for c in panel.campaign.data["classes"]:
                if c["name"] == "mud":
                    c["name"] = "clay"
            panel.campaign.save()
            panel.rename_features()
            K.check("the renamed stroke is on disk and the net holds nothing",
                    not panel.pending_layers() and not net_rows(),
                    ([r for r, _ in panel.pending_layers()], net_rows()))
            print("CRASH right after the rename", flush=True)
            K.hard_kill()

        # the three that commit the frames alone: a note waits in the buffer
        # of the frames, and the stroke of the polygons waits in its own
        note_pending(a)
        K.check("the net holds the note and the stroke before",
                {(r["role"], r["what"]) for r in net_rows()}
                == {("polygons", "added"), ("tiles", "attrs")}, net_rows())
        if case == "create":
            frame(13, 5)
        elif case == "note":
            K.g["QInputDialog"].getText = staticmethod(
                lambda *args, **k: ("a word", True))
            section.select_tile(a)
            section.edit_note()
        elif case == "import":
            from osgeo import ogr
            drawn = os.path.join(root, "draws.gpkg")
            ds = ogr.GetDriverByName("GPKG").CreateDataSource(drawn)
            lyr = ds.CreateLayer("sample", K.UTM, ogr.wkbPoint)
            lyr.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
            one = ogr.Feature(lyr.GetLayerDefn())
            one.SetField("id", 1)
            one.SetGeometry(ogr.CreateGeometryFromWkt(
                "POINT(%r %r)" % (K.X0 + 14.0, K.Y0 - 14.0)))
            lyr.CreateFeature(one)
            ds = None
            K.g["QFileDialog"].getOpenFileName = staticmethod(
                lambda *args, **k: (drawn, ""))
            K.ANSWERS["ImportFrames"] = lambda d: 1
            section.import_tiles()
            K.check("the frame was imported", len(section.tile_ids()) == 2,
                    section.tile_ids())
        after = {(r["role"], r["what"]) for r in net_rows()}
        K.check("the net holds the stroke and no longer the note",
                after == {("polygons", "added")}, net_rows())
        print("CRASH right after the frames were committed", flush=True)
        K.hard_kill()

    # ------------------------------------------------------ the next open
    K.CLICK.append("Put them back")
    K.open_campaign(panel, camp)
    cid = panel.campaign.data["id"]
    polygons = K.find_mine(cid, "polygons")
    on_disk = K.counts(package)
    trouble = [t for k, t in K.BOXES if "not on disk yet" in t]
    K.check("what was put back is on disk", not trouble, trouble)
    K.check("no two polygons share ground", K.overlapping_pairs(polygons) == 0,
            [f.geometry().area() for f in polygons.getFeatures()])
    if case in ("create", "note", "import"):
        K.check("one offer, for the stroke alone: not for the note the "
                "commit wrote", len(K.ASKED) == 1 and "1 polygons" in K.ASKED[0]
                and "change" not in K.ASKED[0], K.ASKED)
        K.check("and the stroke is there once", on_disk["polygons"] == 1,
                on_disk)
    else:
        K.check("nothing is offered: it was all saved", not K.ASKED, K.ASKED)
    if case == "delete":
        K.check("the polygon of the frame that stayed is there once, none of "
                "the deleted one", on_disk["polygons"] == 1
                and on_disk["tiles"] == 1, on_disk)
        K.check("and not in a frame that is gone",
                {f["tile_id"] for f in polygons.getFeatures()} == {"t001"},
                [f["tile_id"] for f in polygons.getFeatures()])
    if case == "move_carry":
        K.check("both strokes, once", on_disk["polygons"] == 2
                and on_disk["tiles"] == 2, on_disk)
    if case == "move_drop":
        K.check("the stroke of the frame that stayed, once",
                on_disk["polygons"] == 1 and on_disk["tiles"] == 2, on_disk)
    if case == "rename":
        names = sorted(f["class_name"] for f in polygons.getFeatures())
        K.check("the one stroke, under the new name",
                names == ["clay"] and on_disk["polygons"] == 1,
                (names, on_disk))
    K.close_panel(panel)
    K.finish()


if __name__ == "__main__":
    if len(sys.argv) == 4:
        child(*sys.argv[1:])
    else:
        sys.exit(parent())
