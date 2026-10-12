"""rasterlabel.tools

What the mouse does on the canvas.
"""
import math

from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtGui import QColor
from qgis.core import (QgsCoordinateTransform, QgsGeometry, QgsPointXY,
                       QgsProject, QgsRectangle)
from qgis.gui import QgsMapTool, QgsRubberBand, QgsVertexMarker

from .constants import (CLOSE_RADIUS_PX, GEOM_LINE, GEOM_POLYGON, HANDLE_PX,
                        MOVE_PX, STEP_PX)
from .compat import iface
from .project import canvas, crs_label
from .errors import alive, log
from .journal import Stopwatch


#  The time of a stroke
# =====================================================================
# Every tool keeps a Stopwatch from the first press of a stroke to its last
# release, and hands what it read to the section just before handing over
# the stroke: section.timing = (dur_ms, pauses_s, tool). The section's path
# that keeps the stroke takes it (pop_timing) and writes it into the journal
# with the stroke. One left over once the call returns is a stroke the
# section refused, and it is written as "refused": the time was spent all
# the same. A section with no journal simply never reads it.
def stroke_watch(tool):
    """The Stopwatch of a map tool, made the first time it is asked for."""
    watch = getattr(tool, "_stopwatch", None)
    if not isinstance(watch, Stopwatch):
        watch = Stopwatch()
        try:
            tool._stopwatch = watch
        except Exception:
            pass
    return watch


def stroke_handed(section, watch, tool, call, *args):
    """call(*args) with the stroke's time handed to the section first, and a
    refusal written when the section did not take it."""
    timing = watch.take() if watch is not None else None
    timing = tuple(timing or (0, "")) + (tool,)
    try:
        section.timing = timing
    except Exception:
        pass
    try:
        return call(*args)
    finally:
        left = getattr(section, "timing", None)
        if left is not None:
            try:
                section.timing = None
            except Exception:
                pass
            note = getattr(section, "note", None)
            if callable(note):
                try:
                    note("refused", timing=left)
                except Exception as err:
                    log("the journal missed a refused stroke: %s" % err)


def stroke_dropped(section, watch, tool):
    """A stroke thrown away with Esc: its time is written as "discard"."""
    if watch is None or not watch.running:
        return
    timing = watch.take()
    note = getattr(section, "note", None)
    if callable(note) and timing is not None:
        try:
            note("discard", timing=tuple(timing) + (tool,))
        except Exception as err:
            log("the journal missed a discarded stroke: %s" % err)


def keep_key(ev):
    """Say that a key was taken here and QGIS is not to act on it too.

    The map canvas hands a key to the tool first and, backwards as it is, goes on
    to its own handling unless the tool left the event ignored. Backspace and
    Delete are then Delete Selected on the active layer: a vertex taken back
    would delete whichever polygons happened to be selected, and a box deleted
    here would be deleted a second time."""
    ev.ignore()


#  The line
# =====================================================================
class LineTool(QgsMapTool):
    """A trace rather than an outline: it never closes on itself.

      drag                  freehand, one stretch at a time
      single click          one vertex
      right click / Enter   finishes the line
      Backspace             removes the last vertex
      Esc                   throws away the line in progress
    """

    def __init__(self, canvas, section):
        super().__init__(canvas)
        self.canvas = canvas
        self.section = section
        self.points = []
        self.pressed = False
        self.dragged = False
        self.last_px = None
        self.skipped = False
        self.last_point = None
        self.band = QgsRubberBand(canvas, GEOM_LINE)
        self.band.setWidth(3)

    def refresh_colour(self):
        self.band.setColor(QColor(self.section.current_colour()))

    def _map(self, ev):
        return self.toMapCoordinates(ev.pos())

    def _redraw(self, provisional=None):
        self.band.reset(GEOM_LINE)
        pts = self.points + ([provisional] if provisional else [])
        if len(pts) >= 2:
            self.band.setToGeometry(QgsGeometry.fromPolylineXY(pts), None)

    def canvasPressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if not self.points:
            stroke_watch(self).begin()
        else:
            stroke_watch(self).touch()
        self.pressed = True
        self.dragged = False
        self.last_px = ev.pos()

    def canvasMoveEvent(self, ev):
        self.last_point = self._map(ev)
        if stroke_watch(self).running:
            stroke_watch(self).touch()
        if not self.pressed:
            self._redraw(self.last_point)
            return
        if self.last_px is not None:
            d = ev.pos() - self.last_px
            if d.manhattanLength() < STEP_PX:
                return
        self.dragged = True
        self.last_px = ev.pos()
        self.points.append(self.last_point)
        self._redraw()

    def canvasReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.RightButton:
            self.finish()
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if self.skipped:
            self.skipped = False
            return
        if not self.pressed:
            # a release whose press went to another tool, the same swap the
            # polygon tool guards against when a frame is placed
            return
        self.pressed = False
        if stroke_watch(self).running:
            stroke_watch(self).touch()
        if not self.dragged:
            self.points.append(self._map(ev))
        self.dragged = False
        self._redraw()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            stroke_dropped(self.section, stroke_watch(self), "line")
            self.discard()
        elif ev.key() == Qt.Key.Key_Backspace:
            keep_key(ev)
            if self.points:
                stroke_watch(self).touch()
                self.points.pop()
                self._redraw(self.last_point)
        elif ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish()

    def finish(self):
        """Two points are the least a line can be made of. One is a click that
        meant nothing, and turning it into a mark would put a blot of the
        current class on the ground for no reason."""
        pts = list(self.points)
        self.discard()
        if len(pts) < 2:
            stroke_dropped(self.section, stroke_watch(self), "line")
            return
        stroke_handed(self.section, stroke_watch(self), "line",
                      self.section.draw_line, pts)

    def discard(self):
        self.points = []
        self.pressed = False
        self.dragged = False
        self.band.reset(GEOM_LINE)

    def deactivate(self):
        self.discard()
        stroke_watch(self).drop()
        try:
            super().deactivate()
        except Exception:
            pass

    def isEditTool(self):
        return True


