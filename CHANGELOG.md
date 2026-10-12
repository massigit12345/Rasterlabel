# Changelog

Dates are when the work was done. Versions are what was released.

## 1.1, 2026-10-12

Two things. What the first person to install the plugin from the zip and
annotate with it found, which is the one test the suites cannot run, with a
review of the whole repository and walks through a real QGIS 3.36, 3.44 and
4.2 on the maps and pictures people really load. And the measuring features:
how far two readings agree, how long the drawing took, how far a model was
from its corrected map, where its uncertainty pointed, and what the dataset
holds, each also an algorithm of the Processing toolbox. A synthetic example
and a tutorial come with it.

### Measuring

New in 1.1: numbers for a paper, from what is already in a campaign or a correction.

- **Measure, in both blocks.** ANNOTATION CAMPAIGN and CORRECTION each have a
  **Measure ▾** key just before Check, a key with a menu behind it like QGIS's
  own Style button. The menu lists only what this build can measure on what
  the block holds; a grey entry says why when the pointer rests on it. Every
  measure saves first, writes a report folder of its own under `reports/`,
  written under `.tmp` and renamed when whole, never over an older one, and
  changes nothing drawn. A reader kept by *blind* or *one operator at a time*
  from another reading's work is refused any measure that would show it, in
  the words of one rule shared by all of them.
- **Compare two readings.** **Measure ▾ ▸ Compare two readings…** in
  ANNOTATION CAMPAIGN measures how far two readings of the same frames agree,
  two operators in one pass (inter-observer) or one operator in two passes
  (intra-observer), on the frames both closed (the area rule of Annotate and
  Check) or both touched. The readings are burned on the campaign's own grid
  exactly as Whole raster writes one reading. Out come, in
  `reports/agreement/<A>_vs_<B>_<stamp>/`, the confusion matrix with
  unlabelled as a row and a column of its own, per class IoU, F1 (Dice) and
  the agreement seen from each reading, Cohen's kappa as an agreement
  statistic beside quantity and allocation disagreement (with exchange and
  shift), each pooled, as the median and quartiles over frames and with a
  frame bootstrap 95 % interval; a disagreement map (agree, disagree, only A,
  only B, neither), a map of pairs, and a GeoPackage of the places where the
  readings differ and of the frames with their numbers, all loaded into QGIS
  styled. An unfinished reading is asked about, Cancel first, and the maps
  are switched off for a reader who becomes blinded to them. The same report
  is the Processing algorithm `rasterlabel:agreement`, which only reads the
  campaign; `metadata.txt` says `hasProcessingProvider=yes`.
