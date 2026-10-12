"""The campaign helpers every measuring feature reads through.

One definition of a closed frame, one of who is hidden from whom, one way to
name a pair of readings, and one way to read a campaign without writing to
it. Agreement, the card, Time and the ignore value all lean on these, so
they are checked here once, on real GeoPackages:

- reading_shares on the shared two-reader campaign of tests/fixtures/impact:
  t001 read whole by ANNA and BRUNO, t002 left at 81 % by BRUNO, t003
  touched by ANNA only; and on a campaign of the awkward cases: overlapping
  polygons of one reading counted once, a polygon past the frame clipped,
  "Massi" with no pass the same reading as "MASSI" in pass 1, a second pass
  a reading of its own, a frame nobody painted;
- reading_closed, strictly above CLOSED_SHARE;
- the hidden_from truth table, comparison_kind, reading_tag and pair_tag;
- campaign_read_only and frame_design leave the package's bytes and mtime
  as they were, and leave no journal file of SQLite beside it;
- frame_design on a package without the design columns, after the open
  adds them (every row kept), and with a frame that carries a design;
- the manifest: no "journal" block, not at create() and not added to an
  old manifest by a save: a block saying "on" before journal.csv is written
  would have Time count the days since as days of no work. The block is
  written by the journal's wiring alone, when the first row is;
- build_changes with its defaults writes the record of changes as before,
  and with other words writes another record on the same grid.

The code is lifted out of the built file, as written.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import ast
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "fixtures"))
import impact  # noqa: E402

ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
SRC = os.environ.get("RL_SRC") or os.path.join(ROOT, "dist", "rasterlabel.py")
source = io.open(SRC, encoding="utf-8").read()
tree = ast.parse(source)
lines = source.splitlines(True)

fails = []


def check(name, cond, detail=""):
    cond = bool(cond)
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)) if not cond else ""))
    if not cond:
        fails.append(name)


WANTED = {
    "CLOSED_SHARE", "DESIGN_FIELDS", "DESIGN_TILE_COLUMNS", "TABLES",
    "JOURNAL_NAME", "JOURNAL_VERSION", "OPERATOR_BLANK", "FLAG_BAND_NAME",
    "REVIEWED_MEANING", "STRIP_ROWS", "PICTURE_GRID",
    "operator_word", "pass_number", "reading_label", "readings_in",
    "reading_choices", "READING_TABLES", "tidy", "now", "long_path",
    "reading_tag", "pair_tag", "comparison_kind", "hidden_from",
    "campaign_read_only", "_package_read", "_field_of", "_sql_list",
    "_area_of_union", "_clipped", "reading_shares", "reading_closed",
    "frame_design", "manifest_journal", "Campaign",
    "build_changes", "_there", "_move", "_drop", "_quiet_gdal",
    "_loud_gdal", "temporary_name", "pixel_grid", "has_grid", "open_raster"}
pieces, found = [], set()
for node in tree.body:
    name = getattr(node, "name", None)
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        name = node.targets[0].id
    if name in WANTED and name not in found:
        found.add(name)
        pieces.append("".join(lines[node.lineno - 1:node.end_lineno]))
assert found == WANTED, sorted(WANTED - found)
said = []
SRS = osr.SpatialReference()
SRS.ImportFromEPSG(32633)
g = {"os": os, "re": re, "json": json, "np": np, "gdal": gdal, "ogr": ogr,
     "osr": osr, "datetime": datetime, "timezone": timezone,
     "log": lambda m, loud=False: said.append(str(m)),
     "spatial_reference": lambda crs: SRS}
exec("\n".join(pieces), g)

root = tempfile.mkdtemp(prefix="rl_campaign_helpers_")
ANNA, BRUNO = impact.ANNA, impact.BRUNO


def fingerprint(path):
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    return digest, os.stat(path).st_mtime_ns


def near_dict(got, want, tol=1e-9):
    if set(got) != set(want):
        return False
    return all(abs(got[k] - want[k]) <= tol for k in want)


try:
    # ---------------------------------------------------------- shares
    print("reading_shares on the shared two-reader campaign")
    shared = os.path.join(root, "shared")
    package = impact.make_shared_campaign(shared)
    shares = g["reading_shares"](package)
    want = impact.SHARED_VALUES["shares"]
    check("every frame is there", set(shares) == {"t001", "t002", "t003"},
          sorted(shares))
    for tid in sorted(want):
        check("%s: %s" % (tid, ", ".join(
            "%s %.0f %%" % (g["reading_label"](r), 100 * s)
            for r, s in sorted(want[tid].items()))),
              near_dict(shares.get(tid, {}), want[tid]), shares.get(tid))
    closed = g["reading_closed"](shares)
    check("closed: t001 by both, t002 by ANNA only, t003 by nobody",
          closed == impact.SHARED_VALUES["closed"], closed)
    check("one frame's shares give the set of that frame",
          g["reading_closed"](shares["t002"]) == {ANNA})
    check("tile_ids narrows the answer",
          set(g["reading_shares"](package, ["t002"])) == {"t002"})
    check("a frame asked for and not there is not invented",
          g["reading_shares"](package, ["t999"]) == {})
    check("a package that is not there gives nothing, and does not raise",
          g["reading_shares"](os.path.join(root, "none.gpkg")) == {})
    check("CLOSED_SHARE is 0.995", g["CLOSED_SHARE"] == 0.995)
    check("strictly above: 0.995 is open, 0.9951 closed",
          g["reading_closed"]({ANNA: 0.995, BRUNO: 0.9951}) == {BRUNO})

    print()
    print("reading_shares on the awkward cases")
    grid = impact.GRID_CARD
    box = lambda c0, r0, c1, r1: impact.px_box(grid, c0, r0, c1, r1)
    frames = [("t001", box(0, 0, 10, 10), False),
              ("t002", box(0, 0, 10, 10), False)]
    odd = os.path.join(root, "odd")
    package2 = impact.make_campaign(odd, grid, [frames[0]], [
        # two overlapping halves of one reading: 60 % once, not 100 %
        ("polygons", ("ANNA", 1), 1, box(0, 0, 6, 10), "t001"),
        ("polygons", ("ANNA", 1), 1, box(0, 0, 6, 10), "t001"),
        # past the frame on the right: only the part inside counts
        ("polygons", ("BRUNO", 1), 2, box(5, 0, 25, 10), "t001"),
        # "Massi" with no pass is MASSI in pass 1
        ("polygons", ("Massi", None), 1, box(0, 0, 2, 10), "t001"),
        ("polygons", ("MASSI", 1), 1, box(2, 0, 3, 10), "t001"),
        # the same person in pass 2 is a reading of its own
        ("polygons", ("ANNA", 2), 1, box(0, 0, 10, 10), "t001"),
        # a polygon of another frame's tile_id is that frame's
        ("polygons", ("ANNA", 1), 1, box(0, 0, 10, 10), "t777"),
    ])
    s2 = g["reading_shares"](package2)
    check("only the frames of the tiles table", set(s2) == {"t001"}, s2)
    check("overlapping polygons of one reading count once: 0.6",
          abs(s2["t001"][("ANNA", 1)] - 0.6) < 1e-9, s2["t001"])
    check("a polygon past the frame is clipped to it: 0.5",
          abs(s2["t001"][("BRUNO", 1)] - 0.5) < 1e-9)
    check("Massi with no pass and MASSI in pass 1 are one reading: 0.3",
          abs(s2["t001"].get(("MASSI", 1), 0) - 0.3) < 1e-9, s2["t001"])
    check("pass 2 is a reading of its own, and closes the frame",
          abs(s2["t001"][("ANNA", 2)] - 1.0) < 1e-9
          and g["reading_closed"](s2["t001"]) == {("ANNA", 2)})
    empty = os.path.join(root, "empty")
    package3 = impact.make_campaign(empty, grid, [frames[0]], [])
    check("a frame nobody painted is there, with nobody in it",
          g["reading_shares"](package3) == {"t001": {}})

    # ---------------------------------------------------------- who sees
    print()
    print("hidden_from, the two clauses of apply_filter")
    hf = g["hidden_from"]
    check("reader ANNA 1, only mine, blind: BRUNO 1 hidden, ANNA 1 not",
          hf(("ANNA", 1), ("BRUNO", 1), True, True)
          and not hf(("ANNA", 1), ("ANNA", 1), True, True))
    check("reader ANNA 2, everyone, blind: ANNA 1 hidden, BRUNO 2 not",
          hf(("ANNA", 2), ("ANNA", 1), False, True)
          and not hf(("ANNA", 2), ("BRUNO", 2), False, True))
    check("reader ANNA 1, everyone, blind: only pass 1 is in sight, so her "
          "pass 2 is hidden and BRUNO's pass 1 is not",
          not hf(("ANNA", 1), ("BRUNO", 1), False, True)
          and hf(("ANNA", 1), ("ANNA", 2), False, True))
    check("reader ANNA 3, only mine, not blind: BRUNO 3 hidden, ANNA 1 not",
          hf(("ANNA", 3), ("BRUNO", 3), True, False)
          and not hf(("ANNA", 3), ("ANNA", 1), True, False))
    check("the operator is read the way the marks are: ' anna ' is ANNA",
          not hf((" anna ", 1), ("ANNA", None), True, True))
    check("nothing hidden when neither box is ticked",
          not hf(("ANNA", 2), ("BRUNO", 1), False, False))

    print()
    print("comparison_kind, reading_tag and pair_tag")
    ck = g["comparison_kind"]
    check("one person, two passes: intra", ck(("ANNA", 1), ("ANNA", 2))
          == "intra")
    check("two people, one pass: inter", ck(("ANNA", 1), ("BRUNO", 1))
          == "inter")
    check("both different: other", ck(("ANNA", 1), ("BRUNO", 2)) == "other")
    check("spelt as the marks are: Massi with no pass and MASSI 2 is intra",
          ck(("Massi", None), ("MASSI", 2)) == "intra")
    check("reading_tag ANNA_p1", g["reading_tag"](("ANNA", 1)) == "ANNA_p1")
    check("pair_tag ANNA_p1_vs_BRUNO_p1",
          g["pair_tag"](ANNA, BRUNO) == "ANNA_p1_vs_BRUNO_p1")
    choices = g["reading_choices"]({("ANNA B", 1): 3, ("ZOE", 2): 1})
    check("the same tag as the export windows give a reading",
          all(g["reading_tag"](c["readings"][0]) == c["tag"]
              for c in choices if c["mode"] == "one"),
          [(c["tag"], c["readings"]) for c in choices])

    # ---------------------------------------------------------- read only
    print()
    print("campaign_read_only writes nothing")
    before = fingerprint(package)
    time.sleep(0.05)
    data, ds = g["campaign_read_only"](shared)
    check("the manifest comes back as it is on disk", data == json.load(
        io.open(os.path.join(shared, "campaign.json"), encoding="utf-8")))
    check("and the package open", ds is not None
          and ds.GetLayerByName("tiles") is not None)
    s_ds = g["reading_shares"](ds)
    check("reading_shares reads an open datasource the same as a path",
          all(near_dict(s_ds[t], shares[t]) for t in shares))
    g["frame_design"](ds)
    g["readings_in"](package)
    ds = None
    check("the package's bytes and mtime are unchanged",
          fingerprint(package) == before)
    check("and no journal of SQLite was left beside it",
          not [f for f in os.listdir(shared)
               if f.endswith(("-wal", "-shm", "-journal"))],
          os.listdir(shared))
    gone = os.path.join(root, "no_package")
    os.makedirs(gone)
    shutil.copy(os.path.join(shared, "campaign.json"), gone)
    data, ds = g["campaign_read_only"](gone)
    check("no package: None, and none is made",
          ds is None and not os.path.exists(os.path.join(gone,
                                                         "annotation.gpkg")))

    # ---------------------------------------------------------- design
    print()
    print("frame_design, before and after the columns are there")
    old_schema = [(t, k, [f for f in fields if f[0] not in g["DESIGN_FIELDS"]])
                  for t, k, fields in g["TABLES"]]
    check("the tiles table of TABLES carries the five design columns",
          [f[0] for f in g["TABLES"][0][2]][-5:] == list(g["DESIGN_FIELDS"]))
    olddir = os.path.join(root, "old")
    old_pkg = impact.make_campaign(olddir, grid, [frames[0]], [
        ("polygons", ANNA, 1, box(0, 0, 10, 10), "t001")], schema=old_schema)
    before = fingerprint(old_pkg)
    check("an older package: {}", g["frame_design"](old_pkg) == {})
    check("and reading it changed nothing", fingerprint(old_pkg) == before)
    camp = g["Campaign"](olddir)
    added = camp.prepare_package(None)
    check("the open adds the five columns, and only them",
          sorted(added) == sorted("tiles.%s" % f for f in g["DESIGN_FIELDS"]),
          added)
    probe = ogr.Open(old_pkg)
    tiles = probe.GetLayerByName("tiles")
    check("every row is kept, as it was",
          tiles.GetFeatureCount() == 1
          and tiles.GetNextFeature().GetField("tile_id") == "t001")
    tiles = probe = None
    check("five empty columns are no design: still {}",
          g["frame_design"](old_pkg) == {})
    edit = ogr.Open(old_pkg, 1)
    tiles = edit.GetLayerByName("tiles")
    f = tiles.GetNextFeature()
    f.SetField("sample_id", "S017")
    f.SetField("stratum", "olive")
    f.SetField("incl_prob", 0.02)
    f.SetField("weight", 50.0)
    tiles.SetFeature(f)
    f = tiles = edit = None
    design = g["frame_design"](old_pkg)
    check("a frame with a design is given back as it is",
          design == {"t001": {"sample_id": "S017", "stratum": "olive",
                              "incl_prob": 0.02, "weight": 50.0,
                              "design": None}}, design)

    # ---------------------------------------------------------- manifest
    print()
    print("the manifest's journal")
    legacy = os.path.join(root, "legacy")
    os.makedirs(legacy)
    old_data = {"program": "RasterLabel", "version": "1.0", "id": "a1b2c3",
                "name": "legacy", "classes": [], "grid": {"crs": ""},
                "tiles": [], "cutouts": [], "corrections": []}
    camp = g["Campaign"](legacy)
    camp.data = dict(old_data)
    camp.save()
    back = json.load(io.open(os.path.join(legacy, "campaign.json"),
                             encoding="utf-8"))
    check("an old manifest gains no journal block on its first save",
          "journal" not in back, back.get("journal"))
    check("nothing of it changed but the modified stamp",
          {k: v for k, v in back.items() if k != "modified"} == old_data)
    camp.data = back
    camp.save()
    again = json.load(io.open(os.path.join(legacy, "campaign.json"),
                              encoding="utf-8"))
    check("nor on the next", "journal" not in again)
    check("the block of a given moment, kept for when the journal is "
          "written", g["manifest_journal"](
              datetime(2026, 10, 8, 17, 30, 5, 123, tzinfo=timezone.utc))
          == {"on": True, "file": "journal.csv", "version": 1,
              "since": "2026-10-08T17:30:05Z"})

    def created_keys(cls_name):
        """The keys of the manifest dict a create() writes, from its code."""
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == cls_name:
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef) and sub.name == "create":
                        for d in ast.walk(sub):
                            if isinstance(d, ast.Dict) and any(
                                    isinstance(k, ast.Constant)
                                    and k.value == "program" for k in d.keys):
                                return {k.value for k in d.keys
                                        if isinstance(k, ast.Constant)}
        return set()
    campaign_keys = created_keys("Campaign")
    correction_keys = created_keys("CorrectionCampaign")
    check("the manifest of a new campaign is found in the code",
          {"program", "classes"} <= campaign_keys, campaign_keys)
    check("and of a new correction", {"program", "classes"} <= correction_keys,
          correction_keys)
    check("a new campaign says nothing of a journal",
          "journal" not in campaign_keys, campaign_keys)
    check("a new correction says nothing of a journal",
          "journal" not in correction_keys, correction_keys)
    # The block is written by the journal's wiring alone (ui_time), at the
    # first row really written or when the switch in Annotate's settings is
    # used, never by create() or a save: test_time_report_run drives that.
    parts = re.split(r"^# -{69}\n# ---- (\w+) -+\n# -{69}\n", source,
                     flags=re.M)
    callers = sorted({parts[i] for i in range(1, len(parts) - 1, 2)
                      if "manifest_journal(" in parts[i + 1]})
    check("manifest_journal() is called only where journal.csv is begun "
          "(campaign defines it, ui_time calls it)",
          callers == ["campaign", "ui_time"], callers)

    # ---------------------------------------------------------- changes
    print()
    print("build_changes: the same record by default, other words on demand")
    like = os.path.join(root, "copy.tif")
    ds = gdal.GetDriverByName("GTiff").Create(like, 6, 4, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((500000.0, 1.0, 0.0, 4140010.0, 0.0, -1.0))
    ds.SetProjection(SRS.ExportToWkt())
    ds = None
    out = os.path.join(root, "copy_changes.tif")
    g["build_changes"](like, out)
    rd = gdal.Open(out)
    band = rd.GetRasterBand(1)
    check("the band is still called corrected",
          band.GetDescription() == "corrected")
    check("and says what a 1 means, as before",
          band.GetMetadataItem("MEANING") == "1 a person changed this pixel "
          "in Correct, 0 it is as the map arrived")
    check("the ones are magenta", tuple(band.GetColorTable()
                                        .GetColorEntry(1)) == (255, 0, 255, 255))
    check("on the grid of the copy", rd.GetGeoTransform()
          == (500000.0, 1.0, 0.0, 4140010.0, 0.0, -1.0))
    band = rd = None
    other = os.path.join(root, "copy_reviewed.tif")
    g["build_changes"](like, other, name="reviewed",
                       meaning=g["REVIEWED_MEANING"], colour=(0, 128, 255, 255))
    rd = gdal.Open(other)
    band = rd.GetRasterBand(1)
    check("with other words: the band, its meaning and its colour",
          band.GetDescription() == "reviewed"
          and band.GetMetadataItem("MEANING") == g["REVIEWED_MEANING"]
          # a GeoTIFF palette keeps no alpha: the colour is what is said
          and tuple(band.GetColorTable().GetColorEntry(1))[:3]
          == (0, 128, 255))
    band = rd = None
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef)
          and n.name == "build_changes"][0]
    check("the new arguments are keywords after flags, defaults in place",
          [a.arg for a in fn.args.args] == ["like", "destination", "flags",
                                            "name", "meaning", "colour"]
          and isinstance(fn.args.defaults[1], ast.Name)
          and fn.args.defaults[1].id == "FLAG_BAND_NAME")
finally:
    shutil.rmtree(root, ignore_errors=True)

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