#  The brush
# =====================================================================
class BrushTool(QgsMapTool):
    """The outline does not close when the mouse is released: it closes when
    you come back to the starting point, marked by a circle.

    So a stretch can be traced, released, resumed, taken around a shrub, and
    closed only once back at the beginning. Outlines are long, and closing on
    release would force each one to be drawn in a single breath.

      drag                  freehand trace, one stretch at a time
      single click          one vertex
      back to the origin    closes
      right click / Enter   closes anyway, wherever the cursor is
      Backspace             removes the last vertex
      Esc                   discards the outline in progress
      Ctrl + click          gives the polygon under the cursor the current class
                            (in Correct: FROM is the class under the cursor)
      Shift + click         in Correct only: TO is the class under the cursor
    """

    def __init__(self, canvas, section):
        super().__init__(canvas)
        self.canvas = canvas
        self.section = section
        self.points = []
        self.pressed = False
        self.dragged = False
        self.last_px = None
        self.near_origin = False
        self.skipped = False
        self.first_of_stretch = None
        self.last_point = None
        self.band = QgsRubberBand(canvas, GEOM_POLYGON)
        self.band.setWidth(2)
        self.circle = QgsRubberBand(canvas, GEOM_POLYGON)
        self.circle.setWidth(2)
        self.circle.setLineStyle(Qt.PenStyle.DashLine)
        self.origin = QgsVertexMarker(canvas)
        self.origin.setIconType(QgsVertexMarker.IconType.ICON_CIRCLE)
        self.origin.setIconSize(14)
        self.origin.setPenWidth(3)
        self.origin.setVisible(False)

    # ----------------------------------------------------------- colour
    def refresh_colour(self):
        col = QColor(self.section.current_colour())
        self.band.setColor(col)
        fill = QColor(col)
        fill.setAlpha(70)
        self.band.setFillColor(fill)
        self.band.setWidth(3 if self.is_round() else 2)
        self.origin.setColor(col)
        self.circle.setColor(col)
        fill2 = QColor(col)
        fill2.setAlpha(55)
        self.circle.setFillColor(fill2)
        self.show_preview(self.last_point)

    # ----------------------------------------------------------- helpers
    def _map(self, ev):
        return self.toMapCoordinates(ev.pos())

    def is_round(self):
        return self.section.round_brush.isChecked()

    def _on_origin(self, pos):
        if len(self.points) < 3:
            return False
        p0 = self.toCanvasCoordinates(self.points[0])
        d = pos - QPoint(int(p0.x()), int(p0.y()))
        return d.manhattanLength() <= CLOSE_RADIUS_PX

    def _redraw(self, provisional=None):
        self.band.reset(GEOM_POLYGON)
        pts = self.points + ([provisional] if provisional else [])
        if len(pts) >= 2:
            self.band.setToGeometry(QgsGeometry.fromPolygonXY([pts + [pts[0]]]), None)
        if self.points:
            self.origin.setCenter(self.points[0])
            self.origin.setIconType(QgsVertexMarker.IconType.ICON_BOX if self.near_origin
                                    else QgsVertexMarker.IconType.ICON_CIRCLE)
            self.origin.setIconSize(20 if self.near_origin else 14)
            self.origin.setVisible(True)
        else:
            self.origin.setVisible(False)

    def _round_stroke(self):
        """The traced path becomes a strip twice the radius wide."""
        radius = self.section.radius.value()
        if len(self.points) == 1:
            g = QgsGeometry.fromPointXY(self.points[0])
        else:
            g = QgsGeometry.fromPolylineXY(self.points)
        return self.section.geometry.buffer(self._to_layer(g), radius, 12)

    def _to_layer(self, g):
        """The canvas may be in another system than the campaign."""
        view = self.canvas.mapSettings().destinationCrs()
        target = self.section.geometry.crs
        if view != target:
            g = QgsGeometry(g)
            g.transform(QgsCoordinateTransform(view, target, QgsProject.instance()))
        return g

    def show_preview(self, point):
        if point is not None:
            self.last_point = point
        self.circle.reset(GEOM_POLYGON)
        if point is None or not self.is_round():
            return
        g = self.section.geometry.buffer(
            self._to_layer(QgsGeometry.fromPointXY(point)),
            self.section.radius.value(), 16)
        view = self.canvas.mapSettings().destinationCrs()
        if view != self.section.geometry.crs:
            g.transform(QgsCoordinateTransform(self.section.geometry.crs, view,
                                               QgsProject.instance()))
        self.circle.setToGeometry(g, None)

    def _redraw_round(self):
        self.band.reset(GEOM_POLYGON)
        if self.points:
            g = self._round_stroke()
            view = self.canvas.mapSettings().destinationCrs()
            if view != self.section.geometry.crs:
                g = QgsGeometry(g)
                g.transform(QgsCoordinateTransform(self.section.geometry.crs, view,
                                                   QgsProject.instance()))
            self.band.setToGeometry(g, None)
        self.origin.setVisible(False)

    # ----------------------------------------------------------- events
    def canvasPressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if (ev.modifiers() & Qt.KeyboardModifier.ControlModifier) and not self.points:
            if self.section.reclassify_at(self._to_layer(
                    QgsGeometry.fromPointXY(self._map(ev))).asPoint()):
                self.skipped = True
                return
        # Shift and click picks the class a stroke writes, but only where the
        # section says it can: Correct does, by having the method. Annotate
        # does not, and there Shift held while drawing means "paints over",
        # read at the end of the stroke, so the press has to start an outline
        # as it always did.
        pick = getattr(self.section, "pick_into_at", None)
        if pick is not None and (ev.modifiers() & Qt.KeyboardModifier.ShiftModifier) \
                and not self.points:
            if pick(self._to_layer(
                    QgsGeometry.fromPointXY(self._map(ev))).asPoint()):
                self.skipped = True
                return
        self.skipped = False
        # the first press of a stroke starts its watch: every press of a
        # round brush, the first of an outline, which may take several
        if self.is_round() or not self.points:
            stroke_watch(self).begin()
        else:
            stroke_watch(self).touch()
        self.pressed = True
        self.dragged = False
        self.last_px = ev.pos()
        if self.is_round():
            self.points = [self._map(ev)]
            self._redraw_round()
            return
        self.first_of_stretch = self._map(ev)

    def canvasMoveEvent(self, ev):
        if stroke_watch(self).running:
            stroke_watch(self).touch()
        if self.is_round():
            self.show_preview(self._map(ev))
            if self.pressed and self.last_px is not None and \
                    (ev.pos() - self.last_px).manhattanLength() > STEP_PX:
                self.points.append(self._map(ev))
                self.last_px = ev.pos()
                self._redraw_round()
            return
        self.circle.reset(GEOM_POLYGON)
        if self.pressed:
            if self.last_px is not None and \
                    (ev.pos() - self.last_px).manhattanLength() > STEP_PX:
                if not self.dragged:
                    self.dragged = True
                    self.points.append(self.first_of_stretch)
                self.points.append(self._map(ev))
                self.last_px = ev.pos()
                self.near_origin = self._on_origin(ev.pos())
                self._redraw()
        elif self.points:
            self.near_origin = self._on_origin(ev.pos())
            self._redraw(self._map(ev))

    def canvasReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.RightButton:
            self.close_outline()
            return
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        if self.skipped:
            self.skipped = False
            return
        if not self.pressed:
            # A release whose press went to another tool. It happens the moment
            # a frame is placed: the frame tool hands the map back to the
            # polygon between the press and the release of the same click, and
            # without this the release would leave a stray vertex behind at the
            # middle of the frame that was just made.
            return
        if stroke_watch(self).running:
            stroke_watch(self).touch()
        if self.is_round():
            self.pressed = False
            if self.points:
                g = self._round_stroke()
                self.discard()
                stroke_handed(self.section, stroke_watch(self), "round",
                              self.section.paint, g)
            return
        self.pressed = False
        if not self.dragged:
            if self._on_origin(ev.pos()):
                self.close_outline()
                return
            self.points.append(self._map(ev))
        self.dragged = False
        if self._on_origin(ev.pos()):
            self.close_outline()
            return
        self.near_origin = False
        self._redraw()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            if self.points or self.pressed:
                stroke_dropped(self.section, stroke_watch(self),
                               "round" if self.is_round() else "brush")
            stroke_watch(self).drop()
            self.discard()
        elif ev.key() == Qt.Key.Key_Backspace:
            keep_key(ev)
            if self.points:
                stroke_watch(self).touch()
                self.points.pop()
                self._redraw()
        elif ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.close_outline()

    # ----------------------------------------------------------- actions
    def discard(self):
        self.points = []
        self.pressed = False
        self.dragged = False
        self.near_origin = False
        self.band.reset(GEOM_POLYGON)
        self.origin.setVisible(False)

    def close_outline(self):
        pts = list(self.points)
        self.discard()
        if len(pts) < 3:
            stroke_dropped(self.section, stroke_watch(self), "brush")
            return
        g = QgsGeometry.fromPolygonXY([pts + [pts[0]]])
        stroke_handed(self.section, stroke_watch(self), "brush",
                      self.section.paint, self._to_layer(g))

    def deactivate(self):
        self.discard()
        stroke_watch(self).drop()
        self.circle.reset(GEOM_POLYGON)
        super().deactivate()

    def isEditTool(self):
        return True


