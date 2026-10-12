"""A layer that edits like QGIS, geometry done by GEOS, and the real code on top.

The tests of the hand edit machinery used to be of two kinds: a model of the
rule written again in shapely, and a reading of the source text. Neither runs
settle_edits, give_back, save or move_tile themselves, and every one of the
regressions of the last weeks lived in the gap between the two: the rule was
right, the text was there, and the program did something else.

This kit closes the gap. It imports the package with QGIS faked, replaces the
three things the hand edits lean on, and borrows the methods of
AnnotationSection unchanged:

  QgsGeometry   a thin wrapper around shapely, which is GEOS, the library QGIS
                hands the arithmetic to. An intersection here is the real one.
  the layer     an edit buffer that behaves as QGIS's does where it matters:
                new features get negative ids, commit gives them new positive
                ones, changeGeometry fires geometryChanged synchronously, the
                undo stack counts commands.
  QTimer        a queue. settle_edits is scheduled the way QGIS schedules it,
                after the signal, and a test says when the event loop runs.

What is NOT real: the widgets are plain objects with the state the methods
read, and the message bar is a list of what was said.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness_imports                                             # noqa: E402
harness_imports            # it builds the fakes on import

import enum                                                        # noqa: E402


class _Qgis(object):
    """Qgis, as far as the message levels go, and as PyQt6 has them: an enum
    that is not an int. Put in before the package is imported, so LEVEL_INFO
    and its siblings are these members and the message bar below can refuse
    the bare number PyQt6 refuses. The bar used to take anything, and
    pushWidget(bar, 0) in Whole passed every suite and failed on QGIS 4."""
    class MessageLevel(enum.Enum):
        Info = 0
        Warning = 1
        Critical = 2
        Success = 3


sys.modules["qgis.core"].Qgis = _Qgis

from shapely.geometry import box                                  # noqa: E402
from shapely.ops import unary_union                               # noqa: E402
from shapely.validation import make_valid                         # noqa: E402

from rasterlabel import geometry as GEO                           # noqa: E402
from rasterlabel import sections_annotate as SA                   # noqa: E402

POLY = "polygon-type"
GEO.GEOM_POLYGON = POLY


# ------------------------------------------------------------------ geometry
class Box(object):
    """QgsRectangle, and what boundingBox() hands back."""
    def __init__(self, *b):
        self.b = tuple(b[0]) if len(b) == 1 else tuple(b)
    def xMinimum(self): return self.b[0]
    def yMinimum(self): return self.b[1]
    def xMaximum(self): return self.b[2]
    def yMaximum(self): return self.b[3]
    def width(self): return self.b[2] - self.b[0]
    def height(self): return self.b[3] - self.b[1]
    def area(self): return self.width() * self.height()

    def intersects(self, other):
        a, o = self.b, other.b
        return not (a[2] < o[0] or o[2] < a[0] or a[3] < o[1] or o[3] < a[1])


class Abstract(object):
    """What QgsGeometry.constGet() hands back: the geometry underneath, which
    has boundary() where the QgsGeometry wrapping it has none."""
    def __init__(self, shape):
        self.s = shape

    def boundary(self): return Abstract(self.s.boundary)


class G(object):
    """QgsGeometry, as far as the hand edits use it, done by GEOS. A GEOS
    error comes back as a null geometry, which is what QGIS does. It has no
    boundary() either, as QgsGeometry has none: constGet() has."""

    def __init__(self, shape=None):
        if isinstance(shape, (G, Abstract)):
            shape = shape.s
        self.s = shape

    def _wrap(self, fn):
        try:
            return G(fn())
        except Exception:
            return G(None)

    def isNull(self): return self.s is None
    def isEmpty(self): return self.s is None or self.s.is_empty
    def area(self): return 0.0 if self.s is None else self.s.area
    def length(self): return 0.0 if self.s is None else self.s.length
    def boundingBox(self): return Box(self.s.bounds)
    def isGeosValid(self, *a): return self.s is not None and self.s.is_valid
    def isMultipart(self): return self.s is not None and hasattr(self.s, "geoms")

    def type(self):
        if self.s is not None and self.s.geom_type in ("Polygon", "MultiPolygon"):
            return POLY
        return "other"

    def asGeometryCollection(self):
        return [G(p) for p in getattr(self.s, "geoms", [self.s])]

    def intersects(self, other):
        try:
            return self.s.intersects(other.s)
        except Exception:
            return False

    def contains(self, other):
        try:
            return self.s.contains(other.s)
        except Exception:
            return False

    def intersection(self, other): return self._wrap(lambda: self.s.intersection(other.s))
    def difference(self, other): return self._wrap(lambda: self.s.difference(other.s))
    def combine(self, other): return self._wrap(lambda: self.s.union(other.s))
    def constGet(self): return None if self.s is None else Abstract(self.s)
    def makeValid(self): return self._wrap(lambda: make_valid(self.s))
    def buffer(self, d, seg=8): return self._wrap(lambda: self.s.buffer(d, seg))

    def translate(self, dx, dy):
        from shapely import affinity
        self.s = affinity.translate(self.s, dx, dy)
        return 0

    @staticmethod
    def fromRect(r):
        return G(box(r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()))

    @staticmethod
    def fromPointXY(p):
        from shapely.geometry import Point
        return G(Point(p.x(), p.y()))

    def asPoint(self):
        return Pt(self.s.x, self.s.y)

    @staticmethod
    def unaryUnion(geoms):
        try:
            return G(unary_union([g.s for g in geoms if g.s is not None]))
        except Exception:
            return G(None)


# ------------------------------------------------------------ features, layer
class Signal(object):
    def __init__(self): self.slots = []
    def connect(self, slot): self.slots.append(slot)
    def disconnect(self, slot): self.slots.remove(slot)
    def emit(self, *a):
        for s in list(self.slots):
            s(*a)


class Field(object):
    def __init__(self, n): self._n = n
    def name(self): return self._n


class Fields(list):
    def names(self): return [f.name() for f in self]
    def indexOf(self, n):
        for i, f in enumerate(self):
            if f.name() == n:
                return i
        return -1


FIELDS = ["class_name", "class_code", "tile_id", "pass_no", "operator",
          "created"]


class Feature(object):
    def __init__(self, fields=None, fid=None, geom=None, **values):
        self._fields = fields if isinstance(fields, Fields) else Fields(
            Field(n) for n in FIELDS)
        self._id = fid
        self._g = G(geom) if geom is not None else G(None)
        self.values = dict(values)

    def id(self): return self._id
    def isValid(self): return self._id is not None
    def fields(self): return self._fields
    def geometry(self): return G(self._g.s)
    def hasGeometry(self): return not self._g.isEmpty()
    def setGeometry(self, g): self._g = G(g.s if isinstance(g, G) else g)
    def __getitem__(self, k): return self.values.get(k)
    def __setitem__(self, k, v): self.values[k] = v

    def copy(self):
        f = Feature(self._fields, self._id, None, **self.values)
        f._g = G(self._g.s)
        return f


class Request(object):
    def __init__(self): self.fids = None
    def setFilterFids(self, fids):
        self.fids = set(fids)
        return self
    def setFilterRect(self, r): return self


class Stack(object):
    """QUndoStack, as QGIS drives it: a push drops what could be redone and adds
    one command; undo and redo move the index and leave the count alone. Undo
    replays the command backwards, and the geometryChanged it fires arrives
    BEFORE indexChanged, which is the order QUndoStack keeps."""

    def __init__(self, layer):
        self.layer = layer
        self.commands = []
        self._index = 0
        self.indexChanged = Signal()

    def count(self): return len(self.commands)
    def index(self): return self._index
    def canUndo(self): return self._index > 0
    def canRedo(self): return self._index < len(self.commands)

    def push(self, ops):
        del self.commands[self._index:]
        self.commands.append(list(ops))
        self._index = len(self.commands)
        self.indexChanged.emit(self._index)

    def undo(self):
        if not self.canUndo():
            return
        ops = self.commands[self._index - 1]
        self._index -= 1
        for op in reversed(ops):
            self.layer._revert(op)
        self.indexChanged.emit(self._index)

    def clear(self):
        """What a commit or a rollback does to the stack in QGIS: the same
        object, emptied, and indexChanged(0) said."""
        self.commands = []
        self._index = 0
        self.indexChanged.emit(0)

    def redo(self):
        if not self.canRedo():
            return
        ops = self.commands[self._index]
        self._index += 1
        for op in ops:
            self.layer._apply(op)
        self.indexChanged.emit(self._index)


class Layer(object):
    _next_new = -1                    # QGIS: one global low water mark
    _ids = 0

    def __init__(self, name="polygons"):
        Layer._ids += 1
        self._name = name
        self._id = "%s_%d" % (name, Layer._ids)
        self.fields_ = Fields(Field(n) for n in FIELDS)
        self.saved = {}               # fid -> Feature, what is on disk
        self.buffer = None            # the edit session, or None
        self.next_disk = 1
        self.geometryChanged = Signal()
        self.dataChanged = Signal()
        self.editCommandStarted = Signal()
        self.editCommandEnded = Signal()
        self.editCommandDestroyed = Signal()
        self.afterCommitChanges = Signal()
        self.afterRollBack = Signal()
        self.stack = Stack(self)
        self.open_command = None      # the ops of the command being built
        self.commit_ok = True

    # the shape of the API
    def id(self): return self._id
    def name(self): return self._name
    def fields(self): return self.fields_
    def isEditable(self): return self.buffer is not None
    def isModified(self): return self.buffer is not None and self.buffer != self.saved
    def triggerRepaint(self): pass
    def updateExtents(self): pass
    def undoStack(self): return self.stack
    def subsetString(self): return ""
    def commitErrors(self): return ["refused"]

    def startEditing(self):
        if self.buffer is None:
            self.buffer = {k: v.copy() for k, v in self.saved.items()}
        return True

    def rollBack(self):
        self.buffer = None
        self.stack.clear()
        self.afterRollBack.emit()
        return True

    def commitChanges(self):
        if self.buffer is None:
            return True
        if not self.commit_ok:
            return False
        out = {}
        for fid in sorted(self.buffer, key=lambda k: (k < 0, abs(k))):
            f = self.buffer[fid].copy()
            if fid < 0:
                f._id = self.next_disk
                self.next_disk += 1
            else:
                self.next_disk = max(self.next_disk, fid + 1)
            out[f._id] = f
        self.saved = out
        self.buffer = None
        self.stack.clear()
        self.afterCommitChanges.emit()
        return True

    def _rows(self):
        return self.buffer if self.buffer is not None else self.saved

    def getFeatures(self, request=None):
        rows = self._rows()
        for fid in sorted(rows, key=lambda k: (k < 0, abs(k))):
            if request is not None and request.fids is not None \
                    and fid not in request.fids:
                continue
            yield rows[fid].copy()

    def getFeature(self, fid):
        f = self._rows().get(fid)
        return f.copy() if f is not None else Feature(self.fields_)

    def featureCount(self): return len(self._rows())

    # ----------------------------------------------------- the undo machinery
    def _record(self, op):
        if self.open_command is not None:
            self.open_command.append(op)
        else:
            self.stack.push([op])

    def _apply(self, op):
        kind = op[0]
        if kind == "geom":
            _, fid, old, new = op
            self.buffer[fid].setGeometry(G(new))
            self.geometryChanged.emit(fid, G(new))
        elif kind == "add":
            self.buffer[op[1]] = op[2].copy()
        elif kind == "del":
            self.buffer.pop(op[1], None)
        elif kind == "attr":
            _, fid, name, old, new = op
            self.buffer[fid].values[name] = new

    def _revert(self, op):
        kind = op[0]
        if kind == "geom":
            _, fid, old, new = op
            self.buffer[fid].setGeometry(G(old))
            self.geometryChanged.emit(fid, G(old))
        elif kind == "add":
            self.buffer.pop(op[1], None)
        elif kind == "del":
            self.buffer[op[1]] = op[2].copy()
        elif kind == "attr":
            _, fid, name, old, new = op
            self.buffer[fid].values[name] = old

    def beginEditCommand(self, text):
        self.open_command = []
        self.editCommandStarted.emit(text)

    def endEditCommand(self):
        ops, self.open_command = self.open_command, None
        if ops:
            self.stack.push(ops)
        self.editCommandEnded.emit()

    def destroyEditCommand(self):
        ops, self.open_command = self.open_command or [], None
        for op in reversed(ops):
            self._revert(op)
        self.editCommandDestroyed.emit()

    # edits
    def addFeature(self, f):
        assert self.buffer is not None, "addFeature outside an edit session"
        new = f.copy()
        new._id = Layer._next_new
        Layer._next_new -= 1
        self.buffer[new._id] = new
        self._record(("add", new._id, new.copy()))
        return True

    def changeGeometry(self, fid, g):
        assert self.buffer is not None, "changeGeometry outside an edit session"
        if fid not in self.buffer:
            return False
        old = self.buffer[fid]._g.s
        new = g.s if isinstance(g, G) else g
        self.buffer[fid].setGeometry(G(new))
        self._record(("geom", fid, old, new))
        self.geometryChanged.emit(fid, G(new))
        return True

    def changeAttributeValue(self, fid, index, value):
        name = self.fields_[index].name()
        old = self.buffer[fid].values.get(name)
        self.buffer[fid].values[name] = value
        self._record(("attr", fid, name, old, value))
        return True

    def deleteFeature(self, fid):
        f = self.buffer.pop(fid, None)
        if f is not None:
            self._record(("del", fid, f.copy()))
        return True

    def deleteFeatures(self, fids):
        ops = []
        for fid in fids:
            f = self.buffer.pop(fid, None)
            if f is not None:
                ops.append(("del", fid, f.copy()))
        if ops:
            if self.open_command is not None:
                self.open_command.extend(ops)
            else:
                self.stack.push(ops)
        return True

    # what the vertex tool does: a new outline, inside one edit command
    def drag(self, fid, shape):
        self.beginEditCommand("Moved vertex")
        self.changeGeometry(fid, G(shape))
        self.endEditCommand()


# ------------------------------------------------------------- the event loop
class Loop(object):
    """QTimer.singleShot(0, fn) runs fn after the current event, not inside it."""
    queue = []

    @staticmethod
    def singleShot(ms, fn):
        Loop.queue.append(fn)

    @staticmethod
    def run():
        n = 0
        while Loop.queue:
            fn = Loop.queue.pop(0)
            fn()
            n += 1
            assert n < 1000, "the event loop does not settle"


def _level_of(level):
    """A message level as PyQt6 takes it: the enum, never a bare number."""
    if level is not None and not isinstance(level, _Qgis.MessageLevel):
        raise TypeError("argument 'level' has unexpected type '%s'"
                        % type(level).__name__)


class Bar(object):
    said = []

    def pushMessage(self, *a, **k):
        _level_of(k.get("level", a[2] if len(a) > 2 else None))
        Bar.said.append(" ".join(str(x) for x in a))

    def createMessage(self, *a, **k): return None

    def pushWidget(self, widget, level=None, duration=0):
        _level_of(level)

    def popWidget(self, *a, **k): pass


class Iface(object):
    def messageBar(self): return Bar()
    def setActiveLayer(self, l): pass
    def layerTreeView(self): raise RuntimeError("no tree")


class Pt(object):
    def __init__(self, x, y): self._x, self._y = x, y
    def x(self): return self._x
    def y(self): return self._y


def _raise(err, what, parent=None):
    """The error window would block a test: the error goes up instead."""
    raise err


from rasterlabel import errors as _E                              # noqa: E402
_E.trouble = _raise

SA.QgsGeometry = G
SA.QgsRectangle = Box
SA.QgsPointXY = Pt
GEO.QgsGeometry = G
GEO.QgsRectangle = Box
SA.QgsFeature = Feature
SA.QgsFeatureRequest = Request
SA.QTimer = Loop
SA.iface = Iface()


# --------------------------------------------------------------- the section
class Tick(object):
    def __init__(self, on): self.on = on
    def isChecked(self): return self.on
    def setChecked(self, v): self.on = bool(v)
    def blockSignals(self, v): return False


class Spin(object):
    def __init__(self, v): self.v = v
    def value(self): return self.v


class Combo(object):
    def __init__(self, text): self.text = text
    def currentText(self): return self.text


class Measure(object):
    def measureArea(self, g): return g.area()
    def measureLength(self, g): return g.length()
    def measureLine(self, a, b):
        return ((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5


def make_geometry(px=1.0):
    g = GEO.Geometry.__new__(GEO.Geometry)
    g.pixel_crs = (px, px)
    g.pixel_m = (px, px)
    g.min_area_flat = 4 * px * px
    g.measure = Measure()
    g.origin = (0.0, 10.0)
    return g


class Panel(object):
    def __init__(self): self.safe = 0
    def keep_safe(self): self.safe += 1


BORROW = ("settle_edits", "give_back", "untangle", "cut_away",
          "remember_shapes", "note_geometry_change", "scope_polygons",
          "all_polygons", "operator_name", "new_feature", "code_of", "save",
          "unsaved", "measure_all_tiles", "measure_tile", "repair",
          "tables_of_tile", "move_tile", "_carry_or_drop", "ticked",
          "marks_locked", "frames_locked", "watch_geometry_edits",
          "add_merging", "paint", "undo_stroke", "reading_of",
          "frame_geometry", "piece_of", "command_is",
          "locks_changed", "hold_marks", "remember_after_replay",
          "delete_tile", "stack_moved", "rebase_lock", "watch_stacks",
          "LOCKED_ROLES", "watch_point_moves", "point_command_is",
          "note_point_move", "check_point_moves", "point_size_of",
          "frame_clash", "pass_of", "foreign_work", "frame_refusal", "refuse",
          "hiding", "create_tile", "frame_event", "table_back",
          "watched_tables", "rewatch_layers", "layers_came", "rewatch_due",
          "suppress_forms", "let_go", "merging", "merge_joined",
          "_joined_with", "_merge_group", "rows_near", "add_piece",
          "draw_rank")


class Host(object):
    """An AnnotationSection with its methods and without its widgets."""
    OPERATOR_BLANK = SA.AnnotationSection.OPERATOR_BLANK
    tidy_operator = staticmethod(SA.AnnotationSection.tidy_operator)
    operator_of = staticmethod(SA.AnnotationSection.operator_of)

    def __init__(self, polygons, tiles=None, tile_id="t001", operator="OP1",
                 pass_no=1, px=1.0):
        self.layers = {"polygons": polygons, "tiles": tiles}
        self.tiled = tiles is not None
        self._tile = tile_id
        self.geometry = make_geometry(px)
        self.campaign = type("C", (), {})()
        self.campaign.data = {"id": "x", "classes": [
            {"name": "a", "code": 1}, {"name": "b", "code": 2},
            {"name": "c", "code": 3}]}
        self.campaign.active_classes = lambda: self.campaign.data["classes"]
        self.panel = Panel()
        self.operator = Combo(operator)
        self.pass_no = Spin(pass_no)
        self.by_operator = Tick(True)
        self.blind = Tick(False)
        self.settle_edits_on = Tick(True)
        self.lock_marks = Tick(False)
        self.lock_frames = Tick(False)
        self.autosave = Spin(0)
        self.class_name = "a"
        self.since_save = 0
        self._settling = False
        self._to_settle = set()
        self._shapes = {}
        self._watching = None
        self.coverage_refreshed = 0
        # the real wiring, signals and all
        self.watch_geometry_edits()

    def layer(self, role): return self.layers.get(role)

    @property
    def polygons(self): return self.layers["polygons"]

    @property
    def tile_layer(self): return self.layers["tiles"]

    def current_tile_id(self): return self._tile if self.tiled else None

    def tile_geometry(self):
        return self.frame_geometry(self._tile)

    def all_tiles(self):
        t = self.tile_layer
        return [] if t is None else list(t.getFeatures())

    def refresh_coverage(self, *a): self.coverage_refreshed += 1
    def show_blind(self): pass
    def apply_filter(self, *a): pass
    def under_mode(self): return False


for _name in BORROW:
    if _name in SA.AnnotationSection.__dict__:      # a test asks for the rest
        setattr(Host, _name, SA.AnnotationSection.__dict__[_name])


def put(layer, shape, **values):
    """A polygon already saved on disk, with the next disk id."""
    f = Feature(layer.fields(), layer.next_disk, shape, **values)
    layer.saved[f._id] = f
    layer.next_disk += 1
    return f._id


def shape_of(layer, fid):
    f = layer._rows().get(fid)
    return None if f is None else f._g.s


def overlap_area(layer, ids=None, scope=None):
    """The largest area two polygons of the layer share."""
    rows = [f for f in layer.getFeatures() if scope is None or scope(f)]
    worst = 0.0
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i]._g.s, rows[j]._g.s
            if a is None or b is None:
                continue
            worst = max(worst, a.intersection(b).area)
    return worst


def covered(layer, frame, scope=None):
    shapes = [f._g.s for f in layer.getFeatures()
              if f._g.s is not None and (scope is None or scope(f))]
    return unary_union(shapes).intersection(frame).area if shapes else 0.0
