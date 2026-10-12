"""rasterlabel.ui_card

Measure ▸ Dataset card…, in the campaign's block and in the correction's.

No window to set it up: there is nothing to choose. What happens, in order:

- the work is saved first, and the card is refused while something could
  not be: the package is what is counted, and a card that quietly missed
  the last ten minutes would look right and be wrong;
- for a campaign, the blind gate: a card holds every reading's counts, so
  a reader the Annotate filter keeps from another reading's work is not
  shown them here either (measure.measure_blind_gate);
- the counting, with the wait cursor, its progress in the status bar
  ("RasterLabel: dataset card, ANNA, pass 1 (2 of 5), 40%");
- the card in a folder of its own, reports/card/<stamp>/, written under a
  name ending in .tmp and renamed when complete: <stem>_card.md for people,
  <stem>_card.json for programs;
- one information box that says where, what the card holds, and which of
  the reports it copies are older than the last change.

Nothing in the campaign or the correction is changed: the package is read
only, and the manifest is neither written nor told of the card. The card
is a description of the files at one moment, with their SHA-256; the
Export and the Whole raster write one beside the files they make.
"""
import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication, QMessageBox

from .constants import LEVEL_INFO, NAME
from .compat import iface
from .errors import log
from .reports import report_abandon, report_finish, report_folder
from .campaign import readings_in, reading_label
from .card import (card_gather_campaign, card_gather_correction,
                   card_names, card_stale_lines, card_summary, card_write)

CARD_KIND = "card"


def card_say(text, bar=False):
    """A line in the status bar of QGIS, or in its message bar; QGIS kept
    answering in between. Never raises: a card is not stopped because the
    window that shows its progress is not there."""
    try:
        if bar:
            iface.messageBar().pushMessage(NAME, text, level=LEVEL_INFO,
                                           duration=3)
        else:
            iface.mainWindow().statusBar().showMessage(
                "%s: %s" % (NAME, text), 4000)
    except Exception:
        pass
    try:
        QApplication.processEvents()
    except Exception:
        pass


def card_progress(text, done, total):
    """What card_gather_* is told as it goes, put in the status bar."""
    share = int(100.0 * float(done) / max(float(total), 1.0))
    card_say("dataset card, %s, %d%%" % (text, min(max(share, 0), 100)))


def card_saved(panel):
    """Save what the modules hold; True when everything is on disk."""
    for m in (getattr(panel, "section", None),
              getattr(panel, "annotation", None)):
        if m is None:
            continue
        for hook in getattr(m, "stroke_hooks", None) or []:
            flush = getattr(hook, "flush", None)
            if callable(flush):
                try:
                    flush(m)
                except Exception as err:
                    log("a measure could not write what it holds: %s" % err)
        try:
            if m.unsaved():
                m.save()
        except Exception as err:
            log("could not save before writing the card: %s" % err)
    try:
        if panel.pending_layers():
            panel.flush_layers()
    except Exception as err:
        log("could not write the layers before writing the card: %s" % err)
    still = []
    for m in (getattr(panel, "section", None),
              getattr(panel, "annotation", None)):
        try:
            if m is not None and m.unsaved():
                still.append(m)
        except Exception:
            pass
    try:
        pending = panel.pending_layers()
    except Exception:
        pending = []
    return not still and not pending


CARD_NOT_SAVED = ("There is work that could not be written to the package.\n\n"
                  "A card written now would count the file as it stands on "
                  "disk, without it. Save by hand first, and look at the log "
                  "for why it refused.")


def card_package(campaign):
    return getattr(campaign, "package_path", None) or os.path.join(
        campaign.folder, "annotation.gpkg")


#  Measure ▸ Dataset card…
# =====================================================================
def card_enabled_campaign(panel):
    """(True, "") with a campaign open whose package is there."""
    campaign = getattr(panel, "campaign", None)
    if campaign is None:
        return False, "Open a campaign first."
    if not os.path.isfile(card_package(campaign)):
        return False, ("The campaign has no package to describe: %s is not "
                       "in its folder." % os.path.basename(
                           card_package(campaign)))
    return True, ""


def card_enabled_correction(panel):
    """(True, "") with a correction open whose working copy is there."""
    book = getattr(panel, "correction", None)
    if book is None:
        return False, "Open a correction first."
    copy = getattr(book, "working_path", "") or ""
    if not copy or not os.path.isfile(copy):
        return False, ("The working copy of this correction is not there%s. "
                       "Put it back beside correction.json, then write the "
                       "card." % (": " + os.path.basename(copy) if copy
                                  else ""))
    return True, ""


def card_start_campaign(panel):
    """Measure ▸ Dataset card…, from ANNOTATION CAMPAIGN."""
    campaign = getattr(panel, "campaign", None)
    if campaign is None:
        return None
    on, why = card_enabled_campaign(panel)
    if not on:
        QMessageBox.information(panel, NAME, why)
        return None
    if not card_saved(panel):
        QMessageBox.warning(panel, NAME, CARD_NOT_SAVED)
        return None
    package = card_package(campaign)
    readings = sorted(readings_in(package), key=lambda r: (r[1], r[0]))
    gate = getattr(panel, "blind_gate", None)
    if callable(gate):
        hidden = [r for r in readings if gate([r])]
        if hidden:
            QMessageBox.warning(panel, NAME, gate(hidden, "card",
                                                  "write the card"))
            log("card refused: %s hidden from the reader"
                % ", ".join(reading_label(r) for r in hidden))
            return None
    data = campaign.data
    return card_run(panel, campaign.folder, campaign.stem,
                    lambda: card_gather_campaign(
                        data, campaign.folder, package,
                        progress=card_progress))


def card_start_correction(panel):
    """Measure ▸ Dataset card…, from CORRECTION."""
    book = getattr(panel, "correction", None)
    if book is None:
        return None
    on, why = card_enabled_correction(panel)
    if not on:
        QMessageBox.information(panel, NAME, why)
        return None
    if not card_saved(panel):
        QMessageBox.warning(panel, NAME, CARD_NOT_SAVED.replace(
            "the package", "the correction"))
        return None
    data = book.data
    return card_run(panel, book.folder, book.stem,
                    lambda: card_gather_correction(data, book.folder,
                                                   progress=card_progress))


def card_run(panel, owner_folder, stem, gather):
    """Count, write into reports/card/<stamp>/, and say so. Returns
    {"folder", "files", "card"}, or None when it failed."""
    tmp = None
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    said = None
    try:
        card_say("writing the dataset card…", bar=True)
        card = gather()
        tmp, final = report_folder(owner_folder, CARD_KIND)
        files = card_write(card, tmp, stem)
        done = report_finish(tmp, final)
        tmp = None
    except Exception as err:
        log("the dataset card could not be written: %s" % err)
        said = "The dataset card could not be written:\n\n%s" % err
        return None
    finally:
        if tmp is not None:
            report_abandon(tmp)
        QApplication.restoreOverrideCursor()
        card_say("")
        if said is not None:
            QMessageBox.critical(panel, NAME, said)
    md = card_names(stem)[0]
    files = [os.path.join(done, os.path.basename(f)) for f in files]
    text = ("Dataset card written in %s: %s and .json. %s"
            % (done, md, card_summary(card)))
    stale = card_stale_lines(card)
    if stale:
        text += "\n\n" + "\n".join(stale)
    log("dataset card written: %s" % ", ".join(files))
    QMessageBox.information(panel, NAME, text)
    return {"folder": done, "files": files, "card": card}