#  The tile tool
# =====================================================================
class PointTool(QgsMapTool):
    """Drops one point of the current class where you click.

    A point says "here there is one of these" without saying how far it
    extends. It is what you want for sampling, for counting, and for marking
    a place you will come back to, and it costs one click instead of an
    outline. Right click takes back the point under the cursor, Ctrl and click
    gives it the class you are holding."""

    def __init__(self, canvas_, section):
        super().__init__(canvas_)
        self.section = section
        self.mark = QgsVertexMarker(canvas_)
        self.mark.setIconType(QgsVertexMarker.IconType.ICON_CIRCLE)
        self.mark.setIconSize(14)
        self.mark.setPenWidth(3)
        self.refresh_colour()

    def refresh_colour(self):
        self.mark.setColor(QColor(self.section.current_colour()))

    def _layer_point(self, ev):
        point = self.toMapCoordinates(ev.pos())
        view = canvas().mapSettings().destinationCrs()
        target = self.section.geometry.crs
        if target.isValid() and view.isValid() and view != target:
            try:
                point = QgsCoordinateTransform(
                    view, target, QgsProject.instance()).transform(point)
            except Exception:
                pass
        return point

    def canvasMoveEvent(self, ev):
        self.mark.setCenter(self.toMapCoordinates(ev.pos()))

    def canvasPressEvent(self, ev):
        point = self._layer_point(ev)
        # a click is a stroke of no length: no watch, its time is the gap
        # before it, and a point refused is written as refused all the same
        if ev.button() == Qt.MouseButton.RightButton:
            stroke_handed(self.section, None, "point",
                          self.section.remove_point_at, point)
            return
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            stroke_handed(self.section, None, "point",
                          self.section.reclass_point_at, point)
            return
        stroke_handed(self.section, None, "point", self.section.drop_point,
                      point)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.section.use_brush()

    def deactivate(self):
        try:
            self.mark.setCenter(QgsPointXY(0, 0))
            self.mark.hide()
        except Exception:
            pass
        super().deactivate()

    def isEditTool(self):
        return True


