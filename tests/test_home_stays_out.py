"""Nothing the tutorial's workflow writes carries the home folder.

The README says the manifests, the exports with their sidecars, the reports,
the dataset cards and the Cutouts dataset can be zipped and sent without the
name of whoever made them. This runs the whole workflow of the tutorial
(tools/tutorial_walk.py: a campaign, Import frames, two readings, Check,
Compare, Time, the card, Export, Whole raster, Cutouts, Processing, Correct,
Model vs corrected, Uncertainty, the card of the correction) in a folder under
the home folder of this run, so that every path it meets is one that could
spell it, and then reads every file it wrote, as bytes, for the home folder in
each of its spellings: as it is, with slashes the other way, with the
backslashes doubled as JSON writes them, in any case, and as a file: link.

Two files used to hold it, campaign.json (the path of the sample design,
designs[].source) and cutouts/layers.json (the grid and every layer).

Needs QGIS itself (tests/run.py, NEEDS_QGIS).
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import json
import os
import shutil
import sys
import tempfile
import traceback
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import tutorial_walk as W  # noqa: E402
import qgiskit as K  # noqa: E402

check = K.check
print("QGIS %s" % K.QGIS_VERSION)
home = os.path.expanduser("~")


def spellings(path):
    """The ways a path turns up in a file, in lower case."""
    forward = path.replace("\\", "/")
    forms = {path, forward, path.replace("/", "\\"),
             path.replace("\\", "\\\\"), "file:///" + forward.lstrip("/"),
             "file:///" + quote(forward.lstrip("/"))}
    return {f.lower().encode("utf-8") for f in forms}


def files_with_home(folder):
    """(files read, the relative names of those that spell the home)."""
    forms, seen, found = spellings(home), 0, []
    for where, _, names in os.walk(folder):
        for name in names:
            path = os.path.join(where, name)
            try:
                with open(path, "rb") as fh:
                    body = fh.read().lower()
            except OSError:
                continue
            seen += 1
            if any(f in body for f in forms):
                found.append(os.path.relpath(path, folder))
    return seen, sorted(found)


print("the scan sees the home in every spelling")
probe = tempfile.mkdtemp(prefix="rl_probe_")
try:
    for i, form in enumerate(sorted(spellings(home))):
        with open(os.path.join(probe, "f%d.txt" % i), "wb") as fh:
            fh.write(b"x " + form.upper() + b" y")
    seen, found = files_with_home(probe)
    # A home with no backslash in it, as on Linux, has fewer distinct
    # spellings than a Windows one (the doubled-backslash form is the plain
    # one there): every one planted must be found, however many there are.
    check("each spelling is found, in any case",
          seen == len(found) == len(spellings(home)) >= 3, (seen, found))
    with open(os.path.join(probe, "clean.txt"), "wb") as fh:
        fh.write(b"~/maps/a.tif ../data/a.tif")
    check("and a file with ~ and ways is not", "clean.txt" not in
          files_with_home(probe)[1])
finally:
    shutil.rmtree(probe, ignore_errors=True)

print()
print("the tutorial, walked in a folder under the home")
work = tempfile.mkdtemp(prefix="rl_home_walk_", dir=home)
try:
    W.walk(work, None)
    seen, found = files_with_home(work)
    check("a whole workflow was written: more than fifty files", seen > 50,
          seen)
    check("no file of it spells the home folder", not found, found)

    def book(*parts):
        with open(os.path.join(work, *parts), encoding="utf-8") as fh:
            return json.load(fh)

    camp = book("campaign", "campaign.json")
    check("the sample design is named by its way from the campaign",
          [d["source"] for d in camp["designs"]]
          == ["../rasterlabel_example/sample_design.gpkg"],
          [d.get("source") for d in camp.get("designs") or []])
    layers = book("cutouts", "layers.json")
    check("the layers of the Cutouts folder, and its grid, by their way "
          "from it",
          layers["grid"] == "../rasterlabel_example/scene_rgb.tif"
          and all(not os.path.isabs(e["source"]) for e in layers["layers"]),
          layers)
    corr = [os.path.join(where, "correction.json")
            for where, _, names in os.walk(work) if "correction.json" in names]
    check("a correction.json was written", len(corr) == 1, corr)
except Exception:
    traceback.print_exc()
    check("the walk ran to its end", False)
finally:
    shutil.rmtree(work, ignore_errors=True)

K.finish()
