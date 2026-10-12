"""rasterlabel.ui_uncertainty

The windows of uncertainty-guided correction: the UNCERTAINTY card in
Correct, the window that says which band or raster holds the uncertainty
and how to read it, the hook that keeps the walk beside the strokes, and
Measure ▸ Uncertainty report….

What happens, in order:

- with no uncertainty chosen the card says so in one quiet line, offers the
  band whose name says what it is ('band 2 "probabilita x255" looks like the
  probability of the class', Use it), and nothing else changes: no file, no
  layer, no line in the manifest;
- Use it, or Source… and Use, reads the band once into <copy>_uncertainty.tif
  (uncertainty.unc_build), cuts the map into places, and from then on the
  card holds the walk: show it on the map, the place in hand, ◀ / Done, next
  ▶ / Skip, the share changed per decile so far and the AUC, and Report…;
- a stroke made while a place is in hand tells the journal which place it
  was (the hook leaves it in the stroke's ctx, before the journal reads it);
- the report reads what is in memory, writes reports/uncertainty/<stamp>/
  and shows its numbers. Nothing in the map changes.
"""
import math
import os
import uuid

import numpy as np
from qgis.PyQt.QtCore import QEventLoop, QSize, Qt, QTimer
from qgis.PyQt.QtGui import QColor, QPainter
from qgis.PyQt.QtWidgets import (QApplication, QButtonGroup, QComboBox,
                                 QDialog, QDialogButtonBox,
                                 QDoubleSpinBox, QFileDialog, QFrame,
                                 QGridLayout, QHBoxLayout, QLabel,
                                 QMessageBox, QProgressDialog, QSizePolicy,
                                 QSpinBox, QVBoxLayout, QWidget)
from qgis.core import (QgsCoordinateReferenceSystem, QgsProject,
                       QgsRasterLayer, QgsVectorLayer)

from .constants import (LEVEL_INFO, NAME, OVERLAY_OPACITY, PLACE_SIDE_PX,
                        PLACES_CSV, PLACES_GEOJSON, RANDOM_EVERY, U_LEVELS,
                        U_NODATA, first_attr)
from .compat import iface, run_dialog
from .naming import long_path, now
from .project import canvas, project_rasters
from .errors import log, shielded
from .layout import KeyRow
from .theme import (follows_width, keep_shape, key_least, key_need,
                    palette_colours, short_combo, short_spin, spread, titled,
                    browse)
from .widgets import WrapTick, narrow_radio, narrow_tick
from .layers import add_layer, find_mine, group_node, is_report_layer
from .campaign import operator_word
from .reports import report_entry, report_register, report_utc
from .stats import st_auc_hist, st_bin_of, st_decile_cuts
from .uncertainty import (UNC_KIND, UNC_KIND_WORDS, UNC_KINDS,
                          UNC_LABELLED_BAND, UNC_VOTES_BAND, Places,
                          UncRefused, unc_bands, unc_build, unc_class_valid,
                          unc_default_seed, unc_describe, unc_file_state,
                          unc_files, unc_grid_relation, unc_guess_kind,
                          unc_guess_scale, unc_hist, unc_net, unc_path_of,
                          unc_plane, unc_preview, unc_report, unc_sample,
                          unc_score_blocks, unc_side_for, unc_source_path,
                          unc_to_u8, unc_whole_hist)
from .dialogs import ReportWindow, report_group, report_part

UNC_MISSING = ("the uncertainty named in the manifest is not there: choose "
               "it again")
UNC_NONE = "none: the map has no uncertainty band. Correct works as before."
UNC_CHOOSE_FIRST = ("Choose the uncertainty in Correct first (UNCERTAINTY, "
                    "Source…).")
UNC_SCALE_CHOICES = [("0-1", 1.0), ("x100", 100.0), ("x255", 255.0),
                     ("x10000", 10000.0), ("x65535", 65535.0),
                     ("custom", None)]
UNC_GROW = 0.15                    # the view of a place, this much wider
UNC_SPARK_H = 18
UNC_OVERLAY_COLOURS = ((0, "#ffffff"), (127, "#f0a040"), (254, "#8b1a1a"))
UNC_TIPS = {
    "source": "Which band or raster says how unsure the model was, and how "
              "to read it.",
    "use": "Read this band as the uncertainty of the map, as it is named, "
           "with no window. Source… chooses another or another reading.",
    "overlay": "The uncertainty, darkening the classes where the model was "
               "unsure. Certain pixels are left as they are.",
    "back": "Back to the place before. Nothing is marked.",
    "next": "You looked at every pixel of this place and mended what was "
            "wrong. It is marked done and the next place opens.",
    "start": "The first place: the most uncertain one, or a random one "
             "every few places.",
    "skip": "Not reviewed. A skipped place counts in no curve.",
    "report": "Write the calibration: how often a person changed the class, "
              "by uncertainty. Changes nothing in the map.",
}


def unc_hook_of(section):
    """The uncertainty hook of a Correct, or None."""
    for hook in getattr(section, "stroke_hooks", None) or []:
        if isinstance(hook, UncertaintyHook):
            return hook
    return None


def unc_section(panel):
    """Correct on the open correction, or None."""
    book = getattr(panel, "correction", None)
    section = getattr(panel, "section", None)
    if book is None or section is None or \
            getattr(section, "book", None) is not book:
        return None
    return section