class TileTool(QgsMapTool):
    """Directly on the map: click on empty ground creates a frame centred
    there, click inside one to pick it up. Dragging a frame somewhere else is
    a mode of its own, switched on with Move, and while it is on the pointer
    is a hand. Esc goes back to the brush."""

    def __init__(self, canvas, section):
        super().__init__(canvas)
        self.canvas = canvas
        self.section = section
        self.dragging = None
        self.start = None
        self.pressed_at = None          # where on screen the press landed
        self.others = []                # the other frames, read on the press
        self.band = QgsRubberBand(canvas, GEOM_POLYGON)
        self.band.setWidth(2)
        self.paint_band(False)
        self.show_mode()

    def paint_band(self, clash):
        """Yellow where the frame can go, red where it would lie over another
        frame. The move is refused on release in that case, and a band that
        turns red while it is still being dragged says so before the hand lets
        go, rather than after."""
        if clash:
            self.band.setColor(QColor("#e0281e"))
            self.band.setFillColor(QColor(224, 40, 30, 60))
        else:
            self.band.setColor(QColor("#ffdc00"))
            self.band.setFillColor(QColor(255, 220, 0, 40))

    def show_mode(self):
        """The pointer says which of the two things a drag will do.

        A cross places frames. An open hand means one can be dragged, and a
        closed one that it is being dragged right now. Nothing else in the
        panel has to be read to know which."""
        try:
            self.setCursor(Qt.CursorShape.OpenHandCursor
                           if self.section.can_move_frames()
                           else Qt.CursorShape.CrossCursor)
        except Exception:
            pass

    def activate(self):
        super().activate()
        self.show_mode()

    def _layer_point(self, ev):
        on_screen = self.toMapCoordinates(ev.pos())
        g = QgsGeometry.fromPointXY(on_screen)
        view = self.canvas.mapSettings().destinationCrs()
        target = self.section.geometry.crs
        if view != target:
            g.transform(QgsCoordinateTransform(view, target, QgsProject.instance()))
            log("click at %s in %s becomes %s in %s"
                % (on_screen.toString(2), crs_label(view),
                   g.asPoint().toString(2), crs_label(target)))
        return g.asPoint()

    def canvasPressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        p = self._layer_point(ev)
        hit = self.section.tile_at(p)
        if hit is None:
            log("empty ground at %s: creating a tile" % p.toString(2))
            stroke_handed(self.section, None, "frame",
                          self.section.create_tile, p)
            return
        log("tile %s selected" % hit["tile_id"])
        self.section.select_tile(hit["tile_id"])
        if not self.section.can_move_frames():
            # Picked up, not taken: without Move down a drag is just a click
            # that wandered, and the frame stays exactly where it is.
            return
        if not self.section.frames_locked(say=False):
            # A frame that holds somebody else's work, or another pass, does
            # not come off the ground at all. Said on the press: letting it be
            # dragged across the map and refusing only on release is the
            # program wasting the hand's time. move_tile asks again anyway.
            why = self.section.frame_refusal(hit["tile_id"], "moved")
            if why:
                self.section.refuse(why)
                return
        self.dragging = hit
        stroke_watch(self).begin()
        # Read once: the band asks at every movement of the mouse whether it
        # lies over another frame, and the table does not change in between.
        self.others = [f for f in self.section.all_tiles()
                       if f.id() != hit.id()]
        self.paint_band(False)
        self.start = p
        self.pressed_at = ev.pos()
        try:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        except Exception:
            pass

    def canvasMoveEvent(self, ev):
        if self.dragging is None:
            return
        stroke_watch(self).touch()
        p = self._layer_point(ev)
        g = QgsGeometry(self.dragging.geometry())
        g.translate(p.x() - self.start.x(), p.y() - self.start.y())
        # Before the frame is put back on the grid, which happens on release:
        # a fraction of a pixel either way, against an allowance of a
        # thousandth of one, and move_tile has the last word on the snapped
        # outline.
        self.paint_band(bool(self.section.frame_clash(g, among=self.others)))
        view = self.canvas.mapSettings().destinationCrs()
        if view != self.section.geometry.crs:
            g.transform(QgsCoordinateTransform(self.section.geometry.crs, view,
                                               QgsProject.instance()))
        self.band.setToGeometry(g, None)

    def canvasReleaseEvent(self, ev):
        if self.dragging is None:
            return
        p = self._layer_point(ev)
        dx, dy = p.x() - self.start.x(), p.y() - self.start.y()
        self.band.reset(GEOM_POLYGON)
        # A click meant to select a frame does not land on exactly the pixel it
        # started from: a hand moves, a mouse jitters, a trackpad drifts. With
        # the old test of "more than nothing", that sub pixel wobble asked
        # whether to move the frame and delete every polygon in it. A move is a
        # move when it is worth a few pixels on screen.
        moved = (ev.pos() - self.pressed_at).manhattanLength() \
            if self.pressed_at is not None else 0
        stroke_watch(self).touch()
        if moved > MOVE_PX and (abs(dx) > 0 or abs(dy) > 0):
            stroke_handed(self.section, stroke_watch(self), "frame",
                          self.section.move_tile, self.dragging, dx, dy)
        stroke_watch(self).drop()
        self.dragging = None
        self.pressed_at = None
        self.others = []
        self.paint_band(False)
        self.show_mode()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.section.use_brush()

    def deactivate(self):
        self.band.reset(GEOM_POLYGON)
        super().deactivate()

    def isEditTool(self):
        return True


