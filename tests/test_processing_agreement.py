"""rasterlabel:agreement in a real QGIS Processing.

The plugin's initProcessing puts RasterLabel in the toolbox, and the
algorithm "Agreement between two readings" runs on the shared two-reader
campaign of tests/fixtures/impact.py through processing.run, as Model
Designer, batch mode and a script call it:

- the provider registers, once however often it is asked, and the plugin's
  unload takes it away again;
- with an unfinished reading and ALLOW_UNFINISHED off, the run is refused
  with a QgsProcessingException that names the frames;
- allowed, it gives OVERALL 0.8, KAPPA 0.6154 and FRAMES_USED 1, the maps,
  the GeoPackage, summary.json, and the styles of the vector layers;
- with no OUTPUT_FOLDER the report goes under the campaign's
  reports/agreement/, and with one it goes there;
- the campaign is only read: the GeoPackage's bytes and time are as they
  were, and campaign.json too, which Processing never writes;
- a reader the panel has blinded to one of the readings is refused, with
  the panel's own words.

Needs QGIS itself (tests/run.py, NEEDS_QGIS), on Qt 5 and Qt 6 alike.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import io
import json
import os
import shutil
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROFILE = tempfile.mkdtemp(prefix="rl_processing_profile_")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = PROFILE
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(HERE, "fixtures"))

fails = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)[:600]) if not cond and detail != "" else ""),
          flush=True)
    if not cond:
        fails.append(name)


def finish():
    print()
    print("FAILED: %d" % len(fails) if fails else "all pass", flush=True)
    for f in fails:
        print("   " + f)
    sys.stdout.flush()
    os._exit(1 if fails else 0)


try:
    import qgis
    from qgis.core import (Qgis, QgsApplication, QgsProcessingException,
                           QgsProcessingFeedback)
    from qgis.PyQt.QtCore import QSettings
except ImportError as e:
    print("QGIS is not importable here: %s" % e)
    sys.exit(1)

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                  PROFILE)
app = QgsApplication([], False)
app.initQgis()
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(qgis.__file__))), "plugins"))
import processing                                                  # noqa: E402
from processing.core.Processing import Processing                  # noqa: E402
Processing.initialize()
import impact as F                                                 # noqa: E402
print("QGIS %s" % Qgis.QGIS_VERSION)

root = tempfile.mkdtemp(prefix="rl_processing_agreement_")
folder = os.path.join(root, "aragona")
package = F.make_shared_campaign(folder)
manifest = os.path.join(folder, "campaign.json")


def state():
    out = []
    for path in (package, manifest):
        with open(path, "rb") as fh:
            out += [fh.read(), os.path.getmtime(path)]
    return tuple(out)


before = state()

print("the provider")
import rasterlabel                                                 # noqa: E402
from rasterlabel import processing_provider as PP                  # noqa: E402
plugin = rasterlabel.classFactory(None)
plugin.initProcessing()
registry = QgsApplication.processingRegistry()
provider = registry.providerById("rasterlabel")
check("the plugin puts RasterLabel in the toolbox", provider is not None)
alg = registry.algorithmById("rasterlabel:agreement")
check("with the algorithm Agreement between two readings",
      alg is not None and alg.displayName() ==
      "Agreement between two readings")
plugin.initProcessing()
PP.processing_register()
check("asked again, it is still the one provider",
      registry.providerById("rasterlabel") is provider
      and len([p for p in registry.providers() if p.id() == "rasterlabel"])
      == 1)
names = [p.name() for p in alg.parameterDefinitions()] if alg else []
check("its parameters", names == ["CAMPAIGN", "READING_A", "READING_B",
                                  "FRAMES", "POINTS_IN", "RESAMPLES", "SEED",
                                  "ALLOW_UNFINISHED", "OUTPUT_FOLDER"], names)
outs = sorted(o.name() for o in alg.outputDefinitions()) if alg else []
check("its outputs, the numbers among them, for Model Designer",
      {"DISAGREEMENT", "PAIRS", "VECTORS", "SUMMARY", "OVERALL", "KAPPA",
       "QUANTITY", "ALLOCATION", "MEAN_IOU", "FRAMES_USED"} <= set(outs),
      outs)


class Feedback(QgsProcessingFeedback):
    said = []

    def reportError(self, error, fatalError=False):  # noqa: N802
        self.said.append(error)

    def pushInfo(self, info):  # noqa: N802
        self.said.append(info)


def run(**extra):
    params = {"CAMPAIGN": manifest, "READING_A": "ANNA,1",
              "READING_B": "BRUNO,1", "FRAMES": 0, "POINTS_IN": False,
              "RESAMPLES": 200, "SEED": 1, "ALLOW_UNFINISHED": False}
    params.update(extra)
    return processing.run("rasterlabel:agreement", params,
                          feedback=Feedback())


print()
print("an unfinished reading")
raised = None
try:
    run()
except QgsProcessingException as err:
    raised = str(err)
except Exception as err:
    raised = "not a QgsProcessingException: %r" % err
said = (raised or "") + " " + " ".join(Feedback.said)
check("is refused with a QgsProcessingException",
      raised is not None and not raised.startswith("not a"), raised)
check("naming the frames", "t002" in said and "BRUNO, pass 1" in said, said)
check("and saying how to go on all the same", "ALLOW_UNFINISHED" in said,
      said)
check("nothing was written", not os.path.isdir(os.path.join(folder,
                                                            "reports")))

print()
print("allowed")
out = run(ALLOW_UNFINISHED=True)
check("OVERALL 0.8", abs(out["OVERALL"] - 0.8) < 1e-9, out.get("OVERALL"))
check("KAPPA 0.6154", abs(out["KAPPA"] - 0.6154) < 1e-4, out.get("KAPPA"))
check("QUANTITY 0.2, ALLOCATION 0", abs(out["QUANTITY"] - 0.2) < 1e-9
      and abs(out["ALLOCATION"]) < 1e-9)
check("MEAN_IOU 2/3", abs(out["MEAN_IOU"] - 2 / 3.0) < 1e-9)
check("FRAMES_USED 1", out["FRAMES_USED"] == 1, out.get("FRAMES_USED"))
report = out.get("OUTPUT_FOLDER") or ""
check("under the campaign's reports/agreement/",
      os.path.dirname(report) == os.path.join(folder, "reports",
                                              "agreement")
      and os.path.basename(report).startswith("ANNA_p1_vs_BRUNO_p1_"),
      report)
check("the maps and the summary are there",
      all(os.path.isfile(out[k].split("|")[0]) for k in
          ("DISAGREEMENT", "PAIRS", "VECTORS", "SUMMARY")), out)
stem = os.path.splitext(out["VECTORS"].split("|")[0])[0]
check("the styles of the vector layers, written by QGIS",
      os.path.isfile(stem + "_polygons.qml")
      and os.path.isfile(stem + "_frames.qml"))

print()
print("named by its folder, as the other four algorithms are")
campaign_param = alg.parameterDefinition("CAMPAIGN")
check("the parameter accepts the folder", campaign_param.checkValueIsAcceptable(
    folder), folder)
check("and campaign.json", campaign_param.checkValueIsAcceptable(manifest))
check("and the help says the campaign is named by its folder or its "
      "campaign.json", "named by its folder or by its campaign.json"
      in alg.shortHelpString())
by_folder = run(CAMPAIGN=folder, ALLOW_UNFINISHED=True)
check("the folder runs and gives the same numbers",
      abs(by_folder["OVERALL"] - out["OVERALL"]) < 1e-12
      and by_folder["FRAMES_USED"] == out["FRAMES_USED"], by_folder)
with io.open(out["SUMMARY"], encoding="utf-8") as fh:
    summary = json.load(fh)
check("summary.json: version 1.1, the readings, the seed",
      summary["version"] == "1.1"
      and summary["axes"] == {"A": "ANNA, pass 1", "B": "BRUNO, pass 1"}
      and summary["parameters"]["seed"] == 1, summary.get("axes"))
mine = os.path.join(root, "elsewhere", "pair_report")
out2 = run(ALLOW_UNFINISHED=True, FRAMES=1, OUTPUT_FOLDER=mine)
check("with OUTPUT_FOLDER, the report goes there",
      os.path.normcase(out2["OUTPUT_FOLDER"]) == os.path.normcase(mine)
      and os.path.isfile(os.path.join(mine, "summary.json")),
      out2.get("OUTPUT_FOLDER"))
check("touched by both: two frames", out2["FRAMES_USED"] == 2)
check("the campaign is only read: the GeoPackage and the manifest are as "
      "they were", state() == before)

print()
print("a blinded reader")


class Panel(object):
    class campaign(object):
        data = {"id": "0123456789ab"}

    def blind_gate(self, readings):
        return "BRUNO is drawing pass 1 with one operator at a time on."


from rasterlabel import launch                                     # noqa: E402
launch._RASTERLABEL = (None, None, Panel())
raised = None
try:
    run(ALLOW_UNFINISHED=True)
except QgsProcessingException as err:
    raised = str(err)
said = (raised or "") + " " + " ".join(Feedback.said)
check("is refused, in the panel's words",
      raised is not None and "one operator at a time" in said, said)
launch._RASTERLABEL = None

print()
print("unloaded")
plugin.unload()
check("the plugin's unload takes the provider away",
      registry.providerById("rasterlabel") is None)

shutil.rmtree(root, ignore_errors=True)
finish()
