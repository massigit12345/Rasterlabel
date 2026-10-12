---
name: Something went wrong
about: A failure, a crash, or work that was lost
labels: bug
---

## The report from Check

Press **Check** under ANNOTATION CAMPAIGN (or under CORRECTION, if it happened
in Correct), then **Copy report**, and paste it here. It says which build is
running, its build fingerprint, and what it is running on: QGIS, Qt, GDAL,
Python and the system, which is the first thing anybody will ask. Say too
whether it is the plugin installed from the zip or the two lines pasted into
the Python Console.

```
paste it here
```

If the error window appeared, press its **Copy report** too and paste that below:
it has the traceback.

```
paste it here if there was one
```

## What you were doing

The steps, in order, as plainly as you can. "I had a frame selected, I pressed
Fill Gap, and nothing happened" is a better report than a paragraph about what you
think the cause was.

1.
2.
3.

## What you expected, and what happened instead

## Was any work lost

If so, look for a `recovery/` folder beside `campaign.json`. It holds plain text
snapshots of what was drawn but not saved, and the program offers them back the
next time the campaign is opened: Put them back, Not now or Discard. Say which
you chose, and whether the work came back. Nothing there is ever deleted: a file
put back ends in `.restored`, one discarded in `.discarded`. The files are useful
to attach: they are readable text and contain only your own geometry and the
operator names of the campaign. A correction has no recovery folder: every
stroke is written into its copy as it is made.

## The log

`rasterlabel.log`, beside `campaign.json`, beside `correction.json` while
Correct is open, or in the cutouts folder when Cutouts runs with no campaign.
The last twenty lines before the failure are usually the interesting part.

```
paste them here
```