class CutoutTool(QgsMapTool):
    """Click for a square of the chosen side, drag for a free rectangle."""

    # Under this many screen pixels of movement a press and a release are a
    # click, which cuts the square of the chosen side.
    CLICK_PX = 4

    def __init__(self, canvas_, section):
        super().__init__(canvas_)
        self.section = section
        self.origin = None
        self.pressed = None
        self.band = QgsRubberBand(canvas_, GEOM_POLYGON)
        self.band.setColor(QColor(20, 20, 20))
        self.band.setFillColor(QColor(255, 255, 255, 60))
        self.band.setWidth(2)

    def _map(self, ev):
        return self.toMapCoordinates(ev.pos())

    def canvasPressEvent(self, ev):
        if ev.button() == Qt.MouseButton.RightButton:
            self.section.undo()
            return
        self.origin = self._map(ev)
        self.pressed = (ev.pos().x(), ev.pos().y())

    def canvasMoveEvent(self, ev):
        point = self._map(ev)
        rect = QgsRectangle(self.origin, point) if self.origin is not None \
            else self.section.square_at(point)
        if self.origin is not None and (rect.width() <= 0 or rect.height() <= 0):
            rect = self.section.square_at(point)
        self.band.reset(GEOM_POLYGON)
        self.band.setToGeometry(QgsGeometry.fromRect(rect), None)

    def canvasReleaseEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        point = self._map(ev)
        rect = QgsRectangle(self.origin, point)
        self.origin = None
        nominal = None
        if self.is_click(ev, rect):
            # a click, not a drag: the square of the chosen side
            rect = self.section.square_at(point)
            nominal = self.section.side.value()
        self.band.reset(GEOM_POLYGON)
        self.section.export(rect, nominal=nominal)

    def is_click(self, ev, rect):
        """A click or a drag, told apart on the screen.

        It is not told by the area of the rectangle, which would be measured
        by the geometry of the annotation campaign: with no campaign open there
        is none, and free rectangles could not be cut at all. Pixels on the
        screen are the same in every system, and with or without a campaign."""
        if rect.width() < 1e-9 or rect.height() < 1e-9:
            return True
        if self.pressed is None:
            return False
        dx = abs(ev.pos().x() - self.pressed[0])
        dy = abs(ev.pos().y() - self.pressed[1])
        self.pressed = None
        return dx < self.CLICK_PX or dy < self.CLICK_PX

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.band.reset(GEOM_POLYGON)
            self.section.stop_cutting()

    def deactivate(self):
        self.band.reset(GEOM_POLYGON)
        super().deactivate()