def unc_wait(on, words=None):
    """The hourglass, and a line on the message bar, around a pass over the
    whole map on the thread that draws QGIS."""
    try:
        if on:
            if words:
                iface.messageBar().pushMessage(NAME, words, level=LEVEL_INFO,
                                               duration=6)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents(
                QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        else:
            QApplication.restoreOverrideCursor()
    except Exception:
        pass


#  The hook: what Correct keeps of the walk
# =====================================================================
class UncertaintyHook(object):
    """The uncertainty of one Correct, its places, and the word a stroke
    leaves for the journal.

    Built with Correct (measure.CORRECT_HOOKS, before the journal's hook,
    so the place it leaves in a stroke's ctx is what the journal writes).
    With no uncertainty in the manifest it reads the names of the copy's
    bands for a suggestion and does nothing else. With one, it makes sure
    the file of u is there and up to date (it is made again when it is
    missing or older than its source), opens it as a band read a window at
    a time (unc_plane: a map of hundreds of millions of pixels is a few
    hundred megabytes of bytes, and Correct reads in strips too), and holds
    the places. The file is only read from then on."""

    def __init__(self, section):
        self.section = section
        self.card = None
        self.spec = None
        self.u8 = None
        self.places = None
        self.trouble = ""
        self.suggested = None
        self.view = None
        self.overlay_seen = False
        self.cuts = []
        self.h_done = (np.zeros(U_NODATA, np.int64),
                       np.zeros(U_NODATA, np.int64))
        self.load()

    # ---------------------------------------------------------- paths
    @property
    def record(self):
        return self.section.record

    @property
    def folder(self):
        return os.path.dirname(self.section.path)

    @property
    def derived(self):
        return unc_path_of(self.section.path, self.record)

    @property
    def places_path(self):
        return os.path.join(self.folder, PLACES_CSV)

    @property
    def geojson_path(self):
        return os.path.join(self.folder, PLACES_GEOJSON)

    def save_manifest(self):
        try:
            self.section.book.save()
        except Exception as err:
            log("cannot update the manifest: %s" % err)

    # ---------------------------------------------------------- loading
    def load(self):
        spec = self.record.get("uncertainty")
        if not isinstance(spec, dict) or spec.get("kind") not in UNC_KINDS:
            self.suggest()
            return
        state, why = unc_file_state(self.derived, spec, self.folder)
        src = unc_source_path(spec, self.folder)
        source_there = os.path.exists(long_path(src)) if src else True
        if state != "ok":
            if source_there:
                try:
                    self.build(spec, "the uncertainty of the map is read "
                               "again (%s): one pass over the map" % why)
                except Exception as err:
                    log("the uncertainty could not be read again: %s" % err,
                        loud=True)
                    if state == "missing":
                        self.trouble = UNC_MISSING
                        self.suggest()
                        return
            elif state == "missing":
                log("the uncertainty named in the manifest is not there: %s "
                    "and %s are both missing. Choose it again under "
                    "UNCERTAINTY, Source…" % (src or "the band",
                                               os.path.basename(
                                                   self.derived)), loud=True)
                self.trouble = UNC_MISSING
                self.suggest()
                return
            else:
                log("%s is used as it is: the raster it was read from is "
                    "not where it was (%s)" % (os.path.basename(self.derived),
                                               src))
        u8 = unc_plane(self.derived, self.section.nx, self.section.ny)
        if u8 is None:
            log("%s is not on the grid of the copy: the uncertainty is off "
                "until it is chosen again" % os.path.basename(self.derived),
                loud=True)
            self.trouble = UNC_MISSING
            self.suggest()
            return
        self.spec = spec
        self.u8 = u8
        self.load_places()

    def suggest(self):
        """The first band of the copy, past the class band, whose name says
        what it holds: (band, description, kind, scale), or None."""
        self.suggested = None
        try:
            bands = unc_bands(self.section.path)
        except Exception:
            bands = []
        names = [b["description"] for b in bands]
        for b in bands:
            if b["band"] == self.section.band_no:
                continue
            kind = unc_guess_kind(b["description"], names)
            if kind is None or kind == "votes":
                continue
            scale = unc_guess_scale(b["description"], b["type"],
                                    b.get("scale"))
            if scale is None:
                continue
            self.suggested = (b["band"], b["description"], kind, scale)
            return self.suggested
        return None

    def load_places(self, settings=None):
        """The places of the walk, from the file, or cut afresh."""
        settings = dict(self.record.get("places") or {}, **(settings or {}))
        side = unc_side_for(self.section.nx, self.section.ny,
                            int(settings.get("side_px") or PLACE_SIDE_PX))
        seed = settings.get("seed")
        if seed is None:
            seed = unc_default_seed(self.section.book.data.get("id"),
                                    self.record.get("name", ""))
        every = settings.get("random_every")
        every = RANDOM_EVERY if every is None else int(every)
        blind = bool(settings.get("blind", every > 0))
        places = None
        if os.path.exists(long_path(self.places_path)):
            try:
                places = Places(self.places_path, side, seed, every,
                                blind).load()
            except IOError as err:
                log(str(err))
                places = None
            if places is not None and places.rows and places.side != side:
                if any(r["status"] for r in places.rows):
                    side = places.side
                    log("the places keep their side of %d px: some are "
                        "already done" % side)
                else:
                    places = None
            if places is not None and not places.rows:
                places = None
        blocks = unc_score_blocks(self.u8, side)
        if places is None:
            places = Places.from_blocks(self.places_path, blocks,
                                        self.section.gt, self.section.nx,
                                        self.section.ny, seed, every, blind)
            log("%d places of %d px to review, ranked by uncertainty, one in "
                "%d drawn at random (seed %d)" % (places.N, side, every
                                                  or 0, seed))
        else:
            places.rescore(blocks)
            places.seed, places.random_every = int(seed), int(every)
            places.blind = blind
        self.places = places
        try:
            places.save()
        except OSError as err:
            log("cannot write %s: %s" % (PLACES_CSV, err), loud=True)
        self.record["places"] = {"side_px": places.side,
                                 "random_every": places.random_every,
                                 "seed": places.seed, "blind": places.blind,
                                 "file": PLACES_CSV, "eligible": places.N}
        self.save_manifest()
        self.view = places.current()
        self.overlay_seen = False
        self.refresh_hists()
        self.write_geojson()

    def build(self, spec, words=None):
        """The file of u made from a spec, with the hourglass; the counters
        it found go into the spec."""
        self.drop_overlay()
        unc_wait(True, words)
        try:
            said = unc_build(self.section.path, self.section.band_no,
                             self.section.nodata, spec, self.derived)
        finally:
            unc_wait(False)
        spec.update({"grid": said["grid"], "offset": said["offset"],
                     "derived": os.path.basename(self.derived),
                     "made": now(), "valid_px": said["valid_px"],
                     "zero_read_as_value": said["zero_read_as_value"],
                     "clipped_px": said["clipped_px"],
                     "map_px": said["map_px"]})
        spec.pop("resample_ok", None)
        log("the uncertainty of the map is in %s: %s; a value on %d of %d "
            "pixels with a class%s%s" % (
                os.path.basename(self.derived), unc_describe(spec),
                said["valid_px"], said["map_px"],
                ", %d nodata of 0 read as 0" % said["zero_read_as_value"]
                if said["zero_read_as_value"] else "",
                ", %d values clipped to 0-1" % said["clipped_px"]
                if said["clipped_px"] else ""))
        return said

    def refresh_hists(self):
        """The decile cuts of the whole map and the histograms of the done
        places, in memory: the sparkline and the AUC of the card read them
        at every Done without reading a file. One pass over the map, a
        strip at a time."""
        self.cuts = []
        self.h_done = (np.zeros(U_NODATA, np.int64),
                       np.zeros(U_NODATA, np.int64))
        if self.u8 is None:
            return
        h_all = unc_whole_hist(self.u8, self.section.marks)[0]
        self.cuts = st_decile_cuts(h_all)
        for r in self.places.rows if self.places else []:
            if r["status"] == "done":
                self.add_done(r)

    def add_done(self, row):
        win = (slice(row["row"], row["row"] + row["height"]),
               slice(row["col"], row["col"] + row["width"]))
        marks = self.section.marks
        a, c = unc_hist(self.u8[win], marks[win] if marks is not None
                        else None)
        self.h_done = (self.h_done[0] + a, self.h_done[1] + c)

    def spark(self):
        """[(share changed, n)] per decile over the done places."""
        a, c = self.h_done
        bins = st_bin_of(np.arange(U_NODATA), self.cuts)
        out = []
        for b in range(len(self.cuts) + 1):
            inside = bins == b
            n = int(a[inside].sum())
            out.append((float(c[inside].sum()) / n if n else None, n))
        return out

    def auc_done(self):
        a, c = self.h_done
        return st_auc_hist(c, a - c)

    # ---------------------------------------------------------- choosing
    def apply(self, spec, settings=None):
        """A spec chosen: the file of u made, the places cut or rescored,
        the manifest told, the card and the layers following."""
        spec = dict(spec)
        old = self.record.get("uncertainty")
        self.build(spec, "reading the uncertainty of the map: one pass over "
                   "the map")
        self.u8 = unc_plane(self.derived, self.section.nx, self.section.ny)
        if self.u8 is None:
            raise IOError("%s does not read back on the grid of the copy"
                          % os.path.basename(self.derived))
        self.spec = spec
        self.trouble = ""
        self.record["uncertainty"] = spec
        self.save_manifest()
        settings = dict(settings or {})
        if self.places is not None and self.places.side != \
                int(settings.get("side_px") or self.places.side) and \
                not any(r["status"] for r in self.places.rows):
            self.places = None
            try:
                os.remove(long_path(self.places_path))
            except OSError:
                pass
        self.load_places(settings)
        log("uncertainty %s: %s" % ("changed" if old else "chosen",
                                    unc_describe(spec)))
        self.ensure_overlay()
        self.reload_places_layer()

    def turn_off(self):
        """None chosen: the walk is put away, its files kept."""
        self.record.pop("uncertainty", None)
        self.save_manifest()
        self.flush(self.section)
        self.drop_overlay()
        self.drop_places_layer()
        self.spec = None
        self.u8 = None
        self.places = None
        self.view = None
        self.suggest()
        log("no uncertainty: the walk is put away, its files are kept")

    # ---------------------------------------------------------- the walk
    def overlay_ticked(self):
        card = self.card
        return bool(card is not None and card.overlay.isChecked())

    def start_or_next(self):
        """Start, Done and next, or back to the place in hand."""
        places = self.places
        if places is None:
            return None
        here = places.current()
        if here is not None and self.view is not None and \
                self.view["place_id"] != here["place_id"]:
            self.view = here
            self.show_place(here)
            return here
        if here is not None and self.view is not None:
            changed = 0
            marks = self.section.marks
            if marks is not None:
                changed = int(marks[here["row"]:here["row"] + here["height"],
                                    here["col"]:here["col"] + here["width"]]
                              .astype(bool).sum())
            places.done(operator_word(self.section.operator_name()),
                        report_utc(), self.overlay_seen
                        or self.overlay_ticked(), changed)
            self.add_done(here)
            self.note("place_done", here)
        return self.offer()

    def skip_place(self):
        places = self.places
        if places is None or places.current() is None:
            return None
        row = places.skip(report_utc(), self.overlay_seen
                          or self.overlay_ticked())
        self.note("place_skip", row)
        return self.offer()

    def offer(self):
        row = self.places.next(report_utc())
        self.overlay_seen = self.overlay_ticked()
        self.view = row
        self.save_places()
        if row is not None:
            self.show_place(row)
        else:
            log("every place of the walk has been seen")
        return row

    def back_place(self):
        if self.places is None:
            return None
        row = self.places.back(self.view)
        if row is not None:
            self.view = row
            self.show_place(row)
        return row

    def note(self, action, row):
        note = getattr(self.section, "note", None)
        if callable(note) and row is not None:
            try:
                note(action, place=row["place_id"])
            except Exception:
                pass

    def save_places(self):
        if self.places is None:
            return
        try:
            self.places.save()
        except OSError as err:
            log("cannot write %s: %s" % (PLACES_CSV, err), loud=True)
        self.write_geojson()
        self.reload_places_layer()

    def write_geojson(self, reveal=False):
        if self.places is None:
            return
        try:
            self.places.geojson(self.geojson_path, self.section.wkt, reveal)
        except Exception as err:
            log("cannot write %s: %s" % (PLACES_GEOJSON, err))

    def show_place(self, row):
        """The place on the map: its box, in the canvas's system, a little
        wider than itself."""
        try:
            from qgis.core import QgsCoordinateTransform, QgsRectangle
            box = QgsRectangle(row["x_min"], row["y_min"], row["x_max"],
                               row["y_max"])
            here = QgsCoordinateReferenceSystem()
            here.createFromWkt(self.section.wkt or "")
            target = canvas().mapSettings().destinationCrs()
            if here.isValid() and target.isValid() and here != target:
                box = QgsCoordinateTransform(
                    here, target, QgsProject.instance()).transformBoundingBox(
                        box)
            grow_x = box.width() * UNC_GROW / 2.0
            grow_y = box.height() * UNC_GROW / 2.0
            canvas().setExtent(QgsRectangle(
                box.xMinimum() - grow_x, box.yMinimum() - grow_y,
                box.xMaximum() + grow_x, box.yMaximum() + grow_y))
            canvas().refresh()
        except Exception as err:
            log("cannot show the place on the map: %s" % err)

    # ---------------------------------------------------------- layers
    def overlay_role(self):
        return "uncertainty:%s" % self.record.get("name", "")

    def places_role(self):
        return "places:%s" % self.record.get("name", "")

    def _owner_id(self):
        return self.section.book.data["id"]

    def ensure_overlay(self, visible=None):
        """The layer of u over the copy, multiplied into its colours: white
        where the model was sure, so nothing changes there."""
        if self.u8 is None:
            return None
        layer = find_mine(self._owner_id(), self.overlay_role())
        if layer is None:
            layer = QgsRasterLayer(self.derived, "%s_uncertainty"
                                   % self.section.layer_title())
            if not layer.isValid():
                log("the uncertainty will not load as a layer: %s"
                    % self.derived)
                return None
            unc_style_overlay(layer)
            layer = add_layer(layer, self.section.book, self.overlay_role())
            unc_place_above(self.section.book.group_name, layer,
                            find_mine(self._owner_id(),
                                      self.section.layer_role()))
        if visible is None:
            visible = self.overlay_ticked()
        unc_tick(layer, visible)
        return layer

    def drop_overlay(self):
        for role in (self.overlay_role(),):
            layer = find_mine(self._owner_id(), role)
            if layer is not None:
                QgsProject.instance().removeMapLayers([layer.id()])

    def ensure_places_layer(self):
        if self.places is None or not os.path.exists(
                long_path(self.geojson_path)):
            return None
        layer = find_mine(self._owner_id(), self.places_role())
        if layer is None:
            layer = QgsVectorLayer(self.geojson_path, "%s_places"
                                   % self.section.layer_title(), "ogr")
            if not layer.isValid():
                log("the places will not load as a layer: %s"
                    % self.geojson_path)
                return None
            try:
                crs = QgsCoordinateReferenceSystem()
                crs.createFromWkt(self.section.wkt or "")
                if crs.isValid():
                    layer.setCrs(crs)
            except Exception:
                pass
            unc_style_places(layer)
            layer = add_layer(layer, self.section.book, self.places_role())
            unc_place_above(self.section.book.group_name, layer,
                            find_mine(self._owner_id(), self.overlay_role())
                            or find_mine(self._owner_id(),
                                         self.section.layer_role()))
        return layer

    def reload_places_layer(self):
        layer = find_mine(self._owner_id(), self.places_role())
        if layer is None:
            self.ensure_places_layer()
            return
        try:
            layer.dataProvider().reloadData()
            layer.triggerRepaint()
        except Exception:
            pass

    def drop_places_layer(self):
        layer = find_mine(self._owner_id(), self.places_role())
        if layer is not None:
            QgsProject.instance().removeMapLayers([layer.id()])

    # ---------------------------------------------------------- the hooks
    def stroke(self, section, ctx):
        """The place in hand, for the journal's row of this stroke."""
        if self.places is not None:
            here = self.places.current()
            if here is not None:
                ctx["place"] = here["place_id"]
        return None

    def flush(self, section):
        if self.places is not None:
            try:
                self.places.save()
            except OSError as err:
                log("cannot write %s: %s" % (PLACES_CSV, err))

    def closing(self, section):
        self.flush(section)
        self.u8 = None
        self.places = None
        self.card = None

    def files(self, section):
        out = unc_files(section.path)
        if self.derived not in out:
            out[:0] = [self.derived, self.derived + ".aux.xml"]
        return out


def unc_tick(layer, on):
    try:
        node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
        if node is not None:
            node.setItemVisibilityChecked(bool(on))
    except Exception:
        pass


def unc_place_above(group_name, layer, below):
    """The layer moved to sit right above another in the group."""
    try:
        group = group_node(group_name)
        node = group.findLayer(layer.id())
        if node is None:
            return
        index = 0
        if below is not None:
            kids = list(group.children())
            for k, kid in enumerate(kids):
                if getattr(kid, "layerId", lambda: None)() == below.id():
                    index = k
                    break
        clone = node.clone()
        group.insertChildNode(index, clone)
        group.removeChildNode(node)
    except Exception as err:
        log("cannot put the layer above the copy: %s" % err)


def unc_style_overlay(layer):
    """A pseudocolour of band 1, white at 0, orange in the middle, dark red
    at 254, multiplied into what is under it at OVERLAY_OPACITY percent.
    255 is the file's nodata and stays clear. The enumerations moved between
    QGIS 3 and 4, so each is looked up."""
    try:
        from qgis.core import (QgsColorRampShader, QgsRasterShader,
                               QgsSingleBandPseudoColorRenderer)
        try:
            from qgis.core import Qgis
        except Exception:
            Qgis = None
        shader = QgsColorRampShader(0.0, float(U_LEVELS))
        interpolated = first_attr(Qgis, "ShaderInterpolationMethod.Linear") \
            if Qgis is not None else None
        if interpolated is None:
            interpolated = first_attr(QgsColorRampShader, "Type.Interpolated",
                                      "Interpolated")
        if interpolated is not None:
            shader.setColorRampType(interpolated)
        shader.setColorRampItemList([
            QgsColorRampShader.ColorRampItem(float(v), QColor(c), "%.2f"
                                             % (v / float(U_LEVELS)))
            for v, c in UNC_OVERLAY_COLOURS])
        raster = QgsRasterShader()
        raster.setRasterShaderFunction(shader)
        renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1,
                                                    raster)
        renderer.setClassificationMin(0.0)
        renderer.setClassificationMax(float(U_LEVELS))
        layer.setRenderer(renderer)
        layer.setBlendMode(QPainter.CompositionMode.CompositionMode_Multiply)
        try:
            layer.setOpacity(OVERLAY_OPACITY / 100.0)
        except Exception:
            renderer.setOpacity(OVERLAY_OPACITY / 100.0)
        layer.triggerRepaint()
    except Exception as err:
        log("cannot style the uncertainty: %s" % err)


