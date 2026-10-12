"""The recovery net on the worst day, in a real QGIS: a session killed, and
the next one opening the campaign.

Each case is two runs of this file. The first draws and is killed the way a
crash kills, at a chosen moment: no clean up, nothing flushed that was not
already. The second opens the campaign as a person would and answers the
question about unsaved work. What was wrong, each case:

  not now: "Not now" renamed the file to .restored, which is never offered
  again, while Check went on saying everything was on disk. Not now now
  leaves the file to be asked about at the next open, Discard is what
  retires it, and Check lists every file set aside;
  autosave: an autosave started by a stroke ran before the net was written,
  and a crash inside it, after the stroke's removals had reached the
  package, lost a polygon that had been saved;
  between tables: a crash after the polygons were committed and before the
  points left the polygons in the net as well, and Put them back drew them
  a second time;
  half a commit: a crash after the removals of a commit and before its
  additions, and Put them back deleted again what was already gone, which
  left the table refusing every save from then on.

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
CASES = ("notnow", "autosave", "between", "partial")


def parent():
    root = tempfile.mkdtemp(prefix="rl_recovery_")
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
    camp = os.path.join(root, "camp")
    image = K.layer_of(K.write_image(os.path.join(root, "data", "image.tif"))
                       if phase == "draw" else
                       os.path.join(root, "data", "image.tif"))
    panel = K.new_panel()
    x, y = K.X0 + 2.0, K.Y0 - 18.0
    if phase == "draw":
        K.new_campaign(panel, camp, image)
        section = K.annotate(panel)
        section.choose_class("mud")
        if case == "notnow":
            section.autosave.setValue(0)
            for i in range(3):
                section.paint(K.square(x + 2 * i, y, 1.0))
            print("CRASH with three polygons in the net", flush=True)
            K.hard_kill()
        if case == "autosave":
            section.autosave.setValue(2)
            section.paint(K.square(x, y, 1.0))            # A
            section.paint(K.square(x + 3, y, 1.0))        # B, autosaved
            section.paint(K.square(x + 10, y, 1.0))       # C, in the net
            polygons = section.layer("polygons")

            def boom(*a):
                print("CRASH in the autosave, the removals committed",
                      flush=True)
                K.hard_kill()
            polygons.committedFeaturesRemoved.connect(boom)
            # across A and B, so the stroke joins them: A takes the whole
            # outline, B is removed, and the autosave of this stroke dies half
            # way, with the removal committed and A's new outline not
            section.paint(K.square(x + 0.5, y + 0.5, 3.0))
        if case == "between":
            section.autosave.setValue(0)
            section.paint(K.square(x, y, 1.0))
            section.paint(K.square(x + 3, y, 1.0))
            section.drop_point(K.point(x + 6, y + 0.5))
            points = section.layer("points")

            def boom(*a, **k):
                print("CRASH after the polygons were committed, before the "
                      "points", flush=True)
                K.hard_kill()
            points.commitChanges = boom
            section.save()
        if case == "partial":
            section.autosave.setValue(0)
            section.paint(K.square(x, y, 1.0))
            section.paint(K.square(x + 3, y, 1.0))
            section.save()
            section.paint(K.square(x + 0.5, y + 0.5, 3.0))   # joins the two
            polygons = section.layer("polygons")

            def boom(*a):
                print("CRASH after the removals of the commit, before the "
                      "additions", flush=True)
                K.hard_kill()
            polygons.committedFeaturesRemoved.connect(boom)
            section.save()
        print("the run was not killed", flush=True)
        os._exit(0)

    # ------------------------------------------------------ the next open
    package = os.path.join(camp, "annotation.gpkg")
    net = os.path.join(camp, "recovery")

    def files(ending):
        try:
            return sorted(f for f in os.listdir(net) if f.endswith(ending)
                          or ending in f)
        except OSError:
            return []

    def armed():
        return sorted(f for f in os.listdir(net) if f.endswith(".jsonl"))

    if case == "notnow":
        K.CLICK.append("Not now")
        K.open_campaign(panel, camp)
        K.check("the question was asked", len(K.ASKED) == 1, K.ASKED)
        K.check("it says Not now asks again", "asked again" in
                (K.ASKED[-1] if K.ASKED else ""), K.ASKED[-1:])
        K.check("Not now leaves the file as it was", len(armed()) == 1,
                os.listdir(net))
        K.check("and renames nothing", not files(".restored")
                and not files(".discarded"), os.listdir(net))
        pending = K.g["_pending"](panel.campaign)
        K.check("Check says a recovery file is waiting",
                any("recovery file" in f.what for f in pending),
                [f.what for f in pending])
        K.check("and not that everything is on disk",
                not any("everything drawn is on disk" in f.what
                        for f in pending), [f.what for f in pending])
        panel.close_campaign()
        K.CLICK.append("Not now")
        K.open_campaign(panel, camp)
        K.check("the next open asks again", len(K.ASKED) == 2, K.ASKED)
        K.check("nothing was put back", K.counts(package)["polygons"] == 0,
                K.counts(package))
        panel.close_campaign()
        K.CLICK.append("Discard")
        K.open_campaign(panel, camp)
        K.check("asked a third time, and discarded", len(K.ASKED) == 3,
                K.ASKED)
        K.check("Discard keeps the file, renamed .discarded",
                not armed() and len(files(".discarded")) == 1,
                os.listdir(net))
        pending = K.g["_pending"](panel.campaign)
        said = [(f.what, f.detail) for f in pending]
        K.check("Check lists the discarded file",
                any("set aside" in w and "discarded" in w
                    for w, _ in said), said)
        gone = files(".discarded")
        K.check("by name", gone and any(gone[0] in d for _, d in said), said)
        K.check("and does not say everything is on disk",
                not any("everything drawn is on disk" in w for w, _ in said),
                said)
        panel.close_campaign()
        K.open_campaign(panel, camp)
        K.check("a discarded file is not offered again", len(K.ASKED) == 3,
                K.ASKED)
        K.check("and the package still holds nothing of it",
                K.counts(package)["polygons"] == 0, K.counts(package))
        K.close_panel(panel)
        K.finish()

    K.CLICK.append("Put them back")
    K.open_campaign(panel, camp)
    K.check("the question was asked", len(K.ASKED) == 1, (K.ASKED, K.BOXES))
    cid = panel.campaign.data["id"]
    polygons = K.find_mine(cid, "polygons")
    areas = sorted(round(f.geometry().area(), 3)
                   for f in polygons.getFeatures())
    on_disk = K.counts(package)
    trouble = [t for k, t in K.BOXES if "not on disk yet" in t]
    K.check("what was put back is on disk", not trouble, trouble)
    K.check("no table is left holding work it cannot save",
            not panel.pending_layers(),
            [(r, l.commitErrors()) for r, l in panel.pending_layers()])
    K.check("no two polygons share ground", K.overlapping_pairs(polygons) == 0,
            areas)
    if case == "autosave":
        K.check("A and B joined by the stroke, and C: none lost",
                areas == [1.0, 10.5] and on_disk["polygons"] == 2,
                (areas, on_disk))
    if case == "between":
        K.check("the two polygons once, not twice",
                areas == [1.0, 1.0] and on_disk["polygons"] == 2,
                (areas, on_disk))
        K.check("and the point that never reached the disk is back",
                on_disk["points"] == 1, on_disk)
    if case == "partial":
        K.check("one polygon, the joined one",
                areas == [10.5] and on_disk["polygons"] == 1,
                (areas, on_disk))
    # and drawing goes on, and saves
    section = K.annotate(panel)
    section.choose_class("water")
    section.paint(K.square(x + 20, y, 1.0))
    del K.SAID[:]
    section.save()
    K.check("a save after the restore works",
            not any("not everything could be saved" in s for s in K.SAID)
            and K.counts(package)["polygons"] == on_disk["polygons"] + 1,
            (K.SAID, K.counts(package)))
    text, problems, notes = K.check_report(panel.campaign)
    K.check("Check finds no problem", problems == 0,
            [line for line in text.splitlines() if "PROBLEM" in line])
    K.check("and lists the file the work was put back from",
            "set aside" in text and ".restored" in text,
            [line for line in text.splitlines() if "recovery" in line])
    K.close_panel(panel)
    K.finish()


if __name__ == "__main__":
    if len(sys.argv) == 4:
        child(*sys.argv[1:])
    else:
        sys.exit(parent())