#  The objects module
#
#  Detection, not segmentation. A box says "one of these is here", it does not
#  say where the thing ends, and two boxes may cover the same ground because
#  two objects can stand one behind the other. That is the whole difference
#  from the annotation module, and it is why the boxes live in their own table
#  and not among the polygons.
# =====================================================================
class BoxTool(QgsMapTool):
    """Drag on empty ground to draw a box, click one to pick it up.

    A picked box can be dragged by its middle and stretched by its corners,
    which is all the editing a rectangle ever needs. Ctrl and click gives the
    box under the cursor the class you are holding."""

    def __init__(self, canvas_, section):
        super().__init__(canvas_)
        self.section = section
        self.mode = None
        self.origin = None
        self.anchor = None
        self.start_rect = None
        self.pressed_at = None
        self.band = QgsRubberBand(canvas_, GEOM_POLYGON)
        self.band.setWidth(2)
        self.marks = QgsRubberBand(canvas_, GEOM_POLYGON)
        self.marks.setColor(QColor(255, 255, 255))
        self.marks.setFillColor(QColor(255, 255, 255, 30))
        self.marks.setWidth(3)
        self.refresh_colour()

    def refresh_colour(self):
        colour = QColor(self.section.current_colour())
        self.band.setColor(colour)
        faint = QColor(colour)
        faint.setAlpha(40)
        self.band.setFillColor(faint)

    # ----------------------------------------------------------- geometry
    def _layer_point(self, ev):
        point = self.toMapCoordinates(ev.pos())
        view = canvas().mapSettings().destinationCrs()
        target = self.section.geometry.crs
        if target.isValid() and view.isValid() and view != target:
            try:
                point = QgsCoordinateTransform(
                    view, target, QgsProject.instance()).transform(point)
            except Exception:
                pass
        return point

    def _on_screen(self, x, y):
        """Where a point of the campaign's coordinate system is on the screen,
        in pixels, or None if it cannot be put there.

        The campaign keeps its boxes in its own system and the canvas may be
        showing another, so the point is taken to the canvas system first,
        under the same condition _layer_point brings it back under, and then
        to pixels by the canvas itself. A pixel is a pixel whichever of the
        two systems is in degrees and whichever is in metres, which is the
        whole reason for measuring there."""
        point = QgsPointXY(x, y)
        view = canvas().mapSettings().destinationCrs()
        source = self.section.geometry.crs
        if source.isValid() and view.isValid() and view != source:
            try:
                point = QgsCoordinateTransform(
                    source, view, QgsProject.instance()).transform(point)
            except Exception:
                return None
        return canvas().getCoordinateTransform().transform(point)

    def _corner_grabbed(self, point):
        """Which corner of the picked box the cursor is on, if any. The reach
        is measured on screen, so it is the same however far you have zoomed.

        Except on a box that is small on screen. The reach is not the full
        HANDLE_PX whatever the size of the box: on a box twenty pixels wide
        the four corner squares would meet in the middle, leaving no ground
        to pick the box up by, so it could not be moved at all, and a plain
        click on its middle would take the bottom left corner and, on
        release, pull it to where the click was, cutting the box down to the
        quarter on the far side. So the reach is never more than a third of
        the shorter side, which always leaves a middle to grab, and never less
        than three pixels, so a corner can still be found on a box that has
        shrunk to a speck.

        Everything is compared in screen pixels: the click, the corners and
        the sides of the box, all put on the screen by _on_screen. Doing it in
        map units, with the box and the click in the campaign's system and the
        size of a pixel in the canvas's, is the same thing only while the two
        systems are. A campaign in degrees on a canvas in metres would make a
        two metre box a hundred thousandth of a "metre" wide, the reach would
        come out at three pixels' worth of metres read as degrees, larger than
        the box many times over, and every press would take a corner: the box
        could not be moved and a click would reshape it. The other way round
        the reach would shrink to nothing and no corner could be taken."""
        rect = self.section.selected_rect()
        if rect is None:
            return None
        here = self._on_screen(point.x(), point.y())
        low = self._on_screen(rect.xMinimum(), rect.yMinimum())
        right = self._on_screen(rect.xMaximum(), rect.yMinimum())
        up = self._on_screen(rect.xMinimum(), rect.yMaximum())
        if here is None or low is None or right is None or up is None:
            return None
        short_px = min(math.hypot(right.x() - low.x(), right.y() - low.y()),
                       math.hypot(up.x() - low.x(), up.y() - low.y()))
        reach = max(3.0, min(float(HANDLE_PX), short_px / 3.0))
        corners = ((rect.xMinimum(), rect.yMinimum()),
                   (rect.xMinimum(), rect.yMaximum()),
                   (rect.xMaximum(), rect.yMinimum()),
                   (rect.xMaximum(), rect.yMaximum()))
        for x, y in corners:
            at = self._on_screen(x, y)
            if at is None:
                continue
            if abs(here.x() - at.x()) <= reach and abs(here.y() - at.y()) <= reach:
                return QgsPointXY(rect.xMinimum() + rect.xMaximum() - x,
                                  rect.yMinimum() + rect.yMaximum() - y)
        return None

    def _show(self, rect):
        self.band.reset(GEOM_POLYGON)
        if rect is None:
            return
        g = QgsGeometry.fromRect(rect)
        view = canvas().mapSettings().destinationCrs()
        if view != self.section.geometry.crs:
            try:
                g.transform(QgsCoordinateTransform(self.section.geometry.crs,
                                                   view, QgsProject.instance()))
            except Exception:
                return
        self.band.setToGeometry(g, None)

    def show_selection(self):
        self.marks.reset(GEOM_POLYGON)
        rect = self.section.selected_rect()
        if rect is None:
            return
        g = QgsGeometry.fromRect(rect)
        view = canvas().mapSettings().destinationCrs()
        if view != self.section.geometry.crs:
            try:
                g.transform(QgsCoordinateTransform(self.section.geometry.crs,
                                                   view, QgsProject.instance()))
            except Exception:
                return
        self.marks.setToGeometry(g, None)

    # ----------------------------------------------------------- events
    def canvasPressEvent(self, ev):
        point = self._layer_point(ev)
        if ev.button() == Qt.MouseButton.RightButton:
            self.section.select_box(None)
            self.show_selection()
            return
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            stroke_handed(self.section, None, "box",
                          self.section.assign_class_at, point)
            return
        self.pressed_at = ev.pos()
        stroke_watch(self).begin()
        anchor = self._corner_grabbed(point)
        if anchor is not None:
            self.mode, self.anchor = "resize", anchor
            return
        hit = self.section.box_at(point)
        if hit is not None:
            self.section.select_box(hit.id())
            self.show_selection()
            self.mode = "move"
            self.origin = point
            self.start_rect = hit.geometry().boundingBox()
            return
        self.mode = "draw"
        self.origin = point

    def canvasMoveEvent(self, ev):
        if self.mode is None:
            return
        stroke_watch(self).touch()
        point = self._layer_point(ev)
        if self.mode == "draw":
            self._show(QgsRectangle(self.origin, point))
        elif self.mode == "resize":
            self._show(QgsRectangle(self.anchor, point))
        elif self.mode == "move":
            dx = point.x() - self.origin.x()
            dy = point.y() - self.origin.y()
            r = self.start_rect
            self._show(QgsRectangle(r.xMinimum() + dx, r.yMinimum() + dy,
                                    r.xMaximum() + dx, r.yMaximum() + dy))

    def canvasReleaseEvent(self, ev):
        if self.mode is None or ev.button() != Qt.MouseButton.LeftButton:
            return
        point = self._layer_point(ev)
        mode, self.mode = self.mode, None
        self.band.reset(GEOM_POLYGON)
        # The same wobble TileTool guards against: a click on a corner, or on
        # the middle, meant only to pick the box up, does not come back up on
        # the pixel it went down on. Without this a corner jumped to wherever
        # the hand had drifted, up to the whole reach of the handle, and the
        # box was reshaped by a click nobody meant as an edit. A stretch or a
        # move counts when it is worth a few pixels on screen.
        moved = (ev.pos() - self.pressed_at).manhattanLength() \
            if self.pressed_at is not None else MOVE_PX + 1
        self.pressed_at = None
        stroke_watch(self).touch()
        if mode == "draw":
            stroke_handed(self.section, stroke_watch(self), "box",
                          self.section.create_box,
                          QgsRectangle(self.origin, point))
        elif mode == "resize":
            if moved > MOVE_PX:
                stroke_handed(self.section, stroke_watch(self), "box",
                              self.section.reshape_box,
                              QgsRectangle(self.anchor, point))
        elif mode == "move":
            dx = point.x() - self.origin.x()
            dy = point.y() - self.origin.y()
            if moved > MOVE_PX and (abs(dx) > 0 or abs(dy) > 0):
                r = self.start_rect
                stroke_handed(self.section, stroke_watch(self), "box",
                              self.section.reshape_box,
                              QgsRectangle(r.xMinimum() + dx,
                                           r.yMinimum() + dy,
                                           r.xMaximum() + dx,
                                           r.yMaximum() + dy))
        stroke_watch(self).drop()
        self.show_selection()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            keep_key(ev)
            stroke_handed(self.section, None, "key",
                          self.section.delete_selected)
            self.show_selection()
        elif ev.key() == Qt.Key.Key_Escape:
            self.section.select_box(None)
            self.show_selection()

    def deactivate(self):
        self.band.reset(GEOM_POLYGON)
        self.marks.reset(GEOM_POLYGON)
        super().deactivate()

    def isEditTool(self):
        return True


