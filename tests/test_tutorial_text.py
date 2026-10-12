"""docs/tutorial.md says what the program says.

The tutorial writes every button, window part and menu entry in bold. This
suite holds that to the source: each label in bold is a label of the package
(or of QGIS itself, or one of the standard buttons of Qt, which are named
below, so a new one has to be named on purpose), the way a menu is written
(Measure ▸ Compare two readings…) is read part by part, and what else the page
points to is there:

- every picture of docs/img is shown on the page, every picture the page shows
  is there, and none is big (the repository is cloned by everyone);
- every table of contents link goes to a heading;
- every file the page names under tools/, tests/, examples/ or docs/ exists,
  and so does every file of the example that it names;
- the Processing call is the algorithm's own: each key of its dictionary is a
  parameter rasterlabel:agreement registers;
- no path of anybody's machine, no name of a tool that is not the program's
  own, no later version.

It reads text only, so it needs nothing but Python. The windows themselves
are walked by tests/test_tutorial_walk.py, which needs QGIS.
"""
import scratch_home  # a home of its own, before anything else: see scratch_home.py
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("RL_ROOT") or os.path.dirname(HERE)

fails = []
# the labels have arrows and ellipses in them, and a console of Windows writes
# cp1252: what the suite prints must not stop it
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name +
          (("   " + str(detail)[:600]) if not cond and detail != "" else ""))
    if not cond:
        fails.append(name)


