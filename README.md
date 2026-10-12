# RasterLabel

A QGIS panel for drawing labels on a raster: areas, lines and points, with a
legend of your own, saved as real geometry in a GeoPackage and exportable as the
masks a training run needs.

It was written for annotating mud volcano orthomosaics at five centimetres a
pixel, and it works on any raster QGIS can open, georeferenced or not. A
photograph with no coordinate system is a perfectly good thing to annotate; you
only lose the metres, not the drawing.

It also mends a thematic map made by any other program (Correct), cuts a
dataset out of the layers of a project (Cutouts), and measures what was done:
how far two readings of the same ground agree, how long the drawing took, how
far a model was from the map as corrected, where its uncertainty pointed, and
what the dataset holds, class by class. See [Measuring](#measuring). Each of
those measures can also be run from the Processing toolbox, a model or a script
([From Processing, a model or a script](#from-processing-a-model-or-a-script)),
and a small synthetic example with a tutorial lets you try all of it ([Example
and tutorial](#example-and-tutorial)).

Runs on **QGIS 3.36 to 4.x**, on Qt 5 and on Qt 6, from one code base and one
plugin zip, on Windows and on Linux, and is tested on 3.36 Maidenhead, 3.44
Solothurn and 4.2 Belém do Pará: see [Requirements and
limits](#requirements-and-limits). Free software under the GNU GPL, version 2
or any later version: see [Licence](#licence).

**The one thing worth knowing before anything else.** A mask burned from a
campaign at full size lines up with the image pixel for pixel, with no
resampling: it is rasterized on the campaign's own grid, the one taken from
the reference raster, by the rule that a pixel belongs to whoever covers its
centre. That is the reason to use this rather than a tool with its own canvas.

What is placed on the grid exactly, edge by edge, is the **frame** (origin plus
a whole number of pixels, which is why cutouts from two frames stack), the
**strip a line claims** (whole pixels: the trace laid as a rectangle of the
width you asked for, that many pixels across at a right angle to the line
whichever way it runs, and the pixels whose centre is inside it), and the
**footprint of a point**. A **brush outline is
vector**: it follows your hand, vertex by vertex, and is turned into pixels
when the mask is burned. If you want to see where that falls, export the mask;
what is written there is what a training run will read.

---

## Statement of need

RasterLabel is for people who have to make a training set, or a reference map,
out of raster imagery by hand, and who then have to say how good it is: remote
sensing and geoscience groups drawing classes over orthomosaics, scenes or
photographs, with a legend of their own, and wanting the result as masks that
line up with the image pixel for pixel.

What is already there for this, and what each does well:

- **General annotation tools** (Label Studio, CVAT, LabelMe) are made for
  pictures. They work on an image, not on a georeferenced raster, so the
  coordinate system and the frames of a survey are not what they keep, and what
  they write has to be brought back onto the map.
- **QGIS plugins for classification** work on sparse samples or on thematic
  maps: the Semi-Automatic Classification Plugin (Congedo 2021,
  doi:10.21105/joss.03172) with its regions of interest and its accuracy tool,
  AcATaMa (Llano et al. 2026, doi:10.1016/j.acags.2026.100389) for point
  sampling and accuracy assessment, and ThRasE (Llano 2026,
  doi:10.21105/joss.09634) for editing the classes of a thematic raster. They
  are the closest tools and they are good at what they do; none of them is
  built around frames and several readings of the same ground.
- **Desktop annotators for orthomosaics** such as TagLab (Pavoni et al. 2022,
  doi:10.1002/rob.22049) draw dense masks with assisted tools, and their
  authors measured the agreement between annotators in a user study.

What RasterLabel puts together, inside QGIS, on the grid of the raster it
annotates: dense areas, lines, points and boxes drawn by hand into a
GeoPackage; frames placed on that grid, also from a sampling design, with the
design columns kept; several readings of the same frames, which can be blind;
the agreement of two readings (confusion matrix, per-class IoU, kappa read only
as an agreement statistic, quantity and allocation disagreement, with a frame
bootstrap interval) and a map of where they differ; the working time of each
frame and class from a journal; the correction of a thematic map made by
another program, with the agreement of the model with the corrected map; and a
dataset card that records the pixel counts and the rules that made the masks.
None of the parts is new: an ignore value for unlabelled pixels, the tracking
of working time and the ordering of work by uncertainty exist in other tools,
and a confusion matrix between two maps is in several. What is offered is having
them in one place, on the pixel grid of the raster, with the rule that made each
mask written beside it.

What it does not do: assisted drawing with a segmentation model (use Geo-SAM,
segment-geospatial or Deepness for that and open their masks in Correct),
training a model, a server for several people at once (one GeoPackage has one
writer), or the design-based estimators of AcATaMa, to which it points.

---

## Installing it

### As a plugin

Download `rasterlabel-1.1.zip` from the [1.1 release
page](https://github.com/massigit12345/Rasterlabel/releases/tag/v1.1) (every
release is listed under
[releases](https://github.com/massigit12345/Rasterlabel/releases)), then in
QGIS: **Plugins ▸ Manage and Install Plugins ▸ Install from ZIP**. It appears
under **Raster ▸ RasterLabel**, and on the toolbar.

To build the zip yourself: `python3 tools/package_plugin.py` (on Windows,
`py -3.12 tools/package_plugin.py`), which writes
`dist/rasterlabel-1.1.zip`. It zips the folder as it stands and says so, loudly,
when that is not the last commit; `--release` refuses to build at all unless
the zip will be exactly the commit. The same files make the same zip: every
entry has the same date and permissions and the entries are sorted by name, so
building the zip of a tag again gives the zip that was published (with the same
Python and zlib; another compressor may write other bytes for the same files).

### As two lines in the console

This is how it was developed and it is still the fastest way to try it or to
change it. Open a raster, then the Python Console (`Plugins ▸ Python Console`, or
`Ctrl+Alt+P`), and paste:

```python
p = r"C:\path\to\dist\rasterlabel.py"
exec(compile(open(p, encoding="utf-8").read(), p, "exec"))
```

The panel appears on the right. You do not have to restart QGIS to reload after a
change: launching again takes the old panel down first, gives back every signal it
was holding, and builds a new one.

If the plugin is installed and its panel is already up, the two lines bring that
panel forward instead of building a second one, and say so in the log. To run
the file you pasted rather than the plugin, switch the plugin off first
(Plugins, Manage and Install Plugins), which takes its panel down.

`dist/rasterlabel.py` is **built, not written**: it is the package folded into one
file by `tools/bundle.py`. Edit the modules, not that file.

### Which build am I running

Every build has a **build fingerprint**, eight letters taken from the bytes
actually running. "1.1" is true of every build ever called 1.1; the fingerprint
is not. It is under WHAT IS RUNNING in the **Check** report, in every error
report, at the top of the log file beside a campaign, and in the QGIS message
log (`View ▸ Panels ▸ Log Messages`, the RasterLabel tab), where the panel
writes one line when it starts: `shell 1.1 build ... ready`.

Inside QGIS nothing is printed to the Python Console, not even after the
two-line paste: the message log and the log file hold every line. Set the
environment variable `RASTERLABEL_DEBUG` before starting QGIS to have the lines
printed there as well.

---

## Five minutes

1. Load the raster into QGIS.
2. Press **New** under ANNOTATION CAMPAIGN. The *Reference raster* is the layer
   you have selected in the Layers panel, else the one you picked in RASTER at
   the top of the panel, else the one on top of the layer tree, not the first by
   name: the grid of a campaign comes from it and never changes. The folder is
   filled in for you as
   `<your QGIS project folder>/<campaign name>`, or beside the raster while the
   project is not saved yet, and follows the name while you type it. A big georeferenced raster is proposed *in tiles*, a small one or a
   picture with no coordinate system *free*; the dialog says which and why.
   One class is there already so you can press Ok straight away.
3. Pick a class chip, take **Polygon**, and draw. Click by click, or hold the
   button down and draw freehand. Right click or Enter closes the outline.
4. Press **Save**, or let the autosave do it every twenty strokes.

Rename the class by double clicking its chip. Add one with the **+** at the end of
the chips. Nothing about the legend has to be decided before the first stroke: the
ground tells you what is in it, usually around the third frame.

---

## Example and tutorial

`examples/rasterlabel_example/` holds a small synthetic scene anybody can run
the program on, about a megabyte in all: a 600 x 400 pixel picture of half a
metre in UTM 33 N (`scene_rgb.tif`), the two-band map of an imaginary
classifier on the same grid (`model_map.tif`: band 1 the class, band 2 the
probability it gave to that class times 255, lower where the map is wrong,
with its colour table and a `.qml`), twelve sample points as AcATaMa writes a
stratified design (`sample_design.gpkg`: `sample_id`, `stratum`, `incl_prob`,
`weight`, `design`) and the four classes (`classes.csv`). Nothing in it is real
data. `python tools/make_example.py` makes it again from a fixed seed: the same
bytes on the same machine, and on another build of GDAL the same scene to
within a few pixels in a thousand, which is what a suite holds the committed
files to.

[docs/tutorial.md](docs/tutorial.md) walks a geoscientist through it: install
from the zip, New campaign with the four classes, Import frames from the sample
design keeping the design, two readings of the same frames (the second not
seeing the first), Check, Compare two readings, Time, Export with the dataset
card, the whole raster with the ignore value, Cutouts, the same measure from
Processing, then Correct on the model's map with its classes read from it,
Model vs corrected, the uncertainty of band 2 and its report, and the dataset
card of the correction. The first steps take about ten minutes, drawing
quickly, and the rest about half an hour more. It says what each step writes
and where, with the labels of the program as they are.

The tutorial is kept true by two suites. `tools/tutorial_walk.py` does every
step through the panel with no window (run it with the Python of a QGIS and
`QT_QPA_PLATFORM=offscreen`), prints the headline number of each measure, and
with `--figures docs/img` draws the pictures of the page; the numbers the page
quotes are checked by ranges, not to the digit, because drawn by hand yours
will differ a little. `tests/test_tutorial_text.py` checks that every label in
bold on the page is a label of the package, so renaming a button or a menu
entry the page shows means changing the page.

### How to cite

`CITATION.cff` (GitHub's "Cite this repository") and `.zenodo.json` hold the
citation: Guastella, Massimiliano (ORCID 0009-0006-9841-6275). RasterLabel,
version 1.1, software, released 2026-10-12, GPL-2.0-or-later,
<https://github.com/massigit12345/Rasterlabel>. There is no
DOI yet and the files do not pretend there is one; when a release is archived
on Zenodo, its DOI belongs in both files. A suite checks them against the
version, the licence and the repository that `metadata.txt` names. How every
number is computed, with references, is in [docs/methods.md](docs/methods.md).

---

## What a campaign is

A folder with two things in it:

- **`campaign.json`**, the manifest. Name, id, operators, the legend with a code
  and a colour per class, and the grid: reference raster, coordinate system,
  origin, pixel size. The manifest is the truth about a campaign.
- **`annotation.gpkg`**, a GeoPackage with five tables: `tiles`, `polygons`,
  `lines`, `points`, `boxes`.

Two more things appear beside them while you work: `rasterlabel.log`, and a
`recovery/` folder. Both are explained under [When something goes
wrong](#when-something-goes-wrong). Others appear when they have something to
hold: `journal.csv`, one line per thing done, from which the working time is
measured ([How long it took](#how-long-it-took)); `design_log.csv`, written by
Import frames ([Sampling designs](#sampling-designs)); and `reports/`, one
folder per report of the Measure menu, never written over.

A campaign folder can be copied, moved or zipped whole. Opened again, by Open
or from a saved QGIS project, it works on the files of the folder it is in
now: a layer of the project that still reads the original of a copy, or the
old place of a moved folder, is taken out of the project, said in the log,
and the right one loaded.

The manifests do not carry the name of whoever made them, nor does anything
else that is meant to be shared: the Cutouts dataset folder with its
`layers.json`, the exports and their sidecars, the reports and the dataset
card. A path is written in one of three ways. A file inside the folder of the
manifest is written from it (`ortho.tif`, `../maps/ortho.tif`). A file
elsewhere under your home folder is written from `~` (`~/maps/ortho.tif`) and
read back from the home folder of whoever opens it; so is a folder outside your
home that points into it. A way is never written when it would climb out of
your home folder or go down through it. This covers `campaign.json` (the
reference raster of its grid and the file of each imported sampling design),
`correction.json` (the map it started from and the reference raster of its
grid), the record a campaign keeps of a correction, which points to its
manifest the same way, and so does the working copy, and the `layers.json` of a
Cutouts folder (the grid and every layer). A file on another drive or on a
server has no way from the folder and keeps its whole path, which has no home
folder in it. A layer that is a web service or a database (WMS, XYZ, PostGIS
and the like) is written without its `user=`, `username=`, `password=`, token
and `user:password@` parts; `authcfg`, which only names a configuration stored
in QGIS, is kept. The Check and error reports, the summaries of the Measure
reports and the log write the home folder as `~`, and the dataset card names a
file outside its own folder by its name alone. Manifests written before keep
their whole paths and open as they did (a `layers.json` with whole paths is
written again, the new way, at the next cut), and the other paths in a log (a
disk, a project folder) are those of your machine.

An annotation campaign is what **Annotate** and **Objects** draw into, and only
they need one. **Correct** keeps a correction campaign of its own, below, with
buttons of its own in the panel, and **Cutouts** keeps none at all.

In QGIS the five tables appear as layers named after the campaign:
`aragona_2025_tiles`, `aragona_2025_polygons`, and so on. The second half is the
name of the table inside the package, letter for letter, and it is also the name of
the file that comes out of Export.

The grid never changes.

Making a new campaign in the folder of another asks first (**Replace**, with
Cancel as the default). Replacing moves its package and its manifest aside under
a stamped name (`.replaced-<date>-<time>`) and deletes nothing. It is all or
nothing: if the package cannot be moved because another program holds it open,
nothing is moved, the old campaign opens as before, and the message says so.

### What a correction campaign is

Correct mends a thematic map that is already made, by this program or by any
other: a land cover, a mask, the output of a model. It needs no annotation
campaign. A correction campaign is a folder you choose, with:

- **`correction.json`**, its manifest: the name, the operators, the map it
  started from and its class band, the grid of that map (so areas are in the
  map's own pixel), the classes as you confirmed them, and the tally of what
  was changed. The tally counts every stroke that was written, as
  `operations.csv` does; once something was undone, `undone` says how much of
  it, and the panel shows the count net of it. A row of the tally in the panel
  reads "597.73 m2 in 3 strokes", the area first and the strokes in words, so
  the count cannot be read as a thousands separator.
- **`<map>_corrected.tif`**, the working copy, which is the corrected map.
  The correction of a thematic map is a thematic map: the copy has exactly the
  bands of the map it started from, in the same order, with the same names,
  type, nodata, grid, coordinate system, tiles or strips and compression, and
  a BigTIFF stays a BigTIFF; its class band holds the corrected classes and
  every other band is copied unchanged. The map it started from is only ever
  read. Overviews are not copied, those inside a cloud optimised GeoTIFF
  included: zoomed out, QGIS draws a map from its overviews, and those would
  show it as it was before the correction. Build them on the corrected map
  once it is done (Raster > Miscellaneous > Build Overviews). A map whose bands differ in type,
  which a VRT, an IMG or a netCDF can be and a GeoTIFF cannot, is copied in
  the one type that holds every value of each (Int16 and UInt16 give Int32),
  then compared with the map value for value; if a single one would change,
  nothing is made and Correct says why.
- **`<map>_corrected.qml`**, the QGIS style it opens with, so the corrected
  map opens in QGIS exactly like the original: Paletted/Unique values on the
  class band, with the classes of the correction, their codes, colours and
  names. When the original had a `.qml` of its own, this one follows it (its
  opacity, for one). Once it exists it is kept: whenever the classes change
  (the Classes window, "+", a code adopted from the map) and every time
  Correct opens and closes, only its renderer, its band and its classes are
  rewritten, so a style you set on the corrected map in QGIS and kept with
  Save as Default (its opacity, its resampling, its blend mode) stays. The
  `.qml` has to travel with the `.tif`: shared without it, a map of several
  bands opens in QGIS as a picture of its first three, exactly as the
  original does without its own `.qml`.
- The classes are also written into the class band as its **colour table and
  category names**, for GDAL, rasterio, ArcGIS and the rest. A GeoTIFF of one
  band of bytes keeps them inside the file, and QGIS opens it in its classes
  from them even without the `.qml`. A band of sixteen bits is given a colour
  table only when the map came with one: TIFF makes it 65536 colours long
  whatever the codes, and QGIS 3.36 then takes some ten seconds to open the
  map, `.qml` or not. A GeoTIFF of several bands cannot hold a colour table,
  so GDAL keeps it in `<map>_corrected.tif.aux.xml`, and reads it back for
  band 1 only: a class band further down gets its category names alone. For
  QGIS, the `.qml` is what counts. They are rewritten with the `.qml`.
- The **attribute table** of the class band, when the map has one, the way
  ArcGIS and many classifiers name their classes: the copy's own, and a
  `<map>_corrected.tif.vat.dbf` when the map came with a `.tif.vat.dbf`. Each
  keeps its columns and has a row per class of the correction, with its
  name, its colour where the table has colour columns, and its pixel count
  in the corrected map; a class added in the correction is in it, and
  whatever else the map's row held is kept. They are rewritten with the
  `.qml`; the attribute table of a map of several bands when Correct
  closes.
- **`<map>_corrected_changes.tif`**, which pixels a person changed: one byte
  band on the grid of the copy, 1 where a stroke changed the pixel, 0 where
  it is as the map arrived, named in `correction.json`. Undo takes its marks
  back with the pixels.
- **`<map>_corrected_reviewed.tif`**, which pixels a stroke went over: one
  byte band, 1 under the whole footprint of a stroke that was made, whether or
  not every pixel under it changed, 0 elsewhere; a stroke refused, or one with
  nothing to change, leaves no mark. Written stroke by stroke and taken back
  by Undo. It is the ground the strokes swept, which
  [Measuring the model](#measuring-the-model) reads. A correction made before
  it existed starts it at its next stroke, and `correction.json` says how many
  strokes came before (`reviewed_since`).
- **`operations.csv`**, one row per stroke written, with the operator who
  struck. An Undo keeps the row of the stroke it takes back (the log is what
  was written; `journal.csv` notes the undo), and the panel counts net of it,
  with a line for the ground changed once each when strokes went over the same
  pixels. The operator is the one typed in the operator box under Settings,
  else the one picked in the panel in this session, else the one who made the
  correction; a name typed in the window that made it stays the operator for
  the rest of the session unless another reading is picked; a new operator is
  added to the `operators` of the manifest. The box is the field *operator*
  under Settings in Correct, and its hint says which name it will use when it is
  left empty. Areas are measured on the ground, row by row, on a map in degrees
  or in Web Mercator, in Correct, in the Dataset card and for the net change and
  the transitions of Model vs corrected.
- **`journal.csv`**, one line per thing done, as in a campaign.
- **`<map>_corrected_uncertainty.tif`**, `uncertainty_places.csv` and
  `uncertainty_places.geojson`, only once an uncertainty has been chosen
  ([Uncertainty](#uncertainty)).
- **`reports/`**, the reports of the Measure menu under CORRECTION.
- **`rasterlabel.log`**, while Correct is open.

There is no GeoPackage and no `recovery/` folder: every stroke is written into
the copy, the record of changes and the record of the ground swept as it is
made, each file opened, written and closed again, and the class band and the
record of changes are read a window or a strip at a time, never whole, so a
map of hundreds of millions of pixels is corrected in the memory of a small
one. The uncertainty is read the same way: its file and its report are never
held whole. A stroke is written whole or not at all: when the copy cannot be opened
for writing, or the write or the close answers with an error, the stroke is
refused with one message, nothing is counted, logged or kept in the history, and
the blocks that did reach the disk are put back. Saving the QGIS project while
Correct is open does not save the map it started from unticked, and the view of
the original beside the copy follows the main view into another coordinate
system. The manifest names the copy relative to the folder, so the folder can be
moved or zipped whole, and it takes the working copy by its file name in that
folder, whatever the manifest says: a `working_copy` that climbs out of the
folder with `..` or names another drive is not followed.

A working copy made by an earlier build of 1.1 has one band more than its
map, "corrected", and no style, so QGIS opened it as a picture: the class on
red, the probability on green, the entropy on blue. Opening it in Correct
converts it, losing nothing: the band is first written out to
`<map>_corrected_changes.tif` and read back, the copy is then rewritten
without it under a temporary name and compared with the old one band for
band and pixel for pixel, and only then takes its place; its `.qml` is
written, `correction.json` is told, and the log says so in one line. If
anything stops it half way, the old copy is still there as it was and the next
opening does it again; `correction.json` is told the new number of the class
band before the copy is replaced, and keeps the old one for as long as the old
copy might still be there, so a stop between the two never points the brush at
the wrong band. On a large map this takes a minute or two, under an hourglass
and with a line on the message bar. If the old copy was loaded in the project
as a layer, that layer is taken out so the file can be replaced, and the
message bar says so; the corrected map is then on the map in its classes.

A new correction **asks before it uses anything already on disk**. A map with
a `_changes.tif` beside it, or the "corrected" band of an earlier build, or
named `_corrected`, or named by a `correction.json` beside it, is a working
copy, not a map to correct, and the `_changes.tif` itself is no map either:
Correct offers to open the
correction that owns it, looked for beside the copy, in the recent list and in
the annotation campaign, and says how to open it by hand when there is none. A
map that already has a correction offers "Open that one", "Make a new
correction" or Cancel. A folder that holds `<map>_corrected.tif` without a
`correction.json` offers "Resume it", which keeps the copy and every correction
in it, shows the classes first with the copy's values locked and reads the
counters back from `operations.csv`, or "Start from a fresh copy", which moves
the old copy, its `.aux.xml`, its `.qml`, its `_changes.tif` and its
`operations.csv` into a `set_aside_` folder and deletes nothing. A copy with
neither its `_changes.tif` nor the band of an earlier build cannot say which
pixels a person changed, and is offered only a fresh copy. The map's own folder
can still be used, after a warning.

It also **asks about the map itself**, and the Correction window says the same
as soon as the map is picked. A map stored with a compression that does not
keep values exactly (a JPEG, a GeoTIFF compressed as JPEG or as LERC with an
error allowed, a lossy WebP or JPEG 2000) holds values along the edges of its classes that are no class, and
each would be listed as a class of its own: Correct asks whether to start
anyway, Cancel the default, and the map as the program that made it wrote it,
a GeoTIFF or a PNG, is the one to correct. A picture in colour, red, green and
blue, is a map of classes only as colours across three bands, while a
correction takes its classes from the codes of one band: Correct asks the
same, and the way out is to convert it first to a map of one band with one
code per class. A map on a rotated grid is refused, because Correct finds the
pixels under a stroke on a north-up grid: warp it north-up first, in its own
coordinate system and with nearest neighbour resampling (Raster > Projections
> Warp, or `gdalwarp -r near`), and correct the map that gives. A correction
whose working copy is on a rotated grid is not opened, and nothing of it is
changed.

A correction made by an earlier build lives inside its annotation campaign, in
`<campaign>/corrections/<name>/`. Open that campaign, press Open under
CORRECTION and pick it: it opens where it is as a correction campaign of its own. A
`correction.json` is written beside its copy, its "corrected" band moves out to
`_changes.tif` as above, nothing is deleted, and the record in `campaign.json`
is kept, with a pointer to the new manifest.
From then on it is in the list of recent corrections, with or without the
campaign.

---

## The panel

**RASTER**, and the list beside it, is the image everything is measured on;
the line under it gives its pixel on the ground and its coordinate system.
While nothing is open, a strip under it says what to do first: load a raster,
or New or Open a campaign, or go straight to Correct or Cutouts.

Then three blocks, one for each kind of work, each with the modules it opens.
One module is open at a time, because they share the map tool; closing Annotate
or Objects gives the map the tool you had before, Pan when there was none. The
module that is open is shown right under the block that owns it, Annotate and
Objects under ANNOTATION CAMPAIGN, Correct under CORRECTION, Cutouts under CUTOUTS, and its
button stays pressed in the colour QGIS uses for a selection. The other blocks
fold to one line while it is open: their name, what they hold in a few words
("none open", or the campaign's name and its number of classes), and a small
arrow at the end. A click anywhere on that line, or on the arrow, unfolds the
block again without closing the module.

The panel is drawn by QGIS's own style, in the default theme, in Night Mapping
and in Blend of Gray: buttons, lists, number boxes and tick boxes look as they
do in every other dock. The four module buttons, and Save in a module, are a
size above the other keys and carry QGIS's icons. A button that cannot be
pressed stands back, with no fill, a faint outline and faint words; one that
destroys work (Delete, Set aside, Undo in Cutouts) is written in red before
the pointer reaches it.

**ANNOTATION CAMPAIGN**: a line saying which campaign is open ("no annotation
campaign open" when none is), then New, Open and Close in a row of three,
Classes and Export in a row of two, **Measure ▾** and Check in another, then
**Annotate** and **Objects** side by side. Those two draw into the campaign and
stay grey until one is open. Closing a campaign only takes its layers out of
the project, and only the layers the program made: a layer of yours in the same
group stays, and so does the group, and the log says so. It touches no file.
Opening or closing a campaign leaves Correct and the correction alone; an open Cutouts is built again, since All tiles and
Whole read the campaign.

**Measure ▾** is a key with a menu behind it, like QGIS's own Style button:
pressed, it lists what can be measured on what the block holds, and each entry
writes a report of its own under `reports/` and changes nothing in the
campaign. It is grey while the block holds nothing, and a grey entry says why
when the pointer rests on it. See [Measuring](#measuring).

**Who is drawing.** Every mark is filed under a reading: an operator in a pass.
The panel holds that reading for the whole QGIS session, for Annotate and for
Objects alike, and remembers it per campaign on this computer. Opening a
campaign whose remembered reading is not the one last used in this session
asks who is drawing before Annotate or Objects opens, so a second reader never
draws into the first reading by mistake; a campaign with only its creator in
pass 1 is never asked. Annotate changes it under Settings, and Objects shows it
above its tools with a **Change** button.

**CORRECTION**: its line (the name and the number of classes, or "no correction
open"), then the correction campaign's own New, Open and Close, standing under
the campaign's, Classes, **Measure ▾** and Check in the row under them, then
**Correct**. New starts a correction on a thematic map, Open takes
one opened lately or a `correction.json`, and either opens it in Correct. The
correction is open while Correct is: going to Annotate, Objects or Cutouts, or
pressing Correct again, closes it exactly as Close does, taking its layer out
of the project and touching no file, and Open brings it back as it was. While
Correct is open its layer keeps the working copy open, so on Windows move or
rename the folder only once you have left Correct. Classes opens the window its
classes were confirmed in, and Check looks the correction over on its own; with
no correction open both are grey. Correct pressed with no correction open
offers the same choice as New and Open. It needs no annotation campaign; New
needs the map on the screen, Open does not, since a correction brings its own
copy.

A button that cannot be pressed says why in its tooltip: with no raster
loaded, the two New buttons, Correct and Cutouts say to load one first and
where, and the others say what is missing (a campaign, a correction, or the
one already open to close first).

**CUTOUTS**: its line, "saves no campaign", and **Cutouts**, which needs only
a raster.

**VIEW** is one low row: four arrows around **fit**, which goes back to the
whole raster, the two zooms beside them, and then *step*, *keyboard* and
**Detach**. *step* is how far one arrow moves the view, as a share of what you
see. With *keyboard* ticked the arrow keys move the map, Shift and an arrow
moves it three times further, PageUp and PageDown zoom, and the line under the
row says so. **Detach** takes the panel out of the QGIS frame as a window of its
own, and **Dock** puts it back.

Tab walks through every control of the panel and of the module that is open,
and the one it is on is ringed. A click on a key never takes the keyboard from
the map, so the arrow keys keep moving the view; a click into *step*, a list or
a number box does, as it always has, until the next click on the map.

Every key of a block or a module is one of a row of equal keys, and a row is
never left with one key alone: two keys share the bar in halves, four are a row
of four or two rows of two, five are three and two with the two sharing their
row. A legend of a dozen classes or more takes as many columns as the panel
has room for, a long name cut short in its chip and written whole in the
banner and the tooltip.

RasterLabel is a vertical bar and only that. It can be docked left or right or
floated, and QGIS remembers where you put it; the top and bottom edges are
refused, because a low strip across a wide
screen puts every control a long way from every other. It holds down to 260
pixels wide, with Segoe UI on Windows and with the wider DejaVu that Ubuntu and
Debian draw with: a row of keys narrows to the width its words need, and a tick
box whose words do not fit breaks them onto a second line instead of cutting
them. In Correct, the *see through* slider goes onto a row of its own, under its
word and its box, when the row would leave it narrower than its word.

---

## Annotate

The module where the work happens. The banner on top is the class in hand, and
the line under it says what the next click does with the tool in hand
("Polygon: click or drag round an area"). Under the class chips the buttons are
in four groups, each under a small heading, in the order the work is in: the
frame first, because on a tiled campaign nothing can be drawn until one is
placed, with the frame in hand and its Go, Note and Delete right under Tiles and
Move; then the locks that hold it, then what leaves a mark, then what mends it,
then Save. A long class name is cut in its chip and in the banner, and is whole
in the tooltip; from four classes up the legend keeps at least two columns.

### FRAME, the pieces the work is cut into

- **Tiles** places a frame where you click, of the side set under Settings, and
  picks one up when you click inside it.
- **Move** turns dragging on, and takes the map to do it: the shape in hand is
  put down, the pointer becomes a hand over a frame, and the frame can be
  dragged. Taking a shape again puts Move back up. It is off to begin with,
  because a frame nudged by half a metre leaves every polygon inside it
  describing slightly different ground and nothing in the file says so.

  A frame that holds work asks before it moves, and there are two answers.
  **Move with its contents** translates every mark by exactly what the frame
  moved, which is a whole number of pixels: the frame stays a closed partition
  and every mark now covers ground it was not drawn on. **Move and delete them**
  leaves the frame clean and the afternoon gone. Cancel is what Esc does.

  **Frames never overlap.** A frame dragged onto another stays where it was,
  and a new frame placed partly over one is not made; the message bar names
  the frame in the way. Frames may touch edge to edge, and while you drag the
  outline turns red where it lies over another frame. **A frame is moved or
  deleted only by whose work it holds**: everything in it, polygons, lines,
  points and boxes, in every pass, must be your own work in the pass you are
  drawing. An empty frame anyone can move or delete. Otherwise it stays, and the
  message bar says whose work it holds and in which pass ("1 mark by ANNA in
  pass 1"), or, in a blind pass, only that it holds work of another reading.
  With Move down such a frame is not picked up at all. Import frames refuses a
  frame that would overlap another, as a click would. Check does not report
  frames that overlapped in packages made before this rule.

### LOCK, what is held still

- **Frames** shut: frames cannot be moved, made or deleted.
- **Marks** shut: nothing can be drawn, filled, reclassified or rubbed out, and a
  vertex moved with the QGIS tool is put back. So is anything QGIS's own undo
  and redo would change in the polygons, lines and points: they stay as they
  were when the lock was shut. A frame that holds marks can be neither moved
  nor deleted.

A shut lock draws a padlock on itself.

### SHAPE, what leaves a mark

- **Polygon** draws an outline, click by click or freehand.
- **Round** is a round brush, for small repairs. Its radius is in pixels.
- **Line** traces something long and thin: a fissure, a channel, an edge. Its
  width is in pixels and is measured at a right angle to the line: the ground
  it claims is a rectangle that many pixels across, along a row, along a
  column and across a diagonal alike, and it reaches half a width past each
  end, so the area of a line is its length plus a width, times its width,
  whatever its direction. A pixel is part of the line when its centre is
  inside, as for every mark. The one exception is a line of **1 pixel**:
  across a diagonal an unbroken chain of pixels cannot be thinner than about
  1.4 pixels (pixels that touch only at a corner would break the line), so a
  1 pixel line is exact along rows and columns and up to 1.4 pixels across at
  45 degrees. The trace itself is kept as a line, so its length and bearing
  stay measurable. Lines drawn before this was corrected keep the strip they
  were drawn with (the strip is stored as polygons, and the export does not
  draw it again).
- **Points** drops one point per click. Each point carries a footprint, the odd
  square of pixels it stands for: 1, 3×3, 9×9 and so on. The point on the map is
  drawn as big as its own footprint. On a tiled campaign a point keeps to the
  frame in the list exactly as a stroke and a line do: a click outside it drops
  nothing and says so, and so does a click so near the edge that the footprint
  would reach past it, because the export burns the whole square and nothing
  clips it to the frame. A 9×9 point needs four pixels of room on every side. A
  point dragged out of its frame with Vertices is put back. Removing and
  reclassing work anywhere, so that old points can be cleaned up. For points
  anywhere, make the campaign without tiles.

### EDIT, what mends what is already there

- **Vertices** hands the map to the vertex tool QGIS itself uses, on the right
  layer for the shape you are holding. Press it again to give the map back.
  What happens to the border afterwards is under *a moved vertex wins*.
- **Fill Gap** fills everything not yet painted inside the frame with the current
  class. Nothing already drawn is touched. On an empty frame the gap is the whole
  frame, which is how you lay a background down before drawing the detail over it.
- **Repair** fixes overlaps. After vertices have been moved by hand two polygons
  can share ground; the smaller one keeps it, because the small one is the
  deliberate detail. Anything above a hundredth of a pixel counts, the same
  threshold Check uses. Repair works on the frame, pass and operator in hand.
  Before that it untangles any outline that crosses itself: QGIS's vertex tool
  lets a vertex be dragged across an edge of its own polygon, which leaves a bow
  tie nothing can be cut against, and Repair writes it back as the polygons it
  encloses. A moved vertex that does this is untangled on the spot as well.
  Last, Repair joins the neighbours that were never joined, which is what a
  campaign drawn before polygons were joined as they meet is full of: polygons
  of one class, one reading and one frame that overlap or share a border become
  one polygon (see *Neighbours of one class are one polygon*). It is one step
  with the rest, Undo takes all of it back, and the message says how many.
- **Undo** takes back the last stroke, in the table the shape in hand writes to.
  Undoing a line takes away both the painted band and the trace recorded with it;
  undoing a point takes away the point. Undo reaches back to the last save. A
  save, by hand with **Save** or by itself with the autosave, closes QGIS's undo
  history, so a stroke that has been written to the package cannot be taken
  back with Undo: with the default of twenty strokes, the twentieth is written
  the moment it is drawn. A message in the bar says so when there is nothing
  left to undo. To be able to take back more, raise the autosave under Settings
  or set it to zero; the recovery file keeps the strokes that are not saved safe
  in the meantime.

### The rule that holds it together

**Every new mark wins over what is already there.** A stroke is clipped to the
frame and subtracted from everything underneath it, so two polygons can never share
ground and, once a background has been laid down, there are no holes either. The
partition is closed by construction, not by checking afterwards. What a stroke
leaves of a polygon already there stays a polygon of its own, however small:
only a new stroke under four pixels is taken for a fleck and dropped, so a
frame marked closed has no pixel of no class, and Fill Gap finds a hole of one
or two pixels instead of saying there is none.

While Annotate is open the project's *topological editing* and *avoid
intersections* are switched off, because the polygon tool decides overlaps by
itself. They are put back as the project had them when Annotate closes, and a
project read while it is open brings its own values back at the close. A
project saved while Annotate is open (Ctrl+S, QGIS's own project autosave, Save
As) is written with your own values, not with the two switched off.

**Neighbours of one class are one polygon.** Two or more polygons of the same
class, the same reading (operator and pass) and the same frame that overlap or
share a border become one polygon at the moment a new mark, Fill Gap or a moved
vertex makes them meet, in the same step on the undo stack: one Undo puts back
exactly the polygons that stood there before. In a campaign without frames the
same reading anywhere counts. Two polygons that touch at a single point stay
two, because their union would not be one polygon; polygons of another class,
another operator, another pass or another frame are never joined and never
touched, and neither are lines, points and the boxes of Objects. Nothing that is
measured changes: joining changes how many polygons there are, never which
pixel centres fall in a class, so every mask, vote, coverage, Compare, Time,
Model vs corrected, Cutouts and the pixel counts and areas of the dataset card
come out byte for byte the same with and without it (a suite burns a campaign
both ways and compares). What changes is the number of polygons the card
and Check count. The polygons table has `class_name`, `class_code`, `tile_id`,
`pass_no`, `operator` and `created` and nothing else, so there is nothing to
combine but one date: the joined polygon keeps the earliest `created` of its
parts, and everything else is the same on every part by definition. One more
case is left alone: when a polygon of another reading lies over the same
ground and the order the polygons were drawn in decides which of them shows in
"all readings together", the neighbours stay separate rather than change that
order. Campaigns are not rewritten when they are opened; **Repair** joins what
is already there, and **Check** says how many such neighbours it found.

**paint under the others** turns that around, and it is on by default with a lock
beside it. On, a new polygon yields to the polygons of other classes already there
and fills only what is still free. That is what you want almost always: you
overshoot on purpose across everything sharp you have already placed, and only the
free ground is taken. Holding **Shift** inverts it for one stroke. Open the padlock
if you really mean to change it.

For lines there is a separate choice: a line can cut over what it crosses, or go
under it and leave only the parts outside. Either way what is exported is what you
see.

### Settings

Only the ones the tool in hand actually reads are shown, and taking a tool opens
the settings by itself.

- **pass** is which reading this is. A second, independent pass over the same
  ground is how agreement between two readings is measured: **Measure ▾ ▸
  Compare two readings…** under ANNOTATION CAMPAIGN (see [Comparing two
  readings](#comparing-two-readings)). Passes are a list for each operator,
  as the operators are: a campaign starts with one operator in pass 1, the
  box offers only the passes that operator has, and the **+** beside it adds
  the next one. An operator you add starts at pass 1.
- **blind: show only this pass** shows the pass you are drawing and hides
  every other pass of that operator, the earlier ones and the later ones, so
  the new reading is not anchored by another. Untick it to see all the passes.
- **operator**, with a **+** to add one. Names are always capitals: the same person
  written two ways would otherwise be two people. The pass, the operator and
  blind are the reading the panel holds, the same one Objects draws with (see
  *Who is drawing* under [The panel](#the-panel)).
- **one operator at a time** shows and touches only your own work. It governs the
  brush as well as the view, so a frame somebody else has finished opens genuinely
  empty for you, and Fill Gap counts your reading alone: a frame can reach 100%
  for you with somebody else's polygons lying under it, hidden, untouched and
  perfectly correct. The amber strip says how many there are and who drew them.
  The coverage counts your reading alone whether or not this is ticked.
- **tile side**, **radius**, **line width**, **point size**: the number the tool in
  hand uses. A campaign you come back to starts at the point size most of its
  points already have, not at one pixel. The tile side and the radius step by
  one pixel of the raster, whatever its pixel is, from 2 mm to hundreds of metres, and on a picture
  with no coordinate system they count in px.
- **autosave**: strokes between one automatic save and the next. Zero turns it off.
  Objects has the same setting, counted in changes to the boxes. It is not the
  same thing as the recovery snapshot, which is written after every single
  stroke whatever this says.
- **a moved vertex wins**: dragging a vertex drags the border. The polygon you
  edited wins where you pushed into a neighbour, and the ground you stopped
  claiming goes to the neighbour sharing that stretch of border where you pulled
  away, so the frame stays a closed partition whichever way you drag. Ground
  somebody has painted in the meantime is never given away, and a hole in the
  middle of a polygon, bordering nobody, stays a hole. This happens in the frame
  of the polygon you dragged, whichever frame is selected in the list, and only
  among the polygons of its own pass and operator, whether or not "one operator
  at a time" is ticked. The tidying is one step of its own on the undo stack:
  Ctrl+Z takes it back first, then the drag. Off, nothing is tidied up and an
  overlap can survive.
- **keep a journal of working time**, on by default: every thing done adds a
  line to `journal.csv`, from which [How long it took](#how-long-it-took) is
  measured. Untick it and nothing more is written.
- **keep the view on the tile**, **only the current tile**: how much of the
  campaign you see while working one frame.
- **Import frames** takes frames from a vector file: a sample drawn in
  AcATaMa, in R or elsewhere, or the frames somebody else worked on. The design
  columns come along (see [Sampling designs](#sampling-designs)), every frame is
  put on the pixel grid, and every feature of the file gets a row in
  `design_log.csv`. A frame that would lie over another frame is refused, as a
  click there would be.

### Coverage

With a frame in hand the panel shows how much of it is painted, class by class, and
how much is still unpainted, in square metres. The share is measured on the union
of what is painted, not on the sum of the pieces, so two polygons that overlap each
other cannot push it past a hundred per cent and cannot have a frame with holes
still in it declared finished. It is the share of one reading, the operator and
the pass in the panel: two operators who have each painted sixty per cent of a
frame have not closed it between them. Above 99.5% in one reading the frame is
written down as closed, and Check measures it the same way. The yellow line
underneath always says the one thing worth doing next; with **one operator at a
time** off and the rest of the frame painted by somebody else in the same pass,
it says that, since Fill Gap then has no gap to fill, and that ticking the box
lets you paint the rest as your own. A quiet line under it says the active
time of the day, by the rule of [How long it took](#how-long-it-took):
"active 1 h 12 min today · this frame 6 min". With frames imported with a
design, another says the sample of the frame in hand ("sample S017 · stratum
3 · w 20").

### Sampling designs

RasterLabel does not draw samples and does not estimate accuracy or area:
AcATaMa and R (spsurvey, sampling, survey) already do that. It keeps the
sampling design through the annotation, so that whoever analyses it knows
exactly which drawn units were annotated, and how.

**Import frames**, under Settings, opens a window that asks three things and
shows what will happen before anything does:

- **The design.** Which column of the file is the *sample id*, the *stratum*,
  the *inclusion probability*, the *weight* and the *design*. The columns are
  guessed from their names (spsurvey's `siteID`, `stratum`, `ip`, `wgt`;
  sampling's `ID_unit`, `Stratum`, `Prob`; AcATaMa's `id`; `fid` is never
  taken) and can be changed. The stratum can also be read from a single-band
  raster of the project, at the middle of each frame: an AcATaMa sample layer
  holds only an id per point, and the stratum is the class of the map it was
  stratified on. The design can be typed ("stratified random, AcATaMa,
  n=120").
- **Frame side.** The side in Settings, or each shape's own side, offered
  first when every polygon of the file is square within a pixel. Points and
  lines always take the side in Settings.
- **What will happen.** "117 added: 12 moved onto the grid, 0 resized, 117 from
  points; 1 already there (t004); 2 refused: overlap with t004, t031", worked
  out again at every change. The key reads **Import 117**, and is grey when
  nothing would become a new frame.

Every value is carried exactly as given. A weight is not worked out from a
probability, a probability is not normalised, and a value that does not read as
a number (`1,000.5`, `abc`, a probability of 0 or above 1, a weight of 0 or
below) is left empty, with its text kept in the log. A comma is taken as the
decimal mark only when it is the one separator (`0,05`). A number a REAL column
holds whole, an id or a stratum of 12.0 (R and pandas write every id so), is
written 12; a true decimal keeps its digits. Frames written by an earlier build
as 12.0 and the same file imported again as 12 are the same sample.

The features are taken in the order of the file (fid ascending), and an earlier
draw wins: a unit whose frame would overlap a frame already there, or one
accepted before it from the same file, is refused. Sort the file first if
another order should win. A unit on exactly the square of a frame already
there is *already there* when it is the same sample, *completed* when that
frame had no design yet (its design columns are filled in), and refused as a
*duplicate* otherwise. A frame is put on the grid by rounding its corner half
up from the pixel edges, so a square already on the grid stays where it is. A
refused draw changes the inclusion probabilities of the sample annotated; the
window and Check say so, and the log names each one. For a point design the
frame is a block of pixels around the point, and the inclusion probability it
carries is the point's, not the frame's.

What is written:

- **the `tiles` table**: five columns, `sample_id`, `stratum` (text),
  `incl_prob`, `weight` (real) and `design` (text, 80 characters; the whole
  text is in the manifest), empty for frames placed by hand. A campaign made
  before gets the columns when it is opened. R reads them with
  `sf::st_read(".../annotation.gpkg", "tiles")`.
- **`design_log.csv`** in the campaign folder, append only: one row for every
  feature of the file at every import, written once the frames are on disk
  (`not_written` when the save fails), and one row each time a frame of a
  design is later moved or deleted. *outcome* is added, completed,
  already_there, refused, not_written, moved or deleted, and *reason* says why
  (snapped, resized, from_point, duplicate, overlap, outside_raster,
  no_geometry, bad_value:weight and the like), with the shape as it came and
  the frame as it was made, in the campaign's system with every digit.
- **`campaign.json`**, a `designs` list: per import its id, when, who, the file
  and its system, the columns chosen, the design, the side, the order rule and
  the counts.

The list of frames shows the design of a frame in its tooltip, and deleting a
frame of a design says which sample it takes out. **Check** says how many
frames carry a sample of how many designs, and notes an import that refused
draws, frames of a design moved or deleted after the import, and a weight that
is not one over the inclusion probability (said as a fact; nothing is changed).

---

## The other three modules

**Correct** works on a thematic map that already exists, made by any tool, and
needs no annotation campaign. Press **New** under CORRECTION (or **Open** for a
correction opened lately, or a `correction.json`; Correct with nothing open
asks for either): a name, the thematic map, its class band, the
folder it goes in and the operator. The band offered is the one the map's
style draws in classes (Paletted, or a pseudocolor ramp that is Exact or
Discrete; a stretch does not count), then the first whose name says
"class", then the first that carries an attribute table, a colour table or
category names, then band 1.
The classes are read from the map and
**shown before anything is made**, one row each: the value written in the map,
its colour, its name, how many pixels hold it, and where the reading came from
(the style, the attribute table of the file or its `.tif.vat.dbf`, its colour
table and category names, or the bare value). An entry of the style labelled
with its own number, which is how QGIS labels a colour table, counts as no
name: the file's own name for it is used, or "class 7". Change a colour or
a name, renumber a row, add a class the map does not hold yet. The window
refuses a name used twice, the nodata value as a class, and a value the map
holds left without a row. Renumbering a row points a name at another value: it
never recodes a pixel. Cancel, and nothing is written. Ok, and the map is copied
into the folder, band for band, and the copy is what the brush changes, never
the original; on the map it is drawn in the classes, see-through over the
image, and "show the original beside it" opens the map as it arrived in a
second view that follows this one. No
tiles here: the brush goes wherever the mistakes are. Useful for measuring how
much correcting a model's output actually costs. Every stroke turns one class
into another, and
the banner over the chips says which, in the two classes' colours: "FROM crops
➜ TO forest". The FROM chips choose what the brush changes, "any class" or a
single class (then every other class under the stroke is left alone); the TO
chips choose what it becomes. On the map, Ctrl+click picks FROM from the pixel
under the cursor and Shift+click picks TO. The TO chip in hand is ringed
thick in the colour of its own lettering, black on a light class, white with a
dark rim on a dark one, and ticked, so it shows on any colour. With any class,
only nodata is spared. You can hide the original, show it beside the
copy, and ask for a confirmation before each change. Its classes are the map's
own, not the campaign legend: they come from the layer's style when it is
Paletted/Unique values, with its names and colours, and from the values in the
band otherwise, confirmed by you, and kept in `correction.json`. "+" adds a class
the map does not hold yet, by its code, and **Classes** under CORRECTION opens
the confirmation window again, with the values the copy holds locked. **Set
aside**, in the module, closes the correction and renames its folder with
`.removed-<date>`; nothing is erased. A folder that also holds other work, an
annotation campaign made in the same folder for one, is not renamed: only the
correction's own files (the copy, its `.aux.xml`, `.qml` and `_changes.tif`,
`correction.json` and `operations.csv`) move into a `set_aside_<date>` folder
inside it, and everything else stays where it is. The legend and the Classes button under
ANNOTATION CAMPAIGN belong to Annotate and Objects. Under Save, the
UNCERTAINTY card can send you first to where the model was unsure (see
[Uncertainty](#uncertainty)); with nothing chosen it is one quiet line and
changes nothing. How far the model was from the map once corrected is under
[Measuring the model](#measuring-the-model).

**Objects** draws rectangles with a class on them, for detection training. Drag to
make one, click to pick it up, drag a corner to resize it. Every box is filed
under the reading the panel holds, shown above the tools with a **Change**
button; a box of another reading cannot be picked up, moved, reclassed or
deleted, and a press on it draws a box of your own. The reading filter of
Annotate covers the boxes too. **Save** says how it went in the message bar,
as in Annotate ("saved, 1 layer written", or "not everything could be saved"
with the reason), and Objects has the autosave setting of Annotate, counted in
changes to the boxes. The boxes leave the program in two ways. **Export** writes
them as polygons in the coordinates of the map, in the table `boxes`, in any of
its formats. **Cutouts** writes them as detection labels in the pixels of each
image it cuts: see [Boxes for detection](#boxes-for-detection).

**Cutouts** is for building a dataset. You have a ground truth layer and one or
more image layers, RGB or false colour; you pick a window and it writes one file per
layer ticked on the map (a layer unticked in the Layers panel starts as
"ignore", and **Layers** changes any of it), with a format chosen per layer.
A map a report loaded (the disagreement map of Compare, for one) starts as
"ignore" all the same: it is a picture of the work, not part of the dataset, and
**Layers** puts it in if you want it.
The layers are listed in the order of the Layers panel, top first, and
**Layers** shows which one sets the pixel grid and the coordinate system, and
lets you choose it. Systems are compared on the ground, so an image in WGS 84
written another way than its classes map in EPSG:4326 is cut with it, and every
file is written in the registered system. A layer whose system really is another
is reprojected onto the grid, and the message bar says so once; only a layer
with no system beside one that has one is left out, and the panel and the
"written" message say which and why. A layer that sits off the grid is
resampled by what it is: classes by the class most of a larger pixel holds, or
the one under the centre of a smaller one, so no code is ever invented; an
image is averaged onto a larger pixel and interpolated onto a smaller one,
each band with its own nodata. A layer stored bottom row first can set the
grid, and its cutouts come out top row first like every other, and a picture
with no georeference is cut on the grid QGIS draws it on; a layer on a
rotated grid cannot set it, since no cutout of whole pixels can be laid on
one. A click cuts
exactly the number of pixels the side box shows, centred on the click. It needs
no campaign and saves none; freehand rectangles work without one too. It can cut a single window and, with an
annotation campaign open, every frame of the campaign in one go, or the whole
raster. There is a common pixel grid option, a same size option, and a STAC
catalogue. The output folder is yours to choose; it, the side, the prefix and
the options are remembered by QGIS on this machine, not in any manifest. The
layers of a folder, which are cut as what, with which names and on whose grid,
are kept in the folder itself, in `layers.json` beside `cutouts.csv`, written
with the first cutout of a choice: choose the folder again, tomorrow, and it
is cut from the same layers, the first of them the grid, whatever is ticked on
the map. `layers.json` writes the paths of its layers from the Cutouts folder,
or from `~` when they are far from it, as the manifests do, so the folder can be
zipped and published without the name of whoever cut it. The layers are known
by the path of their file, so the record serves where the files are at the
places these paths lead to: on another machine, another drive or after the
files were moved, none of its layers is found, the record is left aside and the
layers are chosen from the map as for a new folder. A layer the
folder does not list stays out until **Layers** puts it in, and a change of
layers is said on the message bar before the cut it concerns. A cutout that
was being written when QGIS died is found by the note `cutting.pending` and
its files are taken away the next time the folder is opened, unless
`cutouts.csv` cannot be read at that moment, when they are left where they
are. The
number of pixels a side of so many metres comes out as is kept in
`shapes.json` in the output folder, so every cutout of that side in that
folder has the same size, with keys of their own for pixels measured in
degrees. **Undo** deletes the last cutout of the session: its files, its row,
its footprint in `cutouts.gpkg` and its place in `sampler.json`. Cutouts
deleted by hand are counted out and named on the panel and in the log; their
rows, footprints and STAC items are kept and their names are never used again.
With no campaign open, Cutouts writes `rasterlabel.log` into the `RasterLabel`
folder of your home, not into the Cutouts folder: the Cutouts folder is a
dataset, and a log in it would go with it when it is zipped and published. With
a campaign or a correction open the log stays beside it, as before.

With a campaign open that has boxes, **boxes for detection** (on by default,
under Settings) writes the boxes of Objects as labels for training a detector,
in the pixels of each image: see [Boxes for detection](#boxes-for-detection).

**Whole**, in Cutouts, shown when an annotation campaign is open, writes a whole
raster out with the annotation painted on it (its mask comes with the classes
of the campaign: inside a GeoTIFF as a colour table, with the names beside it
in the `.aux.xml`, and as a `.qml` that QGIS opens it with):
the image with the annotation over it, a mask of class codes, the plain image, or a
picture for a figure, at full size or scaled down. For work with no frames at all,
a river traced across a scene, a coastline, anything whose extent is the picture
itself. **Raster** starts on the reference raster of the campaign, else on the
first raster that is not a map of a report; the list is by name and holds the
maps of reports too, so check that it is the image you mean. The pictures are
what QGIS shows: each strip is drawn by the layer's own
style, its bands, stretch or palette, brightness, contrast and saturation. A layer
that can show anything see-through (an alpha band, nodata, a transparent class,
an opacity below full) gets an alpha band in its GeoTIFF and PNG pictures; a JPEG
holds none and has the transparent part on white. A rotated raster, which QGIS
draws on a grid of its own, is stretched from its bands instead, and its mask
follows the rotated grid. A picture with no georeferencing is written on the grid
QGIS draws it on, one unit a pixel and y = -row, so the files open over it. PNG
and JPEG are painted into a scratch GeoTIFF beside the file and copied out at the
end, so no picture is ever held in memory whole. **Readings** says whose work
goes in, the same choice as in Export: all the readings together, the latest drawn on top (right when the passes are layers
of one piece of work; when two operators read the same ground the second simply
erases the first wherever they differ, and the window says so), one reading, an
operator in a pass, or the consensus of the readings of a pass, or of every
reading. A consensus gives each pixel the class more than half of the readings
gave it, the class both gave it when there are two, and 0 where no class has a
majority. The readings counted are the ones that covered the frame the pixel
lies in (a reading covered a frame when it has a mark in it, finished or not):
in a campaign where every frame was read by two of four people, a frame needs
both of its two readers, not three of four, and a frame read by one person is
that person's. When everyone read every frame this is the plain majority of all
the readings, and the files are what they were. Ground outside every frame (a
free-hand campaign, or a stray mark outside the frames) is voted by the
readings that painted anywhere in the campaign. Beside the mask a `_votes.tif`
holds, pixel by pixel, how many readings gave it that class and how many
painted it at all; when some frame was read by fewer readings than the vote
holds, a third band, `readings_voting`, says how many readings voted at each
pixel, and the metadata item `RASTERLABEL_FRAMES_READ_BY` says how many frames
were read by how many readings ("1 frame by 1 reading, 3 frames by 2
readings"), with the rule in `RASTERLABEL_READING_RULE` worded for it. One reading and a
consensus are named in the files (`_ANNA_p1`, `_consensus_p1`; two readings
whose names would give the same file name get a number, `_ANNA_B_p1_2`), and every
GeoTIFF that comes out says inside it which readings it holds and how they were
put together (`RASTERLABEL_READING_MODE`, `RASTERLABEL_READINGS`,
`RASTERLABEL_READING_RULE`), with the build, the campaign and the pixel rule
(`RASTERLABEL_BUILD`, `RASTERLABEL_CAMPAIGN_ID`, `RASTERLABEL_PIXEL_RULE`).
**Where nobody painted** says what the mask holds there: 0, as before, or an
ignore value (see [Unlabelled pixels and the ignore
value](#unlabelled-pixels-and-the-ignore-value)). The last row of *What to
write*, *the dataset card, with the pixel counts of this mask*, writes a
[dataset card](#dataset-card) beside the files; it starts unticked, because it
counts every reading of the campaign at full size, which takes a while on a
large campaign, and the choice is remembered on this machine.

### Boxes for detection

With a campaign open that has boxes, and **boxes for detection** ticked under
Settings in Cutouts (it is, to begin with), each cutout also writes, for its
images (a layer cut as classes has none):

- `boxes_coco.json` in the cutouts folder, one book for all of it in the COCO
  form: `images` (file name, width and height in pixels, the cutout and the
  layer), `annotations` (`bbox` as `[x, y, width, height]` in the pixels of that
  image counted from its top left corner, `area`, `iscrowd` 0, and under
  `attributes` the operator, the pass, the frame and whether the box was
  clipped), `categories` (`id` the class code of the campaign, `name`, and
  `retired`) and `unlabelled_images`, below;
- `labels/<image>.txt`, one text file per image in the YOLO form, a line per box
  `index cx cy w h` with the four numbers as fractions of the width and height
  of the image; and `labels/classes.txt`, which names the indices.

The index counts the classes of the campaign from 0 in the order of their codes,
retired ones included, so that an index means the same thing in every export
and when a class is added later. A box that crosses the edge of a cutout is cut
to it and marked `clipped`; a box with less than a pixel left is not written.
The boxes are put in the system of the cutout when it is not the campaign's
(none is written, and the log says so, when they cannot be), and each image
counts in its own window, so a layer that keeps its own grid gets its own
numbers. A cutout keeps the boxes the campaign held when it was cut, like its
other files, and **Undo** takes it out of the book and its labels off the disk.

The box under the tick chooses whose boxes: *boxes of all readings together* or
*boxes of* one reading. Two people who boxed the same ground would otherwise put
every object in twice, so for a campaign read by several people choose one.

**Ground nobody read.** An empty label file says "nothing in this picture", and a
detector trains on it as a picture with nothing in it. Over ground that was read
that is true when no box was drawn; over ground nobody looked at it is not. In a
campaign with frames the ground that was read is the ground inside them, as for
the ignore value of Whole (see [Unlabelled pixels and the ignore
value](#unlabelled-pixels-and-the-ignore-value)). An image the frames cover is
labelled, with an empty file when it holds no box. An image they do not cover
(more than half a percent of it outside every frame) gets no label file and no
place among the `images` of the book; it is listed under `unlabelled_images`,
with its cutout, its layer, its size, the share of it the frames cover and why,
and the log says how many were left out. Leave those images out of training:
a YOLO tool reads a picture with no label file as a picture with nothing in it
too, so the list is the way to tell them apart. A campaign without frames has no
unread ground to tell apart, and every image gets its file.

`labels/` is the folder the YOLO tools call the labels; they find it beside an
`images/` folder, so move the images there, or point the dataset file at both.

### Mouse and keys

What the map does under each tool. Ctrl is the Command key on a Mac, and the
hints in the program call it Cmd there.

| tool | left click or drag | right click | with a key | keys |
|---|---|---|---|---|
| Polygon | click by click, or hold and draw freehand; a click on the first vertex closes | closes the outline | Ctrl+click: the polygon under the cursor takes the class in hand; Shift: paints over the others for this one stroke | Enter closes, Backspace takes back the last vertex, Esc throws the outline away |
| Round | hold and paint | | Ctrl+click and Shift as for Polygon | Esc throws the stroke away |
| Line | click by click, or hold and draw | finishes the line | | Enter finishes, Backspace takes back the last vertex, Esc throws it away |
| Points | drops a point | takes back the point under the cursor | Ctrl+click: the point under the cursor takes the class in hand | Esc goes back to the polygon |
| Tiles | on empty ground places a frame, inside one picks it up | | | Esc goes back to the polygon |
| Move | drag a frame | | | |
| Objects | drag draws a box, a click picks one up, a corner drags to resize | puts the box in hand down | Ctrl+click: the box under the cursor takes the class in hand | Delete or Backspace deletes the box in hand, Esc puts it down |
| Correct | a stroke changes FROM into TO | | Ctrl+click picks FROM, Shift+click picks TO, from the pixel under the cursor | Esc throws the stroke away |
| Cutouts | a click cuts a square of the side, centred on it; a drag cuts the rectangle | undoes the last cutout | | Esc stops cutting |

With *keyboard* ticked under VIEW, the arrow keys move the map, Shift and an
arrow three times further, and PageUp and PageDown zoom. Ctrl+Z is QGIS's own
undo, on the layer being edited; **Undo** in a module takes back its last
stroke.

---

## Measuring

A labelled dataset goes into a paper with numbers beside it: how far two
people reading the same ground agree, how long the drawing took, how far a
model was from the map once a person had corrected it, whether the model's own
uncertainty pointed at its mistakes, and how many pixels of each class there
are. **Measure ▾**, in ANNOTATION CAMPAIGN and in CORRECTION, writes each of
these from what is already in the campaign or the correction.

| Measure ▾ | in | what it answers |
|---|---|---|
| Compare two readings… | ANNOTATION CAMPAIGN | how far two readings of the same frames agree, and where they differ |
| Time… | both | how long the drawing took, per frame, class and hectare, and from scratch against correcting |
| Model vs corrected… | CORRECTION | how far the model was from the corrected map, class by class |
| Uncertainty report… | CORRECTION | how often a person changed the class where the model said it was unsure |
| Dataset card… | both | what the dataset holds: pixels per class and reading, frames, who drew what, the rules, the build |

What they have in common:

- **Nothing drawn changes.** The work is saved first, and a measure is
  refused while something could not be saved; then the package and the copy
  are only read, and the manifest gains at most the entry of the report.
- **Every report is a folder of its own**, `reports/<kind>/<label>_<stamp>/`
  (or `reports/<kind>/<stamp>/`), in the folder of the campaign or of the
  correction. It is written under a name ending in `.tmp` and renamed when it
  is whole, so a report that stopped half way never looks finished, and it is
  never written over: a second run makes a second folder. Compare, Time and
  Model vs corrected let you type another folder.
- **The tables are plain**: CSV in UTF-8, comma separated, a point for the
  decimal, an empty cell for a value that is not there, and a text that
  begins with `=`, `+`, `-` or `@` starts with a single quote, so that a
  spreadsheet shows it and does not run it (numbers are left as they are, and
  the program takes the quote off again when it reads its own files); JSON with
  the same
  header in every `summary.json` (what made it, which build, when, of what),
  the inputs with their SHA-256, the parameters, the numbers, and the
  sentences that qualify them. The figures of a paper are drawn from these,
  outside the program.
- **The maps are styled**: every raster or vector a report writes has a
  `.qml` beside it, a byte raster carries its colours and names inside as
  well, and *put the maps in QGIS* loads them into a group of their own under
  the campaign's or the correction's. A map is named for what it is, so it
  still says so once copied out of its folder.
- **A blind reader is not shown what blind hides.** A measure that would show
  a reading the person drawing may not see (by the rule of Annotate's filter,
  *one operator at a time* and *blind*) is refused, with what, why and the way
  out. This is a guard for a shared desk, not a lock: the files are in the
  folder.
- **A report window** shows the headline numbers of Compare, Time, Model vs
  corrected and the uncertainty report, with **Copy** (the tables as text, for
  a spreadsheet) and **Open folder**, and those four are listed in the
  manifest's `reports`. Check says when a file of a report is gone, or when
  the newest report is older than the work it measured. The dataset card is
  only an information box, and the manifest is not told of it.

### From Processing, a model or a script

Everything under Measure is also in the Processing toolbox, under RasterLabel,
group Measure, so the numbers of a paper can be made again without the panel,
from Model Designer, in a batch or in a script:

| Algorithm | Same as | Main parameters | Numbers it returns |
|---|---|---|---|
| `rasterlabel:agreement` | Compare two readings | `CAMPAIGN`, `READING_A`, `READING_B`, `FRAMES`, `RESAMPLES`, `SEED` | `OVERALL`, `KAPPA`, `QUANTITY`, `ALLOCATION`, `MEAN_IOU`, `FRAMES_USED` |
| `rasterlabel:model_vs_corrected` | Model vs corrected | `CORRECTION`, `SCOPE` (whole map, ground swept, inside the polygons), `POLYGONS`, `SELECTED_ONLY`, `PEOPLE`, `WRITE_MAP` | `OVERALL`, `QUANTITY`, `ALLOCATION`, `PIXELS`, `SUMMARY`, `PAIRS_MAP` |
| `rasterlabel:time_report` | Time | `OWNER` (campaign or correction), `PAIRED_WITH`, `READINGS`, `IDLE_S`, `FRAMES` | `ACTIVE_H`, `MIN_PER_HA_SCRATCH`, `MIN_PER_HA_CORRECT`, `RATIO`, `FRAMES_USED`, `SUMMARY` |
| `rasterlabel:uncertainty_report` | Uncertainty report | `CORRECTION`, `DRAW` | `AUC`, `AUC_RANDOM`, `AUC_WHOLE`, `ECE`, `ECE_RANDOM`, `ECE_WHOLE`, `RANDOM_DONE`, `SUMMARY` |
| `rasterlabel:dataset_card` | Dataset card | `OWNER` | `CARD_MD`, `CARD_JSON` |

Each is the engine of its window in the panel, handed the same recipe, so the
numbers are the same. All of them take `OUTPUT_FOLDER` (empty: a new folder
under `reports/` of the campaign or the correction) and return it as
`OUTPUT_FOLDER`. A campaign or a correction is named by its folder, or by its
`campaign.json` or `correction.json`.

```python
import processing
r = processing.run("rasterlabel:model_vs_corrected", {
    "CORRECTION": r"D:/work/aragona_corrected", "SCOPE": 0,
    "OUTPUT_FOLDER": r"D:/paper/tables/mvc"})
print(r["OVERALL"], r["QUANTITY"], r["ALLOCATION"])
```

What they read they only read: the campaign's `campaign.json`, its GeoPackage
and its journal, the correction's `correction.json`, working copy, record of
changes and files of uncertainty keep their bytes and their time. They never
write the manifest: the report is not listed in it, which the panel does for
the four that have a window. The checks of the panel are made too, in the same
words: a campaign with no journal, an uncertainty that is not chosen, a map the
model made that is gone, and, with the panel open on the same campaign, a
reading hidden from the reader the panel holds, which refuses the dataset card
of that campaign. `rasterlabel:uncertainty_report` never makes the file of
uncertainty: if it is missing or out of date it says so and asks you to open
the correction in Correct once. The example for `rasterlabel:agreement` is
under [Comparing two readings](#comparing-two-readings).

### Comparing two readings

**Measure ▾ ▸ Compare two readings…** in ANNOTATION CAMPAIGN puts two readings
of the same frames side by side. A reading is one operator in one pass (ANNA,
pass 1). The entry is grey, and says why, while the campaign holds fewer than
two.

The window asks four things:

- **Which readings.** *Two operators, one pass (inter-observer)* lists the
  pairs of people who read the same pass; *One operator, two passes
  (intra-observer)* the same person in two passes; *Any two readings*
  everything else. A and B are picked from those lists. Intra-observer
  agreement means something only if the later pass read the ground again from
  scratch, with blind on; leave at least two days between the two (the report
  gives the delay it measured).
- **Which frames.** *closed by both readings* (the default) compares only the
  frames each reading closed, more than 99.5 % of the frame painted, the same
  rule as Annotate's coverage and Check. *touched by both readings* compares
  every frame both drew in, and whatever a reading left empty counts as
  unlabelled. The counts beside each choice, and the frames left out with the
  reason (`t007 (B 81.0 %)`, `t012 (only A)`), follow every change. A campaign
  with no frames is compared as one region, with no spread and no interval:
  one region is not a sample of frames.
- **What counts.** Off by default, *the points, as in the mask* lays every
  point's footprint over the areas, as Whole raster can. Boxes and line traces
  are never compared (the band a line claims is in the polygons, and is).
- **Uncertainty.** *Resamples* (2000) and a *Seed* (1) for the interval.

What is compared is exactly what Whole raster writes as one reading at full
size: each frame is burned on the campaign's own grid, a pixel taking the
class of the polygon its centre falls in. **Compare** writes, in
`reports/agreement/<A>_vs_<B>_<YYYYmmdd-HHMMSS>/`:

| file | what it holds |
|---|---|
| `summary.json` | every number below, the parameters (frame rule, seed, resamples), the readings with their first and last mark, the frames used and left out with the reason, the grid, the notes, the files |
| `confusion.csv` | the pooled matrix, A in rows and B in columns, with unlabelled (0) as a row and a column of its own; pixels, then m² |
| `confusion_by_frame.csv` | the same, long, frame by frame, and pooled as `ALL` |
| `per_class.csv` | per class: pixels of A, of B and of both, IoU and F1 (Dice) with their interval, the median and quartiles of IoU over frames, agreement seen from A and from B, quantity, allocation, exchange and shift |
| `per_frame.csv` | per frame: used or why not, its share and coverage for each reading, the counts, overall agreement, kappa, quantity, allocation, mean IoU, and the hours between A's last mark and B's first; with the sample columns when the frames carry a design |
| `pairs.csv` | the legend of the map of pairs, with the pixels of each pair |
| `<campaign>_agreement_<A>_vs_<B>_disagreement.tif` | 1 agree, 2 disagree, 3 only A painted, 4 only B, 5 neither; 0 outside the frames compared |
| `<campaign>_agreement_<A>_vs_<B>_pairs.tif` | which class of A met which class of B, the value 1 + i·K + j over the codes, unlabelled included |
| `<campaign>_agreement_<A>_vs_<B>.gpkg` | `disagreement`, one polygon per connected place where the readings differ, with both classes, pixels and m²; `frames`, every frame with its numbers |

Every number is given three ways: pooled over the pixels (every pixel weighs
the same), as the median and quartiles over frames (every frame weighs the
same), and with a 95 % interval from a bootstrap that resamples whole frames,
never pixels, since neighbouring pixels are not independent. Below five frames
there is no interval. Frames are seldom a random sample: the interval says how
much the result varies across these frames, not over a population.

Cohen's kappa is reported as an agreement statistic between two readings, and
always beside quantity and allocation disagreement (Pontius and Millones
2011); it is not a measure of accuracy (Foody 2020). Quantity plus allocation
is one minus the overall agreement; allocation splits into exchange and shift
(Pontius and Santacruz 2014).

Rates, IoU, F1 and kappa are computed over the pixels **both** readings
painted; the pixels only A painted, only B painted, and neither painted are
counted apart, and `with_unlabelled` in `summary.json` repeats Po and kappa
with unlabelled as a class of its own. In `per_class.csv`, quantity,
allocation, exchange and shift are the by-category components of Pontius
(2019) and add up to twice the overall values (the Model vs corrected report
writes the halved contribution of each class, which adds up to the overall
values; both say so in their notes). Every formula, its population and its
references are in [docs/methods.md](docs/methods.md).

The maps go into a group `agreement <A> vs <B>`, the disagreement map and its
polygons on, the pairs and the frames off. A reading with frames touched but
not closed is named, with its frames, and Compare asks before going on, Cancel
first: whoever is still reading must not see the map. Report maps showing a
reading that becomes hidden are switched off, and the amber strip says so.

On Windows, **Compare** is grey, with a note under the folder, when the
GeoPackage of the report would be on a path QGIS cannot open and edit (249
characters or more): choose a shorter folder, typed or picked with the button
beside the folder, or move the campaign closer to the root of the drive.
Nothing is written. The same holds for the map of the frames of **Time**.

**In the Processing toolbox.** The same report is the algorithm *RasterLabel ▸
Agreement between two readings* (`rasterlabel:agreement`), for Model Designer,
batch runs and scripts:

```python
processing.run("rasterlabel:agreement", {
    "CAMPAIGN": r"...\aragona_2025\campaign.json",
    "READING_A": "ANNA,1", "READING_B": "BRUNO,1",
    "FRAMES": 0,            # 0 closed by both, 1 touched by both
    "POINTS_IN": False, "RESAMPLES": 2000, "SEED": 1,
    "ALLOW_UNFINISHED": False,
    "OUTPUT_FOLDER": None})  # None: reports/agreement/ in the campaign
```

It returns the maps, the GeoPackage, `summary.json` and the numbers OVERALL,
KAPPA, QUANTITY, ALLOCATION, MEAN_IOU and FRAMES_USED. CAMPAIGN is the folder of
the campaign or its `campaign.json`, as in the other four algorithms. It only
reads the campaign (the manifest as JSON, the GeoPackage opened read only) and
does not list the report in `campaign.json`. With an unfinished reading it refuses
unless ALLOW_UNFINISHED is set, and with the panel open it refuses what the
panel would refuse.

### How long it took

RasterLabel keeps a journal of working time, so the minutes a frame cost can
be reported without a stopwatch and without anybody writing down hours.

**What is recorded.** Every saved action adds one line to `journal.csv`
beside the campaign, or beside `operations.csv` in a correction: a stroke, a
line, a point, a box placed, reshaped, reclassed or deleted, Fill Gap, Repair,
a vertex that moved a border, a frame placed, moved, deleted or imported, a
stroke of Correct, an undo, a stroke thrown away with Esc or refused, a class
chosen, a change of pass or of operator, a save. Each line says when the
action ended (in UTC, and on the computer's monotonic clock), how long the
stroke took from the first press to the last release, the pauses of 10 s or
more inside it, who drew it, in which pass, on which frame, of which class,
how large and where. Two more kinds of line say only that the map was being
looked at (at most one every 5 s while the view moves) and that QGIS went to
the background or came back. Nothing else is recorded: no keys, no mouse
tracks, no screen. Writing a line takes about a tenth of a millisecond, never
stops the work, waits in memory while the file is locked, and a QGIS killed
outright leaves every line it wrote.

**When it starts.** No stopwatch runs in the background. A campaign or a
correction gets its journal at the first thing really done in it, and only
then is a `"journal"` block written into its manifest, with the moment of its
first line. Opening a campaign, or looking at it, writes nothing, and a
campaign made with an earlier build opens exactly as it was. The time spent on
it before the journal began is *not recorded*: the report lists those frames
with their time empty and `journal = 0`, never as zero seconds, and Check
counts the marks drawn before the journal began. To switch it off, untick
*keep a journal of working time* under Annotate's Settings: nothing more is
written, and the manifest says `"on": false`.

**The rule.** Active time is the sum of the strokes less their pauses longer
than the idle limit, plus the gaps between consecutive lines no longer than
it; a longer gap, or one while QGIS was not the active application, is idle.
A gap is given to the next mark (its class and frame); what is left when the
work stops or the frame changes is overhead of the frame in hand. The idle
limit is 60 s unless chosen otherwise, and 30, 60 and 120 s are always written
as well, so a conclusion can be shown not to hang on the limit. The quiet line
under the coverage in Annotate, and under the tally in Correct, is the same
rule at 60 s.

**The report.** **Measure ▾ ▸ Time…**, in either block. The window asks for
the readings *Drawn from scratch*, a correction to set against them under
*Corrected* (✓ on the campaign's grid; ⚠ the same coordinate system with
pixels not aligned, frames paired by position; ✘ another system, no pairing),
*Which frames* (*every frame read*, *closed only*, *drawn and corrected*) and
the idle limit. **Write** makes `reports/time/<YYYYmmdd-HHMMSS>/`:

- `time_per_frame.csv`: one row per source (scratch or correct), reading and
  frame: the frame's area, marks, undos, refused strokes, coverage and closed,
  the ground changed (correct), drawing, lead and overhead time, active time
  and minutes per hectare, active time at 30, 60 and 120 s, wall time, first
  and last moment, `journal` and `estimated`. One row per observation, ready
  for a paired test or a mixed model; the sample columns are added when the
  frames carry a design.
- `time_per_class.csv`: the same per class, with class 0 "(no class)" for the
  overhead, and each reading pooled over the frames (`tile_id = *`). A frame
  has its "(no class)" row whenever there is overhead at the chosen limit or at
  30, 60 or 120 s, so the classes of a frame add up to its time at every limit.
- `time_paired.csv`, with a correction: drawing from scratch against
  correcting, frame by frame
  (ratio, log ratio, saving, and the ratio at 30, 60 and 120 s), and a pooled
  row: the geometric mean ratio, the median ratio, its 95 % frame bootstrap
  interval (none below five frames) and the Wilcoxon signed-rank p. The p is
  exact for up to 25 non-zero log ratios (the full null distribution on
  mid-ranks, zeros dropped, as scipy's `wilcoxon(method="exact")` gives for
  data without ties) and, above 25, the normal approximation with continuity
  and tie corrections (scipy's `method="approx", correction=True`; scipy's
  default has no continuity correction and uses its exact test up to 50
  values). The ratio is the geometric mean of the per-frame ratios; the frames
  are resampled in the order of their ids as text, which fixes what a seed
  gives.
- `time_frames.gpkg` and its `.qml`: the frames with their minutes per
  hectare, in graduated colours, loaded into the group "time <stamp>". The map
  of the frames is a GeoPackage, so the path it would be written to is held to
  the length of the note under Compare: past 248 characters on Windows, Write is
  grey and says so.
- `time_summary.json`: the rule in words, the inputs with their SHA-256, the
  readings and the correction, the frames used and skipped and why, the
  totals and the 30/60/120 s table, warnings, and notes on the design.

A correction made before the journal existed has only `operations.csv`, which
records the end of each stroke to the second: its time is *estimated* from
the gaps between rows (`estimated = 1`), and the report says so.
`operations.csv` itself is unchanged.

**A design for drawing against correcting.** The unit is the frame, and one
operator meets a frame once, from scratch or correcting. Split 2N frames into
two sets matched by stratum; one group draws the first set from scratch and
corrects the second, the other group the reverse, and half of each group
starts with scratch. Those drawing from scratch do not see the model's map,
and draw in a pass of their own with *blind* and *one operator at a time* on.
Analyse the per-frame log ratio with its bootstrap interval, and, outside the
program, `ln(active_s) ~ condition + order + ln(frame_ha) + (1|operator) +
(1|frame)` from `time_per_frame.csv`, again at 30, 60 and 120 s. With a paired
SD of 0.6 on the log scale, halving the time needs about 6 frames and a 30 %
saving about 23; plan at least 12 frames per operator and condition.

**Consent.** The journal is a record of how fast a person works. Tell the
people who draw that it is kept, prefer pseudonymous operator names, and
switch it off where it is not wanted.

### Measuring the model

Once a map a model made (a random forest, SAM, GeoAI, anything) has been
corrected in Correct, RasterLabel can say how far the model was from the
corrected map, class by class. The corrected map is the reference: the rows
of the matrix are the model, the columns the corrected map (the orientation
of Olofsson et al. 2014).

**Measure ▾ ▸ Model vs corrected…** in CORRECTION. The entry is grey, and
says why, when the map the correction started from is no longer where it was,
or no longer on the grid of the copy. That map may have had its coordinate
system set in QGIS (Set Layer CRS) rather than in the file: the copy carries
it, and the window and the Processing algorithm accept it. The window asks:

- **Which ground**, each with what it is biased towards:
  - *the whole map*: every pixel both maps hold. Ground nobody looked at counts
    as right, so the model's accuracy here is an upper bound;
  - *the ground the strokes swept*: the pixels a stroke of Correct went over
    (`_reviewed.tif`), and the pixels marked as changed. Strokes go where the
    model was wrong, so this is a purposive sample and the accuracy here is a
    lower bound;
  - *inside the polygons of a layer* (a sample of frames reviewed whole, for
    one; *selected polygons only* if you want): one matrix per polygon as
    well, and with five polygons or more an interval over the polygons
    (percentile bootstrap, 2000 resamples, seed 1). The window says how much of
    the ground inside them was swept. Only polygons drawn by a probability
    design and swept whole support an estimate for the whole map.
- **Beside it: people against people**, optionally: another person's
  correction of the same map, compared on the very same pixels (it must be on
  the same grid, and it is asked about first, because comparing ends the
  blindness of whichever correction is still going; only its numbers are
  shown, never its map), or the agreement report of an annotation campaign
  (its `summary.json`, from Compare two readings), which is on other pixels
  and is matched class by class by name, then by code; classes nobody matched
  are listed. Per class, `excess_error = (1 - IoU of the model) - (1 - IoU of
  the people)`: above 0, the model's error is beyond what two people disagree
  on.
- **What to write**: the tables always, and *the map of what changed, styled
  for QGIS*, with *put the map in QGIS*.

**Compare** writes `reports/model_vs_corrected/<whole|swept|polygons>_<YYYYmmdd-HHMMSS>/`
in the correction's folder:

- `confusion.csv`: the matrix in pixels with its totals, then in m²;
- `per_class.csv`: pixels and m² of the model and of the corrected map, the
  net change, producer's and user's accuracy (and omission and commission),
  IoU, F1, the quantity and allocation disagreement of the class; with
  polygons, the interval of IoU and F1; with people, their IoU and F1 and the
  excess;
- `pairs.csv`: every pair of classes met, its value in the map, pixels, m²,
  share of the ground and of the model's class, and the strokes and m² the log
  has for the same FROM ➜ TO;
- `side_by_side.csv` (with people), `polygons.csv` (with polygons), and
  `summary.json`: the inputs with their SHA-256, the headline, the overall
  numbers (overall agreement, quantity, allocation, the net changed pixels and
  m², pixels changed and changed back, nodata that does not match, values that
  are not a code), the figures of the log, the people, and the sentences that
  qualify it all;
- `<map>_corrected_mvc_<scope>_pairs.tif` and its `.qml`: the map of pairs,
  `1 + i*K + j` for the model's class i and the corrected map's class j, 0
  outside the ground measured and on nodata.

The report window shows the ground, how much the model agrees, the
disagreement split into quantity and allocation, a table per class (IoU, PA,
UA, F1 and the people's IoU) and what changed most. The newest report also
gives a quiet line under the tally of Correct ("last measured, ground swept:
the model agrees on 77.8 % of 9 px").

**No kappa for the model.** Kappa is no measure of a map's accuracy (Pontius
and Millones 2011; Foody 2020): it is reported only between people, as an
agreement statistic, always beside quantity and allocation.

**Net and gross.** The figures the log keeps as each stroke is made (the
operations, m² changed, m² swept) are gross: an undone stroke keeps its row,
and the report says how many were undone and how much of the logged ground
that was. The report's net figures are read from the pixels, so a pixel changed
and changed back counts as agreeing, and is counted apart. The two are written
side by side and never mixed. A correction made before the record of the
ground swept existed starts it at its next stroke; on the swept ground only the
pixels the earlier strokes changed count for them, and the report says so.

**Areas on a map in degrees.** On a map in degrees or in Web Mercator the pixel
is not the same ground in every row, so every area in m² of the report (the
scope, the classes, the confusion matrix, the net change, each transition and
each polygon) is the ground its pixels cover, row by row, as Correct measures a
stroke, and the report says so in its notes. On a map in UTM or in any other
metric system it is the pixels times the pixel, as it always was. The dataset
card of a campaign measures the m² of each class of each product the same way.

### Uncertainty

Many models write more than the class of a pixel: the probability of the
class they chose, the entropy of their scores, or the margin between the two
best classes. A consensus of readings from Whole raster writes how many
readings voted for the class (`<stem>_votes.tif`). Correct can use any of
these to send you first to where the model was unsure, and measure afterwards
how often a person had to change the class there. RasterLabel runs no model:
it reads the number the model left.

**The card.** In Correct, under Save, the card *UNCERTAINTY*. With nothing
chosen it is one quiet line and nothing else changes: no file, no layer, no
line in the manifest. When a band of the map is named like an uncertainty
(`probabilita x255`, `entropia x255`, `margin`, `conf`, `std`...), the card
says so and offers **Use it**. **Source…** opens *Uncertainty of the map*:

- a band of the map, or another raster on the same ground (one half a pixel
  off the grid is read nearest neighbour, after a warning; one in another
  coordinate system is refused);
- *What it holds*: the probability of the class (read as 1 - p), an entropy
  from 0 to 1 (an entropy in nats can be divided by ln K), a margin p1 - p2
  (read as 1 - margin), a ready-made uncertainty, or the votes of a consensus
  (read as 1 - votes / readings, offered only for a raster with the bands
  `votes` and `readings_labelled`);
- *Scale*: 0-1, x100, x255, x10000, x65535 or a number of your own;
- a line that shows how it reads: the range of u, its median and the share of
  the map that has a value.

The list of other rasters leaves out the maps a report loaded (the
disagreement map of Compare, the pairs of Model vs corrected): they are a
picture of the work, never the uncertainty of a map. The uncertainty read from
the votes of a consensus is 1 - votes / readings labelled, where "labelled"
counts the readings that painted the pixel. In a frame that only one reading
covered, the class that reading gave has 1 vote of 1 and an uncertainty of 0:
the figure says how far the readers of the frame agreed, not how many readers
there were. The third band of the votes file, `readings_voting`, says how many
there were.

It is read once into `<map>_corrected_uncertainty.tif` beside the copy, one
byte per pixel: 0 to 254 for u from 0 to 1, higher meaning less sure, and 255
for no value, with the formula written into the file. It is made again when
it is missing or older than the raster it was read from. The file is not held
in memory: the walk, the places and the report read it a window or a strip at a
time, so a map of hundreds of millions of pixels needs a few hundred megabytes
for them, besides what QGIS holds.

**Places.** The map is cut into fixed squares, *places*, of 256 pixels a side
by default (more on a very large map), and the places with at least half of
their pixels valued are ranked by their mean u. The card walks them: **Start
▶**, then **Done, next ▶** once you have looked at every pixel of the place and
mended what was wrong, **Skip** for a place you did not review, and **◀** to
look back without marking anything. *show it on the map* draws u over the
classes, multiplied in, so the classes darken where the model was unsure and
stay as they are where it was sure. The places are a layer of their own (the
one in hand outlined, done grey, skipped dotted, the next ones dashed), kept in
`uncertainty_places.csv` and `.geojson`, and a stroke made while a place is in
hand is written in `journal.csv` with the place.

**Random places.** One place in five (*1 in*, settable, 0 for none) is drawn
instead from a seeded random permutation of all the places: a simple random
sample of places without replacement. The seed is written in the manifest,
taken from the correction's id unless you set one. Only these places carry an
inclusion probability, m/N; the places chosen because they were uncertain are
purposive, and every file labels them as excluded from design-based
estimators. A random draw that falls on a place already done as purposive
joins the sample as it is, and is flagged as not reviewed blind. *blind: hide
the uncertainty while reviewing* (on by default) keeps u and the reason a place
was chosen out of the card and the places layer while places remain.

**The report.** **Measure ▾ ▸ Uncertainty report…** in CORRECTION, or
**Report…** on the card, with Correct open and an uncertainty chosen. It
changes nothing in the map and writes `reports/uncertainty/<YYYYmmdd-HHMMSS>/`:

- `calibration.csv`: the share of pixels a person changed, per decile of u
  and per tenth of its scale, for the random places (with the standard error
  of the cluster ratio estimator, places as clusters, with the finite
  population correction, and a 95 % interval), for the purposive places (the
  same number, labelled a spread between places and not a design-based error)
  and for the whole map (a lower bound: what nobody reviewed counts as
  right); the net change beside it; and the model's own expected error when u
  is 1 - p;
- `capture.csv`: how much of the change the most uncertain 1, 2, 5, 10, 20,
  30, 50 and 100 % of the map hold;
- `places.csv`: each place done, its mean u, the pixels changed, who, and
  whether the uncertainty was on the map;
- `strokes.csv`: each stroke of `operations.csv` with the place it was made
  in and u over the pixels it changed (`operations.csv` keeps its 14 columns);
- `calibration.png`, the curve, and `summary.json`: the AUC of u as a
  detector of the changed pixels, the ECE when u is 1 - p, the places done,
  drawn and skipped, the record of changes checked against the net change, and
  the sentences that qualify it all.

ECE uses ten equal bins of u (tenths of the scale, the last one closed) and the
mean u in each as the stated error. The 95 % interval of the share changed is
`share ± 1.96 SE` (normal, optimistic with few places) cut to 0..1, with the
finite population correction `1 - m/N` for random places, m being the places
done. The inclusion probability m/N counts places drawn, done or skipped;
because m depends on when the review stopped and on how many draws fell on
places already visited, the random places are a simple random sample only
approximately.

The report is refused, with the reason, when the record of changes was started
again after the strokes it should hold. Check says which uncertainty a
correction reads, whether its file is up to date, and how many random places
were reviewed with the uncertainty shown, and so does the tooltip of the
correction's line in the panel.

**Limits.** Changed is not the same as wrong: a pixel changed and changed back
stays marked as changed (the net share is given beside it). Inside a place
done the review is taken as complete. The inclusion probability m/N is
conditional on when the review stopped, which the report says. RasterLabel
does not estimate areas or accuracy for the whole map from the sample; for
that use a tool built for it, such as AcATaMa.

### Dataset card

A dataset card is one file for people, `<name>_card.md`, and one for programs,
`<name>_card.json`, that answer what a reviewer or a data user asks first:
how many pixels of each class there are, in each reading and in the
consensus; who drew what, in which pass; how many frames are complete, and by
whose reading; what rule turned the polygons into pixels and which value means
unlabelled; which build of RasterLabel made it, on which grid and in which
coordinate system. It is in the spirit of datasheets for datasets (Gebru et
al., 2021) and data cards (Pushkarna et al., 2022).

**Measure ▾ ▸ Dataset card…**, in either block. There is nothing to choose:
the work is saved first, the counting shows its progress in the status bar,
and an information box says where the card went and what it holds. It goes in
`reports/card/<YYYYmmdd-HHMMSS>/`. A blind reader is refused a campaign's
card, because it shows every reading's counts.

**A campaign's card holds:**

- the classes, and how many pixels each holds in every reading, in all the
  readings together and in every consensus: the same products the Export and
  Whole raster windows offer, with the same names. Each is burned with the very
  code that writes the masks, on the campaign grid at full size, by pixel
  centre, strip by strip; areas in m² beside the pixels (on a map in degrees or
  in Web Mercator the ground of a class is the sum of the ground each of its
  pixels covers, row by row on the ellipsoid, as Correct measures a stroke; on a
  map in a metric system it is the pixels times the pixel, as it was), and the
  share of each class. A consensus also gives how many pixels k of n readings
  agreed on, how many have no majority, and how many of those every reading
  painted differently (with four readings or more the card does not say
  "differently", since two and two is no majority either). When some frames were
  read by fewer readings than the consensus holds, the majority is taken among
  the readings of each frame, the card says `partial_design` and how many
  frames were read by how many readings, and the sentence under the table says
  the same in words;
- the readings: operator, pass, how many polygons, lines, points and boxes,
  and how many frames each touched and completed (the polygon count is of
  polygons as stored, neighbours of one class being joined as they meet, so it
  is not the number of strokes);
- the frames: how many, how many are closed as stored and as measured now, and
  any frame where the two differ (press Save in Annotate). Each frame with each
  reading's share and pixels per class;
- the rules, as sentences: pixel centre; 0 is unlabelled; codes 1 to 254, 255
  kept; inside one reading the last drawn wins; every reading together, the
  mark stored last wins; a consensus is a strict majority of the readings that
  covered the frame; lines are never in the mask; points only when asked;
- the software (version, build fingerprint, QGIS, Qt, GDAL, numpy, Python,
  system), the grid (system, origin, pixel, size, the reference raster and
  whether it is there; a reference raster stored bottom row first is
  recognised as on the campaign's grid, and its size is used) and the SHA-256
  of the package;
- the fields of the STAC label extension (`label:classes`, `label:overviews`
  with the real pixel counts, `label:type` raster, `label:methods` manual,
  `label:tasks` segmentation);
- the headline numbers of the agreement and time reports of the campaign,
  copied, never computed again, each with its source, and marked "(may be
  stale)" when the package has changed since;
- what the card does not say: the counts are pixels on the campaign grid,
  areas in degrees are approximate, kappa is only an agreement statistic, and
  operator names are personal data (they are already in the package).

**A correction's card holds** the classes before (the map as it came) and
after (the working copy), the change per class, the pixels a person changed
and from what into what, the operations of `operations.csv` (how many, by
whom, first and last, the area logged against the area measured), the bands of
the map, the SHA-256 of the copy and of the record of changes, the STAC fields,
and the headline numbers of its model vs corrected, uncertainty and time
reports.

**Same input, same card.** Two cards of the same campaign are the same bytes
but for the moment they were written.

**Beside the exports.** Export has a last box, *dataset card (Markdown +
JSON)*, ticked by default, which writes `<campaign>_card.md` and `.json`
beside the files, with the SHA-256 and size of each. Whole raster has a last
row, *the dataset card, with the pixel counts of this mask*, unticked by
default because it counts every product of the campaign at full size; ticked,
it writes `<mask stem>_card.md` and `.json` beside the mask, with the counts
the mask was written with and whether they are the card's own (`verified`,
only at full size, on the campaign's grid), and beside a GeoTIFF mask with a
coordinate system a STAC item, `<mask stem>_mask.stac.json`. Both choices are
remembered on this machine. The card can be written alone: untick every table
in Export, or every raster in Whole. A reader the Annotate filter keeps from
another reading's work gets the files and no card, with the reason.

---

## What gets written

### The tables

| table | geometry | columns |
|---|---|---|
| `tiles` | polygon | `tile_id`, `side_m`, `note`, `created`, `closed`, and the design: `sample_id`, `stratum`, `incl_prob`, `weight`, `design` |
| `polygons` | multipolygon | `class_name`, `class_code`, `tile_id`, `pass_no`, `operator`, `created` |
| `lines` | multilinestring | the above, plus `width_px`, `width_m`, `length_m`, `mode` |
| `points` | point | the above, plus `size_px`, `conf` |
| `boxes` | polygon | the above, plus `width_m`, `height_m` |

`class_code` is the number that ends up in an exported mask, and it never changes:
renaming a class changes the label everywhere, including on everything already
drawn, and leaves the number alone. A campaign hands out 1 to 254, 0 being
"nobody painted it" and 255 kept for "ignore", and a class past 254 is refused,
with the reason, by Classes and by the + on the chips, so the mask stays one
byte a pixel. A campaign that holds a code past 254 all the same, from a
manifest edited by hand, gets a 16 bit mask instead of one where class 256
comes out as 0, and Check notes it. A class taken out of the legend is retired
rather than deleted, so its polygons are not orphaned and its number is never
handed to another class. Its *name* is not handed over either: the map is painted
by name, so a new class may not be called what a retired one was called, and
Classes says so rather than letting two codes answer to one label.

### How saving works

This is the part worth understanding.

The manifest is rewritten whole and atomically: a temporary file, then a rename.
Either the old one is there or the new one is, never half of either.

The geometries go through **QGIS's edit session**. When a module opens, the layers
are put into editing and stay there. Every stroke is a feature in a buffer in
memory: you see it drawn and counted, but it is not on disk yet. **Save** commits
all five tables and reopens editing straight away, so the brush never finds the
layer shut under it. Just before committing, every frame's side and coverage are
measured again, so what is written is the measurement of what is being written.

Autosave counts strokes and saves quietly at the threshold.

Three doors stop work escaping: closing a campaign with unsaved work asks, Export
saves first, and the check for unsaved work reads exactly the same list of tables
that the save does.

That question is put to the layers themselves and not only to the module in front
of you, because Correct and Cutouts hold no brush and would answer that nothing is
pending even when a buffer is full. Answer Yes and the save is checked: if anything
would not go, nothing is closed and the window says which table refused. A commit
that fails leaves its buffer exactly as it was, so pressing Save again tries the
same work once more rather than starting from nothing.

Whole is no exception, though it is reached from Cutouts: it asks the tables for
work still waiting to be written, writes what it can, and if anything is left it
says so and asks "Export anyway?" (Cancel is the default), because a mask made
from the package without that work labels it as background.

### Exports

**Export** under ANNOTATION CAMPAIGN writes the tables out in another shape: GeoPackage,
Shapefile, GeoJSON, KML, or CSV with the geometry as text. The table of a
Shapefile is written in UTF-8, with a `.cpg` file beside it, so class names in
Chinese, Greek or Cyrillic survive (an older reader that ignores the `.cpg`
reads them as Latin-1). Files come out named
`<campaign>_<table>`, which is also what the layers are called, and exporting
again into the same folder replaces them. **Which reading** narrows every
table but the frames to one reading, an operator in a pass, named in the files
(`<campaign>_ANNA_p1_<table>`), or writes the consensus of a pass or of every
reading: the polygons are then the ground more than half of the readings give
the same class, with `operator` CONSENSUS, the pass when they share one, and
how many readings agreed in `votes`, out of `readings`; `readings` is the number
of readings that covered the frame the polygon lies in, so a frame two of four
people read gives `votes` 2, `readings` 2; burned, they are the consensus mask
of the whole raster. The lines, points and boxes of the readings
that took part go out as they are, each with its own operator and pass. The
KML and the CSV carry every
coordinate in full, so a polygon reads back exactly as it is in the campaign;
GDAL writes fifteen digits by default, and two vertices closer than that made
the polygon invalid in those two formats only. Every file written is read back:
a polygon valid in the campaign that came out invalid is named in the message
that says what was written, so is a table that came out with fewer shapes than
the campaign holds, and a file that came out with none is taken away and
reported as not written. Every CSV the program writes starts a text that begins
with `=`, `+`, `-` or `@` with a quote and leaves numbers alone, and the CSV
export is checked and rewritten row by row, never held whole in memory.
Exporting to a GeoPackage works near the 260 characters of path that Windows
allows. GeoJSON and KML are in longitude and latitude, and so
are the others with "in longitude and latitude" ticked; a campaign with no
coordinate system, a picture or a world file without one, has nothing to turn
into degrees, so there the box is off and greyed, KML cannot be chosen, and the
other formats write the coordinates as they were drawn, in pixels or in the units
of the world file, with no system in the file, and say so. The last box,
*dataset card (Markdown + JSON)*, ticked by default, writes the
[dataset card](#dataset-card) beside the files.

**Cutouts** writes GeoTIFF, PNG or JPEG per layer, with a `cutouts.csv` manifest,
the footprints in `cutouts.gpkg`, `sampler.json`, `shapes.json` and, if asked, a
STAC 1.0.0 catalogue with the Projection extension. `layers.json`,
`sampler.json`, `shapes.json` and the STAC items are written whole or not at
all (under a temporary name, flushed, then renamed), and `sampler.json` counts
cutouts, not files. Class codes are never written to JPEG, whatever you pick: a lossy format would invent codes that were
never there. A layer of classes is cut in bytes when every value it holds fits
in one, and in the narrowest wider type only when one does not: a 16 bit map
with a class 300 used to come out with 300 turned into 44. The type is decided
on the whole map, so every cutout of it has the same one. A PNG holds bytes and
16 bit values that are not negative, nothing else, so a map with a negative
value in it, a nodata of -9999 for one, is cut as GeoTIFF even when PNG was
picked, and the message bar says so. A map's own nodata is kept: a -9999 stays
-9999 in the cutout and is declared as its nodata, and a float map whose nodata
is no whole number (the -3.4e38 that Raster Calculator and SAGA write) is cut in
the type its classes need, a byte for classes 1 and 2, with the top of that type,
255, declared as the nodata. The coloured PNG shows the nodata see-through. A
layer that is not a file, a web basemap (XYZ, WMS) or a database table, cannot
be cut: Cutouts leaves it out, and the panel and the log say why, and
Whole raster says "That raster cannot be read: it is not a file but a web or
database layer." A layer's name, up to 48 letters, is the tag in the names of
its files. A longer name keeps its beginning and its last words and gives its
middle for six letters of its SHA-1, so `..._disag_classes` and
`..._disag_probabilities` stay two names; a folder already cut keeps the tags in
its `layers.json`. A layer of classes
that is a mask written by Whole carries which readings it holds into the
classes of every cutout and into the STAC item, as `rasterlabel:readings`.
A map of classes stored with a lossy codec, a JPEG for one, is cut as it is,
and the message bar says once that its codes carry compression noise. The
STAC item says what the specification asks: `proj:wkt2` holds WKT2 and is
left out when it cannot be made, the footprint runs counter-clockwise as GeoJSON
wants of an exterior ring (the item beside a Whole mask too), the classes are
`labels` as well as `data`, and a layer on a grid of its own carries its own
`proj:shape`, `proj:transform` and `proj:bbox`. The STAC item gives the data
type of every file it lists (`raster:bands`, from the
raster extension). The GeoTIFF of an image is the image as it is: every band,
in its own data type, with its nodata and band names, red, green and blue
first. Where a cutout runs past the edge of an image that has no nodata, the
GeoTIFF has a mask of its own, 0 over the padding, so the padding is not
taken for black ground. Its
PNG is a picture of it as QGIS shows it, with the bands and stretch of its
style, transparent where there is no data. A class layer written as PNG keeps
its codes; its coloured picture, painted in that layer's own style, comes with
"also write PNG copies", as `_classes_colour.png`. The classes listed in
`sampler.json` are the ones that style names, and so are those of the STAC
item (`classification:classes`). The date of a STAC item is the date a layer
says its image was taken, and null, with the moment of the cutting as its
start and end, when none does. The STAC catalogue lists the
files that were actually written and leaves out of `catalog.json` an item whose
files are gone. The STAC items and the sampler name a campaign only when one is
open.

**Correct** writes nothing outside its folder: the working copy is the result,
a GeoTIFF with the bands of the map it started from, that opens in QGIS with
its classes from the `.qml` beside it, and in other programs from the colour
table, the category names and the attribute table of its class band. Which pixels were changed by hand is the
`_changes.tif` beside it. A cutout of the corrected map, or of any layer
styled in classes, gets those classes too: its `_classes.tif` carries them as
its colour table and category names, and opens in QGIS in the colours of the
PNG beside it instead of grey; the codes are the same.

**How the readings are arranged.** With *all readings together* chosen,
Export can write everything in one set of files (each mark carries its
`operator` and `pass_no`) or one set of files per operator, named after the
operator, each holding all the passes of that operator. With a single reading
or a consensus there is one set.

**Pack in a .zip.** Tick *also pack it all in one .zip* to get, beside the
files, `<campaign>_export.zip` with all of them inside: the formats chosen,
the dataset card and the files that go beside one. Names inside are relative.

**Hidden work.** If the files to be written hold readings that your current
Annotate settings hide from you (*one operator at a time*, *blind*), Export
asks once before writing anything; the same goes for the dataset card of the
Whole raster. Cancel writes nothing.

### Unlabelled pixels and the ignore value

A mask has always held 0 where nobody painted, and it still does unless you
choose otherwise. A training script that should leave those pixels out of the
loss has to be told which value they are, and 0 can mean three different
things: ground outside every frame, where nobody looked; ground inside a frame
that nobody painted, which in a campaign where everything in a frame is painted
is the class "none of these"; and, in a consensus, ground the readings painted
and did not agree on.

**Whole raster.** The block **Where nobody painted**, under *Which reading*,
says what the mask holds there:

- *0, as before*: what every mask has held. The default on a first use.
- *the ignore value everywhere*: the ignore value (255 by default) wherever
  nobody painted and, in a consensus, wherever the readings do not agree.
- *0 in the frames, the ignore value outside*: inside a frame, ground nobody
  painted is 0, "none of these"; outside every frame it is the ignore value.
  Ground the readings of a consensus disputed is the ignore value inside a
  frame too, and a polygon traced outside the frames keeps its class. Greyed
  for a campaign with no frames. The note under it counts the frames not
  closed for the reading chosen: the unpainted ground of such a frame goes out
  as 0 all the same, a claim nobody made, so close the frame, or choose the
  ignore value everywhere. For a consensus the note counts a frame as closed
  when the readings that covered it closed it, the same readings that vote in
  it: in a design where each frame was read by two of four people, a frame both
  of its readers closed is closed, and the note does not ask the other two. For
  *all readings together* it still asks every reading.

The ignore value is never 0 and never a code a campaign hands out (1 to 254);
a value a class of the legend already uses is refused, and so is a mark with
no class code, before any file is written. 255 keeps the mask one byte; a
value past 255 makes it 16 bits, a negative one 16 bits signed (and a PNG mask
is then written as a GeoTIFF). The choice is remembered on this machine. The
value is declared as the GDAL nodata of the mask, so QGIS draws it see-through
and a loader reads it as the value to leave out, and the GeoTIFF says it in
`RASTERLABEL_UNLABELLED` (zero, ignore or frames), `RASTERLABEL_UNLABELLED_RULE`
(the sentence) and `RASTERLABEL_IGNORE_INDEX`. The file name says it too:
`<campaign>_<raster>[_<reading>]_ign255_mask.tif`, `_ign255out` for the
frames rule, `_ignm100` for -100. The painted image, the plain image, the
figure and the `_votes.tif` are not changed: the ignore value is never painted.

**Cutouts.** Under Settings, *unlabelled as ignore*, with its value beside it,
off by default. On, a layer cut as classes gets the ignore value over the
padding past its edge and over its own nodata, declared as the nodata of the
cutout, and the 0 of a mask written by Whole with 0 where nobody painted
becomes the ignore value too. A 0 in any other map is left alone: it may be a
class. A mask that already carries an ignore value keeps its own, whatever the
setting says, and a cutout in which the layer itself holds the ignore value
among its own values is refused, all of it, with the layer named. The value goes into the cutout's tags,
the last column of `cutouts.csv`, `ignore_index` (an older `cutouts.csv` gets
the column, empty for its rows, the first time it is added to), the `labels`
block of `sampler.json` (the value, what 0 is, and the loss arguments for
PyTorch, TorchGeo and MMSegmentation), and the STAC item:
`rasterlabel:ignore_index`, `nodata` in `raster:bands`, and a
`classification:classes` entry `{"value": 255, "name": "ignore", "nodata":
true}`. The coloured PNG is transparent there. The ignore value is not a class:
it gets no index in `sampler.json` or YOLO.

**It is not a foreground.** samgeo (segment-geospatial) and Deepness write 255
for the foreground of a binary mask, the opposite meaning: a mask of theirs and
one of ours must not be mixed without converting one of them.

| Tool | What it takes for "nobody labelled it" |
|---|---|
| RasterLabel | 0 (default), or an ignore value: everywhere, or outside the frames; declared as nodata and in every file |
| TorchGeo | `ignore_index`, any value, 0 included; pads past a mask's edge with the file's nodata |
| MMSegmentation | 255 by default (`ignore_index`), with `reduce_zero_label` to turn 0 into it |
| PyTorch `CrossEntropyLoss` | `ignore_index=-100` by default; targets as `torch.long` |
| LabelMe | `__ignore__`, written as 255 |
| Segmentation Gym | none: 0 is trained as a class |
| samgeo, Deepness | none: 255 is the foreground, the opposite |

### Reports

`reports/` in a campaign or a correction folder holds one folder per report of
the Measure menu: `agreement/`, `time/`, `card/` in a campaign;
`model_vs_corrected/`, `uncertainty/`, `time/`, `card/` in a correction. Each
is described under [Measuring](#measuring), and none is ever written over.

---

## When something goes wrong

A young program fails in ways its author has not imagined, on rasters and QGIS
builds its author has not seen. There are two useful answers to that. One is to
wait until it feels finished, which it never will. The other is to make a failure
cheap to survive and cheap to report. This is the second answer, and it has four
parts.

### The recovery snapshot

**After every stroke**, what is drawn but not yet committed, boxes stretched,
reclassed, deleted or undone in Objects included, is written as plain text
beside the campaign, in `recovery/`. Autosave decides how often work reaches the
GeoPackage; the snapshot is written after every single stroke, because what it
exists for is the crash *between* two autosaves. It is also brought up to date
after a frame is placed, moved, deleted, noted or imported and after a class is
renamed across what is drawn, because each of those writes a whole table and
takes the strokes still waiting in it along; QGIS's own Save Layer Edits on a
table of the campaign is heard the same way.

It is a JSON Lines file, one object per line, that a person can open and read. That
matters: a recovery file nobody can inspect is a recovery file nobody trusts. It is
written as a temporary file and a rename, so what is on disk is always either the
previous snapshot or the current one, and a snapshot cut off halfway still gives up
every whole entry in it.

When a save succeeds there is nothing pending and the file is removed. So a
snapshot still there at the next open can only mean one thing: the session that
wrote it never saved. The program says what is in it and **asks** before putting it
back, because a crash in the middle of something you had decided to abandon should
not come back to life unasked: **Put them back**, **Not now** or **Discard**.
Not now leaves the file as it is, and the question comes back the next time the
campaign is opened. Put back, the file is kept, renamed with `.restored` on the
end; discarded, it is kept too, renamed with `.discarded`: never deleted, and
Check lists both, so a campaign with work set aside never reads as all on disk.
Taking `.discarded` off the end of the name makes the next open ask again.

### Check

One button under ANNOTATION CAMPAIGN, and one under CORRECTION. It says which QGIS, Qt, GDAL, numpy and Python are
running, which formats this GDAL actually has, whether the campaign folder can be
written, and then whether the campaign still agrees with itself:

- a manifest or a grid with something missing, a GeoPackage that is missing or
  cannot be read, a table that is not in it, an empty legend
- class codes carried by features that the legend does not have, and codes in
  the legend past 254
- names that the legend gives to a different code
- frames that have drifted off the pixel grid
- outlines that cross themselves
- polygons of one reading and one frame that share ground
- frames whose `closed` column disagrees with what is painted in them, measured
  reading by reading, as the save writes it, and naming the fullest reading
- on a tiled campaign, points outside every frame, footprint included, and
  points whose `tile_id` names a frame other than the one they sit in, counted,
  with how to clean them up
- layers in the project that read the package but are not the campaign's
- work that is not on disk yet, snapshots from an earlier session, and the
  recovery files set aside earlier, discarded or put back
- layers of the campaign that read another file than its own, the original of
  a copied folder or the old place of a moved one (Open replaces them)
- a correction that moved to a campaign of its own whose folder is gone
- what the journal of working time holds, a manifest that claims a journal
  with no file, and marks drawn before the journal began
- the frames that carry a sampling design, draws an import refused, frames of
  a design moved or deleted since, and weights that are not one over the
  inclusion probability
- reports whose folder or files are gone, and reports older than the work they
  measured

With no campaign open that half is one note, not an alarm: Annotate and Objects
need one, Correct and Cutouts do not. While a correction is open there is a
section of its own, THE CORRECTION, and Check under CORRECTION shows that
section with what is running and leaves the annotation campaign out: the keys of `correction.json`, its grid, the working
copy (there, readable, with the bands of the map it corrects in their order,
on the grid of the manifest), its `_changes.tif` (there, on the grid of the
copy, and how many pixels it marks) and its `.qml`, the map it started from, the codes in the copy against its classes, nodata listed as a
class, `operations.csv` against the count, the record of the ground swept and
how much of the map it holds, which uncertainty the correction reads and
whether its file is up to date, its journal, and whether the folder can be
written.

The window lists what is wrong first, then the whole report, each line marked
ok, note or problem in a colour of its own and wrapped to the window.

It changes nothing. A tool that offers to repair what it has just diagnosed is a
tool that has to be trusted twice. **Copy report** puts the lot on the clipboard,
as plain text, and that is the first thing to paste into a bug report.

### The error window

When something fails, a window opens. It says what was being done, what the machine
said, and what is worth trying, in that order, with the technical detail folded
away behind *Detail* and a **Copy report** button that puts the lot on the
clipboard, versions included.

Twenty rules turn common failures into advice: a package held open by an edit
session or by a sync client, permission refused, a full disk, a file that has
moved, memory exhausted by a raster too big, a format this GDAL cannot write, a
QGIS older than the one this was built on. When no rule matches, the window says so
rather than guessing, and reminds you that a failure leaves the campaign as it was.

The rules read the **error number** before the text, so an Italian Windows saying
*Accesso negato* gets the same advice as an English one saying *Permission denied*.

### The log file

`rasterlabel.log`, beside `campaign.json`, or beside `correction.json` while
Correct is open, or, when Cutouts runs with no campaign, in the `RasterLabel`
folder of your home and not in the cutouts folder (a dataset: the log would go
with it when it is zipped and published), rolled over at a megabyte. The log
writes your home folder as `~`; the other paths in it (a disk, a project
folder) are still the ones of your machine. One file at a time: when it moves
from one to the other, both say where the rest went. The QGIS log
panel is where a failure belongs while somebody is sitting in front of it. It is not
where a failure is three days later, when the report arrives and says the program
"stopped working".

---

## Requirements and limits

- QGIS 3.36 to 4.x. The plugin will not install on anything older, because
  that is the floor `metadata.txt` declares and QGIS enforces it. The single
  file pasted into the console has no such floor: it starts on older releases,
  says so in a window, and keeps going, because the handful of enumerations
  QGIS has renamed since are looked up under both spellings.
- **QGIS 3 and QGIS 4 run the same code.** QGIS 3 is built on Qt 5 and QGIS 4
  on Qt 6, and the one difference that reaches a plugin like this is that PyQt6
  knows an enumeration member only by its full name, `Qt.MouseButton.LeftButton`
  and never `Qt.LeftButton`. Every Qt name in the program is written in that
  full form, which PyQt5 reads just as well; everything Qt is imported through
  `qgis.PyQt`; dialogs are opened with `exec()`. `metadata.txt` says
  `qgisMaximumVersion=4.99`, which is how QGIS 4 and plugins.qgis.org decide
  that a plugin is offered to QGIS 4. `supportsQt6=True` stays as a statement
  that the code runs on Qt 6; the plugins site says QGIS no longer recognises
  the flag, so nothing relies on it. One zip installs on all of them.
- **Windows and Linux.** On Linux, Correct opens, writes and closes the
  corrected map at every stroke, because the libtiff of Debian and Ubuntu does
  not let another reader see a compressed block until its writer closes the
  file; the panel and its windows are laid out for the DejaVu fonts those
  systems draw with. macOS has not been tried.
- How that was checked: the suites run on PyQt5 and on PyQt6, a static check
  refuses any short Qt spelling, any import of PyQt5 or PyQt6 by name and any
  `exec_()`, and the plugin was loaded, driven through Annotate, Correct and
  Cutouts, unloaded and loaded again in a real QGIS 3.36, 3.44 and 4.2 with no
  window on screen. The QGIS 4 runs were in the official QGIS Docker image on
  Linux and in QGIS 4.2.3 on Windows, both headless.
- GDAL and numpy come with QGIS. Run it as a plugin, or from the QGIS Python
  Console: not from a system Python.
- A raster with no coordinate system works, but sizes are then in pixels, not
  metres, or in the units of its world file when it has one, and areas and
  lengths are measured on the plane in those units. The New dialog says so.
  GDAL does not read a `.prj` beside a PNG, a JPEG, a BMP, a WebP or a JPEG
  2000; when one is there, or when the layer's system was set in QGIS and is
  not in the file, the New dialog says so and on Ok offers to write it into
  the `.aux.xml` beside the file, so the campaign, the masks and the cutouts
  carry it. The picture itself is never written to.
- A raster written north-down, with a positive pixel height, works in Annotate
  and in Correct.
- Windows paths past 259 characters: GDAL writes them and the maps open, but
  QGIS cannot open a GeoPackage on such a path. Compare and Time refuse a report
  that would put one there and say how many characters to take away.
- A raster on a rotated grid (rows not parallel to the x axis) is shown by
  QGIS resampled north-up. Annotate takes it, and the New dialog says that
  frames and lines then sit on that view and not on the raster's own pixels;
  Correct refuses it, because a stroke would change pixels beside the ones
  under it. Warp it north-up first: Raster > Projections > Warp, nearest
  neighbour for a map of classes, or `gdalwarp -r near`.
- A frame is square in pixels. Where the pixels are not square on the ground,
  4 x 6 cm in a survey or any orthophoto in WGS 84, it is a rectangle in
  metres, and the New dialog and the frame side say how long each way.
- QGIS and GDAL ignore the EXIF orientation of a photo, so a photo stored on
  its side is shown on its side, and the mask and the cutouts follow the
  pixels as stored. The New dialog says when a photo is stored turned.
- macOS has not been tried. QGIS runs there and nothing in the program is
  written for one system, but nobody has used it on a Mac yet; Qt reads Ctrl
  as the Command key there, so every Ctrl+click in this file is Cmd+click, and
  the hints in the program say Cmd.
- The panel is a vertical bar and cannot be docked top or bottom.
- A frame cannot be resized once placed. Set `tile side` before placing it.
- The vertex tool is QGIS's own, not a copy of it.
- There is no server, no task assignment and no accounts. This is a tool for one
  person, or a few who pass a folder between them. A campaign, or a correction,
  must be open in one QGIS at a time: the same project opened twice, or two
  people on one folder on a network drive. Nothing stops the second QGIS, and
  the GeoPackage does not refuse it either: both save, and the work of one can
  overwrite or duplicate the other's.

---

## The repository

| | |
|---|---|
| `rasterlabel/` | the package, and the QGIS plugin folder |
| `dist/rasterlabel.py` | built by `tools/bundle.py`: what you paste into the console |
| `launch_rasterlabel.py` | open it in the console editor and press Run: it finds and runs `dist/rasterlabel.py` |
| `dist/rasterlabel-1.1.zip` | built by `tools/package_plugin.py`: what QGIS installs |
| `tests/` | the suites, and the fakes that let most of them run with no QGIS |
| `examples/rasterlabel_example/` | the synthetic example dataset of the tutorial, made by `tools/make_example.py` |
| `docs/tutorial.md` | the walk-through on the example, with its pictures in `docs/img/` |
| `docs/methods.md` | how every number is computed, with references |
| `tools/make_example.py` | makes the example from a fixed seed (numpy and GDAL only) |
| `tools/tutorial_walk.py` | does the tutorial without a window, and draws its pictures |
| `CITATION.cff`, `.zenodo.json` | how to cite it |
| `CONTRIBUTING.md` | the two rules the build enforces, what a change needs, and how to ask for help or report a problem |
| `CODE_OF_CONDUCT.md` | the Contributor Covenant 2.1, and where to report a problem of conduct privately |

The program was one file of twelve thousand lines, and the reasoning is written
next to the code rather than in a wiki nobody opens. It is now a package of
modules, one for each part of the work, and the single file is built from them: the import order is a promise that no
module needs a name from a later one, and the builder refuses to build at all if
two modules define the same top-level name, because one flat namespace cannot hold
two of anything.

On Ubuntu or Debian, the same packages the build server installs:

```
sudo apt install python3-pyqt5 python3-numpy python3-shapely \
    python3-pyflakes python3-gdal
python3 tests/run.py
```

A current Ubuntu or Debian refuses `pip install` into the system Python, and
the GDAL bindings have to match the GDAL on the machine anyway, so apt is the
way there. `pip install PyQt5 pyflakes numpy shapely` is for inside a virtual
environment, or on an older distribution, with the GDAL bindings still taken
from the system's own packages.

The suites run on PyQt6 just as well: `python3 tests/run.py --qt 6` with
`python3-pyqt6` installed, or inside the QGIS 4 Docker image, as
[CONTRIBUTING.md](CONTRIBUTING.md#on-qt-6-and-qgis-4) shows. The first line of
a run says which binding it used.

No QGIS needed for most of them: they fake the parts of QGIS they use. The
suites named in `NEEDS_GDAL`, at the top of `tests/run.py`, need the GDAL
Python bindings and are skipped, with a line saying so, where there are none;
those in `NEEDS_QGIS` hand values to the real QGIS classes (the message levels
to a real message bar, corrected maps opened as real layers, pictures and odd
grids walked through Correct and New campaign, the whole raster held up
against a real map render, a session killed in the middle of a save, a
campaign copied and moved under a saved project, the Processing algorithms, the
time report, Import frames, the uncertainty of a map as real layers, and the
tutorial walked step by step) and are skipped where QGIS is not importable. On Windows the bindings that are
easiest to reach are the ones inside QGIS, and
[CONTRIBUTING.md](CONTRIBUTING.md#on-windows) says how to run the whole set
there. Real GDAL and real GeoPackages for the geometry and the
exports, a real Qt panel built and clicked for the interface, the plugin zip
unpacked and installed the way QGIS installs it, a sweep over fifteen widths
that checks nothing is drawn on top of anything else, a static pass that refuses
any name used and never defined, and one suite whose only job is to hold the
ground already won: every defect that was ever found and fixed has a check in
it, so the fix cannot quietly come undone. A bug that is fixed and not pinned
down comes back.

Correct has several suites of its own. One opens the real module on a map
numbered differently from the legend and checks that the chips, the strokes and
Ctrl and click use the map's codes, and that FROM, TO, the banner, Ctrl+click and
Shift+click do what the panel says. Two others are worth knowing about, because the
same trick would suit anything else that matters. One lifts the decision about
which pixels may be touched out of `paint()` by name at run time and plays it
against arrays whose every pixel is known. The other writes a real class raster,
runs the program's own `build_copy()` on it, writes a correction through the copy,
drops the handle, and opens both files again from nothing: a value that is only in
memory looks exactly like a value that was saved, right up until QGIS closes.
Nothing is copied into either test, so neither can drift away from the program.
Two more make a correction of a map of five bands, laid out like a model's land
cover with its own `.qml`: one through the panel with real files, checking the
copy against the map band for band, the `.qml`, the colour table, the
`_changes.tif` under a stroke and an Undo, and the conversion of a six-band copy
of the earlier build, interrupted and then finished; the other inside a real
QGIS, which opens the copy as a layer and must find it paletted, with the
right classes, on QGIS 3.36, 3.44 and 4. And two walk the maps people really
load through the whole of Correct, new correction, classes window, strokes,
Undo, Save, Close and open again: one band of bytes with nothing else, with
a colour table, with a `.qml` paletted or pseudocolor, sixteen bits with
codes in the thousands and three kinds of nodata, a stack whose class band is
not the first, an attribute table and a `.tif.vat.dbf`, a BigTIFF tiled and
compressed, strips uncompressed, a cloud optimised GeoTIFF. One with real
GDAL and QGIS faked, the other in a real QGIS on its map canvas, where QGIS
styles the map itself and opens the corrected one. Others hold what the work
costs on a map too big to hold (the class band and the record read a strip at a
time, the memory measured, a stroke whose write fails refused whole), the count
net of Undo and the operator who struck, and the area of a stroke on the ground
against the ellipsoid on a map in degrees and in Web Mercator.

One guarantee there does not rest on a test at all. The map the model produced is
opened read only, so GDAL refuses a write to it rather than this program
remembering not to make one.

---

## Licence

RasterLabel, a QGIS panel for drawing labels on a raster.

Copyright (C) 2026 Massimiliano Guastella

This program is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation; either version 2 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

The full text of version 2 is in [LICENSE](LICENSE), and it travels inside the
plugin zip as well. Later versions are at <https://www.gnu.org/licenses/>. In
SPDX terms: `GPL-2.0-or-later`.