#  Giving the map back
# =====================================================================
OWN_TOOLS = (LineTool, BrushTool, PointTool, TileTool, CutoutTool, BoxTool)
_PAN = []           # the pan tool made here, when QGIS has no action for it


def clear_bands(*tools):
    """Wipe what these tools drew on the canvas: the rubber bands and the
    marks they hold. A band is an item of the canvas and outlives the module
    that made it unless it is reset, and one left over from a stroke in the
    middle of being drawn would show on the map of a campaign already closed."""
    for tool in tools:
        if tool is None:
            continue
        for name, how in (("band", GEOM_POLYGON), ("circle", GEOM_POLYGON),
                          ("marks", GEOM_POLYGON)):
            band = getattr(tool, name, None)
            if band is None:
                continue
            try:
                band.reset(GEOM_LINE if tool_band_is_line(tool, name)
                           else how)
            except Exception:
                pass
        mark = getattr(tool, "mark", None)
        try:
            if mark is not None:
                mark.hide()
        except Exception:
            pass


def tool_band_is_line(tool, name):
    """Whether a band of this tool is a line: the line tool draws its
    trace as one."""
    return isinstance(tool, LineTool) and name == "band"


def tool_in_hand():
    """The map tool the canvas has now, or None when it cannot be told."""
    try:
        return canvas().mapTool()
    except Exception:
        return None