def text_of(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


# Labels that are QGIS's own, written in bold as the person meets them there.
QGIS_OWN = {"Plugins", "Manage and Install Plugins", "Install from ZIP",
            "Install Plugin", "Layer", "Add Layer", "Add Raster Layer",
            "Raster", "RasterLabel", "Processing Toolbox"}
# Qt's standard buttons: the program asks for them by name, not by a word.
QT_BUTTONS = {"Ok", "Cancel", "Close"}

package = os.path.join(ROOT, "rasterlabel")
source = "\n".join(text_of("rasterlabel", n) for n in sorted(os.listdir(package))
                   if n.endswith(".py"))
# two string literals next to each other are one string: a label cut over two
# lines of the source is still one label
source = re.sub(r'"\s*\n\s*"', "", source)
source = re.sub(r"'\s*\n\s*'", "", source)

page = text_of("docs", "tutorial.md")
prose = re.sub(r"```.*?```", "", page, flags=re.S)


def in_source(label):
    if len(label) >= 8 or " " in label:
        return label in source
    return re.search(r"[\"'>]\s*%s\s*[\"'<:]" % re.escape(label), source) \
        is not None


print("every label in bold is the program's")
labels = []
for m in re.finditer(r"\*\*(.+?)\*\*", prose, re.S):
    words = re.sub(r"\s+", " ", m.group(1)).strip()
    if words:
        labels.append(words)
parts = sorted({p.strip() for w in labels for p in w.split(" ▸ ")})
check("the page has labels in bold: %d, %d of them different"
      % (len(labels), len(parts)), len(parts) > 80, len(parts))
missing = [p for p in parts if p not in QGIS_OWN and p not in QT_BUTTONS
           and not in_source(p)]
check("each is in the package, or named here as QGIS's or Qt's", not missing,
      missing)
print()
print("the menus the page writes are the ones the registries hold")
measure = text_of("rasterlabel", "measure.py")
menu_entries = set(re.findall(r'\("[a-z_]+", "([^"]+…)"', measure))
used = {w.split(" ▸ ")[1] for w in labels
        if w.startswith("Measure ▸ ") and " ▸ " in w}
check("Measure ▸ <entry>: every entry is one of the two menus",
      used <= menu_entries, sorted(used - menu_entries))
check("and the four entries of a correction are all named on the page",
      {"Model vs corrected…", "Uncertainty report…", "Time…",
       "Dataset card…"} <= {p for p in parts})

print()
print("the pictures")
img = os.path.join(ROOT, "docs", "img")
shown = re.findall(r"!\[[^\]]*\]\((img/[^)]+)\)", page)
there = sorted(os.listdir(img)) if os.path.isdir(img) else []
check("every picture on the page is in docs/img",
      all(os.path.isfile(os.path.join(ROOT, "docs", p)) for p in shown),
      shown)
check("every picture of docs/img is on the page",
      sorted("img/" + n for n in there) == sorted(set(shown)),
      (there, shown))
check("at least the four the tutorial promises: the panel, the compare "
      "report, the disagreement map, Correct with the uncertainty card",
      {"panel_campaign.png", "compare_report.png", "disagreement_map.png",
       "correct_uncertainty.png"} <= set(there), there)
sizes = {n: os.path.getsize(os.path.join(img, n)) for n in there}
check("none is over 120 kB, and together they are under 600 kB",
      all(v < 120 * 1024 for v in sizes.values())
      and sum(sizes.values()) < 600 * 1024, sizes)


def head(path):
    with open(path, "rb") as fh:
        return fh.read(8)


check("each is a PNG", all(head(os.path.join(img, n)) == b"\x89PNG\r\n\x1a\n"
                           for n in there))

print()
print("the contents, and what the page points to")


def slug(heading):
    s = heading.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s", "-", s)


headings = {slug(h) for h in re.findall(r"^#+\s+(.+)$", prose, re.M)}
links = re.findall(r"\]\(#([^)]+)\)", prose)
check("every link of the contents goes to a heading",
      links and all(l in headings for l in links),
      [l for l in links if l not in headings])
steps = re.findall(r"^## (\d+)\. ", prose, re.M)
check("the steps are numbered 1 to 17 in order",
      steps == [str(i) for i in range(1, 18)], steps)
named = set(re.findall(r"`((?:tools|tests|examples|docs)/[A-Za-z0-9_./-]+)`",
                       page))
check("every file under tools/, tests/, examples/ or docs/ the page names is "
      "there", all(os.path.exists(os.path.join(ROOT, n)) for n in named),
      [n for n in named if not os.path.exists(os.path.join(ROOT, n))])
for name in ("scene_rgb.tif", "model_map.tif", "model_map.tif.aux.xml",
             "model_map.qml", "sample_design.gpkg", "classes.csv"):
    check("the example file %s is named, and is in the example" % name,
          "`%s`" % name in page and os.path.isfile(os.path.join(
              ROOT, "examples", "rasterlabel_example", name)))
check("the commands of the generator and of the walk are given",
      "python tools/make_example.py" in page
      and "tools/tutorial_walk.py" in page)

print()
print("the Processing call is the algorithm's")
provider = text_of("rasterlabel", "processing_provider.py")
# Only the agreement algorithm's own class: the provider holds the other
# measures too, and their parameters are not the call's.
_start = provider.find("class AgreementAlgorithm")
_end = provider.find("\n    class ", _start + 1)
if _start >= 0:
    provider = provider[_start:_end if _end > 0 else None]
call = re.search(r'processing\.run\("([^"]+)", \{(.*?)\n\}\)', page, re.S)
check("the page calls rasterlabel:agreement", call is not None
      and call.group(1) == "rasterlabel:agreement")
if call:
    keys = re.findall(r'^\s+"([A-Z_]+)":', call.group(2), re.M)
    registered = re.findall(r'(?:Parameter\w+\(\s*)"([A-Z_]+)"', provider)
    check("every key of the dictionary is a parameter of the algorithm",
          keys and set(keys) <= set(registered),
          (keys, registered))
    check("and every parameter is given, none left to a default by "
          "accident", set(registered) <= set(keys),
          sorted(set(registered) - set(keys)))
    outputs = re.findall(r'out\["([A-Z_]+)"\]', page)
    names = set(re.findall(r'"([A-Z_]+)", "[A-Z][^"]*"\)\)', provider)) \
        | set(re.findall(r'\("([A-Z_]+)", "[A-Z]', provider))
    check("the outputs it reads are outputs of the algorithm",
          outputs and set(outputs) <= names, (outputs, sorted(names)))

print()
print("the steps can be followed as written (the walk does the same)")
walk = text_of("tools", "tutorial_walk.py")
step4 = " ".join(page[page.index("## 4. Import the frames"):page.index("## 5.")]
                 .split())
check("step 4 takes the Tiles tool before it looks for tile side",
      "**Tiles**" in step4 and step4.index("**Tiles**")
      < step4.index("**tile side**"), step4[:300])
check("and the walk takes it too", "b_tiles.click()" in walk
      and "row_tile.isHidden()" in walk)
step13 = page[page.index("## 13. Correct the model's map"):]
step13 = " ".join(step13.split())
check("step 13 does not tell the reader to press Correct to open what New "
      "has opened", "Press **Correct**" not in step13
      and "Correct is open already" in step13)
check("and the walk checks Correct is open after New",
      "Correct is open already after New" in walk)
step9 = " ".join(page[page.index("## 9. Export"):page.index("## 10.")].split())
step10 = page[page.index("## 10. The whole raster"):page.index("## 11.")]
check("step 9 names the files of the reading that is left, and of one chosen",
      "example_card.md" in step9 and "example_ANNA_p1.gpkg" in step9)
step10 = " ".join(step10.split())
check("step 10 says to untick the painted image and to tick the card",
      "untick **the image with the annotation on it**" in step10
      and "tick **the dataset card" in step10, step10[:400])
check("and lists the style and statistics files the mask comes with",
      "_mask.qml" in step10 and "_mask.tif.aux.xml" in step10)
check("the walk does both, and checks the files",
      'd.want["painted"].setChecked(False)' in walk
      and "_mask.tif.aux.xml" in walk and "export_one_files" in walk)

print()
print("nothing that should not be there")
personal = re.compile("|".join([r"[A-Za-z]:" + r"[\\/]+" + "Users",
                                "/" + "home" + "/[^/\\s\"']",
                                "/" + "Users" + "/[^/\\s\"']"]))
check("no path of anybody's machine", not personal.search(page))
check("no commit trailer", "Co-Authored" not in page)
check("no later version, no promise of one", not re.search(
    r"next release|future version|upcoming|coming soon|v?1\.[2-9]\.\d|"
    r"version 1\.[2-9]", prose, re.I))
check("the version named is 1.1", "rasterlabel-1.1.zip" in page)
check("LF line ends, one newline at the end", "\r" not in page
      and page.endswith("\n") and not page.endswith("\n\n"))

print()
print("FAILED: %d" % len(fails) if fails else "all pass")
for f in fails:
    print("   " + f)
sys.exit(1 if fails else 0)
