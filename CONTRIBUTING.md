# Contributing

Everybody who takes part is asked to follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## The one rule about the shape of the code

`dist/rasterlabel.py` is **built, not written**. It is the package under
`rasterlabel/` folded into one file by `tools/bundle.py`, because the two-line
console paste is how most people use this program and keeping two copies of
tens of thousands of lines would mean keeping two programs.

So: edit the modules, then run

```
python3 tools/bundle.py
```

and commit both. `python3 tools/bundle.py --check` says whether the file in `dist`
still matches the package, and the test run does that check for you.

Two things the builder enforces, and they are worth knowing before you move code
between modules:

- **The import order is a promise.** `ORDER` in `tools/bundle.py` is the order the
  modules are concatenated in, and no module may need a name from one that comes
  after it. The package has the same property, which is why `import rasterlabel`
  cannot deadlock.
- **One flat namespace holds one of everything.** After the concatenation every
  top-level name lives together, so two modules may not both define `set_aside`.
  The builder refuses to build if they do, rather than silently letting whichever
  came last win. This is the one real cost of the arrangement, and it is a cheap
  one: it means every top-level name in the program is unique, which is not a bad
  property to have anyway.

## Running the tests

On Ubuntu or Debian, with the packages the build server installs
(`.github/workflows/tests.yml`):

```
sudo apt install python3-pyqt5 python3-numpy python3-shapely \
    python3-pyflakes python3-gdal
python3 tests/run.py
```