def unc_style_places(layer):
    """The places as outlines, by status: the one in hand thick in the
    highlight colour, done thin grey, skipped dotted, queued dashed."""
    try:
        from qgis.core import (QgsCategorizedSymbolRenderer, QgsFillSymbol,
                               QgsRendererCategory)
        accent = palette_colours().get("accent", "#2a78d6")
        looks = [("current", accent, "0.9", "solid", "current"),
                 ("done", "#808080", "0.26", "solid", "done"),
                 ("skipped", "#808080", "0.26", "dot", "skipped"),
                 ("queued", "#606060", "0.26", "dash", "next")]
        cats = []
        for value, colour, width, style, label in looks:
            symbol = QgsFillSymbol.createSimple({
                "color": "0,0,0,0", "style": "no", "outline_color":
                QColor(colour).name(), "outline_width": width,
                "outline_style": style})
            cats.append(QgsRendererCategory(value, symbol, label))
        layer.setRenderer(QgsCategorizedSymbolRenderer("status", cats))
        layer.triggerRepaint()
    except Exception as err:
        log("cannot style the places: %s" % err)


#  The card in Correct
# =====================================================================
class Sparkline(QWidget):
    """The share of pixels changed per decile of u over the done places,
    as ten bars drawn by hand, UNC_SPARK_H pixels high. It is as wide as
    the room it is given and never asks for more than a few pixels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.values = []
        self.setFixedHeight(UNC_SPARK_H)
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(120, UNC_SPARK_H)

    def minimumSizeHint(self):
        return QSize(40, UNC_SPARK_H)

    def set_values(self, values):
        self.values = list(values or [])
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            colours = palette_colours()
            n = max(1, len(self.values))
            gap = 2
            w = max(1.0, (self.width() - gap * (n - 1)) / float(n))
            h = self.height()
            base = QColor(colours.get("line", "#cccccc"))
            ink = QColor(colours.get("accent", "#2a78d6"))
            for k, (share, count) in enumerate(self.values):
                x = int(k * (w + gap))
                p.fillRect(x, h - 1, int(w), 1, base)
                if share is None:
                    continue
                tall = max(1, int(round(share * (h - 1))))
                p.fillRect(x, h - tall, int(w), tall, ink)
        finally:
            p.end()


class UncertaintyCard(QWidget):
    """UNCERTAINTY, in Correct after Save: one quiet line while no
    uncertainty is chosen, the walk once one is."""

    @classmethod
    def place_in(cls, section):
        """The card in Correct's slot after Save, when this build keeps an
        uncertainty hook for it; nothing at all otherwise."""
        hook = unc_hook_of(section)
        if hook is None or getattr(section, "measure_slot", None) is None:
            return None
        card = cls(section, hook)
        section.measure_slot.addWidget(card)
        return card

    def __init__(self, section, hook):
        super().__init__()
        self.section = section
        self.hook = hook
        hook.card = self
        follows_width(self)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 4, 0, 0)
        box.setSpacing(5)

        head = follows_width(QWidget())
        row = QHBoxLayout(head)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        word = QLabel("UNCERTAINTY")
        word.setObjectName("subsection")
        f = word.font()
        f.setPointSize(max(f.pointSize() - 1, 7))
        word.setFont(f)
        row.addWidget(word)
        row.addStretch(1)
        self.b_source = section._act("Source…", UNC_TIPS["source"],
                                     self.choose)
        row.addWidget(self.b_source)
        box.addWidget(head)

        self.line = QLabel("")
        self.line.setObjectName("quiet")
        self.line.setWordWrap(True)
        box.addWidget(self.line)

        self.use_box = follows_width(QWidget())
        self.b_use = section._act("Use it", UNC_TIPS["use"], self.use_it)
        self.use_box.setLayout(spread([self.b_use], gap=4))
        box.addWidget(self.use_box)

        self.walk = follows_width(QWidget())
        inner = QVBoxLayout(self.walk)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(5)
        self.overlay = WrapTick("show it on the map")
        self.overlay.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.overlay.setToolTip(UNC_TIPS["overlay"])
        self.overlay.toggled.connect(shielded(self.overlay_toggled,
                                              "show it on the map"))
        inner.addWidget(self.overlay)
        self.frame = QFrame()
        self.frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame_box = QVBoxLayout(self.frame)
        frame_box.setContentsMargins(6, 4, 6, 4)
        self.place = QLabel("")
        self.place.setWordWrap(True)
        frame_box.addWidget(self.place)
        inner.addWidget(follows_width(self.frame))
        keys = follows_width(QWidget())
        self.keys = KeyRow(key_need, 4, least=key_least)
        self.b_back = section._act("◀", UNC_TIPS["back"], self.back)
        self.b_next = section._act("Done, next ▶", UNC_TIPS["next"],
                                   self.next)
        self.b_skip = section._act("Skip", UNC_TIPS["skip"], self.skip)
        for b in (self.b_back, self.b_next, self.b_skip):
            self.keys.add(b)
        keys.setLayout(self.keys)
        inner.addWidget(keys)
        spark = follows_width(QWidget())
        srow = QHBoxLayout(spark)
        srow.setContentsMargins(0, 0, 0, 0)
        srow.setSpacing(6)
        self.spark_word = QLabel("changed, by decile")
        self.spark_word.setObjectName("quiet")
        self.spark_word.setWordWrap(True)
        srow.addWidget(self.spark_word)
        self.spark = Sparkline()
        srow.addWidget(self.spark, 1)
        inner.addWidget(spark)
        foot = follows_width(QWidget())
        frow = QHBoxLayout(foot)
        frow.setContentsMargins(0, 0, 0, 0)
        frow.setSpacing(6)
        self.auc = QLabel("")
        self.auc.setObjectName("quiet")
        self.auc.setWordWrap(True)
        frow.addWidget(self.auc, 1)
        self.b_report = section._act("Report…", UNC_TIPS["report"],
                                     self.report)
        frow.addWidget(self.b_report)
        inner.addWidget(foot)
        box.addWidget(self.walk)
        self.overlay.blockSignals(True)
        self.overlay.setChecked(bool(hook.places is not None
                                     and not hook.places.blind))
        self.overlay.blockSignals(False)
        self.refresh()
        if hook.u8 is not None:
            # after Correct has put the copy on the map, so the layers of
            # the walk go above it
            QTimer.singleShot(0, shielded(self.layers, "Uncertainty"))

    # ---------------------------------------------------------- showing
    def layers(self):
        if self.hook.u8 is None:
            return
        self.hook.ensure_overlay()
        self.hook.ensure_places_layer()

    def refresh(self):
        hook = self.hook
        on = hook.u8 is not None and hook.spec is not None
        self.walk.setVisible(on)
        self.use_box.setVisible(not on and hook.suggested is not None)
        if on:
            blind = hook.places is not None and hook.places.blind
            self.line.setText("%s%s" % (unc_describe(hook.spec),
                                        " · blind" if blind else ""))
            self.line.setToolTip(hook.spec.get("rule", "")
                                 or unc_describe(hook.spec))
            self.show_walk()
        elif hook.trouble:
            self.line.setText(hook.trouble + ".")
        elif hook.suggested is not None:
            band, desc, kind, _ = hook.suggested
            self.line.setText('band %d "%s" looks like the %s.'
                              % (band, desc, UNC_KIND_WORDS.get(kind, kind)
                                 if kind != "probability"
                                 else "probability of the class"))
        else:
            self.line.setText(UNC_NONE)
        settle = getattr(self.section, "settle", None)
        if callable(settle):
            try:
                settle()
            except Exception:
                pass

    def show_walk(self):
        hook = self.hook
        places = hook.places
        if places is None:
            return
        c = places.counts()
        here = places.current()
        view = hook.view
        tally = "%d done · %d skipped" % (c["done"], c["skipped"])
        if view is None:
            if places.remaining():
                words = "%d places of %d px · %s" % (places.N, places.side,
                                                     tally)
            else:
                words = "all %d places seen · %s" % (places.N, tally)
        else:
            words = "place %d" % view["offer_no"]
            if not places.blind:
                words += " of %d · u %.2f · %s" % (
                    places.N, float(view["mean_u"] or 0.0),
                    view["selection"])
            if here is not None and view["place_id"] != here["place_id"]:
                words += " · %s, seen before" % (view["status"] or "seen")
            words += " · " + tally
        self.place.setText(words)
        self.b_back.setEnabled(places.back(view) is not None)
        if here is None:
            remaining = places.remaining()
            self.b_next.setText("Start ▶" if remaining and not c["offered"]
                                else "Next ▶" if remaining
                                else "All places seen")
            self.b_next.setToolTip(UNC_TIPS["start"])
            self.b_next.setEnabled(remaining)
            self.b_skip.setEnabled(False)
        elif view is None or view["place_id"] != here["place_id"]:
            self.b_next.setText("Current ▶")
            self.b_next.setToolTip("Back to the place in hand. Nothing is "
                                   "marked.")
            self.b_next.setEnabled(True)
            self.b_skip.setEnabled(False)
        else:
            self.b_next.setText("Done, next ▶")
            self.b_next.setToolTip(UNC_TIPS["next"])
            self.b_next.setEnabled(True)
            self.b_skip.setEnabled(True)
        bars = hook.spark()
        self.spark.set_values(bars)
        self.spark.setToolTip("Share of the pixels changed in the done "
                              "places, per decile of u:\n" + "\n".join(
                                  "decile %d: %s of %d px" % (
                                      k + 1, "—" if s is None
                                      else "%.1f %%" % (100 * s), n)
                                  for k, (s, n) in enumerate(bars)))
        auc = hook.auc_done()
        self.auc.setText("AUC %s over %d place%s" % (
            "—" if auc != auc else "%.2f" % auc, c["done"],
            "" if c["done"] == 1 else "s"))

    # ---------------------------------------------------------- keys
    def choose(self):
        unc_choose(self.section, self.hook)
        self.refresh()

    def use_it(self):
        hook = self.hook
        if hook.suggested is None:
            return
        band, desc, kind, scale = hook.suggested
        spec = {"source": "copy", "path": "", "band": band,
                "band_name": desc, "kind": kind, "scale": float(scale),
                "offset": 0.0}
        hook.apply(spec)
        words = unc_preview_words(self.section, spec)["text"]
        if words:
            iface.messageBar().pushMessage(NAME, "uncertainty: %s; %s"
                                           % (unc_describe(spec), words),
                                           level=LEVEL_INFO, duration=8)
        self.overlay.setChecked(not hook.places.blind)
        self.refresh()

    def overlay_toggled(self, on):
        if on and self.hook.places is not None and \
                self.hook.places.current() is not None:
            self.hook.overlay_seen = True
        self.hook.ensure_overlay(on)

    def next(self):
        self.hook.start_or_next()
        self.refresh()

    def skip(self):
        self.hook.skip_place()
        self.refresh()

    def back(self):
        self.hook.back_place()
        self.refresh()

    def report(self):
        unc_report_start(self.section.panel)


#  Choosing the uncertainty
# =====================================================================
def unc_preview_words(section, spec):
    """The one line of a reading, from a small look at the whole map."""
    try:
        src = unc_source_path(spec, os.path.dirname(section.path)) \
            or section.path
        cls = unc_sample(section.path, [section.band_no])[section.band_no]
        bands = [spec["band"]] + ([spec.get("labelled_band")]
                                  if spec.get("kind") == "votes" else [])
        got = unc_sample(src, bands)
        raw = got[spec["band"]]
        lab = got.get(spec.get("labelled_band"))
        if raw.shape != cls.shape:
            cls = np.ones(raw.shape, dtype=bool)
            valid = cls
        else:
            valid = unc_class_valid(cls, section.nodata)
        info = [b for b in unc_bands(src) if b["band"] == spec["band"]]
        nodata = info[0]["nodata"] if info else None
        gain = (info[0].get("scale") if info else None) or 1.0
        offset = (info[0].get("offset") if info else None) or 0.0
        u8, _ = unc_to_u8(raw, lab, spec, valid, nodata, gain, offset)
        v = None
        if spec.get("kind") == "entropy":
            v = (raw.astype(np.float64) * gain + offset) / \
                float(spec.get("scale") or 1.0)
            v = v[valid]
        return unc_preview(u8, valid, v, spec.get("kind"))
    except Exception as err:
        log("cannot preview the uncertainty: %s" % err)
        return {"text": "", "nats": False}


def unc_choose(section, hook):
    """Source…: the window, then what it says."""
    done = hook.places is not None and any(
        r["status"] for r in hook.places.rows)
    dialog = UncertaintySource(section, section, hook, side_locked=done)
    if not run_dialog(dialog):
        return None
    got = dialog.result()
    if got is None:
        if hook.spec is not None:
            hook.turn_off()
        return None
    spec, settings = got
    try:
        hook.apply(spec, settings)
    except Exception as err:
        QMessageBox.warning(section, NAME, "The uncertainty could not be "
                            "read:\n\n%s\n\nNothing was changed." % err)
        log("the uncertainty could not be read: %s" % err)
        return None
    if hook.card is not None:
        hook.card.overlay.setChecked(not hook.places.blind)
    return spec


class UncertaintySource(QDialog):
    """Which band or raster holds the uncertainty of the map, what it
    holds, on which scale; and the places the walk goes through."""

    def __init__(self, parent, section, hook, side_locked=False):
        super().__init__(parent)
        self.setWindowTitle(titled("Uncertainty of the map"))
        self.section = section
        self.hook = hook
        self.side_locked = side_locked
        self.confirmed = False
        self.relation = "same"
        self.copy_bands = [b for b in unc_bands(section.path)
                           if b["band"] != section.band_no]
        self.other_bands = []
        spec = dict(hook.spec or {})
        settings = dict(section.record.get("places") or {})
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        row = 0
        self.group = QButtonGroup(self)
        self.none = narrow_radio("none: the map has no uncertainty")
        self.in_copy = narrow_radio("a band of the map")
        self.in_file = narrow_radio("another raster")
        for k, b in enumerate((self.none, self.in_copy, self.in_file)):
            self.group.addButton(b, k)
        # each choice is a row of its own and the list that goes with it the
        # row under: side by side they are as wide as a radio button and a
        # list together, and DejaVu holds the window past 300 px
        grid.addWidget(self.none, row, 0, 1, 3)
        row += 1
        grid.addWidget(self.in_copy, row, 0, 1, 3)
        row += 1
        self.band = QComboBox()
        for b in self.copy_bands:
            self.band.addItem("band %d  %s" % (b["band"], b["description"]),
                              b["band"])
        self.band.setToolTip("Every band of the map but its classes.")
        grid.addWidget(self.band, row, 1, 1, 2)
        row += 1
        grid.addWidget(self.in_file, row, 0, 1, 3)
        row += 1
        self.raster = QComboBox()
        self.raster.setToolTip("A raster on the same ground as the map: the "
                               "probabilities of a model, or the _votes.tif "
                               "of a consensus.")
        for lyr in project_rasters(need_crs=False):
            # a map a report loaded (the disagreement map of Compare, the
            # pairs of Model vs corrected) is a picture of the work, never
            # the uncertainty of a map
            if is_report_layer(lyr):
                continue
            try:
                path = lyr.source().split("|")[0]
            except Exception:
                continue
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(
                    os.path.abspath(section.path)):
                continue
            self.raster.addItem(lyr.name(), path)
        grid.addWidget(self.raster, row, 1)
        self.pick = browse("Choose a raster file.")
        self.pick.clicked.connect(shielded(self.browse_file, "Source"))
        grid.addWidget(self.pick, row, 2)
        row += 1
        grid.addWidget(QLabel("Band"), row, 0)
        self.file_band = QComboBox()
        grid.addWidget(self.file_band, row, 1, 1, 2)
        row += 1
        # Sized to their contents, the lists of bands and rasters took the
        # width of the longest name in the project: a report map loaded by
        # Compare held the window at 440 px. They cut a long name instead,
        # whole in the list when it opens.
        for box in (self.band, self.raster, self.file_band):
            short_combo(box)
        self.grid_note = self._quiet("")
        self.grid_note.setStyleSheet("color:%s" % palette_colours()["danger"])
        grid.addWidget(self.grid_note, row, 0, 1, 3)
        row += 1
        holds = QLabel("What it holds")
        holds.setWordWrap(True)         # the name column is the widest row
        grid.addWidget(holds, row, 0)
        self.kind = QComboBox()
        for k in UNC_KINDS:
            self.kind.addItem(UNC_KIND_WORDS[k], k)
        self.kind.setToolTip("Probability: the model's probability of the "
                             "class it chose, read as 1 - p.\nEntropy, "
                             "normalised to 0-1. Margin: the first "
                             "probability minus the second,\nread as 1 - m. "
                             "Uncertainty: already higher where less sure.\n"
                             "Votes: the votes and labelled readings of a "
                             "consensus, read as 1 - votes / readings.")
        short_combo(self.kind)
        grid.addWidget(self.kind, row, 1, 1, 2)
        row += 1
        grid.addWidget(QLabel("Scale"), row, 0)
        self.scale = QComboBox()
        for words, value in UNC_SCALE_CHOICES:
            self.scale.addItem(words, value)
        self.scale.setToolTip("What the raw values are divided by to give 0 "
                              "to 1.")
        short_combo(self.scale)
        grid.addWidget(self.scale, row, 1)
        self.custom = QDoubleSpinBox()
        self.custom.setRange(1e-9, 1e12)
        self.custom.setDecimals(4)
        self.custom.setValue(1.0)
        grid.addWidget(short_spin(self.custom, "0000,000"), row, 2)
        row += 1
        self.nats = narrow_tick("")
        self.nats.setToolTip("An entropy in nats goes up to ln K, K the "
                             "number of classes; divided by ln K it goes to "
                             "1.")
        grid.addWidget(self.nats, row, 0, 1, 3)
        row += 1
        self.preview = self._quiet("")
        grid.addWidget(self.preview, row, 0, 1, 3)
        row += 1

        grid.addWidget(report_part("Places"), row, 0, 1, 3)
        row += 1
        grid.addWidget(QLabel("Side"), row, 0)
        self.side = QSpinBox()
        self.side.setRange(16, 8192)
        self.side.setSingleStep(16)
        self.side.setSuffix(" px")
        self.side.setValue(int(settings.get("side_px") or PLACE_SIDE_PX))
        if side_locked:
            self.side.setEnabled(False)
            self.side.setToolTip("Some places are already done: their side "
                                 "cannot change.")
        grid.addWidget(self.side, row, 1)
        self.side_note = self._quiet("")
        grid.addWidget(self.side_note, row, 2)
        row += 1
        grid.addWidget(QLabel("1 in"), row, 0)
        self.every = QSpinBox()
        self.every.setRange(0, 100)
        every = settings.get("random_every")
        self.every.setValue(RANDOM_EVERY if every is None else int(every))
        self.every.setToolTip("Every so many places, one is drawn at random "
                              "instead. 0: none.")
        grid.addWidget(self.every, row, 1)
        grid.addWidget(self._quiet("drawn at random"), row, 2)
        row += 1
        grid.addWidget(QLabel("Seed"), row, 0)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2 ** 31 - 1)
        seed = settings.get("seed")
        self.seed.setValue(int(seed) if seed is not None else
                           unc_default_seed(section.book.data.get("id"),
                                            section.record.get("name", "")))
        self.seed.setToolTip("The seed of the random draw, written in the "
                             "manifest: the same seed draws the same "
                             "places.")
        if side_locked:
            self.seed.setEnabled(False)
        grid.addWidget(short_spin(self.seed), row, 1, 1, 2)
        row += 1
        self.blind = narrow_tick("blind: hide the uncertainty while reviewing")
        self.blind.setChecked(bool(settings.get("blind", True)))
        self.blind.setToolTip("The card says nothing of how uncertain a "
                              "place is or why it was chosen, and the map\n"
                              "shows no uncertainty until you tick it: you "
                              "look at every place alike.")
        grid.addWidget(self.blind, row, 0, 1, 3)
        row += 1
        grid.addWidget(self._quiet(
            "Places ranked by uncertainty are purposive: they never enter a "
            "design-based estimate. Only the random ones carry an inclusion "
            "probability."), row, 0, 1, 3)
        row += 1
        grid.setRowStretch(row, 1)
        row += 1
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self.go = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.go.setText("Use")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        grid.addWidget(self.buttons, row, 0, 1, 3)

        # what the manifest holds, or what the copy's names suggest
        if spec.get("source") == "file":
            self.in_file.setChecked(True)
            path = unc_source_path(spec, os.path.dirname(section.path))
            self.set_file(path)
            self.select(self.file_band, spec.get("band"))
        elif spec.get("source") == "copy" or hook.suggested or \
                self.copy_bands:
            self.in_copy.setChecked(bool(self.copy_bands))
            self.none.setChecked(not self.copy_bands)
            want = spec.get("band") or (hook.suggested[0] if hook.suggested
                                        else None)
            self.select(self.band, want)
        else:
            self.none.setChecked(True)
        if self.raster.count() and not self.other_bands:
            self.file_changed()
        if spec.get("kind"):
            self.select(self.kind, spec["kind"])
            self.set_scale(spec.get("scale"))
        else:
            self.guess()
        self.group.buttonClicked.connect(shielded(self.source_changed,
                                                  "Source"))
        self.band.currentIndexChanged.connect(
            shielded(self.source_changed, "Source"))
        self.raster.currentIndexChanged.connect(
            shielded(self.file_changed, "Source"))
        self.file_band.currentIndexChanged.connect(
            shielded(self.source_changed, "Source"))
        self.kind.currentIndexChanged.connect(shielded(self.refresh,
                                                       "Source"))
        self.scale.currentIndexChanged.connect(shielded(self.refresh,
                                                        "Source"))
        self.custom.valueChanged.connect(shielded(self.refresh, "Source"))
        self.nats.toggled.connect(shielded(self.refresh, "Source"))
        self.side.valueChanged.connect(shielded(self.refresh, "Source"))
        self.refresh()
        # as narrow as the other windows of the measures, 300 px
        keep_shape(self, 300)

    # ---------------------------------------------------------- pieces
    def _quiet(self, text):
        label = QLabel(text)
        label.setObjectName("quiet")
        label.setWordWrap(True)
        return label

    @staticmethod
    def select(combo, data):
        k = combo.findData(data)
        if k >= 0:
            combo.setCurrentIndex(k)

    def set_scale(self, value):
        for k in range(self.scale.count()):
            if self.scale.itemData(k) == value:
                self.scale.setCurrentIndex(k)
                return
        self.scale.setCurrentIndex(self.scale.count() - 1)
        if value:
            self.custom.setValue(float(value))

    def source(self):
        """(path, band, bands) of the chosen source, or None for none."""
        if self.in_copy.isChecked():
            band = self.band.currentData()
            return self.section.path, band, self.copy_bands
        if self.in_file.isChecked():
            return self.raster.currentData() or "", \
                self.file_band.currentData(), self.other_bands
        return None

    def set_file(self, path):
        if not path:
            return
        k = self.raster.findData(path)
        if k < 0:
            self.raster.addItem(os.path.basename(path), path)
            k = self.raster.count() - 1
        self.raster.setCurrentIndex(k)
        self.file_changed()

    def browse_file(self):
        got, _ = QFileDialog.getOpenFileName(
            self, "A raster with the uncertainty of the map",
            os.path.dirname(self.section.path),
            "Rasters (*.tif *.tiff *.vrt *.img);;All files (*)")
        if got:
            self.in_file.setChecked(True)
            self.set_file(got)
            self.source_changed()

    def file_changed(self, *args):
        path = self.raster.currentData() or ""
        self.other_bands = unc_bands(path) if path else []
        self.file_band.blockSignals(True)
        self.file_band.clear()
        for b in self.other_bands:
            self.file_band.addItem("%d  %s" % (b["band"], b["description"]),
                                   b["band"])
        votes = [b["band"] for b in self.other_bands
                 if b["description"].strip().lower() == UNC_VOTES_BAND]
        if votes:
            self.select(self.file_band, votes[0])
        self.file_band.blockSignals(False)
        self.relation = unc_grid_relation(self.section.path, path) \
            if path else "same"
        self.confirmed = False
        if self.in_file.isChecked():
            self.guess()
        self.refresh()

    def source_changed(self, *args):
        self.guess()
        self.refresh()

    def labelled_band(self):
        """The band of labelled readings beside the votes, or None."""
        got = self.source()
        if got is None:
            return None
        for b in got[2]:
            if b["description"].strip().lower() == UNC_LABELLED_BAND:
                return b["band"]
        return None

    def guess(self):
        got = self.source()
        if got is None or not got[1]:
            return
        _, band, bands = got
        info = [b for b in bands if b["band"] == band]
        if not info:
            return
        b = info[0]
        names = [x["description"] for x in bands]
        kind = unc_guess_kind(b["description"], names)
        if kind:
            self.select(self.kind, kind)
        sample_max = None
        if b["type"] == "UInt16":
            try:
                arr = unc_sample(got[0], [band], 256)[band]
                sample_max = float(np.nanmax(arr))
            except Exception:
                sample_max = None
        scale = unc_guess_scale(b["description"], b["type"], b.get("scale"),
                                sample_max)
        if scale is not None:
            self.set_scale(scale)

    def chosen_scale(self):
        value = self.scale.currentData()
        if value is None:
            value = float(self.custom.value())
        if self.nats.isVisible() and self.nats.isChecked():
            value *= math.log(max(2, len(self.section.classes())))
        return float(value)

    def spec(self):
        got = self.source()
        if got is None:
            return None
        path, band, bands = got
        info = [b for b in bands if b["band"] == band]
        spec = {"source": "copy" if self.in_copy.isChecked() else "file",
                "path": "", "band": band,
                "band_name": info[0]["description"] if info else "",
                "kind": self.kind.currentData(),
                "scale": self.chosen_scale(), "offset": 0.0}
        if spec["source"] == "file":
            rel = path
            try:
                inside = os.path.relpath(path, os.path.dirname(
                    self.section.path))
                if not inside.startswith(".."):
                    rel = inside
            except ValueError:
                pass
            spec["path"] = rel
            if self.relation == "resampled":
                spec["resample_ok"] = self.confirmed
        if spec["kind"] == "votes":
            spec["labelled_band"] = self.labelled_band()
            spec["scale"] = 1.0
        return spec

    # ---------------------------------------------------------- refresh
    def refresh(self, *args):
        got = self.source()
        on = got is not None and bool(got[1])
        file_on = self.in_file.isChecked()
        self.band.setEnabled(self.in_copy.isChecked())
        for w in (self.raster, self.pick, self.file_band):
            w.setEnabled(file_on)
        votes_ok = on and self.labelled_band() is not None
        votes_item = self.kind.model().item(self.kind.findData("votes")) \
            if hasattr(self.kind.model(), "item") else None
        if votes_item is not None:
            votes_item.setEnabled(votes_ok)
        if self.kind.currentData() == "votes" and not votes_ok:
            self.select(self.kind, "probability")
        kind = self.kind.currentData()
        self.kind.setEnabled(on)
        self.scale.setEnabled(on and kind != "votes")
        self.custom.setVisible(self.scale.currentData() is None)
        self.custom.setEnabled(on and kind != "votes")
        note = ""
        refused = False
        if file_on:
            if isinstance(self.relation, tuple):
                note = "%s: it cannot be used" % self.relation[1]
                refused = True
            elif self.relation == "resampled":
                note = ("not on the grid of the map: it will be read "
                        "nearest-neighbour")
            elif self.relation == "aligned":
                note = ""
        self.grid_note.setText(note)
        self.grid_note.setVisible(bool(note))
        words = ""
        nats = False
        if on and not refused:
            spec = self.spec()
            said = unc_preview_words(self.section, spec)
            words, nats = said["text"], said["nats"]
        self.nats.setText("in nats: divide by ln K (K = %d)"
                          % max(2, len(self.section.classes())))
        self.nats.setVisible(kind == "entropy" and (nats
                                                    or self.nats.isChecked()))
        self.preview.setText(words or ("" if on else
                                       "No uncertainty: Correct works as "
                                       "before."))
        side = unc_side_for(self.section.nx, self.section.ny,
                            self.side.value())
        n = int(math.ceil(self.section.nx / float(side))) * \
            int(math.ceil(self.section.ny / float(side)))
        px = getattr(getattr(self.section, "geometry", None), "pixel_m",
                     None) or (0.0, 0.0)
        self.side_note.setText("(%.1f m) · up to %d places%s" % (
            side * float(px[0] or 0.0), n, ", raised to %d px" % side
            if side != self.side.value() else ""))
        self.go.setEnabled(not refused and (on or self.none.isChecked()))

    def accept(self):
        if self.in_file.isChecked() and self.relation == "resampled" and \
                not self.confirmed:
            q = QMessageBox.question(
                self, NAME, "This raster is not on the grid of the map. Each "
                "pixel of the map takes the value under its centre "
                "(nearest neighbour).\n\nUse it?")
            if q != QMessageBox.StandardButton.Yes:
                return
            self.confirmed = True
        super().accept()

    def result(self):
        """(spec, places settings), or None for none."""
        spec = self.spec()
        if spec is None:
            return None
        return spec, {"side_px": int(self.side.value()),
                      "random_every": int(self.every.value()),
                      "seed": int(self.seed.value()),
                      "blind": bool(self.blind.isChecked())}


#  Measure ▸ Uncertainty report…
# =====================================================================
def unc_report_enabled(panel):
    if getattr(panel, "correction", None) is None:
        return False, "Open a correction first."
    section = unc_section(panel)
    hook = unc_hook_of(section) if section is not None else None
    if hook is None or hook.u8 is None or hook.spec is None:
        return False, UNC_CHOOSE_FIRST
    return True, ""


def unc_report_start(panel):
    """The report, from the press to its window."""
    section = unc_section(panel)
    hook = unc_hook_of(section) if section is not None else None
    on, why = unc_report_enabled(panel)
    if not on:
        QMessageBox.warning(panel, NAME, why)
        return None
    section.hooks_flush()
    record = section.record
    book = section.book
    owner_folder = book.folder if section.own_book() else \
        os.path.dirname(section.path)
    owner = {"kind": "correction", "id": record.get("id")
             or book.data.get("id", ""), "name": record.get("name", ""),
             "folder": owner_folder}
    progress = QProgressDialog("Measuring the uncertainty against the "
                               "corrections…", "Cancel", 0, 100, panel)
    progress.setWindowTitle(titled("Uncertainty report"))
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    def tick(done, total):
        progress.setValue(int(100 * done / max(1, total)))
        QApplication.processEvents()
        return not progress.wasCanceled()

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    said = None
    result = None
    try:
        net = unc_net(section.values, record.get("source"),
                      record.get("band", 1), section.nodata)
        folder = os.path.dirname(section.path)
        paths = {"copy": section.path, "changes": section.changes_path,
                 "derived": hook.derived, "places_csv": hook.places_path,
                 "operations": section.log_path,
                 "journal": os.path.join(folder, "journal.csv"),
                 "source": record.get("source")}
        result = unc_report(owner, record, hook.spec,
                            {"u8": hook.u8, "marks": section.marks,
                             "net": net}, hook.places, paths,
                            record.get("operations", 0), progress=tick)
    except UncRefused as err:
        said = (QMessageBox.warning, str(err))
        log("no uncertainty report: %s" % err)
    except Exception as err:
        said = (QMessageBox.critical, "Nothing was written:\n\n%s" % err)
        log("the uncertainty report failed: %s" % err)
    finally:
        QApplication.restoreOverrideCursor()
        progress.close()
        progress.deleteLater()
    if said is not None:
        said[0](panel, NAME, said[1])
        return None
    hook.save_places()
    hook.write_geojson(reveal=True)
    hook.reload_places_layer()
    try:
        rel = os.path.relpath(result["folder"], owner_folder)
    except ValueError:
        rel = result["folder"]
    summary = result["summary"]
    report_register(record, report_entry(UNC_KIND, uuid.uuid4().hex[:12], "",
                                         summary.get("created_utc")
                                         or report_utc(), rel,
                                         summary.get("headline") or {}))
    hook.save_manifest()
    log("uncertainty report written: %s" % result["folder"])
    if hook.card is not None:
        hook.card.refresh()
    try:
        section.show_tally()
    except Exception:
        pass
    run_dialog(unc_window(panel, result))
    return result


def unc_window(panel, result):
    """The report window of one run."""
    s = result["summary"]
    cal = result["calibration"]
    p = s.get("places") or {}
    u = s.get("uncertainty") or {}
    auc = s.get("auc") or {}
    ece = s.get("ece_fixed") or {}
    scope = ("%s · %d places done (%d random, %d purposive) of %d · %s px "
             "with a value" % (unc_describe(u), p.get("random_done", 0)
                               + p.get("purposive_done", 0),
                               p.get("random_done", 0),
                               p.get("purposive_done", 0),
                               p.get("eligible_N", 0),
                               report_group("%d" % int(u.get("valid_px") or 0))))
    headline = [("AUC, random places", auc.get("random_places")),
                ("AUC, purposive places", auc.get("purposive_places")),
                ("AUC, whole map", auc.get("whole_map"))]
    if u.get("kind") == "probability":
        headline += [("ECE, random places", ece.get("random_places")),
                     ("ECE, whole map", ece.get("whole_map"))]
    headline += [("Random places", "%d done, %d skipped, m = %d of N = %d"
                  % (p.get("random_done", 0), p.get("random_skipped", 0),
                     p.get("random_drawn_m", 0), p.get("eligible_N", 0)))]
    by = {}
    for r in cal["rows"]:
        if r["binning"] == "decile":
            by.setdefault(r["bin"], {})[r["scope"]] = r
    rows = []
    for b in sorted(by):
        whole = by[b].get("whole_map") or {}
        rnd = by[b].get("random_places") or {}
        pur = by[b].get("purposive_places") or {}
        rows.append([b + 1, "%.2f–%.2f" % (whole.get("u_low", 0),
                                           whole.get("u_high", 0)),
                     rnd.get("share_changed"), rnd.get("se_share"),
                     pur.get("share_changed"), whole.get("share_changed")])
    tables = [{"title": "Share changed, by decile of u", "columns": [
        "decile", "u", "random", "± SE", "purposive", "whole map"],
        "rows": rows, "colours": [], "align": [None, "r"],
        "formats": ["int", None, "pct", "pct", "pct", "pct"]}]
    cap = [r for r in cal["capture"] if r["scope"] == "whole_map"]
    if cap:
        tables.append({"title": "The most uncertain part of the map holds",
                       "columns": ["top of the map", "u at least",
                                   "changes caught"],
                       "rows": [["%g %%" % (100 * r["top_share"]),
                                 r["u_threshold"],
                                 r["share_of_changes_captured"]]
                                for r in cap], "colours": [],
                       "align": ["r"], "formats": [None, "f3", "pct"]})
    notes = list(s.get("notes") or [])
    window = ReportWindow(panel, "Uncertainty report", scope, headline,
                          tables, notes, result["folder"])
    return window