def hand_back_tool(before, mine):
    """Put the tool the person had back, when a module lets go of the map.

    unsetMapTool leaves the canvas with no tool at all: the pointer is an
    arrow that does nothing, and the way out is to find Pan in the toolbar.
    So when the tool in hand is one of this module's own (mine), the one that
    was in hand when the module opened takes its place, and Pan when there was
    none or it is gone or it is one of ours. A tool of anybody else's in hand
    is left alone: the person has picked it since. True when the canvas was
    given a tool."""
    current = tool_in_hand()
    if current is None or not any(current is t for t in mine if t is not None):
        return False
    target = before
    if target is not None and (current is target
                               or isinstance(target, OWN_TOOLS)
                               or not alive(target)):
        target = None
    try:
        if target is not None:
            canvas().setMapTool(target)
            return True
    except Exception as err:
        log("cannot give the map tool back: %s" % err)
    try:
        iface.actionPan().trigger()
        if tool_in_hand() is not current:
            return True
    except Exception:
        pass
    try:
        from qgis.gui import QgsMapToolPan
        if not _PAN:
            _PAN.append(QgsMapToolPan(canvas()))
        canvas().setMapTool(_PAN[0])
        return True
    except Exception as err:
        log("cannot hand the map to Pan: %s" % err)
    try:
        canvas().unsetMapTool(current)
    except Exception:
        pass
    return False

