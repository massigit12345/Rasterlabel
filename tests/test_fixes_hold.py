"""Faults once found in the source must not come back.

Each has a proof here. Where it can be done,
the function is taken from the source and run; where the fix is an order
between two lines, the order is what gets looked at.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_ROOT = _os.environ.get("RL_ROOT") or _os.path.dirname(_HERE)
_BUILT = _os.path.join(_ROOT, "dist", "rasterlabel.py")

import ast
import os
import sys

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
        if inside is None and getattr(node, "name", None) == name:
            return "".join(lines[node.lineno - 1:node.end_lineno])
        if isinstance(node, ast.ClassDef) and node.name == inside:
            for sub in node.body:
                if getattr(sub, "name", None) == name:
                    t = "".join(lines[sub.lineno - 1:sub.end_lineno])
                    return "\n".join(l[4:] if l.startswith("    ") else l
                                     for l in t.splitlines())
    raise AssertionError("%s not found" % name)


# --------------------------------------------------------------------------
print("nothing is read from a key that nobody writes")
bracketed = [l for l in lines if "dot_px" in l and "recipe[" in l]
check("dot_px is no longer read with the square bracket", not bracketed,
      bracketed)
check("it is read with a fallback value", 'recipe.get("dot_px", 1)' in source)

# --------------------------------------------------------------------------
print()
print("the autosave counter goes off on every road")
ra = take("reclassify_at", "AnnotationSection")
i_tick = ra.find("self.ticked()")
i_ret = ra.rfind("return True")
check("reclassify_at calls ticked before it returns",
      0 <= i_tick < i_ret, (i_tick, i_ret))
tail = ra[i_ret:].split("\n", 1)
check("and there is no code after the last return",
      len(tail) == 1 or not tail[1].strip(), ra[i_ret:][:80])

se = take("settle_edits", "AnnotationSection")
check("settle_edits arms the autosave", "self.ticked()" in se)

sv = take("save", "AnnotationSection")
check("the counter is only cleared if the save worked",
      "if not trouble:" in sv and sv.find("if not trouble:") < sv.find("self.since_save = 0"),
      sv.find("if not trouble:"))

# --------------------------------------------------------------------------
print()
print("the neighbour is read back from the layer, not from an old snapshot")
check("settle_edits reads the neighbour's geometry again",
      "lyr.getFeature(other.id())" in se)
check("and no longer uses the geometry from the previous round",
      "og = other.geometry()" not in se)

# --------------------------------------------------------------------------
print()
print("a failed cut does not delete the polygon")
rp = take("repair", "AnnotationSection")
check("repair goes through the guard",
      "self.cut_away(g, claimed, f" in rp)
check("and if the cut cannot be made, it leaves things alone",
      "if rest is None:" in rp)
check("no raw difference in repair",
      "g.difference(claimed)" not in rp)

pt = take("paint", "AnnotationSection")
check("paint under goes through the guard", "kept = self.cut_away(" in pt)
check("and does not call a failed cut 'already painted'",
      "could not be fitted under" in pt)
check("no raw difference in paint",
      "geom = geom.difference(QgsGeometry.unaryUnion(" not in pt)

# --------------------------------------------------------------------------
print()
print("a failed commit does not carry off the whole buffer")
for name, where in (("move_tile", "AnnotationSection"),
                    ("rename_features", "Panel")):
    body = take(name, where)
    if name == "move_tile":
        # the contents are carried or dropped by a helper since the carry was
        # put under the settling flag; the two together are the move
        body += take("_carry_or_drop", where)
    check("%s does not call rollBack" % name, "rollBack()" not in body,
          [l.strip() for l in body.splitlines() if "rollBack" in l])
    # the message can wrap in the middle of the sentence
    flat = " ".join(body.split())
    check("%s says the work is still waiting" % name,
          "waiting to be saved" in flat, flat[-200:])

# --------------------------------------------------------------------------
print()
print("deleting a tile: the tile first, and the commit gets looked at")
dt = take("delete_tile", "AnnotationSection")
i_tiles = dt.find("tiles.commitChanges()")
i_cont = dt.find("lyr.deleteFeatures(ids)")
check("the tile is deleted before its contents",
      0 <= i_tiles < i_cont, (i_tiles, i_cont))
check("and the tile's commit is read",
      "if not tiles.commitChanges():" in dt)
check("and the contents' one as well",
      "if not lyr.commitChanges():" in dt)
check("if the tile is not deleted, the contents are left untouched",
      dt.find("so nothing was") < i_cont, dt.find("so nothing was"))
check("the log no longer announces a success that did not happen",
      "could not be emptied" in dt)

# --------------------------------------------------------------------------
print()
print("closing the campaign: one question only, and the save is checked")
cc = take("close_campaign", "Panel")
check("it asks the layers too, not just the module",
      "or self.pending_layers():" in cc)
check("one question only", cc.count("QMessageBox.question") == 1,
      cc.count("QMessageBox.question"))
i_save = cc.find("self.section.save()")
i_close = cc.find("self.close_module(")
check("it saves before taking things apart", 0 <= i_save < i_close,
      (i_save, i_close))
check("and if something is left out it closes nothing",
      "nothing was " in cc and cc.find("return") < i_close)

# And the answer that was never obeyed. The question offers Save, Discard and
# Cancel (it offered Yes, No and Cancel then); Cancel stopped and Yes saved,
# and No fell straight through into close_module, which saves whatever the
# module is holding. So the one answer that meant "do not write this to disk"
# wrote it to disk, and nothing said so.
check("Discard is remembered",
      "discard = (q == QMessageBox.StandardButton.Discard)" in cc)
check("and Save is the default, the answer that keeps the work",
      "QMessageBox.StandardButton.Save)" in cc)
check("and obeyed: the module is told not to save",
      "self.close_module(save_first=not discard)" in cc)
check("the buffers are rolled back, because that is what was asked",
      "lyr.rollBack()" in cc)
check("and the net goes with them, or the next open offers it back",
      "self.recovery.clear()" in cc)
cm = take("close_module", "Panel")
check("close_module can be told not to save", "def close_module(self, save_first=True)" in cm)
check("and still saves by default, which is the module swap",
      "if save_first and self.section.unsaved():" in cm)
check("the check looks at both the module and the layers",
      "self.section.unsaved()) \\" in cc or "self.section.unsaved())" in cc)

# --------------------------------------------------------------------------
print()
print("a retired name is not reused")
ec = take("edit_classes", "Panel")
check("it is compared against the retired classes",
      'if c.get("retired")' in ec)
check("and refused", "Nothing was " in ec and "return" in ec)
i_check = ec.find("retired = {")
i_write = ec.find('self.campaign.data["classes"] = ')
check("the refusal comes before the manifest is written",
      0 <= i_check < i_write, (i_check, i_write))

ce = take("complaints", "ClassEditor")
check("the dialog can say what is wrong",
      "has no name" in ce and "used twice" in ce)
ac = take("accept", "ClassEditor")
check("and does not close if something is wrong",
      "self.complaints()" in ac and "super().accept()" in ac)
i_warn = ac.find("QMessageBox.warning")
i_ok = ac.find("super().accept()")
check("the warning comes before the ok", 0 <= i_warn < i_ok, (i_warn, i_ok))

# --------------------------------------------------------------------------
print()
print("the coverage is measured on the union, not on the sum")
rc = take("refresh_coverage", "AnnotationSection")
check("refresh_coverage unions", "unaryUnion" in rc)
check("and no longer adds piece by piece", "painted += a" not in rc)
check("and does not exceed the tile", "min(painted, total_area)" in rc)

mt = take("measure_tile", "AnnotationSection")
check("measure_tile counts per reading, a pass and an operator",
      "per_reading" in mt
      and "(self.pass_of(f), self.operator_of(f))" in mt)
check("it takes the fullest reading", "max(per_reading.values())" in mt)
check("it unions inside the pass", "unaryUnion" in mt)
check("and the share does not go past one", "min(painted / total, 1.0)" in mt)


# the arithmetic, actually run
class Geom(object):
    def __init__(self, a):
        self._a = float(a)
    def area(self):
        return self._a
    def isEmpty(self):
        return self._a <= 0


def union_share(piece_areas, union_area, tile_area):
    """What refresh_coverage does now: the union decides."""
    painted = union_area
    return min(painted, tile_area) / tile_area


check("two overlapping polygons do not make 150 per cent",
      abs(union_share([75.0, 75.0], 100.0, 100.0) - 1.0) < 1e-9,
      union_share([75.0, 75.0], 100.0, 100.0))
check("half a tile stays half",
      abs(union_share([30.0, 20.0], 50.0, 100.0) - 0.5) < 1e-9)
check("and a share cannot go above one",
      union_share([200.0], 200.0, 100.0) <= 1.0)

# --------------------------------------------------------------------------
print()
print("a manifest from elsewhere does not bring the program down")
rec = take("reconcile", "Campaign")
check("the grid is read with a fallback value",
      'self.data.get("grid")' in rec)
check("and a manifest with no grid is a disagreement, not an error",
      "has no grid" in rec)
check("no raw read of the grid",
      'self.data["grid"]["reference_raster"]' not in rec)

# --------------------------------------------------------------------------
print()
print("the export rewrites its own files")
wv = take("write_vectors")
check("gdal is allowed to overwrite",
      '"accessMode": "overwrite"' in wv)

# --------------------------------------------------------------------------
print()
print("a half written raster is closed before it is removed")
pw = take("paint_whole")
i_pop = pw.find("targets.pop(kind")
i_rm = pw.find("os.remove(path)")
check("the entry leaves targets before the removal",
      0 <= i_pop < i_rm, (i_pop, i_rm))
# popping the entry is not enough if the loop walks a snapshot of the items:
# the snapshot list holds every (dataset, path, driver) tuple until the loop
# ends, so the dataset stays open and Windows will not let the file go
check("and the loop does not walk a snapshot that keeps the datasets open",
      "list(targets.items())" not in pw and "for kind in list(targets):" in pw)

# --------------------------------------------------------------------------
print()
print("every tool is given back when things close")
rt = take("release_tools", "AnnotationSection")
check("the line one too", "line_tool" in rt)
check("and the latch on the vertices is lifted",
      "self.drop_vertices()" in rt)

# --------------------------------------------------------------------------
print()
print("Undo works on the table of the shape in hand")
us = take("undo_stroke", "AnnotationSection")
check("a line comes undone across two tables", '"lines", "polygons"' in us)
check("a point in its own", '"points"' in us)
check("and if there is nothing left to undo it says so",
      "nothing left to undo" in us)

# --------------------------------------------------------------------------
print()
print("the old spelling of the geometry kinds can still be found")
# first_of() looks a dotted name up in its own module's namespace. Qgis and
# QgsWkbTypes are imported there and written nowhere else in it, so a tidy-up
# that drops imports nothing refers to takes the fallback away, and the only
# sign is that the program stops working on the older QGIS it could still
# support. That is exactly what the split into a package did.
check("the built file imports QgsWkbTypes", "import" in source
      and "QgsWkbTypes" in source.split("def first_of")[0])
check("and says why it looks unused", "It has happened once" in source)
package = _os.path.join(_ROOT, "rasterlabel", "constants.py")
if _os.path.exists(package):
    names = set()
    for node in ast.parse(open(package, encoding="utf-8").read()).body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    check("the package's constants imports Qgis", "Qgis" in names, sorted(names))
    check("and QgsWkbTypes, which only a string refers to",
          "QgsWkbTypes" in names, sorted(names))

print()
print("paths are compared the way the machine compares them")
check("the correction guard uses normcase, like every other comparison",
      "here.startswith(mine + os.sep)" in source)
check("and nothing is left comparing with normpath",
      "os.path.normpath(os.path.abspath(source)).startswith" not in source)

print()
print("the recovery net records what was taken away, not only what was added")
check("deletions are read out of the buffer", "deletedFeatureIds()" in source)
check("and attribute changes too", "changedAttributeValues()" in source)
check("a feature added and deleted in the same session is not a removal",
      "never reached the file" in source)
check("a restore replays removals before the new marks",
      '"deleted": 0' in source and '"added": 3' in source)
check("and the question asked at open says what a restore will do",
      "removal%s" in source)

print()
print("a save empties the net, so nothing already on disk is offered back")
# The net was armed on every stroke and asked to look again on no other
# occasion. It removes its own file when nothing is pending, but something has
# to ask, and only a stroke ever did. So: draw, press Save, close QGIS, and the
# snapshot stayed behind describing work that was already written. The next open
# read it as an afternoon that was never saved, and saying yes made a second
# copy of every polygon in it.
sv = take("save", "AnnotationSection")
check("the annotation save asks the net to look again",
      "self.panel.keep_safe()" in sv)
i_commit = sv.find("commitChanges()")
i_net = sv.find("self.panel.keep_safe()")
check("and it asks after the commit, not before", 0 <= i_commit < i_net,
      (i_commit, i_net))
ob = take("save", "ObjectsSection")
# through the section's own keep_safe(), which every edit of a box uses
check("so does the objects save",
      ob.find("commitChanges()") < ob.find("self.keep_safe()")
      and "self.panel.keep_safe()" in take("keep_safe", "ObjectsSection"))
fl = take("flush_layers", "Panel")
check("so does a flush", "self.keep_safe()" in fl)
sd = take("shut_down")
check("and so does going away", "panel.keep_safe()" in sd)
i_close = sd.find("panel.close_module()")
i_net = sd.find("panel.keep_safe()")
check("after the module has saved what it was holding",
      0 <= i_close < i_net, (i_close, i_net))

print()
print("closing the panel puts the brush down with it")
mn = take("main")
check("something watches the dock", "visibilityChanged" in mn)
check("and it tells a closed dock from one tabbed behind another",
      "dock.isHidden()" in mn)
check("the tool is given back", "release_tools()" in mn)
check("and the arrow keys too", "removeEventFilter(keys)" in mn)
check("while the campaign is left exactly as it was",
      "Nothing was saved or lost" in mn)

print()
print("the fingerprint is of the program, not of whatever sits beside it")
bs = take("build_stamp")
check("the two shapes are told apart by __package__",
      '__package__' in bs)
check("not by counting the files in the folder",
      "if len(kin) > 1:" not in bs)
check("and the comment says why, because it was the other way once",
      "twenty earlier versions" in bs)

print()
print("the release zip cannot ship with the links unfilled")
tools = open(os.path.join(_ROOT, "tools", "package_plugin.py"),
             encoding="utf-8").read() \
    if os.path.exists(os.path.join(_ROOT, "tools", "package_plugin.py")) else ""
if tools:
    check("the builder looks for placeholders", "REPLACE-ME" in tools)
    check("and refuses", "still has placeholders" in tools)
    check("with a way through for a zip you build for yourself",
          "RL_ALLOW_PLACEHOLDERS" in tools)

print()
print("the check report says what it measured, and never more")
sh = take("_shape")
# The grid check used to read every vertex of every polygon, and reported
# ordinary brush outlines as "not on the pixel grid": a brush outline follows
# the hand and was never snapped to anything. What is placed on the grid is the
# frame, and a frame off it offsets every cutout taken from it for good.
check("the grid is measured on the frames", 'find_mine(campaign.data.get("id", ""), "tiles")' in sh)
check("and an off-grid frame is a defect, not a note",
      '"%d frame%s not on the pixel grid"' in sh)
check("the brush outlines are not measured against it any more",
      '"%d polygon%s not on the pixel grid"' not in source)
check("and the report says where the exactness really is",
      "burned on the campaign grid at export" in sh)
check("a coordinate that is not a number does not end the check",
      "except (ValueError, OverflowError, ZeroDivisionError)" in sh)
check("and a count found in part of a campaign is called a floor",
      "a floor, not a total" in sh)
check("the ceilings are named rather than written twice",
      "MANY_FRAMES" in source and "MANY_PAIRS" in source
      and "MANY_FEATURES" in source)
ac = take("about_the_campaign")
check("a grid that is not an object is reported, not tripped over",
      "the grid is not an object" in ac)
check("a reference raster that is a service is not called missing",
      "is a service, not a file" in ac)
check("an unreadable package does not silence the rest of the report",
      "if not readable:" in ac and "_pending(campaign)" in ac)
cf = take("_closed_flags")
check("the closed column is actually checked, as the README says",
      "disagrees with the drawing" in cf)
pe = take("_pending")
check("the session's own live snapshot is not called an orphan",
      "mine" in pe and "snapshots_waiting(campaign.folder, mine" in pe)
ck = take("check")
check("and an hourglass while it reads", "WaitCursor" in ck)

print()
print("a file that could not be removed is not reported as removed")
un = take("undo", "CutoutsSection")
i_read = un.find("f.readlines()")
i_rm = un.find("os.remove(p)")
check("the manifest is read before anything is deleted",
      0 <= i_read < i_rm, (i_read, i_rm))
check("a refusal is collected", "refused.append" in un)
check("and said out loud", "not be removed and are still on disk" in un)
# The manifest is read in one place now, manifest_rows(), for the count, the
# names in use and the cutouts whose files are gone.
ce = take("count_existing", "CutoutsSection")
mr = take("read_manifest", "CutoutsSection")
check("a manifest that is not UTF-8 does not lock the module out",
      "errors=\"replace\"" in mr and "except Exception" in mr
      and "except Exception" in ce and "self.manifest_rows()" in ce)

print()
print("a legend change that could not be written changes nothing")
fr = take("finish_rename", "AnnotationSection")
check("the old name is put back on a failed save", 'c["name"] = was' in fr)
check("and the panel is rebuilt from it", "rebuild_class_buttons()" in fr)

print()
print("the builder can see every way a name is bound")
bd = open(os.path.join(_ROOT, "tools", "bundle.py"), encoding="utf-8").read() \
    if os.path.exists(os.path.join(_ROOT, "tools", "bundle.py")) else ""
if bd:
    check("tuple unpacking at the top level counts", "ast.walk(t)" in bd)
    check("and a name bound inside a top level try",
          "ast.Store" in bd)

print()
print("a picture with no coordinate system can actually be annotated")
# The first sentence of the README says any raster QGIS can open, georeferenced
# or not. project_rasters defaults to need_crs=True and the raster selector and
# New campaign both took the default, so a photograph never appeared in the list
# and New campaign returned without opening a window. The New dialog had handled
# that case all along, down to saying "no coordinate system" and proposing to
# work free of frames. The feature was written, documented and unreachable.
rr = take("refresh_rasters", "Panel")
check("the raster selector asks for them", "project_rasters(need_crs=False)" in rr)
nc = take("new_campaign", "Panel")
check("and so does New campaign", "project_rasters(need_crs=False)" in nc)
check("which now says what to load instead of doing nothing",
      "georeferenced or not" in nc)
oc = take("open_correction", "Panel")
check("a correction too", "project_rasters(need_crs=False)" in oc)
pl = take("pick_layers", "CutoutsSection")
check("and the cutouts layer picker", "project_rasters(need_crs=False)" in pl)

print()
print("a manifest the program has just complained about does not then crash it")
dc = take("describe_campaign", "Panel")
check("the grid is read with a default", 'd.get("grid")' in dc)
check("and so is everything else", 'd.get("name"' in dc and 'g.get("crs")' in dc)
check("no bare subscript is left", 'd["grid"]' not in dc and 'g["crs"]' not in dc)

print()
print("a GeoPackage that is gone is a loss, not an empty campaign")
op = take("open", "Campaign")
check("whether it was there is noticed before it is made",
      "was_there = os.path.exists" in op)
check("and said out loud", "one you drew" in op)

print()
print("Retire asks first, because the marks leave the map when it is pressed")
rt = take("retire", "ClassEditor")
check("it asks", "run_dialog(ask)" in rt)
check("and says what it will look like", "stop being drawn on the map" in rt)
check("with a button named for what it does", '"Retire"' in rt)
check("Cancel means nothing happens",
      0 < rt.find("if ask.clickedButton() is not go") < rt.find("self.rows.pop()"))

print()
print("an export does not quietly go out without the last ten minutes")
ev = take("export_vectors", "Panel")
check("it asks the layers too", "or self.pending_layers():" in ev)
check("and checks that the save actually took", "self.flush_layers()" in ev)
check("and asks before writing something that is not what is on screen",
      "Export anyway?" in ev)

print()
print("the teardown finishes even when the canvas has already gone")
sd2 = take("shut_down")
check("the canvas is reached inside a guard", "watched = (canvas()" in sd2)
check("and the rest still runs", "for w in watched:" in sd2)

print()
print("a suggested name is one the program will actually accept")
sg = take("suggest", "OpenCorrection")
check("the comparison is made in the form the name is stored in",
      'tidy("correction %d" % n' in sg)
check("and the reason is written down", "the program rejected it" in sg)

print()
print("the export tooltip describes the export")
check("it no longer claims the frames come out whole",
      "The frames themselves are written whole either way" not in source)
check("it says every table is narrowed to the one frame",
      "the\nframes table included" in source
      or "frames table included" in source)

print()
print("the two open questions are written down as decisions")
meta = open(os.path.join(_ROOT, "rasterlabel", "metadata.txt"),
            encoding="utf-8").read() \
    if os.path.exists(os.path.join(_ROOT, "rasterlabel", "metadata.txt")) else ""
if meta:
    flat = meta.replace("\r\n", "\n")
    check("Qt6 is declared, and the file says the site ignores it",
          "is no longer\n# recognised, so it has no effect" in flat)
    check("and it no longer claims a QGIS 3 build refuses a plugin without it",
          "refuses a plugin that does not declare" not in meta)
    check("and it is declared once", meta.count("\nsupportsQt6=True") == 1)
    check("the version floor says what it means",
          "the version somebody is told the plugin" in meta)
    import configparser as _ini
    _c = _ini.ConfigParser()
    _c.read_string(meta)
    check("and the file is still a valid ini after all that",
          _c.get("general", "version") and _c.get("general", "qgisMinimumVersion"))
    # QGIS 4 is Qt 6, and the code runs on Qt 5 and Qt 6 alike. The ceiling is
    # what QGIS 4 and the plugin site read to decide that, so it is pinned
    # here, not left to taste: left out, it would default to 3.99.
    check("QGIS 4 is let in by the maximum version",
          _c.get("general", "qgisMaximumVersion", fallback="") == "4.99")
    check("and the file says why the same code runs on both",
          "Every Qt enumeration here is written in that full" in meta)
    check("supportsQt6 is read as true",
          _c.getboolean("general", "supportsQt6", fallback=False))

print()
print("a name quoted for a QGIS expression survives a backslash")
_q = {}
exec(take("sql_text"), _q)
# inside a QGIS string a backslash escapes the next character, so a name that
# ends in one used to swallow the closing quote and break the whole filter
check("the backslash is doubled", _q["sql_text"]("t001\\") == "'t001\\\\'",
      _q["sql_text"]("t001\\"))
check("before the quote is, so the two do not interfere",
      _q["sql_text"]("a\\'b") == "'a\\\\''b'", _q["sql_text"]("a\\'b"))
check("and an ordinary name is only wrapped",
      _q["sql_text"]("t001") == "'t001'")

print()
print("Correct paints with the map's classes, never with the legend")
# The legend is what Annotate and Objects draw with. Correct used it for its
# chips, its palette, Ctrl and click and its log, and wrote the legend's codes
# into a model's map that was numbered another way. test_correct_classes runs
# the module; this pins down that the legend has not crept back in.
_cs = [n for n in tree.body if isinstance(n, ast.ClassDef)
       and n.name == "CorrectionSection"]
_body = "".join(lines[_cs[0].lineno - 1:_cs[0].end_lineno]) if _cs else ""
check("CorrectionSection does not read the campaign legend",
      _body and "active_classes()" not in _body
      and 'campaign.data["classes"]' not in _body)
check("it does not borrow the legend's current_code or current_colour",
      'AnnotationSection.__dict__["current_code"]' not in _body
      and 'AnnotationSection.__dict__["current_colour"]' not in _body)
check("its classes live in its record",
      'self.record.setdefault("classes", [])' in _body)
# The layer is handed to start_correction, which reads the classes with its
# style before the correction is made the open one; the module is then built
# on classes already confirmed, and needs no layer of its own.
_sc = take("start_correction", "Panel")
check("and a new correction is handed the layer, for its style",
      "return self.start_correction(book, layer)" in source
      and "thematic_classes(" in _sc and "layer = layer_reading(source)" in _sc)
_rc = take("report_codes", "CorrectionSection")
check("the codes are no longer counted in 256 bins of one byte",
      "GetHistogram" not in _rc and "255.5" not in _rc)
# The colour table of a band belongs to it. It was kept past the closing of
# the file, every entry read from it failed, and a map with a table and no
# style got palette colours instead of its own (in real QGIS: the error was
# swallowed; it could as well have read freed memory).
_tc = take("thematic_classes")
check("the colour table of the map is copied before the file is closed",
      "GetColorTable()" in _tc and ".Clone()" in _tc)

# Two QGIS on one campaign: the README promised the GeoPackage would refuse
# the second writer. It does not, both saves succeed, and the work of one
# can overwrite or duplicate the other's. What it says now is the rule.
_readme_path = os.path.join(_ROOT, "README.md")
if os.path.exists(_readme_path):
    _readme = " ".join(open(_readme_path, encoding="utf-8").read().split())
    check("the README no longer promises the package refuses a second writer",
          "refusing to be written" not in _readme)
    check("it says a campaign is open in one QGIS at a time",
          "must be open in one QGIS at a time" in _readme)
    check("and that the GeoPackage does not refuse the second",
          "the GeoPackage does not refuse it" in _readme)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