- **A report QGIS could not open is refused before it is written.** On
  Windows QGIS opens a GeoPackage through SQLite, and SQLite cannot open a
  path of 260 characters or more, the `\\?\` form that GDAL writes it through
  included (tried on QGIS 3.36, 3.44 and 4.2): Compare and Time wrote their
  GeoPackage into a folder deep enough, and the layers of the report then did
  not load, with nothing to say why. Both now look at the path of the file
  before they make a folder, and refuse, in the window (Compare and Write stay
  grey, with the note under the folder) and in the Processing algorithm, with
  the length of the path, the longest QGIS can open and edit (248 characters:
  259 less the eight of the `-journal` file that QGIS 3.36 keeps beside a
  GeoPackage it edits and the three of a `-99` after the folder's name; at 252
  the layer loaded and Start editing failed with "unable to open database
  file") and how many characters too many: choose a shorter folder, or move
  the campaign closer to the root of the drive. Nothing is made, not even the
  `.tmp` folder. Only a GeoPackage is held to a length: the maps of pairs and
  of disagreement are GeoTIFF, the places of the uncertainty GeoJSON, and QGIS
  opens those at any length, so Model vs corrected and Uncertainty ask the
  same question and are never refused for it. The 8.3 name of a folder would
  open the file on a volume that keeps them, and was left out: a report that
  loads on one machine and not on another is worse than one that says where it
  cannot go. A folder picked with the button beside the field counts as chosen
  by the person, like one typed: it greys Compare at once if it is too deep,
  and the default folder no longer replaces it when the readings are changed.
  `tests/test_report_paths_qgis.py` asks QGIS itself, on Windows, and the rule
  can go the day it opens the GeoPackage.
- **Another raster, in the source of an uncertainty, no longer lists the maps
  of a report** (the disagreement map of Compare, the pairs of Model vs
  corrected), as Whole raster and Cutouts already left them out.
- **Time: how long the drawing took, from a journal of what was done.** Every
  saved action (a stroke, a line, a point, a box, a frame placed, moved or
  deleted, Fill Gap, Repair, a stroke of Correct, an undo, a stroke thrown
  away or refused, a class or a pass chosen, a save) adds a line to
  `journal.csv` beside the campaign or the correction: when it ended, how
  long the stroke took and its pauses, who, which pass, frame and class. No
  stopwatch runs on its own and nothing else is recorded: no keys, no mouse
  tracks, no screen. A manifest gets its `"journal"` block only when the
  first line is really written, so a campaign made before opens unchanged and
  its earlier time reads as not recorded, never as zero; an earlier build of
  1.1 had given every new manifest a journal block while nothing wrote one,
  and that is gone. Writing is append only, about a tenth of a millisecond a
  line, never raises, keeps the lines in memory while the file is locked, and
  a session killed outright leaves every line it wrote. Active time sums the
  strokes and the gaps between lines up to the idle limit (60 s, with 30 and
  120 s always written beside it); a longer gap, or one with QGIS in the
  background, is idle. **Measure ▾ ▸ Time…**, in both blocks, writes tables
  per frame, per reading, per class and per hectare, a map of the frames, and
  drawing from scratch against correcting on the same frames, with a frame
  bootstrap interval and the Wilcoxon test, into `reports/time/<stamp>/`. A
  correction from before the journal is estimated from `operations.csv`,
  which is unchanged, and says so. A quiet line under the coverage, and under
  the tally of Correct, gives the day's active time; Annotate's settings have
  *keep a journal of working time*; Check says what the journal holds.
- **Model vs corrected.** **Measure ▾ ▸ Model vs corrected…** in CORRECTION
  compares the map a model made with the map as corrected, class by class,
  the corrected map as the reference: the confusion matrix, producer's and
  user's accuracy, IoU, F1, quantity and allocation disagreement (no kappa for
  the model) and the net FROM ➜ TO transitions. On the whole map (an upper
  bound), on the ground the strokes swept (a lower bound), or inside the
  polygons of a layer, one matrix per polygon and an interval over five or
  more. Beside it, another person's correction of the same map on the same
  pixels, asked about first, or an annotation campaign's agreement report
  matched by class name. Tables and `summary.json` in
  `reports/model_vs_corrected/<scope>_<stamp>/`, a map of pairs styled for
  QGIS, and a quiet line under the tally of Correct.
- **Correct keeps the ground the strokes swept.**
  `<map>_corrected_reviewed.tif` beside the copy says which pixels a stroke
  went over, written stroke by stroke and undone with the stroke. A new
  correction has it from the start; one made before opens unchanged and
  starts it at its next stroke, with `reviewed_since` in its manifest. It is
  refused as a map to correct, set aside with the correction, and said by
  Check.
- **Uncertainty in Correct.** Under Save, an UNCERTAINTY card. With nothing
  chosen it is one quiet line and nothing else changes: no file, no layer, no
  line in the manifest. A band named like a probability, an entropy or a
  margin is offered with **Use it**; **Source…** reads a band of the map or
  another raster on the same ground, as a probability, an entropy, a margin,
  a ready-made uncertainty or the votes of a consensus, into
  `<map>_corrected_uncertainty.tif` (0 to 254 for u, 255 for no value). The
  map is cut into fixed square places ranked by mean u, and the card walks
  them (Start, Done next, Skip, back), one place in five drawn instead from a
  seeded simple random sample of places; the places chosen by uncertainty are
  labelled as excluded from design-based estimators. The uncertainty is drawn
  multiplied over the classes, the places are a layer of their own, and the
  place of each stroke goes into `journal.csv`; `operations.csv` keeps its 14
  columns. **Measure ▾ ▸ Uncertainty report…** writes
  `reports/uncertainty/<stamp>/`: the share of pixels a person changed per
  decile and per tenth of u, for the random places (cluster ratio standard
  error), the purposive places and the whole map (a lower bound), the AUC of
  u, the ECE for a probability, a capture curve, the strokes with u, and a
  picture of the curve.
- **Dataset card.** **Measure ▾ ▸ Dataset card…**, in both blocks, writes
  `reports/card/<stamp>/<name>_card.md` and `.json`. For a campaign: the
  pixels of every class in every reading, in all of them together and in
  every consensus, burned by the same code as the masks; the frames and how
  complete each reading made them; who drew what; the rules that made the
  pixels; the build, the grid and the SHA-256 of the package; the STAC label
  fields with the real counts; and the headline numbers of the agreement and
  time reports, marked when they may be stale. For a correction: the classes
  before and after, the pixels a person changed and from what into what, the
  operations, the bands, and the headlines of its reports. Nothing in the
  campaign or the correction is written, and the same input gives the same
  card but for the date.
- **The dataset card beside Export and Whole raster.** Export writes the card
  beside the files it makes, ticked by default; Whole raster offers it as the
  last row of *What to write*, unticked by default, because it counts every
  reading of the campaign at full size. Both choices are remembered on this
  machine. The card holds the SHA-256 of each file written; from Whole, the
  counts the mask was written with and whether they are the card's, and a
  STAC item beside a GeoTIFF mask. The card can be written on its own. Every
  mask and votes file carries the build, the campaign id and the pixel rule
  in its tags.
- **An ignore value where nobody painted.** The Whole raster has a block
  *Where nobody painted*: 0, as before (the default), the ignore value
  everywhere, or 0 inside the frames and the ignore value outside; in a
  consensus, ground the readings do not agree on gets the ignore value too.
  The value, 255 by default, is never 0 or a class code; a class that already
  uses it, or a mark with no class code, is refused before any file is
  written. It is the mask's GDAL nodata, and is said in its tags and in its
  name (`_ign255`, `_ign255out`). Cutouts has *unlabelled as ignore* under
  Settings, off by default: the padding, a map's own nodata and the 0 of a
  Whole mask become the ignore value, recorded in `cutouts.csv` (a new last
  column, older files brought up to date), in a `labels` block of
  `sampler.json` with the loss arguments, and in the STAC items. It is not a
  foreground, which samgeo and Deepness write 255 for, and the windows say
  so. Nothing changes in a mask or a cutout made without choosing.
- **Every measure in the Processing toolbox.** Everything the Measure menu
  computes can be run from the Processing toolbox, from Model Designer and from
  a Python script, headless, so that the numbers of a paper can be made again
  in batch. Next to `rasterlabel:agreement` there are now
  `rasterlabel:model_vs_corrected`, `rasterlabel:time_report`,
  `rasterlabel:uncertainty_report` and `rasterlabel:dataset_card`, in the group
  Measure. Each uses the same engine as its window in the panel, reads the
  campaign or the correction only (the manifest, the GeoPackage and every file
  keep their bytes and their time), writes one new report folder (under the
  owner's `reports/`, or the one named by `OUTPUT_FOLDER`), and does not list
  the report in the manifest, as the panel does. What the panel refuses, they
  refuse in the same words: a correction with no uncertainty chosen, a map the
  model made that is gone, a campaign with no journal, and, with the panel open
  on the same campaign, a reading hidden from the reader it holds (the dataset
  card). On a map in degrees or in Web Mercator, Model vs corrected in the
  toolbox measures the ground row by row, as the panel does.
- **Time and the cards say what their columns add up to.** In
  `time_per_class.csv` a frame has its "(no class)" row whenever there is
  overhead at the chosen limit or at 30, 60 or 120 s, so the classes of a frame
  add up to its time at every limit (before, the 30 and 120 s columns lost the
  overhead that exists only at that limit). The dataset card of a campaign with
  four readings or more no longer says that pixels every reading painted
  without a majority were painted "differently" (two and two is no majority
  either). Compare and Model vs corrected say in a note what the per-class
  quantity and allocation columns add up to.
- **Smaller things in the measures.** The dataset card in Markdown has no
  stray commas where an interval is missing (an agreement headline with no
  bootstrap reads `bare ground 0.9075; built-up 0.6504 (0.5 to 0.8)`, not
  `bare ground 0.9075, , ;`) and gives the whole SHA-256 of each file in the
  Files table, where it gave the first twelve letters. The dataset card
  recognises a reference raster stored bottom row first as on the campaign's
  grid, and keeps its size. `rasterlabel:agreement` takes a campaign by its
  folder, like the other four algorithms, as well as by its `campaign.json`.
- **Model vs corrected accepts a correction whose map had its coordinate system
  set in QGIS and not in the file.** The copy carries the system and the map it
  started from did not, and the window and the Processing algorithm took the
  two for different systems.
- **Methods, written down and held to independent implementations.**
  `docs/methods.md` gives the formulas, populations, intervals and references
  of every number a report prints. `tests/test_reference_values.py` holds the
  numbers to implementations written in the suite from the published formulas
  and, where scipy is installed, to scipy (`wilcoxon`, `mannwhitneyu`,
  `bootstrap`); without scipy those checks say SKIP, loudly, and
  `--require-scipy` makes the skip a failure.
- **Import frames keeps the sampling design.** Import frames opens a window
  that maps the columns of the file to sample id, stratum, inclusion
  probability, weight and design, guessed from the names spsurvey, sampling
  and AcATaMa give them; the stratum can also be read from a single-band
  raster of the project at the middle of each frame, and the design typed. It
  offers the side in Settings or each shape's own side, and shows what will
  happen to every feature before anything is written; the key reads
  "Import N" and is grey when nothing would become a new frame. The five
  values go into five new columns of the `tiles` table, as given: nothing is
  derived or normalised, and a value that does not read as a number is left
  empty and flagged. `design_log.csv` gets one row for every feature of the
  file (added, completed, already there, or refused as a duplicate, an
  overlap, outside the raster, with no geometry or not transformable), and
  one whenever a frame of a design is later moved or deleted; the manifest
  gets a `designs` entry per import. The features are taken in fid order and
  an earlier draw wins. Frames that would overlap are refused, as a click is:
  the import used to create them. Corners are rounded half up from the
  edges, so a square already on the grid stays where it is whatever its
  side. Check counts the frames carrying a design and notes refused draws,
  frames moved or deleted after the import, and weights that are not one
  over the inclusion probability.

- **The maps of a report keep their whole names.** A map of a report is
  named `<owner>_<kind>_<label>_<part>` and never cut short: cut at 48
  letters, two long readings gave their disagreement map and their map of
  pairs one name. Only a name past 240 characters loses the end of its
  label, followed by eight letters of its SHA-1, and keeps its part whole.

- **The report windows are tidy.** Compare, Model vs corrected, Time and
  Uncertainty share one window, and its tables were as tall as the window, so
  a few rows left a large empty area under them, with the figures of one
  column in two formats (0.9889 over 1) and the unit written "m2". A table is
  now as tall as its rows and scrolls only past twelve; each column of
  numbers is right aligned, its header too, with one number of decimals
  (three for a ratio, two for an amount, none for a count, or a percentage
  where a share reads better); thousands are set apart by a narrow space;
  areas read m²; the swatch is a narrow bar of the class colour; a name too
  long for the room is cut with "…" and whole in its tooltip. The window
  opens as wide as its tables ask and as tall as that needs, and can still be
  made 300 px wide. A hairline sets the notes apart, and they can be
  selected. Copy still gives plain figures for a spreadsheet.

### Readings: whose work goes out

- **The Whole raster and Export can write one reading, or a consensus.** Both
  wrote every operator and every pass on top of each other, the mark drawn
  last winning: right when the passes are layers of one piece of work, wrong
  when two operators read the same frame, because the mask was then neither
  reading. Both windows now ask which reading goes out: all of them together,
  as before (and the window says when two operators share a pass); one
  reading, an operator in a pass; or the consensus of the readings of a pass,
  or of every reading. A consensus gives a pixel the class a strict majority
  of the readings gave it, the class both gave it of two, and 0 where no class
  has one; beside the mask a `_votes.tif` counts the readings that gave each
  pixel its class and those that painted it. Export writes the consensus as
  polygons, with `operator` CONSENSUS and how many readings agreed in `votes`;
  burned, they are the consensus mask pixel for pixel. One reading and a
  consensus are named in the files, every GeoTIFF of the Whole raster says
  inside it which readings it holds and by what rule
  (`RASTERLABEL_READING_MODE`, `RASTERLABEL_READINGS`,
  `RASTERLABEL_READING_RULE`), and a cutout of such a mask carries the same
  into its classes and into its STAC item, as `rasterlabel:readings`. Two
  readings whose names would make the same file name, on a disk that does not
  tell the case apart included, get a number, so one never overwrites the
  other. The list of readings is counted by SQLite, so a large campaign opens
  either window at once.
  `test_readings` tries all of it on a campaign of two operators and two
  passes.
- **A consensus counts its majority among the readings that covered the
  frame.** In a campaign where each frame was read by two of four people, the
  consensus of the four needed three votes everywhere, so two people who
  agreed on a frame gave 0. Now a pixel needs more than half of the readings
  that have a mark in its frame (both of two, one of one), in the Whole raster
  and its `_votes.tif` (a third band, `readings_voting`, when the design is not
  full), in Export's consensus polygons (`readings` is the readers of the
  frame), and in the dataset card, which says how many frames were read by how
  many readings. Outside every frame the readings that painted anywhere vote.
  The note under *0 in the frames, the ignore value outside* counts a frame as
  closed for a consensus when the readings that covered it closed it. When
  everyone read every frame nothing changes, to the byte.
- **The dataset card of a campaign gives the ground of each class on a map in
  degrees or in Web Mercator.** The m2 of a class were its pixels times the
  pixel at the middle of the map; they are now the sum of the ground each pixel
  covers, row by row, as in Correct and Model vs corrected. Maps in a metric
  system give the numbers they gave.
- **A frame is closed by one reading.** The save measured the coverage pass by
  pass, so two operators who had each painted sixty per cent of a frame, in
  different places, made a hundred together and the frame was written down as
  closed, a complete reading nobody had made, while Check, which measures by
  operator and pass, called it right. The save now measures each reading, an
  operator in a pass, and the frame is closed when one of them covers it; the
  coverage on the panel is the reading in the panel, whether or not "one
  operator at a time" is ticked, and Check reads a reading through the same
  two functions as the save and names the fullest reading of a frame it
  flags. With "one operator at a time" off, where the other operators of the
  pass have painted the rest of the frame, the yellow line says so and that
  ticking the box lets you paint the rest as your own, instead of pointing at
  a Fill Gap that answers "no holes".
- **A second reader stays the second reader, in Annotate and in Objects.** Who
  is drawing, the pass and the blind switch lived in the Annotate module,
  which is built anew each time it opens and started from the campaign's
  creator in pass 1: a blind second reader who looked at Objects, or closed
  and opened Annotate again, silently became the first reader, and the
  strokes went into the first reading and cut its polygons. Objects knew
  nothing of readings at all and stamped every box with the creator and pass
  1. The panel now holds the reading for the whole session and remembers it
  per campaign on this machine; opening a campaign whose remembered reading
  is not the one last used in this QGIS session asks who is drawing before
  Annotate or Objects opens, and a campaign with only its creator in pass 1
  is never asked. Boxes are stamped with the reading, the reading filter
  covers them, and a box of another reading cannot be picked up, moved,
  reclassed or deleted. Objects shows who is drawing and can change it.

- Blind shows only the pass being drawn. With blind on, every other pass of
  the operator is hidden, the earlier ones and the later ones: going back to
  pass 1 no longer shows pass 2 on top of it. With blind off, every pass shows
  as before. The tick now says "blind: show only this pass" (Annotate and the
  window that asks who is drawing), and so do its tooltip, the amber strip,
  the README and the tutorial. Compare, the dataset card and the report layers
  follow the same rule: a reader blinded to a pass is refused a comparison
  that shows it, and the report layers that show it are switched off.

- Passes are a list for each operator, like the operators. A campaign starts
  with one operator in pass 1; the + beside "pass" adds the next pass for the
  current operator; the pass box offers only the passes that operator has; an
  operator who is added starts at pass 1, not in the pass the last one was in.
  The list is kept in campaign.json ("passes"); passes already present in the
  tables of an older campaign appear in it without the manifest being touched.
  The window that asks who is drawing has the same box and the same +.

- A campaign that is opened is drawn through the filter of the reading the
  panel holds, before Annotate is pressed: the map no longer shows every
  reading at once in overlapping colours, and is the same before and after
  pressing Annotate. Editing the legend with no module open keeps the filter
  too. The boxes of Objects follow all of it.

- Closing Annotate, Objects or the campaign draws the map again once the
  layers are gone, so their polygons do not stay on the canvas until the next
  pan or zoom, and the bands of a tool that was in the middle of a stroke are
  wiped.

### The panel

- **The panel has a block for each kind of work.** The CAMPAIGN buttons sat
  above all four modules but only ever spoke for the annotation campaign, and
  Correct ignored them and asked for its correction in a window of its own.
  Now ANNOTATION CAMPAIGN holds New, Open, Close, Classes, Export and Check
  with Annotate and Objects side by side under them; CORRECTION holds the
  correction's own New, Open, Close, Classes and Check, with Correct under
  them; and CUTOUTS, which saves no campaign, holds Cutouts. Each block has a
  line saying what is open in it. A correction is open while Correct is:
  going to another module closes it as Close in CORRECTION does, its layer
  leaving the project and its working copy let go of, so on Windows the
  folder can be moved or renamed as soon as Correct is left. Correct opens on
  the correction New or Open made, and offers New or Open when there is none.
  Classes moved out of the Correct module into the block, and Check there
  reports on the correction without the annotation campaign; with no
  correction open both are grey.
- **The panel looks like QGIS and keeps the work in reach.** Its stylesheet
  no longer touches combo boxes, spin boxes, line edits or tick boxes, nor the
  normal state of a button, so QGIS's own style draws them: the spin box
  arrows are back under Fusion, and in Night Mapping the buttons are dark like
  every other dock instead of light slabs with grey words. The sheet paints only
  what means something: the tool or module in hand in QGIS's selection colour,
  a grey button with no fill and faint words so it plainly reads as one, and
  Delete, Set aside and Undo in Cutouts in red before the pointer gets there.
  Its colours come from the theme as it paints, not from a palette Night
  Mapping does not use, and it no longer reaches the windows the panel opens,
  whose OK and Cancel had shrunk to thirty pixels. The open module now sits
  right under the block that owns it, and the other blocks fold to one line
  (their name, what they hold, and an arrow that unfolds them): at 300 pixels
  the tools of Annotate begin under its button instead of under CUTOUTS. VIEW
  is one low row, the pad, step, keyboard and Detach, with a line saying what
  the keyboard does; the PANEL block is gone. RASTER and its list share a line,
  with the pixel and the system under it, and with nothing open a strip says
  what to do first. Every row of keys is a row of equal keys with none left
  alone on it: four are four or two and two, five are three and two. The four
  module buttons and Save are a size taller with QGIS's icons; no other key has
  one. Inside a module the groups have small headings and no frames of their
  own, Annotate's frame in hand moved up under Tiles and Move, and Objects and
  Correct use the same SHAPE, EDIT and Save. The class banner and the chips cut
  a long name instead of losing both ends of it, a line under the banner says
  what the next click does, the legend keeps two columns from four classes in
  Annotate, Objects and Correct alike, chip lettering is chosen by contrast, the
  FROM chips of Correct keep a rim on any colour, and clipped tick box labels
  were shortened. Key heights follow the font. The windows have one title
  pattern ("RasterLabel: ..."), sentence-case labels and one browse button;
  New campaign and Open a correction lose their empty bands and two-line
  labels, the second hiding the recipe of a new correction unless one is being
  made and naming its OK Open, Choose file or Create; Whole raster keeps the
  JPEG note under the format; Layers to cut opens wide enough for its columns;
  Export says which files as the boxes change; Check lists what is wrong first,
  coloured, wrapped and in a fixed font, like the Trouble window's detail.
  Closing a campaign with work not on disk asks Save, Discard or Cancel, and
  the recovery offer says what and when, with Put them back, Not now or
  Discard; Retire, Delete tile and replacing a campaign answer with Retire,
  Delete tile and Replace instead of Yes, and Delete tile warns instead of asking. A folded
  block says only what its name does not ("none open", "aragona_2025 · 6
  classes"), from the moment the panel opens, and a click anywhere on its line
  unfolds it. A legend of twelve classes or more takes its columns from the
  room, up to four, and FROM and TO in Correct always have the same number. The
  heights of the chips and the banners, and the widths of the number boxes and
  of the keys, follow the font and the style QGIS draws with, so a 13 point
  font or the windows11 style no longer cuts them. A window can no longer be
  made smaller than its words: Classes, Open a correction and the classes of a
  map overlapped their own buttons at their least size. Whole raster opens as
  wide as Export, with the same Where heading. Check lines its findings up in
  two columns. The red of Delete reads on Night Mapping's buttons, a grey
  button's word is fainter than a live one but still readable, and the arrows
  and the tick are drawn for every screen scale. One thing the panel does has
  changed, on purpose: Tab now walks through every control of the panel and of
  the module that is open, ringing the one it is on, where it used to stay
  between the map and the dock. A click on a key still leaves the arrow keys to
  the map, and the step box, the lists and the number boxes take the keyboard
  on a click as they always did. The layout suites check the new shape at
  every width, in the light theme, in a copy of Night Mapping and, where Qt has
  it, under the windows11 style: nothing overlaps, nothing is cut off, no key
  is alone on a row, the stylesheet names none of those controls, a grey
  button is plainly fainter than a live one, and every control is reached by
  Tab.
- **The panel holds at 260 pixels on Linux.** With DejaVu at twelve points, as
  Ubuntu draws it, rows of keys spilled or fell to two columns and tick boxes
  were cut. A row of keys now narrows to the width its words need, a tick box
  breaks its words onto a second line, the settings blocks are as tall as
  their wrapped rows, and VIEW puts the step's name over its box when the
  column would not fit beside the pad. Nothing changes where the words
  already fit, as with Segoe UI on Windows. The Import frames window holds at
  300 pixels with those fonts too. The windows of the measures, Compare,
  Time, Model vs corrected, the source of an uncertainty, Whole raster and the
  report window, hold at 300 pixels with the fonts of Windows and with DejaVu
  alike, nothing cut: their lists cut a long name at the edge of the box and
  show it whole when they open, the tick boxes and radio buttons with long
  words (the dataset card, the map of what changed, "touched by both
  readings", a reading with a long operator's name) break them onto a second
  line, the keys of the report window wrap onto a second line when they must,
  the headings and the names of the numbers wrap, and the choices of the
  source of an uncertainty stand one over the other instead of beside their
  lists. Whole raster still opens at the width it always had.
  `tests/test_dialogs_narrow.py` opens each at 300 pixels twice, with the
  fonts of the machine and with DejaVu, and where DejaVu is not to be found it
  says in capitals that it skipped that half.
  VIEW tries each shape of its column on the column itself: reckoned from
  the words, the shape said to fit at 300 pixels with DejaVu and Night
  Mapping did not, the column went under the pad, and the panel asked for
  the height of the shape beside it, so the chips of Correct were drawn over
  each other and Detach fell off the bottom.
- **A grey button says why.** With no raster loaded, New under ANNOTATION
  CAMPAIGN, New under CORRECTION, Correct and Cutouts are grey, and their
  tooltips now say "Load a raster first:" and where to load it from, with what
  Open can do without one. The other grey buttons say what is missing: no
  campaign open, no correction open, or the one open to close first.

- **Words that said the opposite of what happens.** The tooltip of
  Polygon said the polygons already there give way to it, when with *paint
  under the others* on, as it starts, it fills only the free ground; that of
  Vertices called its rule the brush's. A pass was "a layer of the work" in
  its tooltip and a reading everywhere else: it is a reading. The width of a
  line was said to be exact everywhere along it, when on a diagonal a square
  of that width laid on every pixel made it up to 1.41 times as wide. The tips
  and the next-step line no longer speak of mud and plants to someone drawing
  roofs, the panel closed names the menu that exists (Raster > RasterLabel),
  the error window no longer sends a plugin user to the Python Console, and the
  counts on the panel say "1 class" and "1 polygon". The README has a table of what the
  mouse and the keys do under each tool, and says that macOS has not been
  tried and that Ctrl is Cmd there.
- **New campaign proposes the raster you have selected.** It opened on the
  first raster by name, so Ok pressed at once made the grid of the wrong
  picture (five centimetres where the one on the screen was ten), for good,
  because the grid of a campaign is not changed afterwards. It now proposes the
  layer selected in the Layers panel, then the one the panel's RASTER box was
  set to by hand, then the one on top of the tree.
- **One panel, with the plugin installed.** Pasting the launcher into the
  console with the plugin installed made a second panel, two tools on the same
  map. It brings the plugin's panel forward instead, and says so in the log; to
  run the pasted file, switch the plugin off first. The dock has a name now
  (`RasterLabelDock`), so QGIS remembers where it was put, and a dock closed
  with its X and shown again takes the arrow keys of the map back.
- **On a Mac the hints say Cmd.** Qt maps Ctrl to the Command key there, so a
  hint that said "Ctrl+click" named a key that does nothing. The hints of
  Annotate, Objects and Correct use the name of the key the person has.

### Annotate, the frames and the partition

- **Neighbours of one class are one polygon.** Polygons of the same class, the
  same reading (operator and pass) and the same frame that overlap or share a
  border are joined when a new mark, Fill Gap or a moved vertex makes them
  meet, in the same undo step, so one Undo puts back exactly what was there.
  Corner-only contact, another class, reading or frame, lines, points and boxes
  are left alone. No product changes by a pixel (masks, votes, coverage and
  closed frames, Compare, consensus, Time, Model vs corrected, Cutouts, the
  card's pixel counts and areas), checked by burning a campaign with and
  without it; only the number of polygons does. The joined polygon keeps the
  earliest `created`, the only field the polygons table has that can differ.
  Where another reading lies over the same ground in a way that the order of
  drawing decides, they stay separate. Repair joins the neighbours of a
  campaign drawn before this, in its one step, and Check lists unjoined
  neighbours as a note that Repair fixes and says which overlaps are between
  polygons of one class.
- **Frames no longer overlap.** A frame dragged onto another frame stays where
  it was, and a new frame placed partly over an existing one is not created;
  the message bar names the frame in the way. Frames can still touch edge to
  edge. While you drag, the outline turns red when it lies over another frame.
  Import frames refuses them too (see *Import frames keeps the sampling
  design*). Check does not report frames that overlapped in packages made
  before this change.
- **A frame is moved or deleted only by whose work it holds.** A frame can be
  moved or deleted only when everything in it (polygons, lines, points and
  boxes, in every pass) is your own work in the pass you are drawing. Empty
  frames can be moved and deleted by anyone. Otherwise the frame stays and the
  message bar says whose work it holds and in which pass, for example "1 mark
  by ANNA in pass 1"; in a blind pass it says only that the frame holds work of
  another reading, without names. With Move down, such a frame is not picked up
  at all. Frames that pass the rule still ask "Move with its contents" or "Move
  and delete them".
- **On a tiled campaign, points keep to the frame like areas and lines.** A
  stroke and a line are clipped to the frame in the list; a point went down
  wherever the click was, inside a frame or not, and an export burned its
  square of pixels on ground no frame covered. A point is now dropped only
  inside the frame in the list and carries its name; outside it nothing is
  drawn ("nothing drawn: the point fell outside the tile", and "no tile
  selected" with none picked), and so is a point whose footprint would reach
  past the frame edge, since the export burns the whole square: a 9×9 point
  needs four pixels of room on every side. A point dragged out of its frame
  with the vertex tool is put back. Removing and reclassing still work
  anywhere, and a frame moved with its contents still takes its points.
  Check counts, as a note, the points outside every frame and those whose
  tile_id names another frame, and says how to clean them up. A campaign
  without tiles takes points anywhere, as before.
- **Move takes the map.** It used to be a switch and nothing else: with the
  polygon still in hand the pointer stayed a cross and a drag across a frame drew
  a polygon. Pressing it now puts the shape down, hands the map to the tile tool
  and shows the hand cursor; taking a shape again puts it back up.
- **A frame that holds work can move with it.** The only answer used to be
  "move it and lose them". There are now two: translate every mark by exactly
  what the frame moved, which is a whole number of pixels and keeps the
  partition closed, or delete them as before. Cancel is the default.
- The panel's boxes are in the order of the work, FRAME and LOCK first, then
  SHAPE, EDIT and Save; and the boxes of one or two buttons give them the whole
  width of the bar, so Move, Marks and Save are always in the same place.
- **A drag that lands the frame back in the cell it started from is not a move.**
  The guard against a wandering click was in screen pixels; zoomed in far
  enough, several screen pixels are less than half a raster pixel, the frame
  snapped back where it was, and the program still asked whether to move it,
  still rewrote every geometry inside it and still announced "moved by -0.00,
  0.00". The threshold is now the grid: no cell, no move, nothing said.
- **No green X left on the map after moving a frame.** QGIS's vertex tool
  stays connected to every table it has touched after it is put down, and
  checks each geometry changed afterwards, marking every fault it finds (two
  edges of an outline crossing) with a green X that only putting that tool
  down again deletes. A frame moved with its contents changes every polygon
  in it, so after Vertices and then Move the map kept green X marks that
  nothing in the panel could clear. When the vertex tool is put down the
  campaign tables now tell it their data changed, which is the signal on
  which it lets go of them. A campaign opened again does the same for the
  tables it adopts from the project, which the tool may still follow from
  before the plugin was upgraded without closing QGIS. While it is held its
  marks show as before.
- **The filter on the view was silently dropped.** What is shown is a renderer
  with the operator, the pass and the current frame as rules on it; `restyle()`
  replaces that renderer, and two places called it without putting the rules
  back. Adding a class with **+** was one of them, and the Annotate module never
  applied the filter when it opened at all. From that moment the map showed
  every operator and every pass while the brush, Fill Gap and the coverage still
  saw one of each: a frame read 100% covered with another operator's polygon
  lying across it, and the amber strip announced work "you cannot see" over work
  in plain sight. Both are fixed, and a static check now refuses a call to
  `restyle()` that does not filter again.
- **Strokes of the same class merge again on real map coordinates.** On a
  projected campaign (UTM, coordinates in the hundreds of thousands and
  millions of metres), a stroke that overlapped or touched a polygon of its own
  class was saved as a second polygon on top of the first, and Check then
  reported the two as sharing ground. The neighbours were found through a
  buffer of a billionth of a unit, which GEOS returns empty at coordinates that
  large. They are now found with a tolerance measured on the pixel grid, which
  works at any coordinate.
- **A frame or operator name with a quote or a backslash no longer breaks the
  view filter.** Frame names are now quoted the same way operator names are,
  and both have their backslashes doubled, because inside a QGIS string a
  backslash escapes the next character. A broken filter hides nothing, so
  during a blind pass it showed every earlier pass. Exporting one frame quotes
  its name too, the way SQLite wants it.
- **Renaming a class from the Classes window no longer loses the new name when
  the marks are locked.** If the save after the rename failed, the marks lock
  took the rename for an edit and undid it, so the features kept the old name
  and disappeared from the map. The guard that already protected a rename from
  the class bar now covers every way of renaming.
- **A vertex pushed into a neighbour never trimmed it.** In a closed partition
  the edited polygon shares its whole border with the neighbour before the drag,
  so the ground they share afterwards comes back from GEOS as a collection: the
  wedge the vertex pushed in, plus the stretches of border still in common.
  `settle_edits` skipped anything whose type was not polygon, which skipped
  exactly that, and "a moved vertex wins" had never worked in the one case it
  exists for. The overlap is now judged by its area. An earlier entry here put
  the "sometimes the class next to it stays" down to the direction of the drag;
  half of it was this.
- **A vertex dragged across its own polygon's edge jammed everything near it.**
  QGIS's vertex tool allows it, and what it leaves is a bow tie, an outline that
  crosses itself, which GEOS will not cut. Three faults turned that into a loop:
  the retry inside `cut_away` repaired only the polygon being cut and never the
  one cutting, so with the bow tie as the cutter it failed exactly as the first
  try had; `settle_edits` repaired the bow tie in a local variable and left it in
  the layer; and Repair went through the same cut, failed the same way, printed
  "press Repair" from inside itself and reported "0 overlaps resolved". Now both
  sides are repaired on the retry, a self-crossing outline is written back as the
  polygons it encloses the moment a vertex makes it, Repair untangles every
  outline in the frame before it cuts anything and counts what it still could
  not cut instead of reporting a calm zero, and Check reports outlines that cross
  themselves.
- **A border pulled back is given to the neighbour.** Dragging a vertex drags a
  border, and a border has two sides. Pushed into a neighbour it was already
  settled, the edited polygon winning; pulled back it left a hole, so half the
  drags grew a class and the other half knocked the frame off a hundred per
  cent, depending on a direction nobody can see while dragging. The freed ground
  now goes to the polygon sharing the longest stretch of that border. Ground
  somebody painted in the meantime is never given away, nothing travels outside
  the frame, and a piece bordering nobody stays the hole it is.
- **A vertex dragged in another frame was left unsettled.** Every frame is on
  screen unless "show the current tile only" is ticked, and the vertex tool can
  grab any of them; a drag outside the frame selected in the list was logged as
  "outside the current pass" and its overlap stayed. A moved polygon is now
  settled among the polygons of its own reading, its frame, pass and operator,
  and the shapes kept for comparison cover every frame. Other readings are
  never touched, whether or not "one operator at a time" is ticked: with it
  off, dragging one operator's border used to cut the other operator's
  polygons, and a stroke next to another operator's polygon of the same class
  merged it into the stroke under the name in hand.
- **Ctrl+Z after a vertex drag went back and forth for ever.** Undo replays a
  command backwards and fires the same signal a drag does; it was taken for a
  new drag and settled again, which pushed a command and threw the redo away.
  An undo is now told from a drag by whether an edit command is open, as QGIS's
  editing tools always open one, and the tidying after a drag is a single
  command of its own: Ctrl+Z takes it back, then the drag.
- **The marks lock let redo through.** A drag made while the marks were locked
  was put back with an undo, and Ctrl+Shift+Z brought it straight back; QGIS's
  own Ctrl+Z could rub out a stroke made before the lock. The lock is now a place
  on the undo stack of each table it holds, polygons, lines and points, and
  whatever moves one away from it while it is shut is walked back: a drag, an
  undo of a stroke that only added a polygon or only changed a class, a redo.
  It starts again from the bottom after any commit, Save or not. Delete tile
  no longer deletes what is drawn in a frame while the marks are locked. A
  tidying that fails half way is taken back without being announced as done.
- **After Save, a border pulled back left a hole.** A commit renumbers every
  polygon drawn since the last one, and the shapes kept for the vertex tool
  stayed filed under the old numbers. They are now taken again after every save.
- **A piece split off another reading was filed under the reading in hand.** The
  leftover of a trim, the lobes of an untangled outline and the ground a
  neighbour takes now keep the frame, pass and operator of the polygon they
  came from.
- **A frame moved with its contents could fill its own gaps.** Carrying the
  marks fired the vertex machinery, which took each translated polygon for a
  hand drag and gave the "freed" ground to a neighbour. The carry is now the
  program's own edit.
- **The + of the Objects legend raised an error** after saving the class, and
  the box to name it never opened.
- **A small object box could not be moved, and a click on it cut it to a
  quarter.** The corner handles reached a flat ten pixels whatever the size of
  the box, so on a box twenty pixels across they met in the middle: a press
  anywhere took the bottom left corner and the release pulled it to the click.
  The reach is now at most a third of the box's shorter side and at least three
  pixels, as the prototype had it. And a click on a box is a click: a corner, or
  the whole box, used to follow the few pixels a hand drifts between press and
  release. The object tool now has the same `MOVE_PX` threshold as the frame
  tool, so a stretch or a move counts only when it is worth a few pixels.
- **Box corners are grabbed correctly when the map and the campaign use
  different units.** With the campaign in degrees and the map in metres, or the
  other way round, the corner handles of a picked box came out far too large or
  far too small. The reach is now measured in screen pixels.
- **The number boxes fit the pixel.** The radius of the round brush, in
  Annotate and in Correct, and the side of a frame had limits made for a 5 cm
  orthophoto: a radius of 200 m at most in steps of a metre, a frame side
  from half a metre. On a 250 m grid the radius was locked at one pixel and a
  frame could not pass twenty; at 30 m the radius stopped at seven pixels; at
  1 cm one click of an arrow moved the radius a hundred pixels; at 2 mm the
  smallest radius read 0.00 and the smallest frame was 250 pixels. Each box
  now steps by one pixel, reaches 500 pixels for the radius and 4000 for a
  frame, or the old limit in metres where that is more, starts at 10 and 200
  pixels, and shows as many decimals as the pixel needs. On a picture the
  boxes count in px.
- **Class codes stop at 254.** The next class took the highest code plus one,
  with no ceiling, and a mask is one byte a pixel: class 256 went into it as
  0, without a word. A campaign now hands out 1 to 254, 255 being kept for
  "ignore", and a class past the last is refused, with the reason, in Classes
  and by the + on the chips. A campaign that holds a higher code all the
  same, from a manifest edited by hand, gets a 16 bit mask rather than a
  wrong one, and Check notes it: the mask is widened only when such a code
  is really there. Cutouts used to cut every layer of classes into bytes, so
  a 16 bit map with a class 300 came out with 44; it now uses a byte when
  every value of the map fits in one and the narrowest wider type when one
  does not, decided on the whole map so that every cutout of it has the same
  type. A map's own values are kept as they are, 255 included: the ceiling is
  for the codes a campaign hands out. A map with a value a PNG cannot hold, a
  nodata of -9999 for one, is cut as GeoTIFF when PNG was picked, since GDAL
  would clamp it into bytes and turn a class 300 into 255.
- **A stroke drawn over a polygon no longer throws away what it leaves of it.**
  What was left under four pixels was dropped as a sliver. It stays as a
  polygon of its own now (a vertex drag, Repair, an untangled outline and a
  merge keep theirs too); only a new stroke under four pixels is taken for a
  fleck. A frame marked closed has no pixel of no class, and Fill Gap finds a
  hole of one or two pixels instead of saying "no holes".
- **Boxes reach the recovery file.** Boxes stretched, given another class,
  deleted or undone in Objects now reach the recovery file, as a box drawn
  does.
- **Taking the polygons table out of the layer tree no longer makes strokes
  vanish.** The next stroke loads the table again from the campaign's file and
  says so. Close campaign removes only the layers the program made: the group
  stays, with the log saying so, when something of the person's is in it.
- **A project read again with Annotate open keeps vertex settling and the
  marks lock.** The tables the project brings back are other objects with the
  same id, and the check that a table was listened to was its id, so nobody
  listened to the new ones. The tables themselves are compared now, in
  Annotate and in the recovery net, so that discarding the edits of a table
  read again with the project still sets the strokes aside.
- **Topological editing and avoid intersections are put back.** Annotate
  turned both off and never gave them back, so a person who worked with
  topological editing on found it off in every project from then on. Setting
  the list of layers to avoid to nothing did nothing when the mode was the one
  that avoids the layer being edited: the mode is set now. Both are put back as
  the project had them when Annotate closes, and a project read while it is
  open brings its own values back at the close.
- **Closing Annotate or Objects gives the map the tool the person had before,**
  Pan when there was none, instead of leaving it with no tool. Backspace in the
  Line and Brush tools, and Delete or Backspace in the box tool, are left
  ignored once the tool has taken them, so QGIS does not also delete the
  selected features of the active layer.
- **A campaign goes on with the point size it has.** Opening it put the point
  size back to one pixel, so a second session of 9 x 9 points began by mixing
  two footprints; it now starts at the size most of the points already there
  have. The amber strip of a blind pass says "Pass 1 is hidden" where it used
  to say "Passes 1 to 1".

- **A line is as wide as you asked in every direction.** A line drawn with a
  width of N pixels is now N pixels across at a right angle to it, along a row,
  along a column and across a diagonal: a 5 pixel line at 45 degrees used to
  be 7 pixels across, so the area of fissures and channels depended on their
  direction. Each stretch of the trace is a rectangle N
  pixels wide, the two ends of the whole line are squared off half a width past
  the last points and the turns inside it are joined round, so that a line
  drawn freehand is no wider than a straight one; a pixel belongs to it when
  its centre is inside. A line exactly along a row or a column comes out
  exactly as before. A line of 1 pixel keeps to the thinnest unbroken chain
  (1.41 pixels across at 45 degrees). Lines already drawn keep their strips:
  the strip is stored in the polygons, so no mask changes at the next export,
  and only lines drawn from now on have the new width.
- **Import frames writes a whole number as a whole number.** A sample id or a
  stratum that a REAL column holds whole (R and pandas write every id so) was
  written 12.0 and 2.0, which no longer matched the design it was joined to. It
  is written 12 and 2; a true decimal keeps its digits. Frames an earlier build
  wrote as 12.0 and the same file imported again are the same sample: they are
  already there, and nothing is added or written over.
- **A project saved while Annotate is open keeps your own editing settings.**
  Topological editing and avoid intersections are written as you had them, in
  Ctrl+S, in QGIS's own project autosave and in Save As, not with the two
  switched off.
- **Undo's limit is said.** Undo stops at the last save, by hand or by itself;
  the Settings tooltip of the autosave and the message when there is nothing
  left to undo say so.

### Correct

- **Correct and Cutouts work without an annotation campaign.** All four
  module buttons stayed grey until a campaign was open, so a thematic map
  made by another program could not be corrected, and a raster could not be
  cut, without first making a campaign of hand drawing nobody wanted. Now
  Annotate and Objects, which draw into the campaign, need one and say so in
  their tooltip; Correct and Cutouts need only a raster. Opening or closing a
  campaign leaves Correct open, and rebuilds an open Cutouts, whose All tiles
  and Whole read the campaign. With no campaign open, Check says so as a
  note, not as a problem.
- **A correction is a campaign of its own.** It used to be a record in
  campaign.json and a folder of the campaign's. It is now a folder you
  choose, holding correction.json, the working copy, operations.csv and the
  log while Correct is open. The manifest keeps the map's own grid, so areas
  in m2 are measured on the map's pixel: they used to be measured on the
  pixel of the campaign's reference raster, wrong by the ratio whenever the
  two differed. The working copy is named relative to the folder, so the
  folder can be moved or zipped whole. Corrections opened lately are offered
  first, remembered by QGIS on this machine. "Delete" is now "Set aside": the
  folder is renamed, nothing is erased, and no annotation manifest is written.
  Check has a section for the correction while one is open.
- **The classes of a new correction are shown before the copy is made.** They
  are read from the map as before (its style, its colour table, its values),
  and a window then lists every value with its colour, its name, its pixel
  count and where it came from. Colours, names and values can be changed and
  classes added; the window refuses a name used twice, the nodata value as a
  class, and a value the map holds left without a row. Renumbering a row
  points a name at another value and never recodes a pixel. Cancel writes
  nothing. A Classes button in Correct opens the same window later, with the
  values the copy holds locked.
- **Corrections kept inside an annotation campaign still open, losing
  nothing.** Picked in the Correct window while their campaign is open, they
  get a correction.json beside their working copy, carrying their classes,
  count, areas and pairs and where they came from; nothing is copied, moved
  or deleted, and the record in campaign.json is kept with a pointer to the
  new manifest. That pointer is the only thing Correct ever writes into an
  annotation manifest.
- **Correct takes its classes from the map it corrects, not from the legend.**
  The chips, the class to change, the colours of the copy, Ctrl and click and
  the log all used the campaign legend, which is what Annotate and Objects
  draw with: on a land cover map numbered 0, 3, 7, 12 the brush offered the
  legend's 1 and 2 and wrote them into a map that never had them. A
  correction now reads its classes from the layer's style when it is
  Paletted/Unique values (or a pseudocolor ramp with exact classes), with
  their names and colours, and from the values the class band holds
  otherwise, of any type, nodata left out and zero counted as a class. They
  are kept in the correction's record in the manifest, so reopening shows the
  same chips; a correction made by an earlier build gets them the first time
  it is opened. A code met under a stroke or under Ctrl and click that the
  list does not have is given a class, with a line in the log, and "+" adds a
  class by its code for one the map does not hold yet. The Classes window
  changes the legend only. "Any class" now spares only nodata, not zero.
  The style QGIS gives a band with a colour table lists all 256 entries of
  the table: only those the map holds, or that carry a name, become classes.
  A float map whose nodata is NaN keeps its holes under "any class".
- **Correct says what it turns into what.** The banner showed only the class
  the brush writes, without saying so, and the class it replaces was a
  "change" list further down. The banner now reads "FROM crops ➜ TO forest",
  each half in its class colour, and says when the two are the same and a
  stroke would change nothing. Under it, FROM chips ("any class" and one per
  class, outlined) choose what the brush changes, and TO chips (one per class
  and "+", filled) choose what it becomes. On the map Ctrl+click picks FROM
  and Shift+click picks TO; Shift in Annotate still paints over. The manifest
  and operations.csv keep writing "every class" for any class, as before.
- **The TO class in hand in Correct is unmistakable on any colour.** Its chip is
  ringed thick in the colour its own name is written in: black on a light
  class, white on a dark one with a dark rim outside, so it also stands out
  from the panel. It also carries a tick before its name. Before, the chosen
  chip on a navy or dark brown class differed from the others only by bold
  lettering and a faint white edge. The other chips, and all of Annotate's
  chips, look as before. The room for the tick is counted when the chips are
  laid out, so a name that fits is not cut when you choose it.
- **Correct closes the corrected map after every stroke.** Correct held the
  corrected map and its `_changes.tif` open for writing for the whole
  correction. With the libtiff of Debian and Ubuntu a compressed block it
  flushed cannot be read by another handle until the writer closes, so on
  Linux the map went blank in QGIS after the first stroke, and a QGIS that
  died left the blocks of the last stroke unreadable. Each stroke and each
  Undo now open the files, write their window and close them before QGIS
  reloads the layer; a stroke that cannot be written is said and not made, so
  the brush and the file never disagree. The files are unchanged, and on a
  10000 x 10000 map a stroke costs a few milliseconds more.
- **The corrected map is a thematic map, and opens like the original.** The
  working copy used to be the map plus a sixth band, "corrected", with no
  style, so QGIS opened it as a picture: the class on red, the probability on
  green, the entropy on blue. It now has exactly the bands of the map it
  corrects, in the same order, with the same names, type, nodata, grid,
  coordinate system, tiles and compression; the class band holds the
  corrected classes, every other band is copied unchanged, and the statistics
  of the class band, which the correction makes wrong, are left behind. A
  `<map>_corrected.qml` beside it makes QGIS open it paletted on the class
  band with the classes of the correction, following the original's own
  `.qml` when it has one (its opacity, for one), and the class band carries
  the same classes as a colour table and category names for GDAL, rasterio,
  ArcGIS and the rest (in the `.aux.xml`, the only place GDAL keeps a table
  for a GeoTIFF of several bands). Both are rewritten whenever the classes
  change and every time Correct opens and closes. Which pixels a person
  changed moved out of the copy into `<map>_corrected_changes.tif` beside it,
  one byte band on the same grid, named in `correction.json`, written by every
  stroke and taken back by Undo. A copy made before this change is converted
  the first time Correct opens it, losing nothing: the band is written out
  and read back first, the copy is rewritten without it under a temporary
  name and compared band for band and pixel for pixel before it replaces the
  old one, the manifest is told and the log says it in one line; a conversion
  stopped half way leaves the old copy as it was, and the next opening
  finishes it. Check compares the copy with the map it corrects, band for
  band, and looks for the `_changes.tif` and the `.qml`. Opened as a layer in
  a real QGIS 3.36, 3.44 and 4.2, the corrected map is paletted with the
  right classes; two new suites, test_correct_thematic and
  test_correct_qgis_style, hold it there. Once the corrected map has its
  `.qml`, that one is the one kept: only its renderer, band and classes are
  rewritten, so opacity and anything else set in QGIS with Save as Default
  survive the next class change, open and close (they used to go back to the
  original's). The conversion tells `correction.json` the new class band
  before the copy is replaced and keeps the old one while the old copy may
  still be there, so a QGIS killed between the two no longer leaves the brush
  painting into the probability band; the old copy's `.aux.xml` waits under a
  name of its own while the copy is replaced, and a stop at any point is
  finished or undone at the next opening, instead of leaving the statistics
  and the sixth band of the old copy in the new one's `.aux.xml`. It runs
  under an hourglass with a line on the message bar, and says there when it
  had to take the user's own layer of the old copy out of the project. A map
  whose bands differ in type is copied in the type GDAL gives their union
  (Int16 and UInt16 make Int32, no longer UInt16, which turned every negative
  value into 0), then compared with the map and refused if any value moved.
  Set aside in a folder that also holds an annotation campaign moves only the
  correction's own files into a `set_aside_` folder, instead of renaming the
  campaign's folder from under it. The `_classes.tif` of a cutout of a layer
  styled in classes carries them as its colour table and opens in colour.
- **Correct reads the class names of an attribute table.** A map whose
  classes are named in a Raster Attribute Table, as ArcGIS and many
  classifiers write it, in the `.aux.xml`, inside the file or as a
  `.tif.vat.dbf`, showed "class 1", "class 2" in the classes window whenever
  QGIS had not styled it from that table, and the `.tif.vat.dbf` is one the
  GDAL of QGIS 3.36 does not read at all. The table is now read, its columns
  known by what GDAL says they are or by the names classifiers give them
  (Value, Class_Name, ClassName, Red, Green, Blue, Count, and a table indexed
  by value with no column of values), for the names and the colours; on QGIS
  3.44 and 4, which style a `.tif.vat.dbf` in colours of their own, the
  table's colours are used. A style entry labelled with its own number, the
  label QGIS gives every entry of a colour table, is no longer taken for a
  name: the file's own name for that class is used, or "class 7".
- **The corrected map's attribute table follows the correction.** The copy
  carried the attribute table of the map before it was corrected: its names,
  its colours and its pixel counts, without the classes added in the
  correction. QGIS opening the corrected map without its `.qml` showed those
  names, and so did any program reading the table. It is now rewritten with
  the `.qml`, a row per class with its name, its colour and its count in the
  corrected map, every other column kept, and a map that came with a
  `.tif.vat.dbf` gets `<map>_corrected.tif.vat.dbf` alike (written in place
  when QGIS 3.36 holds the old one open). What could not be written of the
  style, the colour table and the tables is said in the log.
- **Correct offers the band the map's style draws.** The band of a new
  correction was the first whose name said "class", else band 1: a stack of
  probability, class and entropy with unnamed bands and a `.qml` on band 2
  was offered the probability. The band the style draws in classes now comes
  first, and after the band named "class", the first that carries an
  attribute table, a colour table or category names in the file. Only a
  style that names classes counts, Paletted or a pseudocolor ramp that is
  Exact or Discrete: a stretch over the probability band says nothing about
  where the classes are, and the band named "class" is still the one offered.
- **The corrected map keeps the layout of the map, and opens fast.** A
  BigTIFF was copied as a classic TIFF; it stays a BigTIFF. A band of sixteen
  bits that came with no colour table was given one, which TIFF makes 65536
  colours long, and QGIS 3.36 then took ten seconds to open the corrected
  map, `.qml` or not; it now gets its classes in the `.qml` and the category
  names, and keeps a table only if it came with one. On a map of several
  bands GDAL reads a colour table back on band 1 alone: one written for a
  class band further down was never seen, and turned it into a palette with
  no colours, so it gets its category names only. Those category names, and
  those of the map read for the classes window, are read and written once
  GDAL has the `.aux.xml` in: before, the names of a class band other than
  the first were lost after the first time they were written, and those of
  the map were not read at all. Overviews are not copied, a cloud optimised
  GeoTIFF's included: they would show the map before the correction.
  Two new suites, test_correct_typical with real GDAL and
  test_correct_typical_qgis in a real QGIS 3.36, 3.44 and 4.2, walk the maps
  people load (one band of bytes and nothing else, a colour table, a `.qml`
  paletted or pseudocolor, sixteen bits with codes up to 65000 and nodata 0,
  255 or 65535, a stack with the class band not first, an attribute table, a
  `.tif.vat.dbf`, a tiled BigTIFF, strips, a cloud optimised GeoTIFF) through
  a new correction, the classes window, strokes, Undo, Save, Close and
  opening again, and check the copy against the map.
- **Correct asks before it uses anything that is already on disk.** A working
  copy is now recognised first by the `_changes.tif` beside it (or, for a copy
  made before the change above, by its "corrected" band), then by its
  `_corrected` name, then by a `correction.json` that names that very file,
  and the `_changes.tif` itself is refused as a map to correct, so
  a correction made in the map's own folder no longer makes the original map
  look like a copy. Choosing a working copy as the map to correct offers "Open
  the correction that owns it", looked for beside the copy, in the recent list
  and in the annotation campaign; when no owner is found, the message explains
  how to open it by hand. Choosing a map that already has a correction offers
  "Open that one", "Make a new correction" or Cancel. A folder that holds
  `<map>_corrected.tif` but no `correction.json` is no longer reused silently:
  "Resume it" keeps the copy with all its corrections, shows the classes first
  with the copy's values locked and reads the counters back from
  `operations.csv`; "Start from a fresh copy" moves the old copy, its
  `.aux.xml`, `.qml` and `_changes.tif` and its `operations.csv` into a
  `set_aside_` folder, never deleting them. Using the
  map's own folder is still allowed, after a warning, and the Correction window
  says so before Ok. Opening a correction from the list or with Open a
  correction.json... works as before.
- **Correct says when the map chosen is not a map of codes it can mend as it
  is.** Two kinds of map went ahead without a word. A class map saved as a
  JPEG, or with another compression that does not keep values exactly, holds
  values along the edges of its classes that are no class, and the classes
  window offered them as classes (seven for a map of four). It now asks
  first, Yes or Cancel with Cancel the default, naming the compression:
  JPEG, a GeoTIFF compressed with it or with LERC allowed an error, a lossy
  WebP or JPEG 2000; a WebP or JPEG 2000 written without loss is not asked
  about, as GDAL's `COMPRESSION_REVERSIBILITY` says. A class map exported as
  a picture in
  colour has its classes as colours across red, green and blue, and the
  correction made classes of the shades of the red band, with no question at
  all when the picture had few colours. It now gets a question of its own,
  before the one about too many values and instead of it, that says to
  convert it to a map of one band with one code per class first. A stack of a
  classifier's, three bands of bytes that GDAL calls red, green and blue, is
  not taken for a picture when a band says what it holds, by a name, a colour
  table, category names or an attribute table. The Correction window says
  each of these in its note as soon as the map is picked, and that a map on a
  rotated grid is refused (see below). `test_correct_inputs_qgis` chooses
  each in a real QGIS 3.36, 3.44 and 4.2.
- **A picture with no georeference is corrected where QGIS draws it.** QGIS
  draws a PNG or a JPEG that has no world file and no `.aux.xml` with y going
  down from 0 to minus the number of rows, and every stroke is drawn there.
  GDAL, asked for the grid of the same file, answers its default, with y
  going up, and Correct read it that way: every stroke said "the stroke falls
  outside the map" and changed nothing, Ctrl and Shift and a click found no
  class, and the `_changes.tif` was written on GDAL's grid, so QGIS drew it
  beside the map. The grid is now read as QGIS draws it (`pixel_grid` in
  `rasters.py`), the record gets no grid when the copy has none, a record an
  earlier build wrote on GDAL's grid is put back on the copy's when Correct
  opens it, and Check says when a record is not where its copy is.
- **A map written north-down can be corrected.** A raster with a positive
  pixel height has its first row at the bottom. The window of a stroke was
  worked out as if the first row were at the top, came out with a negative
  height, and every stroke "fell outside the map". The window now puts its
  two edges in order whichever way the grid runs, rows and columns alike.
  The pixel under the cursor is found by rounding down instead of toward
  zero, so a click up to one pixel off the map no longer reads the class at
  its edge.
- **A map on a rotated grid is refused by Correct and named by New campaign.**
  A raster whose rows are not parallel to the x axis (a Helmert world file
  from the Georeferencer, some aerial products) was corrected on a grid that
  was not its own: a stroke changed pixels beside the ones under it, and
  `operations.csv` and the tally recorded it as right. New correction now
  refuses such a map before anything is written, and the Correction window
  says so as soon as it is picked; a correction made before does not open
  either, and Check says why; all of them say to warp the map
  north-up first (Raster > Projections > Warp, nearest neighbour for a map of
  classes, or `gdalwarp -r near`). New campaign accepts a rotated raster but
  says that QGIS shows it resampled north-up, so frames, lines and points sit
  on that view of it and not on its own pixels.
- **Correct opens a map of hundreds of millions of pixels in the memory of a
  small one.** It read the class band and the record of changes whole into
  memory when it opened, and counted the codes of the band by turning all of it
  into 64 bit integers: a map of 20000 x 20000 bytes took 6.8 GB above what
  QGIS already held, and a new correction on it 6.8 GB as well. The band and
  the record are now the files, read a window under a stroke or a strip of two
  million pixels at a time, the classes of a new correction and Check count the
  same way, and the same map opens in 0.37 GB.
- **The uncertainty of a map of hundreds of millions of pixels is read in
  strips too.** Correct kept the whole file of u in memory, a byte a pixel, and
  the report held it again with the record of changes and the net change from
  the map the correction started from: a map of 20000 x 20000 pixels with a
  probability band took 690 MB to open and 2.1 GB to report on. The file of u
  and the record of changes are now read a window or a strip at a time from
  their files, the net change is worked out window by window, the places are
  scored a block at a time, and the histograms, the counts and the strokes of
  the report go through strips of at most two million pixels (one row of tiles
  at the least). The same map opens in 261 MB and reports in 264 MB, of which
  191 MB is the program itself, and the files and the report are the same bytes
  as before. The Processing algorithm `rasterlabel:uncertainty_report` reads
  its maps the same way.
- **The "see through" row of Correct keeps its slider at 260 pixels with
  DejaVu.** The word, the slider and the box shared one row: the slider came to
  22 pixels, a handle and no track, and the box ended a pixel from the edge.
  The row is one line while the slider keeps the width of its own word, as the
  font in use measures it, and two when it would not: the word and the box on
  the first, the slider the whole width of the second. Nothing changes where it
  already fitted (Segoe UI on Windows at any width, DejaVu from 340 pixels).
- **Correct's tally says "597.73 m2 in 3 strokes"** instead of "3, 597.73 m2",
  so the count cannot be read as a thousands separator.
- **Areas on the ground, row by row, on a map in degrees or in Web Mercator.**
  The area of a stroke was the pixel at the middle of the map times their
  number: 1.6 times too much at 55 to 60 north on a map of 0 to 60, 0.87 times
  at the equator, 2.4 times in Web Mercator. It is the ground the pixels
  cover, measured on the ellipsoid row by row, as the area of the stroke is. A
  map in UTM or any metric system of its own keeps the numbers it had. The
  Dataset card (the changed area and the m2 of each transition) and Model vs
  corrected (the scope, the classes and the confusion matrix in m2, the net
  change, the transitions and the polygons) add up the ground the same way, so
  the card no longer blames undone strokes for a difference on a map in
  degrees that Undo never caused.
- **Undo leaves a trace, and the panel counts net of it.** `operations.csv`
  stays the log of what was written, in its fourteen columns, with the row of
  the stroke that was undone; the manifest says how much of it was undone
  (`undone`, only once something was), and the panel counts net of it:
  operations with "(n undone)", the m2 and the pairs without the undone
  strokes, and a line "on the ground, once each" when strokes went over the
  same pixels. The list of corrections shows the net count, and Model vs
  corrected gives the undone part beside its gross logged figures.
- **A correction no longer has one operator for ever.** Strokes are filed
  under the operator typed in a new box under Settings, else the operator
  picked in the panel in this session, else the one who made the correction;
  a name typed in the window that makes a correction stays its operator while
  the session still holds the reading it held then, and the log says when the
  strokes go to another reading. The manifest's list of operators grows when
  somebody else strikes.
- **A write that fails is refused as a whole.** Nothing is counted, logged
  or kept in the history, and the blocks that did reach the disk are put back.
  A copy that cannot be opened for writing is refused with one message: the
  stroke is put back only when the file was opened. The record of changes given
  up on its own leaves the strokes working.
- **Saving the QGIS project while Correct is open no longer saves the map it
  started from unticked,** and the view of the original follows the main view
  into another coordinate system.
- **A correction's working copy is looked for in its own folder.** A
  `correction.json` whose `working_copy` climbed out of the folder with `..`
  made Correct write the map and the style of another file; only the file name
  is taken now, which is what Correct has always written.

- **Correct: every FROM chip looks like the others.** The chosen FROM chip was
  filled with its class colour, so a class a person added, a yellow "test"
  say, looked like a block of paint beside the rest. All FROM chips are now
  neutral with the class colour as a thick edge on the left; the chosen one
  is marked by a thick outline in the colour of the text, bold lettering and
  a tick before its name, as TO has, in light, dark and Night Mapping, with
  pale and dark classes. "any class" keeps its own look.

### Rasters with no system, odd grids and pictures

- **A raster with no coordinate system is measured on the plane.** Measured
  on the ellipsoid of the project with no system under it, its coordinates
  were read as degrees: the coverage of a frame read "nan%", a line "nan m",
  `side_m`, `length_m`, `width_m` and `height_m` were left empty in the
  tables, a frame's `closed` never became 1, and on a small picture whose
  coordinates stayed inside ninety a 60 x 40 pixel polygon measured thirteen
  million square kilometres. With no system the ruler is now the plane, in
  the raster's own units, the pixels of a picture or the units of its world
  file, which is what its manifest calls metres. Objects no longer lets a
  box measured NaN through as not too small, and the ruler Cutouts measures
  the side of a cutout with is on the plane as well.
- **The system of a picture reaches its campaign and its files.** GDAL reads
  the world file of a PNG, a JPEG, a BMP, a WebP or a JPEG 2000 but not the
  `.prj` beside it, so a picture placed with both opened with no system, and
  the New campaign window said in one line "pixel 0.100 x 0.100 m" and that
  sizes would be in pixels. It now says the pixel is in the units of the
  world file, says when a `.prj` names a system QGIS did not apply, or when
  the layer's system was set in QGIS and is not in the file, and on Ok offers
  to write it beside the file, in its `.aux.xml`, where GDAL reads it: the
  campaign, the masks and the cutouts then carry it, and the picture itself
  is not touched; with no other layer placed on the ground the project takes
  that system too, so the picture stays where it was drawn. QGIS writes back the `.aux.xml` it holds when it lets go
  of a file, over anything written there meanwhile, so it is made to let go
  first. A world file with no system at all is said too, and so is a `.prj`
  beside a picture nothing places on the ground, a WebP whose `.wpw` the GDAL
  of QGIS 3.36 does not read: applied, it would have put the picture's pixels
  at 0, 0 of that system, so it is not offered. The working copy of
  a correction gets the system of its layer when the map's file names none,
  instead of being born with none.
- **New campaign says what else it sees in the raster.** Pixels that are not
  square on the ground, in a UTM survey with 4 x 6 cm pixels or in any
  orthophoto delivered in WGS 84: a frame stays square in pixels, which is
  what a chip for training needs, and the window and the frame side under
  Settings say how many metres that is each way. A photo stored turned by its
  EXIF orientation, which QGIS shows as stored, on its side, while every
  photo viewer turns it: the mask and the cutouts follow the stored pixels.
  `test_input_grids_qgis`, in a real QGIS 3.36, 3.44 and 4.2, makes each of
  these rasters and walks it through Correct, New campaign, Annotate and
  Objects.
- **A raster in WGS 84 "bound to itself" is measured in metres again.** Some
  orthomosaics declare WGS 84 with a TOWGS84 of seven zeros. GDAL hands that
  to QGIS as a BOUNDCRS, which QGIS 3.36 gives no EPSG code and calls not
  geographic, although its coordinates are degrees. The program took "not
  geographic" for metres: the round brush of half a metre was buffered by half
  a degree, its preview covered the whole screen, one click filled the frame,
  and the log said "drawing in ?, measuring in ?". Degrees or metres is now
  decided by the units of the system, a system without a code is named by
  PROJ when it is certainly the same as a registered one (this one is
  EPSG:4326), and the brush is measured in the UTM zone of the site as
  before. When no metric system can be found at all, metres are turned into
  campaign units with the pixel size the manifest holds, instead of being
  used as campaign units.
- **The manifest no longer writes "" for a system that has no EPSG code.** It
  writes the code when there is one and the whole WKT otherwise, and every
  reader takes both. "" is left for a raster that really has no system.
  A campaign already made with "" and the GeoPackage's stand-in for "no
  system" in its tables is repaired when it is opened: the system is read
  from the tables, or from the reference raster, and written into the
  manifest, and Check no longer reports that the raster has no coordinate
  system. The tables of a new campaign get the raster's system even when it
  does not come through as WKT1, instead of silently getting none.

### Whole raster and Export

- **The Whole raster comes out in the colours of the screen.** Its pictures
  (the image with the annotation, the plain image, the figure) were rebuilt
  from the raw bands with a stretch of their own: an eight bit RGB image came
  out about thirty levels off what QGIS showed, because QGIS draws it as it
  is and the limits it keeps were applied anyway; a paletted map came out as
  its indices in grey; sixteen bits came out with another stretch; and what
  was transparent on the screen came out opaque. Each strip is now drawn by
  the layer's own style, its brightness, contrast, gamma, hue and saturation
  included, and the plain image is what a QGIS map render shows, pixel for
  pixel. A layer that can show anything see-through (an alpha band, nodata, a
  transparent class or colour, an opacity below full) gets an alpha band in
  its GeoTIFF and PNG pictures, the paint lying over a transparent pixel at
  its own opacity; a JPEG holds no alpha and gets the transparent part on
  white. A rotated raster, which QGIS draws on a grid of its own, is still
  stretched from its bands, and a band shown with no contrast enhancement is
  now stretched as QGIS shows it, from 0 to 255. `test_whole_export_qgis`
  holds every case up against a real map render on QGIS 3.36, 3.44 and 4.2.
- **The Whole raster of a picture with no georeferencing, and of a rotated
  raster, carries its annotation.** For a PNG or JPEG with no world file and
  no `.aux.xml`, GDAL answers rows going up the y axis, while QGIS draws the
  picture, and the annotation is drawn, at y = -row: the mask came out empty,
  the painted image the same as the plain one, and the files opened off the
  picture. The grid QGIS uses is taken now, and the outputs open over the
  picture. On a rotated raster each strip after the first was burned metres
  away from its pixels, the window of a strip left out what lay in its
  corners, and a point was a square of the wrong shape: of six polygons on a
  raster turned by thirty degrees, one reached the mask. The strips, their
  windows and the points now follow the rotated grid, and the mask is the
  annotation burned on it, pixel for pixel.
- **The Whole raster to PNG or JPEG no longer holds the image in memory.**
  Those two formats can only be copied out finished, so the painted image,
  the plain image and the mask were held whole in memory until the end,
  about seven bytes a pixel: eight gigabytes for a photograph of 40000 by
  30000 pixels, the very thing the strips are there to avoid. They are now
  painted strip by strip into a scratch GeoTIFF beside the file, copied out
  at the end and the scratch file removed, a failure taking it away too.
- **Export says when it cannot give degrees, and never calls an empty file
  written.** A campaign with no coordinate system, a picture or a world file
  without one, has its coordinates in pixels, which nothing can turn into
  longitude and latitude; GeoJSON and KML reprojected them all the same and
  came out with no feature at all, said written (GDAL 3.13), or with pixels
  labelled as degrees (GDAL 3.8, in QGIS 3.36), and a shapefile with
  "in longitude and latitude" ticked came out empty too. Whether there is a
  system is now taken from the manifest: without one the degrees box is off
  and greyed, KML, which holds degrees only, cannot be chosen, and every
  other format writes the coordinates as they were drawn, with no system in
  the file, and says so. And every file written is read back and its shapes
  counted against the campaign: a table that lost some is named in the
  message, and a file that holds none of what it was asked for is taken away
  and reported as not written.
- **Whole writes on QGIS 4.** It handed the message bar a bare 0 as the level
  of its "writing the whole raster" line, which PyQt6 refuses: on QGIS 4 every
  Whole raster stopped on a TypeError before writing a single file, whatever
  the input. The level is the enum now. The static check that refuses a bare
  number as a level looks at `pushWidget` too, the stand-in message bar of the
  suites refuses one as PyQt6 does, and `test_message_levels` hands each level
  to a real `pushWidget`.
- **Painting the whole raster to PNG or JPEG no longer falsely warns about a
  half-written file.** PNG and JPEG are copied out only at the end, so a paint
  that failed part way left nothing behind, yet the message bar said a file
  could not be removed. The warning now appears only when a file is really
  left on disk.
- **A failed Paint Whole Raster left a truncated GeoTIFF behind on Windows.**
  The cleanup popped each target and cleared its name, but walked a snapshot of
  the items while doing it, and that snapshot kept every dataset open until the
  loop ended. Windows will not delete an open file, the removal failed, and the
  failure was swallowed: next to an error saying nothing was written lay a file
  that looked finished. The loop now walks the keys only, so the dataset is
  closed before the removal, and a removal that still fails is said out loud.
  Linux deletes open files, which is why the CI run never saw it.
- **KML and CSV exports give the polygons back exactly.** Of twenty-three
  polygons of a real campaign, two came out of the KML and the CSV invalid (a
  ring that touched or crossed itself), while the campaign and its GeoPackage, shapefile and
  GeoJSON exports were valid. Polygons cut against their neighbours can hold two
  vertices a hundredth of a nanometre apart; GDAL writes coordinates as text
  with fifteen significant digits, about ten nanometres on a longitude, and
  wrote both as the same point. The same rounding made eight pairs of
  neighbours overlap, by slivers ten nanometres wide. The KML and the CSV
  are now written with every coordinate in full, so they read back as the very
  same doubles: GDAL is asked for seventeen digits, and where it does not
  honour that (GDAL 3.8 inside QGIS 3.36 decides its digits once per session)
  the coordinates it wrote are written again from the campaign, exactly.
  Every exported file is read back, and a polygon valid in the campaign that
  came out invalid is named in the message.
- **Exporting again into the same folder replaces the CSV, GeoJSON and KML
  files.** GDAL could not overwrite the CSV and GeoJSON, left the first export
  in place, and the window said they were written. An old KML it handed to its
  other KML driver, which rewrote it in another layout, with an altitude on
  every vertex and fifteen digits again.
- **The mask of Whole carries its legend.** It held the class codes and a band
  called `class_code`, and nothing else: grey in QGIS, and whoever received it
  could not tell a 3 from a 4. A GeoTIFF mask now has the classes of the
  campaign as its colour table and category names (the names in the `.aux.xml`
  beside it, as for the corrected map of Correct), and any mask has a `.qml`
  of the same name that QGIS opens it with, followed rather than overwritten
  when one is already there. The pixels are exactly what they were. Cutouts of
  such a mask, its STAC items (`classification:classes`) and `sampler.json` now
  list the classes, with or without an ignore value.
- **A mask written in strips is the mask one pass would write.** A pixel whose
  centre lies exactly on the edge of a polygon went to the polygon or not
  depending on the height of the strip it fell in, because each strip was
  burned on a grid moved down by its first row, and the rounding moved with
  it. Every strip is now burned from the shapes in the pixels of the whole
  raster, shifted by whole rows, which is exact; the card counts its pixels
  the same way, and so does Compare readings. This changes pixels that were
  decided by a tie: a mask or a comparison made again with this build can
  differ from an older one on pixels whose centre lies exactly on a polygon
  edge, and nowhere else.
- **The vector layers held in memory use the driver GDAL still has.** GDAL
  3.11 moved "Memory" into "MEM" and warns at every use of the old name; Whole
  and Export would stop working the day it goes. "MEM" is asked for first.
- **Export to GeoPackage works near 260 characters of path on Windows.** Its
  folder, its file and the file it replaces are reached through the long-path
  prefix, which SQLite needs where GeoJSON and the others did not.
- **Text that leaves the program cannot run in a spreadsheet.** Every CSV the
  program writes (cutouts, operations, journal, design log, places, reports,
  the CSV export) starts a text that begins with `=`, `+`, `-` or `@` with a
  quote, and leaves numbers alone; every reader of those files takes the quote
  off again, so a cutout called `-x_0001` is found by Undo and by the check for
  missing files, in a folder written by an older build as well. The CSV export
  is checked and rewritten row by row, never held whole in memory, and cells
  longer than the csv module's own limit are read.

- **The Shapefile export keeps class names outside Latin-1.** The table of a
  Shapefile was written in Latin-1 and a class named in Chinese, Greek or
  Cyrillic came out as question marks. It is written in UTF-8, with a `.cpg`
  beside it that says so.
- **Whole raster asks about work that is still pending.** Reached from Cutouts,
  it made the mask and the card from the package without work that a failed
  save had left in a buffer. It now writes what it can and asks "Export
  anyway?" about the rest, like Export vectors, with Cancel as the default.

- **Export: how the readings are arranged.** A new list in the Export window,
  *How the readings are arranged*: **everything in one** (a single set of
  files holding every reading, operator and pass as attributes, as before) or
  **one per operator** (a set of files for each operator, holding all the
  passes of that operator, the pass an attribute, named
  `<campaign>_<OPERATOR>_<table>` or `<campaign>_<OPERATOR>` for a format that
  holds all the tables in one file). One per operator goes with *all readings
  together*; with one reading or a consensus chosen the list goes back to
  *everything in one* and is greyed.

- **Export: one .zip.** *also pack it all in one .zip* writes, besides the
  files, `<campaign>_export.zip` in the same folder, holding every file the
  export wrote (all the formats chosen, the dataset card, and what goes beside
  a file: the `.csvt`/`.prj` of a CSV, the parts of a shapefile). The names
  inside are relative to the folder. It is written under a temporary name and
  renamed when whole, so a failure leaves the old archive or none.

- **Work hidden from the reader is asked about once.** Export used to write
  the tables with the hidden readings in them and refuse only the dataset
  card, which counts the same work. Now, when the files about to be written
  hold readings that the Annotate filter keeps from the reader in hand
  (*one operator at a time*, *blind*), one question comes before anything is
  written: "These files contain work hidden from OPERATOR 1 (OP2 pass 1, OP2
  pass 2). Write them anyway?", with Cancel as the default. Yes writes
  everything, the card included; Cancel writes nothing. When nothing is hidden
  there is no question. The Whole raster asks the same for its dataset card
  ("The dataset card holds work hidden from ...") instead of leaving the card
  out. Measure's reports keep their gate as it was.

- The Export window can be made as narrow as a 300 px dock (it was held at
  460 px), with the fonts of Windows and of Linux.

### Cutouts

- **Boxes as detection labels.** With a campaign open, Cutouts writes the boxes
  of Objects in the pixels of each image: `boxes_coco.json` for the folder and
  `labels/` with one YOLO file per image and `classes.txt`. They are put in the
  coordinate system of the cutout when it is not the campaign's, and in the pixels
  of each file, so a layer that keeps its own grid and is clipped by its own
  edge gets its own numbers. Every image over ground that was read has its
  file, empty when no box falls in it. In a campaign with frames the ground
  that was read is the ground inside them, as for the ignore value of Whole: an
  image the frames do not cover would get an empty file that says "nothing
  here" over ground nobody looked at, a negative sample that is not one, so it
  gets no label file and no place among the images of the book, and is listed
  under `unlabelled_images` (its cutout, its layer, its size, the share of it
  the frames cover, and why), which a YOLO tool, that reads a picture with no
  label file as a picture with nothing in it, needs to be told. The log says
  how many were left out. A campaign without frames has no unread ground to
  tell apart. If the boxes cannot be put in the system of the cutout, none is
  written and the log says so.
- **Cutouts of a map of classes with a negative nodata no longer stop.** A
  nodata of -9999 stopped them with "list index out of range": the nodata is
  now kept, declared in the cutout, and left see-through in the coloured
  picture. A Float32 map of classes with the nodata -3.4e38 (Raster Calculator
  and SAGA write it) is cut in a byte when its classes fit in one, with the top
  of that type declared as the nodata, instead of as Int32 holding the smallest
  32 bit number.
- **A web basemap or any layer that is not a file no longer stops Cutouts or
  Whole raster.** GDAL raises, instead of answering nothing, once QGIS has
  switched its exceptions on, which it does. The layer is skipped and the
  message says why ("it is not a raster file (a web or database layer)"); the
  same guard is in every place that opens what a layer names.
- **A long layer name keeps its ending in the names of the files.** A layer's
  name was cut at 48 letters, and the ending is what tells one map from
  another: `..._disag_classes` and `..._disag_probabilities` of one model
  became one name, the second numbered `_2`. A name of 48 letters or less is as
  it was. A longer one keeps its beginning and its last words, and gives its
  middle for six letters of the SHA-1 of the whole name
  (`aragona_orthomosa-2d21f6_v3_disagreement_classes`), 48 letters in all. The
  same word is in the file names, in `cutouts.csv` and in the STAC assets. A
  folder cut before keeps the names `layers.json` remembers, letter for
  letter. The Layers window makes the same names: a layer it has not met, one
  that was ticked off, or one switched from ignore to image or classes, is
  offered the same tag, and a tag left as the window offered it is kept whole,
  a `_2` included; a tag typed by hand is held to 48 letters, ending kept.
  Whole raster names its files the same way; a folder exported before with a
  layer name past 48 letters gets the new names beside the old files, which are
  left alone.
- **Cutouts saves no campaign.** Its folder used to be kept in campaign.json,
  the sizes of each side too, and every cutout added a line to the manifest.
  The folder and the settings are remembered by QGIS on this machine; the
  sizes of each side are kept in shapes.json in the output folder (taken
  once from a campaign that kept them); nothing is written into any
  manifest. Every raster ticked on the map is proposed for cutting, one
  unticked starts as "ignore". The PNG of a class layer is painted with that
  layer's own style and sampler.json lists the classes that style names,
  where both used to take the campaign legend, which says nothing about that
  layer. The STAC items and the sampler name a campaign only when one is
  open; the catalogue is named after the folder.
- **Cutouts no longer leaves the image out.** An image whose coordinate system
  is the same on the ground as the other layers' but written differently was
  dropped from every cutout, in whichever order the layers stood: an
  orthomosaic in WGS 84 with a TOWGS84 of zeros next to a classes map in
  EPSG:4326. Systems are now compared on the ground, and every file, footprint
  and catalogue entry is written in the registered system (EPSG:4326 by its
  code), not in the image's unnamed form. A layer whose system really is
  another is reprojected onto the grid (see below); one with no system at all,
  beside one that has one, is left out, and the panel says so next to that
  layer and the "written" message names it with the reason, instead of a
  warning the next message covered.
- **A click in Cutouts cuts the pixels the side box says.** The square of the
  side, measured on the ground, was snapped outwards to whole pixels, and
  since it almost never falls on pixel edges it came out one pixel larger: 201
  by 201 for the 200 shown, 4 by 4 (forty metres) for a side of 30 m on 10 m
  pixels, and `shapes.json` then held that size for every later cutout of the
  side. A click is now round(side / pixel) pixels a side, centred on the
  click; a folder whose `shapes.json` already holds the old size keeps it.
- **Cutouts resamples by what a layer is.** Every layer off the grid was read
  by nearest neighbour: an image onto larger pixels came out as stripes that
  are not on the ground, a surface onto smaller ones as steps, and a map of
  25 cm onto 10 m pixels gave each one the class of a patch at its centre
  instead of the class around it. Classes are now read by mode onto a larger
  pixel and by nearest onto a smaller one, so no code is invented; images are
  averaged onto a larger pixel and interpolated (bilinear) onto a smaller one;
  each band keeps its own nodata, not the first band's.
- **A layer in another coordinate system is reprojected, not left out.** A
  map of classes and an image in two systems could not be cut together at
  all. Such a layer is now reprojected onto the grid of the layer that sets it,
  also with "one common pixel grid" off, and cutouts.csv marks it resampled.
- **The padding past the edge of an image is not black ground.** Where a
  cutout runs past an image with no nodata, the GeoTIFF held 0, 0, 0 there,
  the same as a black roof, with nothing to tell them apart; a resampled image
  was padded with zeros too. The GeoTIFF now has a mask of its own (GDAL's
  internal mask), 0 over the padding and 255 over the image, which QGIS reads
  as transparency, and the values are not touched.
- **A picture with no georeference can be cut.** Cutouts read the grid GDAL
  answers for a PNG or a JPEG with no world file and no `.aux.xml`, rows going
  up, while QGIS draws it at y = -row: a dragged rectangle was "outside the
  first layer" and a click was cut beside the square clicked, or not at all.
  It reads the grid QGIS draws, the same `pixel_grid` as Correct and Whole,
  and its cutouts open over the picture.
- **A layer on a rotated grid does not set the grid of Cutouts.** Its window
  was snapped as if its grid were north up, so a cutout held other pixels
  than the ones under the rectangle, and some clicks on it were refused as
  outside it. A cutout on such a grid is now refused, with how to warp the
  layer north-up, or to let another layer set the grid in Layers.
- **A layer stored bottom row first can set the grid of Cutouts.** Every click
  on it was "the rectangle falls outside the first layer". Its grid is read
  from the top row down, and its cutouts come out top row first.
- **A click on a layer with no coordinate system is cut.** The ruler took the
  units of a picture, or of a world file with no .prj, for degrees, and a click
  stopped with "cannot convert float NaN to integer"; `cutouts.csv` wrote the
  side of a dragged rectangle as nan. The side is now in the units of such a
  layer, one to a metre, as the side box counts it.
- **A map of classes stored with a lossy codec says so.** A JPEG, a lossy
  WebP or JPEG 2000, or a GeoTIFF compressed that way moves the codes along
  every edge, and the cutouts copied the noise as classes without a word. The
  message bar now says it once a session for each such map; what GDAL reports
  of the compression decides, by the same `lossy_codec` that Correct asks, so
  a lossless JPEG 2000 is not called lossy.
- **The STAC item gives the data type of every file.** Each data asset carries
  `raster:bands` with the type of each band (a map of classes is cut in bytes
  or wider depending on the map), under the raster extension.
- **Cutouts lists the layers in the order of the Layers panel**, top first, not
  by name. "Layers to cut" shows which layer sets the pixel grid and the
  coordinate system, and lets you choose it, and no longer has a band of empty
  space above the column titles.
- **Cutouts writes the image as it is.** A GeoTIFF of an image keeps every band,
  in its own data type, with its nodata and band names, and red, green and blue
  on the first three; before, it was always three bands stretched to bytes. The
  PNG of an image is a picture of it as QGIS shows it, with the bands and
  stretch of its style, transparent where there is no data. A classes layer
  written as PNG keeps its codes in the PNG and, with "also write PNG copies"
  on, also gets a coloured copy, `_classes_colour.png`.
- **Cutouts keeps its catalogue and its Undo true to what is on disk.** The STAC
  catalogue lists the roles that were actually written, and leaves out of
  `catalog.json` any item whose files are no longer on disk; the item's json is
  kept. Undo also removes the cutout's footprint from `cutouts.gpkg` and
  updates `sampler.json`, and clicking from the folder box to the map no longer
  makes Undo forget the session. Cutouts deleted by hand are counted out and
  named on the panel and in the log; their rows, footprints and STAC items are
  kept, and their names are never reused, so no STAC item is written over.
- **Cutouts writes a log**, `rasterlabel.log` in the `RasterLabel` folder of
  the home, not in the cutouts folder (a dataset), when no annotation campaign
  is open. Before, it logged nowhere.
- **Freehand rectangles in Cutouts work without an annotation campaign**;
  before, every drag failed.
- **`shapes.json` gives pixels measured in degrees keys of their own.** Before,
  every resolution between about 5e-7 and 1.5e-6 degrees shared one size.
  Folders with metre pixels keep their keys.
- **On Windows, a cutout in a folder whose paths run past 260 characters is
  written** instead of being abandoned with its files left behind.
- **The cutouts count the pixels of a side in metres on any layer.** On a
  layer in degrees the side of a cutout was divided by the pixel size in
  degrees, and the count shown beside it ran into the tens of millions.
- **Cutouts cuts a folder from the same layers every time.** Which layers were
  cut, as what, with which names and on whose grid was chosen afresh at every
  session from the Layers panel, so the same folder was fed by different layers
  on different days and its pieces did not stack. The folder now keeps it in
  `layers.json` beside `cutouts.csv` (in the folder, not in the settings of the
  machine), written with the first cutout of a choice. The layers are known by
  the path of their file: where the files are at other paths, on another
  machine or drive or after a move, no layer of the record is found and it is
  left aside. Choosing the folder gives its layers back, the first of them the
  grid, whatever is ticked or in whatever order the Layers panel has them; a
  layer the folder does not list stays out until Layers puts it in. A change
  is said on the message bar before the cut it concerns, once.
- **A cutout that was being written when QGIS died is cleaned up.** Its files
  were in the folder and in no book. A note, `cutting.pending`, is written
  before the first file and removed when `cutouts.csv` has the rows; the next
  time the folder is opened the files of a cutout the manifest does not list
  are taken away and its name is free again; when the manifest cannot be read
  nothing is taken away, only the note. A refused cutout also takes the
  `.aux.xml` of its files away now.
- **`sampler.json`, `shapes.json` and the STAC items are written whole or not
  at all**: under a temporary name, flushed to the disk, then renamed. A crash
  or a full disk left a truncated file.
- **`sampler.json` counts cutouts, not files.** A cutout of two layers has two
  rows in `cutouts.csv` and was counted twice in `shapes_found`.
- **The STAC items of Cutouts say what the specification asks.** `proj:wkt2`
  holds WKT2 (it held the WKT1 QGIS hands out, for a system with no EPSG
  code), and is left out when it cannot be made; the footprint runs
  counter-clockwise, as GeoJSON wants of an exterior ring (the item beside a
  Whole mask too); the classes are `labels` as well as `data`; a layer on a
  grid of its own carries its own `proj:shape`, `proj:transform` and
  `proj:bbox`; and `datetime` is when a layer says the image was taken (the
  TIFF date tag, an acquisition time), not when it was cut. With no such date
  it is null, with a start and an end that are the moment of the cutting and
  an item that says so, and `created` is the cutting.

### Saving, recovery and folders that move

- **Strokes QGIS throws away on closing keep their recovery file.** Closing
  QGIS with strokes not yet saved, QGIS first asks whether to save the edits of
  each table, then closes the project, and only then unloads the plugin. A
  Discard, or a project closed with the edits in it, had emptied the buffers
  by the time the panel looked, so the recovery file, the one copy of that
  work left, was deleted as having nothing in it, and the log said "Nothing
  was saved or lost, and the campaign is still open". Now a buffer emptied
  without a save, by a rollback or by its layer leaving the project, has its
  recovery file kept, and the next Open campaign offers the work back, saying
  how it was let go of; Not now keeps the file for the next time. Closing a
  campaign without saving, when asked, still lets the work go. Taking the panel down with the
  plugin no longer says that nothing was saved or lost. New suite:
  test_work_let_go.
- **"Not now" on the recovery question meant never.** It renamed the file to
  `.restored`, which is never offered again, and Check went on saying
  everything was on disk. Not now now leaves the file to be asked about at the
  next open; a third button, Discard, retires it, renamed `.discarded` and
  still never deleted; and Check lists every recovery file set aside.
- **Three crashes in the middle of a save, and what Put them back made of
  them.** An autosave ran before the stroke that started it was written into
  the recovery file, and a crash inside it lost a polygon that had been saved;
  the file is now written first. A crash between the commit of one table and
  the next left the first table's work in the file too, and putting it back
  drew it twice; the file is now brought up to date after every table. And a
  crash after the removals of a commit and before its additions made Put them
  back delete again what was gone, which left the table refusing every save;
  a removal or a change of a feature that is no longer there is now skipped.
  `test_recovery_qgis` kills a real QGIS at each of those moments.
- **A campaign folder copied or moved, then opened from a saved QGIS
  project, wrote into the wrong place.** The project brings back its layers,
  and they were reused by the campaign's id alone: on a copy every stroke went
  into the original GeoPackage, on a moved folder into nothing, with a save
  saying "0 layers written". A layer is now the campaign's only while it is
  valid and reads the campaign's own file; any other is taken out of the
  project, said in the log, and the right one loaded. The same for the
  working copy of a correction, and Check says so if one is left.
  `test_moved_campaign_qgis` does both with a real project.
- **The README promised that a second QGIS writing the same GeoPackage would
  be refused.** It is not; the README now says a campaign must be open in one
  QGIS at a time.
- **Unloading or upgrading the plugin with a campaign open no longer leaves its
  layers in edit mode.** Work still waiting is saved and the edit sessions are
  closed. The layers stay in the project, and a table that cannot be saved is
  left as it was, with its work, for QGIS to ask about.
- **The folders proposed for a campaign and for Cutouts are spelled one way.**
  QGIS gives the folder of a project with slashes, and joined to a backslash
  it made a path with both.
- **A manifest carries no name of whoever made it.** `campaign.json` and
  `correction.json` write the map they were made from (the reference raster,
  the source of a correction) and the files in their own folder by their way
  from the folder, and read the whole paths that older ones hold. The working
  copy, the record of a moved correction and the campaign a correction came
  from are written the same way. A file on another drive keeps its whole path.
  The Check and error reports, the summaries of the Measure reports and the log
  write the home folder as `~`, and the dataset card names a file outside its
  folder by its name.
- **The log of Cutouts is not in the cutouts folder.** With no campaign open
  it went into the cutouts folder, which is a dataset and is zipped and
  published; it goes into the `RasterLabel` folder of the home now.
- **Setting a campaign aside moves its `-wal` and `-shm` with it.** Left
  behind, they sat beside whatever was written under the old name next, SQLite
  replayed the old pages into it, and the copy that was set aside lost the
  polygons the `-wal` still held.
- **The safety net works in a deep folder.** In a campaign folder of 227 to 235
  characters on Windows the folder itself was below the length at which paths
  get the long-path prefix, and the paths the net built from it ran past the
  260 that Windows refuses without it: the net could not make its folder, write
  its file, find it again at the next open or keep it after a restore, and
  said so in one line of the log.

- **The files that are shared no longer carry your home folder or your user
  name.** `campaign.json` wrote the whole path of the sampling-design file, and
  the `layers.json` of a Cutouts folder wrote the whole path of the grid and of
  every layer; both now write them from the folder, or from `~` when they are
  elsewhere in your home folder, and read them back (a file written before
  opens as it did, and `layers.json` is written again at the next cut).
- **A path in a manifest is no longer written as a way that climbs out of your
  home folder and goes down through another one** (a string of `..` and then
  your own user name): it is written from `~`, or kept whole when the file is
  outside your home.
- **A layer that is a web service or a database is written without its user
  name, password or token** into `campaign.json`, `correction.json` and
  `layers.json`, and into the reports and the bug reports. `authcfg` is kept.
  The dataset card finds a reference raster that the manifest writes from `~`.
- **The recovery file after a frame is deleted, moved or renamed.** A frame
  deleted, moved (with its contents or without), placed, noted or imported, and
  a class renamed across what is drawn, each commit a whole table with the
  strokes still pending in it, and the recovery file went on listing them until
  the next stroke. A crash in that window made the next Open campaign offer
  them, and Put them back drew them a second time and put polygons inside a
  frame that no longer existed. The file is now brought up to date right after
  each of these, table by table, and it hears every commit of a campaign table,
  QGIS's own Save Layer Edits included.
- **Objects saves like Annotate.** Save says "saved, 1 layer written" or "not
  everything could be saved" with the reason, and Objects has the autosave
  setting, counted in changes to the boxes. An autosave no longer drops the box
  that was picked up: the save gives unsaved boxes new ids, so the selection is
  found again by its shape.
- **A failed overwrite in New campaign leaves the old campaign whole.** The
  package is moved first, anything moved before a failure is moved back, and
  the message says what happened.

### Check

- **Check stopped with "too many values to unpack" on every campaign with a
  frame in it.** Introduced by the fix just below, which added the operator to
  the key the overlap check groups polygons by: `_closed_flags` read the same key
  as two values. Every test of Check read its source text or ran it with no
  campaign open, so the half that looks at a campaign had never been executed by
  any of them. `tests/test_check_runs.py` now runs the whole report on a campaign
  shaped like the one that found it, with the geometry done by GEOS, and fails
  with the same traceback if the bug is put back.
- **Check called a raster with no coordinate system a problem.** The README
  promises in its second paragraph that a photograph with no coordinate system
  is a perfectly good thing to annotate, and the New dialog takes one on
  purpose. The report then marked the campaign it produced as damaged. It is a
  note now, and it says what is really lost: only the metres.
- **Check reported ordinary brush outlines as "not on the pixel grid".** They
  never were on it: a brush outline follows the hand, vertex by vertex, and only
  the frames, the strip a line claims and the footprint of a point are placed on
  the grid exactly. The check now measures the frames, where being off the grid
  is a real defect that offsets every cutout taken from them, and the README no
  longer claims more than the program does. The mask burned at export is
  rasterized on the campaign grid and still lines up with the image pixel for
  pixel.
- **Check counted two readings as an overlap.** The overlap test grouped the
  polygons by frame and pass and not by operator, so on a campaign read by two
  people every pair of their polygons was reported in red as sharing ground,
  with the advice to press Repair underneath it. Two operators are meant to
  cover the same frame twice: that is what makes the readings comparable. The
  operator is now part of the grouping, and the report says so.
- **Check and Repair disagreed about what an overlap is.** Check counted any
  shared area above zero; a border GEOS computes twice, once for each side,
  leaves about 1e-16 m2 between two polygons that meet exactly, which a vertex
  move followed by the trim does about one time in five. Check said "1 pair
  share ground", Repair rightly ignored it and said "0 overlaps resolved".
  Repair in turn only acted above four pixels, so a real overlap of two pixels
  was a problem in one window and nothing in the other. Both now use the same
  tolerance, a hundredth of a pixel.
- **Check on a campaign without frames** printed "not everything was looked at"
  with no reason after it; and **on a large campaign** it measured frames whose
  polygons it had not read at 0% and called a closed one a problem, said "every
  frame sits on the pixel grid" after measuring the first four hundred, and
  counted readings rather than frames against that ceiling. Each now says what
  it actually looked at.
- **The Check report lists each version once and recognises Windows 11.**
  Python, numpy and the operating system were listed twice, and Windows 11 was
  called Windows 10. The same fix applies to the error report.

### QGIS 4

- **QGIS 4 is supported, with the same code as QGIS 3.** QGIS 4 is built on
  Qt 6, and PyQt6 knows an enumeration member only by its full name: with
  `Qt.Key_Left` the panel did not even open on QGIS 4. Every Qt name is now
  written in its full form (`Qt.Key.Key_Left`, `QMessageBox.StandardButton.Yes`,
  `Qt.Orientation(0)` for the flags class PyQt6 removed), which PyQt5 reads the
  same way, so nothing branches on the Qt version. QAction is taken from QtGui,
  where Qt 6 keeps it and QGIS 3 offers it too, and two QGIS spellings the
  plugin site's Qt 6 check flags (the render unit for map units, the size
  property of a symbol layer) are looked up new name first. `metadata.txt` says
  `qgisMaximumVersion=4.99` and `supportsQt6=True`. The suites run on PyQt5 and
  on PyQt6 (`tests/qtbinding.py` picks one, `tests/run.py --qt 6` asks for it),
  a static check refuses any short Qt spelling, any import of PyQt5 or PyQt6 by
  name and any `exec_()`, and the build server runs every suite a second time
  inside the official QGIS 4 image. A message level is always the
  `Qgis.MessageLevel` enum, never a bare number, which PyQt6 refuses: on QGIS 4
  placing a frame, saving and opening Correct raised a TypeError, and a new
  suite hands each level to a real QGIS message bar. Run headless in a real
  QGIS 3.36, 3.44 and 4.2. An upload to plugins.qgis.org warns that
  `supportsQt6` is deprecated; it is kept for the Qt 6 build of QGIS 3, which
  still reads it.
- **The supported versions are written out.** `metadata.txt` names its
  ceiling, `qgisMaximumVersion=4.99`, instead of leaving it to a default, and
  the README says QGIS 3.36 to 4.x in plain words instead of "3.36 and newer".

### The build, the suites and the repository

- **RasterLabel no longer prints its log to the console inside QGIS.** The QGIS
  message log and the log file beside the campaign still record every line. Set
  `RASTERLABEL_DEBUG` to have the lines printed as well. A console that cannot
  display a message can no longer cause a second error while a failure is being
  reported.
- **The build fingerprint uses SHA-256 instead of MD5**, so security scanners no
  longer report it as a weak hash. The eight-letter build code shown in reports
  changes once as a result.
- **The licence says GPL version 2 or any later version, with a copyright
  line**, in the README and at the top of the package.
- **The suites keep out of your own folders.** A suite that opens Cutouts
  without choosing a folder of its own wrote into the log of the default
  cutouts folder, `~/RasterLabel/cutouts`, whenever that folder was there,
  on the machine of whoever ran them. `tests/run.py` now gives the suites a
  home folder of their own, removed at the end.
- **A suite run by hand gets a home of its own too.** `tests/run.py` gives
  its suites a scratch home folder, so that Cutouts does not write into the
  log of whoever runs them; a suite started by hand still used the real one.
  Every suite now imports `scratch_home` first, and a static check holds them
  to it. Git is pointed at the real global settings from that home, so the
  suite that packages a commit is not refused on a build server whose
  checkout belongs to another user.
- **Two suites still read the prototype.** `test_operators.py` and
  `test_scaling.py` opened `qgis_CASUALI_v2/v3.py` from a path that exists on no
  machine and extracted names the package renamed long ago, so one failed
  everywhere and the other was hidden only by the GDAL skip and would have gone
  red on CI. Both now test the shipped file; the renderer expression is lifted
  from `apply_filter()` itself rather than retyped, and the port of the scaling
  suite is what found the handle bug above. `tests/harness_flow.py` and
  `tests/harness2_flow.py`, forks of the harnesses from the same days that
  nothing ran any more, are gone.
- **The suites run on Windows.** `tests/run.py` looked for a GDAL Python with the
  `which` command, which Windows lacks and Git Bash answers with paths Windows
  cannot start; and the offscreen platform found no fonts at all, so every word
  was measured at a made-up width and the layout suites reported overlaps no
  screen shows. It now uses `shutil.which` and points Qt at the system fonts,
  and runs its suites in UTF-8 mode, so a cp1252 console needs nothing set.
- **The build server really runs the six GDAL suites.** They used to be skipped
  there without anyone noticing, so CI went green without ever having read or
  written a real raster. The workflow now installs Python, GDAL, PyQt5, numpy,
  shapely and pyflakes from the system packages, and `tests/run.py
  --require-gdal` (or `RL_REQUIRE_GDAL=1`) counts a missing GDAL as a failure
  instead of a skip. The actions have moved to their Node 24 releases.
- **Line endings are LF everywhere.** A new `.gitattributes` keeps every text
  file LF in the repository and in every checkout, so a zip built on Windows is
  the same byte for byte as the one CI builds. The suites no longer write to
  fixed `/tmp` folders, which on Windows ended up at the root of the drive. A
  static check now walks `rasterlabel/`, `tests/`, `tools/`, `.github/` and the
  three `.md` files at the top, and fails on a personal folder (a user folder
  on Windows or macOS, a home folder on Linux) or an absolute temporary path
  anywhere in them.
- **The release zip says when it is not the commit.** `tools/package_plugin.py`
  zips the folder as it stands; it now compares what goes in with the last
  commit and lists every file that is untracked, ignored, edited or deleted.
  `--release` refuses to build at all unless the zip will be exactly the
  commit.
- **`metadata.txt` names the repository**,
  <https://github.com/massigit12345/Rasterlabel>, as its tracker, repository
  and homepage. The
  placeholder exemption is out of the CI run, so a build that brings one back
  fails.
- **The CI run would have been red on its first push.** It built the plugin zip
  after the suites, and one suite installs that zip the way QGIS does; on a fresh
  clone, where `dist/*.zip` is never committed, it found nothing to open. The zip
  is now built first. Found by running the workflow's own steps on a clone of the
  repository before anything was pushed.
- `tests/test_hand_edits_run.py` runs settle_edits, give_back, save, Repair and
  move_tile themselves, on an edit buffer that renumbers on commit as QGIS does
  and with GEOS doing the arithmetic, instead of a model of the rule or a
  reading of the source.
- `tests/test_cross_qgis.py`, run where two or more QGIS are installed, saves
  a project with a campaign and a correction open in each of QGIS 3.36, 3.44
  and 4.2 and opens it in every other: layers valid and recognised, nothing
  lost, a new stroke, an export, a correction stroke and Check, all clean.
- **The release zip is the same bytes every time.** Every entry has the same
  date and permissions and the entries are sorted by name, so the zip of a tag
  can be checked by building it again (with the same Python and zlib).
  `tools/package_plugin.py --out` writes it elsewhere, which the suites use.
- **The workflow reads only the repository.** Its token can do no more,
  whatever the settings of the repository or the organisation say; a run stops
  after 45 minutes instead of holding the runner for six hours; and the actions
  are named by the commit of the release they were checked at, because a tag
  can be moved and a commit cannot.
- **An example dataset and a tutorial.** A synthetic scene, the map of an
  imaginary classifier with its probability, a sampling design and the legend,
  made again from a fixed seed by `tools/make_example.py`
  (`examples/rasterlabel_example/`); `docs/tutorial.md` walks the program on it,
  step by step, with the labels of the program and what each step writes;
  `tools/tutorial_walk.py` does the same walk with no window and draws the
  pictures, and `test_tutorial_walk.py` runs it so the page cannot rot, while
  `test_tutorial_text.py` checks that every label in bold on the page is a
  label of the package.
- **`CITATION.cff` and `.zenodo.json`,** checked by a suite against the
  version, the licence and the repository of `metadata.txt`. There is no DOI
  yet and the files do not pretend there is one.

- **plugins.qgis.org: nothing a scanner reads as a hard-coded password.** The
  plugins site runs Bandit on every upload and lists B105, B106 and B107 (a
  literal that looks like a password) as critical. Three places where a
  reading's pass was written beside a literal (`pass_default` in the card
  rules, now `default_reading_number`; `pass_no` of a row made from an old
  operations.csv; `pass` of the reading held) were read as passwords, as was a
  constant that named the patterns that take passwords out of a source; they
  are renamed or hold their value in a name. The SHA-1 that shortens a long
  layer name or a report name says `usedforsecurity=False`, a mark in a file
  name and no security, so Bandit has nothing of high severity left. What it
  still lists are rules of the warning class (an `except` that passes, SQL
  built from a table name, the standard XML parser). A test looks for the same
  shapes in every file of the package and runs Bandit when it is installed.
- **`metadata.txt`: the comment on `supportsQt6` says what the plugins site
  says,** that the flag is no longer recognised and has no effect; the line
  stays, as a statement that the code runs on Qt 6.
- **The tutorial can be followed as written.** Step 4 takes the Tiles tool
  before it sets the tile side, step 9 names the files with a reading chosen,
  step 10 says which boxes to untick and tick and lists every file, step 13 no
  longer asks to press Correct, which closes what New has opened, and the walk
  does the same steps and checks them.
- **A code of conduct and a way to ask for help.** `CODE_OF_CONDUCT.md`
  (Contributor Covenant 2.1) and a Support section in `CONTRIBUTING.md`: how
  to ask, where to report, what a pull request holds.
- **Lost line continuations are back.** A few lines of code had a run of
  blanks where a backslash and a line break had been lost, and read as one line
  of a hundred columns and more; they are written as continuations again, and
  `test_static_checks` refuses ten blanks between two tokens of a line of
  code.

## 1.0, 2026-10-04

First release.

Four modules in one panel. **Annotate** draws class areas, lines and points over a
raster, with or without frames. **Correct** mends a map an algorithm produced,
always on a copy of it. **Objects** draws boxes with a class on them, for
detection. **Cutouts** writes a dataset out, one file per selected layer, with a
`cutouts.csv` manifest and optionally a STAC 1.0.0 catalogue.

What the release is built on:

- A campaign is a folder: `campaign.json`, the manifest, and `annotation.gpkg`,
  a GeoPackage with five tables. The manifest is the truth about a campaign and
  is rewritten whole and atomically.
- A mask burned from a campaign lines up with the image pixel for pixel, with no
  resampling anywhere: it is rasterized on the campaign's own grid. The frames,
  the strip a line claims and the footprint of a point are placed on that grid
  edge by edge; a brush outline is vector and becomes pixels when the mask is
  burned. (This line read "every edge of every geometry" until it was corrected
  in 1.1: the frames were on the grid, the brush outlines never were.)
- A new mark is clipped to its frame and subtracted from what is under it. Two
  labels cannot share ground, and once a background has been laid down there are
  no holes either: the partition is closed by construction, not by checking
  afterwards.
- `pass_no` and `operator` are columns, not conventions. A second, blind pass
  over the same ground is how agreement between two readings is measured, and
  coverage is counted pass by pass so a frame read twice cannot reach two
  hundred per cent.
- A class code never changes. Retiring a class keeps its number, and its name:
  neither is handed to another class, because the map is painted by name and the
  masks are burned from the code.

What is here because a first release will fail in ways nobody has imagined:

- **A recovery snapshot after every stroke**, written as plain JSON Lines beside
  the campaign. Autosave decides how often work reaches the GeoPackage; the
  snapshot is written after every single stroke, because what it exists for is
  the crash between two autosaves. At the next open the work is offered back.
- **A log file beside the campaign**, rolled over at a megabyte. The QGIS log
  panel is where a failure belongs while somebody is looking at it; a file is
  where it is three days later when the report arrives.
- **Check**, one button that says which QGIS, Qt, GDAL and numpy are running,
  which formats this GDAL actually has, and whether the campaign still agrees
  with itself: class codes the legend does not know, geometry off the pixel grid,
  polygons of one reading sharing ground, frames whose `closed` column disagrees
  with what is painted in them. It changes nothing, and the report copies in one
  press.
- **The error window**, with twenty rules that turn a common failure into
  advice: a package held open by an edit session or by a sync client, permission
  refused, a full disk, a file that has moved, a raster too big for memory, a
  format this GDAL cannot write, a QGIS older than the one this was built on. The
  rules read the error *number* before the text, so an Italian Windows saying
  *Accesso negato* gets the same advice as an English one.
- **A build fingerprint**, eight letters from the bytes actually running, in the
  panel and in every report. "1.0" is true of every build ever called 1.0.

### Shape of the repository

The program was one file of twelve thousand lines. It is now a package of
twenty-four modules, and `tools/bundle.py` folds the package back into the single
file that gets pasted into the QGIS Python Console. The single file is built, not
written: the import order is a promise that no module needs a name from a later
one, and the builder refuses to build at all if two modules define the same
top-level name, because one flat namespace cannot hold two of anything.

Thirty-two test suites run against what is shipped rather than against what is
written: real GDAL and real GeoPackages for the geometry and the exports, a real
Qt panel built and clicked for the interface, a sweep over fifteen widths that
checks nothing is drawn on top of anything else, a static pass that refuses any
name used and never defined, and one suite whose only job is to hold the ground
already won, with a check for every defect ever fixed.

### Fixed before the release

Twenty defects found by a search through the whole program, each one verified
against the source before it was touched:

- The Whole raster export read a recipe key nobody wrote and died with the
  default settings.
- A new class could be given the name of a retired one, after which the same
  stroke came out with two different class codes.
- The Classes dialog dropped a row with an empty or repeated name in silence, and
  the caller then retired that class: everything drawn in it vanished from the
  map.
- Closing a campaign asked only the module, and Correct and Cutouts answer that
  nothing is pending by construction; and answering Yes did not check that the
  save had worked before dropping the layers.
- `rollBack()` after a failed commit threw away the whole buffer, in three
  places. A failed commit leaves the buffer as it was; Save tries again.
- Deleting a frame deleted its contents first, checked neither commit, and logged
  success either way.
- `Repair` and `paint under the others` took a raw `difference()`, so a GEOS
  failure read as "nothing left", which meant delete.
- Coverage was the sum of the pieces rather than the area of their union, so two
  overlapping polygons pushed a frame past a hundred per cent and had it written
  down as closed with holes still in it.
- `Ctrl+click` reclassification and hand vertex editing never advanced the
  autosave counter: one had `self.ticked()` sitting after a `return`.
- Undo touched only the polygons, leaving a line's trace behind and doing nothing
  at all for a point.
- A campaign manifest with no grid crashed the open; the vector export refused to
  replace a file it had written itself; a half-written GeoTIFF was still open when
  it was removed, so on Windows it stayed on disk.
