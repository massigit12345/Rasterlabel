"""docs/tutorial.md, walked in a real QGIS with no window.

tools/tutorial_walk.py does what the tutorial tells a person to do, on a
scratch copy of examples/rasterlabel_example/, through the panel of the built
file: New campaign with the four classes typed in the Classes window, Import
frames from the sample design, two readings of two frames (the second one not
seeing the first), Check, the refusal of Compare while the filter hides a
reading and then Compare, Time, the dataset card of the campaign, Export with
the card, Whole raster with the ignore value, Cutouts on the scene and the mask,
the Processing algorithm, Correct on the model's map with its classes read from
it, five strokes, Model vs corrected on the whole map and on the ground swept,
the uncertainty of band 2 and its report, and the card of the correction. Every
step carries its own checks (the labels it presses, the files it writes and
where); this suite adds what the numbers must be:

- the agreement of the two readings is between 0.9 and 1, kappa between 0.8
  and 1, over the two frames both closed, and the Processing algorithm gives
  the same numbers;
- the mask holds only the classes of the two frames, and 255 elsewhere;
- the correction changes pixels, and the whole-map agreement of the model
  with the corrected map is above that over the ground swept;
- the uncertainty report is written with its AUC;
- the pictures the tutorial shows are rendered, a PNG each, and not empty.

Needs QGIS itself (tests/run.py, NEEDS_QGIS), on Qt 5 and Qt 6 alike.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import os
import shutil
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import tutorial_walk as W  # noqa: E402
import qgiskit as K  # noqa: E402

check = K.check
print("QGIS %s" % K.QGIS_VERSION)
work = tempfile.mkdtemp(prefix="rl_tutorial_suite_")
try:
    out = W.walk(work, None)
    n = out["numbers"]
    print()
    print("what the numbers must be")
    c = n.get("compare") or {}
    check("two frames closed by both readings, inter-observer",
          c.get("frames_used") == 2 and c.get("kind") == "inter", c)
    check("the readings agree, on 0.9 to 1 of the pixels",
          0.9 < (c.get("overall") or 0) < 1.0, c.get("overall"))
    check("kappa, as an agreement statistic, between 0.8 and 1",
          0.8 < (c.get("kappa") or 0) < 1.0, c.get("kappa"))
    check("quantity and allocation add up to the disagreement",
          abs((c.get("quantity") or 0) + (c.get("allocation") or 0)
              - (1 - (c.get("overall") or 0))) < 1e-9, c)
    check("four classes have an IoU, the roof left out the lowest",
          sorted(c.get("per_class_iou") or {}) ==
          ["bare ground", "built-up", "vegetation", "water"]
          and min(c["per_class_iou"], key=lambda k: c["per_class_iou"][k][0])
          == "built-up", c.get("per_class_iou"))
    p = n.get("processing") or {}
    check("Processing gives the numbers of the panel",
          abs(p.get("OVERALL", -1) - c.get("overall", -2)) < 1e-12
          and abs(p.get("KAPPA", -1) - c.get("kappa", -2)) < 1e-12
          and p.get("FRAMES_USED") == 2, (p, c))
    mask = (n.get("mask") or {}).get("values") or {}
    check("the mask: 7 200 pixels of the classes, the rest 255, no 0",
          sum(v for k, v in mask.items() if k != 255) == 7200
          and mask.get(255) == 600 * 400 - 7200 and 0 not in mask, mask)
    check("four cutouts of two layers, from two frames",
          n.get("cutouts") == 4, n.get("cutouts"))
    whole = n.get("model_vs_corrected_whole") or {}
    swept = n.get("model_vs_corrected_swept") or {}
    check("the model agrees with the corrected map on 95 to 100 % of the "
          "whole map", 0.95 < whole.get("agree", 0) < 1.0, whole)
    check("and on much less of the ground the strokes swept",
          swept.get("agree", 1) < 0.5 < whole.get("agree", 0)
          and swept.get("pixels", 0) < whole.get("pixels", 0), (whole, swept))
    check("five strokes", n.get("operations") == 5, n.get("operations"))
    check("the strokes took pixels off the map's errors",
          n["wrong_px_after"] < n["wrong_px_before"], n)
    u = n.get("uncertainty") or {}
    check("the uncertainty report: the probability read as 1 - p, three "
          "places done, an AUC over the map above 0.7",
          u.get("kind") == "probability" and u.get("purposive_done") == 3
          and (u.get("auc_whole") or 0) > 0.7, u)
    check("six places of 256 pixels", n.get("places") == 6, n.get("places"))
    check("the menus are those the tutorial names",
          n["menu_campaign"] == ["Compare two readings…", "Time…",
                                 "Dataset card…"]
          and n["menu_correction"] == ["Model vs corrected…",
                                       "Uncertainty report…", "Time…",
                                       "Dataset card…"])
    pictures = [f for f in out["figures"] if os.path.isfile(f)]
    check("the five pictures are rendered", sorted(
        os.path.basename(f) for f in pictures) == [
            "annotated_frames.png", "compare_report.png",
            "correct_uncertainty.png", "disagreement_map.png",
            "panel_campaign.png"], out["figures"])
    def head(path):
        with open(path, "rb") as fh:
            return fh.read(8)

    check("each a PNG of some weight", all(
        os.path.getsize(f) > 4000 and head(f) == b"\x89PNG\r\n\x1a\n"
        for f in pictures))
except Exception:
    traceback.print_exc()
    check("the walk ran to its end", False)
finally:
    shutil.rmtree(work, ignore_errors=True)

K.finish()