That is Qt 5. For the same suites on Qt 6, see
[On Qt 6 and QGIS 4](#on-qt-6-and-qgis-4).

A current Ubuntu or Debian refuses `pip install` into the system Python, and
the GDAL bindings have to match the GDAL on the machine, so apt is the way
there. `pip install PyQt5 pyflakes numpy shapely` is for inside a virtual
environment, or on an older distribution, with the GDAL bindings still taken
from the system's own packages.

No QGIS needed for most of them. They fake the parts of QGIS they use, which
is what lets them run on a build server; those in `NEEDS_QGIS` hand values to
the real QGIS classes and are skipped where QGIS is not importable. The suites in `NEEDS_GDAL`, at the top of `tests/run.py`, use real GDAL and
real GeoPackages and are skipped, loudly, if the bindings are missing; the GDAL bindings are compiled
against one Python version, so `tests/run.py` goes looking for an interpreter that
has them rather than failing for a reason that has nothing to do with the program.

To run one suite:

```
python3 tests/run.py vertices
python3 tests/test_vertices.py         # for the full output
```

### On Windows

`python3` is not a command on Windows, or is only the shortcut to the Store.
The launcher is `py`: wherever this file says `python3`, type `py -3.12`
instead, for the tools as for the tests. The same runner does the same thing:

```
py -3.12 -m pip install PyQt5 pyflakes numpy shapely
py -3.12 tests/run.py
```

That runs the suites that need neither GDAL nor QGIS. The runner
puts its suites in UTF-8 mode itself, so a console that is not UTF-8 needs
nothing set.

The GDAL suites (NEEDS_GDAL in `tests/run.py`) are skipped there, because the GDAL
bindings for Windows are not on pip, and so are the ones in NEEDS_QGIS,
which need QGIS itself. The ones that are
already on the machine are inside QGIS, and QGIS ships a launcher,
`python-qgis.bat`, that starts its own Python with them on the path.
`tests/run.py` does not go looking for it, so start the runner itself through
it, from PowerShell in the repository folder, after `py -3.12 tests/run.py`
has rebuilt `dist/`:

```
$r = (Get-Location).Path
$env:RL_ROOT = $r
$env:RL_SRC = "$r\dist\rasterlabel.py"
$env:PYTHONPATH = $r
$env:QT_QPA_PLATFORM = 'offscreen'
$env:QT_QPA_FONTDIR = 'C:\Windows\Fonts'
$env:PYTHONNOUSERSITE = '1'
& 'C:\Program Files\QGIS 3.36.0\bin\python-qgis.bat' tests\run.py --no-build `
    --require-gdal --require-qgis
```

That runs every suite, the GDAL and QGIS ones included, inside that QGIS.
To run only some, name them after `tests\run.py` as on any other machine.

Use the folder of whichever QGIS is installed: `QGIS 3.44.15\bin\python-qgis-ltr.bat`
for the long-term release, `QGIS 4.2.3\bin\python-qgis.bat` for QGIS 4, which
runs the same suites on PyQt6. These are the variables `tests/run.py` sets for
every suite it starts: where the repository is, the built file the suites read,
and an offscreen Qt that measures text with real fonts. `PYTHONNOUSERSITE` is
the one it does not: it keeps out the packages installed for your own Python,
whose PyQt5 would otherwise be found before the one QGIS ships. On QGIS 3.44
that stops the start with a sip that does not match, and on QGIS 4 it is how
the suites end up on PyQt6, the binding QGIS 4 itself runs on, rather than on
a PyQt5 that QGIS 4 never uses.

`test_dialogs_narrow` opens the windows of the measures at 300 pixels twice,
with the fonts of the machine and with DejaVu, the font Ubuntu and Debian draw
with. It looks for DejaVu in the folder named by `RL_DEJAVU_DIR`, or by
`--fonts DIR`, or in `/usr/share/fonts/truetype/dejavu`, and where there is none
it skips that half and says so in capital letters, because a run that skipped
it proved nothing about Linux. On Windows, a folder with `DejaVuSans.ttf` in it
is inside QGIS, in the `matplotlib\mpl-data\fonts\ttf` folder of its Python
(under `apps\Python3xx\Lib\site-packages`), or can be copied out of the
`qgis/qgis` Docker image with
`docker run --rm -v <folder>:/out qgis/qgis:4.2.3-trixie cp -r /usr/share/fonts/truetype/dejavu /out/`.

The Python inside QGIS has no pyflakes, so `test_static_checks` then skips
its pyflakes part, says so, and runs the rest. Run one QGIS at a time: the
suites that start a real QGIS are slow enough without a second one beside
them.

With more than one QGIS installed, `py -3.12 tests/test_cross_qgis.py` (any
Python will do) checks that a project travels between them: each QGIS in
turn, through its own `python-qgis` launcher under Program Files, saves a
QGIS project with a campaign and a correction open, and every QGIS opens a
copy of each and works on in it. It prints which saved in which reopened
fine. `RL_QGIS_PYTHONS` names the launchers instead, separated by `;`, and
`tests/run.py` runs it where it finds two and skips it where it does not.

### On Qt 6 and QGIS 4

The same code runs on QGIS 3 (Qt 5) and QGIS 4 (Qt 6), and the suites run on
both bindings. `tests/qtbinding.py` decides which: PyQt5 when it is installed,
PyQt6 otherwise, or the one asked for with `tests/run.py --qt 6` (or `RL_QT=6`
in the environment). On Ubuntu 24.04 `sudo apt install python3-pyqt6` is
enough for that.

QGIS 4 itself is easiest to reach in its official Docker image, which has
Python, PyQt6, numpy and GDAL, and lacks only shapely, pyflakes and git. This
is what the build server's second job does, from the repository folder:

```
docker run --rm -e DEBIAN_FRONTEND=noninteractive -v "$PWD:/src:ro" \
  qgis/qgis:4.2.3-trixie bash -c '
  apt-get update -qq &&
  apt-get install -y -qq --no-install-recommends python3-shapely \
      python3-pyflakes git >/dev/null &&
  cp -r /src /work && cd /work &&
  git config --global --add safe.directory "*" &&
  python3 tools/bundle.py --check && python3 tools/package_plugin.py &&
  QT_QPA_PLATFORM=offscreen python3 tests/run.py --no-build --require-gdal \
      --require-qgis'
```

The `-trixie` tag is the Debian 13 build of the image; the plain `4.2.3` is
Ubuntu 25.10, which is past its end of life, so its `apt-get` will stop
working. Inside the image `tests/run.py` finds PyQt6 and says so on its first
line, and the GDAL suites and the one that needs QGIS run too. The image is
Linux; on Windows, QGIS 4 runs the same suites through its own
`python-qgis.bat`, as [On Windows](#on-windows) shows.

Three rules keep the code on both Qt versions, and `tests/test_static_checks.py`
enforces all three:

- every Qt enumeration member by its full name: `Qt.MouseButton.LeftButton`,
  `QMessageBox.StandardButton.Yes`, `Qt.Key.Key_Escape`, never the short
  `Qt.LeftButton` that only PyQt5 reads;
- every Qt import from `qgis.PyQt`, never from `PyQt5` or `PyQt6` by name
  (the suites, which run without QGIS, take theirs from `tests/qtbinding.py`);
- dialogs through `compat.run_dialog()`, never `exec_()`, which PyQt6 removed.

One more rule, for QGIS rather than for Qt: a message level is
`LEVEL_INFO`, `LEVEL_WARNING` and the like from `constants.py`, never a bare
number, because PyQt6 refuses an int where QGIS wants a `Qgis.MessageLevel`.
And what `first_of()` or `first_attr()` finds is compared with `None`, never
taken as true or false: the first member of an enumeration is often worth 0,
and `first_of(...) or 0` once threw `Qgis.MessageLevel.Info` away for a bare
0. The static checks refuse both, and `tests/test_message_levels.py` hands each
level to a real QGIS message bar.

## What a change needs

**A test that would have failed before it.** Not a test that exercises the new
code: a test that fails on the old code and passes on the new one. The suites are
written to say *why* a check exists, in prose, next to it. `tests/test_fixes_hold.py`
is the model: every defect that was ever found and fixed has a check in it, so the
fix cannot quietly come undone.

**The tutorial follows the program.** A change to a label, a window or a file
name that `docs/tutorial.md` shows is a change to the page, and
`tests/test_tutorial_text.py` and `tests/test_tutorial_walk.py` say which.

**Reasoning in the code, not in a wiki.** This program explains itself next to
itself. A comment that says what the line does is noise; a comment that says what
went wrong before the line looked like that is the most valuable thing in the
file. Several of the comments here are small postmortems, and they are there
because the same mistake was nearly made twice.

**Plain prose.** No em-dashes: a comma, a colon, or two sentences. No guillemets.
Prose, in comments and docstrings as in these documents, wraps at about 80
characters; code may run longer where breaking it would read worse, and no line
of Python in `rasterlabel/` or `tools/` goes past 99. `rasterlabel/metadata.txt`
is the exception: QGIS reads each key from one line, so `description` and
`tags` stay on one line however long they get.

**`pyflakes` says nothing.** `python3 -m pyflakes rasterlabel tools` prints
no line at all. `QgsWkbTypes` in `rasterlabel/constants.py` is used by name,
through `first_of()`, which asks this QGIS whether it still has the old
spelling of the geometry types; pyflakes cannot see a name read that way, so
the module names it once more in `_LOOKED_UP_BY_NAME`, where it can.
`tests/test_static_checks.py` runs pyflakes over the built
`dist/rasterlabel.py`, which holds every module, and keeps a list of the imports
kept on purpose, with the reason beside each. It fails on any unused import that
is not on that list, on any local variable written and never read, and on any
undefined name other than `iface`, which the Python Console provides. It does not
look at `tools/`, so run pyflakes on that yourself. Anything else pyflakes says
is a defect.

## What to be careful with

**The grid.** Every edge is the origin plus a whole number of pixels, never "the
other edge minus a size". That is not pedantry: the two differ by about 5e-10, and
when they did, rows of a line strip stopped sharing edges, the union came back in
seventeen pieces, and each piece was small enough for the four-pixel floor to
discard. A diagonal line appeared on screen and the cause was floating point.

**A failed geometry operation is not an empty one.** `difference()` on an untidy
ring can return a null geometry whose `area()` reads as nothing, and "nothing
left" one line later means `deleteFeature`. Go through `cut_away()`, which exists
for exactly this.

**A failed commit leaves its buffer alone.** Do not `rollBack()` after one: that
throws away everything else pending in the table, including work drawn somewhere
else entirely. Report it and let Save try again.

**Class codes are permanent.** They are already inside exported masks. Renaming a
class changes the label everywhere and leaves the number alone; removing one
retires it. Neither its number nor its name is ever handed to another class.

## The three addresses QGIS shows

`tracker`, `repository` and `homepage` in `rasterlabel/metadata.txt` point at
<https://github.com/massigit12345/Rasterlabel>. QGIS shows them to everybody who
looks at the plugin, and the tracker is where a bug report goes.

If the repository ever moves, one command rewrites all three and rebuilds
`dist/`:

```
python3 tools/set_urls.py <github-account> --repo <repository-name>
```

`tools/set_urls.py --show` says where things stand without changing anything,
and `tools/package_plugin.py` refuses to build a release zip if a placeholder
ever finds its way back in.

## Making the release zip

`tools/package_plugin.py` zips `rasterlabel/` as it stands on disk, because the
suites need the zip of the code they are testing, committed or not. The zip
attached to a release has to be the tagged commit and nothing else, so build
that one with

```
python3 tools/package_plugin.py --release
```

which refuses unless every file going into the zip is exactly as the last
commit has it: nothing untracked, nothing edited, nothing deleted. Without
`--release` the zip is built anyway and a block on stderr lists what differs;
`RL_DEV_BUILD=1` shortens that to one line for a zip you build for yourself.
Building from a fresh clone of the tag comes to the same thing.

## Reporting a bug

Press **Check** under ANNOTATION CAMPAIGN, press **Copy report**, and paste that in. It
says which build is running, what it is running on, which formats that GDAL has,
and what the campaign looked like, which is most of what anybody needs to begin.
If the error window appeared, its **Copy report** button gives the traceback as
well. The log file beside the campaign, `rasterlabel.log`, has the rest.

## Support

**Asking how to do something.** Read the README first (its statement of need
and its headings, then the tutorial in `docs/tutorial.md`, which walks the whole
program on a small example), then open an issue on the tracker
<https://github.com/massigit12345/Rasterlabel/issues> and begin its title with
"Question:". Say what you want to end up with, the QGIS version, and what you
have already tried.

**Reporting something that is wrong.** The same tracker, with the Check report
described just above. One problem to an issue, and the smallest raster or
campaign that shows it, if you can share one.

**Sending a change.** Open an issue first when the change is more than a fix,
so that nobody works on something that will not fit. A pull request holds the
edit to the modules, the rebuilt `dist/rasterlabel.py`, and a test that fails
without the edit (see "What a change needs"). The run in `tests/run.py` must
pass.

**A private matter**, a conduct problem or something that should not be
public, goes as a private report through the repository's security or issue
tracker, as the Code of Conduct says.

**What to expect.** The program is looked after by one person, in the time
that allows: an answer may take some days.

## Where things are

| | |
|---|---|
| `rasterlabel/` | the package, and the QGIS plugin folder |
| `rasterlabel/constants.py` | the numbers, the spellings, and `VERSION` |
| `rasterlabel/errors.py` | the log, the diagnosis, the error window, the signal net |
| `rasterlabel/geometry.py` | the pixel grid and every measurement on it |
| `rasterlabel/recovery.py` | the snapshot that survives a crash |
| `rasterlabel/correction.py` | the correction campaign: Correct's own folder and manifest |
| `rasterlabel/doctor.py` | what Check reports |
| `rasterlabel/sections_*.py` | the four modules |
| `rasterlabel/panel.py` | the shell |
| `rasterlabel/measure.py` | the Measure menus, and the hooks the measuring modules come in by |
| `rasterlabel/detection.py` | the boxes as COCO and YOLO labels, in pixels: no QGIS |
| `rasterlabel/agreement.py`, `stats.py`, `reports.py` | the matrices, the statistics, the report folders: no QGIS |
| `rasterlabel/compare.py`, `ui_compare.py` | Compare two readings |
| `rasterlabel/processing_provider.py` | the Processing algorithms, one for each measure of the Measure menu |
| `rasterlabel/journal.py`, `effort.py`, `ui_time.py` | the journal of working time, and Time |
| `rasterlabel/model_vs_corrected.py`, `ui_mvc.py` | Model vs corrected |
| `rasterlabel/uncertainty.py`, `ui_uncertainty.py` | the uncertainty card and its report |
| `rasterlabel/card.py`, `ui_card.py` | the dataset card |
| `rasterlabel/design.py`, `ui_import_frames.py` | Import frames and the sampling design |
| `tools/bundle.py` | the package folded into one file |
| `tools/package_plugin.py` | the zip QGIS installs |
| `tools/set_urls.py` | rewrites the three addresses, if the repository moves |
| `tools/make_example.py`, `tools/tutorial_walk.py` | the example dataset, and the tutorial done without a window |
| `docs/` | `tutorial.md`, which the suites keep true, `methods.md` and the pictures |
| `dist/rasterlabel.py` | built: what you paste into the console |
| `tests/` | the suites and the fakes they run against; `tests/run.py` names the sets |
